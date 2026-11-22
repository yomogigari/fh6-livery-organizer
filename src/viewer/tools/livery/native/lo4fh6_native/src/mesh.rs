//! 車体の変換の、メッシュ 1 つ分の数値の処理（2026-11-21）。
//!
//! tools/livery/independent_chassis の次の処理を、同じ順の計算で 1 回で行う（Python から呼ぶ入口は
//! tools/livery/native_mesh_geometry.py）。
//! - modelbin_geometry_decoder.extract_raw_geometry：頂点の解読（位置・法線・UV・色。対応する形式も同じ）
//! - source_skeleton_pose.transform_source_geometry：骨と配置の行列、法線の逆転置、X の反転
//! - source_surface_stage.source_uv_affine：UV の拡大・ずらし
//! - source_static_preview_selection.clean_original_static_triangle_indices：つぶれた・重なった三角形を除き、巻き方向を (A,C,B) に
//! - source_stock_glb._Writer.append：GLB の番号の幅（頂点が 65536 未満なら 16 ビット）と、位置・番号の最小・最大
//! 少しでも想定外なら 0 以外を返す。呼び出し側は、そのメッシュを今までの Python の処理で作る（例外と文言は Python が出す）。
//! 出来上がりは、バイトや画素まで同じでなくてよいとする（目で見て同じ程度。2026-11-21）。それでも、計算の順と
//! 32 ビットの小数の丸めは numpy と同じにしてある（違いは行列の積の足し算の順などで、最後の桁がまれにずれる程度）。

use alloc::vec;
use alloc::vec::Vec;
use core::arch::x86_64::{_mm_cvtsd_f64, _mm_cvtss_f32, _mm_set_sd, _mm_set_ss, _mm_setzero_pd, _mm_sqrt_sd, _mm_sqrt_ss};

const SEM_POSITION: u32 = 0;
const SEM_NORMAL: u32 = 1;
const SEM_TEXCOORD: u32 = 2;
const SEM_COLOR: u32 = 3;
const MAX_VERTICES: u64 = 2_000_000;
const MAX_INDICES: u64 = 20_000_000;
const UV_CHANNELS: usize = 5;
/// 出力の先頭の見出しの大きさ（MeshOutput の並び）。
pub const HEADER_SIZE: usize = 64;
const MAGIC: u32 = 0x474D_4F4C; // "LOMG"
/// 静止の部品の三角形の整理（clean_original_static_triangle_indices）を行う。これ以外の使い方は扱わない。
const FLAG_STATIC_CLEAN: u32 = 1;

/// 頂点の要素 1 つ（VLay の要素と、それを読む VerB）。
#[repr(C)]
pub struct MeshElement {
    pub semantic: u32,
    pub semantic_index: i32,
    pub format: u32,
    pub stride: u32,
    /// VerB の中の位置（16 ＋ usage の位置 ＋ vertex_offset × stride ＋ 要素の位置）。最小の番号 × stride は足していない。
    pub base: i64,
    pub buffer_offset: u64,
    pub buffer_length: u64,
}

/// メッシュ 1 つ分の入力。
#[repr(C)]
pub struct MeshParams {
    /// ModelBin の中の、このメッシュの最初の番号の位置と、番号の数・幅（2 か 4）。
    pub index_offset: u64,
    pub index_count: u64,
    pub index_width: u32,
    pub flags: u32,
    /// Mesh の PositionScale と PositionTranslate（原本の 32 ビットの値）。
    pub scale: [f32; 4],
    pub translate: [f32; 4],
    /// 骨の世界の行列と、配置の行列（4×4、行の順。Python の numpy の配列と同じ並び）。
    pub bone: [f64; 16],
    pub instance: [f64; 16],
    /// UV の 5 組の (offsetU, scaleU, offsetV, scaleV)。
    pub uv_affine: [f64; 20],
}

fn sqrt32(x: f32) -> f32 {
    // SSE の平方根は IEEE の正しい丸め（numpy の sqrt と同じ値）。x86_64 では SSE2 は必ずある。
    unsafe { _mm_cvtss_f32(_mm_sqrt_ss(_mm_set_ss(x))) }
}

