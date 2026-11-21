/**
 * 保存する画像（現在視点・6方向）の下に、ペイントの情報の帯を付ける第一者コード（2026-11-21）。
 * 帯の 1 行目はタイトル、2 行目は作成者・アップロード日・撮影日時（無い項目は書かない）。
 * GPU で描いた画像はそのまま上に置き、帯の分だけ下へ伸ばす。描画・カメラ・寸法の決め方は変えない。
 */
export const CAPTION_COLORS = Object.freeze({band: '#17202a', title: '#ffffff', detail: '#c4ced8'});
const CAPTION_FONT = '"Yu Gothic UI", "Yu Gothic", "Meiryo", "Segoe UI", sans-serif';
const DETAIL_SEPARATOR = '   ·   ';

/** 撮影日時の文字（日本時間の「日/月/年 時:分 JST」。FH6 とレポートのアップロード日と同じ並び）。 */
export function formatCaptureTime(date = new Date()) {
  if (!(date instanceof Date) || !Number.isFinite(date.valueOf())) throw new Error('撮影日時が不正です');
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${byType.day}/${byType.month}/${byType.year} ${byType.hour}:${byType.minute} JST`;
}

/** 帯の 2 行の文字。fields = {title, creator, uploadDate, capturedAt}、labels = {creator, uploaded, captured}。 */
export function captionLines(fields = {}, labels = {}) {
  const text = value => String(value ?? '').replace(/\s+/g, ' ').trim();
  const details = [];
  if (text(fields.creator)) details.push(`${labels.creator}: ${text(fields.creator)}`);
  if (text(fields.uploadDate)) details.push(`${labels.uploaded}: ${text(fields.uploadDate)}`);
  if (text(fields.capturedAt)) details.push(`${labels.captured}: ${text(fields.capturedAt)}`);
  return {title: text(fields.title), detail: details.join(DETAIL_SEPARATOR)};
}

/** 幅に収まらない文字は、末尾を「…」にして切る（絵文字などを途中で割らないよう、文字の単位で切る）。 */
export function fitCaptionText(ctx, text, maxWidth) {
  if (!text || ctx.measureText(text).width <= maxWidth) return text;
  const chars = Array.from(text);
  let low = 0;
  let high = chars.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (ctx.measureText(chars.slice(0, mid).join('') + '…').width <= maxWidth) low = mid;
    else high = mid - 1;
  }
  return chars.slice(0, low).join('') + '…';
}

/** 帯の文字の大きさと余白（画像の幅に合わせる。小さな画像でも読める大きさ・大きな画像でも目立ちすぎない大きさ）。 */
export function captionMetrics(width) {
  const title = Math.max(16, Math.min(44, Math.round(width * 0.016)));
  const detail = Math.max(13, Math.round(title * 0.72));
  return {title, detail, padX: Math.round(title * 0.8), padY: Math.round(title * 0.6), gap: Math.round(title * 0.35)};
}

/** 画像の下に帯を足した、新しい Canvas を返す（渡した画像は変えない）。書く文字が無いときは、渡した画像を返す。 */
export function appendCaptureCaption({image, fields, labels, createCanvas}) {
  if (!image || !Number.isSafeInteger(image.width) || !Number.isSafeInteger(image.height)
      || image.width <= 0 || image.height <= 0 || typeof createCanvas !== 'function') {
    throw new Error('帯を付ける画像の入力が不正です');
  }
  const {title, detail} = captionLines(fields, labels);
  const size = captionMetrics(image.width);
  const lines = [
    title && {text: title, size: size.title, weight: 'bold', color: CAPTION_COLORS.title},
    detail && {text: detail, size: size.detail, weight: 'normal', color: CAPTION_COLORS.detail},
  ].filter(Boolean);
  if (!lines.length) return image;
  const heights = lines.map(line => Math.round(line.size * 1.3));
  const bandHeight = size.padY * 2 + heights.reduce((sum, value) => sum + value, 0) + size.gap * (lines.length - 1);
  const sheet = createCanvas();
  sheet.width = image.width;
  sheet.height = image.height + bandHeight;
  if (!Number.isSafeInteger(sheet.width * sheet.height)) throw new Error('帯を付けた画像の寸法が大きすぎます');
  const ctx = sheet.getContext('2d');
  if (!ctx) throw new Error('帯を付ける Canvas を作成できません');
  ctx.drawImage(image, 0, 0);
  ctx.fillStyle = CAPTION_COLORS.band;
  ctx.fillRect(0, image.height, image.width, bandHeight);
  ctx.textBaseline = 'middle';
  let y = image.height + size.padY;
  lines.forEach((line, index) => {
    ctx.font = `${line.weight} ${line.size}px ${CAPTION_FONT}`;
    ctx.fillStyle = line.color;
    ctx.fillText(fitCaptionText(ctx, line.text, image.width - size.padX * 2), size.padX, y + heights[index] / 2);
    y += heights[index] + size.gap;
  });
  return sheet;
}
