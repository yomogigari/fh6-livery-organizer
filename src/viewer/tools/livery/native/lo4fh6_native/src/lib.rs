//! LO4FH6 Viewer の自前の部品（Rust、2026-11-20、FH6 に近づける案 ④）。
//!
//! Python の処理と同じ結果を、速く求める。読み込みは src/viewer/tools/livery/native_kernels.py（DLL の SHA-256 を
//! 確かめてから読み込み、無い・合わないときは Python の処理を使う）。作り方は tools/native/build_lo4fh6_native.py。
//! 外の crate と標準ライブラリは使わない（no_std）。Windows の KERNEL32.dll と msvcrt.dll だけを使う。
//!
//! - BC4 の復号（lo4_decode_bc4_unorm）：tools/livery/render_contract.py の numpy の計算と同じ。
//! - C_livery の解読（lo4_decode_livery_layers）：fh_livery_preview_core の native_structure（木の読み取り）・
//!   native_canonical_layers.native_layers（図形ごとの変換と覆いの判定）・first_party_privacy_absence（保護の
//!   印が無いことの確かめ）と同じ判定・同じ計算の順。少しでも想定外なら 0 以外を返し、Python の処理に任せる
//!   （例外とその文言は Python の処理が出す）。
//! - 車体の変換のメッシュ 1 つ分の数値の処理（lo4_mesh_geometry、mesh.rs）：independent_chassis の頂点の解読・姿勢・
//!   UV・三角形の整理と同じ計算（2026-11-21）。
//! - 三角関数などは、Python の math と同じ関数（ucrtbase.dll の cos・sin・atan2・fma・sqrt・fmod）を呼ぶ。
//!   hypot は CPython 3.12 の vector_norm と同じ手順、atan2 の特別な値は CPython の m_atan2 と同じ扱い。
#![no_std]

extern crate alloc;

mod mesh;

use alloc::vec::Vec;
use core::alloc::{GlobalAlloc, Layout};
use core::ffi::c_void;

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    // 入力の大きさと位置は先に確かめるので、ここへは来ない。来たら、止まったままにせず、すぐに落とす。
    unsafe { core::arch::asm!("ud2", options(noreturn)) }
}

// ---- Windows（KERNEL32.dll）：プロセスのヒープと、ucrtbase.dll の関数の場所 ----

#[link(name = "kernel32")]
extern "system" {
    fn GetProcessHeap() -> *mut c_void;
    fn HeapAlloc(heap: *mut c_void, flags: u32, bytes: usize) -> *mut c_void;
    fn HeapReAlloc(heap: *mut c_void, flags: u32, memory: *mut c_void, bytes: usize) -> *mut c_void;
    fn HeapFree(heap: *mut c_void, flags: u32, memory: *mut c_void) -> i32;
    fn GetModuleHandleW(name: *const u16) -> *mut c_void;
    fn GetProcAddress(module: *mut c_void, name: *const u8) -> *mut c_void;
}

struct ProcessHeap;

unsafe impl GlobalAlloc for ProcessHeap {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // Windows（x64）のヒープは 16 バイト境界で返す。それより大きい境界は使わない。
        if layout.align() > 16 {
            return core::ptr::null_mut();
        }
        HeapAlloc(GetProcessHeap(), 0, layout.size()) as *mut u8
    }

    unsafe fn dealloc(&self, ptr: *mut u8, _layout: Layout) {
        HeapFree(GetProcessHeap(), 0, ptr as *mut c_void);
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        if layout.align() > 16 {
            return core::ptr::null_mut();
        }
        HeapReAlloc(GetProcessHeap(), 0, ptr as *mut c_void, new_size) as *mut u8
    }
}

#[global_allocator]
static HEAP: ProcessHeap = ProcessHeap;

/// 部品の版（1 は C の版、2 は Rust の BC4 だけの版、3 は解読を足した版、4 は車体の変換のメッシュの処理を足した版）。
/// Python 側の期待と違えば使わない。
#[no_mangle]
pub extern "C" fn lo4_native_version() -> i32 {
    4
}

// ---- BC4 ----

