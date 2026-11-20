import {sourceWheelUvAttributeName} from './source-wheel-uv-channel.mjs';
import {ORIGINAL_WHEEL_DEFAULT} from './wheel-finish-source-gate.mjs';
// 記録の色が無効で、仕上げの材質自体の色（金・スチール等）で描くホイールの色の出どころ（viewer.js と同じ値）。
export const FINISH_MATERIAL_DEFINED = 'finish-material-defined';
// 原本ホイールの塗装Shader。既定色はこのShaderの材質（wheelpaint等）だけに使う。
const ORIGINAL_WHEEL_PAINT_FAMILY = 'car_automotive_paint';
/**
 * 署名済みWheelStyle原本mapと、出典が一意のg_CarUserColor0を別入力として
 * 比較する研究用アダプター。原本RGBは上書きせず同じTextureを保持し、
 * 候補プレビューだけTexture alpha＋C_livery primaryと出典済みPBR仕上げを使う。
 * FH6 Shader/PSOとの画素同値性は未証明。通常描画には一切採用しない。
 * 参照製品(AGPL)や参照製品の実装コードは利用しない第一者実装。
 */
export const ORIGIN = 'fh6-local-original-modelbin-materialbin-shaderbin-texture2d-v1';
const MAP_FRAGMENT = '#include <map_fragment>';
export const MAP_ALPHA_ONLY_FRAGMENT = `#ifdef USE_MAP
  vec4 lo4fh6ResearchWheelTexel = texture2D( map, vMapUv );
  diffuseColor.a *= lo4fh6ResearchWheelTexel.a;
#endif`;

// FH6 GameDB List_LiveryMaterialsの塗装仕上げID＋実MaterialBinのShader参照を使用。
// 2/3は共通NormalPaint系。Jaguarなど車種別条件ではない。
// 元MaterialBin/ShaderBinの実SHAが両方そろわない場合、従来の原本画像を保持。
// FH6原本GameDBには56仕上げ（1色/2色/0色）がある。IDによる固定許可表は
// 他の正規1色仕上げを除外し、Textureの仮RGBを完成色にしていた。
// 元GameDB MaterialPath→同じMaterialBin/ShaderBin実SHAと1色入力を照合する。
const GAME_USER_MATERIAL = /^game:\/media\/cars\/_library\/materials\/_fmnext\/usercustomizable\/([a-z0-9_-]+)\.materialbin$/i;
const SOURCE_WHEEL_ONE_COLOR_FAMILIES = new Set([
  'car_automotive_paint_user','car_standard_user',
]);
// 原本10種の1色仕上げのうちCarbonFiber/Candyは異なるShader系。
// 元RGBを捨てるalpha-only合成を適用しない（車種・仕上げID特例ではない）。
// 2026-11-17（テスト版の方針）：ホイールの元Textureは共通の緑一色Swatchで、元RGBに意味が無い。
// 停止すると画像そのものが出ないため、塗装系の特殊Shader（candy/glitter）と2色の仕上げは、
// 参照製品（参照のみ）と同じくプライマリ色と仕上げの数値で近似して描く。
// 2色目・candy/glitterのShader式は描かず、近似で描いたことを材質の印に残す。
// CarbonFiberは織り目のTextureで質感を出す系統で色だけでは表せないが、停止すると画像そのものが
// 出ないため（SUB_BRZ_13等）、プライマリ色と仕上げの数値で近似し、織り目を描かないことを印に残す。
const SOURCE_WHEEL_APPROXIMATED_PAINT_FAMILIES = new Set([
  'car_candy_paint_user','car_glitter_paint_user','car_carbonfiber_user',
]);


const SOURCE_GENERIC_FALLBACK_GROUPS = Object.freeze({
  lip:'RimsLip',rim3:'Rims3',detail:'Wheel1',detail2:'Wheel2',
});
function sourceSignedGenericFallback(routed) {
  if (!routed?.sourceMaterialProven || routed.routeKind !== 'generic_binding'
      || !/^(Front|Rear)WheelPaint1$/.test(routed.group || '')) return false;
  if (routed.routeSource === 'source-signed-generic-primary') {
    return routed.fallbackEvidence === 'original-mati-source-and-external-usercolor0-v1'
      && SOURCE_GENERIC_FALLBACK_GROUPS[routed.token] === routed.expectedGroup;
  }
  const expected=SOURCE_GENERIC_FALLBACK_GROUPS[routed.token];
  if (!expected || routed.expectedGroup !== expected) return false;
  if (routed.token === 'lip') return routed.routeSource === 'reference-wheel-lip-fallback-research'
    && routed.fallbackEvidence === 'reference-wheel-preview-axle-primary-20261112';
  return routed.routeSource === 'reference-wheel-generic-fallback-research'
    && routed.fallbackEvidence === 'reference-wheel-missing-generic-axle-primary-20261112';
}
// 元ModelBinの署名付き直結経路、または検証済み補助Groupだけを仕上げ判定へ進める。
export function sourceWheelFinishHasExactMeshRoute(routed) {
  return routed?.routeSource === 'material-id-evidence'
    || sourceSignedGenericFallback(routed);
}
const inUnit = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;

