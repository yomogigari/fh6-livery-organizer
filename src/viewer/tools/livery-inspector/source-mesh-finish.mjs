/**
 * 元Carbinのメッシュ材質ハッシュ×元C_livery仕上げの研究用描画ゲート。
 * 正本GLB SHAが一致し、元入力色を欠かさない研究用URLでのみ返す。
 * FH6の2色仕上げShader計算式は再現しない。通常のViewerでは呼ばない。
 */
const HEX64 = /^[\da-f]{64}$/i;
const HASH = /^[\da-f]{16}$/i;
const COLOR = /^#[\da-f]{8}$/i;
const SCHEMA = 'lo4fh6.firstparty.source-mesh-paint-group-binding.v1';
export function validateSourceMeshFinishEvidence(proof, actualGlbSha) {
  if (!proof || proof.schema !== SCHEMA
      || proof.product_default_modified !== false
      || proof.original_glb_modified !== false
      || proof.shader_or_finish_equations_approximated !== false
      || proof.windows_xbox_approved !== false
      || !HEX64.test(String(actualGlbSha || ''))
      || proof.source_glb_sha256?.toLowerCase() !== actualGlbSha.toLowerCase()) {
    throw new Error('元Mesh仕上げ研究: 真正GLB SHA・未承認の研究契約が一致しません');
  }
  const groups = proof.carpaint_groups;
  if (!groups || typeof groups !== 'object' || Array.isArray(groups)
      || !Object.keys(groups).length) {
    throw new Error('元Mesh仕上げ研究: 元CarPaint材質グループがありません');
  }
  const resolved = new Map();
  for (const [hash, row] of Object.entries(groups)) {
    if (!HASH.test(hash) || !row || typeof row !== 'object'
        || !Number.isInteger(row.finish_code_raw) || row.finish_code_raw < 0
        || typeof row.finish_material_name !== 'string' || !row.finish_material_name
        || ![0, 1, 2].includes(row.required_input_colors)
        // 入力色0（prismacolor_black、GoldPolished等）は色を仕上げの材質自体が持つ。C_liveryに
        // 色が残っていても（例：FER_488Pista_19のGoldPolishedに白）ゲームの入力には無いため使わず、
        // 主色を発明しない。表示色は車体の基本塗装の色を使う。色の値自体は形式だけ検査する。
        || (row.required_input_colors === 0
            && [row.primary_color_rgba_hex, row.secondary_color_rgba_hex]
              .some(value => value !== null && !COLOR.test(String(value))))
        || (row.required_input_colors >= 1 && !COLOR.test(String(row.primary_color_rgba_hex || '')))
        || (row.required_input_colors === 2 && !COLOR.test(String(row.secondary_color_rgba_hex || '')))
        || (row.required_input_colors === 1 && row.secondary_color_rgba_hex !== null)
        // カーボン・色の入力の無い仕上げの描画用の色（Python の apply_finish_display_colors）は任意。
        || (row.display_rgba_hex !== undefined && !COLOR.test(String(row.display_rgba_hex)))
        || row.research_only !== true || row.game_shader_gpu_verified !== false) {
      throw new Error('元Mesh仕上げ研究: 元GameDB色入力・仕上げ契約が不完全です');
    }
    const key = hash.toUpperCase();
    if (resolved.has(key)) throw new Error('元Mesh仕上げ研究: 原本材質ID重複');
    resolved.set(key, Object.freeze({...row, originalMaterialBindingHash:key}));
  }
  return resolved;
}
/**
 * 元Carbinの材質名・64bit bindingを参照製品/第一者Converterの双方から照合する。
 * GLBシーン識別子による互換alias接続の有無に左右されない。
 * 値が双方にある場合は一致必須。欠損/矛盾を代表色で補完しない。
 */
