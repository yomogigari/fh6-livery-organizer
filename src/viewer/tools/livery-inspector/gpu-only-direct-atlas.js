/*
 * LO4FH6 first-party GPU-only atlas compositor (research candidate).
 * Consumes WebGL2 framebuffer textures from GpuLiveryOffscreenRenderer.
 * No readPixels, Canvas2D drawImage, or CPU rasterization is performed.
 * IMPORTANT: affine texture filtering needs real-image/Xbox approval.
 */
const VERT = `#version 300 es
precision highp float;
uniform vec4 uBox;
uniform vec2 uAtlasSize;
void main() {
  // TRIANGLE_STRIP は 00,10,01,11 の順序で1枚の四角形を構成する。
  // 旧 00,10,11,01 は左中央を欠き、右中央を二重描画していた。
  vec2 pos = vec2((gl_VertexID == 1 || gl_VertexID == 3) ? 1.0 : 0.0,
                  (gl_VertexID >= 2) ? 1.0 : 0.0);
  vec2 pixel = uBox.xy + uBox.zw * pos;
  gl_Position = vec4(2.0 * pixel.x / uAtlasSize.x - 1.0,
                    1.0 - 2.0 * pixel.y / uAtlasSize.y, 0.0, 1.0);
}`;
const FRAG = `#version 300 es
precision highp float;
uniform sampler2D uSource;
uniform vec2 uAtlasSize;
uniform vec4 uTileBox;
uniform vec2 uSourceSize;
uniform vec2 uRenderSize;
uniform int uResolveX;
uniform int uResolveY;
uniform mat3 uOutputToInput;
uniform int uClearCount;
uniform int uClearOnly;
uniform vec4 uClearRects[32];
out vec4 outPaint;
void main() {
  vec2 atlas = vec2(gl_FragCoord.x, uAtlasSize.y - gl_FragCoord.y);
  // Exact border extrusion: corners outside both axes remain transparent.
  bool outsideX = atlas.x < uTileBox.x || atlas.x >= uTileBox.x + uTileBox.z;
  bool outsideY = atlas.y < uTileBox.y || atlas.y >= uTileBox.y + uTileBox.w;
  if (outsideX && outsideY) { outPaint = vec4(0.0); return; }
  vec2 p = clamp(atlas - uTileBox.xy, vec2(0.5), uTileBox.zw - vec2(0.5));
  vec2 source = (uOutputToInput * vec3(p, 1.0)).xy;
  // Source clearing takes precedence over texture sampling, exactly one stage.
  bool inClearRect = false;
  for (int i = 0; i < 32; ++i) {
    if (i >= uClearCount) break;
    vec4 r = uClearRects[i];
    if (source.x >= r.x && source.y >= r.y && source.x < r.x + r.z && source.y < r.y + r.w) {
      inClearRect = true; break;
    }
  }
  // PRIVATE研究用：追加バッチでは消去対象だけをalpha=1で出し、
  // 既存のAtlas領域をGPUブレンドで消去する。画素のCPU読戻しはしない。
  if (uClearOnly == 1) { outPaint = inClearRect ? vec4(0.0, 0.0, 0.0, 1.0) : vec4(0.0); return; }
  if (inClearRect) { outPaint = vec4(0.0); return; }
  vec2 uv = vec2(source.x / uSourceSize.x, 1.0 - source.y / uSourceSize.y);
  if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) {
    outPaint = vec4(0.0); return;
  }
  if (uResolveX <= 1 && uResolveY <= 1) {
    outPaint = texture(uSource, uv);
  } else {
    // PRIVATE比較: 高解像度FBOをベース解像度へ縮小してからアフィン合成する。
    // Premultiplied RGBAを平均してから通常テクスチャ補間する。
    // 元r485のCanvas高品質フィルタと完全一致を主張しない。
    vec4 sum = vec4(0.0);
    for (int y = 0; y < uResolveY; ++y) {
      for (int x = 0; x < uResolveX; ++x) {
        vec2 offset = (vec2(float(x) + 0.5, float(y) + 0.5)
                       / vec2(float(uResolveX), float(uResolveY))) - vec2(0.5);
        vec2 tap = vec2((source.x + offset.x) / uSourceSize.x,
                        1.0 - (source.y + offset.y) / uSourceSize.y);
        sum += texture(uSource, tap);
      }
    }
    outPaint = sum / float(uResolveX * uResolveY);
  }
}`;
function compile(gl, kind, source) {
  const shader = gl.createShader(kind);
  if (!shader) throw new Error('Cannot allocate GPU-only shader');
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) || 'Unknown GPU-only shader error';
    gl.deleteShader(shader);
    throw new Error(message);
  }
  return shader;
}
function checkedSize(values, name) {
  if (!Array.isArray(values) || values.length !== 2 || values.some(v => !Number.isInteger(v) || v < 1)) {
    throw new Error(`${name} dimensions are invalid`);
  }
  return values;
}
function affine(values) {
  if (!Array.isArray(values) || values.length !== 6 || values.some(v => !Number.isFinite(Number(v)))) {
    throw new Error('GPU-only atlas requires a finite six-element output-to-input affine');
  }
  const m = values.map(Number);
  if (Math.abs(m[0] * m[4] - m[1] * m[3]) < 1e-12) throw new Error('GPU-only atlas affine is singular');
  return [m[0], m[3], 0, m[1], m[4], 0, m[2], m[5], 1];
}
export class GpuOnlyDirectAtlas {
  constructor(gl, canvas, width, height, options = {}) {
    checkedSize([width, height], 'atlas');
    if (canvas.width !== width || canvas.height !== height) throw new Error('GPU-only atlas canvas dimensions differ');
    if (width > gl.getParameter(gl.MAX_TEXTURE_SIZE) || height > gl.getParameter(gl.MAX_TEXTURE_SIZE)) {
      throw new Error('GPU-only atlas exceeds MAX_TEXTURE_SIZE');
    }
    if (width > gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) || height > gl.getParameter(gl.MAX_RENDERBUFFER_SIZE)) {
      throw new Error('GPU-only atlas exceeds MAX_RENDERBUFFER_SIZE');
    }
    this.gl = gl; this.canvas = canvas; this.width = width; this.height = height;
    this.experimentalBoxResolve = options.experimentalBoxResolve === true;
    this.experimentalChunkedClearRects = options.experimentalChunkedClearRects === true;
    this.shaders = [compile(gl, gl.VERTEX_SHADER, VERT), compile(gl, gl.FRAGMENT_SHADER, FRAG)];
    this.program = gl.createProgram();
    gl.attachShader(this.program, this.shaders[0]);
    gl.attachShader(this.program, this.shaders[1]);
    gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(this.program) || 'GPU-only atlas link failed');
    this.locations = Object.fromEntries(['uBox','uAtlasSize','uTileBox','uSourceSize','uRenderSize','uResolveX','uResolveY','uOutputToInput','uClearCount','uClearOnly','uClearRects[0]']
      .map(n => [n, gl.getUniformLocation(this.program, n)]));
    this.texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    this.framebuffer = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.texture, 0);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw new Error('GPU-only atlas FBO is incomplete');
    gl.viewport(0, 0, width, height);
    gl.disable(gl.SCISSOR_TEST); gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    this.vao = gl.createVertexArray();
    this.tileCount = 0;
  }
  compose(target, meta, box, padding) {
    const gl = this.gl, u = this.locations;
    if (!target?.texture || !target?.width || !target?.height) throw new Error('GPU-only target texture unavailable');
    const sourceSize = checkedSize(Array.from(meta?.source_size || []).map(Number), 'source');
    const tileSize = checkedSize(Array.from(meta?.tile_size || []).map(Number), 'tile');
    if (box.width !== tileSize[0] || box.height !== tileSize[1]) throw new Error('GPU-only tile size mismatch');
    const p = Number(padding);
    if (!Number.isInteger(p) || p < 0 || p > 4096) throw new Error('GPU-only padding invalid');
    const left = box.left - p, top = box.top - p;
    const width = box.width + 2 * p, height = box.height + 2 * p;
    if (left < 0 || top < 0 || left + width > this.width || top + height > this.height) throw new Error('GPU-only atlas padding out of bounds');
    const matrix = affine(meta.pillow_output_to_input_affine);
    const rects = Array.from(meta?.source_clear_rects || []);
    // 未承認のGPU研究経路だけ、固定32件上限を描画バッチに分割する。通常経路は不変。
    if (rects.length > 32 && !this.experimentalChunkedClearRects) throw new Error('GPU-only source clear rectangle budget exceeded');
    for (const rect of rects) if (!Array.isArray(rect) || rect.length !== 4 || rect.some(x=>!Number.isFinite(Number(x)))) throw new Error('Invalid source clear rectangle');
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffer);
    gl.viewport(0, 0, this.width, this.height);
    gl.disable(gl.SCISSOR_TEST); gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST);
    gl.bindVertexArray(this.vao);
    gl.useProgram(this.program);
    gl.uniform2f(u.uAtlasSize, this.width, this.height);
    gl.uniform4f(u.uBox, left, top, width, height);
    gl.uniform4f(u.uTileBox, box.left, box.top, box.width, box.height);
    gl.uniform2f(u.uSourceSize, ...sourceSize);
    gl.uniform2f(u.uRenderSize, target.width, target.height);
    let resolveX = 1, resolveY = 1;
    if (this.experimentalBoxResolve) {
      resolveX = target.width / sourceSize[0];
      resolveY = target.height / sourceSize[1];
      if (!Number.isSafeInteger(resolveX) || resolveX < 1 || !Number.isSafeInteger(resolveY) || resolveY < 1) {
        throw new Error('GPU-only supersample comparison requires exact integer render/source ratios');
      }
    }
    gl.uniform1i(u.uResolveX, resolveX);
    gl.uniform1i(u.uResolveY, resolveY);
    gl.uniformMatrix3fv(u.uOutputToInput, false, new Float32Array(matrix));
    gl.uniform1i(u.uClearOnly, 0);
    const initialRectBatch = rects.slice(0, 32);
    gl.uniform1i(u.uClearCount, initialRectBatch.length);
    if (initialRectBatch.length) gl.uniform4fv(u['uClearRects[0]'], new Float32Array(initialRectBatch.flat().map(Number)));
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, target.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.uniform1i(gl.getUniformLocation(this.program, 'uSource'), 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    if (rects.length > 32) {
      // 以降の32件単位をGPU-onlyで適用する。上限を画像の画質や車種に依存させない。
      // ONE_MINUS_SRC_ALPHAが対象画素だけを消し、未該当画素を保持する。
      // 後続3D/ガラス描画へGLブレンド状態が漏れないよう、式と係数を保存する。
      // BLENDの有効状態は既存標準経路と同じdisabledへ戻す。
      const blendState = [gl.getParameter(gl.BLEND_EQUATION_RGB), gl.getParameter(gl.BLEND_EQUATION_ALPHA),
        gl.getParameter(gl.BLEND_SRC_RGB), gl.getParameter(gl.BLEND_DST_RGB),
        gl.getParameter(gl.BLEND_SRC_ALPHA), gl.getParameter(gl.BLEND_DST_ALPHA)];
      gl.enable(gl.BLEND);
      try {
        gl.blendEquation(gl.FUNC_ADD);
        gl.blendFunc(gl.ZERO, gl.ONE_MINUS_SRC_ALPHA);
        gl.uniform1i(u.uClearOnly, 1);
        for (let offset = 32; offset < rects.length; offset += 32) {
          const batch = rects.slice(offset, offset + 32);
          gl.uniform1i(u.uClearCount, batch.length);
          gl.uniform4fv(u['uClearRects[0]'], new Float32Array(batch.flat().map(Number)));
          gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        }
      } finally {
        gl.disable(gl.BLEND);
        gl.blendEquationSeparate(blendState[0], blendState[1]);
        gl.blendFuncSeparate(blendState[2], blendState[3], blendState[4], blendState[5]);
        gl.uniform1i(u.uClearOnly, 0);
      }
    }
    const error = gl.getError();
    if (error !== gl.NO_ERROR) throw new Error(`GPU-only atlas compositor GL error ${error}`);
    this.tileCount++;
  }
  finish(expectedCount) {
    const gl=this.gl;
    if (!Number.isSafeInteger(expectedCount) || expectedCount < 1 || this.tileCount !== expectedCount) {
      throw new Error(`GPU-only atlas incomplete: ${this.tileCount}/${expectedCount}`);
    }
    gl.disable(gl.SCISSOR_TEST);
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, this.framebuffer);
    gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, null);
    gl.blitFramebuffer(0, 0, this.width, this.height, 0, 0, this.width, this.height, gl.COLOR_BUFFER_BIT, gl.NEAREST);
    if (gl.getError() !== gl.NO_ERROR) throw new Error('GPU-only atlas blit to WebGL canvas failed');
    gl.flush();
    return this.canvas;
  }
  dispose(){const gl=this.gl; if(this.vao)gl.deleteVertexArray(this.vao);if(this.framebuffer)gl.deleteFramebuffer(this.framebuffer);if(this.texture)gl.deleteTexture(this.texture);if(this.program)gl.deleteProgram(this.program);for(const x of this.shaders||[])gl.deleteShader(x);}
}
