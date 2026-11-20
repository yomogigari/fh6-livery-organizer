/**
 * WheelStyleの材質IDはModelBin内部スコープ。別モデルの同一IDを流用しない。
 * 原本ModelBin/MatI署名と元FH6のグループ対応だけを判定し、
 * 原本Shaderの完成RGB/ゲームGPU画素一致を主張しない。
 */
export function normalizedWheelSource(value) {
  return String(value ?? '').replaceAll('\\', '/').replace(/^\/+/, '').toLowerCase();
}
export function normalizedWheelMaterial(value) {
  let token = normalizedWheelSource(value).split('/').pop().split('|')[0];
  if (token.endsWith('.materialbin')) token = token.slice(0, -12);
  return token;
}
const SHA256 = /^[0-9a-f]{64}$/i;
const normalizedSha = value => typeof value === 'string' ? value.toLowerCase() : '';
/**
 * ModelBinパス + Material ID + Tokenに加え、ModelBin実バイトまたは
 * MatI実バイトのSHAを照合。旧GLBにはMatI SHAによる等価証明を許す。
 * 新旧どちらも原本署名が片側だけ/矛盾する場合は描画色を採用しない。
 * 合成旧テスト専用の両署名完全不在レコードは後方互換とし、
 * 新しい実原本診断では必ず署名ありのレコードを生成する。
 */
export function sourceBoundWheelPaintRoute(rows, {
  sourceEntry, materialId, materialName,
  sourceModelbinSha256='', materialInstanceSha256='',
  requireSourceSignature=false,
} = {}) {
  if (!Array.isArray(rows) || typeof sourceEntry !== 'string' || !sourceEntry
      || materialId === null || materialId === undefined || materialId === '') return null;
  const source = normalizedWheelSource(sourceEntry);
  const token = normalizedWheelMaterial(materialName);
  const id = Number(materialId);
  if (!source.includes('/wheels/') || !source.endsWith('.modelbin')
      || !token || !Number.isSafeInteger(id) || id < 0) return null;
  const modelSha = normalizedSha(sourceModelbinSha256);
  const matiSha = normalizedSha(materialInstanceSha256);
  if ((modelSha && !SHA256.test(modelSha)) || (matiSha && !SHA256.test(matiSha))) return null;
  // 新規原本ViewerではModelBin/MatI実バイト署名が1つもないルートを禁止。
  // 合成旧テストの無署名後方互換は製品入口から指定できないよう分離する。
  if (requireSourceSignature && !(modelSha || matiSha)) return null;
  const matches = new Map();
  for (const row of rows) {
    if (!row || row.external_input !== 'g_CarUserColor0'
        || normalizedWheelSource(row.source_entry) !== source
        || row.material_id === null || row.material_id === undefined
        || Number(row.material_id) !== id
        ) continue;
    const rowToken = normalizedWheelMaterial(row.material_token || row.material_name);
    if (!rowToken) continue;
    const rowModel = normalizedSha(row.source_modelbin_sha256);
    const rowMati = normalizedSha(row.material_instance_sha256);
    if ((rowModel && !SHA256.test(rowModel)) || (rowMati && !SHA256.test(rowMati)))
      continue;
    if (requireSourceSignature && !(rowModel || rowMati)) continue;
    if (rowModel || rowMati || modelSha || matiSha) {
      if ((modelSha && rowModel && modelSha !== rowModel)
          || (matiSha && rowMati && matiSha !== rowMati)) continue;
      // 少なくともいずれか一つ、元原本の同一実バイトを証明する。
      if (!((modelSha && rowModel && modelSha === rowModel)
            || (matiSha && rowMati && matiSha === rowMati))) continue;
    }
    // 名前の別表記は、同じModelBinとMatIの実バイトSHAが両方一致した場合だけ許可。
    // 色の推測・他ModelBinへの流用を防ぐため、片方のSHA一致では緩和しない。
    const exactBoth = modelSha && rowModel && modelSha === rowModel
      && matiSha && rowMati && matiSha === rowMati;
    if (rowToken !== token && !exactBoth) continue;
    const kind = String(row.route_kind || '');
    let result = null;
    if (kind === 'axle_paint' && /^FrontWheelPaint[1-5]$/.test(row.front_group)
        && /^RearWheelPaint[1-5]$/.test(row.rear_group)
        && row.front_group.slice(-1) === row.rear_group.slice(-1)) {
      result = {token:rowToken, routeKind:kind, frontGroup:row.front_group, rearGroup:row.rear_group};
    } else if (kind === 'generic_binding'
        && /^(Rims3|RimsLip|Wheel1|Wheel2)$/.test(row.generic_group)) {
      result = {token:rowToken, routeKind:kind, group:row.generic_group};
    } else if (kind === 'unresolved' && SHA256.test(rowMati)) {
      // ホイール塗装グループの割当が無い塗装材質（valve_stem等）。ペイントの色の根拠が無いため、
      // その材質自身の原本MatIの既定色（Pythonが補う OriginalWheelMati:<MatI SHA>）だけを使う。
      result = {token:rowToken, routeKind:'original_mati_default', group:'OriginalWheelMati:' + rowMati};
    }
    if (result) matches.set(JSON.stringify(result), result);
  }
  return matches.size === 1 ? [...matches.values()][0] : null;
}