fn sqrt64(x: f64) -> f64 {
    unsafe { _mm_cvtsd_f64(_mm_sqrt_sd(_mm_setzero_pd(), _mm_set_sd(x))) }
}

fn abs64(x: f64) -> f64 {
    f64::from_bits(x.to_bits() & 0x7fff_ffff_ffff_ffff)
}

fn clip_unit(x: f32) -> f32 {
    // np.clip(x, -1., 1.)
    if x < -1.0 {
        -1.0
    } else if x > 1.0 {
        1.0
    } else {
        x
    }
}

fn half_to_f32(h: u16) -> f32 {
    let sign = ((h as u32) & 0x8000) << 16;
    let exponent = ((h >> 10) & 0x1f) as u32;
    let mantissa = (h & 0x3ff) as u32;
    let bits = if exponent == 0 {
        if mantissa == 0 {
            sign
        } else {
            // 非正規化数：仮数を正規化する（値は 2^-24 × mantissa でちょうど表せる）。
            let mut e: i32 = -14;
            let mut m = mantissa;
            while m & 0x400 == 0 {
                m <<= 1;
                e -= 1;
            }
            sign | (((e + 127) as u32) << 23) | ((m & 0x3ff) << 13)
        }
    } else if exponent == 31 {
        sign | 0x7f80_0000 | (mantissa << 13)
    } else {
        sign | ((exponent + 112) << 23) | (mantissa << 13)
    };
    f32::from_bits(bits)
}

fn bytes2(raw: &[u8], at: usize) -> [u8; 2] {
    [raw[at], raw[at + 1]]
}

fn bytes4(raw: &[u8], at: usize) -> [u8; 4] {
    [raw[at], raw[at + 1], raw[at + 2], raw[at + 3]]
}

fn format_bytes(format: u32) -> Option<usize> {
    // modelbin_geometry_decoder.FORMAT_BYTES
    match format {
        2 => Some(16),
        6 => Some(12),
        10 => Some(8),
        13 => Some(8),
        16 => Some(8),
        24 => Some(4),
        28 => Some(4),
        35 => Some(4),
        37 => Some(4),
        _ => None,
    }
}

/// 3 つの成分ごとに、長さで割る（numpy の np.linalg.norm と np.maximum(長さ, 1e-15) を 32 ビットで）。
fn normalize32(values: &mut [f32]) {
    let floor = 1.0e-15f64 as f32;
    for v in values.chunks_exact_mut(3) {
        let length = sqrt32((v[0] * v[0] + v[1] * v[1]) + v[2] * v[2]);
        let d = if length >= floor { length } else { floor };
        v[0] /= d;
        v[1] /= d;
        v[2] /= d;
    }
}

fn all_finite(values: &[f32]) -> bool {
    values.iter().all(|v| v.is_finite())
}

fn matmul4(a: &[f64; 16], b: &[f64; 16]) -> [f64; 16] {
    let mut out = [0.0f64; 16];
    for i in 0..4 {
        for j in 0..4 {
            out[i * 4 + j] = ((a[i * 4] * b[j] + a[i * 4 + 1] * b[4 + j]) + a[i * 4 + 2] * b[8 + j]) + a[i * 4 + 3] * b[12 + j];
        }
    }
    out
}

fn det3(m: &[f64; 16]) -> f64 {
    let (a, b, c) = (m[0], m[1], m[2]);
    let (d, e, f) = (m[4], m[5], m[6]);
    let (g, h, i) = (m[8], m[9], m[10]);
    a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
}

/// 左上の 3×3 の逆行列（行の順）。
fn inverse3(m: &[f64; 16], det: f64) -> [f64; 9] {
    let (a, b, c) = (m[0], m[1], m[2]);
    let (d, e, f) = (m[4], m[5], m[6]);
    let (g, h, i) = (m[8], m[9], m[10]);
    [
        (e * i - f * h) / det,
        (c * h - b * i) / det,
        (b * f - c * e) / det,
        (f * g - d * i) / det,
        (a * i - c * g) / det,
        (c * d - a * f) / det,
        (d * h - e * g) / det,
        (b * g - a * h) / det,
        (a * e - b * d) / det,
    ]
}

