/**
 * FH6原本のWheelStyle材質署名と参照製品の表示動作を区別した研究用候補。
 * lip/RimsLip用の個別ペイントが存在しないときだけ、軸別の第一ペイント
 * グループを比較候補として提示する。FH6 Shader画素一致・公開採用は未承認。
 * 通常描画/完成GLB/原本テクスチャを書き換えない。
 */
const AXLES = Object.freeze({Front:'FrontWheelPaint1',Rear:'RearWheelPaint1'});

export function sourceWheelLipFallbackResearch({
  requested=false, signedSource=false, evidenceRoute=null, axle='', groups=null,
}={}) {
  if (requested !== true) return null;
  if (signedSource !== true || !evidenceRoute
      || evidenceRoute.routeKind !== 'generic_binding'
      || evidenceRoute.group !== 'RimsLip'
      || evidenceRoute.token !== 'lip') return null;
  if (axle !== 'Front' && axle !== 'Rear') return null;
  if (!groups || typeof groups !== 'object' || Array.isArray(groups)) return null;
  // 正規のRimsLipが入力に存在するときは、その色を優先し研究候補にしない。
  if (Object.prototype.hasOwnProperty.call(groups,'RimsLip')) return null;
  const group=AXLES[axle];
  const record=groups[group];
  if (!record || record.primary_color_enabled !== true
      || typeof record.primary_color_rgba_hex !== 'string'
      || !/^#[0-9a-f]{8}$/i.test(record.primary_color_rgba_hex)) return null;
  return {
    token:'lip',group,routeKind:'generic_binding',
    routeSource:'reference-wheel-lip-fallback-research',
    sourceMaterialProven:true,expectedGroup:'RimsLip',
    fallbackEvidence:'reference-wheel-preview-axle-primary-20261112',
  };
}


// Rims3等の個別GroupがC_liveryに存在しない場合、原本の軸別primaryに限定して
// 参照製品で確認した代替順位を比較する。既存のlip専用経路はそのまま保持する。
// 製品採用の可否は呼出元で実ModelBin材質ID/外部g_CarUserColor0と
// MaterialBin/ShaderBin SHAを別途検証する。ここではRGBを生成しない。
const GENERIC_PAINT_GROUPS = Object.freeze({
  rim3:'Rims3',
  detail:'Wheel1',
  detail2:'Wheel2',
});
export function sourceWheelGenericPrimaryFallbackResearch(options={}) {
  const {requested=false,signedSource=false,evidenceRoute=null,axle='',groups=null}=options;
  if (evidenceRoute?.token === 'lip')
    return sourceWheelLipFallbackResearch(options);
  if (!requested || !signedSource || evidenceRoute?.routeKind !== 'generic_binding') return null;
  const expectedGroup=GENERIC_PAINT_GROUPS[evidenceRoute?.token];
  if (!expectedGroup || evidenceRoute.group !== expectedGroup) return null;
  if (axle !== 'Front' && axle !== 'Rear') return null;
  if (!groups || typeof groups !== 'object' || Array.isArray(groups)) return null;
  // 存在する正規GroupはOFFでも代替しない（権限のない再着色を防止）。
  if (Object.prototype.hasOwnProperty.call(groups,expectedGroup)) return null;
  const group=AXLES[axle];
  const record=groups[group];
  if (record?.primary_color_enabled !== true
      || !/^#[0-9a-f]{8}$/i.test(String(record.primary_color_rgba_hex || ''))) return null;
  return {
    token:evidenceRoute.token,group,routeKind:'generic_binding',
    routeSource:'reference-wheel-generic-fallback-research',
    sourceMaterialProven:true,expectedGroup,
    fallbackEvidence:'reference-wheel-missing-generic-axle-primary-20261112',
  };
}


// 原本WheelStyle MatI/ModelBin/g_CarUserColor0の完全一致を判定済みの
// evidenceRouteを受け取る単一標準グループ選択。研究用実行フラグ不要。
export function sourceWheelGenericPrimaryStandardRoute({evidenceRoute=null,axle='',groups=null}={}) {
  if (evidenceRoute?.routeKind !== 'generic_binding'
      || !['Front','Rear'].includes(axle)
      || !groups || typeof groups !== 'object' || Array.isArray(groups)) return null;
  const expected = evidenceRoute.token === 'lip' ? 'RimsLip'
    : GENERIC_PAINT_GROUPS[evidenceRoute.token];
  if (!expected || evidenceRoute.group !== expected
      || Object.prototype.hasOwnProperty.call(groups, expected)) return null;
  const group=AXLES[axle], record=groups[group];
  if (record?.primary_color_enabled !== true
      || !/^#[0-9a-f]{8}$/i.test(String(record.primary_color_rgba_hex || '')))
    return null;
  return {
    token:evidenceRoute.token,group,routeKind:'generic_binding',
    routeSource:'source-signed-generic-primary',sourceMaterialProven:true,
    expectedGroup:expected,
    fallbackEvidence:'original-mati-source-and-external-usercolor0-v1',
  };
}
