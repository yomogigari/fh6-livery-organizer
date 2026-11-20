// r414: Preview-only GPU pixelation. The vehicle silhouette is rendered from the
// current camera every frame; this does not modify materials or saved C_livery.
export const DEMO_MOSAIC_STRENGTHS = Object.freeze([12, 24, 40]);
export function normalizedDemoStrength(value) {
  const n = Number(value);
  return DEMO_MOSAIC_STRENGTHS.includes(n) ? n : 24;
}
export function maskedDemoText(value, hidden, placeholder) {
  return hidden ? placeholder : String(value ?? '');
}
export function createDemoVehicleMosaic(THREE, renderer, scene, camera, options) {
  let colorTarget = null;
  let maskTarget = null;
  let quadScene = null;
  let quadCamera = null;
  let quadMaterial = null;
  let quadGeometry = null;
  let maskMaterial = null;
  const maskBlack = new THREE.Color(0x000000);
  function disposeTargets() {
    colorTarget?.dispose(); maskTarget?.dispose();
    colorTarget = null; maskTarget = null;
  }
  function ensureTargets() {
    const size = renderer.getDrawingBufferSize(new THREE.Vector2());
    const width = Math.max(1, Math.round(size.x));
    const height = Math.max(1, Math.round(size.y));
    // A small silhouette buffer follows the current camera. The full-resolution
    // color buffer retains the unmasked background quality.
    const scale = Math.min(1, 1280 / width, 1280 / height);
    const maskWidth = Math.max(1, Math.ceil(width * scale));
    const maskHeight = Math.max(1, Math.ceil(height * scale));
    if (!colorTarget || colorTarget.width !== width || colorTarget.height !== height ||
        !maskTarget || maskTarget.width !== maskWidth || maskTarget.height !== maskHeight) {
      disposeTargets();
      colorTarget = new THREE.WebGLRenderTarget(width, height, { depthBuffer: true });
      colorTarget.texture.colorSpace = THREE.NoColorSpace;
      maskTarget = new THREE.WebGLRenderTarget(maskWidth, maskHeight, { depthBuffer: true });
      maskTarget.texture.colorSpace = THREE.NoColorSpace;
      maskTarget.texture.minFilter = THREE.NearestFilter;
      maskTarget.texture.magFilter = THREE.NearestFilter;
    }
    return {width, height, maskWidth, maskHeight};
  }
  function ensureShaders() {
    if (quadMaterial) return;
    maskMaterial = new THREE.MeshBasicMaterial({color: 0xffffff, side: THREE.DoubleSide, toneMapped: false});
    quadScene = new THREE.Scene();
    quadCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    quadMaterial = new THREE.ShaderMaterial({
      toneMapped: false, depthTest: false, depthWrite: false,
      uniforms: {
        image: {value: null}, silhouette: {value: null},
        resolution: {value: new THREE.Vector2(1, 1)},
        maskTexel: {value: new THREE.Vector2(1, 1)},
        blockSize: {value: 24}, alreadySrgb: {value: 0}, exposure: {value: 1.1},
      },
      vertexShader: `varying vec2 vUv; void main() {vUv=uv; gl_Position=vec4(position.xy,0.0,1.0);}`,
      fragmentShader: `
        uniform sampler2D image; uniform sampler2D silhouette;
        uniform vec2 resolution; uniform vec2 maskTexel;
        uniform float blockSize; uniform float alreadySrgb; uniform float exposure;
        varying vec2 vUv;
        vec3 encodeSrgb(vec3 v) {
          vec3 lo = v * 12.92;
          vec3 hi = pow(max(v, vec3(0.0)),vec3(0.41666))*1.055-vec3(0.055);
          return mix(hi, lo, vec3(lessThanEqual(v,vec3(0.0031308))));
        }
        vec3 rrtOdt(vec3 v) {
          vec3 a=v*(v+0.0245786)-0.000090537;
          vec3 b=v*(0.983729*v+0.4329510)+0.238081;
          return a/b;
        }
        vec3 toDisplay(vec3 c) {
          if(alreadySrgb>0.5) return c;
          const mat3 mIn=mat3(vec3(0.59719,0.07600,0.02840),vec3(0.35458,0.90834,0.13383),vec3(0.04823,0.01566,0.83777));
          const mat3 mOut=mat3(vec3(1.60475,-0.10208,-0.00327),vec3(-0.53108,1.10813,-0.07276),vec3(-0.07367,-0.00605,1.07602));
          return encodeSrgb(clamp(mOut*rrtOdt(mIn*(c*exposure/0.6)),0.0,1.0));
        }
        void main() {
          // Include neighboring mask texels so a moving silhouette never leaves
          // unprotected 1-pixel strips at downsampled-mask boundaries.
          float m=0.0;
          for(int y=-1;y<=1;y++) for(int x=-1;x<=1;x++) {
            m=max(m,texture2D(silhouette,clamp(vUv+vec2(float(x),float(y))*maskTexel,0.0,1.0)).r);
          }
          vec2 tileUv=(floor(vUv*resolution/blockSize)+0.5)*blockSize/resolution;
          vec3 c=texture2D(image, m>0.10 ? clamp(tileUv,0.0,1.0) : vUv).rgb;
          gl_FragColor=vec4(toDisplay(c),1.0);
        }
      `,
    });
    quadGeometry = new THREE.PlaneGeometry(2, 2);
    quadScene.add(new THREE.Mesh(quadGeometry,quadMaterial));
  }
  function drawMask(mode) {
    // Always restore the complete viewer state, including after an exception.
    const oldBackground = scene.background;
    const oldOverride = scene.overrideMaterial;
    const oldFloor = options.floor.visible;
    const oldCatcher = options.contactShadowCatcher.visible;
    const oldTarget = renderer.getRenderTarget();
    const oldShadowEnabled = renderer.shadowMap.enabled;
    try {
      options.setVariantVisibility(mode);
      options.floor.visible = false;
      options.contactShadowCatcher.visible = false;
      scene.background = maskBlack;
      scene.overrideMaterial = maskMaterial;
      // Silhouette needs depth, not a duplicate shadow-map pass.
      renderer.shadowMap.enabled = false;
      renderer.setRenderTarget(maskTarget);
      maskTarget.viewport.set(0,0,maskTarget.width,maskTarget.height);
      maskTarget.scissor.set(0,0,maskTarget.width,maskTarget.height);
      maskTarget.scissorTest=false;
      renderer.clear(true,true,true);
      renderer.render(scene,camera);
    } finally {
      scene.overrideMaterial = oldOverride;
      renderer.shadowMap.enabled = oldShadowEnabled;
      scene.background = oldBackground;
      options.floor.visible = oldFloor;
      options.contactShadowCatcher.visible = oldCatcher;
      options.setVariantVisibility(null);
      renderer.setRenderTarget(oldTarget);
    }
  }
  function render(timestamp, mode, pixelSize, renderColor, colorIsSrgb) {
    if (!options.hasVehicle()) throw new Error('No vehicle geometry for demo privacy mask');
    const {width,height,maskWidth,maskHeight}=ensureTargets();
    ensureShaders();
    // An unchanged full-resolution scene is rendered offscreen; the private
    // vehicle pixels are shown only through the protected final compositor.
    const finalAa = renderColor(timestamp, colorTarget);
    drawMask(mode);
    quadMaterial.uniforms.image.value=colorTarget.texture;
    quadMaterial.uniforms.silhouette.value=maskTarget.texture;
    quadMaterial.uniforms.resolution.value.set(width,height);
    quadMaterial.uniforms.maskTexel.value.set(1/maskWidth,1/maskHeight);
    quadMaterial.uniforms.blockSize.value=normalizedDemoStrength(pixelSize);
    quadMaterial.uniforms.alreadySrgb.value=(typeof finalAa === "boolean" ? finalAa : colorIsSrgb) ? 1 : 0;
    quadMaterial.uniforms.exposure.value=renderer.toneMappingExposure;
    renderer.setRenderTarget(null);
    renderer.setScissorTest(false);
    renderer.setViewport(0,0,renderer.getSize(new THREE.Vector2()).x,renderer.getSize(new THREE.Vector2()).y);
    renderer.render(quadScene,quadCamera);
  }
  function dispose() {
    disposeTargets(); maskMaterial?.dispose(); quadMaterial?.dispose(); quadGeometry?.dispose();
    maskMaterial=null; quadMaterial=null;quadGeometry=null;quadScene=null;quadCamera=null;
  }
  return {render,dispose};
}
