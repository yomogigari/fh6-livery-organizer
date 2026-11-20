/**
 * PR68研究モードのみのWheelPaint表示/描画命令監査（純粋な件数集計）。
 * メッシュUUID以外のファイルパス、Livery、画像バイトを記録しない。
 * GPU提出フックは描画命令の証拠であり、画素一致・Xbox承認ではない。
 */
function summarizeOriginalWheelPaintDraw({
  variant='', declared=0, retained=0,
  drawSubmitted=null, wheelPaintUnresolved=0,
  primarySourceRoutes=0, unresolvedSourceRoutes=0,
  researchAppliedUuids=null, lipFallbackUuids=null, rejected=null,
}={}) {
  // GPU提出の純粋な監査。実行スイッチは存在しない。
  const drawn = drawSubmitted instanceof Set ? drawSubmitted : new Set();
  const applied = researchAppliedUuids instanceof Set ? researchAppliedUuids : new Set();
  const lip = lipFallbackUuids instanceof Set ? lipFallbackUuids : new Set();
  let researchDrawSubmitted=0, lipDrawSubmitted=0;
  for (const id of applied) if (drawn.has(id)) researchDrawSubmitted++;
  for (const id of lip) if (applied.has(id) && drawn.has(id)) lipDrawSubmitted++;
  const integer = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
  const reasons={};
  for (const [key,value] of Object.entries(rejected || {})) {
    if (/^[a-z0-9_-]{1,80}$/i.test(key) && Number.isSafeInteger(value) && value>0)
      reasons[key]=value;
  }
  const expected=applied.size;
  const status=expected===0 ? 'NO_RESEARCH_MATERIAL'
    : researchDrawSubmitted===expected ? 'RENDER_SUBMISSION_OBSERVED'
    : researchDrawSubmitted===0 ? 'MATERIAL_NOT_SUBMITTED'
    : 'PARTIAL_RENDER_SUBMISSION';
  return {
    schema:'lo4fh6.wheel_paint.original_draw_audit.v2',
    mode:'source-signed-standard',variant:String(variant).slice(0,72),status,
    wheelSignedGlb:integer(declared),wheelRetained:integer(retained),
    wheelDrawSubmitted:drawn.size,
    unresolvedShaderOutput:integer(wheelPaintUnresolved),
    provenPaintInputRoutes:integer(primarySourceRoutes),
    unresolvedPaintInputRoutes:integer(unresolvedSourceRoutes),
    researchMaterialsApplied:expected,researchMaterialsDrawSubmitted:researchDrawSubmitted,
    flsLipResearchMaterialsApplied:lip.size,flsLipResearchDrawSubmitted:lipDrawSubmitted,
    researchRejected:reasons,rendererHookObserved:researchDrawSubmitted>0,
    verifiedGpuPixels:false,shaderParityApproved:false,xboxApproved:false,releaseApproved:false,
  };
}

export function summarizeWheelPaintStandardDraw(args={}) {
  return summarizeOriginalWheelPaintDraw(args);
}

// 履歴研究テストとの互換であり、製品入口からは呼び出さない。
export function summarizeWheelPaintResearchDraw({enabled=false,...args}={}) {
  if (enabled !== true) return null;
  const result=summarizeOriginalWheelPaintDraw(args);
  return {...result,schema:'lo4fh6.wheel_paint.research_draw_audit.v1',
    mode:'research-only'};
}
