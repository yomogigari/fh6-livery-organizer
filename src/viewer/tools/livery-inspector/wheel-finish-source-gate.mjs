/**
 * rM050: FH6原本に紐付くホイール仕上げを数値型・存在・原本帰属で監査する。
 * 概算PBR値をゲームの真値とは呼ばない。元のcolor/route判定は変更しない。
 * 第三者の実装コードは取り込まず、欠落パラメータの Number(null)→0 誤認を防ぐ。
 */
const FIELDS = ['roughness', 'metalness', 'clearcoat', 'clearcoat_roughness', 'env_map_intensity'];
// ペイントにホイール記録が無いとき、Pythonが原本ホイールMatI（MatI→親MaterialBin→
// ShaderBin既定値）から補った既定色。GameDBの仕上げIDは持たない。
export const ORIGINAL_WHEEL_DEFAULT = 'original-wheel-mati-default';

const ownFinite = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key)
  && typeof obj[key] === 'number' && Number.isFinite(obj[key]);

export function sourceWheelFinishEvidence(record) {
  const finish = record?.finish_material;
  if (record?.color_origin === ORIGINAL_WHEEL_DEFAULT
      && finish?.finish_origin === ORIGINAL_WHEEL_DEFAULT) {
    return originalWheelDefaultFinishEvidence(finish);
  }
  if (!finish || finish.catalog_match !== true) {
    return {status: 'unverified-catalog', candidate: null};
  }
  if (!Number.isInteger(record?.finish_code_raw) || record.finish_code_raw < 0
      || !Number.isInteger(finish.finish_id) || finish.finish_id !== record.finish_code_raw
      || typeof finish.material_name !== 'string' || !finish.material_name.trim()
      || typeof finish.shader_family !== 'string' || !finish.shader_family.trim()) {
    return {status: 'unverified-identity', candidate: null};
  }
  const values = finish.viewer_candidate;
  if (!values || typeof values !== 'object'
      || FIELDS.some(key => !ownFinite(values, key))) {
    return {status: 'missing-numeric-field', candidate: null};
  }
  const inUnit = ['roughness', 'metalness', 'clearcoat', 'clearcoat_roughness']
    .every(key => values[key] >= 0 && values[key] <= 1);
  if (!inUnit || values.env_map_intensity < 0 || values.env_map_intensity > 4) {
    return {status: 'out-of-bounds', candidate: null};
  }
  return {
    status: 'catalog-candidate',
    candidate: {
      roughness: values.roughness,
      metalness: values.metalness,
      clearcoat: values.clearcoat,
      clearcoatRoughness: values.clearcoat_roughness,
      envMapIntensity: values.env_map_intensity,
      materialName: finish.material_name,
      shaderFamily: finish.shader_family,
      // GameDB ID と本人インストール済み原本MaterialBin/ShaderBinの実SHA。
      // 仕上げID2/3等に対して、カタログ名だけで色を塗らないための証拠。
      finishId: finish.finish_id,
      finishOrigin: finish.finish_origin || null,
      materialSha256: finish.source_material_sha256 || null,
      shaderSha256: finish.source_shader_sha256 || null,
      materialPath: finish.material_path || null,
      numInputColors: finish.num_input_colors,
      source: typeof values.source === 'string' ? values.source : '',
      basis: typeof values.basis === 'string' ? values.basis : '',
      gameBrdfVerified: false,
      xboxApproved: false,
    },
  };
}

/** 原本ホイールMatIの既定色の仕上げ。名前・Shader・SHA・数値の範囲を検査する。 */
function originalWheelDefaultFinishEvidence(finish) {
  if (typeof finish.material_name !== 'string' || !finish.material_name.trim()
      || typeof finish.shader_family !== 'string' || !finish.shader_family.trim()
      || !['source_material_sha256', 'source_material_instance_sha256', 'source_shader_sha256']
        .every(key => /^[0-9a-f]{64}$/i.test(String(finish[key] || '')))) {
    return {status: 'unverified-identity', candidate: null};
  }
  const values = finish.viewer_candidate;
  if (!values || typeof values !== 'object'
      || FIELDS.some(key => !ownFinite(values, key))) {
    return {status: 'missing-numeric-field', candidate: null};
  }
  const inUnit = ['roughness', 'metalness', 'clearcoat', 'clearcoat_roughness']
    .every(key => values[key] >= 0 && values[key] <= 1);
  if (!inUnit || values.env_map_intensity < 0 || values.env_map_intensity > 4) {
    return {status: 'out-of-bounds', candidate: null};
  }
  return {
    status: 'catalog-candidate',
    candidate: {
      roughness: values.roughness,
      metalness: values.metalness,
      clearcoat: values.clearcoat,
      clearcoatRoughness: values.clearcoat_roughness,
      envMapIntensity: values.env_map_intensity,
      materialName: finish.material_name,
      shaderFamily: finish.shader_family,
      finishId: null,
      finishOrigin: ORIGINAL_WHEEL_DEFAULT,
      materialSha256: finish.source_material_sha256,
      materialInstanceSha256: finish.source_material_instance_sha256,
      shaderSha256: finish.source_shader_sha256,
      materialPath: null,
      numInputColors: finish.num_input_colors,
      source: typeof values.source === 'string' ? values.source : '',
      basis: typeof values.basis === 'string' ? values.basis : '',
      gameBrdfVerified: false,
      xboxApproved: false,
    },
  };
}

/** 原本一致でないcolorはこの監査では認可しない。 */
export function wheelFinishDecision(record, {hasExactMeshRoute = false} = {}) {
  if (!hasExactMeshRoute) return {status: 'unverified-mesh-route', candidate: null};
  // 記録の色が無効で仕上げだけが指定され、仕上げの材質自体の色（Python の material_defined_rgba_hex、
  // 金・スチール等）がある場合は、その仕上げで描く（色は viewer.js wheelPaintColorForMesh が使う）。
  const materialDefined = record?.primary_color_enabled !== true
    && Number.isInteger(record?.finish_code_raw) && record.finish_code_raw > 0
    && /^#[0-9a-fA-F]{8}$/.test(String(record?.finish_material?.material_defined_rgba_hex || ''));
  if (materialDefined) return sourceWheelFinishEvidence(record);
  if (record?.primary_color_enabled !== true
      || !/^#[0-9a-fA-F]{8}$/.test(String(record?.primary_color_rgba_hex || ''))) {
    return {status: 'primary-color-disabled', candidate: null};
  }
  return sourceWheelFinishEvidence(record);
}