/**
 * WheelPaintの1色Shaderを元FH6構造だけで採用する標準ゲート。
 * NumInputColors=2は元2色Shader計算式が未接続なので明示拒否。
 * NumInputColors=0は外部Color0による塗装対象ではないため無言の着色をしない。
 * Car ID/仕上げIDで許否を制御するテーブルは使用しない。
 */
export function sourceWheelFinishEvidenceGate(routed, evidence) {
  if (routed?.colorOrigin === ORIGINAL_WHEEL_DEFAULT) {
    return originalWheelDefaultFinishGate(routed, evidence);
  }
  if (!sourceWheelFinishHasExactMeshRoute(routed)
      || !Number.isSafeInteger(routed?.finishCode) || routed.finishCode < 0) {
    return {ok:false,reason:'finish-original-mesh-route-unverified'};
  }
  if (evidence?.status !== 'catalog-candidate'
      || !evidence.candidate
      || evidence.candidate.gameBrdfVerified !== false
      || evidence.candidate.xboxApproved !== false) {
    return {ok:false,reason:'finish-catalog-shader-evidence-missing'};
  }
  const finish = evidence.candidate;
  if (typeof finish.shaderFamily !== 'string' || !finish.shaderFamily)
    return {ok:false,reason:'finish-original-shader-family-unverified'};
  // 色入力の数はGameDBで判定する。二色・特殊一色を標準一色の
  // Texture alpha式に置換すると本来のShader計算を失うため、区別して停止する。
  const originalPath = String(finish.materialPath || '')
    .replace(/\\/g,'/').toLowerCase();
  const sourcePath = GAME_USER_MATERIAL.exec(originalPath);
  if (!sourcePath || sourcePath[1] !== String(finish.materialName || '').toLowerCase()
      || finish.finishId !== routed.finishCode
      || finish.finishOrigin !== 'installed_fh6_materialbin_shaderbin'
      || typeof finish.shaderFamily !== 'string' || !finish.shaderFamily
      || !/^installed_fh6_material_runtime/.test(String(finish.source || ''))
      || !/^[0-9a-f]{64}$/i.test(String(finish.materialSha256 || ''))
      || !/^[0-9a-f]{64}$/i.test(String(finish.shaderSha256 || ''))) {
    return {ok:false,reason:'finish-original-material-shader-unverified'};
  }
  // 色の入力の無い仕上げ（金・スチール等）は、記録の色が無効で仕上げの材質自体の色を使う場合だけ。
  const materialDefined = routed?.colorOrigin === FINISH_MATERIAL_DEFINED;
  if (finish.numInputColors === 0 && !materialDefined)
    return {ok:false,reason:'finish-original-zero-color-not-userpaint'};
  const approximations = [];
  if (materialDefined) approximations.push('finish-material-defined-color');
  else if (finish.numInputColors === 2) approximations.push('two-color-primary-only');
  else if (finish.numInputColors !== 1)
    return {ok:false,reason:'finish-original-color-input-arity-unverified'};
  if (!materialDefined && !SOURCE_WHEEL_ONE_COLOR_FAMILIES.has(finish.shaderFamily)) {
    if (!SOURCE_WHEEL_APPROXIMATED_PAINT_FAMILIES.has(finish.shaderFamily))
      return {ok:false,reason:finish.shaderFamily
        ? 'finish-original-special-one-color-shader-equation-unverified'
        : 'finish-original-shader-family-unverified'};
    approximations.push('special-paint-shader-primary-only:' + finish.shaderFamily);
  }
  if (![finish.roughness,finish.metalness,finish.clearcoat,finish.clearcoatRoughness].every(inUnit)
      || typeof finish.envMapIntensity !== 'number'
      || !Number.isFinite(finish.envMapIntensity)
      || finish.envMapIntensity < 0 || finish.envMapIntensity > 4) {
    return {ok:false,reason:'finish-numeric-source-evidence-unavailable'};
  }
  return {ok:true,finish,finishCode:routed.finishCode,approximations};
}