struct Decoded {
    positions: Vec<f32>,
    normals: Option<Vec<f32>>,
    uvs: [Option<Vec<f32>>; UV_CHANNELS],
}

/// 頂点を解読する（extract_raw_geometry と同じ形式・同じ 32 ビットの計算）。エラーは番号で返す。
fn decode_vertices(raw: &[u8], elements: &[MeshElement], params: &MeshParams, imin: u64, n: usize) -> Result<Decoded, i32> {
    let mut positions: Option<Vec<f32>> = None;
    let mut position_w: Option<Vec<f32>> = None;
    let mut normals: Option<Vec<f32>> = None;
    let mut uvs: [Option<Vec<f32>>; UV_CHANNELS] = [None, None, None, None, None];
    let scaled = params.scale[0] != 0.0 || params.scale[1] != 0.0 || params.scale[2] != 0.0;
    for element in elements {
        let row = format_bytes(element.format).ok_or(5)?;
        if element.stride == 0 {
            return Err(4);
        }
        let stride = element.stride as i64;
        let address = element.base.checked_add((imin as i64).checked_mul(stride).ok_or(4)?).ok_or(4)?;
        let last = address
            .checked_add((n as i64 - 1).checked_mul(stride).ok_or(4)?)
            .and_then(|v| v.checked_add(row as i64))
            .ok_or(4)?;
        if address < 16 || last > element.buffer_length as i64 {
            return Err(4);
        }
        let start = element.buffer_offset.checked_add(address as u64).ok_or(4)? as usize;
        let end = element.buffer_offset.checked_add(last as u64).ok_or(4)? as usize;
        if end > raw.len() {
            return Err(4);
        }
        let step = element.stride as usize;
        let at = |k: usize| start + k * step;
        match (element.semantic, element.format) {
            (SEM_POSITION, 13) => {
                let mut xyz = vec![0.0f32; n * 3];
                let mut w = vec![0.0f32; n];
                for k in 0..n {
                    let p = at(k);
                    let mut q = [0.0f32; 4];
                    for (c, value) in q.iter_mut().enumerate() {
                        *value = clip_unit((i16::from_le_bytes(bytes2(raw, p + 2 * c)) as f32) / 32767.0f32);
                    }
                    for c in 0..3 {
                        xyz[k * 3 + c] = if scaled { q[c] * params.scale[c] + params.translate[c] } else { q[c] };
                    }
                    w[k] = q[3];
                }
                if element.semantic_index == 0 {
                    positions = Some(xyz);
                } else if !all_finite(&xyz) {
                    return Err(7);
                }
                position_w = Some(w);
            }
            (SEM_POSITION, 6) => {
                let mut xyz = vec![0.0f32; n * 3];
                for k in 0..n {
                    let p = at(k);
                    for c in 0..3 {
                        xyz[k * 3 + c] = f32::from_le_bytes(bytes4(raw, p + 4 * c));
                    }
                }
                if !all_finite(&xyz) {
                    return Err(7);
                }
                if element.semantic_index == 0 {
                    positions = Some(xyz);
                }
                position_w = Some(vec![1.0f32; n]);
            }
            (SEM_NORMAL, 37) => {
                let w = position_w.as_ref().ok_or(10)?;
                let mut out = vec![0.0f32; n * 3];
                for k in 0..n {
                    let p = at(k);
                    out[k * 3] = w[k];
                    for c in 0..2 {
                        out[k * 3 + 1 + c] = clip_unit((i16::from_le_bytes(bytes2(raw, p + 2 * c)) as f32) / 32767.0f32);
                    }
                }
                normalize32(&mut out);
                if element.semantic_index == 0 {
                    normals = Some(out);
                }
            }
            (SEM_NORMAL, 6) => {
                let mut out = vec![0.0f32; n * 3];
                for k in 0..n {
                    let p = at(k);
                    for c in 0..3 {
                        out[k * 3 + c] = f32::from_le_bytes(bytes4(raw, p + 4 * c));
                    }
                }
                normalize32(&mut out);
                if !all_finite(&out) {
                    return Err(7);
                }
                if element.semantic_index == 0 {
                    normals = Some(out);
                }
            }
            (SEM_NORMAL, 24) => {
                let scale = (2.0f64 / 1023.0f64) as f32;
                let mut out = vec![0.0f32; n * 3];
                for k in 0..n {
                    let bits = u32::from_le_bytes(bytes4(raw, at(k)));
                    for (c, shift) in [0u32, 10, 20].iter().enumerate() {
                        out[k * 3 + c] = (((bits >> shift) & 1023) as f32) * scale - 1.0f32;
                    }
                }
                normalize32(&mut out);
                if element.semantic_index == 0 {
                    normals = Some(out);
                }
            }
            (SEM_NORMAL, 10) => {
                let mut out = vec![0.0f32; n * 3];
                for k in 0..n {
                    let p = at(k);
                    for c in 0..3 {
                        out[k * 3 + c] = half_to_f32(u16::from_le_bytes(bytes2(raw, p + 2 * c)));
                    }
                }
                normalize32(&mut out);
                if !all_finite(&out) {
                    return Err(7);
                }
                if element.semantic_index == 0 {
                    normals = Some(out);
                }
            }
            (SEM_TEXCOORD, 35) => {
                let channel = element.semantic_index;
                if !(0..UV_CHANNELS as i32).contains(&channel) {
                    return Err(1);
                }
                let mut out = vec![0.0f32; n * 2];
                for k in 0..n {
                    let p = at(k);
                    for c in 0..2 {
                        out[k * 2 + c] = (u16::from_le_bytes(bytes2(raw, p + 2 * c)) as f32) / 65535.0f32;
                    }
                }
                uvs[channel as usize] = Some(out);
            }
            (SEM_TEXCOORD, 16) => {
                let channel = element.semantic_index;
                if !(0..UV_CHANNELS as i32).contains(&channel) {
                    return Err(1);
                }
                let mut out = vec![0.0f32; n * 2];
                for k in 0..n {
                    let p = at(k);
                    for c in 0..2 {
                        out[k * 2 + c] = f32::from_le_bytes(bytes4(raw, p + 4 * c));
                    }
                }
                if !all_finite(&out) {
                    return Err(7);
                }
                uvs[channel as usize] = Some(out);
            }
            (SEM_COLOR, 28) => {
                // 8 ビットの色は、いつも有限（値は使わない。Python の処理も有限かの確かめだけに使う）。
            }
            (SEM_COLOR, 2) => {
                for k in 0..n {
                    let p = at(k);
                    for c in 0..4 {
                        if !f32::from_le_bytes(bytes4(raw, p + 4 * c)).is_finite() {
                            return Err(7);
                        }
                    }
                }
            }
            _ => return Err(5),
        }
    }
    let positions = positions.ok_or(6)?;
    if !all_finite(&positions) {
        return Err(7);
    }
    if let Some(values) = normals.as_ref() {
        if !all_finite(values) {
            return Err(7);
        }
    }
    Ok(Decoded { positions, normals, uvs })
}

