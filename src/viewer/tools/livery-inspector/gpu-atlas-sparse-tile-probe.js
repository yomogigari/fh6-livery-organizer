// r413: read-only lossless PNG tile payload sizing. No image blobs escape this module.
// A tile is omitted only if every RGBA component is zero; no alpha-only shortcuts.
export async function measureSparseAtlasTiles(canvas, options = {}) {
  const clock = options.clock || (() => performance.now());
  const tileSize = options.tileSize ?? 1024;
  const width = Number(canvas?.width), height = Number(canvas?.height);
  const failed = code => ({ok:false, failureCode:code, encodedBytes:0, totalTiles:0, nonzeroTiles:0, zeroTiles:0, encodeMs:0});
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) ||
      width < 1 || height < 1 || width > 8192 || height > 8192 ||
      width * height > 64 * 1024 * 1024 ||
      !Number.isSafeInteger(tileSize) || tileSize < 64 || tileSize > 2048) return failed(1);
  const sourceContext = canvas?.getContext?.('2d', {willReadFrequently:true});
  if (!sourceContext || typeof sourceContext.getImageData !== 'function') return failed(2);
  const makeCanvas = options.createCanvas || (() => document.createElement('canvas'));
  let tileCanvas;
  try { tileCanvas = makeCanvas(); } catch (_) { return failed(2); }
  if (!tileCanvas || typeof tileCanvas.toBlob !== 'function') return failed(2);
  const columns = Math.ceil(width / tileSize), rows = Math.ceil(height / tileSize);
  if (columns * rows > 256) return failed(1);
  const start = clock();
  let encodedBytes = 0, zeroTiles = 0, nonzeroTiles = 0;
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < columns; col += 1) {
      const x = col * tileSize, y = row * tileSize;
      const w = Math.min(tileSize,width-x), h = Math.min(tileSize,height-y);
      let raw;
      try { raw = sourceContext.getImageData(x,y,w,h)?.data; }
      catch (_) { return failed(3); }
      if (!raw || raw.length !== w*h*4) return failed(3);
      let nonzero = false;
      for (let i = 0; i < raw.length; ++i) {
        if (raw[i] !== 0) { nonzero = true; break; }
      }
      if (!nonzero) { ++zeroTiles; continue; }
      ++nonzeroTiles;
      try {
        tileCanvas.width = w; tileCanvas.height = h;
        const ctx = tileCanvas.getContext?.('2d');
        if (!ctx || typeof ctx.drawImage !== 'function') return failed(2);
        ctx.drawImage(canvas,x,y,w,h,0,0,w,h);
        const blob = await new Promise((resolve,reject) => {
          try { tileCanvas.toBlob(resolve,'image/png'); } catch (error) { reject(error); }
        });
        if (blob?.type !== 'image/png' || !Number.isSafeInteger(blob?.size) || blob.size <= 0) return failed(4);
        encodedBytes += blob.size;
      } catch (_) { return failed(4); }
    }
  }
  return {ok:true, failureCode:0, encodedBytes, totalTiles:columns*rows,
    nonzeroTiles, zeroTiles, encodeMs:Math.max(0, Math.round(clock()-start))};
}
