/** 第一者・原本DXIL由来のタイヤ側面文字RGBサブ経路、研究専用。
 * 元FH6 ShaderBin/PSO/VS0は添付・配布せず、実スロットとSSA片から検証済み式だけ記述。
 * テクスチャの後処理（ゲームPBR/Mask/Normal）は未移植。製品既定ON禁止。
 */
export const FEOW_ORIGINAL = Object.freeze({
  pso: 'a320f94b94ba20631e89c3a0108a6032c39afd8646272dd3feb11e93b6f7d59f',
  vso: '096800d7498a51dc453295af36d1bc963ed62cee3da5ff2c8bae51a66b273dda',
  texture30: 'd56d24584af7dc779a2a51a825d9f673f092807e12d97891bbeb6d74a2d9d72c',
  texture29: 'd6e93c32f243dfe6de2ad651e6635ddac14b8ded3e0e032cbe8484ab3f2a53d4',
});
export function qualifyResearchParameters(e) {
  const issues = [];
  if (e?.explicitResearchOn !== true && e?.sourceVerifiedAutomatic !== true) issues.push('not-original-material-mode');
  if (e?.shaderPsoSha !== FEOW_ORIGINAL.pso || e?.shaderVsoSha !== FEOW_ORIGINAL.vso) issues.push('not-verified-original-dxil');
  // 文字Texture 2枚は原本MatIごとに異なる（FEOW以外へ一般化）。SHAはPython側が原本から照合済み。
  if (!/^[0-9a-f]{64}$/.test(String(e?.texture30SwatchSha || ''))
      || !/^[0-9a-f]{64}$/.test(String(e?.texture29SwatchSha || ''))) issues.push('not-original-two-textures');
  if (!Array.isArray(e?.tiling) || e.tiling.length !== 2
      || e.tiling.some(x=>!Number.isFinite(x) || x < 0.001 || x > 100)) issues.push('invalid-original-mati-tiling');
  if (!Number.isFinite(e?.slide) || Math.abs(e.slide) > 16) issues.push('invalid-original-mati-slide');
  // Runtime carParams CB4[61] and CB4[31+wheel].w are still UNKNOWN. Synthetic A/B is only allowed when explicitly tagged.
  if (e?.runtimeSource !== 'synthetic-research-not-xbox') issues.push('real-runtime-carparams-not-yet-source-verified');
  if (!Number.isFinite(e?.wheelParam) || e.wheelParam <= 0) issues.push('invalid-carparams-wheel-text-factor');
  if (!Number.isFinite(e?.wheelBlend)) issues.push('invalid-carparams-wheel-text-blend');
  if (e?.xboxApproved !== false || (e?.productDefaultChanged !== false && e?.sourceVerifiedAutomatic !== true)) issues.push('unapproved-default-change');
  return {ok:issues.length===0,issues,originalShaderEquivalent:false};
}
export function createDxilTextResearchMaterial(THREE, base, texture30, texture29, evidence) {
  const gate=qualifyResearchParameters(evidence);
  if (!gate.ok) throw new Error('FEOW-DXIL-RESEARCH-REJECT:'+gate.issues.join(','));
  if (!base?.isMaterial || texture30?.isTexture!==true || texture29?.isTexture!==true)
    throw new Error('FEOW-DXIL-RESEARCH-REJECT:not-actual-GLTF-texture');
  // 繰り返し数とずらし量は原本MatI→親MaterialBin→ShaderBin DFPRの値（GLB extras）を使う。
  // FEOW（street_FE_OW）はMatIの(0.25,1.2)/-0.28で、従来の固定値と同じ。
  const mat = base.clone();
  mat.map = texture30;
  mat.color.setRGB(1,1,1);
  mat.transparent = false;
  mat.opacity = 1;
  mat.depthWrite = true;
  mat.side = THREE.DoubleSide;
  mat.userData = {...mat.userData,lo4fh6_dxil_text_source_auto:evidence.sourceVerifiedAutomatic===true,shaderEquivalent:false,source:evidence.runtimeSource};
  mat.onBeforeCompile=(shader)=>{
    shader.uniforms.feowTex29={value:texture29};
    shader.uniforms.feowTiling={value:new THREE.Vector2(...evidence.tiling)};
    shader.uniforms.feowSlide={value:evidence.slide};
    shader.uniforms.feowWheelParam={value:evidence.wheelParam};
    shader.uniforms.feowWheelBlend={value:evidence.wheelBlend};
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
      uniform sampler2D feowTex29;
      uniform vec2 feowTiling;
      uniform float feowSlide;
      uniform float feowWheelParam;
      uniform float feowWheelBlend;`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',`
      // Source-proven RGB subgraph of _Standard/car_tires_pgCarLightScenario PS DXIL.
      // The wheel-specific runtime CB4 values here are explicitly research-only unless verified.
      vec2 feowTextUv = vec2(vMapUv.x * feowTiling.x,
        feowTiling.y * clamp((vMapUv.y + feowSlide) * (16.0/min(16.0, feowWheelParam)),0.0,1.0));
      vec3 feowC30 = texture2D(map,feowTextUv).rgb;
      vec3 feowC29 = texture2D(feowTex29,feowTextUv).rgb;
      diffuseColor.rgb *= mix(feowC30,feowC29,clamp(feowWheelBlend,0.0,1.0));
    `);
  };
  mat.customProgramCacheKey=()=> 'feow-dxil-text-rgb-source-auto-v1';
  return mat;
}

/** 原本CarParametersDataが取得されていない時点の検査。
 * 実画像二枚を同時にglTFで保持し、四輪の正常なTire/Wheelを保護する。
 */
const FEOW_WHEELS = ['front_left','front_right','rear_left','rear_right'];
export function auditOriginalDxilTwoTextures(root) {
  const issues = [];
  let wheels = 0, tires = 0;
  const sourceWheelRoles = new Set();
  const perWheelTires = new Map();
  const perWheelText = new Map();
  const sidewalls = [];
  root?.traverse?.(mesh => {
    if (!mesh?.isMesh) return;
    if (mesh.userData?.lo4_part_type === 'WheelStyle') {
      wheels++;
      if (FEOW_WHEELS.includes(mesh.userData.lo4_wheel_morph_wheel))
        sourceWheelRoles.add(mesh.userData.lo4_wheel_morph_wheel);
    }
    if (mesh.userData?.lo4_part_type !== 'Tire' || mesh.userData?.lo4_role === 'hidden') return;
    tires++;
    const wheel = mesh.userData.lo4_tire_source_wheel;
    const role = mesh.userData.lo4_tire_original_material_name;
    if (!FEOW_WHEELS.includes(wheel) || typeof role !== 'string' || !role) {
      issues.push('unrecognized-original-tire-role'); return;
    }
    perWheelTires.set(wheel, (perWheelTires.get(wheel) || 0) + 1);
    const m = mesh.material, e = m?.userData || {};
    // 文字MatIは役割名でなくPython側の原本文字署名で判定する（sidewall/whitewall等）。
    if (e.lo4fh6_original_feow_two_textures !== true) return;
    perWheelText.set(wheel, (perWheelText.get(wheel) || 0) + 1);
    if (!mesh.geometry?.getAttribute?.('uv') ||
        !m?.map?.isTexture || !m?.emissiveMap?.isTexture ||
        !/^[0-9a-f]{64}$/.test(String(e.feow_dxil_t30_swatch_sha256 || '')) ||
        !/^[0-9a-f]{64}$/.test(String(e.feow_dxil_t29_swatch_sha256 || '')) ||
        !Array.isArray(e.lo4fh6_source_text_uv_tiling) || e.lo4fh6_source_text_uv_tiling.length !== 2 ||
        !Number.isFinite(e.lo4fh6_source_text_slide) ||
        e.feow_dxil_shader_pso_sha256 !== FEOW_ORIGINAL.pso ||
        e.feow_dxil_shader_vso_sha256 !== FEOW_ORIGINAL.vso ||
        e.feow_dxil_runtime_source !== 'UNKNOWN_NOT_IN_MODEL_ASSETS' ||
        e.feow_dxil_product_default_on !== false ||
        !Array.isArray(e.feow_dxil_original_mesh_affine_uv0) ||
        e.feow_dxil_original_mesh_affine_uv0.length !== 4 ||
        e.feow_dxil_original_mesh_affine_uv0.some(v => !Number.isFinite(v))) {
      issues.push('source-signature-or-two-texture-missing'); return;
    }
    sidewalls.push(mesh);
  });
  // 原本の材質構成はTireごとに異なる（3役割・2役割・Dually等）。役割の内訳はPython側が
  // 原本MatIで照合済み。ここでは4輪すべてにTireと同数の文字MatIがあることを確認する。
  const textCounts = FEOW_WHEELS.map(w => perWheelText.get(w) || 0);
  if (FEOW_WHEELS.some(w => !(perWheelTires.get(w) > 0))) issues.push('duplicate-or-missing-tire-role');
  // 車種/ホイールごとに原本primitive数は異なる。58というJaguar実測を固定条件にしない。
  if (wheels < 4 || sourceWheelRoles.size !== 4) issues.push('not-four-signed-original-wheelstyle-groups');
  if (textCounts[0] < 1 || textCounts.some(n => n !== textCounts[0])
      || sidewalls.length !== textCounts[0] * 4) issues.push('not-four-wheel-text-material');
  return {ok:issues.length===0,issues,originalWheels:wheels,originalTires:tires,
    sidewalls:sidewalls.length,sourceTextTwoImagesLoaded:sidewalls.length===4,
    gameRuntimeCB4Verified:false,windowsResearchOnly:true,originalDXILPostPbrEquivalent:false};
}

/** FEOW原本MeshBlob UV0 affine (VS) → DXIL文字UV合成(PS)を研究だけで適用。 */
export function createDxilVsPsResearchMaterial(THREE, mesh, evidence) {
  const base=mesh?.material;
  if (base?.map?.isTexture !== true || base?.emissiveMap?.isTexture !== true)
    throw new Error('FEOW-DXIL-RESEARCH-REJECT:two-original-textures-not-loaded');
  const affine=base.userData?.feow_dxil_original_mesh_affine_uv0;
  if (!Array.isArray(affine) || affine.length!==4 || affine.some(x => !Number.isFinite(x)))
    throw new Error('FEOW-DXIL-RESEARCH-REJECT:meshblob-affine-unverified');
  const result = createDxilTextResearchMaterial(THREE,base,base.map,base.emissiveMap,evidence);
  // Emissive texture is only used to transport original texture29 through GLTFLoader.
  result.emissiveMap=null;
  result.emissive.setRGB(0,0,0);
  const originalCompile=result.onBeforeCompile;
  result.onBeforeCompile=shader => {
    originalCompile(shader);
    shader.uniforms.feowMeshAffine={value:new THREE.Vector4(...affine)};
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>',
       '#include <common>\n uniform vec4 feowMeshAffine;');
    const search='vec2 feowTextUv = vec2(vMapUv.x * feowTiling.x,\n        feowTiling.y * clamp((vMapUv.y + feowSlide) * (16.0/min(16.0, feowWheelParam)),0.0,1.0));';
    const change='vec2 feowVertexUv = vMapUv.xy * vec2(feowMeshAffine.y,feowMeshAffine.w) + vec2(feowMeshAffine.x,feowMeshAffine.z);\n'
      +'      vec2 feowTextUv = vec2(feowVertexUv.x * feowTiling.x,\n'
      +'        feowTiling.y * clamp((feowVertexUv.y + feowSlide) * (16.0/min(16.0, feowWheelParam)),0.0,1.0));';
    if (!shader.fragmentShader.includes(search)) throw new Error('FEOW shader template changed; fail closed');
    shader.fragmentShader=shader.fragmentShader.replace(search,change);
  };
  result.customProgramCacheKey=()=>'feow-DXIL-original-VSPS-two-texture-source-auto-v1';
  return result;
}
