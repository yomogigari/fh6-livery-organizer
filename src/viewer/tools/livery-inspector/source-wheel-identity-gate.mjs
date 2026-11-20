/**
 * 原本WheelStyleの4輪を同定し、Proxyを使わないPRIVATE比較を許可する。
 * Xbox装着・材質・Shader一致までは承認しない。車種別ハードコード禁止。
 */
const expectedWheels = Object.freeze(['front_left', 'front_right', 'rear_left', 'rear_right']);
// 6 輪の車の中央の車輪（骨 LM・RM）。3 輪・6 輪の車は、変換の段階が WheelStyle に
// lo4fh6_feow_standard_four_corner_eligible = false の印を付ける。
const middleWheels = Object.freeze(['middle_left', 'middle_right']);
const allWheels = Object.freeze([...expectedWheels, ...middleWheels]);
const safeField = (mesh, key) => {
  const primitive = mesh?.geometry?.userData;
  return primitive != null && Object.prototype.hasOwnProperty.call(primitive, key)
    ? primitive[key] : mesh?.userData?.[key];
};

function basenamePath(path) {
  return String(path || '').replaceAll('\\', '/').toLowerCase();
}

/**
 * 構造だけを証明する。ゲームの本来装着Wheelや材質の外観の承認ではない。
 * 全4輪が独立原本ModelBinに由来していない場合は、描画を拒否する。
 */
