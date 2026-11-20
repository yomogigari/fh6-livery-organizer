// r415: opt-in in-memory PNG decode and full-canvas RGBA parity diagnostic.
// The Blob, ImageBitmap and pixel arrays remain local; only numeric results escape.
// No persistent browser storage, network access, filesystem or paint mutations.
export async function measureAtlasPngReadback(canvas, blob, options = {}) {
  const clock = options.clock || (() => performance.now());
  const decode = options.decode || (value => createImageBitmap(value));
  const makeCanvas = options.createCanvas || (() => document.createElement('canvas'));
  const failed = code => ({ok:false, failureCode:code, decodeMs:0, drawMs:0,
    compareMs:0, comparedComponents:0, mismatchedComponents:0, maxAbsoluteError:0, pixelExact:0});
  const width = canvas?.width, height = canvas?.height;
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) ||
      width < 1 || height < 1 || width > 8192 || height > 8192 ||
      width*height > 64*1024*1024) return failed(1);
  if (blob?.type !== 'image/png' || !Number.isSafeInteger(blob?.size) || blob.size < 1) return failed(2);
  const sourceContext = canvas.getContext?.('2d', {willReadFrequently:true});
  if (!sourceContext || typeof sourceContext.getImageData !== 'function') return failed(3);
  let imageBitmap = null;
  let decodeMs = 0, drawMs = 0, compareMs = 0;
  try {
    let start = clock();
    imageBitmap = await decode(blob);
    decodeMs = Math.max(0, Math.round(clock()-start));
    if (!imageBitmap || imageBitmap.width !== width || imageBitmap.height !== height) {
      return {...failed(4), decodeMs};
    }
    const scratch = makeCanvas();
    if (!scratch) return {...failed(5), decodeMs};
    scratch.width=width; scratch.height=height;
    const targetContext = scratch.getContext?.('2d', {willReadFrequently:true});
    if (!targetContext || typeof targetContext.drawImage !== 'function' ||
        typeof targetContext.getImageData !== 'function') return {...failed(5), decodeMs};
    start = clock();
    targetContext.clearRect(0,0,width,height);
    targetContext.drawImage(imageBitmap,0,0);
    drawMs = Math.max(0, Math.round(clock()-start));
    // Strip reads bound additional JS pixel-array memory to 2 * 32 rows.
    start = clock();
    let mismatchedComponents = 0, maxAbsoluteError = 0, comparedComponents = 0;
    for (let y=0;y<height;y+=32) {
      const h=Math.min(32,height-y);
      const original=sourceContext.getImageData(0,y,width,h)?.data;
      const restored=targetContext.getImageData(0,y,width,h)?.data;
      if (!original || !restored || original.length !== width*h*4 || restored.length !== original.length) {
        return {...failed(6), decodeMs, drawMs, compareMs:Math.max(0,Math.round(clock()-start))};
      }
      comparedComponents+=original.length;
      for (let i=0;i<original.length;i++) {
        const difference=Math.abs(original[i]-restored[i]);
        if (difference) {
          mismatchedComponents++;
          if (difference>maxAbsoluteError) maxAbsoluteError=difference;
        }
      }
    }
    compareMs = Math.max(0, Math.round(clock()-start));
    return {ok:true, failureCode:0, decodeMs,drawMs,compareMs,comparedComponents,
      mismatchedComponents,maxAbsoluteError,pixelExact:mismatchedComponents===0?1:0};
  } catch (_) {
    return {...failed(7),decodeMs,drawMs,compareMs};
  } finally {
    try { imageBitmap?.close?.(); } catch (_) { /* nothing escapes */ }
  }
}