/// 骨と配置の行列で、位置と法線を動かす（transform_source_geometry と同じ手順）。戻り値は巻き方向を反転したか。
fn transform(decoded: &mut Decoded, params: &MeshParams, n: usize) -> Result<bool, i32> {
    let scale: [f64; 4] = [params.scale[0] as f64, params.scale[1] as f64, params.scale[2] as f64, params.scale[3] as f64];
    if scale.iter().any(|v| !v.is_finite()) {
        return Err(8);
    }
    if params.bone.iter().chain(params.instance.iter()).any(|v| !v.is_finite()) {
        return Err(8);
    }
    let composite = matmul4(&params.bone, &params.instance);
    let det = det3(&composite);
    if !det.is_finite() || abs64(det) < 1.0e-12 {
        return Err(8);
    }
    let inverse = inverse3(&composite, det);
    // 位置（行ベクトル × 行列、w で割る、X を反転）
    let positions = &mut decoded.positions;
    for k in 0..n {
        let x = positions[k * 3] as f64;
        let y = positions[k * 3 + 1] as f64;
        let z = positions[k * 3 + 2] as f64;
        let mut out = [0.0f64; 4];
        for (j, value) in out.iter_mut().enumerate() {
            *value = ((x * composite[j] + y * composite[4 + j]) + z * composite[8 + j]) + composite[12 + j];
        }
        if abs64(out[3]) < 1.0e-12 {
            return Err(8);
        }
        let px = -(out[0] / out[3]);
        let py = out[1] / out[3];
        let pz = out[2] / out[3];
        if !(px.is_finite() && py.is_finite() && pz.is_finite()) {
            return Err(8);
        }
        positions[k * 3] = px as f32;
        positions[k * 3 + 1] = py as f32;
        positions[k * 3 + 2] = pz as f32;
    }
    // 法線（PositionScale で割る → 逆転置 → 長さで割る、短すぎれば上向き → X を反転）。元の法線が無い影のメッシュは 0。
    let source = decoded.normals.take().unwrap_or_else(|| vec![0.0f32; n * 3]);
    let mut normals = vec![0.0f32; n * 3];
    for k in 0..n {
        let mut v = [source[k * 3] as f64, source[k * 3 + 1] as f64, source[k * 3 + 2] as f64];
        for (axis, value) in v.iter_mut().enumerate() {
            if abs64(scale[axis]) > 1.0e-6 {
                *value /= scale[axis];
            }
        }
        if !(v[0].is_finite() && v[1].is_finite() && v[2].is_finite()) {
            return Err(8);
        }
        let mut out = [0.0f64; 3];
        for (j, value) in out.iter_mut().enumerate() {
            *value = (v[0] * inverse[j * 3] + v[1] * inverse[j * 3 + 1]) + v[2] * inverse[j * 3 + 2];
        }
        let length = sqrt64((out[0] * out[0] + out[1] * out[1]) + out[2] * out[2]);
        if length > 1.0e-3 {
            out[0] /= length;
            out[1] /= length;
            out[2] /= length;
        } else {
            out = [0.0, 1.0, 0.0];
        }
        out[0] = -out[0];
        if !(out[0].is_finite() && out[1].is_finite() && out[2].is_finite()) {
            return Err(8);
        }
        normals[k * 3] = out[0] as f32;
        normals[k * 3 + 1] = out[1] as f32;
        normals[k * 3 + 2] = out[2] as f32;
    }
    decoded.normals = Some(normals);
    // X の反転を入れた行列の行列式が負なら、巻き方向を反転する（反転で符号が変わるので det > 0 と同じ）。
    Ok(det > 0.0)
}

