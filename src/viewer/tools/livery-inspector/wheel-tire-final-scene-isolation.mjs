/**
 * PRIVATE研究撮影: 製品Viewerの通常GLB/原本材質/WheelPaint/FEOW適用が
 * 終わった同一のThree.js sceneからWheel/Tireだけを表示する。
 * 単体ModelBinを中立マテリアルへ変換する別Rendererではない。
 * URL未指定時は製品描画へ一切関与しない。
 */
const ROLES = new Set(['assembly']);
const CORNERS = new Set(['all', 'front_left', 'front_right', 'rear_left', 'rear_right']);
const SHA = /^[0-9a-f]{64}$/i;
const FOUR_CORNERS = Object.freeze(['front_left', 'front_right', 'rear_left', 'rear_right']);

export function wheelTireInspectionRequest(params) {
  const role = params.get('wheel-tire-inspection');
  const corner = params.get('wheel-tire-corner') || 'all';
  if (role === null) {
    if (params.has('wheel-tire-corner'))
      throw new Error('wheel-tire-corner は wheel-tire-inspection と併用してください');
    return null;
  }
  if (!ROLES.has(role) || !CORNERS.has(corner))
    throw new Error('単体Wheel/Tire検証の撮影対象または輪位置が不正です');
  return Object.freeze({role, corner});
}

function sourceValue(mesh, key) {
  // 既存ViewerのwheelMetadataForMeshと同じ優先順位。GLTFLoaderでは
  // ModelBin由来メタデータがprimitive(geometry.userData)側に置かれる場合がある。
  const primitive = mesh?.geometry?.userData?.[key];
  return primitive !== undefined && primitive !== null && primitive !== ''
    ? primitive : mesh?.userData?.[key];
}

function sourceRole(mesh) {
  return String(sourceValue(mesh, 'lo4_part_type') || '');
}

function sourceCorner(mesh) {
  const type = sourceRole(mesh);
  return type === 'Tire'
    ? sourceValue(mesh, 'lo4_tire_source_wheel')
    : sourceValue(mesh, 'lo4_wheel_morph_wheel');
}

export function wheelTireInspectionKeep(mesh, request) {
  if (!request || mesh?.isMesh !== true) return false;
  const type = sourceRole(mesh);
  if (type !== 'WheelStyle' && type !== 'Tire') return false;
  // FH6完成四輪は原本WheelStyleとTireを一組としてのみ撮影する。
  return request.corner === 'all' || sourceCorner(mesh) === request.corner;
}

