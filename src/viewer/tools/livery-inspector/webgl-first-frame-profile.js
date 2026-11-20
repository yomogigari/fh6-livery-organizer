// Optional first-frame WebGL CPU-call profiler. Never records shader sources,
// textures, geometry, hardware names or GL arguments. No acceptance state changes.
const METHOD_GROUPS = Object.freeze({
  Shader: ['compileShader', 'getShaderParameter', 'linkProgram', 'getProgramParameter'],
  Buffer: ['bufferData', 'bufferSubData'],
  Texture: ['texImage2D', 'texSubImage2D', 'compressedTexImage2D', 'compressedTexSubImage2D'],
  Draw: ['drawElements', 'drawArrays', 'drawElementsInstanced', 'drawArraysInstanced'],
  Target: ['framebufferTexture2D', 'renderbufferStorage', 'renderbufferStorageMultisample'],
  // Additional CPU-call profiling only. No extra GL requests or GPU readbacks.
  // Program lookup may synchronize the driver during initial material setup.
  Program: ['createProgram', 'getProgramInfoLog', 'getShaderInfoLog',
    'getUniformLocation', 'getAttribLocation', 'getActiveUniform', 'getActiveAttrib',
    'validateProgram', 'useProgram'],
  // Three.js uploads material, camera and per-mesh uniforms on first render.
  Uniform: ['uniformMatrix2fv', 'uniformMatrix3fv', 'uniformMatrix4fv',
    'uniform1f', 'uniform2f', 'uniform3f', 'uniform4f',
    'uniform1i', 'uniform2i', 'uniform3i', 'uniform4i',
    'uniform1fv', 'uniform2fv', 'uniform3fv', 'uniform4fv',
    'uniform1iv', 'uniform2iv', 'uniform3iv', 'uniform4iv',
    'uniform1ui', 'uniform1uiv', 'uniform4ui', 'uniform4uiv'],
  State: ['activeTexture', 'bindTexture', 'bindBuffer', 'bindVertexArray',
    'bindFramebuffer', 'enable', 'disable', 'pixelStorei', 'depthMask',
    'colorMask', 'blendFunc', 'blendFuncSeparate', 'blendEquation',
    'viewport', 'scissor'],
});

// r399: keep group totals for historical comparison, but distinguish which
// program/shader API triggers the synchronous delay. Exact allowlist only;
// no shader source, WebGL return values, arguments, driver names, or GL queries.
export const DETAILED_FIRST_FRAME_METHODS = Object.freeze([
  'createProgram', 'getProgramInfoLog', 'getShaderInfoLog',
  'getUniformLocation', 'getAttribLocation', 'getActiveUniform',
  'getActiveAttrib', 'validateProgram', 'useProgram',
  'compileShader', 'getShaderParameter', 'linkProgram', 'getProgramParameter',
]);
const DETAIL_METRIC_NAMES = Object.freeze(Object.fromEntries(
  DETAILED_FIRST_FRAME_METHODS.map(method => [method, method.charAt(0).toUpperCase() + method.slice(1)]),
));

export function createFirstFrameWebglProfiler(gl, clock = () => performance.now()) {
  const saved = [];
  const detailStats = Object.fromEntries(DETAILED_FIRST_FRAME_METHODS.map(method =>
    [method, {calls: 0, ms: 0}]));
  const stats = Object.fromEntries(Object.keys(METHOD_GROUPS)
    .map(group => [group, {calls: 0, ms: 0}]));
  if (!gl) return {finish: () => ({firstFrameGlInstrumentedMethods: 0})};
  let finished = false;
  for (const [group, methods] of Object.entries(METHOD_GROUPS)) {
    for (const method of methods) {
      const original = gl[method];
      if (typeof original !== 'function') continue;
      const owned = Object.prototype.hasOwnProperty.call(gl, method);
      const descriptor = owned ? Object.getOwnPropertyDescriptor(gl, method) : null;
      const replacement = function (...args) {
        const start = clock();
        try {
          return original.apply(gl, args);
        } finally {
          const elapsed = Math.max(0, clock() - start);
          stats[group].calls++;
          stats[group].ms += elapsed;
          const detail = detailStats[method];
          if (detail) {
            detail.calls++;
            detail.ms += elapsed;
          }
        }
      };
      try {
        Object.defineProperty(gl, method, {configurable: true, writable: true, value: replacement});
        if (gl[method] !== replacement) continue;
        saved.push({method, owned, descriptor});
      } catch (_error) {
        // Host WebGL objects can refuse own-property overrides. Skip safely.
      }
    }
  }
  return {
    finish() {
      if (finished) return {};
      finished = true;
      for (const {method, owned, descriptor} of saved.reverse()) {
        try {
          if (owned) Object.defineProperty(gl, method, descriptor);
          else delete gl[method];
        } catch (_error) {
          // Even if a driver refuses restoration, the wrapper delegates to
          // the original method and only records anonymous numeric totals.
        }
      }
      const result = {firstFrameGlInstrumentedMethods: saved.length};
      for (const [group, value] of Object.entries(stats)) {
        result[`firstFrameGl${group}Calls`] = value.calls;
        result[`firstFrameGl${group}Ms`] = Math.round(value.ms);
      }
      for (const [method, value] of Object.entries(detailStats)) {
        const metric = DETAIL_METRIC_NAMES[method];
        result[`firstFrameGl${metric}Calls`] = value.calls;
        result[`firstFrameGl${metric}Ms`] = Math.round(value.ms);
      }
      return result;
    },
  };
}

