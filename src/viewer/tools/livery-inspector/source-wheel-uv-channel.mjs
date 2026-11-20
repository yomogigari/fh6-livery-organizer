/**
 * 原本WheelテクスチャのglTF UVチャネルを、同梱Three.js r185のGLTFLoaderと同じ規則で解決する。
 * UV0固定による正常なUV1/2/3素材の誤拒否と、中立材質への意図しない後退を防ぐ。
 * 表示座標・シェーダー・車種固有の補正は行わない。
 */
export function sourceWheelUvAttributeName(channel) {
  if (!Number.isSafeInteger(channel) || channel < 0) return null;
  return channel === 0 ? 'uv' : (channel <= 3 ? `uv${channel}` : `texcoord_${channel}`);
}

export function sourceWheelGlbUvSemantic(channel) {
  return sourceWheelUvAttributeName(channel) === null ? null : `TEXCOORD_${channel}`;
}

export function sourceWheelTextureChannel(textureInfo) {
  if (!textureInfo || typeof textureInfo !== 'object') return null;
  const transform = textureInfo.extensions?.KHR_texture_transform;
  const hasOverride = transform && Object.prototype.hasOwnProperty.call(transform, 'texCoord');
  const raw = hasOverride ? transform.texCoord : (Object.prototype.hasOwnProperty.call(textureInfo, 'texCoord') ? textureInfo.texCoord : 0);
  return sourceWheelUvAttributeName(raw) === null ? null : raw;
}
