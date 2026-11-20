import {measureAtlasPngReadback} from './gpu-atlas-png-readback-probe.js';
// r410: opt-in, non-persistent, lossless size probe. Only numeric results escape.
// This never serializes paint pixels to bridge/storage: the PNG Blob stays in JS.
export async function measureLosslessAtlasPng(canvas, options = {}) {
  const clock = options.clock || (() => performance.now());
  const width = Number(canvas?.width);
  const height = Number(canvas?.height);
  // r412: quality=4 render-contract atlases may exceed 16M pixels.
  // Limit diagnostic memory and dimensions; never change the rendering atlas.
  const maxPixels = options.maxPixels ?? 64 * 1024 * 1024;
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) ||
      width < 1 || height < 1 || width > 8192 || height > 8192 ||
      width * height > maxPixels) {
    return {ok: false, width: 0, height: 0, pngBytes: 0, rawRgbaBytes: 0, encodeMs: 0, failureCode: 1};
  }
  if (typeof canvas?.toBlob !== 'function') {
    return {ok: false, width, height, pngBytes: 0, rawRgbaBytes: width * height * 4, encodeMs: 0, failureCode: 2};
  }
  const start = clock();
  let blob;
  try {
    blob = await new Promise((resolve, reject) => {
      try { canvas.toBlob(resolve, 'image/png'); } catch (error) { reject(error); }
    });
  } catch (_) {
    return {ok: false, width, height, pngBytes: 0, rawRgbaBytes: width * height * 4, encodeMs: Math.max(0, Math.round(clock() - start)), failureCode: 3};
  }
  // A browser may silently substitute another format; refuse non-PNG blobs.
  const ok = blob?.type === 'image/png' && Number.isSafeInteger(blob?.size) && blob.size > 0;
  const roundTrip = ok && options.measureReadback
    ? await measureAtlasPngReadback(canvas, blob, options.readbackOptions || {}) : null;
  return {
    ...(roundTrip ? {roundTrip} : {}),
    ok, width, height, pngBytes: ok ? blob.size : 0,
    rawRgbaBytes: width * height * 4, encodeMs: Math.max(0, Math.round(clock() - start)),
    ...(ok ? {} : {failureCode: 4}),
  };
}