/**
 * ペイントにホイール記録が無いグループの、原本ホイールMatI既定色の仕上げ検査。
 * GameDBの仕上げIDは無いため、元のホイール塗装Shaderであること・原本SHA・数値範囲を見る。
 */
function originalWheelDefaultFinishGate(routed, evidence) {
  if (!sourceWheelFinishHasExactMeshRoute(routed))
    return {ok:false,reason:'finish-original-mesh-route-unverified'};
  const finish = evidence?.candidate;
  if (evidence?.status !== 'catalog-candidate' || !finish
      || finish.finishOrigin !== ORIGINAL_WHEEL_DEFAULT
      || finish.gameBrdfVerified !== false || finish.xboxApproved !== false)
    return {ok:false,reason:'finish-original-default-evidence-missing'};
  if (finish.shaderFamily !== ORIGINAL_WHEEL_PAINT_FAMILY
      || !/^installed_fh6_material_runtime/.test(String(finish.source || ''))
      || ![finish.materialSha256, finish.materialInstanceSha256, finish.shaderSha256]
        .every(value => /^[0-9a-f]{64}$/i.test(String(value || ''))))
    return {ok:false,reason:'finish-original-default-material-shader-unverified'};
  if (![finish.roughness,finish.metalness,finish.clearcoat,finish.clearcoatRoughness].every(inUnit)
      || typeof finish.envMapIntensity !== 'number' || !Number.isFinite(finish.envMapIntensity)
      || finish.envMapIntensity < 0 || finish.envMapIntensity > 4)
    return {ok:false,reason:'finish-numeric-source-evidence-unavailable'};
  return {ok:true,finish,finishCode:null};
}

// 履歴研究テストが参照する名前は委譲のみ。通常Viewerの入口は上記を直接呼ぶ。
export function wheelPolishedFinishResearchGate(routed, evidence) {
  return sourceWheelFinishEvidenceGate(routed, evidence);
}