/// UV の拡大・ずらし（source_uv_affine）。
fn uv_affine(decoded: &mut Decoded, params: &MeshParams) -> Result<(), i32> {
    for (channel, slot) in decoded.uvs.iter_mut().enumerate() {
        let Some(values) = slot.as_mut() else { continue };
        let affine = &params.uv_affine[channel * 4..channel * 4 + 4];
        if affine.iter().any(|v| !v.is_finite()) {
            return Err(11);
        }
        for pair in values.chunks_exact_mut(2) {
            let u = (pair[0] as f64) * affine[1] + affine[0];
            let v = (pair[1] as f64) * affine[3] + affine[2];
            if !(u.is_finite() && v.is_finite()) {
                return Err(11);
            }
            let (u32v, v32v) = (u as f32, v as f32);
            if !(u32v.is_finite() && v32v.is_finite()) {
                return Err(11);
            }
            pair[0] = u32v;
            pair[1] = v32v;
        }
    }
    Ok(())
}

/// 静止の部品の三角形の整理（つぶれた三角形を除き、同じ 3 頂点の 2 つ目以降を除き、(A,C,B) にする）。
fn clean_triangles(local: &[u32]) -> Vec<u32> {
    let count = local.len() / 3;
    let mut keyed: Vec<(u64, u32)> = Vec::with_capacity(count);
    for t in 0..count {
        let (a, b, c) = (local[t * 3], local[t * 3 + 1], local[t * 3 + 2]);
        if a == b || a == c || b == c {
            continue;
        }
        let (mut lo, mut mid, mut hi) = (a, b, c);
        if lo > mid {
            core::mem::swap(&mut lo, &mut mid);
        }
        if mid > hi {
            core::mem::swap(&mut mid, &mut hi);
        }
        if lo > mid {
            core::mem::swap(&mut lo, &mut mid);
        }
        // 頂点の番号は 2,000,000 未満（2^21 未満）なので、3 つを 1 つの 64 ビットの数に詰められる。
        keyed.push((((lo as u64) << 42) | ((mid as u64) << 21) | hi as u64, t as u32));
    }
    keyed.sort_unstable();
    let mut first: Vec<u32> = Vec::with_capacity(keyed.len());
    let mut previous: Option<u64> = None;
    for (key, position) in keyed {
        if previous != Some(key) {
            first.push(position);
            previous = Some(key);
        }
    }
    first.sort_unstable();
    let mut out = Vec::with_capacity(first.len() * 3);
    for t in first {
        let t = t as usize;
        out.push(local[t * 3]);
        out.push(local[t * 3 + 2]);
        out.push(local[t * 3 + 1]);
    }
    out
}