export function sourceMeshFinishPaintIdentity(userData) {
  const values = userData && typeof userData === 'object' ? userData : {};
  const materialNames = ['lo4_material_name', 'lo4fh6_material_name']
    .map(key => values[key])
    .filter(value => typeof value === 'string' && value.trim());
  if (materialNames.length === 2
      && materialNames[0].trim().toLowerCase() !== materialNames[1].trim().toLowerCase()) {
    throw new Error('元Mesh仕上げ研究: 原本材質名の名前空間が矛盾します');
  }
  const bindings = ['lo4_material_binding_hash', 'lo4fh6_material_binding_hash']
    .map(key => values[key])
    .filter(value => value !== null && value !== undefined);
  if (bindings.length === 2 && String(bindings[0]).toUpperCase() !== String(bindings[1]).toUpperCase()) {
    throw new Error('元Mesh仕上げ研究: 原本Carbin材質Hashの名前空間が矛盾します');
  }
  const isCarPaint = materialNames.length > 0 && materialNames[0].trim().toLowerCase() === 'carpaint';
  // carPaint の仲間（carpaint_secondary・carPaint|doorLF_a・ID01_carpaint 等）も、結び付いた記録の仕上げを使う。
  // ペイントの板（carpaint_livery）・載せない材質（nolivery）・内装は除く。
  const base = materialNames.length > 0
    ? materialNames[0].trim().toLowerCase().split('|')[0].replace(/^id\d+_/, '') : '';
  const isFamily = !isCarPaint && base.startsWith('carpaint')
    && !base.includes('livery') && !base.includes('interior');
  if (!isCarPaint && !isFamily) return {carPaint:false,unassigned:false,binding:null};
  const binding = bindings[0];
  if (typeof binding !== 'string' || !HASH.test(binding)) {
    throw new Error('元Mesh仕上げ研究: carPaintの元Carbin材質Hashが不正です');
  }
  const normalized = binding.toUpperCase();
  return {carPaint:true,unassigned:/^0{16}$/.test(normalized),binding:normalized,strict:isCarPaint};
}

export function sourceMeshFinishForPaintMesh(userData, verifiedGroups) {
  if (!(verifiedGroups instanceof Map)) throw new Error('元Mesh仕上げ研究: 原本GLBと契約が未検証です');
  const identity = sourceMeshFinishPaintIdentity(userData);
  if (!identity.carPaint || identity.unassigned) return null;
  // 元Carbin ID=0は「未割当」。他グループの色を流用しない。
  if (!verifiedGroups.has(identity.binding)) {
    if (!identity.strict) return null;
    throw new Error('元Mesh仕上げ研究: carPaintが元C_livery材質IDと対応しません');
  }
  return verifiedGroups.get(identity.binding);
}
export function sourceFinishPrimaryOnlyColor(group) {
  // 数値のRGB 0xRRGGBBを直接渡す。2色仕上げは第二色を保持しつつ研究用主色だけ表示。
  if (!group || !COLOR.test(String(group.primary_color_rgba_hex || ''))) {
    throw new Error('元Mesh仕上げ研究: 元主色が欠けています');
  }
  return Number.parseInt(group.primary_color_rgba_hex.slice(1, 7), 16);
}
export function sourceFinishTrialColor(group, mode = 'primary-only') {
  // 第2色は原本の入力値の比較のみ。2色Glitter演算やXbox外観一致は再現しない。
  if (!['primary-only', 'secondary-only'].includes(mode)) {
    throw new Error('元Mesh仕上げ研究: 色入力の診断モードが不正です');
  }
  // カーボン（織り目の平均）・色の入力の無い仕上げ（金・スチール等の材質自体の色）は、Python が求めた
  // 描画用の色（display_rgba_hex）で描く。サムネイルのカーボンの部品はほぼ黒（Car 382 のボンネット等）。
  if (mode === 'primary-only' && COLOR.test(String(group?.display_rgba_hex || '')))
    return Number.parseInt(group.display_rgba_hex.slice(1, 7), 16);
  // 入力色0の仕上げは色を材質自体が持つ。呼出し元は車体の基本塗装の色を使う。
  if (group?.required_input_colors === 0) return null;
  if (mode === 'secondary-only' && group?.required_input_colors === 2) {
    if (!COLOR.test(String(group.secondary_color_rgba_hex || ''))) {
      throw new Error('元Mesh仕上げ研究: 第2色の原本証拠がありません');
    }
    return Number.parseInt(group.secondary_color_rgba_hex.slice(1, 7), 16);
  }
  // 1色仕上げでは副色を発明せず、常に唯一の原本入力色を表示する。
  return sourceFinishPrimaryOnlyColor(group);
}
