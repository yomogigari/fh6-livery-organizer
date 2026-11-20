/* FH6 Decals.zip由来RGBAのWebGL2研究用描画。標準入口では未承認のまま。 */
export const RASTER_MAGIC = 'LO4GRD01';

export function parseRasterDecalPack(buffer) {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes.length < 16) throw new Error('raster decal pack header is truncated');
  const magic = String.fromCharCode(...bytes.subarray(0, 8));
  if (magic !== RASTER_MAGIC || view.getUint32(8, true) !== 1) {
    throw new Error('raster decal pack format is unsupported');
  }
  const count = view.getUint32(12, true);
  if (count > Math.trunc((bytes.length - 16) / 16)) throw new Error('raster decal directory is truncated');
  const entries = new Map();
  let offset = 16;
  for (let i = 0; i < count; i += 1) {
    if (offset + 16 > bytes.length) throw new Error('raster decal entry header is truncated');
    const id = view.getUint32(offset, true);
    const width = view.getUint32(offset + 4, true);
    const height = view.getUint32(offset + 8, true);
    const length = view.getUint32(offset + 12, true);
    offset += 16;
    if (!id || !width || !height || length !== width * height * 4 || offset + length > bytes.length || entries.has(id)) {
      throw new Error('raster decal entry is invalid or duplicated');
    }
    entries.set(id, {width, height, pixels: bytes.slice(offset, offset + length)});
    offset += length;
  }
  if (offset !== bytes.length) throw new Error('raster decal pack contains trailing bytes');
  return {entries};
}

export function createRasterPlacement(record, bounds, asset, toWorldPoint) {
  if (!asset || !Number.isInteger(asset.width) || !Number.isInteger(asset.height) ||
      asset.width < 1 || asset.height < 1 || !asset.pixels || !toWorldPoint) {
    throw new Error('raster decal image unavailable');
  }
  const [minX, minY, maxX, maxY] = bounds;
  const w = asset.width, h = asset.height;
  // 元SwatchBinの行0は上端。GPUの行0を下端にアップロードし、
  // 上辺をV=1へ割り当てることで原本の上下方向を保持する。
  const corners = [
    [-w / 2, h / 2, 0, 1], [w / 2, h / 2, 1, 1],
    [w / 2, -h / 2, 1, 0], [-w / 2, -h / 2, 0, 0],
  ];
  const clip = corners.map(([x, y, u, v]) => {
    const [wx, wy] = toWorldPoint(x, y);
    return [((wx - minX) / (maxX - minX)) * 2 - 1, ((wy - minY) / (maxY - minY)) * 2 - 1, u, v];
  });
  const vertices = new Float32Array(6 * 6);
  let offset = 0;
  for (const index of [0, 1, 2, 0, 2, 3]) {
    const [x, y, u, v] = clip[index];
    vertices.set([x, y, u, v, 0, 0], offset);
    offset += 6;
  }
  const xs = clip.map(p => p[0]), ys = clip.map(p => p[1]);
  return {
    mode: (record.flags & 0x01) ? 'mask' : 'paint',
    recordIndex: record.index,
    rasterId: record.rasterId,
    rasterAsset: asset,
    rasterOpacity: record.color[3] / 255,
    hasVertexAlpha: true,
    triangleCount: 2,
    clipBounds: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
    vertices,
  };
}

const VERTEX = `#version 300 es
layout(location=0) in vec2 a_position;
layout(location=1) in vec4 a_uv_with_padding;
out vec2 v_uv;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
  v_uv = a_uv_with_padding.xy;
}`;
const FRAGMENT = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_image;
uniform float u_opacity;
out vec4 out_color;
void main() {
  vec4 decal = texture(u_image, v_uv);
  float alpha = decal.a * u_opacity;
  out_color = vec4(decal.rgb * alpha, alpha);
}`;

function compile(gl, kind, source) {
  const shader = gl.createShader(kind);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const error = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error('raster decal WebGL2 shader compile failed: ' + error);
  }
  return shader;
}

export class GpuRasterDecalPass {
  constructor(gl) {
    this.gl = gl;
    const vs = compile(gl, gl.VERTEX_SHADER, VERTEX);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      const error = gl.getProgramInfoLog(program);
      gl.deleteProgram(program);
      throw new Error('raster decal WebGL2 program link failed: ' + error);
    }
    this.program = program;
    this.image = gl.getUniformLocation(program, 'u_image');
    this.opacity = gl.getUniformLocation(program, 'u_opacity');
    this.textures = new Map();
  }

  paint(placement, first, count) {
    const gl = this.gl;
    let texture = this.textures.get(placement.rasterId);
    if (!texture) {
      const asset = placement.rasterAsset;
      const maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
      if (asset.width > maxTextureSize || asset.height > maxTextureSize) {
        throw new Error('FH6 original raster decal exceeds WebGL2 MAX_TEXTURE_SIZE');
      }
      texture = gl.createTexture();
      if (!texture) throw new Error('raster decal texture allocation failed');
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, asset.width, asset.height, 0,
        gl.RGBA, gl.UNSIGNED_BYTE, asset.pixels);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      if (gl.getError() !== gl.NO_ERROR) {
        gl.deleteTexture(texture);
        throw new Error('FH6 original raster decal upload failed');
      }
      this.textures.set(placement.rasterId, texture);
    }
    gl.useProgram(this.program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.uniform1i(this.image, 0);
    gl.uniform1f(this.opacity, placement.rasterOpacity);
    gl.drawArrays(gl.TRIANGLES, first, count);
  }

  dispose() {
    for (const texture of this.textures.values()) this.gl.deleteTexture(texture);
    this.textures.clear();
    if (this.program) this.gl.deleteProgram(this.program);
    this.program = null;
  }
}