export function inspectWheelSourceEvidence(root) {
  const wheels = Object.fromEntries(allWheels.map(w => [w, {meshes: 0, triangles: 0, models: new Set()}]));
  const problems = [];
  let visibleSourceTires = 0;
  let nonStandardWheelRoles = false;
  const sourceTiresByWheel = Object.fromEntries(allWheels.map(w => [w, {meshes: 0, archiveSha256: new Set(), sources: new Set()}]));
  let unverifiedTireMeshes = 0;
  let candidates = 0;
  let uncoveredWheelMeshes = 0;
  if (!root || typeof root.traverse !== 'function') {
    return {ok: false, reason: '元GLBシーンがありません', problems: ['invalid-root'], wheels: {}};
  }
  root.traverse(mesh => {
    if (!mesh?.isMesh || mesh.visible === false || mesh.userData?.lo4_base_visible === false
        || safeField(mesh, 'lo4_role') === 'hidden') return;
    const partType = String(safeField(mesh, 'lo4_part_type') || '').toLowerCase();
    const name = `${mesh.name || ''} ${mesh.userData?.lo4_source_entry || ''}`.toLowerCase();
    if (partType !== 'wheelstyle') {
      // 中立的な追加タイヤを原本タイヤと誤認しない。出典情報がなければ拒否する。
      const tireSource = basenamePath(safeField(mesh, 'lo4_source_entry'));
      // 車体の部品として Carbin で配置を検証済みのもの（PEN_Cholla_11 の荷台のスペアタイヤ
      // Scene/Exterior/Engine/spareTire.modelbin 等）は、名前に tire を含んでも走行用のタイヤではない。
      // 出典が車体の ModelBin（/tires/ 以外）なら数えない。出典の無いものは従来どおり拒否する。
      // 部品の種類は CarBody に限らない（AC_6165_Class6100_21 のトランクのスペアタイヤ
      // Scene/Exterior/Trunk/spareTire_a.modelbin は Carbin の種類が RearWing）。種類の無いもの・Tire は対象外。
      const verifiedBodyPart = partType !== '' && partType !== 'tire'
        && (safeField(mesh, 'lo4_source_static_instance_verified') === true
          || safeField(mesh, 'lo4fh6_source_static_instance_verified') === true)
        && tireSource.endsWith('.modelbin') && !tireSource.includes('/tires/');
      if (verifiedBodyPart) return;
      if (name.includes('tire') || name.includes('tyre') || partType === 'tire') {
        const wheel = safeField(mesh, 'lo4_tire_source_wheel') || safeField(mesh, 'lo4_wheel_morph_wheel');
        const archive = String(safeField(mesh, 'lo4_tire_original_archive_sha256') || '').toLowerCase();
        const packet = String(safeField(mesh, 'lo4_tire_source_packet_sha256') || '').toLowerCase();
        const origin = String(safeField(mesh, 'lo4_tire_private_origin') || '');
        const modelbinSha = String(safeField(mesh, 'lo4_tire_original_modelbin_sha256') || '').toLowerCase();
        const uvOrigin = String(safeField(mesh, 'lo4_tire_uv_origin') || '');
        const geom = mesh.geometry;
        const positions = geom?.getAttribute?.('position');
        const indices = geom?.getIndex?.();
        const n = indices?.count || positions?.count || 0;
        const sourceOK = tireSource.includes('/tires/') && tireSource.endsWith('.modelbin');
        const proofOK = /^[0-9a-f]{64}$/.test(archive) && /^[0-9a-f]{64}$/.test(packet)
          && (origin === 'verified-original-archive-packet' || (
            origin === 'local-FH6-ModelBin-dimensions-research-v1'
            && modelbinSha === packet && /^[0-9a-f]{64}$/.test(modelbinSha)
            && safeField(mesh,'lo4_tire_source_digest_kind') === 'local-original-modelbin'
            && uvOrigin === 'ModelBin/TEXCOORD_UNORM16_4channels_no_geometry_edit')); 
        // 元ModelBinと署名済みpacketの出典が一輪単位で成立した場合だけ数える。
        if (sourceOK && proofOK && allWheels.includes(wheel)
            && positions?.count >= 3 && n >= 3 && n % 3 === 0) {
          const item = sourceTiresByWheel[wheel];
          item.meshes++;
          item.archiveSha256.add(archive);
          item.sources.add(tireSource);
          visibleSourceTires++;
        } else {
          unverifiedTireMeshes++;
          problems.push(`タイヤprimitive原本同定不能: ${String(mesh.name || '').slice(0,90)}`);
        }
      }
      return;
    }
    candidates++;
    if (safeField(mesh, 'lo4fh6_feow_standard_four_corner_eligible') === false
        || safeField(mesh, 'lo4_feow_standard_four_corner_eligible') === false) {
      nonStandardWheelRoles = true;
    }
    const installedWheel = safeField(mesh, 'lo4_wheel_morph_wheel');
    const identityWheel = safeField(mesh, 'lo4_wheel_morph_identity_wheel');
    const source = basenamePath(safeField(mesh, 'lo4_source_entry'));
    const morph = String(safeField(mesh, 'lo4_wheel_morph_source') || '');
    const bucket = safeField(mesh, 'lo4_wheel_render_pass_bucket_flags');
    const materialId = safeField(mesh, 'lo4_wheel_material_id');
    const geom = mesh.geometry;
    const position = geom?.getAttribute?.('position');
    const index = geom?.getIndex?.();
    const n = index?.count || position?.count || 0;
    if (!allWheels.includes(installedWheel) || !allWheels.includes(identityWheel)
        || !source.includes('/wheels/') || !source.endsWith('.modelbin')
        || !morph.startsWith('internal-modelbin-')
        || !Number.isSafeInteger(bucket) || !Number.isSafeInteger(materialId)
        || !position || position.count < 3 || n < 3 || n % 3 !== 0) {
      uncoveredWheelMeshes++;
      problems.push(`原本同定不能なWheelStyle primitive: ${String(mesh.name || '').slice(0, 90)}`);
      return;
    }
    const item = wheels[installedWheel];
    item.meshes++;
    item.triangles += n / 3;
    item.models.add(source);
  });
  // 原本の車輪がちょうど 4 つの角の車は従来どおり 4 輪。3 輪・6 輪の車は、ある車輪（角が 3 つ以上、
  // 中央は 0 か 2、中央があるなら角は 4 つ）を確かめる。
  let requiredWheels = expectedWheels;
  if (nonStandardWheelRoles) {
    const present = allWheels.filter(wheel => wheels[wheel].meshes > 0);
    const corners = expectedWheels.filter(wheel => wheels[wheel].meshes > 0).length;
    const middles = middleWheels.filter(wheel => wheels[wheel].meshes > 0).length;
    if (corners < 3 || ![0, 2].includes(middles) || (middles && corners !== 4)) {
      problems.push('原本の3輪・6輪の車輪の組が不正');
    }
    requiredWheels = present;
  } else {
    for (const wheel of middleWheels) {
      if (wheels[wheel].meshes) problems.push(`${wheel}: 4輪の車に中央の車輪があります`);
    }
  }
  for (const wheel of requiredWheels) {
    if (!wheels[wheel].meshes) problems.push(`${wheel}: 原本WheelStyleがありません`);
  }
  for (const wheel of requiredWheels) {
    if (!sourceTiresByWheel[wheel].meshes) problems.push(`${wheel}: 署名された元タイヤがありません`);
  }
  const archiveSet = new Set(Object.values(sourceTiresByWheel).flatMap(v => [...v.archiveSha256]));
  if (archiveSet.size > 1) problems.push('原本4輪タイヤのZIP署名が不一致');
  const report = Object.fromEntries(Object.entries(wheels).filter(([k]) => requiredWheels.includes(k)).map(([k, v]) =>
    [k, {meshes: v.meshes, triangles: v.triangles, modelSources: [...v.models].sort(),
      originalTireMeshes: sourceTiresByWheel[k].meshes,
      tireSources: [...sourceTiresByWheel[k].sources].sort()}]));
  return {
    ok: problems.length === 0,
    reason: problems[0] || '原本4輪とタイヤの構造を確認（装着・Shader・Xboxは未承認）',
    problems,
    wheelStyleCandidates: candidates,
    uncoveredWheelMeshes,
    visibleSourceTires,
    unverifiedTireMeshes,
    wheels: report,
    wheelRoles: [...requiredWheels],
    nonStandardWheelRoles,
    gameWheelSelectionApproved: false,
    xboxAppearanceApproved: false,
  };
}

export function requireVerifiedWheelSource(root) {
  const result = inspectWheelSourceEvidence(root);
  if (!result.ok) throw new Error(`原本車輪の非破壊比較を拒否: ${result.reason}`);
  return result;
}
