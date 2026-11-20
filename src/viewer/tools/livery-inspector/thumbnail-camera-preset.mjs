/**
 * 【2026-11-15 08:13 JST】FH6原本と最新Windows画像の目視差に基づく共通低角サムネイルカメラ。
 *
 * 元ModelBinの座標+Xは左側、+Zは前方。新規PR76 Car433は車首が画面左で屋根が大きいが、
 * FH6元bigThumbは車首が画面右かつ低角。-X・低いYの共通撮影方向に変更。
 * カメラは実画像に基づく候補で、FH6/Xboxの厳密FOV・外観一致は未承認。
 * 車種/ペイント/原本メッシュ/材質/照明には一切補正を加えない。
 * このプリセットをViewer初期表示、全Livery JPEG、全Stock JPEGで共用する。
 */
export const THUMBNAIL_CAMERA_PRESET_ID = 'fh6-thumbnail-right-front-low-three-quarter-v2';
export const THUMBNAIL_CAMERA_DIRECTION = Object.freeze([-1.60, 0.28, 1.05]);

export function thumbnailCameraDirection(makeVector3) {
  if (typeof makeVector3 !== 'function'
    || THUMBNAIL_CAMERA_DIRECTION.length !== 3
    || !THUMBNAIL_CAMERA_DIRECTION.every(Number.isFinite)) {
    throw new Error('サムネイル比較用のカメラ方向が不正です');
  }
  const [x, y, z] = THUMBNAIL_CAMERA_DIRECTION;
  const vector = makeVector3(x, y, z);
  if (!vector || typeof vector.clone !== 'function') {
    throw new Error('サムネイル比較用のVector3構築に失敗');
  }
  return vector;
}