// 標準入口が呼び出す単一路。機能ON/OFFを表す引数は持たない。
// 採用可否は元ModelBin/材質ID/UV/外部色/Shader実SHAの入力証拠で決める。
export function sourceWheelPrimaryPaintStandard(mesh, routed, {finishEvidence = null} = {}) {
  // GLTFLoaderはModelBin署名をprimitive geometry.userDataへ置く場合がある。
  // 製品viewer.jsのwheelMetadataForMeshと同じ優先順位で役割を認識する。
  const partType = mesh?.geometry?.userData?.lo4_part_type
    ?? mesh?.userData?.lo4_part_type;
  if (mesh?.isMesh !== true || partType !== 'WheelStyle'
      || mesh.material?.userData?.lo4fh6_original_source_wheel_texture !== ORIGIN
      || mesh.material?.userData?.lo4fh6_wheel_paint_output_color_unresolved !== true
      || mesh.material?.map?.isTexture !== true || typeof mesh.material?.clone !== 'function') {
    return {status:'unchanged',reason:'original-wheel-material-signature-missing'};
  }
  const fallbackCandidate=sourceSignedGenericFallback(routed);
  const sourceRoute=routed?.routeSource === 'material-id-evidence';
  if ((!sourceRoute && !fallbackCandidate)
      || typeof routed?.group !== 'string' || !routed.group
      || !Number.isInteger(routed.color) || routed.color < 0 || routed.color > 0xffffff) {
    return {status:'unchanged',reason:'source-bound-primary-paint-input-unavailable'};
  }
  if (!mesh.material?.color || typeof mesh.material.color.setHex !== 'function'
      || !mesh.geometry?.getAttribute) {
    return {status:'unchanged',reason:'source-material-or-uv-unavailable'};
  }
  const channel = mesh.material.map.channel ?? 0;
  // 原本Wheelの受信GLB・通常GPU保持と同じUV解決を利用する。
  // glTFのTEXCOORD_4以降を任意件数で切り捨てない。
  const uvName = sourceWheelUvAttributeName(channel);
  if (uvName === null || !mesh.geometry.getAttribute(uvName)) {
    return {status:'unchanged',reason:'signed-map-uv-missing'};
  }
  const decision = sourceWheelFinishEvidenceGate(routed, finishEvidence);
  if (!decision.ok) return {status:'unchanged',reason:decision.reason};
  // GLB署名を保持するため原本のThree.js標準PBR材質のみ受け入れる。
  // 物理材質への黙った変換（MeshPhysicalMaterial新規生成）は行わない。
  if (mesh.material?.isMeshStandardMaterial !== true
      && mesh.material?.isMeshPhysicalMaterial !== true) {
    return {status:'unchanged',reason:'wheel-pbr-material-type-unverified'};
  }
  const material = mesh.material.clone();
  const sourceMap = mesh.material.map;
  if (material.map !== sourceMap || !material.color?.setHex) {
    return {status:'unchanged',reason:'cloned-material-lost-source-map'};
  }
  material.color.setHex(routed.color);
  // 今回のVivioはGameDB ID16=AluminumPolished。0.0/1.0/1.32は
  // 既存source-safe PBR対応値であってFH6の命令レベルBRDF値ではない。
  material.roughness = decision.finish.roughness;
  material.metalness = decision.finish.metalness;
  material.envMapIntensity = decision.finish.envMapIntensity;
  const physicalClearcoat = material.isMeshPhysicalMaterial === true;
  if (physicalClearcoat) {
    material.clearcoat = decision.finish.clearcoat;
    material.clearcoatRoughness = decision.finish.clearcoatRoughness;
  }
  const prevCompile = material.onBeforeCompile;
  material.onBeforeCompile = shader => {
    if (typeof prevCompile === 'function') prevCompile(shader);
    if (typeof shader?.fragmentShader !== 'string'
        || !shader.fragmentShader.includes(MAP_FRAGMENT)) {
      throw new Error('研究用原本WheelPaint: Three.js map_fragment接続がありません');
    }
    shader.fragmentShader = shader.fragmentShader.replace(MAP_FRAGMENT, MAP_ALPHA_ONLY_FRAGMENT);
  };
  const oldKey = material.customProgramCacheKey?.bind(material);
  material.customProgramCacheKey = () => (typeof oldKey === 'function' ? oldKey() : '')
    + '|lo4fh6-wheel-primary-alpha-compare-v1';
  material.userData = {
    ...material.userData,
    lo4fh6_original_source_wheel_texture: ORIGIN,
    lo4fh6_wheel_paint_source_primary_standard: true,
    lo4fh6_wheel_paint_research_group: routed.group,
    lo4fh6_wheel_paint_fls_fallback_research: fallbackCandidate ? routed.fallbackEvidence : null,
    lo4fh6_wheel_paint_research_finish_id: decision.finishCode,
    lo4fh6_wheel_paint_research_finish_name: decision.finish.materialName,
    lo4fh6_wheel_paint_research_clearcoat_applied: physicalClearcoat,
    lo4fh6_wheel_paint_research_shader_exact: false,
    // 2色目・特殊Shaderを描かずプライマリ色で近似した場合の内訳（空なら近似なし）。
    lo4fh6_wheel_paint_shader_approximation: Array.isArray(decision.approximations)
      ? [...decision.approximations] : [],
    lo4fh6_wheel_paint_research_xbox_approved: false,
  };
  material.needsUpdate = true;
  return {
    status:'source-signed-applied',reason:'source-primary-color-original-alpha-and-evidenced-polished-finish',
    material,group:routed.group,finishName:decision.finish.materialName,
    finishCode:decision.finishCode,clearcoatApplied:physicalClearcoat,
    fallbackEvidence: fallbackCandidate ? routed.fallbackEvidence : null,
    xboxApproved:false,shaderExact:false,
  };
}


/**
 * 通常入口に昇格できるのは原本MaterialBin/ShaderBinの実SHAと、
 * 元WheelStyle材質IDから取得した色入力が同時に存在する場合だけ。
 * Lipの補助経路は原本材質ID・元グループ・既知の参照製品観測証拠が揃う場合に限る。
 * ゲームShaderの画素一致を表明せず、Windows受入済みの近似機能として扱う。
 */