export function isolateFinalWheelTireScene(root, request) {
  if (!request) return null;
  if (request.role !== 'assembly') throw new Error('Wheel/Tire完成検査は一組セットのみ許可');
  if (!root?.traverse) throw new Error('完成Viewerの描画シーンがありません');
  const hiddenMeshes = [];
  let wheel = 0;
  let tire = 0;
  // source ModelBin SHAは形状の出典であり、最終Shader材質の正しさを保証しない。
  // 診断材質が残った撮影を利用者が「純正外観OK」と誤認しないよう分離記録する。
  const tireMaterialSourceAudit = {
    diagnosticTireMeshes: 0,
    sourceSignedNormalTireMeshes: 0,
    feowAutoTireMeshes: 0,
    otherUnverifiedTireMeshes: 0,
    shaderEquivalentVerified: false,
    xboxAppearanceApproved: false,
  };
  const wheelCorners = new Set();
  const tireCorners = new Set();
  const wheelSourceHashes = new Set();
  const tireSourceHashes = new Set();
  const wheelSourceEntries = new Set();
  const tireSourceEntries = new Set();
  const wheelSourceIdentity = new Map();
  const tireSourceIdentity = new Map();
  const bad = [];
  root.traverse(mesh => {
    if (!mesh?.isMesh && !mesh?.isLine && !mesh?.isPoints && !mesh?.isSprite) return;
    if (!mesh?.isMesh || !wheelTireInspectionKeep(mesh, request)) {
      hiddenMeshes.push(mesh);
      return;
    }
    if (mesh.visible === false || sourceValue(mesh, 'lo4_base_visible') === false) return;
    const type = sourceRole(mesh);
    const corner = sourceCorner(mesh);
    if (!FOUR_CORNERS.includes(corner))
      bad.push('原本Wheel/Tireの輪位置が未同定: ' + String(mesh.name || type));
    else (type === 'WheelStyle' ? wheelCorners : tireCorners).add(corner);
    // variant root自体は後で可視切替するため、内部の親Groupのみ監査する。
    // 親が非表示ならmesh.visible=trueでもWebGLの描画対象にはならない。
    for (let parent = mesh.parent; parent && parent !== root; parent = parent.parent) {
      if (parent.visible === false) {
        bad.push('原本Wheel/Tireの親Groupが非表示: ' + String(mesh.name || type));
        break;
      }
    }
    const signed = type === 'WheelStyle'
      ? sourceValue(mesh, 'lo4_wheel_source_modelbin_sha256')
      : sourceValue(mesh, 'lo4_tire_original_modelbin_sha256');
    if (!SHA.test(String(signed || ''))) {
      bad.push('原本ModelBin SHA未確認: ' + String(mesh.name || type));
    } else {
      (type === 'WheelStyle' ? wheelSourceHashes : tireSourceHashes).add(String(signed).toLowerCase());
    }
    // 実GPU対象メッシュの原本ModelBin名称をSHAと組で記録する。
    // C_livery・GameSaveパスやユーザー環境の絶対パスは出さない。
    const sourceEntry = String(sourceValue(mesh, 'lo4_source_entry') || '')
      .replaceAll('\\', '/');
    const expectedFolder = type === 'WheelStyle' ? '/wheels/' : '/tires/';
    if (!sourceEntry.toLowerCase().includes(expectedFolder)
        || !sourceEntry.toLowerCase().endsWith('.modelbin')
        || sourceEntry.length > 512)
      bad.push('原本ModelBinパス同定不能: ' + String(mesh.name || type));
    else {
      const name = sourceEntry.split('/').at(-1);
      (type === 'WheelStyle' ? wheelSourceEntries : tireSourceEntries).add(name);
      if (SHA.test(String(signed || ''))) {
        const entries = type === 'WheelStyle' ? wheelSourceIdentity : tireSourceIdentity;
        const normalizedSha = String(signed).toLowerCase();
        if (entries.has(name) && entries.get(name) !== normalizedSha)
          bad.push('同名原本ModelBinの異なるSHAが混在: ' + name);
        entries.set(name, normalizedSha);
      }
    }
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    if (!mats.length || mats.some(mat => !mat || String(mat.name || '').startsWith('NEUTRAL_SOURCE_GEOMETRY_DIAGNOSTIC')
      || mat.userData?.source_material_not_bound === true))
      bad.push('描画用材質未適用: ' + String(mesh.name || type));
    if (type === 'WheelStyle') wheel++;
    else {
      tire++;
      // 現行ローカルTireと旧研究Bridgeの初期材質は共にFH6 Shader非同値。
      if (sourceValue(mesh, 'lo4fh6_original_tire_diagnostic_material_retained') === true
          || mats.some(mat => {
            const name = String(mat?.name || '');
            return name === 'Local-source-tire-research-neutral'
              || name.startsWith('PRIVATE-diagnostic-original-tire-not-game-shader');
          }))
        tireMaterialSourceAudit.diagnosticTireMeshes++;
      else if (mats.every(mat => mat?.userData?.lo4fh6_original_tire_normal_research === true))
        tireMaterialSourceAudit.sourceSignedNormalTireMeshes++;
      else if (sourceValue(mesh, 'lo4fh6_feow_signed_auto_applied') === true)
        tireMaterialSourceAudit.feowAutoTireMeshes++;
      else tireMaterialSourceAudit.otherUnverifiedTireMeshes++;
    }
  });
  if (wheel === 0 || tire === 0)
    bad.push('対象の原本Wheel/Tireが未接続 (wheel=' + wheel + ', tire=' + tire + ')');
  if (request.corner === 'all') {
    for (const corner of FOUR_CORNERS) {
      if (!wheelCorners.has(corner) || !tireCorners.has(corner))
        bad.push('原本Wheel/Tire四輪セットの一部が未接続: ' + corner);
    }
  }
  if (bad.length)
    throw new Error('完成Wheel/Tire撮影を拒否: ' + bad.slice(0, 8).join('; '));
  // 検証が全件成功してから描画可視状態を一括更新する。
  for (const mesh of hiddenMeshes) mesh.visible = false;
  let visibleNonTargetMeshes = 0;
  root.traverse(object => {
    if ((object?.isMesh || object?.isLine || object?.isPoints || object?.isSprite)
      && object.visible === true && !wheelTireInspectionKeep(object, request)) visibleNonTargetMeshes++;
  });
  if (visibleNonTargetMeshes !== 0) throw new Error('Wheel/Tire専用シーンに車体が残っています');
  return {scope:request.role,corner:request.corner,visibleWheelMeshes:wheel,
    visibleTireMeshes:tire,
    sourceWheelCorners:[...wheelCorners].sort(),
    sourceTireCorners:[...tireCorners].sort(),
    sourceWheelModelbinSha256:[...wheelSourceHashes].sort(),
    sourceTireModelbinSha256:[...tireSourceHashes].sort(),
    sourceWheelModelbinNames:[...wheelSourceEntries].sort(),
    sourceTireModelbinNames:[...tireSourceEntries].sort(),
    sourceWheelModelbins:[...wheelSourceIdentity].sort(([a],[b]) => a.localeCompare(b))
      .map(([name,sha256]) => ({name,sha256})),
    sourceTireModelbins:[...tireSourceIdentity].sort(([a],[b]) => a.localeCompare(b))
      .map(([name,sha256]) => ({name,sha256})),
    visibleNonTargetMeshes,
    hiddenNonTargetMeshes:hiddenMeshes.length,
    tireMaterialSourceAudit,
    finalViewerMaterialPipeline:true,materialReplaced:false,xboxApproved:false};
}
