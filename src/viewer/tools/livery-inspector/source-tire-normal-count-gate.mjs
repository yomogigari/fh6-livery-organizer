/** Source-signed Tire Normal mesh count, not a fixed 4×3 approximation.
 * Earlier source GLBs use 12 normal meshes; new GLBs carry the original source
 * per-corner role count. Material signatures and original geometry are checked
 * by the Python source adapter before this independent GPU audit.
 */
const SOURCE_WHEELS = ['front_left', 'front_right', 'rear_left', 'rear_right'];
// 6 輪の車の中央の車輪（骨 LM・RM）。
const MIDDLE_WHEELS = ['middle_left', 'middle_right'];
const ALL_WHEELS = [...SOURCE_WHEELS, ...MIDDLE_WHEELS];

/** 検査する車輪。原本の車輪がちょうど 4 つの角の車は従来どおり 4 輪。
 * 原本が 3 輪・6 輪の車（変換の段階の印が偽）だけ、ある車輪（角が 3 つ以上、中央は 0 か 2）で検査する。 */
function expectedWheelRoles(grouped, nonStandardWheelRoles) {
  if (!nonStandardWheelRoles) return SOURCE_WHEELS;
  const corners = SOURCE_WHEELS.filter(wheel => grouped.has(wheel)).length;
  const middles = MIDDLE_WHEELS.filter(wheel => grouped.has(wheel)).length;
  if (corners < 3 || ![0, 2].includes(middles) || (middles && corners !== 4)) {
    throw new Error('原本Tireの3輪・6輪の車輪の組が不正');
  }
  return ALL_WHEELS.filter(wheel => grouped.has(wheel));
}

/** 元LOD0を各輪のMatI ID/ModelBin SHAで照合し、均一な材質数を仮定しない。 */
function verifyOriginalWheelRoles(rows, retained, expectedTotal, feowWheelClaims=[], nonStandardWheelRoles=false) {
  if (rows.length !== retained) {
    throw new Error('原本Tire四輪別LOD0の役割署名が一部欠落');
  }
  const grouped = new Map();
  for (const item of rows) {
    if (!item || !ALL_WHEELS.includes(item.wheel) ||
        !Number.isSafeInteger(item.materialId) || item.materialId < 0 ||
        !Number.isSafeInteger(item.expectedWheelRoleCount) ||
        item.expectedWheelRoleCount < 1 || item.expectedWheelRoleCount > expectedTotal ||
        !/^[0-9a-f]{64}$/.test(item.sourceModelbinSha256 || '')) {
      throw new Error('原本Tire四輪別LOD0材質・ModelBin署名が不正');
    }
    let role = grouped.get(item.wheel);
    if (!role) {
      role = {expected:item.expectedWheelRoleCount, sha:item.sourceModelbinSha256, ids:new Set()};
      grouped.set(item.wheel, role);
    }
    if (role.expected !== item.expectedWheelRoleCount ||
        role.sha !== item.sourceModelbinSha256 || role.ids.has(item.materialId)) {
      throw new Error('原本Tire同一輪内のMaterial-ID/ModelBin署名が矛盾');
    }
    role.ids.add(item.materialId);
  }
  // FEOWの4輪も元Material-IDと同一ModelBin署名を使うことを確認。
  // 8 Normalの件数だけ合って別の材質が欠落したケースを成功扱いしない。
  // 文字MatIは1輪に1件（FEOW等）または同数の複数件（OW_b_Horizon等）。
  const feowByWheel = new Map();
  for (const item of feowWheelClaims) {
    if (!item || !SOURCE_WHEELS.includes(item.wheel)
        || !Number.isSafeInteger(item.materialId) || item.materialId < 0
        || !/^[0-9a-f]{64}$/.test(item.sourceModelbinSha256 || '')
        || (feowByWheel.get(item.wheel) || []).some(x => x.materialId === item.materialId)) {
      throw new Error('原本FEOW側面4輪のMaterial-ID/ModelBin署名が不正');
    }
    feowByWheel.set(item.wheel, [...(feowByWheel.get(item.wheel) || []), item]);
  }
  const wheels = expectedWheelRoles(grouped, nonStandardWheelRoles);
  const textPerWheel = feowWheelClaims.length / wheels.length;
  let total = 0;
  for (const wheel of wheels) {
    const role = grouped.get(wheel);
    const feow = feowByWheel.get(wheel) || [];
    const sidewallOffset = feowWheelClaims.length ? textPerWheel : 0;
    if (!role || (sidewallOffset && (feow.length !== sidewallOffset
        || feow.some(x => x.sourceModelbinSha256 !== role.sha || role.ids.has(x.materialId))))
        || role.ids.size + sidewallOffset !== role.expected) {
      throw new Error('原本Tireの四輪別LOD0材質が不足・重複・FEOW別出典');
    }
    total += role.ids.size + sidewallOffset;
  }
  if (total !== expectedTotal) throw new Error('原本Tire四輪別LOD0合計件数が不一致');
}