/// 符号なしの BC4（DXGI_FORMAT_BC4_UNORM）を、8 ビットの 1 チャンネルの画像に戻す。
///
/// tools/livery/render_contract.py の _decode_unsigned_bc4_numpy（numpy）と同じ整数の計算・同じ並び。
///   端の値 e0 > e1：8 段（((8 - i) * e0 + (i - 1) * e1) / 7、i = 2〜7）
///   それ以外      ：6 段（((6 - i) * e0 + (i - 1) * e1) / 5、i = 2〜5）と 0・255
/// 戻り値：0 成功、1 幅・高さが 4 の倍数でない、2 データの長さが合わない、3 引数が空。
///
/// # Safety
/// payload は payload_size バイト、out は width × height バイトの読み書きできる領域を指すこと。
#[no_mangle]
pub unsafe extern "C" fn lo4_decode_bc4_unorm(
    payload: *const u8,
    payload_size: usize,
    width: i32,
    height: i32,
    out: *mut u8,
) -> i32 {
    if payload.is_null() || out.is_null() {
        return 3;
    }
    if width <= 0 || height <= 0 || width % 4 != 0 || height % 4 != 0 {
        return 1;
    }
    let block_width = (width / 4) as usize;
    let block_height = (height / 4) as usize;
    let expected = match block_width.checked_mul(block_height).and_then(|count| count.checked_mul(8)) {
        Some(value) => value,
        None => return 2,
    };
    if payload_size != expected {
        return 2;
    }
    let width = width as usize;
    let input = core::slice::from_raw_parts(payload, payload_size);
    let output = core::slice::from_raw_parts_mut(out, width * height as usize);
    for by in 0..block_height {
        for bx in 0..block_width {
            let start = (by * block_width + bx) * 8;
            let block = &input[start..start + 8];
            let e0 = block[0] as u32;
            let e1 = block[1] as u32;
            let mut palette = [0u8; 8];
            palette[0] = e0 as u8;
            palette[1] = e1 as u8;
            if e0 > e1 {
                for i in 2..8u32 {
                    palette[i as usize] = (((8 - i) * e0 + (i - 1) * e1) / 7) as u8;
                }
            } else {
                for i in 2..6u32 {
                    palette[i as usize] = (((6 - i) * e0 + (i - 1) * e1) / 5) as u8;
                }
                palette[6] = 0;
                palette[7] = 255;
            }
            let mut indices: u64 = 0;
            for k in 0..6 {
                indices |= (block[2 + k] as u64) << (8 * k);
            }
            let base = by * 4 * width + bx * 4;
            for p in 0..16usize {
                output[base + (p / 4) * width + (p % 4)] = palette[((indices >> (3 * p)) & 7) as usize];
            }
        }
    }
    0
}

// ---- 数の計算（Python の math と同じ結果） ----

type F1 = unsafe extern "C" fn(f64) -> f64;
type F2 = unsafe extern "C" fn(f64, f64) -> f64;
type F3 = unsafe extern "C" fn(f64, f64, f64) -> f64;

#[derive(Clone, Copy)]
struct Math {
    cos: F1,
    sin: F1,
    atan2: F2,
    fma: F3,
    sqrt: F1,
    fmod: F2,
}

/// Python の math と同じ関数（ucrtbase.dll）の場所。プロセスに読み込まれていなければ None。
unsafe fn resolve_math() -> Option<Math> {
    // "ucrtbase.dll"
    let name: [u16; 13] = [117, 99, 114, 116, 98, 97, 115, 101, 46, 100, 108, 108, 0];
    let module = GetModuleHandleW(name.as_ptr());
    if module.is_null() {
        return None;
    }
    let cos = GetProcAddress(module, b"cos\0".as_ptr());
    let sin = GetProcAddress(module, b"sin\0".as_ptr());
    let atan2 = GetProcAddress(module, b"atan2\0".as_ptr());
    let fma = GetProcAddress(module, b"fma\0".as_ptr());
    let sqrt = GetProcAddress(module, b"sqrt\0".as_ptr());
    let fmod = GetProcAddress(module, b"fmod\0".as_ptr());
    if cos.is_null() || sin.is_null() || atan2.is_null() || fma.is_null() || sqrt.is_null() || fmod.is_null() {
        return None;
    }
    Some(Math {
        cos: core::mem::transmute::<*mut c_void, F1>(cos),
        sin: core::mem::transmute::<*mut c_void, F1>(sin),
        atan2: core::mem::transmute::<*mut c_void, F2>(atan2),
        fma: core::mem::transmute::<*mut c_void, F3>(fma),
        sqrt: core::mem::transmute::<*mut c_void, F1>(sqrt),
        fmod: core::mem::transmute::<*mut c_void, F2>(fmod),
    })
}

const PI: f64 = core::f64::consts::PI;
// CPython の math.radians・math.degrees と同じ定数（Py_MATH_PI / 180.0 と 180.0 / Py_MATH_PI）。
const DEG_TO_RAD: f64 = PI / 180.0;
const RAD_TO_DEG: f64 = 180.0 / PI;
const SIGN: u64 = 0x8000_0000_0000_0000;
const EXPONENT: u64 = 0x7ff0_0000_0000_0000;

#[inline]
fn fabs(x: f64) -> f64 {
    f64::from_bits(x.to_bits() & !SIGN)
}

#[inline]
fn finite(x: f64) -> bool {
    x.to_bits() & EXPONENT != EXPONENT
}

#[inline]
fn is_nan(x: f64) -> bool {
    x != x
}

#[inline]
fn is_inf(x: f64) -> bool {
    x.to_bits() & !SIGN == EXPONENT
}

#[inline]
fn copysign(x: f64, sign: f64) -> f64 {
    f64::from_bits((x.to_bits() & !SIGN) | (sign.to_bits() & SIGN))
}

/// CPython の m_atan2（特別な値の扱い）と同じ。それ以外は ucrtbase の atan2。
fn py_atan2(math: &Math, y: f64, x: f64) -> f64 {
    if is_nan(x) || is_nan(y) {
        return f64::NAN;
    }
    if is_inf(y) {
        if is_inf(x) {
            if copysign(1.0, x) == 1.0 {
                return copysign(0.25 * PI, y);
            }
            return copysign(0.75 * PI, y);
        }
        return copysign(0.5 * PI, y);
    }
    if is_inf(x) || y == 0.0 {
        if copysign(1.0, x) == 1.0 {
            return copysign(0.0, y);
        }
        return copysign(PI, y);
    }
    unsafe { (math.atan2)(y, x) }
}

/// 2 の k 乗（k が正規の数の範囲のときだけ）。
fn pow2(k: i32) -> Option<f64> {
    if !(-1022..=1023).contains(&k) {
        return None;
    }
    Some(f64::from_bits(((k + 1023) as u64) << 52))
}

