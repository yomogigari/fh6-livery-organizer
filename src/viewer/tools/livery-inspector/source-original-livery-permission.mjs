/**
 * 原本Shaderの研究GLBに限り、明示的な0面許可を「情報欠落」と取り違えない。
 * 旧r485・Windows受入済みGLBにこの研究フラグはなく、従来の許可処理へ戻す。
 * 原本Mask/paintの実ピクセル合成、Facing、ゲームShader一致を証明する関数ではない。
 */
export function sourceOriginalResearchLiverySides(userData, category, sectionCount = 11) {
  if (userData?.lo4fh6_shader_role_trial_unapproved !== true) return null;
  const declared = userData.lo4_allowed_sides;
  if (!Number.isInteger(declared) || declared < 0 || declared >= (1 << sectionCount)) {
    throw new Error('原本Shader研究GLB: 面許可ビットが欠落または不正です');
  }
  if (category === 'glass') {
    // car_window/car_glassは材質分類。ガラスのペイント許可は独立した証拠が必要。
    if ((declared & ~0x7c0) !== 0) {
      throw new Error('原本Shader研究GLB: ガラスへ外板面の許可ビットが混入しています');
    }
    if (declared !== 0 && (
      userData.lo4fh6_source_mask_and_saved_alpha_sections_present !== true ||
      userData.lo4fh6_source_per_fragment_mask_and_alpha_sampling_required !== true
    )) {
      throw new Error('原本Shader研究GLB: 未証明のガラス塗装許可を拒否しました');
    }
  }
  if (category === 'paint' && (declared & ~0x3f) !== 0) {
    throw new Error('原本Shader研究GLB: 外板へガラス面の許可ビットが混入しています');
  }
  return declared;
}

/**
 * 研究GLBの原本Shader由来役割を保持する。nullは旧正常版の自動分類へ委譲。
 * 元Shader分類は表示正解の証明ではないため、研究フラグがない入力には適用しない。
 */
export function sourceOriginalResearchMeshRole(userData, hasUv3) {
  if (userData?.lo4fh6_shader_role_trial_unapproved !== true) return null;
  const role = userData.lo4_role;
  if (!['paint', 'glass', 'trim', 'dark', 'hidden'].includes(role)) {
    throw new Error('原本Shader研究GLB: 描画役割が未定義または不正です');
  }
  if (role === 'paint' && !hasUv3) {
    throw new Error('原本Shader研究GLB: paintに元UV3がありません');
  }
  return role;
}