// r397: shadow-map rendering is a separate CPU-side pass inside Three.js.
// Record its elapsed time and GL draw call count without disabling shadows,
// reading private GPU information, or changing draw order. All probes are
// optional: wrappers are restored even when rendering fails.
export function createFirstFrameRenderPassProfiler(renderer, gl, clock = () => performance.now()) {
  const shadowMap = renderer?.shadowMap;
  const originalShadowRender = shadowMap?.render;
  let shadowWrapped = false;
  let shadowRenderDescriptor = null;
  let shadowRenderOwned = false;
  let shadowActive = false;
  let finished = false;
  let shadowPassMs = 0;
  let shadowPassCalls = 0;
  let shadowDrawCalls = 0;
  let nonShadowDrawCalls = 0;
  let shadowDrawCpuMs = 0;
  const savedDraws = [];
  if (typeof originalShadowRender === 'function') {
    shadowRenderOwned = Object.prototype.hasOwnProperty.call(shadowMap, 'render');
    shadowRenderDescriptor = shadowRenderOwned ? Object.getOwnPropertyDescriptor(shadowMap, 'render') : null;
    const replacement = function (...args) {
      const wasActive = shadowActive;
      shadowActive = true;
      const start = clock();
      try {
        return originalShadowRender.apply(shadowMap, args);
      } finally {
        shadowPassMs += Math.max(0, clock() - start);
        shadowPassCalls++;
        shadowActive = wasActive;
      }
    };
    try {
      Object.defineProperty(shadowMap, 'render', {configurable: true, writable: true, value: replacement});
      shadowWrapped = shadowMap.render === replacement;
    } catch (_error) {
      // Some runtime objects cannot be intercepted. Profile is optional.
    }
  }
  const methods = ['drawElements', 'drawArrays', 'drawElementsInstanced', 'drawArraysInstanced'];
  for (const method of methods) {
    if (typeof gl?.[method] !== 'function') continue;
    const original = gl[method];
    const owned = Object.prototype.hasOwnProperty.call(gl, method);
    const descriptor = owned ? Object.getOwnPropertyDescriptor(gl, method) : null;
    const replacement = function (...args) {
      const active = shadowWrapped && shadowActive;
      const start = active ? clock() : 0;
      try {
        return original.apply(gl, args);
      } finally {
        if (active) {
          shadowDrawCalls++;
          shadowDrawCpuMs += Math.max(0, clock() - start);
        } else {
          nonShadowDrawCalls++;
        }
      }
    };
    try {
      Object.defineProperty(gl, method, {configurable: true, writable: true, value: replacement});
      if (gl[method] === replacement) savedDraws.push({method, owned, descriptor});
    } catch (_error) {
      // Keep rendering when any GL method rejects interception.
    }
  }
  return {
    finish() {
      if (finished) return {};
      finished = true;
      for (const {method, owned, descriptor} of savedDraws.reverse()) {
        try {
          if (owned) Object.defineProperty(gl, method, descriptor);
          else delete gl[method];
        } catch (_error) { /* instrumented wrapper still delegates to original */ }
      }
      if (shadowWrapped) {
        try {
          if (shadowRenderOwned) Object.defineProperty(shadowMap, 'render', shadowRenderDescriptor);
          else delete shadowMap.render;
        } catch (_error) { /* original render is still called by wrapper */ }
      }
      return {
        firstFrameShadowProfileAvailable: shadowWrapped ? 1 : 0,
        firstFrameShadowPassCalls: shadowPassCalls,
        firstFrameShadowPassMs: Math.round(shadowPassMs),
        firstFrameShadowDrawCalls: shadowDrawCalls,
        firstFrameShadowDrawCpuMs: Math.round(shadowDrawCpuMs),
        firstFrameNonShadowDrawCalls: nonShadowDrawCalls,
      };
    },
  };
}