/// CPython 3.12 の math.hypot（2 つの値、vector_norm）と同じ手順。dl_mul の誤差は ucrtbase の fma で求める。
/// 非正規の数（2 の -1022 乗より小さい最大値）は扱わない（None）。
fn py_hypot(math: &Math, p: f64, q: f64) -> Option<f64> {
    let values = [fabs(p), fabs(q)];
    let mut largest = 0.0f64;
    for &value in values.iter() {
        if value > largest {
            largest = value;
        }
    }
    if is_inf(largest) {
        return Some(largest);
    }
    if is_nan(values[0]) || is_nan(values[1]) {
        return Some(f64::NAN);
    }
    if largest == 0.0 {
        return Some(largest);
    }
    let field = ((largest.to_bits() & EXPONENT) >> 52) as i32;
    if field == 0 {
        return None;
    }
    // frexp の指数（largest = m × 2^e、0.5 ≤ m < 1）
    let exponent = field - 1022;
    let scale = pow2(-exponent)?;
    let mut csum = 1.0f64;
    let mut frac1 = 0.0f64;
    let mut frac2 = 0.0f64;
    for &value in values.iter() {
        let x = value * scale;
        let hi = x * x;
        let lo = unsafe { (math.fma)(x, x, -hi) };
        let total = csum + hi;
        frac2 += (csum - total) + hi;
        csum = total;
        frac1 += lo;
    }
    let mut h = unsafe { (math.sqrt)(csum - 1.0 + (frac1 + frac2)) };
    let hi = -h * h;
    let lo = unsafe { (math.fma)(-h, h, -hi) };
    let total = csum + hi;
    frac2 += (csum - total) + hi;
    csum = total;
    frac1 += lo;
    let x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    Some(h / scale)
}

/// Python の浮動小数の %（float_rem）と同じ。
fn py_mod(math: &Math, v: f64, w: f64) -> f64 {
    let mut result = unsafe { (math.fmod)(v, w) };
    if result != 0.0 {
        if (w < 0.0) != (result < 0.0) {
            result += w;
        }
    } else {
        result = copysign(0.0, w);
    }
    result
}

/// 試験用：Python の math と同じ結果かを、Python 側で確かめる（0 cos、1 sin、2 atan2、3 hypot、4 角度の % 360）。
#[no_mangle]
pub extern "C" fn lo4_math_eval(operation: i32, x: f64, y: f64) -> f64 {
    let math = match unsafe { resolve_math() } {
        Some(math) => math,
        None => return f64::NAN,
    };
    match operation {
        0 => unsafe { (math.cos)(x) },
        1 => unsafe { (math.sin)(x) },
        2 => py_atan2(&math, x, y),
        3 => py_hypot(&math, x, y).unwrap_or(f64::NAN),
        4 => py_mod(&math, x * RAD_TO_DEG, 360.0),
        _ => f64::NAN,
    }
}

// ---- 2 次元のアフィン変換（native_affine_trial.Affine と同じ） ----

#[derive(Clone, Copy)]
struct Affine {
    a: f64,
    b: f64,
    c: f64,
    d: f64,
    tx: f64,
    ty: f64,
}

const IDENTITY: Affine = Affine { a: 1.0, b: 0.0, c: 0.0, d: 1.0, tx: 0.0, ty: 0.0 };

impl Affine {
    /// 親 × 子（子が先に効く）。Python の then_local と同じ式・同じ順。
    fn then_local(&self, other: &Affine) -> Affine {
        Affine {
            a: self.a * other.a + self.c * other.b,
            b: self.b * other.a + self.d * other.b,
            c: self.a * other.c + self.c * other.d,
            d: self.b * other.c + self.d * other.d,
            tx: self.a * other.tx + self.c * other.ty + self.tx,
            ty: self.b * other.tx + self.d * other.ty + self.ty,
        }
    }

    fn determinant(&self) -> f64 {
        self.a * self.d - self.b * self.c
    }
}

const MAX_ABS_TRANSFORM: f64 = 1.0e12;

/// native_affine_trial._placement（回転の向き 1）と同じ。範囲の外は None。
fn placement(math: &Math, x: f64, y: f64, sx: f64, sy: f64, rotation: f64) -> Option<Affine> {
    for &value in [x, y, sx, sy, rotation].iter() {
        if !(finite(value) && fabs(value) <= MAX_ABS_TRANSFORM) {
            return None;
        }
    }
    let largest = if fabs(sx) > fabs(sy) { fabs(sx) } else { fabs(sy) };
    if fabs(sx) < 1.0e-7 || fabs(sy) < 1.0e-7 || largest > 5000.0 {
        return None;
    }
    let radians = (rotation * 1.0) * DEG_TO_RAD;
    let co = unsafe { (math.cos)(radians) };
    let si = unsafe { (math.sin)(radians) };
    Some(Affine { a: co * sx, b: si * sx, c: (-si) * sy, d: co * sy, tx: x, ty: y })
}

// ---- C_livery の木（native_structure._Parser と同じ） ----

const MAX_NODES: usize = 200_000;
const MAX_DEPTH: u32 = 120;
const MAX_CHILDREN: usize = 15_000;
const MAX_SECTION_LEAVES: usize = 100_000;
const SECTIONS: usize = 11;
const SUPPORTED_FLAGS: u8 = 0x71;
const MAX_BODY_BYTES: usize = 128 * 1024 * 1024;
const NONE: u32 = u32::MAX;

