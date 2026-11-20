/**
 * rM002 GPU画像保存。rL系で実証したRGBA行反転とJPEG品質95の構造をr485に移植。
 * r485のscene、camera、renderer、C_livery、材質、GL状態を変更しない。
 * このモジュールは本プロジェクト独自コードで、第三者製デコーダーは含まない。
 */
export function frameBufferImage(ctx, readPixels, width, height) {
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) {
    throw new Error('GPU画像の幅または高さが不正です');
  }
  const raw = new Uint8Array(width * height * 4);
  readPixels(raw);
  const image = ctx.createImageData(width, height);
  const stride = width * 4;
  for (let y = 0; y < height; y++) {
    image.data.set(raw.subarray((height - 1 - y) * stride, (height - y) * stride), y * stride);
  }
  ctx.putImageData(image, 0, 0);
}

/** 既存WebGL最終画素を同ピクセル数で保存。プレビューの画質設定を勝手に変更しない。 */
export function downloadImage(canvas, name, {format = 'jpeg', quality = 0.95} = {}) {
  if (format !== 'jpeg' && format !== 'png') throw new Error('未対応の画像形式です');
  if (format === 'jpeg' ? !name.endsWith('.jpg') : !name.endsWith('.png')) {
    throw new Error('ファイル拡張子と画像形式が不一致です');
  }
  if (format === 'jpeg' && (!Number.isFinite(quality) || quality <= 0 || quality > 1)) {
    throw new Error('JPEG品質が不正です');
  }
  const mime = format === 'jpeg' ? 'image/jpeg' : 'image/png';
  return new Promise((resolve, reject) => canvas.toBlob(blob => {
    if (!blob || blob.type !== mime || !blob.size) {
      reject(new Error('指定した画像形式のエンコードに失敗しました'));
      return;
    }
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = name;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1200);
    resolve({bytes: blob.size, width: canvas.width, height: canvas.height});
  }, mime, format === 'jpeg' ? quality : undefined));
}

/**
 * 元のカメラ・視野角・材質・ペイント・レンダラーを保持したまま、Reference保存時だけ
 * 背面の画素数を4096幅に引き上げる。GPU予算超過は無告知の低解像度保存とせず拒否。
 * 単純なcanvas拡大ではなく、現行Viewerの描画コールバックで再レンダリングする。
 */
export function planReferenceCapture(width, height, targetWidth, maxDimension, maxPixels) {
  if (![width, height, targetWidth, maxDimension, maxPixels].every(Number.isSafeInteger)
      || width <= 0 || height <= 0 || targetWidth <= 0 || maxDimension <= 0 || maxPixels <= 0) {
    throw new Error('画像出力のGPU寸法・予算が不正です');
  }
  if (width >= targetWidth) return {width, height, upscale: false};
  const plannedHeight = Math.round(targetWidth * height / width);
  if (targetWidth > maxDimension || plannedHeight > maxDimension
      || targetWidth * plannedHeight > maxPixels) {
    throw new Error(`4K画像保存に必要なGPU容量・寸法が不足しています（要求${targetWidth}×${plannedHeight}px、上限${maxDimension}px/辺、${maxPixels}画素）。元の表示は変更しません。`);
  }
  return {width: targetWidth, height: plannedHeight, upscale: true};
}

export function withReferenceCaptureResolution({renderer, gl, cssWidth, cssHeight, pixelRatio,
    reference, renderFrame, capture, targetWidth = 4096, maxPixels}) {
  if (typeof renderFrame !== 'function' || typeof capture !== 'function') {
    throw new Error('GPU画像保存用の描画関数が不足しています');
  }
  if (!reference) return capture();
  const dims = gl.getParameter(gl.MAX_VIEWPORT_DIMS);
  const maxDimension = Math.min(
    gl.getParameter(gl.MAX_RENDERBUFFER_SIZE),
    renderer.capabilities.maxTextureSize,
    dims[0], dims[1]
  );
  const plan = planReferenceCapture(gl.drawingBufferWidth, gl.drawingBufferHeight,
    targetWidth, maxDimension, maxPixels);
  if (!plan.upscale) return capture();
  let modified = false;
  try {
    modified = true;
    renderer.setPixelRatio(1);
    renderer.setSize(plan.width, plan.height, false);
    if (gl.drawingBufferWidth !== plan.width || gl.drawingBufferHeight !== plan.height) {
      throw new Error('GPUが指定した4K描画バッファを確保できませんでした');
    }
    renderFrame();
    if (gl.getParameter(gl.FRAMEBUFFER_BINDING) !== null) {
      throw new Error('4Kレンダリング後にGPUの標準フレームバッファを復元できません');
    }
    return capture();
  } finally {
    // GPU/Canvas異常発生時も元ウィンドウ状態を必ず復元。誤寸法の静かな出力禁止。
    if (modified) {
      renderer.setPixelRatio(pixelRatio);
      renderer.setSize(cssWidth, cssHeight, false);
      renderFrame();
    }
  }
}

/** OSロケールに依存せず、画像ファイル名へ正確なJST時刻を付ける。 */
export function captureFilename(format, date = new Date()) {
  if (format !== 'jpeg' && format !== 'png') throw new Error('画像形式が不正です');
  if (!(date instanceof Date) || !Number.isFinite(date.valueOf())) throw new Error('画像日時が不正です');
  const pieces = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const byType = Object.fromEntries(pieces.map(part => [part.type, part.value]));
  const stamp = `${byType.year}${byType.month}${byType.day}-${byType.hour}${byType.minute}${byType.second}-JST`;
  return `Livery-Viewer-for-FH6-${stamp}.${format === 'jpeg' ? 'jpg' : 'png'}`;
}
