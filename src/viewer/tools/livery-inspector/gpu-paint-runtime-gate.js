/* rM036 first-party strict GPU-only paint contract. No GPU to CPU paint fallback. */
export const GPU_PAINT_CONTRACT = 'lo4fh6.gpu_only_paint.v1';
export class GpuPaintUnavailableError extends Error {
  constructor(reason) {
    super('GPU-only livery paint unavailable: ' + reason);
    this.name = 'GpuPaintUnavailableError';
    this.code = 'LO4FH6_GPU_PAINT_UNAVAILABLE';
  }
}
export function requireGpuPaintRuntime(contract, gl) {
  if (contract?.cpu_shadow_policy !== 'gpu-only'
      || contract?.paint_rasterizer !== 'webgl2-only'
      || contract?.files?.paint) {
    throw new GpuPaintUnavailableError('GPU-only paint contract required; CPU paint atlas prohibited');
  }
  if (!gl || typeof gl.createFramebuffer !== 'function'
      || typeof gl.drawArrays !== 'function' || typeof gl.blitFramebuffer !== 'function'
      || typeof gl.checkFramebufferStatus !== 'function'
      || (typeof WebGL2RenderingContext !== 'undefined' && !(gl instanceof WebGL2RenderingContext))) {
    throw new GpuPaintUnavailableError('WebGL2 context is required');
  }
  if (typeof gl.isContextLost === 'function' && gl.isContextLost()) {
    throw new GpuPaintUnavailableError('WebGL2 context lost');
  }
  return GPU_PAINT_CONTRACT;
}
export function assertGpuAtlasComplete(compositor, expectedTiles) {
  if (!Number.isSafeInteger(expectedTiles) || expectedTiles < 1
      || compositor?.tileCount !== expectedTiles) {
    throw new GpuPaintUnavailableError('GPU atlas tile count incomplete');
  }
  return true;
}