#[derive(Clone, Copy)]
struct Group {
    start: usize,
    prefix: i16, // -1 は接頭辞なし
    x: f64,
    y: f64,
    scale: f64,
    rotation: f64,
    flags: u8,
    child_count: usize,
    bitmap_start: usize,
    bitmap_len: usize,
    optional_four: [u8; 4],
    optional_four_len: u8,
    optional_eight_len: u8,
    byte_length: usize,
    depth: u32,
    parent: u32,
}

#[derive(Clone, Copy)]
struct Shape {
    offset: usize,
    size: usize,
    word: u16,
    x: f64,
    y: f64,
    scale_x: f64,
    scale_y: f64,
    rotation: f64,
    skew: f64,
    rgba: [u8; 4],
    control: i16, // -1 は制御バイトなし
    group: u32,
}

/// Python の SemanticLiveryError（読み方を変えて試し直す）と、それ以外（割り当ての失敗。Python に任せる）。
enum Fail {
    Semantic,
    Fatal,
}

#[inline]
fn u16_at(body: &[u8], at: usize) -> u16 {
    u16::from_le_bytes([body[at], body[at + 1]])
}

#[inline]
fn u32_at(body: &[u8], at: usize) -> u32 {
    u32::from_le_bytes([body[at], body[at + 1], body[at + 2], body[at + 3]])
}

#[inline]
fn f32_at(body: &[u8], at: usize) -> f64 {
    f32::from_le_bytes([body[at], body[at + 1], body[at + 2], body[at + 3]]) as f64
}

/// source_leaf_records.read_leaf_record と同じ。読めなければ None。
fn read_leaf(body: &[u8], offset: usize, group: u32) -> Option<Shape> {
    let n = body.len();
    if n > MAX_BODY_BYTES || offset >= n {
        return None;
    }
    let (head, size, control) = if body[offset] == 2 {
        (offset + 1, 31usize, -1i16)
    } else if body[offset] <= 1 && offset + 1 < n && body[offset + 1] == 2 {
        (offset + 2, 32usize, body[offset] as i16)
    } else {
        return None;
    };
    if offset + size > n {
        return None;
    }
    let word = u16_at(body, head);
    if word == 0 {
        return None;
    }
    let rotation = f32_at(body, head + 2);
    let x = f32_at(body, head + 6);
    let y = f32_at(body, head + 10);
    let scale_x = f32_at(body, head + 14);
    let scale_y = f32_at(body, head + 18);
    let skew = f32_at(body, head + 22);
    if !(finite(rotation) && finite(x) && finite(y) && finite(scale_x) && finite(scale_y) && finite(skew)) {
        return None;
    }
    if !(-10000.0 <= rotation
        && rotation <= 10000.0
        && fabs(x) < 50000.0
        && fabs(y) < 50000.0
        && 0.0 < fabs(scale_x)
        && fabs(scale_x) < 5000.0
        && 0.0 < fabs(scale_y)
        && fabs(scale_y) < 5000.0
        && fabs(skew) < 1000000.0)
    {
        return None;
    }
    // 原本の並びは b, g, r, a。
    let rgba = [body[head + 28], body[head + 27], body[head + 26], body[head + 29]];
    Some(Shape { offset, size, word, x, y, scale_x, scale_y, rotation, skew, rgba, control, group })
}

struct Parser<'a> {
    body: &'a [u8],
    node_count: usize,
    groups: Vec<Group>,
    shapes: Vec<Shape>,
}

impl<'a> Parser<'a> {
    fn group_fields(&self, start: usize, depth: u32, root: bool, shift: usize, parent: u32) -> Result<(usize, Group), Fail> {
        let body = self.body;
        let n = body.len();
        let p = start + shift;
        let (x, y, scale, rotation, flags, count, metadata, bitmap_start);
        let mut optional_four = [0u8; 4];
        let mut optional_four_len = 0u8;
        let mut optional_eight_len = 0u8;
        if root {
            if p + 6 > n {
                return Err(Fail::Semantic);
            }
            count = u16_at(body, p) as usize;
            metadata = u32_at(body, p + 2);
            bitmap_start = p + 6;
            flags = 0u8;
            x = 0.0;
            y = 0.0;
            rotation = 0.0;
            scale = 1.0;
        } else {
            if p + 23 > n {
                return Err(Fail::Semantic);
            }
            x = f32_at(body, p);
            y = f32_at(body, p + 4);
            scale = f32_at(body, p + 8);
            rotation = f32_at(body, p + 12);
            if !(finite(x) && finite(y) && finite(scale) && finite(rotation)) {
                return Err(Fail::Semantic);
            }
            let mut largest = fabs(x);
            if fabs(y) > largest {
                largest = fabs(y);
            }
            if fabs(rotation) > largest {
                largest = fabs(rotation);
            }
            if largest > 50000.0 || !(0.001 < fabs(scale) && fabs(scale) < 5000.0) {
                return Err(Fail::Semantic);
            }
            flags = body[p + 16];
            if flags & !SUPPORTED_FLAGS != 0 {
                return Err(Fail::Semantic);
            }
            let mut cursor = p + 17;
            if flags & 0x01 != 0 {
                let length = if n - cursor < 8 { n - cursor } else { 8 };
                optional_eight_len = length as u8;
                cursor += length;
            }
            if flags & 0x10 != 0 {
                let length = if n - cursor < 4 { n - cursor } else { 4 };
                optional_four[..length].copy_from_slice(&body[cursor..cursor + length]);
                optional_four_len = length as u8;
                cursor += length;
            }
            if cursor + 6 > n {
                return Err(Fail::Semantic);
            }
            count = u16_at(body, cursor) as usize;
            metadata = u32_at(body, cursor + 2);
            bitmap_start = cursor + 6;
        }
        if count > MAX_CHILDREN || metadata > 65535 {
            return Err(Fail::Semantic);
        }
        let bitmap_len = (count + 7) / 8;
        let end = bitmap_start + bitmap_len;
        if end > n {
            return Err(Fail::Semantic);
        }
        if count % 8 != 0 && bitmap_len > 0 && (body[end - 1] >> (count % 8)) != 0 {
            return Err(Fail::Semantic);
        }
        let prefix = if shift != 0 { body[start] as i16 } else { -1 };
        Ok((end, Group {
            start,
            prefix,
            x,
            y,
            scale,
            rotation,
            flags,
            child_count: count,
            bitmap_start,
            bitmap_len,
            optional_four,
            optional_four_len,
            optional_eight_len,
            byte_length: end - start,
            depth,
            parent,
        }))
    }