export function sourceWheelStandardAutoEligible(routed, record) {
  const direct = routed?.routeSource === 'material-id-evidence';
  const generic = sourceSignedGenericFallback(routed);
  if (!direct && !generic) return {ok:false,reason:'wheel-paint-route-unsigned'};
  // ペイントにホイール記録が無いグループ：原本ホイールMatIの既定色（Pythonが補った記録）。
  if (record?.color_origin === ORIGINAL_WHEEL_DEFAULT) {
    const finish = record?.finish_material;
    if (routed?.colorOrigin !== ORIGINAL_WHEEL_DEFAULT || record.primary_color_enabled !== true
        || !Number.isInteger(routed.color) || routed.color < 0 || routed.color > 0xffffff
        || finish?.finish_origin !== ORIGINAL_WHEEL_DEFAULT
        || finish?.shader_family !== ORIGINAL_WHEEL_PAINT_FAMILY
        || !['source_material_sha256','source_material_instance_sha256','source_shader_sha256']
          .every(key => /^[0-9a-f]{64}$/i.test(String(finish?.[key] || '')))) {
      return {ok:false,reason:'wheel-paint-original-default-unverified'};
    }
    return {ok:true,reason:'original-wheel-mati-default'};
  }
  // 記録の色が無効で仕上げだけが指定されたグループ：仕上げの材質自体の色（金・スチール等）。
  // 原本MaterialBin/ShaderBinの照合済みSHAと、Pythonが求めた material_defined_rgba_hex が描く色と
  // 一致する場合だけ（Car 3645・4313 の GoldPolished のホイール）。
  if (routed?.colorOrigin === FINISH_MATERIAL_DEFINED) {
    const finish = record?.finish_material;
    const defined = String(finish?.material_defined_rgba_hex || '');
    if (record?.primary_color_enabled === true
        || !(Number(record?.finish_code_raw) > 0) || record?.finish_code_raw !== routed.finishCode
        || !/^#[0-9a-f]{8}$/i.test(defined)
        || !Number.isInteger(routed.color) || routed.color !== Number.parseInt(defined.slice(1, 7), 16)
        || finish?.catalog_match !== true
        || finish?.finish_origin !== 'installed_fh6_materialbin_shaderbin'
        || !/^[0-9a-f]{64}$/i.test(finish.source_material_sha256 || '')
        || !/^[0-9a-f]{64}$/i.test(finish.source_shader_sha256 || '')) {
      return {ok:false,reason:'wheel-finish-material-color-unverified'};
    }
    return {ok:true,reason:'finish-material-defined-color'};
  }
  if (record?.primary_color_enabled !== true
      || record?.finish_code_raw !== routed.finishCode
      || !Number.isInteger(routed.color) || routed.color < 0 || routed.color > 0xffffff) {
    return {ok:false,reason:'wheel-paint-input-unverified'};
  }
  const finish = record?.finish_material;
  if (finish?.catalog_match !== true
      || finish?.finish_origin !== 'installed_fh6_materialbin_shaderbin'
      || !/^[0-9a-f]{64}$/i.test(finish.source_material_sha256 || '')
      || !/^[0-9a-f]{64}$/i.test(finish.source_shader_sha256 || '')) {
    return {ok:false,reason:'wheel-finish-original-sha-unverified'};
  }
  // 二色を要するShaderでは原本の色1もルートへ接続されている必要がある。
  // ただし接続済みであっても、Shaderの二色計算式未確認なら描画ゲートで停止する。
  if (finish.num_input_colors === 2) {
    const rawSecond = String(record.secondary_color_rgba_hex || '');
    const second = routed.secondaryColor;
    if (record.secondary_color_enabled !== true
        || !/^#[0-9a-f]{8}$/i.test(rawSecond)
        || !Number.isSafeInteger(second) || second < 0 || second > 0xffffff
        || second.toString(16).padStart(6,'0').toLowerCase() !== rawSecond.slice(1,7).toLowerCase()) {
      return {ok:false,reason:'wheel-paint-second-color-unverified'};
    }
  }
  return {ok:true,reason:direct?'exact-original-material-id':'verified-generic-source-evidence'};
}

/**
 * 研究用ユニットテストとの互換入口。製品Viewerでは呼ばない。
 * 歴史比較テスト以外で enabled を使用しないことを標準入口検査が保証する。
 */
export function sourceWheelPrimaryPaintResearch(mesh, routed, {enabled = false, finishEvidence = null} = {}) {
  if (enabled !== true) return {status:'unchanged',reason:'research-not-requested'};
  const result = sourceWheelPrimaryPaintStandard(mesh, routed, {finishEvidence});
  if (result.status !== 'source-signed-applied') return result;
  // 歴史研究テスト用の互換メタデータのみ。製品の標準関数には渡さない。
  result.material.userData.lo4fh6_wheel_paint_source_primary_research = true;
  return {...result,status:'research-only'};
}