fn put_u32(out: &mut [u8], at: usize, value: u32) {
    out[at..at + 4].copy_from_slice(&value.to_le_bytes());
}

fn put_f32(out: &mut [u8], at: usize, value: f32) {
    out[at..at + 4].copy_from_slice(&value.to_le_bytes());
}

/// メッシュ 1 つ分を処理して、out に「見出し（64 バイト）・位置・法線・UV（あるものだけ、0〜4 の順）・番号」を書く。
///
/// 見出し：MAGIC、頂点の数、番号の数、元の三角形の数、印（bit0 元の法線が無い、bit1 巻き方向を反転）、UV の組の印、
/// 番号の幅（2 か 4）、0、位置の最小（3 つ）、位置の最大（3 つ）、番号の最小、番号の最大。
/// 戻り値：0 成功。それ以外は扱わない（Python の処理で作り直す）：
///   1 引数・使い方、2 番号の場所、3 頂点の数、4 頂点の場所、5 形式、6 位置が無い、7 有限でない、8 姿勢、
///   9 出力の場所が足りない、10 法線に位置の W が要る、11 UV。
///
/// # Safety
/// raw は raw_len バイト、params は 1 つ、elements は element_count 個、out は out_capacity バイトの、読み書きできる
/// 領域を指すこと。
#[no_mangle]
pub unsafe extern "C" fn lo4_mesh_geometry(
    raw: *const u8,
    raw_len: usize,
    params: *const MeshParams,
    elements: *const MeshElement,
    element_count: usize,
    out: *mut u8,
    out_capacity: usize,
) -> i32 {
    if raw.is_null() || params.is_null() || out.is_null() || (elements.is_null() && element_count != 0) || element_count > 64 {
        return 1;
    }
    let raw = core::slice::from_raw_parts(raw, raw_len);
    let params = &*params;
    let elements = if element_count == 0 { &[][..] } else { core::slice::from_raw_parts(elements, element_count) };
    let out = core::slice::from_raw_parts_mut(out, out_capacity);
    match mesh_geometry(raw, params, elements, out) {
        Ok(()) => 0,
        Err(code) => code,
    }
}