    fn children(&mut self, cursor: usize, group: u32, depth: u32) -> Result<usize, Fail> {
        if depth > MAX_DEPTH {
            return Err(Fail::Semantic);
        }
        let (count, bitmap_start) = {
            let field = &self.groups[group as usize];
            (field.child_count, field.bitmap_start)
        };
        let mut cursor = cursor;
        for index in 0..count {
            if self.node_count >= MAX_NODES {
                return Err(Fail::Semantic);
            }
            self.node_count += 1;
            let child_is_group = (self.body[bitmap_start + index / 8] >> (index % 8)) & 1 != 0;
            if child_is_group {
                cursor = self.read_group(cursor, group, depth + 1, false)?;
            } else {
                let leaf = match read_leaf(self.body, cursor, group) {
                    Some(leaf) => leaf,
                    None => return Err(Fail::Semantic),
                };
                if self.shapes.try_reserve(1).is_err() {
                    return Err(Fail::Fatal);
                }
                self.shapes.push(leaf);
                if self.shapes.len() > MAX_SECTION_LEAVES * SECTIONS {
                    return Err(Fail::Semantic);
                }
                cursor += leaf.size;
            }
        }
        Ok(cursor)
    }

    fn read_group(&mut self, cursor: usize, parent: u32, depth: u32, root: bool) -> Result<usize, Fail> {
        if depth > MAX_DEPTH {
            return Err(Fail::Semantic);
        }
        // 1 バイトの接頭辞つきを先に、無しを後に試す（先頭の面の根は接頭辞なしだけ）。
        let shifts: &[usize] = if root { &[0] } else { &[1, 0] };
        for &shift in shifts.iter() {
            if shift != 0 && (cursor >= self.body.len() || self.body[cursor] > 1) {
                continue;
            }
            let old_groups = self.groups.len();
            let old_shapes = self.shapes.len();
            let old_nodes = self.node_count;
            match self.group_fields(cursor, depth, root, shift, parent) {
                Ok((next, field)) => {
                    if self.groups.try_reserve(1).is_err() {
                        return Err(Fail::Fatal);
                    }
                    self.groups.push(field);
                    let index = (self.groups.len() - 1) as u32;
                    match self.children(next, index, depth) {
                        Ok(end) => return Ok(end),
                        Err(Fail::Fatal) => return Err(Fail::Fatal),
                        Err(Fail::Semantic) => {}
                    }
                }
                Err(Fail::Fatal) => return Err(Fail::Fatal),
                Err(Fail::Semantic) => {}
            }
            self.groups.truncate(old_groups);
            self.shapes.truncate(old_shapes);
            self.node_count = old_nodes;
        }
        Err(Fail::Semantic)
    }
}

// ---- 図形ごとの変換と覆いの判定（native_canonical_layers.native_layers と同じ） ----

/// 図形 1 つの出力の大きさ（Python の struct '<6dIIIHBB4B'）。
const RECORD_SIZE: usize = 68;

/// 祖先のグループの印の要約（native_layers の chain_flags と同じ値）。
#[derive(Clone, Copy, Default)]
struct ChainFlags {
    counted_60: u32,
    has_40: bool,
    has_50: bool,
    has_60: bool,
    has_70: bool,
}

/// native_skew_candidate.shape_shear_candidate（回転の向き 1、原本の図形）と同じ。範囲の外は None。
fn shape_affine(math: &Math, shape: &Shape) -> Option<Affine> {
    let (sx, sy, k) = (shape.scale_x, shape.scale_y, shape.skew);
    let (px, py, rotation) = (shape.x, shape.y, shape.rotation);
    if !(finite(px) && finite(py) && finite(rotation) && finite(sx) && finite(sy) && finite(k))
        || fabs(px) > MAX_ABS_TRANSFORM
        || fabs(py) > MAX_ABS_TRANSFORM
        || fabs(rotation) > MAX_ABS_TRANSFORM
        || fabs(sx) > MAX_ABS_TRANSFORM
        || fabs(sy) > MAX_ABS_TRANSFORM
        || fabs(k) > MAX_ABS_TRANSFORM
        || !(1e-7 < fabs(sx) && fabs(sx) <= 5000.0)
        || !(1e-7 < fabs(sy) && fabs(sy) <= 5000.0)
        || fabs(k) > 1_000_000.0
    {
        return None;
    }
    let angle = (1.0 * rotation) * DEG_TO_RAD;
    let c = unsafe { (math.cos)(angle) };
    let s = unsafe { (math.sin)(angle) };
    let a = c * sx;
    let b = s * sx;
    let cc = (c * k - s) * sy;
    let d = (s * k + c) * sy;
    for &value in [a, b, cc, d, px, py].iter() {
        if !(finite(value) && fabs(value) <= MAX_ABS_TRANSFORM) {
            return None;
        }
    }
    Some(Affine { a, b, c: cc, d, tx: px, ty: py })
}