/** 既受入の旧12/16形式と、新形式の四輪個別材質数を別々に署名判定。 */
export function sourceTireNormalCountGate({
  retained=0, autoRetained=0, dxilApplied=0, claims=[], wheelClaims=[], feowWheelClaims=[],
  nonStandardWheelRoles=false,
}={}) {
  if (!Number.isSafeInteger(retained) || retained < 0 ||
      !Number.isSafeInteger(autoRetained) || autoRetained < 0 ||
      !Number.isSafeInteger(dxilApplied) || dxilApplied < 0 ||
      !Array.isArray(claims) || claims.length !== retained ||
      !Array.isArray(wheelClaims) || !Array.isArray(feowWheelClaims)) {
    throw new Error('原本Tire Normal件数の出典が不正');
  }
  if (retained === 0) {
    if (autoRetained !== 0 || dxilApplied !== 0 || wheelClaims.length !== 0 || feowWheelClaims.length !== 0) {
      throw new Error('原本Tire不在とNormal/FEOW署名の矛盾');
    }
    return {expected:0, standard:false, status:'absent'};
  }
  // 原本FEOWは四輪のsidewallのみ。その他の元Tire材質はNormalで保持。
  // 片輪欠損・中途半端なDXIL適用数は必ず拒否する。
  if (dxilApplied !== 0 && (dxilApplied < 4 || dxilApplied % 4 !== 0)) {
    throw new Error('原本FEOW側面文字の適用件数が4輪ではありません');
  }
  const known = claims.filter(x => x !== undefined);
  let expected;
  if (known.length === 0) {
    expected = 12; // 過去Windows受入済み旧GLBのみの互換数。
  } else {
    if (known.length !== retained || known.some(x =>
        !Number.isSafeInteger(x) || x < 4 || x !== known[0])) {
      throw new Error('原本Tire NormalのMaterial-ID総数署名が矛盾');
    }
    expected = known[0];
  }
  const normalExpected = expected - dxilApplied;
  if (normalExpected <= 0 || retained !== normalExpected
      || (autoRetained !== 0 && autoRetained !== normalExpected)) {
    throw new Error('原本Tire Normal/FEOWのGLB・四輪・GPU保持件数が不一致');
  }
  if (dxilApplied > 0 && (known.length !== retained || wheelClaims.length !== retained
      || feowWheelClaims.length !== dxilApplied)) {
    throw new Error('FEOW側面文字以外の全Tire材質の輪別原本署名が不足');
  }
  if (dxilApplied === 0 && feowWheelClaims.length) {
    throw new Error('FEOWが適用されていないのに側面原本署名が存在');
  }
  if (wheelClaims.length) {
    verifyOriginalWheelRoles(wheelClaims, retained, expected, feowWheelClaims, nonStandardWheelRoles === true);
  } else if (expected % 4 !== 0) {
    // 非均一LOD0では原本の輪別Material IDとSHAがないと件数だけでは判定不可。
    throw new Error('原本Tire非均一LOD0の四輪別役割署名がありません');
  }
  return {expected:normalExpected, standard:autoRetained===normalExpected,
    status:dxilApplied === 4 ? 'verified-source-feow-normal-combined' : 'verified-source-count'};
}
