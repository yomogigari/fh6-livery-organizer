/**
 * 製品ブラウザーが実際に受信したGLBから原本Wheelの署名とPNG実体を確認する。
 * サーバーの生成証拠ではなくHTTP応答のバイト列を検査し、未接続の黒円盤を
 * 正常な原本材質描画として黙認しない。色・位置・Shaderには介入しない。
 */
import {sourceWheelGlbUvSemantic, sourceWheelTextureChannel} from './source-wheel-uv-channel.mjs';

const ORIGIN = 'fh6-local-original-modelbin-materialbin-shaderbin-texture2d-v1';
const PNG_MAGIC = [137,80,78,71,13,10,26,10];
const decoder = new TextDecoder('utf-8', {fatal: true});

function reject(why) { throw new Error('原本Wheel GLB配信検証失敗: ' + why); }
function validIndex(value, array) {
  return Number.isSafeInteger(value) && value >= 0 && value < array.length;
}
// 第一者GLBの現行名と、受入済みGLBの旧名を共通に扱う。
// 異なる二重宣言はキャッシュや入力破損として明示拒否する。
function wheelPartType(extras) {
  const current = extras?.lo4fh6_part_type;
  const legacy = extras?.lo4_part_type;
  if (current !== undefined && legacy !== undefined && current !== legacy) {
    reject('Wheelの新旧メタデータ名が矛盾');
  }
  return current ?? legacy;
}

export function inspectReceivedSourceWheelGlb(input, {requireSigned = true} = {}) {
  const bytes = input instanceof Uint8Array ? input
    : (input instanceof ArrayBuffer ? new Uint8Array(input) : null);
  if (!bytes || bytes.byteLength < 28) reject('GLBデータが不足');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2
      || view.getUint32(8, true) !== bytes.byteLength) reject('glTF2ヘッダー/サイズ不一致');
  const jsonLength = view.getUint32(12, true);
  if (view.getUint32(16, true) !== 0x4e4f534a || jsonLength < 2
      || jsonLength > bytes.byteLength - 28 || jsonLength % 4 !== 0) reject('GLB JSONチャンク不正');
  const binHead = 20 + jsonLength;
  const binLength = view.getUint32(binHead, true);
  if (view.getUint32(binHead + 4, true) !== 0x004e4942
      || binHead + 8 + binLength !== bytes.byteLength) reject('GLB BINチャンク不正');
  let doc;
  try { doc = JSON.parse(decoder.decode(bytes.subarray(20, binHead))); }
  catch (_) { reject('GLB JSONを解析できません'); }
  const materials = Array.isArray(doc.materials) ? doc.materials : [];
  const meshes = Array.isArray(doc.meshes) ? doc.meshes : [];
  const textures = Array.isArray(doc.textures) ? doc.textures : [];
  const images = Array.isArray(doc.images) ? doc.images : [];
  const bufferViews = Array.isArray(doc.bufferViews) ? doc.bufferViews : [];
  const signed = new Set();
  for (let i = 0; i < materials.length; i++) {
    if (materials[i]?.extras?.lo4fh6_original_source_wheel_texture === ORIGIN) signed.add(i);
  }
  let primitives = 0;
  const imagesUsed = new Set();
  for (const mesh of meshes) {
    if (wheelPartType(mesh?.extras) !== 'WheelStyle') continue;
    for (const primitive of Array.isArray(mesh.primitives) ? mesh.primitives : []) {
      if (!signed.has(primitive?.material)) continue;
      // GLTFLoader r185で実際に使うUVを確認する。KHR_texture_transformの
      // texCoord上書きを優先し、別チャネルのUV0を根拠に合格としない。
      const textureInfo = materials[primitive.material]?.pbrMetallicRoughness?.baseColorTexture;
      const channel = sourceWheelTextureChannel(textureInfo);
      const semantic = sourceWheelGlbUvSemantic(channel);
      if (semantic === null) reject('署名付きWheelの原本texCoordが不正');
      if (!validIndex(primitive?.attributes?.[semantic], Array.isArray(doc.accessors) ? doc.accessors : [])) {
        reject(`署名付きWheelに${semantic}がありません`);
      }
      const index = textureInfo?.index;
      if (!validIndex(index, textures)) reject('署名付き材質のTexture参照不正');
      const imageId = textures[index]?.source;
      if (!validIndex(imageId, images)) reject('Texture→Image参照不正');
      const image = images[imageId];
      const bufferViewId = image?.bufferView;
      if (image?.mimeType !== 'image/png' || !validIndex(bufferViewId, bufferViews)) {
        reject('署名付き材質のPNG参照不正');
      }
      const region = bufferViews[bufferViewId];
      const start = region?.byteOffset ?? 0, size = region?.byteLength;
      if (region?.buffer !== 0 || !Number.isSafeInteger(start) || !Number.isSafeInteger(size)
          || start < 0 || size < 24 || start + size > binLength) reject('原本PNGのBIN領域が不正');
      const offset = binHead + 8 + start;
      if (!PNG_MAGIC.every((value, i) => bytes[offset + i] === value)
          || bytes[offset + size - 8] !== 73 || bytes[offset + size - 7] !== 69
          || bytes[offset + size - 6] !== 78 || bytes[offset + size - 5] !== 68) {
        reject('原本PNG実バイトが不正');
      }
      imagesUsed.add(imageId);
      primitives++;
    }
  }
  if (requireSigned && (primitives === 0 || signed.size === 0)) {
    reject('署名付き原本材質が配信GLBにありません（古いキャッシュ／未接続の可能性）');
  }
  return Object.freeze({signedMaterials:signed.size,signedWheelPrimitives:primitives,
    referencedImages:imagesUsed.size,source:'received-glb-bytes',
    gpuDrawn:false,xboxApproved:false});
}
