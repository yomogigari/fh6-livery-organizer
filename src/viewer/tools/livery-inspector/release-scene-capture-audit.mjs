/**
 * リリース受入用の完成シーン・GPU実描画証拠を、車種非依存で評価する。
 * シーン色・材質・保存動作を変更しない。Xbox外観/配布権利の承認は行わない。
 * 原本Wheel件数は受信GLBの署名値から取得し、固定件数を使用しない。
 */
const finiteCount = value => Number.isSafeInteger(value) && value >= 0;

export function evaluateReleaseSceneCapture(input) {
  const reasons = [];
  const fail = (code, condition) => { if (!condition) reasons.push(code); };
  const frame = input?.frame || {};
  const paint = input?.paint || {};
  const body = input?.body || {};
  const wheels = input?.wheels || {};
  const appearance = input?.appearance || {};
  const actualWidth = frame.width;
  const actualHeight = frame.height;
  const high = Math.max(actualWidth || 0, actualHeight || 0);
  const low = Math.min(actualWidth || 0, actualHeight || 0);
  // 4K横/縦のどちらでも、拡大後の見かけ上の画像でなく実drawingBufferを要求する。
  fail('not-real-webgl2', input?.webgl2 === true);
  fail('invalid-or-under-4k-frame', finiteCount(actualWidth) && finiteCount(actualHeight)
    && high >= 3840 && low >= 2160 && frame.pixelReadbackOk === true
    && frame.defaultFramebuffer === true);
  fail('not-complete-production-view', input?.compareMode === 'off' && input?.demoMosaic === false);
  fail('gpu-only-paint-not-complete', paint.policy === 'gpu-only'
    && paint.rasterizer === 'webgl2-only' && paint.completed === true);
  fail('painted-vehicle-geometry-not-confirmed', finiteCount(body.meshCount)
    && body.meshCount > 0 && finiteCount(body.paintCount) && body.paintCount > 0);
  // Glassのない車種もあるのでガラス枚数0を全車種共通のリリース不合格にしない。
  // 必須検査を明示した比較だけで正のGLASSメッシュを要求する。
  if (input?.requireGlass === true) {
    fail('glass-geometry-not-confirmed', finiteCount(body.glassCount) && body.glassCount > 0);
  }
  fail('source-wheel-view-not-active', wheels.source === 'source-verified' && wheels.visible === true);
  fail('original-appearance-switches-not-enabled', appearance.sourceMaterial === true
    && appearance.neutralGrade === true);
  const declared = wheels.declaredPrimitives;
  const received = wheels.receivedPrimitives;
  const loaded = wheels.loaderRecognized;
  const retained = wheels.retained;
  const submitted = wheels.submitted;
  const signed = finiteCount(declared) && declared > 0;
  fail('signed-wheel-primitives-missing', signed && finiteCount(received) && received === declared);
  fail('source-wheel-loader-mismatch', signed && finiteCount(loaded) && loaded === declared);
  fail('source-wheel-texture-lost', signed && finiteCount(retained) && retained === declared);
  fail('source-wheel-not-gpu-submitted-in-capture-frame', signed
    && finiteCount(submitted) && submitted === declared);
  const technicalReady = reasons.length === 0;
  return Object.freeze({
    schema: 'lo4fh6.release.complete-scene-capture-audit.v1',
    status: technicalReady ? 'TECHNICAL_CAPTURE_READY' : 'REVIEW_REQUIRED',
    reasons,
    frame: {width: actualWidth || 0, height: actualHeight || 0, glReadPixelsOk: frame.pixelReadbackOk === true},
    observed: {
      bodyMeshes:finiteCount(body.meshCount) ? body.meshCount : null,
      paintMeshes:finiteCount(body.paintCount) ? body.paintCount : null,
      glassMeshes:finiteCount(body.glassCount) ? body.glassCount : null,
      signedWheelPrimitives:finiteCount(declared) ? declared : null,
      receivedWheelPrimitives:finiteCount(received) ? received : null,
      gltfLoaderWheelPrimitives:finiteCount(loaded) ? loaded : null,
      retainedWheelTextures:finiteCount(retained) ? retained : null,
      captureFrameWheelGpuSubmissions:finiteCount(submitted) ? submitted : null,
    },
    gameOriginalBytesIncluded:false,
    vehicleSpecificCorrection:false,
    gameXboxVisualApproved:false,
    redistributionApproved:false,
    fileSavedOrShaVerified:false,
    // ここでのPASSはソースとGPU命令の受入で、Xbox外観や保存済み画像の合格ではない。
    releaseApproved:false,
  });
}