fn mesh_geometry(raw: &[u8], params: &MeshParams, elements: &[MeshElement], out: &mut [u8]) -> Result<(), i32> {
    if params.flags != FLAG_STATIC_CLEAN || !(params.index_width == 2 || params.index_width == 4) {
        return Err(1);
    }
    let count = params.index_count;
    if count == 0 || count > MAX_INDICES || count % 3 != 0 {
        return Err(2);
    }
    let width = params.index_width as u64;
    let start = params.index_offset;
    let end = start.checked_add(count * width).ok_or(2)?;
    if end > raw.len() as u64 {
        return Err(2);
    }
    let (start, count) = (start as usize, count as usize);
    let mut source = Vec::with_capacity(count);
    for k in 0..count {
        let value = if width == 4 {
            u32::from_le_bytes(bytes4(raw, start + 4 * k))
        } else {
            u16::from_le_bytes(bytes2(raw, start + 2 * k)) as u32
        };
        source.push(value);
    }
    let mut imin = u32::MAX;
    let mut imax = 0u32;
    for &value in &source {
        if value < imin {
            imin = value;
        }
        if value > imax {
            imax = value;
        }
    }
    let n64 = (imax - imin) as u64 + 1;
    if n64 > MAX_VERTICES {
        return Err(3);
    }
    let n = n64 as usize;
    let mut decoded = decode_vertices(raw, elements, params, imin as u64, n)?;
    let missing_normal = decoded.normals.is_none();
    uv_affine(&mut decoded, params)?;
    let winding_reversed = transform(&mut decoded, params, n)?;
    for value in source.iter_mut() {
        *value -= imin;
    }
    let indices = clean_triangles(&source);
    // 書く
    let uv_mask: u32 = decoded.uvs.iter().enumerate().filter(|(_, v)| v.is_some()).map(|(k, _)| 1u32 << k).sum();
    let uv_count = uv_mask.count_ones() as usize;
    let index_width: usize = if n < 65536 { 2 } else { 4 };
    let needed = HEADER_SIZE + n * 24 + n * 8 * uv_count + indices.len() * index_width;
    if needed > out.len() {
        return Err(9);
    }
    let normals = decoded.normals.as_ref().ok_or(1)?;
    let positions = &decoded.positions;
    let mut minimum = [positions[0], positions[1], positions[2]];
    let mut maximum = minimum;
    for k in 1..n {
        for c in 0..3 {
            let value = positions[k * 3 + c];
            if value < minimum[c] {
                minimum[c] = value;
            }
            if value > maximum[c] {
                maximum[c] = value;
            }
        }
    }
    let (mut index_min, mut index_max) = (0u32, 0u32);
    if let Some(&first) = indices.first() {
        index_min = first;
        index_max = first;
        for &value in &indices {
            if value < index_min {
                index_min = value;
            }
            if value > index_max {
                index_max = value;
            }
        }
    }
    put_u32(out, 0, MAGIC);
    put_u32(out, 4, n as u32);
    put_u32(out, 8, indices.len() as u32);
    put_u32(out, 12, (count / 3) as u32);
    put_u32(out, 16, (missing_normal as u32) | ((winding_reversed as u32) << 1));
    put_u32(out, 20, uv_mask);
    put_u32(out, 24, index_width as u32);
    put_u32(out, 28, 0);
    for c in 0..3 {
        put_f32(out, 32 + 4 * c, minimum[c]);
        put_f32(out, 44 + 4 * c, maximum[c]);
    }
    put_u32(out, 56, index_min);
    put_u32(out, 60, index_max);
    let mut at = HEADER_SIZE;
    for &value in positions.iter().chain(normals.iter()) {
        put_f32(out, at, value);
        at += 4;
    }
    for values in decoded.uvs.iter().flatten() {
        for &value in values {
            put_f32(out, at, value);
            at += 4;
        }
    }
    for &value in &indices {
        if index_width == 2 {
            out[at..at + 2].copy_from_slice(&(value as u16).to_le_bytes());
        } else {
            out[at..at + 4].copy_from_slice(&value.to_le_bytes());
        }
        at += index_width;
    }
    Ok(())
}
