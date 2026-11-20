/**
 * 旧Viewerの6方向完成車両キャプチャ機能を再構成する第一者コード。
 * 元の完成3D Viewerから描かれたGPUフレームを受け取って並べるだけで、
 * UV画像・ペイントアトラス・簡易描画器を代用しない。
 */
export const SIX_CAR_VIEWS = Object.freeze([
  Object.freeze({key:'left', label:'左側面'}),
  Object.freeze({key:'front', label:'前面'}),
  Object.freeze({key:'right', label:'右側面'}),
  Object.freeze({key:'back', label:'後面'}),
  Object.freeze({key:'top', label:'上面'}),
  Object.freeze({key:'bottom', label:'下面'}),
]);

/** 各方向を同じGPUフレーム解像度で描き、3列×2行に合成する。 */
export function composeSixCarViews({width,height,createCanvas,renderView,views=SIX_CAR_VIEWS}) {
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0
      || !Array.isArray(views) || views.length !== 6 || typeof createCanvas !== 'function'
      || typeof renderView !== 'function') throw new Error('6方向画像の入力が不正です');
  const titleHeight = 34;
  const sheetWidth = width * 3;
  const sheetHeight = (height + titleHeight) * 2;
  if (!Number.isSafeInteger(sheetWidth * sheetHeight)) throw new Error('6方向画像の寸法が大きすぎます');
  const sheet = createCanvas();
  sheet.width = sheetWidth;
  sheet.height = sheetHeight;
  const ctx = sheet.getContext('2d');
  if (!ctx) throw new Error('6方向画像の合成Canvasを作成できません');
  ctx.font = 'bold 17px "Yu Gothic", "Meiryo", sans-serif';
  ctx.textBaseline = 'middle';
  for (const [index, view] of views.entries()) {
    if (!view?.key || !view?.label) throw new Error('6方向画像の方向定義が不正です');
    const x = (index % 3) * width;
    const y = Math.floor(index / 3) * (height + titleHeight);
    const frame = renderView(view.key);
    if (!frame || frame.width !== width || frame.height !== height) {
      throw new Error('6方向GPU画像の描画サイズが一致しません: ' + view.key);
    }
    ctx.fillStyle = '#17202a';
    ctx.fillRect(x, y, width, titleHeight);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(view.label, x + 12, y + titleHeight / 2);
    ctx.drawImage(frame, x, y + titleHeight, width, height);
  }
  return sheet;
}