/// native_affine_trial.group_basis（回転の向き 1）と同じ。
fn group_basis(math: &Math, group: &Group) -> Option<Affine> {
    let sy = if group.flags & 0x10 != 0 {
        if group.optional_four_len != 4 {
            return None;
        }
        f32::from_le_bytes(group.optional_four) as f64
    } else if group.optional_four_len != 0 {
        return None;
    } else {
        group.scale
    };
    placement(math, group.x, group.y, group.scale, sy, group.rotation)
}

/// surface_tree_flatten._components と同じ（引数は _components に渡す並び）。
fn components(math: &Math, a: f64, b: f64, c: f64, d: f64, x: f64, y: f64) -> Option<[f64; 6]> {
    let magnitude = py_hypot(math, a, c)?;
    if magnitude < 1e-8 {
        return Some([x, y, 0.0, py_hypot(math, b, d)?, 0.0, 0.0]);
    }
    let mirrored = a * d - b * c < 0.0;
    let theta = if mirrored { py_atan2(math, -c, -a) } else { py_atan2(math, c, a) };
    let sx = if mirrored { -magnitude } else { magnitude };
    if !finite(theta) {
        return None;
    }
    let cs = unsafe { (math.cos)(theta) };
    let sn = unsafe { (math.sin)(theta) };
    let sy = -sn * b + cs * d;
    let shear = if fabs(sy) > 1e-8 { (cs * b + sn * d) / sy } else { 0.0 };
    let angle = py_mod(math, theta * RAD_TO_DEG, 360.0);
    let angle = if fabs(angle - 360.0) < 1e-9 { 0.0 } else { angle };
    Some([x, y, sx, sy, angle, shear])
}

/// native_canonical_layers._validated_odd_transform_before_group と同じ。
fn validated_odd_transform(body: &[u8], after: usize, next_group: Option<&Group>) -> bool {
    let group = match next_group {
        Some(group) => group,
        None => return false,
    };
    if group.prefix != 0 || group.flags != 0x10 {
        return false;
    }
    let n = body.len();
    let marker = after + 4;
    if marker + 18 > n || body[marker] & 1 == 0 {
        return false;
    }
    let x = f32_at(body, marker + 1);
    let y = f32_at(body, marker + 5);
    let sx = f32_at(body, marker + 9);
    let rotation = f32_at(body, marker + 13);
    if !(finite(x) && finite(y) && finite(sx) && finite(rotation)
        && 0.0001 <= fabs(sx)
        && fabs(sx) <= 200.0
        && fabs(rotation) <= 10000.0)
    {
        return false;
    }
    let header = marker + 17;
    if header + 7 > n || body[header] != 0x3F {
        return false;
    }
    let count = u16_at(body, header + 1) as usize;
    let blocks = u16_at(body, header + 3) as usize;
    if !(2 <= count
        && count <= 15000
        && blocks == (count + 7) / 8
        && header + 7 + blocks <= n
        && count == group.child_count)
    {
        return false;
    }
    body[header + 7..header + 7 + blocks] == body[group.bitmap_start..group.bitmap_start + group.bitmap_len]
}

/// 保護ラッパーの先頭のバイト（0x50 のビットを除いて 0x21 と同じ）。
#[inline]
fn protected_lead(value: u8) -> bool {
    value & !0x50 == 0x21
}

/// first_party_privacy_absence.inspect_absent_protected_groups（構造の読み取り済み）と同じ確かめ。
fn privacy_absent(body: &[u8], groups: &[Group], shapes: &[Shape]) -> Option<bool> {
    let mut intervals: Vec<(usize, usize)> = Vec::new();
    if intervals.try_reserve(groups.len() + shapes.len()).is_err() {
        return None;
    }
    for shape in shapes.iter() {
        intervals.push((shape.offset, shape.offset + shape.size));
    }
    for group in groups.iter() {
        intervals.push((group.start, group.start + group.byte_length));
    }
    intervals.sort_unstable();
    let n = body.len();
    for (index, &(start, end)) in intervals.iter().enumerate() {
        if end > n || (index > 0 && start < intervals[index - 1].1) {
            return Some(false);
        }
    }
    let mut position = 0usize;
    for &(start, end) in intervals.iter() {
        if start > position && body[position..start].iter().any(|&value| protected_lead(value)) {
            return Some(false);
        }
        if end > position {
            position = end;
        }
    }
    if position < n && body[position..].iter().any(|&value| protected_lead(value)) {
        return Some(false);
    }
    Some(true)
}

