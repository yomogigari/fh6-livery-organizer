/**
 * FH6原本MaterialBin/ShaderBinの署名付き仕上げをViewer既存PBRへ渡す研究アダプター。
 * ゲーム側のDXIL計算式は未復元。原本色の混合も行わない。
 * 元C_livery・GLB SHA検証済みの材質グループ以外では呼び出してはならない。
 */
const SOURCE_FINISH = new Map([
  [14, Object.freeze({
    name:'AluminumBrushed', inputColors:1, shaderFamily:'car_standard_user',
    materialSha:'07b72e8c6fa5975e77d572a25ea299c8a550e38c8e5ae21dde4281a3d77b5f8b',
    shaderSha:'da1129863c2cebe7ac5c247750ac06a0674847737d5fd37d73fdcd44ec41abd0',
    // 既存Viewer::r175AutomotiveBaselineCandidate が読むsnake_caseに統一。
    parameters:Object.freeze({roughness_shift:-0.600000024}),
    viewerCandidate:Object.freeze({roughness:0.32,metalness:1.0,env_map_intensity:1.70,
      clearcoat:1.0,clearcoat_roughness:0.06,base_clearcoat_scale_home_soft:0.62})
  })],
  [72, Object.freeze({
    name:'MetallicGlitterPaint', inputColors:2, shaderFamily:'car_glitter_paint_user',
    materialSha:'7313b11795d1d080a31c7072ccda9a82110b87d32c6984967308a31ac1653644',
    shaderSha:'4eb9a890c9fba7e899a78fd5695f67d2a20743f7dc0a108cf0c62e01d4f39f03',
    parameters:Object.freeze({flake_roughness:0.25,flake_coverage:0.5,clearcoat_roughness:0.0}),
    viewerCandidate:Object.freeze({roughness:0.25,metalness:0.06,env_map_intensity:1.30,
      clearcoat:1.0,clearcoat_roughness:0.0,base_clearcoat_scale_home_soft:0.22,
      flake_response_strength:0.0,glancing_response_strength:0.0})
  })]
]);
const HEX8 = /^#[\da-f]{8}$/i;
// ラメの粒の描き方に使う、仕上げ 72（MetallicGlitterPaint）の材質の値（2026-11-18）。
// 上の materialSha の MaterialBin から読んだ値（UserColorSwitchBool 真、入れ替え・角度の切り替えは偽、GlitterIntensity 1.0）。
const SOURCE_FINISH_FLAKE = new Map([
  [72, Object.freeze({
    user_color_enabled:true, user_color_swap_primary_secondary:false,
    user_color_flop_switch1:false, user_color_flop_switch2:false, glitter_intensity:1.0,
  })],
]);
/**
 * 部品ごとの仕上げのラメの入力（材質の値と、部品の記録の第 2 色）。ラメの仕上げでなければ null。
 * Viewer の basePaintFlakeLayer がこの形を受け取る。
 */
export function researchSourceFinishFlakeInput(group) {
  const flake = group ? SOURCE_FINISH_FLAKE.get(group.finish_code_raw) : null;
  const source = group ? SOURCE_FINISH.get(group.finish_code_raw) : null;
  if (!flake || !source || !HEX8.test(String(group.secondary_color_rgba_hex || ''))) return null;
  return {
    material_name:source.name, shader_family:source.shaderFamily,
    game_material_parameters:{...source.parameters, ...flake},
    secondary_color_rgba_hex:String(group.secondary_color_rgba_hex),
  };
}
export function researchSourceFinishBasePaint(group) {
  if (!group || group.research_only !== true || group.game_shader_gpu_verified !== false) {
    throw new Error('元PBR研究: 原本照合済み・未承認材質グループのみ受け入れます');
  }
  const source=SOURCE_FINISH.get(group.finish_code_raw);
  if (!source || group.finish_material_name !== source.name
      || group.required_input_colors !== source.inputColors
      || !HEX8.test(group.primary_color_rgba_hex)
      || (source.inputColors===2 && !HEX8.test(group.secondary_color_rgba_hex))
      || (source.inputColors===1 && group.secondary_color_rgba_hex!==null)) {
    throw new Error('元PBR研究: 原本仕上げ・GameDB色入力・Shader対応が未解決です');
  }
  return {
    material_name:source.name,shader_family:source.shaderFamily,
    source_material_sha256:source.materialSha,source_shader_sha256:source.shaderSha,
    game_material_parameters:source.parameters,
    viewer_candidate:{...source.viewerCandidate,source:'source_finish_material_firstparty_viewer_research_only'},
    original_finish_code_raw:group.finish_code_raw,
    native_two_color_shader_applied:false,
    shader_equation_approximated:true,
    product_default_modified:false,
    windows_xbox_approved:false,
  };
}

/**
 * 元Carbin/YRVLに対応する色入力は、PBR仕上げ候補の対応可否とは独立している。
 * PR73で実証したTVRのID1/71など、FH6 Shader式・PBR値未確認の仕上げは
 * 研究用主/副色入力だけ描画し、従来の製品PBRを保持する。
 * 識別済み14/72については元SHA署名検査の厳格ゲートを維持する。
 */
export function researchSourceFinishCandidate(group) {
  // 入力色0（色を仕上げの材質自体が持つ）は、未知の仕上げと同じく候補なし（従来の物理特性）。
  if (group && group.research_only === true && group.game_shader_gpu_verified === false
      && Number.isSafeInteger(group.finish_code_raw) && group.finish_code_raw >= 0
      && group.required_input_colors === 0) {
    return null;
  }
  if (!group || group.research_only !== true || group.game_shader_gpu_verified !== false
      || !Number.isSafeInteger(group.finish_code_raw) || group.finish_code_raw < 0
      || ![1,2].includes(group.required_input_colors)
      || !HEX8.test(String(group.primary_color_rgba_hex || ''))
      || (group.required_input_colors === 2
          && !HEX8.test(String(group.secondary_color_rgba_hex || '')))
      || (group.required_input_colors === 1 && group.secondary_color_rgba_hex !== null)) {
    throw new Error('元PBR研究: 元Carbin/YRVLの入力色または未承認契約が不正です');
  }
  if (!SOURCE_FINISH.has(group.finish_code_raw)) {
    // 未知仕上げをID14/72のPBRへすり替えない。
    // Viewer側の liveryMaterial(sourceFinish) は厳密な元色入力だけを使う。
    return null;
  }
  return researchSourceFinishBasePaint(group);
}
