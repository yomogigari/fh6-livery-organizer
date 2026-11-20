/**
 * 【2026-11-06 23:22 JST】実車両の可視境界を基準に、初期表示と6方向のGPU撮影を
 * はみ出さない範囲で最大化する第一者カメラ補助。
 * カメラのみ変更し、車種・ペイント・Shader・材質には一切補正を入れない。
 */
/**
 * 上下撮影では車体の長い水平軸をスクリーンの横方向に置く。
 * 車種IDには依存せず、原本を含む可視境界のX/Z幅のみで判定する。
 * カメラのupと視線を直交させることで真上・真下の特異点も回避する。
 */
export function horizontalOverheadCameraUp(bounds, makeVector) {
  if (!bounds || bounds.isEmpty?.() || typeof makeVector !== 'function') {
    throw new Error('上下6方向撮影用の車体境界が不正です');
  }
  const size = bounds.getSize(bounds.min.clone());
  if (![size.x, size.z].every(Number.isFinite) || Math.max(size.x, size.z) <= 1e-6) {
    throw new Error('上下6方向撮影の水平軸を判定できません');
  }
  // 視線がほぼY軸のとき、upを短い水平軸に向けると長い軸が画面の横になる。
  return size.z >= size.x ? makeVector(1, 0, 0) : makeVector(0, 0, 1);
}

export function frameVisibleCar(camera, bounds, direction,
  {fillX = 0.90, fillY = 0.88, safety = 1.025, up = null} = {}) {
  if (!camera?.isPerspectiveCamera || !bounds || bounds.isEmpty?.()
    || !direction?.clone || !Number.isFinite(fillX) || !Number.isFinite(fillY)
    || fillX <= 0 || fillX >= 1 || fillY <= 0 || fillY >= 1
    || !Number.isFinite(safety) || safety < 1) {
    throw new Error('車体カメラの境界・視野設定が不正です');
  }
  const size = bounds.getSize(camera.position.clone());
  const center = bounds.getCenter(camera.position.clone());
  const extent = Math.max(size.x, size.y, size.z);
  if (!Number.isFinite(extent) || extent <= 1e-6) throw new Error('車体の有効サイズが取得できません');
  const unitDirection = direction.clone();
  if (!unitDirection.lengthSq()) throw new Error('車体カメラの方向が不正です');
  unitDirection.normalize();
  if (up) {
    if (!up.isVector3 || ![up.x,up.y,up.z].every(Number.isFinite)
        || up.lengthSq() <= 1e-8 || Math.abs(up.clone().normalize().dot(unitDirection)) > 0.98) {
      throw new Error('上下撮影のupベクトルがカメラ方向と一致しています');
    }
    camera.up.copy(up).normalize();
  } else camera.up.set(0, 1, 0);
  camera.near = Math.max(0.01, extent / 250);
  camera.far = Math.max(100, extent * 50);
  camera.updateProjectionMatrix();
  const corners = [];
  for (const x of [bounds.min.x, bounds.max.x]) {
    for (const y of [bounds.min.y, bounds.max.y]) {
      for (const z of [bounds.min.z, bounds.max.z]) {
        corners.push(camera.position.clone().set(x, y, z));
      }
    }
  }
  const fits = distance => {
    camera.position.copy(center).addScaledVector(unitDirection, distance);
    camera.lookAt(center);
    camera.updateMatrixWorld(true);
    for (const corner of corners) {
      const view = corner.clone().applyMatrix4(camera.matrixWorldInverse);
      // NDCの値だけだと、カメラの背後にある角も誤って収まったように見える。
      if (-view.z <= camera.near * 1.05) return false;
      const p = corner.clone().project(camera);
      if (![p.x, p.y, p.z].every(Number.isFinite)
          || Math.abs(p.x) > fillX || Math.abs(p.y) > fillY || p.z < -1 || p.z > 1) return false;
    }
    return true;
  };
  let lower = 0;
  let upper = extent * 20;
  if (!fits(upper)) throw new Error('車体の全体を収めるカメラ距離を確保できません');
  // 旧実装より画面占有率を上げる。ただし境界の8～12%を安全余白として保持する。
  for (let i = 0; i < 32; i += 1) {
    const middle = (lower + upper) * 0.5;
    if (fits(middle)) upper = middle;
    else lower = middle;
  }
  const distance = upper * safety;
  if (!fits(distance)) throw new Error('車体が撮影範囲からはみ出す可能性があります');
  return {center, extent, distance, fillX, fillY};
}