fn write_record(out: &mut [u8], values: &[f64; 6], shape: &Shape, mask_depth: u32, group_depth: u32, section: u8, bits: u8) {
    let mut at = 0;
    for value in values.iter() {
        out[at..at + 8].copy_from_slice(&value.to_le_bytes());
        at += 8;
    }
    out[48..52].copy_from_slice(&(shape.offset as u32).to_le_bytes());
    out[52..56].copy_from_slice(&mask_depth.to_le_bytes());
    out[56..60].copy_from_slice(&group_depth.to_le_bytes());
    out[60..62].copy_from_slice(&shape.word.to_le_bytes());
    out[62] = section;
    out[63] = bits;
    out[64..68].copy_from_slice(&shape.rgba);
}

/// C_livery の描画本体を、図形ごとの値にする（native_layers の通常の入口：覆いの文脈の候補あり・研究の範囲なし）。
///
/// 出力は図形ごとに RECORD_SIZE バイト（x, y, sx, sy, 角度, せん断 の f64、原本の位置・覆いのグループの深さ・
/// グループの深さの u32、図形番号の u16、面の番号、印（bit0 覆い、bit1-2 覆いの出どころ、bit3-4 印のバイト）、RGBA）。
/// evidence は覆いの文脈の件数 7 つ（native_layers の source_contextual_mask_evidence の並び）。
/// 戻り値：0 成功。それ以外は扱わない（Python の処理で解読し直す）：
///   1 引数、2 Windows の数の関数が無い、3 割り当て、4 木を読めない、5 図形の判定で止まる、6 保護の印が残る、7 数が合わない。
///
/// # Safety
/// body は body_len バイト、counts と turns は 11 個、out は capacity × RECORD_SIZE バイト、evidence は 7 個の
/// 読み書きできる領域を指すこと。
#[no_mangle]
pub unsafe extern "C" fn lo4_decode_livery_layers(
    body: *const u8,
    body_len: usize,
    counts: *const u32,
    turns: *const u8,
    capacity: usize,
    out: *mut u8,
    evidence: *mut u64,
) -> i32 {
    if body.is_null() || counts.is_null() || turns.is_null() || out.is_null() || evidence.is_null() {
        return 1;
    }
    let math = match resolve_math() {
        Some(math) => math,
        None => return 2,
    };
    let body = core::slice::from_raw_parts(body, body_len);
    let counts = core::slice::from_raw_parts(counts, SECTIONS);
    let turns = core::slice::from_raw_parts(turns, SECTIONS);
    let total: usize = counts.iter().map(|&count| count as usize).sum();
    if total != capacity || capacity.checked_mul(RECORD_SIZE).is_none() {
        return 7;
    }
    let out = core::slice::from_raw_parts_mut(out, capacity * RECORD_SIZE);
    let evidence = core::slice::from_raw_parts_mut(evidence, 7);

    // 木を読む（native_structure._Parser.decode）
    let mut parser = Parser { body, node_count: 0, groups: Vec::new(), shapes: Vec::new() };
    if parser.shapes.try_reserve(capacity).is_err() {
        return 3;
    }
    let mut cursor = 0usize;
    let mut group_ranges = [(0usize, 0usize); SECTIONS];
    let mut shape_ranges = [(0usize, 0usize); SECTIONS];
    for section in 0..SECTIONS {
        let old_groups = parser.groups.len();
        let old_shapes = parser.shapes.len();
        cursor = match parser.read_group(cursor, NONE, 0, section == 0) {
            Ok(end) => end,
            Err(Fail::Fatal) => return 3,
            Err(Fail::Semantic) => return 4,
        };
        if parser.shapes.len() - old_shapes != counts[section] as usize {
            return 4;
        }
        group_ranges[section] = (old_groups, parser.groups.len());
        shape_ranges[section] = (old_shapes, parser.shapes.len());
    }
    let remaining = &body[cursor..];
    if !(remaining.is_empty() || remaining == [0u8] || remaining == [1u8]) {
        return 4;
    }
    let groups = &parser.groups[..];
    let shapes = &parser.shapes[..];

    // 保護の印が無いこと（inspect_absent_protected_groups）
    match privacy_absent(body, groups, shapes) {
        Some(true) => {}
        Some(false) => return 6,
        None => return 3,
    }

    // 祖先の印の要約（親は子より先に並ぶ）
    let mut chain_flags: Vec<ChainFlags> = Vec::new();
    if chain_flags.try_reserve(groups.len()).is_err() {
        return 3;
    }
    for group in groups.iter() {
        let mut flags = if group.parent == NONE { ChainFlags::default() } else { chain_flags[group.parent as usize] };
        match group.flags {
            0x40 => flags.has_40 = true,
            0x50 => flags.has_50 = true,
            0x60 => {
                flags.has_60 = true;
                flags.counted_60 += 1;
            }
            0x70 => flags.has_70 = true,
            _ => {}
        }
        chain_flags.push(flags);
    }
    // グループの世界の変換（図形の祖先のものだけ、要るときに求める。0 未計算、1 済み）
    let mut worlds: Vec<(u8, Affine)> = Vec::new();
    if worlds.try_reserve(groups.len()).is_err() {
        return 3;
    }
    worlds.resize(groups.len(), (0, IDENTITY));

    for value in evidence.iter_mut() {
        *value = 0;
    }
    let mut written = 0usize;
    for section in 0..SECTIONS {
        let (g0, g1) = group_ranges[section];
        let (s0, s1) = shape_ranges[section];
        let section_groups = &groups[g0..g1];
        // 同じ位置のグループは無い（読み取りの並びで位置は増えていく）。増えていなければ扱わない。
        for pair in section_groups.windows(2) {
            if pair[1].start <= pair[0].start {
                return 5;
            }
        }
        for group in section_groups.iter() {
            match group.flags {
                0x40 => evidence[0] += 1,
                0x50 => evidence[1] += 1,
                0x60 => evidence[2] += 1,
                _ => {}
            }
            if matches!(group.flags, 0x00 | 0x20 | 0x30 | 0x60 | 0x70 | 0x40 | 0x50) {
                continue;
            }
            if group.flags != 0x10 {
                return 5;
            }
            if group.optional_four_len != 4 || group.optional_eight_len != 0 {
                return 5;
            }
            let signed_y = f32::from_le_bytes(group.optional_four) as f64;
            if !finite(signed_y) || !(1.0e-7 < fabs(signed_y) && fabs(signed_y) < 5000.0) {
                return 5;
            }
        }
        let direct_section_root = section_groups.len() > 1
            && section_groups[0].child_count > 1
            && section_groups[1].start == section_groups[0].start + section_groups[0].byte_length
            && section_groups[1].prefix < 0
            && section_groups[1].flags == 0x30;
        for shape in shapes[s0..s1].iter() {
            let leaf_group = shape.group as usize;
            if leaf_group < g0 || leaf_group >= g1 {
                return 5;
            }
            // 祖先の並びの変換（native_layers の worlds と同じ：恒等から順に then_local）
            if worlds[leaf_group].0 == 0 {
                let mut stack = [0u32; 128];
                let mut depth = 0usize;
                let mut current = leaf_group as u32;
                loop {
                    if depth >= stack.len() {
                        return 5;
                    }
                    stack[depth] = current;
                    depth += 1;
                    let parent = groups[current as usize].parent;
                    if parent == NONE || worlds[parent as usize].0 == 1 {
                        break;
                    }
                    current = parent;
                }
                let top_parent = groups[stack[depth - 1] as usize].parent;
                let mut world = if top_parent == NONE { IDENTITY } else { worlds[top_parent as usize].1 };
                while depth > 0 {
                    depth -= 1;
                    let index = stack[depth] as usize;
                    let basis = match group_basis(&math, &groups[index]) {
                        Some(basis) => basis,
                        None => return 5,
                    };
                    world = world.then_local(&basis);
                    worlds[index] = (1, world);
                }
            }
            let shear = match shape_affine(&math, shape) {
                Some(value) => value,
                None => return 5,
            };
            let world = worlds[leaf_group].1.then_local(&shear);
            let determinant = world.determinant();
            if !finite(determinant) || fabs(determinant) < 1e-20 {
                return 5;
            }
            // 面の向き（first_party_affine_bridge._candidate_components）
            let (a, b, c, d, x, y) = (world.a, world.b, world.c, world.d, world.tx, world.ty);
            let (a, b, c, d, x, y) = match turns[section] {
                1 => (-b, a, -d, c, -y, x),
                2 => (-a, -b, -c, -d, -x, -y),
                3 => (b, -a, d, -c, y, -x),
                _ => (a, b, c, d, x, y),
            };
            let values = match components(&math, a, c, b, d, x, y) {
                Some(values) => values,
                None => return 5,
            };
            if !values.iter().all(|&value| finite(value)) {
                return 5;
            }
            // 覆いの判定（通常の入口：原本の記録の意味による判定）
            let flags = chain_flags[leaf_group];
            let group_mask_depth = flags.counted_60;
            let after = shape.offset + shape.size;
            let [r, g, b, _] = shape.rgba;
            let achromatic = r == g && g == b;
            let next_group = match section_groups.binary_search_by(|group| group.start.cmp(&after)) {
                Ok(index) => Some(&section_groups[index]),
                Err(_) => None,
            };
            if group_mask_depth == 0 && achromatic && flags.has_50 {
                return 5;
            }
            let group_boundary_control = match next_group {
                Some(group) => group.prefix == 1 && group.flags == 0x10,
                None => false,
            } && shape.control == 1
                && flags.has_70;
            let raw_record_state = after < body.len() && body[after] == 1 && !group_boundary_control;
            let transform_state = if achromatic && group_mask_depth == 0 {
                validated_odd_transform(body, after, next_group)
            } else {
                false
            };
            let record_mask = raw_record_state
                || (achromatic && (transform_state || flags.has_40 || (flags.has_70 && !group_boundary_control)));
            let is_mask = group_mask_depth > 0 || record_mask;
            if flags.has_40 || flags.has_50 {
                evidence[3] += 1;
                if is_mask {
                    evidence[4] += 1;
                } else {
                    evidence[5] += 1;
                }
            }
            if flags.has_60 {
                evidence[6] += 1;
            }
            let mask_source: u8 = if group_mask_depth > 0 && record_mask {
                3
            } else if group_mask_depth > 0 {
                2
            } else if record_mask {
                1
            } else {
                0
            };
            let marker: u8 = match shape.control {
                0 => 1,
                1 => 2,
                _ => 0,
            };
            let bits = (is_mask as u8) | (mask_source << 1) | (marker << 3);
            let group_depth = groups[leaf_group].depth + 1 - (direct_section_root as u32);
            if written >= capacity {
                return 7;
            }
            let at = written * RECORD_SIZE;
            write_record(&mut out[at..at + RECORD_SIZE], &values, shape, group_mask_depth, group_depth, section as u8, bits);
            written += 1;
        }
    }
    if written != capacity {
        return 7;
    }
    0
}
