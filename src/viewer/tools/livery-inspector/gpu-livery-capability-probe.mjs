/*
 * 実WebGL2 RGBA8レンダーターゲットの非破壊検査。
 * Three.js が所有する描画コンテキストのバインディングを保存・同期復帰する。
 * Python/pywebviewへのawaitは本関数の完了後だけ許可する。
 * CPUペイント代替・簡易描画器ではない。
 */
export function probeWebgl2Rgba8RenderTarget(gl) {
  const info = {
    webgl2: false,
    offscreen_framebuffer: false,
    rgba8_render_target: false,
    probe_reason: 'no_webgl2',
    framebuffer_status: null,
    gl_error: null,
    context_lost: false,
  };
  if (!gl || typeof gl.texImage2D !== 'function' || typeof gl.checkFramebufferStatus !== 'function'
      || typeof gl.RGBA8 !== 'number' || typeof gl.DRAW_FRAMEBUFFER !== 'number') return info;
  info.webgl2 = true;
  let framebuffer = null, texture = null;
  let previousTexture, previousDrawFramebuffer, previousReadFramebuffer;
  let bound = false;
  try {
    info.context_lost = Boolean(gl.isContextLost?.());
    if (info.context_lost) { info.probe_reason = 'context_lost'; return info; }
    previousTexture = gl.getParameter(gl.TEXTURE_BINDING_2D);
    previousDrawFramebuffer = gl.getParameter(gl.DRAW_FRAMEBUFFER_BINDING);
    previousReadFramebuffer = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING);
    bound = true;
    framebuffer = gl.createFramebuffer();
    texture = gl.createTexture();
    if (!framebuffer || !texture) {
      info.probe_reason = 'target_allocation_failed';
      return info;
    }
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 4, 4, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
    info.framebuffer_status = Number(gl.checkFramebufferStatus(gl.FRAMEBUFFER));
    info.gl_error = Number(gl.getError());
    info.context_lost = Boolean(gl.isContextLost?.());
    const good = info.framebuffer_status === gl.FRAMEBUFFER_COMPLETE
      && info.gl_error === gl.NO_ERROR && !info.context_lost;
    info.offscreen_framebuffer = good;
    info.rgba8_render_target = good;
    info.probe_reason = good ? 'rgba8_fbo_complete'
      : info.context_lost ? 'context_lost'
        : info.gl_error !== gl.NO_ERROR ? 'webgl_error'
          : 'framebuffer_incomplete';
    return info;
  } catch (error) {
    info.probe_reason = 'probe_exception';
    info.probe_error_name = String(error?.name || 'Error').slice(0, 48);
    return info;
  } finally {
    // Three.jsの内部GL状態と一致するよう元のREAD/DRAW/テクスチャを全て復帰。
    // Pythonの非同期API呼び出し中にプローブFBOをバインドしたままにしない。
    if (bound) {
      try {
        gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, previousDrawFramebuffer);
        gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previousReadFramebuffer);
        gl.bindTexture(gl.TEXTURE_2D, previousTexture);
      } catch (_error) {
        info.probe_reason = 'restore_failed';
        info.offscreen_framebuffer = false;
        info.rgba8_render_target = false;
      }
    }
    if (framebuffer) gl.deleteFramebuffer(framebuffer);
    if (texture) gl.deleteTexture(texture);
  }
}
