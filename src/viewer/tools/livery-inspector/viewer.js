import * as THREE from 'three';
import {requireVerifiedWheelSource} from './source-wheel-identity-gate.mjs';
import {sourceNeutralMaterialRole, sourceMirrorHousingPaintStandardGate,
  sourceMirrorFactoryStandardEligible, sourceMirrorOriginalMaterialRetentionAllowed,
  sourceOriginalAccessoryStandardGate,
  sourceOriginalNonPaintTrimGuard} from './source-neutral-material-role.mjs';
import {sourceOriginalResearchLiverySides, sourceOriginalResearchMeshRole} from './source-original-livery-permission.mjs';
import {auditOriginalDxilTwoTextures, createDxilVsPsResearchMaterial, FEOW_ORIGINAL} from './source_tire_dxil_text.mjs';
import {shouldAutoApplySignedFeow} from './source_tire_feow_default.mjs';
import {sourceTireNormalCountGate} from './source-tire-normal-count-gate.mjs';
import {wheelTireInspectionRequest, wheelTireInspectionKeep, isolateFinalWheelTireScene}
  from './wheel-tire-final-scene-isolation.mjs';
import {sourceBoundWheelPaintRoute} from './wheel-material-source-router.mjs';
import {sourceWheelFinishEvidence, wheelFinishDecision} from './wheel-finish-source-gate.mjs';
import {sourceWheelPrimaryPaintStandard, sourceWheelStandardAutoEligible, sourceWheelFinishHasExactMeshRoute} from './wheel-paint-source-color.mjs';
import {validateSourceMeshFinishEvidence, sourceMeshFinishForPaintMesh, sourceFinishTrialColor}
  from './source-mesh-finish.mjs';
import {researchSourceFinishCandidate, researchSourceFinishFlakeInput} from './source-finish-pbr.mjs';
import {sourceWheelGenericPrimaryStandardRoute} from './wheel-lip-fallback.mjs';
import {summarizeWheelPaintStandardDraw} from './wheel-paint-draw-audit.mjs';
import {reconcileLoadedSourceWheelMaterials, isVerifiedSourceWheelMap, retainVerifiedSourceWheelMap, signedWheelSceneReconciled} from './source-wheel-glb-material-reconcile.mjs';
import {sourceWheelUvAttributeName} from './source-wheel-uv-channel.mjs';
import {frameBufferImage, downloadImage, withReferenceCaptureResolution, captureFilename} from './rm_capture.mjs';
import {evaluateReleaseSceneCapture} from './release-scene-capture-audit.mjs';
import {saveCaptureImage} from './native-image-save.mjs';
import {appendCaptureCaption, formatCaptureTime} from './capture-caption.mjs';
import {composeSixCarViews, SIX_CAR_VIEWS} from './six-view-capture.mjs';
import {frameVisibleCar, horizontalOverheadCameraUp} from './camera-frame-fit.mjs';
import {THUMBNAIL_CAMERA_PRESET_ID, THUMBNAIL_CAMERA_DIRECTION, thumbnailCameraDirection}
  from './thumbnail-camera-preset.mjs';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import {inspectReceivedSourceWheelGlb} from './source-wheel-glb-browser-preflight.mjs';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { applyTranslations, getLanguage, setLanguage, t } from './i18n.js';
import { buildProductionGpuPaintAtlas } from './gpu-livery-production.js';
import { probeWebgl2Rgba8RenderTarget } from './gpu-livery-capability-probe.mjs';
import { createFirstFrameWebglProfiler, createFirstFrameRenderPassProfiler } from './webgl-first-frame-profile.js';
import {measureLosslessAtlasPng} from './gpu-atlas-png-size-probe.js';
import {measureSyntheticOpfsIo} from './gpu-atlas-synthetic-opfs-probe.js';
import {measureSparseAtlasTiles} from './gpu-atlas-sparse-tile-probe.js';
import {createDemoVehicleMosaic, normalizedDemoStrength, maskedDemoText} from './demo-privacy.js';

const atlasPngProbeRequested = new URLSearchParams(window.location.search).get('atlas-capacity-probe') === 'png-lossless';
let atlasPngProbeCanvas = null;
let atlasPngProbeStarted = false;
let atlasPngProbeFinished = !atlasPngProbeRequested;

const SECTION_COUNT = 11;
const RENDER_CONTRACT_FORMAT = 'lo4fh6_section_render_contract_v3';
const ALL_BODY_SIDES = 0x1f;
const ALL_GLASS_SIDES = 0x7c0;
const SLOT_GEOMETRY_SIDES = [0, 1, 2, 4, 3, 5, 6, 7, 8, 10, 9];
const canvas = document.querySelector('#canvas');
const viewport = document.querySelector('#viewport');
const status = document.querySelector('#status');
const renderErrorWarning = document.querySelector('#lo4fh6-render-error-warning');
const recoverableShaderContinueToggle = document.querySelector('#recoverable-shader-error-continue');
const gpuPaintInfo = document.querySelector('#gpu-paint-info');
const title = document.querySelector('#title');
const demoHideTitle = document.querySelector('#demo-hide-title');
const demoHideSource = document.querySelector('#demo-hide-source');
const demoMosaicBody = document.querySelector('#demo-mosaic-body');
const demoMosaicStrength = document.querySelector('#demo-mosaic-strength');

const vehicle = document.querySelector('#vehicle');
const assemblyInfo = document.querySelector('#assembly-info');
const renderInfo = document.querySelector('#render-info');
const compareInfo = document.querySelector('#compare-info');
const finishInfo = document.querySelector('#finish-info');
const layerInfo = document.querySelector('#layer-info');
const resetButton = document.querySelector('#reset');
const rotateButton = document.querySelector('#rotate');
const captureJpegButton = document.querySelector('#rm-capture-jpeg');
const capturePngButton = document.querySelector('#rm-capture-png');
const sixViewsJpegButton = document.querySelector('#rm-six-views-jpeg');
const sixViewsPngButton = document.querySelector('#rm-six-views-png');
let rmCaptureFormat = null;
let rmCaptureBusy = false;
const wheelsCheckbox = document.querySelector('#wheels');
const displayPresetSelect = document.querySelector('#display-preset');
const materialModeSelect = document.querySelector('#material-mode');
const compareModeSelect = document.querySelector('#compare-mode');
const compareSplitControl = document.querySelector('#compare-split-control');
const compareSplitInput = document.querySelector('#compare-split');
const compareSplitOutput = document.querySelector('#compare-split-output');
const differenceGainControl = document.querySelector('#difference-gain-control');
const differenceGainInput = document.querySelector('#difference-gain');
const differenceGainOutput = document.querySelector('#difference-gain-output');
const glassModeSelect = document.querySelector('#glass-mode');
const environmentModeSelect = document.querySelector('#environment-mode');
const reflectionAngleControl = document.querySelector('#reflection-angle-control');
const reflectionAngleInput = document.querySelector('#reflection-angle');
const reflectionAngleOutput = document.querySelector('#reflection-angle-output');
const reflectionStrengthControl = document.querySelector('#reflection-strength-control');
const reflectionStrengthInput = document.querySelector('#reflection-strength');
const reflectionStrengthOutput = document.querySelector('#reflection-strength-output');
const renderQualitySelect = document.querySelector('#render-quality');
const aaModeSelect = document.querySelector('#aa-mode');
const languageSelect = document.querySelector('#language');
const bodyKitControl = document.querySelector('#body-kit-control');
const bodyKitSelect = document.querySelector('#body-kit');
const partOptionControls = document.querySelector('#part-option-controls');
const sectionFilterSelect = document.querySelector('#section-filter');
const viewButtons = [...document.querySelectorAll('[data-view]')];
const viewerParams = new URLSearchParams(window.location.search);
// 開発用撮影時のみ同一Viewer完成材質処理後のWheel/Tireへ可視対象を制限。
const wheelTireInspectionScope = wheelTireInspectionRequest(viewerParams);
// 明示した研究受入URLだけで4K実フレームと原本Wheel全提出を評価。通常保存は不変。
const releaseSceneCaptureAuditRequested = viewerParams.get('release-scene-capture-audit') === '1';
const releaseRequireGlass = viewerParams.get('release-scene-require-glass') === '1';
let gpuOnlyPaintCompleted = false;
// 元GLB SHAとCarbin→YRVL材質Hashを検証して標準CarPaintへ色を接続。
let sourceMeshFinishVerifiedGroups = null;
// Windows受入済みの原本材質と追加Grade中立化は単一の標準処理。
// Gitブランチが唯一の機能隔離境界であり、URLによるOFF/研究分岐を置かない。
const sourceNeutralResearch = true;
const sourceLiveryNeutralResearch = true;
// 旧r485 FrontSide比較。透明ガラス二重描画の仮説をA/Bする研究URLだけ有効。
// 原本二画像・ModelBin/MatI署名が揃ったタイヤに限り自動適用。利用者ON/OFFは不要。
const sourceTireDxilProvenanceMode = 'signed-original-material-auto';
// ビルド識別はURLのリビジョン推測に頼らず実ソースに固定する。
// 研究ON指定と、sidewall 4輪への実際の材質割当は区別して画面へ記録。
// 署名済みHTMLの代替値を表示用Build識別情報の単一正本とする。
// 以前のviewer.jsは新0659版HTMLの識別値を旧2352へ上書きしていた。
// 表示用Build文字列と診断APIの内容を一致させる。
const lo4fh6BuildLabel = document.querySelector('#lo4fh6-build-label');
const visibleBuildLabel = lo4fh6BuildLabel?.textContent?.trim() || '版: 未指定';
const lo4fh6BuildId = {
  revision:'rM054442', baseBuild:'FEOW-DXIL 20261106-2006-JST',
  buildLabel:visibleBuildLabel,
  researchRequested:false,
  sidewallMaterialsApplied:0,
  xboxApproved:false,
};
window.__lo4fh6BuildId = lo4fh6BuildId;
const lo4fh6ModeLabel = document.querySelector('#lo4fh6-mode-label');
if (lo4fh6ModeLabel) {
  lo4fh6ModeLabel.textContent = '描画モード: 原本材質に応じてタイヤ側面文字を自動判定';
}

// 原本Wheel仕上げ・Mirror/Accessoryは元SHA/MatIなどで標準自動判定する。
// 追加ランタイム研究URLによる未承認材質の切替は置かない。
const ASSET_ROUTING_MODES = ['asset_routing', 'asset_routing_r175_baseline', 'carbon_detail_uv0_probe', 'carbon_detail_uv1_probe', 'carbon_detail_texture_uv0_probe', 'carbon_detail_texture_uv1_probe', 'carbon_mask_texture_uv0_probe', 'carbon_mask_texture_uv1_probe', 'asset_routing_roughness', 'asset_routing_roughness_032', 'asset_routing_roughness_036', 'asset_routing_clearcoat', 'asset_routing_ibl'];
const MATERIAL_MODES = ['physical', ...ASSET_ROUTING_MODES, 'base_paint_direct', 'base_paint_mask', 'reflection_only', 'reflection_boost', 'basic', 'diagnostic', 'decal_alpha', 'decal_luma'];
const DISPLAY_PRESETS = {
  fast: {
    materialMode: 'asset_routing', compareMode: 'off', glassMode: 'game', environmentMode: 'home_soft',
    reflectionAngle: 0, reflectionStrength: 1.35, renderQuality: 'minimum', aaMode: 'off',
  },
  standard: {
    materialMode: 'asset_routing', compareMode: 'off', glassMode: 'game', environmentMode: 'home_soft',
    reflectionAngle: 0, reflectionStrength: 1.35, renderQuality: 'standard', aaMode: 'soft',
  },
  high: {
    materialMode: 'asset_routing', compareMode: 'off', glassMode: 'game', environmentMode: 'home_soft',
    reflectionAngle: 0, reflectionStrength: 1.35, renderQuality: 'high', aaMode: 'standard',
  },
  ultra: {
    materialMode: 'asset_routing', compareMode: 'off', glassMode: 'game', environmentMode: 'home_soft',
    reflectionAngle: 0, reflectionStrength: 1.35, renderQuality: 'reference', aaMode: 'strong',
  },
};
const requestedMaterialMode = viewerParams.get('material');
let materialMode = MATERIAL_MODES.includes(requestedMaterialMode)
  ? requestedMaterialMode
  : 'asset_routing';
const requestedGlassMode = viewerParams.get('glass');
let glassMode = ['game', 'flat', 'off'].includes(requestedGlassMode)
  ? requestedGlassMode
  : 'game';
const requestedEnvironmentMode = viewerParams.get('environment');
let environmentMode = ['home_soft', 'studio', 'bands', 'sweep', 'reference'].includes(requestedEnvironmentMode)
  ? requestedEnvironmentMode
  : 'home_soft';
const requestedReflectionAngle = Number(viewerParams.get('reflection-angle'));
let reflectionAngle = Number.isFinite(requestedReflectionAngle)
  ? THREE.MathUtils.clamp(requestedReflectionAngle, -90, 90)
  : 0;
function defaultReflectionStrengthForEnvironment(mode) {
  return mode === 'home_soft' ? 1.35 : 1.0;
}
let reflectionStrengthExplicit = viewerParams.has('reflection-strength');
const requestedReflectionStrength = reflectionStrengthExplicit
  ? Number(viewerParams.get('reflection-strength'))
  : Number.NaN;
let reflectionStrength = Number.isFinite(requestedReflectionStrength)
  ? THREE.MathUtils.clamp(requestedReflectionStrength, 0.5, 2.5)
  : defaultReflectionStrengthForEnvironment(environmentMode);
const requestedRenderQuality = viewerParams.get('render-quality');
let renderQuality = ['reference', 'high', 'standard', 'minimum'].includes(requestedRenderQuality)
  ? requestedRenderQuality
  : 'reference';
const requestedAAMode = viewerParams.get('aa');
let aaMode = ['off', 'soft', 'standard', 'strong', 'very_strong'].includes(requestedAAMode)
  ? requestedAAMode
  : 'off';
const requestedCompareMode = viewerParams.get('compare');
let compareMode = ['off', 'split', 'difference', 'heatmap', 'flicker'].includes(requestedCompareMode)
  ? requestedCompareMode
  : 'off';
let compareSplit = 50;
let differenceGain = 6;
const requestedDisplayPreset = viewerParams.get('preset');
let displayPreset = requestedDisplayPreset && DISPLAY_PRESETS[requestedDisplayPreset]
  ? requestedDisplayPreset
  : 'custom';
function displayPresetMatchesCurrent(name) {
  const profile = DISPLAY_PRESETS[name];
  if (!profile) return name === 'custom';
  return materialMode === profile.materialMode
    && compareMode === profile.compareMode
    && glassMode === profile.glassMode
    && environmentMode === profile.environmentMode
    && Math.abs(reflectionAngle - profile.reflectionAngle) < 0.001
    && Math.abs(reflectionStrength - profile.reflectionStrength) < 0.001
    && renderQuality === profile.renderQuality
    && aaMode === profile.aaMode;
}
if (displayPreset !== 'custom' && !displayPresetMatchesCurrent(displayPreset)) displayPreset = 'custom';
let lastRenderableMaterialMode = 'asset_routing';
let pendingReloadState = null;
try {
  const stored = window.sessionStorage.getItem('lo4fh6-viewer-reload-state-v1');
  if (stored) pendingReloadState = JSON.parse(stored);
  window.sessionStorage.removeItem('lo4fh6-viewer-reload-state-v1');
} catch (_error) {
  pendingReloadState = null;
}
let wheelsVisible = new URLSearchParams(window.location.search).get('wheels') !== '0';
const requestedWheelSource = String(viewerParams.get('wheel-source') || 'source-verified').toLowerCase();
// GameDB が無い（ブリッジが ?gamedb=missing を付ける）：車輪は簡易表示、ゲームのロゴのステッカーは省いてある。
const gamedbMissing = viewerParams.get('gamedb') === 'missing';
const requestedBodyKitPartId = Number(viewerParams.get('body-kit'));
// 部品の選択肢（?parts=FrontBumper:365001,Hood:365002）。選ぶとページを読み直し、組み立ての前に加える。
const requestedPartOptions = parsePartOptionsParam(viewerParams.get('parts'));
let partOptionCatalog = [];
let activePartOptions = new Map();
// 読み込んで元のモデルに加えた重ね合わせ（'種類:番号'）。切り替えのたびに読み直さない。
const loadedPartOptionKeys = new Set();
let partOptionSwitching = false;
if (!['proxy', 'stock', 'game-fit', 'source-verified'].includes(requestedWheelSource)) throw new Error(`未対応の車輪表示方式: ${requestedWheelSource}`);
const wheelSource = requestedWheelSource;
// 確認済み原本材質は通常入口で自動適用。車輪はsource-verifiedかつ厳密な元SHA一致のみ。
// ミラー・アンテナ・非塗装Trimは元MatI/ModelBinの既存署名ゲートで車種共通に判定。
const sourceWheelStandardAutoEnabled = wheelSource === 'source-verified' && sourceNeutralResearch;
const sourceAccessoryStandardAutoEnabled = sourceNeutralResearch;
// 原本Wheel材質の三段階を照合。ファイル名・SHA・Texture画像を外部へ送らない。
// 研究用source-verifiedのみに限定し、描画順/Shader/Blend/形状は変更しない。
const SOURCE_WHEEL_MATERIAL_ORIGIN = 'fh6-local-original-modelbin-materialbin-shaderbin-texture2d-v1';
const sourceWheelMaterialAudit = { glb:0, declared:null, variants:new Map(), delivered:false };
let receivedWheelGlbAudit = null;
// 同じ車の次のペイントへの差し替えでは、前に受け取った車の GLB のデータ（lastMeshBuffer）をそのまま使い回す
// （GLTFLoader は受け取ったデータを変えない）。同じデータから求める物（SHA-256・ホイールの調べ）は、データごとに
// 1 回だけ求める（2026-11-20。差し替えのたびに約 35 ms 求め直していた）。データの大きさが変わっていれば
// （手放された ArrayBuffer など）求め直す。求めるのに失敗したときは覚えない（次も以前と同じく求め直す）。
const meshBufferFacts = new WeakMap();
function meshBufferFact(buffer, name, compute) {
  let facts = meshBufferFacts.get(buffer);
  if (!facts || facts.byteLength !== buffer.byteLength) {
    facts = {byteLength: buffer.byteLength, values: new Map()};
    meshBufferFacts.set(buffer, facts);
  }
  if (!facts.values.has(name)) facts.values.set(name, compute());
  return facts.values.get(name);
}
function meshBufferSha256(buffer) {
  const forget = error => {
    meshBufferFacts.get(buffer)?.values.delete('sha256');
    throw error;
  };
  return meshBufferFact(buffer, 'sha256', () => crypto.subtle.digest('SHA-256', buffer)
    .then(digest => [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, '0')).join(''))
    .catch(forget));
}
// GLTFLoaderで生成されたTHREE材質とは別に、GLB JSONが主張する原本材質を監査する。
// 生成GLBに署名済み材質が存在するのに描画側が0件なら、その不一致を隠さない。
// 新しい第一者GLBは独立したメタデータ名を永続化する。
// 受入済みFEOW・Glass・BodyKit・Wheel処理を変更しないため、
// GLTFLoader後・描画前処理前にメモリ内だけで互換別名を付ける。
function adaptFirstpartyChassisMetadata(gltf) {
  const scenes = gltf?.parser?.json?.scenes || [];
  if (!scenes.some(scene => scene?.extras?.lo4fh6_format === 'lo4fh6_source_chassis_scene_v1')) return gltf;
  const names = new Set(['role', 'source_entry', 'source_mesh_name', 'material_name',
    'part_type', 'instance_identity', 'stock_part', 'part_option_ids', 'draw_groups',
    'allowed_sides', 'projection_sides', 'material_binding_hash', 'part_options',
    'base_visible', 'source_wheel_name', 'game_fit', 'body_kit_overlay']);
  const expose = values => {
    if (!values || typeof values !== 'object') return;
    for (const [key, value] of Object.entries(values)) {
      if (!key.startsWith('lo4fh6_')) continue;
      const suffix = key.slice(7);
      if (!names.has(suffix) && !suffix.startsWith('wheel_') && !suffix.startsWith('tire_')) continue;
      const prior = 'lo4_' + suffix;
      if (Object.prototype.hasOwnProperty.call(values, prior)
          && JSON.stringify(values[prior]) !== JSON.stringify(value)) {
        throw new Error('Conflicting first-party GLB metadata: ' + suffix);
      }
      values[prior] = value;
    }
  };
  gltf?.scene?.traverse?.(node => { expose(node.userData); expose(node.geometry?.userData); });
  expose(gltf?.scene?.userData);
  return gltf;
}

// 同じ車の差し替えで、車体の GLB を解析し直さない（2026-11-20、FH6 に近づける案 ③）。最初に解析した場面は
// 描かずに持ち（形・画像・材質はページに残す）、読み込みのたびに場面の写しを作る。写しは形と画像を共有し、
// 材質だけを写す（同じ材質を共有していた部品どうしは、写しでも 1 つの材質を共有する）。読み込みの処理は
// 写しの材質を差し替える・部品を外すので、持っている場面は変わらない。GLB のデータが変われば解析し直す。
let pristineMeshGltf = null;

function cloneMeshGltf(gltf) {
  const scene = SkeletonUtils.clone(gltf.scene);
  // 原本の照合（ホイールの材質など）は、場面の部品・材質から GLB の番号を parser.associations で引く。写しの部品と
  // 材質にも元の対応を付けた表を作り、元の parser を土台にした parser に持たせる（元の表は変えない）。
  const parser = gltf.parser;
  const associations = new Map(parser?.associations || []);
  const pairObjects = (source, copy) => {
    const association = parser?.associations?.get(source);
    if (association) associations.set(copy, association);
    for (let index = 0; index < source.children.length; index++) {
      pairObjects(source.children[index], copy.children[index]);
    }
  };
  pairObjects(gltf.scene, scene);
  const materials = new Map();
  const cloneMaterial = material => {
    if (!material?.isMaterial) return material;
    if (!materials.has(material)) {
      const copy = material.clone();
      const association = parser?.associations?.get(material);
      if (association) associations.set(copy, association);
      materials.set(material, copy);
    }
    return materials.get(material);
  };
  scene.traverse(node => {
    if (!node.material) return;
    node.material = Array.isArray(node.material) ? node.material.map(cloneMaterial) : cloneMaterial(node.material);
  });
  const clonedParser = parser ? Object.create(parser, {associations: {value: associations}}) : parser;
  return {...gltf, scene, scenes: [scene], parser: clonedParser};
}

function parsedMeshGltf(buffer) {
  if (pristineMeshGltf?.buffer === buffer) return Promise.resolve(cloneMeshGltf(pristineMeshGltf.gltf));
  return new GLTFLoader().parseAsync(buffer, '').then(adaptFirstpartyChassisMetadata).then(gltf => {
    pristineMeshGltf = {buffer, gltf};
    return cloneMeshGltf(gltf);
  });
}

function sourceWheelDeclaredMaterialClaims(gltf) {
  const document = gltf?.parser?.json || {};
  const materials = Array.isArray(document.materials) ? document.materials : [];
  const meshes = Array.isArray(document.meshes) ? document.meshes : [];
  const signedMaterialIds = new Set();
  for (let i = 0; i < materials.length; i++) {
    if (materials[i]?.extras?.lo4fh6_original_source_wheel_texture === SOURCE_WHEEL_MATERIAL_ORIGIN) {
      signedMaterialIds.add(i);
    }
  }
  let signedWheelPrimitives = 0;
  for (const mesh of meshes) {
    if ((mesh?.extras?.lo4fh6_part_type ?? mesh?.extras?.lo4_part_type) !== 'WheelStyle') continue;
    for (const primitive of Array.isArray(mesh.primitives) ? mesh.primitives : []) {
      if (Number.isInteger(primitive?.material) && signedMaterialIds.has(primitive.material)) {
        signedWheelPrimitives++;
      }
    }
  }
  return { signedMaterials:signedMaterialIds.size, signedWheelPrimitives,
    sourceOnly:true, gltfLoaderMaterialVerified:false, pixelParityApproved:false };
}

function verifiedSourceWheelMap(mesh) {
  return isVerifiedSourceWheelMap(mesh);
}
function countVerifiedSourceWheelMaps(root) {
  let found=0;
  root?.traverse?.(mesh => { if (verifiedSourceWheelMap(mesh)) found++; });
  return found;
}

// 差し替え（swapPaint）で URL が変わったときに読み直せるように、読む部分を関数にしている。
function parseRequestedPartSelection() {
  const raw = viewerParams.get('part-selection');
  if (!raw) return new Map();
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return new Map();
    return new Map(Object.entries(parsed)
      .map(([partType, value]) => [String(partType), Number(value)])
      .filter(([partType, value]) => partType && Number.isInteger(value)));
  } catch (_error) {
    return new Map();
  }
}
let requestedPartSelection = parseRequestedPartSelection();
let inspectionWheels = null;
wheelsCheckbox.checked = wheelsVisible;
displayPresetSelect.value = displayPreset;
materialModeSelect.value = materialMode;
glassModeSelect.value = glassMode;
environmentModeSelect.value = environmentMode;
reflectionAngleInput.value = String(reflectionAngle);
reflectionAngleOutput.value = `${Math.round(reflectionAngle)}°`;
reflectionAngleControl.classList.toggle('hidden', !['sweep', 'reference'].includes(environmentMode));
reflectionStrengthInput.value = String(reflectionStrength);
reflectionStrengthOutput.value = `${reflectionStrength.toFixed(2)}×`;
renderQualitySelect.value = renderQuality;
aaModeSelect.value = aaMode;
compareModeSelect.value = compareMode;
compareSplitInput.value = String(compareSplit);
compareSplitOutput.value = `${Math.round(compareSplit)}%`;
differenceGainInput.value = String(differenceGain);
differenceGainOutput.value = `${differenceGain.toFixed(differenceGain % 1 === 0 ? 0 : 1)}×`;
languageSelect.value = getLanguage();
applyTranslations(document);
const partControls = document.querySelector('#parts');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(1);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = environmentMode === 'home_soft' ? 1.10 : 1.12;
// r202：表示専用の接地影。透過Shadow Catcherを明示的に使用し、
// 床材の材質を変更せず、参照ツールの影計算式との同等性も主張せずに
// 接地影の濃さだけを制御する。
const groundShadowRequested = viewerParams.get('ground-shadow') !== '0';
const requestedGroundShadowStrength = viewerParams.has('ground-shadow-strength')
  ? Number(viewerParams.get('ground-shadow-strength'))
  : Number.NaN;
const groundShadowStrength = Number.isFinite(requestedGroundShadowStrength)
  ? THREE.MathUtils.clamp(requestedGroundShadowStrength, 0.0, 0.65)
  : 0.28;
renderer.shadowMap.enabled = groundShadowRequested;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const gl = renderer.getContext();
// ShaderはThree.jsの厳密な通常検証を維持し、URLで検証を遅延・並列化しない。
const debugRenderer = gl.getExtension('WEBGL_debug_renderer_info');

let gpuLiveryCapabilityReported = false;
let gpuLiveryCapabilityReportInFlight = false;

async function reportGpuLiveryRuntimeCapability() {
  if (gpuLiveryCapabilityReported || gpuLiveryCapabilityReportInFlight) return gpuLiveryCapabilityReported;
  const nativeApi = window.pywebview?.api;
  if (!nativeApi?.report_gpu_livery_capability) return false;
  gpuLiveryCapabilityReportInFlight = true;
  const webgl2 = typeof WebGL2RenderingContext !== 'undefined' && gl instanceof WebGL2RenderingContext;
  // Three.js所有GLの状態を同期復元してからpywebviewの非同期APIを呼ぶ。
  // 旧実装は4x4プローブFBOをawaitの間バインドしたままにしていた。
  const probe = webgl2 ? probeWebgl2Rgba8RenderTarget(gl) : {
    webgl2: false, offscreen_framebuffer: false, rgba8_render_target: false,
    probe_reason: 'no_webgl2', framebuffer_status: null, gl_error: null, context_lost: false,
  };
  try {
    const result = await nativeApi.report_gpu_livery_capability({
      captured_unix: Date.now() / 1000,
      webgl2,
      offscreen_framebuffer: probe.offscreen_framebuffer,
      rgba8_render_target: probe.rgba8_render_target,
      probe: {
        reason: probe.probe_reason,
        framebuffer_status: probe.framebuffer_status,
        gl_error: probe.gl_error,
        context_lost: probe.context_lost,
      },
      limits: {
        max_texture_size: Number(gl.getParameter(gl.MAX_TEXTURE_SIZE) || 0),
        max_renderbuffer_size: Number(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) || 0),
        max_texture_image_units: Number(gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS) || 0),
      },
    });
    // プローブ一時失敗を成功として固定せず、既存の短時間再試行を生かす。
    gpuLiveryCapabilityReported = Boolean(result?.ok && probe.rgba8_render_target);
    return gpuLiveryCapabilityReported;
  } catch (error) {
    viewerEvent('gpu-livery-capability-report-failed', error?.message || String(error));
    return false;
  } finally {
    gpuLiveryCapabilityReportInFlight = false;
  }
}

async function reportGpuLiveryProductionAdapter(result) {
  const nativeApi = window.pywebview?.api;
  if (!nativeApi?.report_gpu_livery_adapter_result) return false;
  try {
    const response = await nativeApi.report_gpu_livery_adapter_result({
      used_gpu: Boolean(result?.usedGpu),
      reason: String(result?.reason || ''),
      rejected_sections: Array.isArray(result?.rejectedSections) ? result.rejectedSections : [],
      gpu_section_count: Number(result?.gpuSectionCount || 0),
      sections: Array.isArray(result?.sections) ? result.sections : [],
    });
    return Boolean(response?.ok);
  } catch (error) {
    viewerEvent('gpu-livery-production-report-failed', error?.message || String(error));
    return false;
  }
}

function installGpuLiveryRuntimeCapabilityHandshake() {
  const tryReport = () => { void reportGpuLiveryRuntimeCapability(); };
  // pywebviewによるwindow.pywebview.apiの注入は非同期で行われる。
  // 通常Viewerの読込が先に完了することがあるため、準備完了イベントと
  // 回数を制限した再試行の両方で報告する。
  // reportGpuLiveryRuntimeCapability()側で成功通知の重複を抑止する。
  window.addEventListener('pywebviewready', tryReport);
  document.addEventListener('pywebviewready', tryReport);
  for (const delayMs of [0, 250, 1000, 3000, 8000]) {
    window.setTimeout(tryReport, delayMs);
  }
}

function qualityProfile() {
  const deviceMemory = navigator.deviceMemory || 4;
  if (renderQuality === 'reference') {
    return {
      dprCap: 4,
      pixelBudget: deviceMemory >= 8 ? 25165824 : 12582912,
      minimumPixelBudget: deviceMemory >= 8 ? 14680064 : 8388608,
      targetWidth: 4096,
      anisotropy: renderer.capabilities.getMaxAnisotropy(),
      label: 'Reference',
      forceSupersample: true,
    };
  }
  if (renderQuality === 'high') {
    return {
      dprCap: 3,
      pixelBudget: deviceMemory >= 8 ? 12582912 : 6291456,
      anisotropy: renderer.capabilities.getMaxAnisotropy(),
      label: 'High',
      forceSupersample: false,
    };
  }
  if (renderQuality === 'minimum') {
    return {
      dprCap: 1,
      pixelBudget: 2500000,
      anisotropy: Math.min(2, renderer.capabilities.getMaxAnisotropy()),
      label: 'Minimum',
      forceSupersample: false,
    };
  }
  return {
    dprCap: 2,
    pixelBudget: deviceMemory >= 8 ? 8388608 : 4194304,
    anisotropy: Math.min(4, renderer.capabilities.getMaxAnisotropy()),
    label: 'Standard',
    forceSupersample: false,
  };
}
const graphicsDevice = {
  renderer: gl.getParameter(debugRenderer ? debugRenderer.UNMASKED_RENDERER_WEBGL : gl.RENDERER),
  vendor: gl.getParameter(debugRenderer ? debugRenderer.UNMASKED_VENDOR_WEBGL : gl.VENDOR),
  maxTextureSize: renderer.capabilities.maxTextureSize,
  maxAnisotropy: renderer.capabilities.getMaxAnisotropy(),
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x090b0e);
const camera = new THREE.PerspectiveCamera(36, 1, 0.01, 1000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.autoRotateSpeed = 0.65;

// 追跡している形・画像の出し入れを数える（資源の大きさの数え直しを、変わったときだけにするため。2026-11-21）
let trackedResourceVersion = 0;
class TrackedResourceSet extends Set {
  add(value) {
    if (!this.has(value)) trackedResourceVersion += 1;
    return super.add(value);
  }
  delete(value) {
    const removed = super.delete(value);
    if (removed) trackedResourceVersion += 1;
    return removed;
  }
  clear() {
    if (this.size) trackedResourceVersion += 1;
    super.clear();
  }
}
const trackedGeometries = new TrackedResourceSet();
const trackedMaterials = new Set();
const trackedTextures = new TrackedResourceSet();
const trackedSkeletons = new Set();
let animationFrameId = 0;
let viewerDisposed = false;
let rendererContextReleased = false;
let renderWidth = 0;
let renderHeight = 0;
let renderPixelRatio = 0;
let renderRequests = 0;
let renderedFrames = 0;
let modelBounds = null;
let cameraFrameBounds = null;
let studioEnvironmentTarget = null;
let startedAt = performance.now();  // 同じ車の次のペイントへの差し替え（swapPaint）のときは今にする
const loadAbort = new AbortController();
const viewerLoadTimeoutMs = renderQuality === 'reference' ? 90000 : 60000;
const loadTimeout = window.setTimeout(() => failViewer(t('error.timeout', {seconds: viewerLoadTimeoutMs / 1000})), viewerLoadTimeoutMs);
const timings = {};
let modelReady = false;
let firstFrameReady = false;
let frameTime = 0;
let lastFrameAt = 0;
let frameTimeTotal = 0;
let frameTimePeak = 0;
const gpuBudgetMiB = renderQuality === 'reference'
  ? Math.min(768, Math.max(256, (navigator.deviceMemory || 4) * 96))
  : renderQuality === 'minimum'
    ? Math.min(256, Math.max(160, (navigator.deviceMemory || 4) * 40))
    : Math.min(512, Math.max(192, (navigator.deviceMemory || 4) * 64));
const gpuBudgetBytes = gpuBudgetMiB * 1024 * 1024;
let modelResourceBytes = 0;

function viewerEvent(event, message = '', details = {}) {
  console.info('LO4FH6_VIEWER:' + JSON.stringify({event, message, ...details, diagnostics: viewerDiagnostics()}));
}

let latestViewerStage = 'script_loaded';
function reportViewerStage(stage, detail = '') {
  latestViewerStage = String(stage || 'unknown').slice(0, 50);
  const api = window.pywebview?.api;
  if (!api?.report_viewer_stage) return Promise.resolve(false);
  try {
    return Promise.resolve(api.report_viewer_stage({
      stage: latestViewerStage,
      elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
      detail: String(detail || '').slice(0, 240),
    })).catch(() => false);
  } catch (_error) {
    return Promise.resolve(false);
  }
}
window.addEventListener('pywebviewready', () => reportViewerStage(latestViewerStage));
document.addEventListener('pywebviewready', () => reportViewerStage(latestViewerStage));

function phase(name, message) {
  timings[name] = Math.round(performance.now() - startedAt);
  setStatus(message);
  reportViewerStage(name);
  viewerEvent('phase', message);
}

function failViewer(message) {
  if (viewerDisposed) return;
  const reason = String(message || 'Viewer startup error');
  // 元コードのdisposeViewer()はWebGLを強制Context Lostにしており、先行する
  // 実際の例外をGPU障害と誤診していた。先にエラーをWindows側に送ってから
  // Contextは強制ロスせず解放する（正常描画経路は変更しない）。
  setStatus(reason, true);
  if (renderErrorWarning) {
    renderErrorWarning.textContent = reason;
    renderErrorWarning.classList.remove('hidden');
  }
  const delivered = reportViewerStage('error', reason);
  try { viewerEvent('error', reason); } catch (_ignored) {}
  let finalized = false;
  const finish = () => {
    if (finalized) return;
    finalized = true;
    disposeViewer(false);
  };
  const timeout = window.setTimeout(finish, 900);
  Promise.resolve(delivered).finally(() => { window.clearTimeout(timeout); finish(); });
}

// 知らせの診断の資源の大きさ。追跡している形・画像と描画の大きさが前に数えたときと同じなら、数え直さない
// （差し替え 1 回で知らせは数十あり、そのたびに全部を数えていた。2026-11-21）。予算の確かめは resourceBytes を直接呼ぶ。
let resourceBytesMemo = null;
function resourceBytesForDiagnostics() {
  const key = `${trackedResourceVersion}|${viewerDisposed}|${renderWidth}|${renderHeight}|${renderPixelRatio}`;
  if (resourceBytesMemo?.key !== key) resourceBytesMemo = {key, value: resourceBytes()};
  return {...resourceBytesMemo.value};
}

function resourceBytes() {
  const buffers = new Set();
  for (const geometry of trackedGeometries) {
    for (const attribute of [...Object.values(geometry.attributes), geometry.index]) {
      const buffer = (attribute?.array || attribute?.data?.array)?.buffer;
      if (buffer) buffers.add(buffer);
    }
  }
  let geometryBytes = 0;
  buffers.forEach(buffer => { geometryBytes += buffer.byteLength; });
  let textureBytes = 0;
  trackedTextures.forEach(texture => {
    const image = texture.image;
    textureBytes += (image?.width || 0) * (image?.height || 0) * 4 * (texture.generateMipmaps ? 4 / 3 : 1);
  });
  const framebuffers = viewerDisposed ? 0 : Math.ceil(renderWidth * renderHeight * renderPixelRatio ** 2 * 40);
  return {geometry: geometryBytes, textures: Math.ceil(textureBytes), framebuffers,
    estimatedGpu: Math.ceil(geometryBytes + textureBytes + framebuffers), budget: gpuBudgetBytes};
}

function trackTexture(texture) {
  if (!texture?.isTexture) return texture;
  if (viewerDisposed) {
    texture.dispose();
    if (typeof texture.image?.close === 'function') texture.image.close();
  } else {
    trackedTextures.add(texture);
  }
  return texture;
}

function trackMaterial(material) {
  for (const item of Array.isArray(material) ? material : [material]) {
    if (!item?.isMaterial) continue;
    for (const value of Object.values(item)) trackTexture(value);
    for (const uniform of Object.values(item.uniforms || {})) {
      const value = uniform?.value;
      if (Array.isArray(value)) value.forEach(trackTexture);
      else trackTexture(value);
    }
    if (viewerDisposed) item.dispose();
    else trackedMaterials.add(item);
  }
  return material;
}

function trackObjectResources(root) {
  root?.traverse(child => {
    if (child.geometry?.isBufferGeometry) {
      if (viewerDisposed) child.geometry.dispose();
      else trackedGeometries.add(child.geometry);
    }
    trackMaterial(child.material);
    if (child.skeleton?.dispose) {
      if (viewerDisposed) child.skeleton.dispose();
      else trackedSkeletons.add(child.skeleton);
    }
  });
  return root;
}

function disposeObjectTree(root) {
  root?.traverse(child => {
    child.geometry?.dispose?.();
    for (const material of Array.isArray(child.material) ? child.material : [child.material]) {
      material?.dispose?.();
    }
  });
}

function createStudioEnvironment(mode = 'studio', sweepDegrees = 0) {
  const studio = new THREE.Scene();
  const homeSoftEnvironment = mode === 'home_soft';
  const referenceEnvironment = mode === 'reference';
  const reflectionBands = mode === 'bands' || mode === 'sweep' || referenceEnvironment;
  studio.background = new THREE.Color(homeSoftEnvironment ? 0x0b0c0e : (referenceEnvironment ? 0x020305 : (reflectionBands ? 0x05070a : 0x11171d)));
  const room = new THREE.Mesh(
    new THREE.BoxGeometry(18, 10, 24),
    new THREE.MeshBasicMaterial({
      color: homeSoftEnvironment ? 0x1b1918 : (referenceEnvironment ? 0x080a0d : (reflectionBands ? 0x101419 : 0x273038)),
      side: THREE.BackSide,
    })
  );
  studio.add(room);

  const reflectionGroup = new THREE.Group();
  reflectionGroup.rotation.y = THREE.MathUtils.degToRad((mode === 'sweep' || referenceEnvironment) ? sweepDegrees : 0);
  studio.add(reflectionGroup);

  const panel = (width, height, color, position, rotation, parent = studio) => {
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(width, height),
      new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide })
    );
    mesh.position.copy(position);
    mesh.rotation.set(rotation.x, rotation.y, rotation.z);
    parent.add(mesh);
  };

  if (homeSoftEnvironment) {
    // r98：Horizon Home／フォトモード「Soft」の近似。
    // 参照画像には広い上方・前方照明、車体とガラスに映る大きな白い枠、
    // 控えめな暖色アクセント、光沢のある床が見られる。
    // 照明カードは室内の再現ではなく、車体上の安定した反射手掛かりを
    // 再現するため、意図的に簡素な形状とする。
    panel(11.5, 4.6, 0xffffff, new THREE.Vector3(-0.6, 4.65, 0.8), new THREE.Euler(Math.PI / 2, 0.0, 0.04), reflectionGroup);
    panel(8.5, 2.4, 0xf7f5f2, new THREE.Vector3(0.1, 2.4, 7.2), new THREE.Euler(0.0, Math.PI, 0.0), reflectionGroup);
    panel(8.8, 1.1, 0xffffff, new THREE.Vector3(0.0, 3.75, -6.6), new THREE.Euler(0.0, 0.0, 0.0), reflectionGroup);
    panel(0.72, 7.8, 0xffffff, new THREE.Vector3(-6.2, 1.4, 0.8), new THREE.Euler(0.0, 1.20, 0.0), reflectionGroup);
    panel(0.68, 7.2, 0xffffff, new THREE.Vector3(6.0, 1.5, -0.4), new THREE.Euler(0.0, -1.18, 0.0), reflectionGroup);
    panel(5.8, 0.42, 0xff9a32, new THREE.Vector3(4.7, 1.1, -4.9), new THREE.Euler(0.0, -0.70, -0.06), reflectionGroup);
    panel(3.4, 0.30, 0xff7f18, new THREE.Vector3(-3.7, 0.65, -5.7), new THREE.Euler(0.0, 0.56, 0.04), reflectionGroup);
    panel(6.6, 2.8, 0xd7d5cf, new THREE.Vector3(-0.5, 1.0, -7.4), new THREE.Euler(0.0, 0.0, 0.0), reflectionGroup);
  } else if (referenceEnvironment) {
    // r48：反射確認用の環境。室内の写実性よりも、
    // 高コントラストの物体を密に配置して識別しやすくすることを重視する。
    // 広い平面のLivery上でRoughness／Clearcoatの微差を見えるようにする。
    const radius = 7.2;
    const stripColors = [0xffffff, 0xbfeeff, 0xffc4f1, 0xffe2b3];
    const stripWidths = [0.34, 0.62, 0.42, 0.88, 0.30, 0.54, 0.38, 0.74];
    for (let index = 0; index < 16; ++index) {
      const angle = (index / 16) * Math.PI * 2;
      const width = stripWidths[index % stripWidths.length];
      const height = index % 3 === 0 ? 8.6 : (index % 3 === 1 ? 6.4 : 4.8);
      const color = stripColors[index % stripColors.length];
      const x = Math.sin(angle) * radius;
      const z = Math.cos(angle) * radius;
      panel(
        width,
        height,
        color,
        new THREE.Vector3(x, index % 2 === 0 ? 1.6 : 0.6, z),
        new THREE.Euler(0.0, angle + Math.PI, 0.0),
        reflectionGroup
      );
    }
    // 天井・床の広いカードで長いハイライトを作り、
    // 小さな色付きカードで単なる白線よりも反射模様を識別しやすくする。
    panel(9.5, 0.72, 0xffffff, new THREE.Vector3(0.0, 4.6, 1.4), new THREE.Euler(Math.PI / 2, 0.0, 0.10), reflectionGroup);
    panel(6.8, 0.46, 0xbfeeff, new THREE.Vector3(-1.2, 4.3, -2.6), new THREE.Euler(Math.PI / 2, 0.0, -0.24), reflectionGroup);
    panel(5.4, 0.40, 0xffc4f1, new THREE.Vector3(1.7, -3.8, 0.4), new THREE.Euler(-Math.PI / 2, 0.0, 0.18), reflectionGroup);
    panel(3.2, 2.2, 0xffe2b3, new THREE.Vector3(-5.2, 0.4, 4.6), new THREE.Euler(0.0, 2.28, 0.0), reflectionGroup);
  } else if (reflectionBands) {
    // 高コントラストの帯状照明は意図的な人工光。
    // スイープモードでは照明一式を車体の周囲で回転させ、
    // Liveryの位置・材質を変えず文字上のClearcoat反射を移動できる。
    panel(1.0, 8.0, 0xffffff, new THREE.Vector3(-6.0, 1.0, 1.8), new THREE.Euler(0.0, 1.22, 0.0), reflectionGroup);
    panel(0.8, 8.0, 0xd8f6ff, new THREE.Vector3(-3.8, 2.0, -7.0), new THREE.Euler(0.0, 0.34, 0.0), reflectionGroup);
    panel(1.4, 8.0, 0xffffff, new THREE.Vector3(5.6, 1.7, -1.2), new THREE.Euler(0.0, -1.25, 0.0), reflectionGroup);
    panel(8.5, 0.8, 0xfff4e7, new THREE.Vector3(0.0, 4.5, 1.5), new THREE.Euler(Math.PI / 2, 0.0, 0.12), reflectionGroup);
    panel(7.0, 0.55, 0xffffff, new THREE.Vector3(1.0, 2.3, 7.5), new THREE.Euler(0.0, Math.PI, -0.08), reflectionGroup);
  } else {
    panel(6.0, 2.0, 0xffffff, new THREE.Vector3(-3.8, 3.6, 1.5), new THREE.Euler(-0.35, 1.05, 0.15));
    panel(4.5, 1.6, 0xbfeeff, new THREE.Vector3(4.5, 2.3, -3.8), new THREE.Euler(0.0, -0.72, -0.15));
    panel(5.5, 1.2, 0xffffff, new THREE.Vector3(0.0, 4.2, -1.0), new THREE.Euler(Math.PI / 2, 0.0, 0.0));
    panel(3.4, 1.0, 0xfff2dd, new THREE.Vector3(0.5, 1.1, 5.8), new THREE.Euler(0.0, Math.PI, 0.0));
  }

  const pmrem = new THREE.PMREMGenerator(renderer);
  // r278：r277で原作者の暗い金色を復元したが、Home SoftのPMREM sigmaが
  // 反射光源を広げ、Xbox参照にある細かなClearcoatハイライトを弱めていた。
  // シーンカードと照明バランスは維持し、反射プリフィルタのぼかしのみ減らす。
  const environmentSigma = homeSoftEnvironment ? 0.12 : (referenceEnvironment ? 0.012 : (reflectionBands ? 0.035 : 0.09));
  studioEnvironmentTarget = pmrem.fromScene(studio, environmentSigma, 0.1, 50);
  pmrem.dispose();
  disposeObjectTree(studio);
  scene.environment = studioEnvironmentTarget.texture;
  scene.environmentIntensity = reflectionStrength;
}

function rebuildStudioEnvironment() {
  if (studioEnvironmentTarget) {
    studioEnvironmentTarget.dispose();
    studioEnvironmentTarget = null;
  }
  scene.environment = null;
  if (materialMode !== 'diagnostic') {
    createStudioEnvironment(environmentMode, reflectionAngle);
  }
  requestRender();
}

function isAssetRoutingMode(mode) {
  return ASSET_ROUTING_MODES.includes(mode);
}

function detailNormalTextureForProfile(profile) {
  if (profile === 'carbon_detail_uv0_probe' || profile === 'carbon_detail_texture_uv0_probe') return baseDetailNormalProbeTextures.get(0) || null;
  if (profile === 'carbon_detail_uv1_probe' || profile === 'carbon_detail_texture_uv1_probe') return baseDetailNormalProbeTextures.get(1) || null;
  return baseDetailNormalTexture;
}

function detailMaskTextureForProfile(profile) {
  if (profile === 'carbon_mask_texture_uv0_probe') return baseDetailMaskProbeTextures.get(0) || null;
  if (profile === 'carbon_mask_texture_uv1_probe') return baseDetailMaskProbeTextures.get(1) || null;
  return null;
}

function isCarbonUvProbeMode(mode) {
  return [
    'carbon_detail_uv0_probe', 'carbon_detail_uv1_probe',
    'carbon_detail_texture_uv0_probe', 'carbon_detail_texture_uv1_probe',
    'carbon_mask_texture_uv0_probe', 'carbon_mask_texture_uv1_probe',
  ].includes(mode);
}

function summarizeCarbonUvAttributes(root) {
  const summary = {
    paintMeshes: 0, bothMeshes: 0, missingUv0: 0, missingUv1: 0,
    mismatchedCountMeshes: 0, vertices: 0, maxAbsDelta: 0.0, rmsDelta: 0.0,
    identical: false,
  };
  let sumSquares = 0.0;
  let componentCount = 0;
  root?.traverse(child => {
    if (!child.isMesh || meshCategory(child) !== 'paint') return;
    summary.paintMeshes += 1;
    const uv0 = child.geometry?.getAttribute('uv');
    const uv1 = child.geometry?.getAttribute('uv1');
    if (!uv0) summary.missingUv0 += 1;
    if (!uv1) summary.missingUv1 += 1;
    if (!uv0 || !uv1) return;
    summary.bothMeshes += 1;
    if (uv0.count !== uv1.count) {
      summary.mismatchedCountMeshes += 1;
      return;
    }
    summary.vertices += uv0.count;
    for (let index = 0; index < uv0.count; ++index) {
      const du = Number(uv0.getX(index)) - Number(uv1.getX(index));
      const dv = Number(uv0.getY(index)) - Number(uv1.getY(index));
      const abs = Math.max(Math.abs(du), Math.abs(dv));
      summary.maxAbsDelta = Math.max(summary.maxAbsDelta, abs);
      sumSquares += du * du + dv * dv;
      componentCount += 2;
    }
  });
  summary.rmsDelta = componentCount > 0 ? Math.sqrt(sumSquares / componentCount) : 0.0;
  summary.identical = summary.paintMeshes > 0
    && summary.bothMeshes === summary.paintMeshes
    && summary.mismatchedCountMeshes === 0
    && summary.maxAbsDelta <= 1e-6;
  return summary;
}

function carbonUvAttributeSummaryText() {
  if (!isCarbonUvProbeMode(materialMode) || !carbonUvAttributeSummary) return '';
  const value = carbonUvAttributeSummary;
  if (value.bothMeshes !== value.paintMeshes || value.mismatchedCountMeshes > 0) {
    return t('info.carbon_uv_incomplete', {both: value.bothMeshes, paint: value.paintMeshes});
  }
  const max = Number(value.maxAbsDelta).toExponential(2);
  if (value.identical) {
    return t('info.carbon_uv_identical', {vertices: value.vertices, max});
  }
  return t('info.carbon_uv_different', {
    vertices: value.vertices, max, rms: Number(value.rmsDelta).toExponential(2),
  });
}

function setCompareInfoText(text) {
  const uv = carbonUvAttributeSummaryText();
  compareInfo.textContent = uv ? `${text} · ${uv}` : text;
}

function materialResponseProbe(mode) {
  if (mode === 'asset_routing_roughness') {
    return { roughness: 0.24, clearcoatScaleHomeSoft: null, iblScale: 1.0, infoKey: 'probe.roughness' };
  }
  if (mode === 'asset_routing_roughness_032') {
    return { roughness: 0.32, clearcoatScaleHomeSoft: null, iblScale: 1.0, infoKey: 'probe.roughness_032' };
  }
  if (mode === 'asset_routing_roughness_036') {
    return { roughness: 0.36, clearcoatScaleHomeSoft: null, iblScale: 1.0, infoKey: 'probe.roughness_036' };
  }
  if (mode === 'asset_routing_clearcoat') {
    return { roughness: null, clearcoatScaleHomeSoft: 0.30, iblScale: 1.0, infoKey: 'probe.clearcoat' };
  }
  if (mode === 'asset_routing_ibl') {
    return { roughness: null, clearcoatScaleHomeSoft: null, iblScale: 1.35, infoKey: 'probe.ibl' };
  }
  return { roughness: null, clearcoatScaleHomeSoft: null, iblScale: 1.0, infoKey: null };
}

function materialLightProfileForMode(mode, environment = environmentMode) {
  if (environment === 'home_soft') {
    if (mode === 'physical' || isAssetRoutingMode(mode)) {
      return { hemi: 0.74, key: 1.52, rim: 0.22, top: 0.64, front: 0.20, warm: 0.18 };
    }
    if (mode === 'basic') {
      return { hemi: 1.32, key: 1.85, rim: 0.36, top: 0.82, front: 0.42, warm: 0.18 };
    }
    return { hemi: 1.70, key: 2.20, rim: 0.55, top: 0.95, front: 0.52, warm: 0.22 };
  }
  return (mode === 'physical' || isAssetRoutingMode(mode))
    ? { hemi: 1.25, key: 2.15, rim: 0.90, top: 0.0, front: 0.0, warm: 0.0 }
    : mode === 'basic'
      ? { hemi: 1.70, key: 2.55, rim: 1.30, top: 0.0, front: 0.0, warm: 0.0 }
      : { hemi: 2.35, key: 3.10, rim: 2.00, top: 0.0, front: 0.0, warm: 0.0 };
}

const initialLightProfile = materialLightProfileForMode(materialMode);
const hemisphereLight = new THREE.HemisphereLight(0xf2f6ff, 0x181615, initialLightProfile.hemi);
scene.add(hemisphereLight);
const keyLightOffset = new THREE.Vector3(4.5, 8, 6);
const keyLight = new THREE.DirectionalLight(0xffffff, initialLightProfile.key);
keyLight.position.copy(keyLightOffset);
scene.add(keyLight);
scene.add(keyLight.target);
const rimLight = new THREE.DirectionalLight(0xc9e8ff, initialLightProfile.rim);
rimLight.position.set(-6, 3, -5);
scene.add(rimLight);
const topFillLight = new THREE.DirectionalLight(0xf7f9ff, initialLightProfile.top);
topFillLight.position.set(0.0, 10.0, -1.5);
scene.add(topFillLight);
const frontFillLight = new THREE.DirectionalLight(0xfffbf3, initialLightProfile.front);
frontFillLight.position.set(0.0, 3.2, 8.5);
scene.add(frontFillLight);
const warmAccentLight = new THREE.DirectionalLight(0xffa24a, initialLightProfile.warm);
warmAccentLight.position.set(6.5, 2.2, -5.0);
scene.add(warmAccentLight);

function groundShadowMapSize() {
  if (renderQuality === 'minimum') return 512;
  if (renderQuality === 'standard') return 1024;
  return 2048;
}

function groundShadowEnabledForPresentation() {
  return groundShadowRequested
    && environmentMode === 'home_soft'
    && materialMode !== 'diagnostic'
    && !materialMode.startsWith('carbon_detail_texture_')
    && !materialMode.startsWith('carbon_mask_texture_')
    && materialMode !== 'decal_alpha'
    && materialMode !== 'decal_luma'
    && materialMode !== 'base_paint_mask';
}

function applyGroundShadowProfile() {
  // 完成Wheel/Tire専用撮影では床と接地影も車体外の描画対象。
  // 通常Viewerには一切影響しない限定条件で遮断する。
  const enabled = !wheelTireInspectionScope && groundShadowEnabledForPresentation();
  renderer.shadowMap.enabled = !wheelTireInspectionScope && groundShadowRequested;
  if (wheelTireInspectionScope) floor.visible = false;
  keyLight.castShadow = enabled;
  // r202：展示用の床材には固有の材質・照明応答を維持する。
  // 別のShadowMaterial受光面で安定した少し強めの接地感を与える。
  floor.receiveShadow = false;
  contactShadowCatcher.receiveShadow = enabled;
  contactShadowCatcher.visible = enabled;
  contactShadowCatcher.material.opacity = groundShadowStrength;
  if (!enabled) return;
  const size = groundShadowMapSize();
  keyLight.shadow.mapSize.set(size, size);
  keyLight.shadow.bias = -0.00018;
  keyLight.shadow.normalBias = 0.018;
  keyLight.shadow.radius = 2.2;
}

function configureGroundShadow(bounds) {
  if (!bounds || bounds.isEmpty()) return;
  const size = bounds.getSize(new THREE.Vector3());
  const center = bounds.getCenter(new THREE.Vector3());
  const horizontalExtent = Math.max(size.x, size.z, 1.0);
  const shadowExtent = horizontalExtent * 0.88;
  keyLight.position.copy(center).add(keyLightOffset);
  keyLight.target.position.copy(center);
  keyLight.target.updateMatrixWorld(true);
  keyLight.shadow.camera.left = -shadowExtent;
  keyLight.shadow.camera.right = shadowExtent;
  keyLight.shadow.camera.top = shadowExtent;
  keyLight.shadow.camera.bottom = -shadowExtent;
  keyLight.shadow.camera.near = 0.1;
  keyLight.shadow.camera.far = keyLightOffset.length() + Math.max(horizontalExtent, size.y) * 3.0;
  keyLight.shadow.camera.updateProjectionMatrix();
  applyGroundShadowProfile();
}

function applyGroundShadowCasterFlags(root) {
  root?.traverse(child => {
    if (!child.isMesh) return;
    const category = meshCategory(child);
    child.castShadow = category !== 'glass' && category !== 'hidden';
  });
}

function applyLightProfile(mode) {
  const profile = materialLightProfileForMode(mode, environmentMode);
  hemisphereLight.intensity = profile.hemi;
  keyLight.intensity = profile.key;
  rimLight.intensity = profile.rim;
  topFillLight.intensity = profile.top;
  frontFillLight.intensity = profile.front;
  warmAccentLight.intensity = profile.warm;
  applyGroundShadowProfile();
}

const floor = trackObjectResources(new THREE.Mesh(
  new THREE.CircleGeometry(7, 96),
  new THREE.MeshStandardMaterial({ color: 0x11161a, roughness: 0.86, metalness: 0.05 })
));
floor.rotation.x = -Math.PI / 2;
scene.add(floor);

const contactShadowCatcher = trackObjectResources(new THREE.Mesh(
  new THREE.CircleGeometry(7, 96),
  new THREE.ShadowMaterial({
    color: 0x000000,
    opacity: groundShadowStrength,
    transparent: true,
    depthWrite: false,
    toneMapped: false,
  })
));
contactShadowCatcher.rotation.x = -Math.PI / 2;
contactShadowCatcher.position.y = 0.0025;
contactShadowCatcher.renderOrder = 2;
contactShadowCatcher.visible = false;
scene.add(contactShadowCatcher);

function applyEnvironmentPresentation() {
  const homeSoft = environmentMode === 'home_soft';
  renderer.toneMappingExposure = homeSoft ? 1.10 : 1.12;
  scene.background.setHex(homeSoft ? 0x101112 : 0x090b0e);
  floor.material.color.setHex(homeSoft ? 0x292a29 : 0x11161a);
  floor.material.roughness = homeSoft ? 0.34 : 0.86;
  floor.material.metalness = homeSoft ? 0.04 : 0.05;
  floor.material.envMapIntensity = homeSoft ? 1.20 : 1.0;
  floor.material.needsUpdate = true;
  if (wheelTireInspectionScope) {
    floor.visible = false;
    contactShadowCatcher.visible = false;
  }
  if (presentationCompositeMaterial) {
    presentationCompositeMaterial.uniforms.lo4Exposure.value = renderer.toneMappingExposure;
  }
  applyLiveryColorGrade();
  applyGlassOpacityProfile();
}

let model = null;
let homeCamera = camera.position.clone();
let homeTarget = controls.target.clone();
let paintMaterials = [];
let glassMaterials = [];
let renderContract = null;
let currentManifest = null;
let baseDetailNormalTexture = null;
// 細かい凹凸の無いペイントの材質に渡す、平らな凹凸のテクスチャ（1×1。シェーダーは凹凸の塊を飛ばすので中身は使わない。
// 2026-11-20）。ページで 1 つを使い回し、差し替えでは捨てない（persistentPageResources）。
let flatDetailNormalTexture = null;
function flatDetailNormal() {
  if (!flatDetailNormalTexture) {
    flatDetailNormalTexture = new THREE.DataTexture(new Uint8Array([128, 128, 255, 255]), 1, 1, THREE.RGBAFormat);
    flatDetailNormalTexture.name = 'lo4fh6-flat-detail-normal';
    flatDetailNormalTexture.needsUpdate = true;
  }
  return flatDetailNormalTexture;
}
let baseDetailNormalProbeTextures = new Map();
let baseDetailMaskProbeTextures = new Map();
let carbonUvAttributeSummary = null;
let selectedPartOptions = new Map();
let selectablePartGroups = new Map();
let activeSectionFilter = 'all';
let variantRoots = new Map();
let variantPaintMaterials = new Map();
let variantGlassMaterials = new Map();
// r390：材質バリエーションが要求されるまで元シーンだけを保持する。
let variantCounts = new Map();
let variantSourceModel = null;
let variantSourceProjectionBounds = null;
let variantSourcePaintTexture = null;
let variantSourceMasks = null;
let viewerDisplayReportSaved = false;
let inspectionWheelGroups = new Map();
let stockWheelAssetInventories = new Map();
let compareRenderTargetA = null;
let compareRenderTargetB = null;
let compareCompositeScene = null;
let compareCompositeCamera = null;
let compareCompositeMaterial = null;
let presentationRenderTarget = null;
let presentationCompositeScene = null;
let presentationCompositeCamera = null;
let presentationCompositeMaterial = null;
let presentationAAEnabled = true;
let presentationAAFallbackReason = '';

applyEnvironmentPresentation();

function setStatus(message, error = false) {
  // 通常のエラー・ロード中などの通知は既存のまま維持。
  // 保存の結果だけ外側クリックで閉じられる状態にする。
  status.classList.remove('lo4fh6-save-notice');
  status.textContent = message;
  status.classList.toggle('hidden', !message);
  status.classList.toggle('error', error);
}

function showImageSaveNotice(message, error = false) {
  setStatus(message, error);
  if (message) status.classList.add('lo4fh6-save-notice');
}

document.addEventListener('click', event => {
  if (!status.classList.contains('lo4fh6-save-notice')) return;
  if (status.contains(event.target)) return;
  setStatus('');
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && status.classList.contains('lo4fh6-save-notice')) setStatus('');
});

function setGpuPaintStatus(usedGpu, reason = '') {
  if (!gpuPaintInfo) return;
  const active = Boolean(usedGpu);
  gpuPaintInfo.textContent = active ? t('status.gpu_paint_active') : String(reason || 'GPU-only paint unavailable');
  gpuPaintInfo.classList.toggle('hidden', active);
  gpuPaintInfo.classList.toggle('warning', !active);
  gpuPaintInfo.title = active ? '' : String(reason || 'GPU-only paint unavailable');
}

function showRasterOmissionNotice(omissions, layerCount) {
  // 省いて表示したもの（ゲームに無いステッカー、GameDB が無いために画像を引けないゲームのロゴのステッカー）と、
  // GameDB が無いときの簡易の車輪を、画面の上の注意の帯に出す（黙って省かない）。
  const items = Array.isArray(omissions) ? omissions : [];
  const noGamedb = items.filter(item => item?.reason === 'gamedb-unavailable');
  const others = items.filter(item => item?.reason !== 'gamedb-unavailable');
  const layers = Number(layerCount) || 0;
  const messages = [];
  if (gamedbMissing) messages.push(t('warning.no_gamedb_wheels'));
  if (noGamedb.length) {
    messages.push(t('warning.raster_decals_no_gamedb', {
      count: noGamedb.length, layers: (others.length ? 0 : layers) || noGamedb.length,
    }));
  }
  const ids = others.map(item => Number(item?.raster_id)).filter(Number.isSafeInteger);
  if (ids.length) {
    messages.push(t('warning.raster_decals_omitted', {
      count: ids.length, ids: ids.join(', '), layers: (noGamedb.length ? 0 : layers) || ids.length,
    }));
  }
  if (!messages.length) return;
  const message = messages.join(' ');
  if (renderErrorWarning) {
    renderErrorWarning.textContent = message;
    renderErrorWarning.classList.remove('hidden');
  }
  const allIds = items.map(item => Number(item?.raster_id)).filter(Number.isSafeInteger);
  if (allIds.length) viewerEvent('raster-decals-omitted', message, {rasterIds: allIds, layerCount: layers});
  if (gamedbMissing) viewerEvent('gamedb-missing', message, {rasterIds: allIds, layerCount: layers});
}

function updateDemoTitle() {
  if (!currentManifest) return;
  const actual = currentManifest.livery?.title || t('status.loading_livery');
  title.textContent = maskedDemoText(actual, demoHideTitle.checked, t('demo.title_redacted'));
}
function changeDemoTextPrivacy() {
  updateDemoTitle();
  updateVehicleInfo();
}
// 保存する画像（現在視点・6方向）の下の帯に書く、ペイントの情報（2026-11-21）。タイトルはペイントから読んだ物を先に使い、
// 作成者とアップロード日は Organizer から届いた物を使う。「タイトル・作成者を隠す」がオンのときは、どちらも伏せる。
function captureCaptionFields(capturedAt) {
  const organizer = currentManifest?.capture_caption || {};
  const titleText = String(currentManifest?.livery?.title || organizer.title || organizer.vehicle_name || '').trim();
  const creatorText = String(organizer.creator_name || '').trim();
  return {
    title: titleText ? maskedDemoText(titleText, demoHideTitle.checked, t('demo.title_redacted')) : '',
    creator: creatorText ? maskedDemoText(creatorText, demoHideTitle.checked, t('demo.creator_redacted')) : '',
    uploadDate: String(organizer.upload_date || '').trim(),
    capturedAt: formatCaptureTime(capturedAt),
  };
}
function withCaptureCaption(image, capturedAt) {
  return appendCaptureCaption({
    image,
    fields: captureCaptionFields(capturedAt),
    labels: {
      creator: t('capture.caption.creator'),
      uploaded: t('capture.caption.uploaded'),
      captured: t('capture.caption.captured'),
    },
    createCanvas: () => document.createElement('canvas'),
  });
}
function changeDemoMosaicPrivacy() {
  // Mask適用済みの1フレームが正常終了するまでは利用不可として扱う。
  viewport.classList.toggle('demo-vehicle-pending', demoMosaicBody.checked);
  viewport.classList.remove('demo-vehicle-failed');
  demoMosaicStrength.disabled = !demoMosaicBody.checked;
  if (!demoMosaicBody.checked) {
    demoVehicleMosaic?.dispose();
    demoVehicleMosaic = null;
  }
  requestRender();
}
function updateVehicleInfo() {
  if (!currentManifest) return;
  const modelCode = currentManifest.vehicle?.model_code || (getLanguage() === 'ja' ? '車両不明' : 'Unresolved car');
  const carId = currentManifest.livery?.target_car_id || '?';
  const placements = currentManifest.livery?.logical_placement_count || 0;
  const sourceFolderName = String(currentManifest.source?.source_folder_name || '').trim();
  const sourceSuffix = sourceFolderName ? ` · ${maskedDemoText(sourceFolderName, demoHideSource.checked, t('demo.source_redacted'))}` : '';
  vehicle.textContent = `${modelCode} · Car ID ${carId} · ${placements} ${getLanguage() === 'ja' ? '配置' : 'placements'}${sourceSuffix}`;
}

function gameDbTireSizeLabel(assembly, wheelName) {
  const dimensions = assembly?.wheel_dimensions?.[wheelName] || {};
  const widthMm = Math.round(Number(dimensions.tire_width) * 1000);
  const aspect = Math.round(Number(dimensions.tire_aspect));
  const diameter = Number(dimensions.wheel_diameter_in);
  if (!Number.isFinite(widthMm) || widthMm <= 0 || !Number.isFinite(aspect) || aspect <= 0 || !Number.isFinite(diameter) || diameter <= 0) return '';
  return `${widthMm}/${aspect} R${Number.isInteger(diameter) ? diameter : diameter.toFixed(1)}`;
}

function updateAssemblyInfo() {
  if (!assemblyInfo) return;
  const assembly = activeVehicleAssembly();
  if (assembly?.source !== 'local-fh6-gamedb') {
    assemblyInfo.textContent = '';
    assemblyInfo.classList.add('hidden');
    return;
  }
  const body = Number(assembly.car_body_id);
  const front = gameDbTireSizeLabel(assembly, 'front_left');
  const rear = gameDbTireSizeLabel(assembly, 'rear_left');
  const wheelbase = Number(assembly.wheelbase);
  const frontTrack = Number(assembly.front_track_outer);
  const rearTrack = Number(assembly.rear_track_outer);
  if (!Number.isInteger(body) || !front || !rear || ![wheelbase, frontTrack, rearTrack].every(Number.isFinite)) {
    assemblyInfo.textContent = '';
    assemblyInfo.classList.add('hidden');
    return;
  }
  assemblyInfo.textContent = t('info.assembly_gamedb', {
    body,
    front,
    rear,
    wheelbase: wheelbase.toFixed(3),
    frontTrack: frontTrack.toFixed(3),
    rearTrack: rearTrack.toFixed(3),
  });
  // 「ホイール」チェックは表示トグルであり原本車輪選択ではない。
  // 使用中の実描画入口を常に示し、代用輪を原本輪の成功と誤認させない。
  const ja = getLanguage() === 'ja';
  const wheelModeText = {
    'proxy': ja ? '従来の代用車輪（原本Wheelの外観ではありません）' : 'Legacy proxy wheels (not original Wheel appearance)',
    'stock': ja ? '原本Wheel候補＋タイヤ補完（未承認）' : 'Original Wheel candidate + tire fallback (unapproved)',
    'game-fit': ja ? 'GameDB車輪位置の研究表示（未承認）' : 'GameDB wheel fitment research (unapproved)',
    'source-verified': ja ? '原本Wheel＋原本Tire・ローカル研究（Xbox未承認）' : 'Original Wheel + Tire local research (Xbox unapproved)',
  };
  assemblyInfo.textContent += `\n${ja ? '車輪描画方式' : 'Wheel rendering'}: ${wheelModeText[wheelSource] || wheelSource} [${wheelSource}]`;
  if (wheelSource !== 'source-verified') {
    assemblyInfo.textContent += ja
      ? '\n原本Wheel画像のGPU提出監査: 対象外（起動GUIの「車輪・タイヤ」選択で切替）'
      : '\nOriginal Wheel GPU audit: inactive (select Wheel / Tire mode in launcher)';
  } else {
    assemblyInfo.textContent += ja
      ? '\n原本Wheel画像のGPU提出監査: 読込・描画確認中'
      : '\nOriginal Wheel GPU audit: loading/drawing pending';
  }
  const morphTruth = renderContract?.assembly_truth || {};
  if (morphTruth.wheelstyle_morph_applied === true) {
    const morphBody = Number(morphTruth.wheelstyle_morph_car_body_id);
    const internal = String(morphTruth.wheelstyle_morph_source || '') === 'independent-local-modelbin';
    const key = internal
      ? (Number.isInteger(morphBody) && morphBody === body
        ? 'info.assembly_morph_internal_active'
        : 'info.assembly_morph_internal_other_body')
      : (Number.isInteger(morphBody) && morphBody === body
        ? 'info.assembly_morph_reference_active'
        : 'info.assembly_morph_reference_other_body');
    assemblyInfo.textContent += t(key, {body: Number.isInteger(morphBody) ? morphBody : '?'});
  }
  assemblyInfo.classList.remove('hidden');
}

// 同一3Dモデルを複数の描画モードへ展開するとき、ユーザー向け診断文だけを
// 重複表示しない。値が異なるモードの行は残し、GPUイベントや描画処理は変更しない。
function appendDistinctAssemblyDiagnosticLine(line) {
  if (!assemblyInfo || typeof line !== 'string' || !line) return false;
  if (assemblyInfo.textContent.split('\n').includes(line)) return false;
  assemblyInfo.textContent += '\n' + line;
  assemblyInfo.classList.remove('hidden');
  return true;
}

function rgbaHexToColorNumber(value, fallback = 0xc7cbd0) {
  const text = String(value || '').trim();
  const match = /^#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$/.exec(text);
  return match ? Number.parseInt(match[1], 16) : fallback;
}

function homeSoftBasePaintColor(colorNumber, basePaint = assetRoutingBasePaint()) {
  if (environmentMode !== 'home_soft') return colorNumber;
  const materialName = String(basePaint?.material_name || '').toLowerCase();
  // r104の濃いピンクの補正はAluminumPolishedのSakura Miko参照から得た。
  // すべての仕上げに適用するとAluminumBrushedの赤が不必要に暗くなるため、
  // 測定対象の材質に限定し、他の復号済み色は原本値を維持する。
  if (materialName !== 'aluminumpolished') return colorNumber;
  const color = new THREE.Color(colorNumber);
  const hsl = {};
  color.getHSL(hsl);
  color.setHSL(hsl.h, Math.min(1.0, hsl.s * 1.02), Math.max(0.0, Math.min(1.0, hsl.l * 0.82)));
  return color.getHex();
}

function assetRoutingBasePaint() {
  return renderContract?.base_paint_material || {};
}

// 部品の記録（sourceFinish）が、車体全体の塗装（base_paint_material）と別の仕上げ・色か。
// 記録が無い部品は全体の塗装のまま（false）。
function sourceFinishDiffersFromBasePaint(sourceFinish, basePaint = assetRoutingBasePaint()) {
  if (!sourceFinish) return false;
  const hex = value => String(value || '').toLowerCase();
  return Number(sourceFinish.finish_code_raw) !== Number(basePaint?.finish_id)
    || hex(sourceFinish.primary_color_rgba_hex) !== hex(basePaint?.primary_color_rgba_hex)
    || (sourceFinish.secondary_color_rgba_hex !== null
        && hex(sourceFinish.secondary_color_rgba_hex) !== hex(basePaint?.secondary_color_rgba_hex));
}

function boundedMaterialValue(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.max(0.0, Math.min(1.0, numeric)) : fallback;
}

function roughnessFromFh6Shift(value, fallback = 0.42) {
  const shift = Number(value);
  if (!Number.isFinite(shift)) return fallback;
  if (shift <= -0.95) return 0.08;
  if (shift <= -0.75) return 0.20;
  if (shift <= -0.55) return 0.32;
  if (shift <= -0.35) return 0.50;
  return fallback;
}

function legacySafeBasePaintCandidate(basePaint) {
  const materialName = String(basePaint?.material_name || '').toLowerCase();
  const shaderFamily = String(basePaint?.shader_family || '').toLowerCase();
  const roughnessShift = Number(basePaint?.roughness_shift);
  const candidate = {
    roughness: 0.42,
    metalness: 0.04,
    env_map_intensity: 1.0,
    clearcoat: 0.35,
    clearcoat_roughness: 0.25,
    base_clearcoat_scale_home_soft: 0.22,
  };

  if (['car_carbonfiber', 'car_carbonfiber_user'].includes(shaderFamily)) {
    candidate.roughness = materialName.includes('matte') ? 0.50 : 0.24;
    candidate.metalness = materialName.includes('kevlar') ? 0.80 : 0.20;
    candidate.env_map_intensity = 1.15;
    candidate.clearcoat = 1.0;
    candidate.clearcoat_roughness = materialName.includes('matte') ? 0.60 : 0.0;
  } else if (['car_standard', 'car_standard_user'].includes(shaderFamily)) {
    const metalSurface = /^(aluminum|brass|chromium|copper|gold|steel|damascus|galvanized)/.test(materialName);
    candidate.roughness = roughnessFromFh6Shift(roughnessShift, 0.42);
    candidate.metalness = metalSurface ? 1.0 : 0.05;
    candidate.env_map_intensity = metalSurface ? 1.45 : 1.10;
    candidate.clearcoat = 0.0;
    candidate.clearcoat_roughness = 0.0;
  } else if (['car_automotive_paint', 'car_automotive_paint_user', 'car_candy_paint', 'car_candy_paint_user', 'car_glitter_paint', 'car_glitter_paint_user'].includes(shaderFamily)) {
    candidate.roughness = materialName.includes('matte') ? 0.51
      : materialName.includes('semigloss') ? 0.44
        : materialName.includes('polished') ? 0.30
          : roughnessFromFh6Shift(roughnessShift, 0.30);
    candidate.metalness = 0.06;
    candidate.env_map_intensity = /(metallic|glitter|candy|prismacolor|zinc)/.test(materialName) ? 1.30 : 1.20;
    candidate.clearcoat = materialName === 'zinc' ? 0.0 : 1.0;
    candidate.clearcoat_roughness = materialName.includes('matte') ? 0.60
      : materialName.includes('semigloss') ? 0.40 : 0.0;
  }

  // r143以前のキャッシュでもXbox参照の2材質を保全する。
  // AluminumBrushedのR=0.32を公開判定用の確認点とし、
  // 厳密な外観一致は公開後の追加研究事項として区別する。
  if (materialName === 'aluminumbrushed') {
    Object.assign(candidate, {
      roughness: 0.32,
      metalness: 1.0,
      env_map_intensity: 1.70,
      clearcoat: 1.0,
      clearcoat_roughness: 0.06,
      base_clearcoat_scale_home_soft: 0.62,
    });
  } else if (materialName === 'aluminumpolished') {
    Object.assign(candidate, {
      roughness: 0.0,
      metalness: 1.0,
      env_map_intensity: 1.32,
      clearcoat: 1.0,
      clearcoat_roughness: 0.0,
      base_clearcoat_scale_home_soft: 0.22,
    });
  }
  return candidate;
}

function basePaintViewerCandidate(basePaint = assetRoutingBasePaint()) {
  const explicit = basePaint?.viewer_candidate || {};
  // 新契約はゲーム原本由来の候補を直接保持する。
  // 旧キャッシュは材質識別子とShader系統のみを保持するため、
  // 同じ範囲制限のある互換候補を導出し、明示された契約値を優先する。
  return {
    ...legacySafeBasePaintCandidate(basePaint),
    ...explicit,
  };
}

// ラメ・メタリックの塗装（MetallicGlitterPaint・MetallicPaint など、シェーダー car_glitter_paint_user・
// car_automotive_paint_user）の第 2 色（ラメの色）。2026-11-18〜19。
// ゲームの材質は、ユーザーの色を使うとき第 1 色を地の色（PaintColor）、第 2 色をラメの色（FlakeColor）にする
// （UserColorSwitch が真、入れ替えとツートンの角度の切り替えが偽）。
// Xbox 版 FH6 の画面（Car 3414 の拡大）では、塗装が見えている所は「暗い金色の地に、金色の小さな粒がまばらに光る」。
// そこで 2 つを重ねる。
// (1) 目に見えないほど細かい粒の平均の色：地の色を第 2 色へ「ラメの量 × 強さ × FLAKE_TINT_PER_COVERAGE」の割合で寄せる。
//     割合は 3414 の Xbox 版の画面で、テープ（塗装が見えている所）の明るさが周りの黄色の約 0.35（直線の明るさで約 0.1）
//     だったことから、第 1 色 #171616・第 2 色 #cb992d で約 0.28（ラメの量 0.5）とした（Viewer の撮影の照明で比 0.3 前後）。
// (2) 近くで見える光る粒：車体の表面を細かい升に分け、一部の升を粒にして、粒ごとに少し傾けた向きで環境の映り込みを足す
//     （反射の光なので明るい環境ほど目立つ）。粒が画素より小さいときは平均の明るさで足す（ちらつきを防ぐ）。
//     粒は塗装が見えている所で強く、ステッカーの上では弱い（Xbox 版の拡大で、黄色のステッカーの上の粒は控えめ）。
// メタリックも同じ形で描く（粒を塗装が見えている所に絞ってからは、見本と合う：1500 のシャンパン色、4222 の紫寄り、
// 4164 の明るい銀色）。ツートン（角度の切り替え）と入れ替えは対象にしない。
// 部品ごとの仕上げ（source-finish-pbr.mjs）では、その部品の記録の第 2 色で描く（2467 の赤、3953 の緑）。
const FLAKE_TINT_PER_COVERAGE = 0.55;
const FLAKE_CELLS_PER_UNIT = 650.0;
const FLAKE_FRACTION_PER_COVERAGE = 0.3;
const FLAKE_STRENGTH = 2.5;
const FLAKE_TILT = 0.6;
function basePaintFlakeLayer(basePaint = assetRoutingBasePaint()) {
  const family = String(basePaint?.shader_family || '').toLowerCase();
  if (!['car_glitter_paint', 'car_glitter_paint_user', 'car_automotive_paint', 'car_automotive_paint_user'].includes(family)) {
    return null;
  }
  const params = basePaint?.game_material_parameters || {};
  if (params.user_color_enabled !== true) return null;
  if (params.user_color_swap_primary_secondary === true) return null;
  if (params.user_color_flop_switch1 === true || params.user_color_flop_switch2 === true) return null;
  // 切り替えを持たない古い目録では、ツートンを名前で見分けて外す。
  if (params.user_color_flop_switch1 === undefined && /^twotone/i.test(String(basePaint?.material_name || ''))) return null;
  const coverage = Number(params.flake_coverage);
  if (!Number.isFinite(coverage) || coverage <= 0.0) return null;
  const glitter = Number.isFinite(Number(params.glitter_intensity))
    ? Math.max(0.0, Math.min(2.0, Number(params.glitter_intensity))) : 1.0;
  const roughness = Number.isFinite(Number(params.flake_roughness))
    ? Math.max(0.02, Math.min(1.0, Number(params.flake_roughness))) : 0.3;
  const hex = String(basePaint?.secondary_color_rgba_hex || '');
  if (!/^#[0-9a-fA-F]{8}$/.test(hex) || hex.slice(-2).toLowerCase() === '00') return null;
  const fraction = Math.max(0.0, Math.min(1.0, Math.min(1.0, coverage) * FLAKE_FRACTION_PER_COVERAGE));
  if (fraction <= 0.0 || glitter <= 0.0) return null;
  const tint = Math.max(0.0, Math.min(0.9, Math.min(1.0, coverage) * Math.min(1.0, glitter) * FLAKE_TINT_PER_COVERAGE));
  return {color: new THREE.Color(hex.slice(0, 7)), fraction, strength: glitter * FLAKE_STRENGTH, roughness, tint, hex};
}

function r175AutomotiveBaselineCandidate(basePaint = assetRoutingBasePaint()) {
  const current = basePaintViewerCandidate(basePaint);
  const family = String(basePaint?.shader_family || '').toLowerCase();
  if (!['car_automotive_paint', 'car_automotive_paint_user', 'car_candy_paint', 'car_candy_paint_user', 'car_glitter_paint', 'car_glitter_paint_user'].includes(family)) {
    return current;
  }
  const params = basePaint?.game_material_parameters || {};
  const numeric = (name, fallback = null) => {
    const value = Number(params?.[name]);
    return Number.isFinite(value) ? value : fallback;
  };
  const clamp01 = value => Math.max(0.0, Math.min(1.0, value));
  const clearcoatRoughness = clamp01(numeric('clearcoat_roughness', Number(current.clearcoat_roughness) || 0.0));
  const roughnessShift = numeric('roughness_shift', null);
  const flakeRoughness = numeric('flake_roughness', null);
  const flakeCoverage = clamp01(numeric('flake_coverage', 0.0));
  let roughness = 0.30 + 0.35 * clearcoatRoughness;
  if (roughnessShift !== null && roughnessShift < 0.0) roughness += 0.25 * roughnessShift;
  if (flakeRoughness !== null && flakeCoverage > 0.0) {
    roughness = Math.min(roughness, Math.max(0.18, Math.min(0.42, flakeRoughness)));
  }
  return {
    ...current,
    roughness: clamp01(roughness),
    env_map_intensity: flakeCoverage > 0.0 ? 1.30 : 1.20,
    flake_response_strength: 0.0,
    glancing_response_strength: 0.0,
    source: 'diagnostic_r175_automotive_baseline',
  };
}


function assetRoutingBasePaintColorHex() {
  const selection = renderContract?.base_paint_selection || {};
  if (selection.color_available === false) return null;
  return renderContract?.base_paint_color_rgba_hex
    || selection.primary_color_rgba_hex
    || null;
}

function viewerMaterialLabel(mode) {
  return mode === 'physical'
    ? t('material.physical')
    : mode === 'asset_routing'
      ? t('material.asset_routing')
    : mode === 'asset_routing_r175_baseline'
      ? t('material.asset_routing_r175_baseline')
    : mode === 'carbon_detail_uv0_probe'
      ? t('material.carbon_detail_uv0_probe')
    : mode === 'carbon_detail_uv1_probe'
      ? t('material.carbon_detail_uv1_probe')
    : mode === 'carbon_detail_texture_uv0_probe'
      ? t('material.carbon_detail_texture_uv0_probe')
    : mode === 'carbon_detail_texture_uv1_probe'
      ? t('material.carbon_detail_texture_uv1_probe')
    : mode === 'carbon_mask_texture_uv0_probe'
      ? t('material.carbon_mask_texture_uv0_probe')
    : mode === 'carbon_mask_texture_uv1_probe'
      ? t('material.carbon_mask_texture_uv1_probe')
    : mode === 'asset_routing_roughness'
      ? t('material.asset_routing_roughness')
    : mode === 'asset_routing_roughness_032'
      ? t('material.asset_routing_roughness_032')
    : mode === 'asset_routing_roughness_036'
      ? t('material.asset_routing_roughness_036')
    : mode === 'asset_routing_clearcoat'
      ? t('material.asset_routing_clearcoat')
    : mode === 'asset_routing_ibl'
      ? t('material.asset_routing_ibl')
    : mode === 'base_paint_direct'
      ? t('material.base_paint_direct')
    : mode === 'base_paint_mask'
      ? t('material.base_paint_mask')
    : mode === 'reflection_only'
      ? t('material.reflection_only')
    : mode === 'reflection_boost'
      ? t('material.reflection_boost')
    : mode === 'basic'
      ? t('material.basic')
      : mode === 'decal_alpha'
        ? t('material.decal_alpha')
        : mode === 'decal_luma'
          ? t('material.decal_luma')
          : t('material.diagnostic');
}

function comparePartner(mode) {
  if (mode === 'carbon_detail_uv0_probe') return 'carbon_detail_uv1_probe';
  if (mode === 'carbon_detail_uv1_probe') return 'carbon_detail_uv0_probe';
  if (mode === 'carbon_detail_texture_uv0_probe') return 'carbon_detail_texture_uv1_probe';
  if (mode === 'carbon_detail_texture_uv1_probe') return 'carbon_detail_texture_uv0_probe';
  if (mode === 'carbon_mask_texture_uv0_probe') return 'carbon_mask_texture_uv1_probe';
  if (mode === 'carbon_mask_texture_uv1_probe') return 'carbon_mask_texture_uv0_probe';
  if (mode === 'asset_routing_r175_baseline') return 'asset_routing';
  if (['asset_routing_roughness', 'asset_routing_clearcoat', 'asset_routing_ibl'].includes(mode)) return 'asset_routing';
  if (['asset_routing_roughness_032', 'asset_routing_roughness_036'].includes(mode)) return 'asset_routing';
  if (mode === 'asset_routing') return 'physical';
  if (mode === 'physical') return 'asset_routing';
  if (mode === 'basic') return 'physical';
  return null;
}

function canCompareMaterials() {
  return materialMode === 'asset_routing'
    || materialMode === 'asset_routing_r175_baseline'
    || materialMode === 'carbon_detail_uv0_probe'
    || materialMode === 'carbon_detail_uv1_probe'
    || materialMode === 'carbon_detail_texture_uv0_probe'
    || materialMode === 'carbon_detail_texture_uv1_probe'
    || materialMode === 'carbon_mask_texture_uv0_probe'
    || materialMode === 'carbon_mask_texture_uv1_probe'
    || materialMode === 'asset_routing_roughness'
    || materialMode === 'asset_routing_roughness_032'
    || materialMode === 'asset_routing_roughness_036'
    || materialMode === 'asset_routing_clearcoat'
    || materialMode === 'asset_routing_ibl'
    || materialMode === 'physical'
    || materialMode === 'basic';
}

function effectiveCompareMode() {
  return canCompareMaterials() ? compareMode : 'off';
}

function markDisplayPresetCustom() {
  if (displayPreset === 'custom') return;
  displayPreset = 'custom';
  displayPresetSelect.value = 'custom';
  replaceViewerParam('preset', 'custom', 'custom');
  viewerEvent('display-preset-custom', '', {});
}

// チェック変更時にリロードする。カメラ・面・他表示設定はURLとsessionStorageで保持。
function switchAppearanceOption(key, enabled) {
  saveViewerReloadState();
  const next = new URL(window.location.href);
  next.searchParams.set(key, enabled ? 'on' : 'off');
  viewerEvent('appearance-toggle', '', {key, enabled, defaultOn:true});
  window.location.replace(next.toString());
}

function saveViewerReloadState() {
  try {
    window.sessionStorage.setItem('lo4fh6-viewer-reload-state-v1', JSON.stringify({
      camera: camera.position.toArray(),
      target: controls.target.toArray(),
      section: activeSectionFilter,
    }));
  } catch (_error) {
    // sessionStorageが利用できなくても再読込機能は維持する。
  }
}

async function changeDisplayPreset() {
  const selected = displayPresetSelect.value;
  if (selected === 'custom') {
    displayPreset = 'custom';
    replaceViewerParam('preset', 'custom', 'custom');
    viewerEvent('display-preset', '', {displayPreset});
    return;
  }
  const profile = DISPLAY_PRESETS[selected];
  if (!profile) return;
  saveViewerReloadState();
  // r155：表示プリセットはViewer実行時のプロファイルに限定する。
  // 元のq1〜q4画質に関係なく準備済みPaint Atlas／キャッシュを再利用する。
  // プリセット切替時に元C_liveryを再読込させない。
  const url = new URL(window.location.href);
  const setParam = (name, value, defaultValue = null) => {
    if (defaultValue !== null && String(value) === String(defaultValue)) url.searchParams.delete(name);
    else url.searchParams.set(name, String(value));
  };
  setParam('preset', selected);
  setParam('material', profile.materialMode, 'asset_routing');
  setParam('compare', profile.compareMode, 'off');
  setParam('glass', profile.glassMode, 'game');
  setParam('environment', profile.environmentMode, 'home_soft');
  setParam('reflection-angle', profile.reflectionAngle, 0);
  setParam('reflection-strength', profile.reflectionStrength, defaultReflectionStrengthForEnvironment(profile.environmentMode));
  setParam('render-quality', profile.renderQuality, 'reference');
  setParam('aa', profile.aaMode, 'off');
  viewerEvent('display-preset', '', {displayPreset: selected, ...profile});
  window.location.replace(url.toString());
}

function recoverMaterialShaderFailure(error) {
  const message = String(error?.message || error || '');
  if (!message.includes('could not compile the livery shader')) return false;
  // 既定ONはPR67/68の既存成功復旧動作を保護。OFFは例外を握りつぶさず停止。
  if (recoverableShaderContinueToggle?.checked === false) return false;
  const failedMode = materialMode;
  const fallbackMode = lastRenderableMaterialMode !== failedMode
    && variantRoots.has(lastRenderableMaterialMode)
    ? lastRenderableMaterialMode
    : 'physical';
  if (fallbackMode === failedMode || !variantRoots.has(fallbackMode)) return false;
  markDisplayPresetCustom();
  materialMode = fallbackMode;
  materialModeSelect.value = fallbackMode;
  compareMode = 'off';
  applyLightProfile(materialMode);
  replaceViewerParam('material', materialMode, 'asset_routing');
  replaceViewerParam('compare', compareMode, 'off');
  updateCompareControls();
  rebuildStudioEnvironment();
  const warning = t('error.shader_mode_fallback', {
    failed: viewerMaterialLabel(failedMode),
    fallback: viewerMaterialLabel(fallbackMode),
  });
  setStatus(warning, true);
  // Scene/phaseが次フレームへ進んでも、元Shader失敗の警告は画面から消さない。
  if (renderErrorWarning) {
    renderErrorWarning.textContent = warning;
    renderErrorWarning.classList.remove('hidden');
  }
  viewerEvent('shader-mode-fallback', message, {failedMode, fallbackMode, recoveryEnabled:true, originalShaderFailed:true});
  requestRender();
  return true;
}

function syncCompareOutputs() {
  compareModeSelect.value = compareMode;
  compareSplitInput.value = String(compareSplit);
  compareSplitOutput.value = `${Math.round(compareSplit)}%`;
  differenceGainInput.value = String(differenceGain);
  differenceGainOutput.value = `${differenceGain.toFixed(differenceGain % 1 === 0 ? 0 : 1)}×`;
}

function replaceViewerParam(name, value, defaultValue = null) {
  const url = new URL(window.location.href);
  if (defaultValue !== null && String(value) === String(defaultValue)) {
    url.searchParams.delete(name);
  } else {
    url.searchParams.set(name, String(value));
  }
  window.history.replaceState(null, '', url.toString());
}

function setVariantVisibility(primaryMode = null) {
  if (primaryMode && modelReady) ensureVariantRoot(primaryMode);
  for (const [mode, root] of variantRoots.entries()) {
    root.visible = mode === primaryMode;
  }
}

function updateCompareInfo() {
  if (!compareInfo) return;
  const partner = comparePartner(materialMode);
  const mode = effectiveCompareMode();
  const glassLabel = glassModeSelect.options[glassModeSelect.selectedIndex]?.text || t('glass.game');
  if (mode === 'off' || !partner) {
    setCompareInfoText(t('info.mode', {material: viewerMaterialLabel(materialMode), glass: glassLabel}));
    return;
  }
  if (mode === 'split') {
    setCompareInfoText(t('info.compare_split', {
      left: viewerMaterialLabel(materialMode),
      right: viewerMaterialLabel(partner),
      split: Math.round(compareSplit),
    }));
    return;
  }
  if (mode === 'difference') {
    setCompareInfoText(t('info.compare_difference', {
      left: viewerMaterialLabel(materialMode),
      right: viewerMaterialLabel(partner),
      gain: differenceGain.toFixed(differenceGain % 1 === 0 ? 0 : 1),
    }));
    return;
  }
  if (mode === 'heatmap') {
    setCompareInfoText(t('info.compare_heatmap', {
      left: viewerMaterialLabel(materialMode),
      right: viewerMaterialLabel(partner),
      gain: differenceGain.toFixed(differenceGain % 1 === 0 ? 0 : 1),
    }));
    return;
  }
  setCompareInfoText(t('info.compare_flicker', {
    left: viewerMaterialLabel(materialMode),
    right: viewerMaterialLabel(partner),
  }));
}

function updateCompareControls() {
  const enabled = canCompareMaterials();
  if (!enabled) compareMode = 'off';
  compareModeSelect.disabled = !enabled;
  syncCompareOutputs();
  const splitVisible = enabled && compareMode === 'split';
  const gainVisible = enabled && ['difference', 'heatmap'].includes(compareMode);
  compareSplitControl.classList.toggle('hidden', !splitVisible);
  differenceGainControl.classList.toggle('hidden', !gainVisible);
  reflectionAngleControl.classList.toggle('hidden', !['sweep', 'reference'].includes(environmentMode));
  reflectionStrengthControl.classList.toggle('hidden', !(isAssetRoutingMode(materialMode) || ['reflection_only', 'reflection_boost', 'physical', 'basic'].includes(materialMode)));
  updateCompareInfo();
}

function disposeCompareTargets() {
  if (compareRenderTargetA) trackedTextures.delete(compareRenderTargetA.texture);
  if (compareRenderTargetB) trackedTextures.delete(compareRenderTargetB.texture);
  compareRenderTargetA?.dispose();
  compareRenderTargetB?.dispose();
  compareRenderTargetA = null;
  compareRenderTargetB = null;
}

function presentationAAProfile() {
  const qualityDefaults = renderQuality === 'reference'
    ? {soft: 0.72, standard: 1.0, strong: 1.0, veryStrong: 1.0}
    : renderQuality === 'high'
      ? {soft: 0.58, standard: 0.78, strong: 0.96, veryStrong: 1.0}
      : {soft: 0.46, standard: 0.64, strong: 0.82, veryStrong: 0.94};
  if (aaMode === 'soft') {
    return {
      edgeStrength: qualityDefaults.soft,
      contrastThreshold: 0.0200,
      supersampleScale: renderQuality === 'reference' ? 1.10 : 1.0,
      searchSpan: 7.0,
      subpixelBlend: 0.04,
      label: 'soft',
    };
  }
  if (aaMode === 'strong') {
    return {
      edgeStrength: qualityDefaults.strong,
      contrastThreshold: 0.0100,
      supersampleScale: renderQuality === 'reference' ? 1.55 : 1.22,
      searchSpan: 11.0,
      subpixelBlend: 0.14,
      label: 'strong',
    };
  }
  if (aaMode === 'very_strong') {
    return {
      edgeStrength: qualityDefaults.veryStrong,
      contrastThreshold: 0.0078,
      supersampleScale: renderQuality === 'reference' ? 1.85 : 1.34,
      searchSpan: 14.0,
      subpixelBlend: 0.24,
      label: 'very_strong',
    };
  }
  return {
    edgeStrength: qualityDefaults.standard,
    contrastThreshold: 0.0156,
    supersampleScale: renderQuality === 'reference' ? 1.25 : 1.0,
    searchSpan: 8.0,
    subpixelBlend: 0.08,
    label: 'standard',
  };
}

function shouldUsePresentationAA() {
  return presentationAAEnabled && aaMode !== 'off';
}

function presentationSupersampleScale() {
  return presentationAAProfile().supersampleScale;
}

function disposePresentationTargets() {
  if (presentationRenderTarget) trackedTextures.delete(presentationRenderTarget.texture);
  presentationRenderTarget?.dispose();
  presentationRenderTarget = null;
}

function ensurePresentationComposite() {
  if (presentationCompositeScene && presentationCompositeCamera && presentationCompositeMaterial) return;
  presentationCompositeScene = new THREE.Scene();
  presentationCompositeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  presentationCompositeMaterial = trackMaterial(new THREE.ShaderMaterial({
    uniforms: {
      tDiffuse: { value: null },
      inverseResolution: { value: new THREE.Vector2(1, 1) },
      edgeStrength: { value: 0.75 },
      contrastThreshold: { value: 0.0156 },
      searchSpan: { value: 8.0 },
      subpixelBlend: { value: 0.08 },
      lo4Exposure: { value: renderer.toneMappingExposure },
    },
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = vec4(position.xy, 0.0, 1.0);
      }
    `,
    fragmentShader: `
      uniform sampler2D tDiffuse;
      uniform vec2 inverseResolution;
      uniform float edgeStrength;
      uniform float contrastThreshold;
      uniform float searchSpan;
      uniform float subpixelBlend;
      uniform float lo4Exposure;
      varying vec2 vUv;

      vec3 lo4RRTAndODTFit(vec3 value) {
        vec3 a = value * (value + 0.0245786) - 0.000090537;
        vec3 b = value * (0.983729 * value + 0.4329510) + 0.238081;
        return a / b;
      }

      vec3 lo4ACESFilmic(vec3 color) {
        const mat3 inputMat = mat3(
          vec3(0.59719, 0.07600, 0.02840),
          vec3(0.35458, 0.90834, 0.13383),
          vec3(0.04823, 0.01566, 0.83777)
        );
        const mat3 outputMat = mat3(
          vec3(1.60475, -0.10208, -0.00327),
          vec3(-0.53108, 1.10813, -0.07276),
          vec3(-0.07367, -0.00605, 1.07602)
        );
        color *= lo4Exposure / 0.6;
        color = inputMat * color;
        color = lo4RRTAndODTFit(color);
        color = outputMat * color;
        return clamp(color, 0.0, 1.0);
      }

      vec3 lo4SrgbOETF(vec3 color) {
        vec3 lo = color * 12.92;
        vec3 hi = pow(max(color, vec3(0.0)), vec3(0.41666)) * 1.055 - vec3(0.055);
        return mix(hi, lo, vec3(lessThanEqual(color, vec3(0.0031308))));
      }

      vec3 lo4SampleToneMapped(vec2 uv) {
        return lo4ACESFilmic(texture2D(tDiffuse, uv).rgb);
      }

      // LO4FH6の研究用エッジ補完（r84）。
      // 独自の小型3×3勾配・被覆率フィルターで、FXAA/SMAAから移植していない。
      // 後処理AAは任意で既定OFFとし、面全体の合成AAを比較基準とする。
      float lo4EdgeLuma(vec3 rgb) {
        return dot(rgb, vec3(0.299, 0.587, 0.114));
      }

      void main() {
        vec2 texel = inverseResolution;
        vec3 rgbM = lo4SampleToneMapped(vUv);
        vec3 rgbNW = lo4SampleToneMapped(vUv + vec2(-texel.x, -texel.y));
        vec3 rgbNE = lo4SampleToneMapped(vUv + vec2( texel.x, -texel.y));
        vec3 rgbSW = lo4SampleToneMapped(vUv + vec2(-texel.x,  texel.y));
        vec3 rgbSE = lo4SampleToneMapped(vUv + vec2( texel.x,  texel.y));
        vec3 rgbN = lo4SampleToneMapped(vUv + vec2(0.0, -texel.y));
        vec3 rgbS = lo4SampleToneMapped(vUv + vec2(0.0,  texel.y));
        vec3 rgbW = lo4SampleToneMapped(vUv + vec2(-texel.x, 0.0));
        vec3 rgbE = lo4SampleToneMapped(vUv + vec2( texel.x, 0.0));

        float lumaM = lo4EdgeLuma(rgbM);
        float lumaNW = lo4EdgeLuma(rgbNW);
        float lumaNE = lo4EdgeLuma(rgbNE);
        float lumaSW = lo4EdgeLuma(rgbSW);
        float lumaSE = lo4EdgeLuma(rgbSE);
        float lumaN = lo4EdgeLuma(rgbN);
        float lumaS = lo4EdgeLuma(rgbS);
        float lumaW = lo4EdgeLuma(rgbW);
        float lumaE = lo4EdgeLuma(rgbE);

        float lumaMin = min(lumaM, min(min(min(lumaN, lumaS), min(lumaW, lumaE)), min(min(lumaNW, lumaNE), min(lumaSW, lumaSE))));
        float lumaMax = max(lumaM, max(max(max(lumaN, lumaS), max(lumaW, lumaE)), max(max(lumaNW, lumaNE), max(lumaSW, lumaSE))));
        float contrast = lumaMax - lumaMin;
        vec3 finalColor = rgbM;

        if (contrast >= contrastThreshold) {
          // Sobel型の局所輝度勾配。正規化した勾配をエッジ法線として使用し、
          // 両側をサンプリングしてサブピクセル被覆率を推定する。
          // 外部AA Shaderへの依存はない。
          float gx = (lumaNE + 2.0 * lumaE + lumaSE) - (lumaNW + 2.0 * lumaW + lumaSW);
          float gy = (lumaSW + 2.0 * lumaS + lumaSE) - (lumaNW + 2.0 * lumaN + lumaNE);
          vec2 gradient = vec2(gx, gy);
          float gradientLength = max(length(gradient), 1.0e-6);
          vec2 normal = gradient / gradientLength;
          float radius = clamp(searchSpan * 0.0625, 0.35, 0.90);
          vec2 offset = normal * texel * radius;
          vec3 sideA = lo4SampleToneMapped(vUv - offset);
          vec3 sideB = lo4SampleToneMapped(vUv + offset);
          vec3 coverageEstimate = (rgbM * 2.0 + sideA + sideB) * 0.25;
          vec3 neighborhoodAvg = (rgbM * 2.0 + rgbN + rgbS + rgbW + rgbE + rgbNW + rgbNE + rgbSW + rgbSE) / 10.0;
          float edgeBlend = smoothstep(contrastThreshold, contrastThreshold * 4.0, contrast);
          vec3 edgeResolved = mix(rgbM, coverageEstimate, edgeStrength * edgeBlend);
          finalColor = mix(edgeResolved, neighborhoodAvg, subpixelBlend * edgeBlend);
        }

        gl_FragColor = vec4(lo4SrgbOETF(finalColor), 1.0);
      }
    `,
    depthTest: false,
    depthWrite: false,
    toneMapped: false,
  }));
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), presentationCompositeMaterial);
  trackedGeometries.add(quad.geometry);
  presentationCompositeScene.add(quad);
}

function ensurePresentationTarget() {
  if (!shouldUsePresentationAA()) return;
  ensurePresentationComposite();
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const scale = presentationSupersampleScale();
  const maximum = Math.max(1, renderer.capabilities.maxTextureSize || 4096);
  let width = Math.max(1, Math.round(size.x * scale));
  let height = Math.max(1, Math.round(size.y * scale));
  const cap = Math.min(1, maximum / width, maximum / height);
  width = Math.max(1, Math.round(width * cap));
  height = Math.max(1, Math.round(height * cap));
  const needsNewTarget = !presentationRenderTarget || presentationRenderTarget.width !== width || presentationRenderTarget.height !== height;
  if (needsNewTarget) {
    disposePresentationTargets();
    presentationRenderTarget = new THREE.WebGLRenderTarget(width, height, { depthBuffer: true });
    presentationRenderTarget.texture.colorSpace = THREE.NoColorSpace;
    const maximumSamples = gl.MAX_SAMPLES ? Number(gl.getParameter(gl.MAX_SAMPLES) || 0) : 0;
    presentationRenderTarget.samples = Math.min(4, Math.max(0, maximumSamples));
    trackTexture(presentationRenderTarget.texture);
  }
  const aaProfile = presentationAAProfile();
  presentationCompositeMaterial.uniforms.inverseResolution.value.set(1 / width, 1 / height);
  presentationCompositeMaterial.uniforms.edgeStrength.value = aaProfile.edgeStrength;
  presentationCompositeMaterial.uniforms.contrastThreshold.value = aaProfile.contrastThreshold;
  presentationCompositeMaterial.uniforms.searchSpan.value = aaProfile.searchSpan;
  presentationCompositeMaterial.uniforms.subpixelBlend.value = aaProfile.subpixelBlend;
  presentationCompositeMaterial.uniforms.lo4Exposure.value = renderer.toneMappingExposure;
}

function presentRenderTarget(target, outputTarget = null) {
  if (!target) return;
  resetTargetOrDefault(outputTarget);
  presentationCompositeMaterial.uniforms.tDiffuse.value = target.texture;
  renderer.render(presentationCompositeScene, presentationCompositeCamera);
}

function ensureCompareComposite() {
  if (compareCompositeScene && compareCompositeCamera && compareCompositeMaterial) return;
  compareCompositeScene = new THREE.Scene();
  compareCompositeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  compareCompositeMaterial = trackMaterial(new THREE.ShaderMaterial({
    uniforms: {
      sceneA: { value: null },
      sceneB: { value: null },
      gain: { value: differenceGain },
      split: { value: compareSplit / 100 },
      mode: { value: 1 },
    },
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = vec4(position.xy, 0.0, 1.0);
      }
    `,
    fragmentShader: `
      uniform sampler2D sceneA;
      uniform sampler2D sceneB;
      uniform float gain;
      uniform float split;
      uniform float mode;
      varying vec2 vUv;
      void main() {
        vec4 a = texture2D(sceneA, vUv);
        vec4 b = texture2D(sceneB, vUv);
        if (mode < 1.5) {
          gl_FragColor = vUv.x <= split ? a : b;
          return;
        }
        vec3 diff = clamp(abs(a.rgb - b.rgb) * gain, 0.0, 1.0);
        vec3 reference = 0.5 * (a.rgb + b.rgb);
        float referenceLuma = dot(reference, vec3(0.2126, 0.7152, 0.0722));
        if (mode < 2.5) {
          // r178：2つの材質応答が近い場合、純粋な差分画像はほぼ黒になる。
          // RGB実測差分は変更せず、薄い無彩色の参照画像を重ねて
          // 車体輪郭と差異の位置を判別可能にする。
          // この背景画像は診断専用で、差分量には算入しない。
          vec3 context = vec3(referenceLuma * 0.08);
          gl_FragColor = vec4(clamp(context + diff, 0.0, 1.0), 1.0);
          return;
        }
        // r179：上記の生差分を保持し、微小な材質応答差には別の知覚用Heatmapを用意する。
        // 平方根での強調は可視化専用で、RGB実測差分の置換や再入力はしない。
        // 差分が小さい箇所は青／シアン、中程度は黄、最大は赤に近付ける。
        float diffMagnitude = max(diff.r, max(diff.g, diff.b));
        float heatStrength = sqrt(clamp(diffMagnitude, 0.0, 1.0));
        vec3 heatBlue = vec3(0.08, 0.24, 1.00);
        vec3 heatCyan = vec3(0.00, 0.95, 1.00);
        vec3 heatYellow = vec3(1.00, 0.90, 0.05);
        vec3 heatRed = vec3(1.00, 0.08, 0.02);
        vec3 heatColor = heatStrength < 0.33
          ? mix(heatBlue, heatCyan, heatStrength / 0.33)
          : (heatStrength < 0.66
            ? mix(heatCyan, heatYellow, (heatStrength - 0.33) / 0.33)
            : mix(heatYellow, heatRed, (heatStrength - 0.66) / 0.34));
        vec3 heat = heatColor * heatStrength;
        vec3 heatContext = vec3(referenceLuma * 0.05);
        gl_FragColor = vec4(clamp(heatContext + heat, 0.0, 1.0), 1.0);
      }
    `,
    depthTest: false,
    depthWrite: false,
  }));
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), compareCompositeMaterial);
  trackedGeometries.add(quad.geometry);
  compareCompositeScene.add(quad);
}

function ensureCompareTargets() {
  ensureCompareComposite();
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const width = Math.max(1, Math.round(size.x));
  const height = Math.max(1, Math.round(size.y));
  const needsNewTarget = target => !target || target.width !== width || target.height !== height;
  if (needsNewTarget(compareRenderTargetA) || needsNewTarget(compareRenderTargetB)) {
    disposeCompareTargets();
    compareRenderTargetA = new THREE.WebGLRenderTarget(width, height, { depthBuffer: true });
    compareRenderTargetB = new THREE.WebGLRenderTarget(width, height, { depthBuffer: true });
    trackTexture(compareRenderTargetA.texture);
    trackTexture(compareRenderTargetB.texture);
  }
  compareCompositeMaterial.uniforms.gain.value = differenceGain;
  compareCompositeMaterial.uniforms.split.value = compareSplit / 100;
}

function resetDefaultRendererState() {
  renderer.setRenderTarget(null);
  const size = renderer.getSize(new THREE.Vector2());
  const width = Math.max(1, Math.round(size.x));
  const height = Math.max(1, Math.round(size.y));
  renderer.setScissorTest(false);
  renderer.setScissor(0, 0, width, height);
  renderer.setViewport(0, 0, width, height);
  renderer.clear(true, true, true);
}

function resetRenderTargetState(target) {
  // WebGLRenderer.setRenderTarget()は対象固有の画素座標Viewport／Scissorを復元する。
  // renderer.setViewport()は論理描画器座標で指定され、オフスクリーン経路に
  // DPRを再適用する恐れがあるため、ここでは呼び出さない。
  target.viewport.set(0, 0, target.width, target.height);
  target.scissor.set(0, 0, target.width, target.height);
  target.scissorTest = false;
  renderer.setRenderTarget(target);
  renderer.clear(true, true, true);
}

function resetTargetOrDefault(target) {
  if (target) resetRenderTargetState(target);
  else resetDefaultRendererState();
}

// 読み込み・差し替えの最初の 1 枚の前に、物を作らずに照明の状態だけを用意する（2026-11-20）。three.js は 1 枚ごとに、
// 影を照明の準備より先に描くので、起動後の最初の 1 枚の影の深さのシェーダーは「影 0 個」の鍵で作られ、最初の差し替えで
// 「影 1 個」の鍵で作り直していた（シェーダーの文は同じで、鍵だけが違う）。空の場面を、本当の場面を対象にして compile
// すると、本当の場面の光と影を数えて照明の状態だけを用意する（材質は作らず、描く物・影の結果は変わらない）。
const shadowLightPrimingScene = new THREE.Scene();

function renderSceneVariant(variantMode, target = null) {
  const firstPass = modelReady && !firstFrameReady;
  const begin = firstPass ? performance.now() : 0;
  setVariantVisibility(variantMode);
  if (target) resetRenderTargetState(target);
  else resetDefaultRendererState();
  if (firstPass) renderer.compile(shadowLightPrimingScene, camera, scene);
  const beforeRender = firstPass ? performance.now() : 0;
  renderer.render(scene, camera);
  // 実描画命令に乗った原本Wheel材質数を一度だけ表示。Xbox見た目の承認とは区別。
  if (wheelSource === 'source-verified' && sourceNeutralResearch) {
    const audit = sourceWheelMaterialAudit.variants.get(variantMode);
    if (audit && !audit.reported) {
      audit.reported = true;
      const claims = sourceWheelMaterialAudit.declared || {signedMaterials:0,signedWheelPrimitives:0};
      const result = {glb:sourceWheelMaterialAudit.glb, retained:audit.retained,
        submitted:audit.drawn.size, variant:variantMode,
        signedMaterials:claims.signedMaterials, signedWheelPrimitives:claims.signedWheelPrimitives,
        gltfMaterialRecognitionMismatch:claims.signedWheelPrimitives > 0 && sourceWheelMaterialAudit.glb === 0,
        unresolvedPaintOutputColor:audit.unresolvedPaintOutputColor || 0,
        provenPaintInputRoutes:audit.provenPaintInputRoutes || 0,
        unresolvedPaintInputRoutes:audit.unresolvedPaintInputRoutes || 0,
        sourcePrimaryResearchApplied:audit.researchApplied || 0,
        sourcePrimaryResearchRejected:audit.researchRejected || {},
        sourceOnly:true, pixelParityApproved:false};
      window.__lo4fh6SourceWheelMaterialDrawAudit = result;
      viewerEvent('source-wheel-material-gpu-submission', '', result);
      if (sourceWheelStandardAutoEnabled) {
        const standardAudit = summarizeWheelPaintStandardDraw({
          variant:variantMode,
          declared:result.glb,retained:result.retained,drawSubmitted:audit.drawn,
          wheelPaintUnresolved:result.unresolvedPaintOutputColor,
          primarySourceRoutes:result.provenPaintInputRoutes,
          unresolvedSourceRoutes:result.unresolvedPaintInputRoutes,
          researchAppliedUuids:audit.researchAppliedUuids,
          lipFallbackUuids:audit.lipFallbackUuids,
          rejected:result.sourcePrimaryResearchRejected,
        });
        window.__lo4fh6WheelPaintStandardDrawAudit = standardAudit;
        viewerEvent('source-wheel-paint-standard-signed-draw', '', standardAudit);
      }
      if (assemblyInfo && !sourceWheelMaterialAudit.delivered) {
        assemblyInfo.textContent += `\n原本Wheel画像: GLB ${result.glb} / 保持 ${result.retained} / GPU提出 ${result.submitted}（画質未承認）`;
        assemblyInfo.textContent += `\n原本GLB材質宣言: ${result.signedMaterials}件 / Wheelプリミティブ ${result.signedWheelPrimitives}件`;
        if (result.unresolvedPaintOutputColor > 0) {
          assemblyInfo.textContent += `\n原本WheelPaint: ${result.unresolvedPaintOutputColor} meshのShader最終色は未承認（BaseColorAlpha原本画像のみ・g_CarUserColor0合成未確認）。`;
          assemblyInfo.textContent += `\n輪色入力ルート: 出典一致 ${result.provenPaintInputRoutes} / 未解決 ${result.unresolvedPaintInputRoutes}`;
          if (sourceWheelStandardAutoEnabled) {
            assemblyInfo.textContent += `\n原本署名済みWheel標準仕上げ: 適用 ${result.sourcePrimaryResearchApplied} / 拒否 ${JSON.stringify(result.sourcePrimaryResearchRejected)}（Windows受入済み機能／Xbox Shader未承認）`;
          } else {
            assemblyInfo.textContent += '（原本画像のみ・研究用再着色OFF）';
          }
        }
        if (result.signedWheelPrimitives === 0) {
          assemblyInfo.textContent += '\n未接続: 原本Wheel画像の署名付き材質がGLBにありません。ローカル原本材質生成・キャッシュを確認してください。';
        }
        if (result.gltfMaterialRecognitionMismatch) {
          assemblyInfo.textContent += '\n要確認: GLBの署名済み車輪材質をThree.js側で認識できません。未接続のまま画質承認しないでください。';
        }
        assemblyInfo.classList.remove('hidden');
        sourceWheelMaterialAudit.delivered = true;
      }
    }
  }
  if (firstPass) {
    timings.firstFrameVariantSetupMs = Math.round((timings.firstFrameVariantSetupMs || 0) + beforeRender - begin);
    timings.firstFrameThreeRenderMs = Math.round((timings.firstFrameThreeRenderMs || 0) + performance.now() - beforeRender);
  }
}

function renderSplitComparison(primaryMode, secondaryMode, target = null) {
  const size = target
    ? new THREE.Vector2(target.width, target.height)
    : renderer.getSize(new THREE.Vector2());
  const width = Math.max(1, Math.round(size.x));
  const height = Math.max(1, Math.round(size.y));
  const splitX = Math.max(1, Math.min(width - 1, Math.round(width * (compareSplit / 100))));

  renderSceneVariant(primaryMode, target);
  renderer.clearDepth();
  setVariantVisibility(secondaryMode);
  renderer.setScissorTest(true);
  renderer.setScissor(splitX, 0, width - splitX, height);
  renderer.setViewport(0, 0, width, height);
  renderer.render(scene, camera);
  renderer.setScissorTest(false);
  renderer.setScissor(0, 0, width, height);
  renderer.setViewport(0, 0, width, height);
}

function renderDifferenceComparison(primaryMode, secondaryMode, target = null, heatmap = false) {
  ensureCompareTargets();
  renderSceneVariant(primaryMode, compareRenderTargetA);
  renderSceneVariant(secondaryMode, compareRenderTargetB);
  setVariantVisibility(null);
  resetTargetOrDefault(target);
  compareCompositeMaterial.uniforms.sceneA.value = compareRenderTargetA.texture;
  compareCompositeMaterial.uniforms.sceneB.value = compareRenderTargetB.texture;
  compareCompositeMaterial.uniforms.mode.value = heatmap ? 3 : 2;
  renderer.render(compareCompositeScene, compareCompositeCamera);
}

function renderSelectedModeCore(timestamp, target = null) {
  const mode = effectiveCompareMode();
  const partner = comparePartner(materialMode);
  if (mode === 'split' && partner) {
    renderSplitComparison(materialMode, partner, target);
    return;
  }
  if (mode === 'difference' && partner) {
    renderDifferenceComparison(materialMode, partner, target, false);
    return;
  }
  if (mode === 'heatmap' && partner) {
    renderDifferenceComparison(materialMode, partner, target, true);
    return;
  }
  if (mode === 'flicker' && partner) {
    const phase = Math.floor(timestamp / 700) % 2;
    renderSceneVariant(phase === 0 ? materialMode : partner, target);
    return;
  }
  renderSceneVariant(materialMode, target);
}

function renderSelectedMode(timestamp, outputTarget = null) {
  const firstPass = modelReady && !firstFrameReady;
  if (shouldUsePresentationAA()) {
    try {
      const targetStart = firstPass ? performance.now() : 0;
      ensurePresentationTarget();
      if (firstPass) timings.firstFrameAaTargetMs = Math.round(performance.now() - targetStart);
      renderSelectedModeCore(timestamp, presentationRenderTarget);
      setVariantVisibility(null);
      const compositeStart = firstPass ? performance.now() : 0;
      presentRenderTarget(presentationRenderTarget, outputTarget);
      if (firstPass) timings.firstFrameAaCompositeMs = Math.round(performance.now() - compositeStart);
      return true;
    } catch (error) {
      presentationAAEnabled = false;
      presentationAAFallbackReason = String(error?.message || error);
      disposePresentationTargets();
      presentationCompositeScene = null;
      presentationCompositeCamera = null;
      presentationCompositeMaterial = null;
      console.warn('Presentation edge resolve disabled after shader/render failure.', error);
      viewerEvent('presentation-aa-fallback', presentationAAFallbackReason);
      updateRenderInfo();
    }
  }
  renderSelectedModeCore(timestamp, outputTarget);
  return false;
}

let demoVehicleMosaic = null;
function renderDemoProtected(timestamp) {
  if (!demoVehicleMosaic) {
    demoVehicleMosaic = createDemoVehicleMosaic(THREE,renderer,scene,camera,{
      floor, contactShadowCatcher, setVariantVisibility,
      hasVehicle: () => modelReady && variantRoots.size > 0,
    });
  }
  demoVehicleMosaic.render(timestamp, materialMode, demoMosaicStrength.value,
    (time,target) => renderSelectedMode(time,target), shouldUsePresentationAA());
  viewport.classList.remove('demo-vehicle-pending','demo-vehicle-failed');
}
function meshIdentity(mesh) {
  return `${mesh.name || ''} ${mesh.material?.name || ''}`.toLowerCase();
}
function normalizedSourceEntry(value) {
  return String(value || '').replace(/\\/g, '/').replace(/^\/+/, '').toLowerCase();
}

function removeBodyKitReplacedMeshes(root, removedEntries) {
  const removed = new Set((Array.isArray(removedEntries) ? removedEntries : []).map(normalizedSourceEntry));
  if (!removed.size || !root) return 0;
  const targets = [];
  root.traverse(child => {
    if (!child.isMesh) return;
    const sourceEntry = normalizedSourceEntry(child.userData?.lo4_source_entry);
    if (sourceEntry && removed.has(sourceEntry)) targets.push(child);
  });
  for (const child of targets) child.parent?.remove(child);
  return targets.length;
}


function isExplicitNonPaintIdentity(identity) {
  return [
    'headlight', 'headlamp', 'foglight', 'fog_lamp', 'lamp_lens',
    'taillight', 'tail_lamp', 'brakelight', 'brake_lamp', 'stoplamp',
    'indicator', 'turnsignal', 'turn_signal', 'signal_lamp', 'blinker',
    'chrome', 'badge', 'emblem', 'muffler', 'exhaust',
    'grille', 'grill', 'mesh', 'vent',
    'interior', 'seat', 'dashboard', 'dash', 'steering', 'cabin',
    'rubber', 'molding', 'wiper', 'undercarriage', 'tire',
    'blackglass', 'gls_clear'
  ].some(token => identity.includes(token));
}

function isBodyPanelIdentity(identity) {
  return [
    'body', 'bodywork', 'bodyshell', 'body_shell', 'shell', 'skin', 'panel', 'exterior',
    'hood', 'bonnet', 'door', 'fender', 'quarter', 'roof',
    'hatch', 'trunk', 'boot', 'decklid', 'deck_lid', 'rocker', 'sill', 'fascia', 'bumper'
  ].some(token => identity.includes(token));
}

function meshMaterialNameLower(mesh) {
  return String(mesh?.userData?.lo4_material_name || mesh?.userData?.lo4fh6_material_name || '').toLowerCase();
}

// 純正のペイント（工場のステッカー）の板。材質 livery_sticker（ID06_livery_sticker・livery_sticker_002 等）。
function isFactoryLiveryStickerMesh(mesh) {
  return /(^|_)livery_sticker(_\d+)?$/.test(meshMaterialNameLower(mesh).split('|')[0]);
}

// ペイントを載せない材質（CarPaintNoLivery・CarbonFiber_Paint_noLivery 等）。
function isNoLiveryMaterialMesh(mesh) {
  return meshMaterialNameLower(mesh).split('|')[0].includes('nolivery');
}

function meshCategory(mesh) {
  // 利用者のペイントを描くときは、純正のステッカーの板は出さない（ゲームでは利用者のペイントに置き換わる）。
  if (isFactoryLiveryStickerMesh(mesh)) {
    mesh.userData.lo4fh6_factory_livery_sticker_hidden = true;
    return 'hidden';
  }
  // ペイントを載せないカーボンで、塗装の記録に結び付かないものは、ほかのカーボンの部品と同じく部品として描く。
  if (isNoLiveryMaterialMesh(mesh) && meshMaterialNameLower(mesh).includes('carbon')
      && /^0{16}$/.test(String(mesh?.userData?.lo4_material_binding_hash || mesh?.userData?.lo4fh6_material_binding_hash || ''))) {
    mesh.userData.lo4fh6_no_livery_carbon_trim = true;
    return 'trim';
  }
  const declared = String(mesh.userData?.lo4_role || '').toLowerCase();
  // 原本材質の研究描画は、過去の名前由来 paint 復旧に優先させる。
  // 通常入口も原本ModelBin/MatI署名でアクセサリーを判定。未知素材は旧処理を保持。
  if (sourceAccessoryStandardAutoEnabled) {
    const accessory = sourceOriginalAccessoryStandardGate(mesh);
    if (accessory.ok) {
      mesh.userData.lo4fh6_source_accessory_compare = accessory.sourceRole;
      return accessory.category;
    }
    const nonPaint = sourceOriginalNonPaintTrimGuard(mesh);
    if (nonPaint.guard) {
      mesh.userData.lo4fh6_source_nonpaint_trim_guarded = nonPaint.originalMaterial;
      return 'trim';
    }
  }
  // ペイントに Mirror の記録があり、部品の結び付け（lo4fh6_material_binding_hash）が Mirror の
  // ミラーの部品の塗装面は、材質名（carPaint・CarPaint_a 等）によらずミラーのカバーとして投影から分け、
  // Mirror の記録の色で描く（Car 3072 POR_911GT3RS_18 の右ミラーは CarPaint_a で、材質名の判定に当たらず
  // 車体の色＋ステッカーの投影で描かれていた。ゲームのサムネイルは Mirror の記録の赤一色）。
  if (declared === 'paint' && namedMirrorPaintMesh(mesh)) {
    mesh.userData.lo4fh6_named_mirror_paint = true;
    return 'trim';
  }
  // 署名済みミラーカバーは通常入口でも投影から分離。工場色の仮選択は研究に限定。
  if (sourceAccessoryStandardAutoEnabled) {
    const mirrorGate = sourceMirrorHousingPaintStandardGate(mesh);
    if (mirrorGate.ok && declared !== 'hidden') {
      mesh.userData.lo4fh6_mirror_housing_source_compare = true;
      return 'trim';
    }
  }
  // 原本Shader研究GLBは従来のUV3/部品名によるpaint昇格より優先し、通常GLBは変更しない。
  const originalRole = sourceOriginalResearchMeshRole(mesh.userData, Boolean(mesh.geometry?.getAttribute('uv3')));
  if (originalRole !== null) return originalRole;
  // SideMarkerの透明レンズは窓ガラスではない。原本材質と部品が共に一致した研究時のみ別扱い。
  if (sourceNeutralResearch && sourceNeutralMaterialRole(mesh).role === 'marker_glass' && declared !== 'hidden') return 'trim';
  const identity = meshIdentity(mesh);
  const hasUv3 = Boolean(mesh.geometry?.getAttribute('uv3'));

  // FH6の車体材質には、独自Converterの保守的なPaint分類で名前を認識できないものがある。
  // 正しいLivery用TEXCOORD_3を持っていても中立Trimに分類されるため、
  // 明確に車体パネルと判定できる面だけを補完対象とする。
  // Lamp／Chrome／Interiorなど明示された材質は中立のまま維持する。
  if (
    declared === 'trim'
    && hasUv3
    && isBodyPanelIdentity(identity)
    && !isExplicitNonPaintIdentity(identity)
  ) {
    mesh.userData.lo4_role_recovery = 'trim_uv3_body';
    return 'paint';
  }
  if (['paint', 'glass', 'hidden', 'dark', 'trim'].includes(declared)) return declared;
  if (
    identity.includes('gls_window')
    || identity.includes('gls_windshield')
    || identity.includes('glassflivery')
    || identity.includes('glass_livery')
    || identity.includes('windshield')
    || identity.includes('windsheild')
  ) return 'glass';
  if (hasUv3 && identity.includes('glass') && !identity.includes('blackglass') && !identity.includes('gls_clear')) {
    return 'glass';
  }
  if (identity.includes('carpaint') || identity.includes('car_paint')) return 'paint';
  if (identity.includes('shadow')) return 'hidden';
  if (
    identity.includes('blackglass')
    || identity.includes('gls_clear')
    || identity.includes('undercarriage')
    || identity.includes('tire')
  ) return 'dark';
  return 'trim';
}

function meshAllowedSides(mesh, category) {
  // ペイントを載せない材質には、どの面のペイントも貼らない（塗装だけ）。
  if (isNoLiveryMaterialMesh(mesh)) return 0;
  // 独自原本研究GLBで明示した許可0を全ガラス面許可に取り違えない。
  const researchSides = sourceOriginalResearchLiverySides(mesh.userData, category, SECTION_COUNT);
  if (researchSides !== null) return researchSides;
  const declared = Number(mesh.userData?.lo4_allowed_sides);
  if (Number.isInteger(declared) && declared > 0 && declared < (1 << SECTION_COUNT)) {
    return declared;
  }
  return category === 'glass' ? ALL_GLASS_SIDES : ALL_BODY_SIDES;
}

function meshProjectionSides(mesh) {
  const declared = Number(mesh.userData?.lo4_projection_sides);
  return Number.isInteger(declared) && declared >= 0 && declared < (1 << SECTION_COUNT)
    ? declared
    : 0;
}

function neutralSurfaceProfile(mesh, category) {
  const identity = meshIdentity(mesh);
  if (category === 'dark') return 'dark';
  if (mesh?.userData?.lo4fh6_named_mirror_paint === true && namedPaintGroup('Mirror'))
    return 'source_named_mirror_paint';
  if (sourceNeutralResearch) {
    const evidence = sourceNeutralMaterialRole(mesh);
    switch (evidence.role) {
      case 'mirror_surface': return 'bright_metal';
      case 'antenna_plastic':
      case 'antenna_rubber':
      case 'mirror_rubber':
      case 'mirror_plastic':
      case 'marker_plastic': return 'dark_trim';
      case 'mirror_metal': return 'bright_metal';
      case 'mirror_carpaint': {
        // ペイントの Mirror の記録（ミラーのカバーの色・仕上げ）があれば、その色で描く。
        // ゲームのサムネイルのミラーは Mirror の記録の色（Car 365 黄・2817 紺・3072 赤・3849 黒・
        // 4057 紫・4223 灰。カーボンはほぼ黒）で、メーカー指定色の 0 番（365 なら WR ブルー）ではない。
        // 部品の結び付け（lo4fh6_material_binding_hash）が別の塗る場所なら使わない。
        const namedMirror = namedPaintGroup('Mirror');
        const mirrorBinding = String(mesh?.userData?.lo4fh6_material_binding_hash
          || mesh?.geometry?.userData?.lo4fh6_material_binding_hash || '').toUpperCase();
        if (namedMirror && (!mirrorBinding || mirrorBinding === String(namedMirror.binding_hash_hex || '').toUpperCase()))
          return 'source_named_mirror_paint';
        // Windows+Xbox目視で既受入のMirror OEM白プレビューを通常入口へ再接続。
        // 元ModelBin/MatI/UV3＋ManufacturerColors Mirror slot0色の両方を必須にし、
        // 署名ミラーカバーが不一致ならLiveryピンクへ黙って後退しない。
        const cover = sourceMirrorHousingPaintStandardGate(mesh);
        if (sourceAccessoryStandardAutoEnabled && cover.ok) {
          const proof = renderContract?.original_accessory_research;
          const factory = sourceMirrorFactoryStandardEligible(mesh, proof);
          if (!factory.ok) {
            // 車両原本に「Mirror selector0の工場色候補」が明示できないとき
            // だけ元GLBの材質を保持。非署名の色を他車種へ流用しない。
            // 署名付きのPalette契約が壊れている場合は従来どおり明示停止。
            if (!sourceMirrorOriginalMaterialRetentionAllowed(proof))
              throw new Error('原本Mirror標準色を検証できません: ' + factory.reason);
            mesh.userData.lo4fh6_mirror_factory_preview_unavailable = String(proof.unavailable_reason);
            return 'source_mirror_original_glb';
          }
          mesh.userData.lo4fh6_signed_mirror_factory_color = factory.colorHex;
          return factory.profile;
        }
        // 署名のない他のpaint面は従来経路から不用意に変更しない。
        return 'source_body_color';
      }
      case 'marker_reflector':
      case 'marker_glass': return 'indicator_lens';
    }
  }
  if (
    identity.includes('headlight')
    || identity.includes('headlamp')
    || identity.includes('foglight')
    || identity.includes('fog_lamp')
    || identity.includes('lamp_lens')
  ) return 'headlight_lens';
  if (
    identity.includes('taillight')
    || identity.includes('tail_lamp')
    || identity.includes('brakelight')
    || identity.includes('brake_lamp')
    || identity.includes('stoplamp')
  ) return 'taillight_lens';
  if (
    identity.includes('indicator')
    || identity.includes('turnsignal')
    || identity.includes('turn_signal')
    || identity.includes('signal_lamp')
    || identity.includes('blinker')
  ) return 'indicator_lens';
  // 出典の部品の名前（bumperFEmblem_a 等）より、メッシュの名前のグリル（grille_a_LODS0）を優先する
  // （Car 2270：グリルがエンブレムの判定に当たり、模様の無い金属一色で描かれていた）。
  const sourceMeshName = String(mesh?.userData?.lo4fh6_source_mesh_name || mesh?.userData?.lo4_source_mesh_name || '')
    .toLowerCase();
  if (/grill/.test(sourceMeshName) && !/chrome/.test(sourceMeshName)) return 'dark_trim';
  if (
    identity.includes('mirror')
    || identity.includes('chrome')
    || identity.includes('badge')
    || identity.includes('emblem')
    || identity.includes('muffler')
    || identity.includes('exhaust')
  ) return 'bright_metal';
  if (
    identity.includes('grille')
    || identity.includes('grill')
    || identity.includes('mesh')
    || identity.includes('vent')
  ) return 'dark_trim';
  if (
    identity.includes('interior')
    || identity.includes('seat')
    || identity.includes('dashboard')
    || identity.includes('dash')
    || identity.includes('steering')
    || identity.includes('handle')
    || identity.includes('cabin')
  ) return 'interior';
  if (
    identity.includes('bumper')
    || identity.includes('trim')
    || identity.includes('rubber')
    || identity.includes('molding')
    || identity.includes('wiper')
  ) return 'dark_trim';
  return 'trim';
}

// 車体の非塗装部品（樹脂・ゴム・内装・金属部品等）は、原本MatI→親MaterialBin→ShaderBinの色
// （Pythonの body_trim_default_color が求め、契約の body_trim_colors に入れる）で描く。
// 部品名から選んだ中立の灰色は、原本の色が反映されていない仮の色だった（NIS_SilviaKs_94の
// ボンネット左右 hoodCustom_a＝原本はほぼ黒の樹脂）。色の無い材質・ホイール・タイヤ・
// レンズ等の光学系プロファイルは従来どおり。光沢・金属度はプロファイルの値のまま。
// ランプの部品（headlight/taillight/indicator のレンズ用プロファイルになる部品）も、原本の色が
// 分かる枠・反射板は原本の色、原本がガラスのカバーは半透明のランプ用ガラス（lamp_glass）にする。
const SOURCE_BODY_TRIM_PROFILES = new Set(['trim', 'dark_trim', 'interior', 'dark',
  'headlight_lens', 'taillight_lens', 'indicator_lens']);
const SOURCE_LAMP_PROFILES = new Set(['headlight_lens', 'taillight_lens', 'indicator_lens']);
function sourceBodyTrimColor(mesh, profile) {
  if (!SOURCE_BODY_TRIM_PROFILES.has(profile)) return null;
  const proof = renderContract?.body_trim_colors;
  if (proof?.schema !== 'lo4fh6.body-trim-original-color.v1' || !proof.groups) return null;
  const sha = String(mesh?.userData?.lo4fh6_original_material_sha256
    || mesh?.geometry?.userData?.lo4fh6_original_material_sha256 || '').toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(sha)) return null;
  const partType = String(wheelMetadataForMesh(mesh, 'lo4_part_type') || '');
  const entry = String(mesh?.userData?.lo4_source_entry || mesh?.geometry?.userData?.lo4_source_entry || '')
    .toLowerCase();
  if (partType === 'Tire' || partType === 'WheelStyle' || /(^|\/)[^/]*(_wheel|tire)[^/]*\.modelbin$/.test(entry))
    return null;
  // キャリパーの塗装（材質 caliper_paint_front/rear）は、ペイントの Brakes の記録の色で描く
  // （ゲームのサムネイルのキャリパーは Brakes の記録の色：Car 1069 橙・2175 黄・3072/3227/3917/4223 赤。
  // 参照製品 car_model_renderer.cpp fallbackPaintHash も材質名の caliper を Brakes に結び付ける。参照のみ）。
  const brakes = namedPaintGroup('Brakes');
  if (brakes && /(^|\/)[^/]*caliper[^/]*\.modelbin$/.test(entry)) {
    const material = String(mesh?.userData?.lo4fh6_material_name || mesh?.userData?.lo4_material_name
      || mesh?.geometry?.userData?.lo4fh6_material_name || '').toLowerCase();
    if (material.startsWith('caliper_paint')) return {hex: 'brakes:' + brakes.hex, color: brakes.color};
  }
  const record = proof.groups[sha];
  if (record?.color_origin !== 'original-body-mati-default') return null;
  // 原本のベースカラーTextureが読めていれば、Texture×色合いで描く（読めなければ平均色）。
  const textureInfo = record.texture;
  const loadedTexture = textureInfo?.file ? sourceBodyTrimTextures.get(textureInfo.file) : null;
  if (record.surface === 'glass') {
    // 原本がガラスShaderのランプのカバー（GLBの役割はtrim）は、不透明な中立色でなく半透明の
    // ランプ用ガラスで描き、中の反射板・発光部が見えるようにする。部品は出典ModelBin名で判定
    // （参照製品 car_model_renderer.cpp isLampSurface：glass*HL_/TL_/CHMSLをランプの
    // ガラスとし透明度0.20、色付きガラスは0.34。参照のみ）。ガラスの色合い（MTPRの型12）は未解読。
    const base = entry.split('/').pop() || '';
    // glass?HL＝ヘッドランプ、glass?TL＝テールランプ、glass?FL＝フォグランプ（NIS_SilviaKs_94 の glassLFL_a 等）。
    const lamp = /taillight|taillamp|chmsl|headlight|headlamp|foglight|sidemarker|indicator|turnsignal|glass[lrc]?(?:hl|tl|fl)[_.]/
      .test(base);
    if (!lamp) return null;
    const material = String(mesh?.userData?.lo4_material_name || mesh?.userData?.lo4fh6_material_name || '')
      .toLowerCase();
    // 原本のガラスの色合い（GlassColorColorParam）があればその色。色付き（彩度のある）ガラスは
    // 参照製品 の colored と同じ透明度0.34、無色は0.20。
    const glassHex = String(record.glass_rgba_hex || '');
    if (/^#[0-9a-f]{8}$/i.test(glassHex)) {
      const rgb = [1, 3, 5].map(i => Number.parseInt(glassHex.slice(i, i + 2), 16) / 255);
      const tinted = Math.max(...rgb) - Math.min(...rgb) > 0.2;
      return {hex: 'lamp-glass:' + glassHex.toLowerCase(), lensProfile: tinted ? 'lamp_glass_colored' : 'lamp_glass',
        lensColor: Number.parseInt(glassHex.slice(1, 7), 16)};
    }
    const colored = /colored|colour/.test(material);
    return {hex: colored ? 'lamp-glass-colored' : 'lamp-glass', lensProfile: colored ? 'lamp_glass_colored' : 'lamp_glass'};
  }
  if (SOURCE_LAMP_PROFILES.has(profile) && !/^#[0-9a-f]{8}$/i.test(String(record.rgba_hex || ''))) return null;
  // ランプの部品の発光部は従来のレンズ用プロファイル（テールランプの赤等）を保つ。原本の発光色は白・暖白で、
  // テールランプの赤は色付きガラスの色合いにあり、白い発光部の上では薄い赤のガラスでは赤が消えるため。
  // ただし出典の部品がヘッドライトの発光部（反射板）は、原本の色と Texture で不透明に描く（Car 2270 の丸目 4 灯。
  // 原本の描画区分は不透明、従来の半透明のレンズ用プロファイルでは奥の黒が透けて見えなかった）。
  // フォグランプ（橙の発光部がある）と、材質名がウインカーの発光部は従来どおり。
  const lampMaterial = String(mesh?.userData?.lo4fh6_material_name || mesh?.userData?.lo4_material_name || '')
    .toLowerCase();
  const headlampEmitter = profile === 'headlight_lens'
    && /(^|\/)[^/]*head(light|lamp)[^/]*\.modelbin$/.test(entry)
    && !/turn|indicator|signal|amber|blinker/.test(lampMaterial);
  if (SOURCE_LAMP_PROFILES.has(profile) && record.emissive === true && !headlampEmitter) return null;
  const hex = String(record.rgba_hex || '');
  if (!/^#[0-9a-f]{8}$/i.test(hex)) return null;
  // ラベル（内装の記号等）は透明部分が多いため、原本Textureの平均の不透明度で半透明に描く。
  const opacity = Number(record.opacity);
  const translucent = Number.isFinite(opacity) && opacity > 0 && opacity < 0.95;
  const tint = String(textureInfo?.tint_rgba_hex || '');
  if (loadedTexture && /^#[0-9a-f]{8}$/i.test(tint) && [0, 1].includes(textureInfo.uv_channel)) {
    const channel = textureInfo.uv_channel;
    const attribute = channel === 0 ? 'uv' : 'uv1';
    if (mesh?.geometry?.getAttribute(attribute)) {
      // ラベルの記号は Texture の α で抜く（平均の不透明度は使わない）。
      const alphaTexture = textureInfo.alpha === true;
      return {hex: `tex:${textureInfo.file}:${channel}:${textureInfo.repeat}:${tint.toLowerCase()}${alphaTexture ? ':alpha' : ''}`,
        color: Number.parseInt(tint.slice(1, 7), 16), opacity: !alphaTexture && translucent ? opacity : null,
        texture: loadedTexture, channel, repeat: textureInfo.repeat, alphaTexture};
    }
  }
  return {hex: hex.toLowerCase() + (translucent ? ':a' + opacity.toFixed(2) : ''),
    color: Number.parseInt(hex.slice(1, 7), 16), opacity: translucent ? opacity : null};
}

// body_trim_colors の原本ベースカラーTextureを先に読み込む（材質の作成は同期のため）。
// 読み込めないTextureは平均色のまま描き、件数を報告する（黙って省略しない）。
const sourceBodyTrimTextures = new Map();
let sourceBodyTrimTextureFailures = 0;
// ゲームの BC7（1×1 までの全段のミップ付き）のまま渡す飾りの画像（2026-11-20、FH6 に近づける案 ①）。
// 形：LO4BC7 の印と版（8 バイト）・幅・高さ（各 4 バイト）・全段の画素。PNG にした画像と一番上の段の画素は同じ
// （BC7 の復号は規格どおり。透明の部分が無い画像だけ）。ミップはゲームのもの。BC7 を受け取れない GPU では、
// サーバーに PNG を頼む（?png=1）。
const BC7_TEXTURE_MAGIC = [76, 79, 52, 66, 67, 55, 0, 1];
// 4×4 の塊の形（BC7 は 16 バイト、BC4 は 8 バイト）の、1×1 までの全段
function compressedMipLevels(bytes, width, height, blockBytes) {
  const mipmaps = [];
  let offset = 0, w = width, h = height;
  for (;;) {
    const size = Math.max(1, Math.ceil(w / 4)) * Math.max(1, Math.ceil(h / 4)) * blockBytes;
    if (offset + size > bytes.byteLength) throw new Error('Compressed texture data is truncated.');
    mipmaps.push({data: bytes.subarray(offset, offset + size), width: w, height: h});
    offset += size;
    if (w === 1 && h === 1) break;
    w = Math.max(1, w >> 1);
    h = Math.max(1, h >> 1);
  }
  if (offset !== bytes.byteLength) throw new Error('Compressed texture data has extra bytes.');
  return mipmaps;
}

function bc7MipLevels(bytes, width, height) {
  return compressedMipLevels(bytes, width, height, 16);
}

async function loadBodyTrimBc7Texture(url) {
  if (!renderer.extensions.has('EXT_texture_compression_bptc')) return loadTexture(`${url}?png=1`, true);
  const response = await fetch(url, {signal: loadAbort.signal});
  if (!response.ok) throw new Error(`Texture load failed (${response.status}).`);
  const buffer = await response.arrayBuffer();
  if (viewerDisposed) throw new Error('Viewer closed.');
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength < 16 || BC7_TEXTURE_MAGIC.some((value, index) => bytes[index] !== value)) {
    throw new Error('BC7 texture header is invalid.');
  }
  const header = new DataView(buffer, 8, 8);
  const width = header.getUint32(0, true);
  const height = header.getUint32(4, true);
  if (!width || !height || Math.max(width, height) > renderer.capabilities.maxTextureSize) {
    throw new Error('BC7 texture size is invalid.');
  }
  const mipmaps = bc7MipLevels(bytes.subarray(16), width, height);
  const texture = trackTexture(new THREE.CompressedTexture(mipmaps, width, height, THREE.RGBA_BPTC_Format));
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = false;
  texture.generateMipmaps = false;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = qualityProfile().anisotropy;
  texture.needsUpdate = true;
  return texture;
}

// ラベルの記号（色の画像と透明度の画像）は、元の 2 枚をゲームの形のまま受け取り、GPU で 1 回だけ合わせる
// （2026-11-21、FH6 に近づける案 ① の続き。以前は Python が合わせた PNG を書いていた）。合わせ方は PNG と同じ：
// 色は上書きの色（sRGB の 8 ビット）か色の画像の色、透明度は色の画像の α × 透明度の画像の 1 チャンネル目。
// 出来上がりは PNG と同じく sRGB の 8 ビットの RGBA の画像（ミップは GPU で作る）。BC7・BC4 を受け取れない GPU や、
// 合わせるのに失敗したときは、サーバーに合わせた PNG を頼む（?png=1）。
// 受け取る形：LO4TEX の印と版（8 バイト）・形（1＝BC7、2＝BC4、3＝RGBA8）・幅・高さ（各 4 バイト）・画素。
const LABEL_TEXTURE_MAGIC = [76, 79, 52, 84, 69, 88, 0, 1];
const LABEL_PART_FORMATS = {1: {name: 'bc7', block: 16}, 2: {name: 'bc4', block: 8}, 3: {name: 'rgba8', block: 0}};

async function fetchBodyTrimLabelPart(url, color) {
  const response = await fetch(url, {signal: loadAbort.signal});
  if (!response.ok) throw new Error(`Texture load failed (${response.status}).`);
  const buffer = await response.arrayBuffer();
  if (viewerDisposed) throw new Error('Viewer closed.');
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength < 20 || LABEL_TEXTURE_MAGIC.some((value, index) => bytes[index] !== value)) {
    throw new Error('Label texture header is invalid.');
  }
  const header = new DataView(buffer, 8, 12);
  const format = LABEL_PART_FORMATS[header.getUint32(0, true)];
  const width = header.getUint32(4, true);
  const height = header.getUint32(8, true);
  if (!format || !width || !height || Math.max(width, height) > renderer.capabilities.maxTextureSize) {
    throw new Error('Label texture size or format is invalid.');
  }
  const body = bytes.subarray(20);
  let texture;
  if (format.block) {
    texture = new THREE.CompressedTexture(compressedMipLevels(body, width, height, format.block), width, height,
      format.name === 'bc7' ? THREE.RGBA_BPTC_Format : THREE.RED_RGTC1_Format);
    texture.minFilter = THREE.LinearMipmapLinearFilter;
  } else {
    if (body.byteLength !== width * height * 4) throw new Error('Label texture data size is invalid.');
    texture = new THREE.DataTexture(body, width, height, THREE.RGBAFormat, THREE.UnsignedByteType);
    texture.minFilter = THREE.LinearFilter;
  }
  // 色の画像の色は sRGB、透明度（α・透明度の画像の 1 チャンネル目）はそのままの値（PNG の作り方と同じ）
  texture.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  texture.flipY = false;
  texture.generateMipmaps = false;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

let bodyTrimLabelCombinerState = null;
function bodyTrimLabelCombiner() {
  // 合わせる場面は 1 つを使い回す（シェーダーを作るのはページで 1 回）
  if (bodyTrimLabelCombinerState) return bodyTrimLabelCombinerState;
  const material = new THREE.ShaderMaterial({
    uniforms: {
      baseMap: {value: null}, alphaMap: {value: null}, hasBase: {value: false}, hasAlpha: {value: false},
      hasOverride: {value: false}, overrideColor: {value: new THREE.Vector3(1, 1, 1)},
    },
    vertexShader: ['varying vec2 vUv;', 'void main() {', '  vUv = uv;',
      '  gl_Position = vec4(position.xy, 0.0, 1.0);', '}'].join('\n'),
    fragmentShader: ['uniform sampler2D baseMap;', 'uniform sampler2D alphaMap;', 'uniform bool hasBase;',
      'uniform bool hasAlpha;', 'uniform bool hasOverride;', 'uniform vec3 overrideColor;', 'varying vec2 vUv;',
      'void main() {',
      '  vec4 base = hasBase ? texture2D(baseMap, vUv) : vec4(1.0);',
      '  float alpha = base.a * (hasAlpha ? texture2D(alphaMap, vUv).r : 1.0);',
      '  gl_FragColor = vec4(hasOverride ? overrideColor : base.rgb, alpha);',
      '}'].join('\n'),
    depthTest: false, depthWrite: false, blending: THREE.NoBlending, toneMapped: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  mesh.frustumCulled = false;
  const scene = new THREE.Scene();
  scene.add(mesh);
  bodyTrimLabelCombinerState = {material, scene, camera: new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)};
  return bodyTrimLabelCombinerState;
}

function srgbByteToLinear(value) {
  const v = Math.min(255, Math.max(0, Number(value) || 0)) / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function combineBodyTrimLabel(base, alpha, overrideSrgb8, width, height) {
  const combiner = bodyTrimLabelCombiner();
  const uniforms = combiner.material.uniforms;
  const override = Array.isArray(overrideSrgb8) && overrideSrgb8.length === 3 ? overrideSrgb8 : null;
  uniforms.baseMap.value = base;
  uniforms.hasBase.value = Boolean(base);
  uniforms.alphaMap.value = alpha;
  uniforms.hasAlpha.value = Boolean(alpha);
  uniforms.hasOverride.value = Boolean(override);
  if (override) uniforms.overrideColor.value.set(...override.map(srgbByteToLinear));
  // sRGB の 8 ビットの描き先に描き（書くときに sRGB にする）、そのままの値を読み戻す
  const target = new THREE.WebGLRenderTarget(width, height, {
    colorSpace: THREE.SRGBColorSpace, depthBuffer: false, stencilBuffer: false, generateMipmaps: false,
    minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
  });
  const previous = renderer.getRenderTarget();
  const pixels = new Uint8Array(width * height * 4);
  try {
    renderer.setRenderTarget(target);
    renderer.render(combiner.scene, combiner.camera);
    renderer.readRenderTargetPixels(target, 0, 0, width, height, pixels);
  } finally {
    renderer.setRenderTarget(previous);
    target.dispose();
    uniforms.baseMap.value = null;
    uniforms.alphaMap.value = null;
  }
  const texture = trackTexture(new THREE.DataTexture(pixels, width, height, THREE.RGBAFormat, THREE.UnsignedByteType));
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = false;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = true;
  texture.anisotropy = qualityProfile().anisotropy;
  texture.needsUpdate = true;
  return texture;
}

async function loadBodyTrimLabelTexture(url, label) {
  const parts = label?.parts && typeof label.parts === 'object' ? label.parts : {};
  const formats = Object.values(parts).map(part => String(part?.format || ''));
  const width = Number(label?.width);
  const height = Number(label?.height);
  const supported = formats.length > 0 && formats.every(format => ['bc7', 'bc4', 'rgba8'].includes(format))
    && (!formats.includes('bc7') || renderer.extensions.has('EXT_texture_compression_bptc'))
    && (!formats.includes('bc4') || renderer.extensions.has('EXT_texture_compression_rgtc'))
    && Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0
    && Math.max(width, height) <= renderer.capabilities.maxTextureSize;
  if (!supported) return loadTexture(`${url}?png=1`, true);
  const settled = await Promise.allSettled(['base', 'alpha'].map(part => (parts[part]
    ? fetchBodyTrimLabelPart(`${url}?part=${part}`, part === 'base') : Promise.resolve(null))));
  const [base, alpha] = settled.map(result => (result.status === 'fulfilled' ? result.value : null));
  try {
    const failure = settled.find(result => result.status === 'rejected');
    if (failure) throw failure.reason;
    if (viewerDisposed) throw new Error('Viewer closed.');
    return combineBodyTrimLabel(base, alpha, label.override_srgb8, width, height);
  } catch (error) {
    if (viewerDisposed) throw error;
    return loadTexture(`${url}?png=1`, true);
  } finally {
    base?.dispose();
    alpha?.dispose();
  }
}

async function preloadSourceBodyTrimTextures() {
  const groups = renderContract?.body_trim_colors?.groups || {};
  const labels = new Map();
  for (const record of Object.values(groups)) {
    const file = String(record?.texture?.file || '');
    if (file.endsWith('.label') && record.texture.label) labels.set(file, record.texture.label);
  }
  const files = [...new Set(Object.values(groups).map(record => record?.texture?.file)
    .filter(file => /^[0-9a-f]{64}\.(png|bc7|label)$/.test(String(file || '')) && !sourceBodyTrimTextures.has(file)))];
  await Promise.all(files.map(async file => {
    try {
      const url = `./api/local-render/body-trim-texture/${file}`;
      const texture = file.endsWith('.label') ? await loadBodyTrimLabelTexture(url, labels.get(file))
        : file.endsWith('.bc7') ? await loadBodyTrimBc7Texture(url) : await loadTexture(url, true);
      sourceBodyTrimTextures.set(file, texture);
    } catch (error) {
      if (viewerDisposed) throw error;
      sourceBodyTrimTextureFailures += 1;
    }
  }));
}

// UVの番号・繰り返し回数ごとに、共有Textureの見え方（clone）を作る。画像の実体は共有。
const sourceBodyTrimTextureViews = new Map();
function sourceBodyTrimTextureView(bodyTrim) {
  const key = bodyTrim.hex;
  if (sourceBodyTrimTextureViews.has(key)) return sourceBodyTrimTextureViews.get(key);
  const view = trackTexture(bodyTrim.texture.clone());
  view.channel = bodyTrim.channel;
  view.wrapS = THREE.RepeatWrapping;
  view.wrapT = THREE.RepeatWrapping;
  const repeat = Array.isArray(bodyTrim.repeat) ? bodyTrim.repeat : [1, 1];
  view.repeat.set(Number(repeat[0]) || 1, Number(repeat[1]) || 1);
  view.needsUpdate = true;
  sourceBodyTrimTextureViews.set(key, view);
  return view;
}

// ペイントの名前の分かった記録（Mirror・Brakes）の描画用の色（Python の named_paint_groups）。
// 記録が無い・色が分からない場合は null（従来の描き方のまま）。
function namedPaintGroup(name) {
  const proof = renderContract?.named_paint_groups;
  if (proof?.schema !== 'lo4fh6.named-paint-groups.v1') return null;
  const group = proof.groups?.[name];
  const hex = String(group?.display_rgba_hex || '');
  if (!/^#[0-9a-f]{8}$/i.test(hex)) return null;
  return {...group, hex: hex.toLowerCase(), color: Number.parseInt(hex.slice(1, 7), 16)};
}

// 結び付けが Mirror で、出典がミラーの ModelBin（wingMirror・mirrorBase 等）の部品か。
function namedMirrorPaintMesh(mesh) {
  const group = namedPaintGroup('Mirror');
  if (!group) return false;
  const binding = String(mesh?.userData?.lo4fh6_material_binding_hash
    || mesh?.geometry?.userData?.lo4fh6_material_binding_hash || '').toUpperCase();
  if (!binding || binding !== String(group.binding_hash_hex || '').toUpperCase()) return false;
  const source = String(mesh?.userData?.lo4_source_entry || mesh?.geometry?.userData?.lo4_source_entry
    || mesh?.userData?.lo4fh6_source_entry || '').toLowerCase().replace(/\\/g, '/');
  return /(^|\/)[^/]*mirror[^/]*\.modelbin$/.test(source);
}

function neutralSurfaceMaterialOptions(profile) {
  if (profile === 'source_named_mirror_paint') {
    const group = namedPaintGroup('Mirror');
    if (!group) throw new Error('ペイントの Mirror の記録の色がありません');
    // 光沢・金属度は車体の地の色と同じ決め方（記録の仕上げの材質の候補）。
    const candidate = basePaintViewerCandidate({material_name: group.material_name,
      shader_family: group.shader_family, viewer_candidate: group.viewer_candidate || {}});
    return { color: group.color,
      roughness: boundedMaterialValue(candidate.roughness, 0.42),
      metalness: boundedMaterialValue(candidate.metalness, 0.05),
      clearcoat: boundedMaterialValue(candidate.clearcoat, 0.0),
      clearcoatRoughness: boundedMaterialValue(candidate.clearcoat_roughness, 0.0) };
  }
  // FH6原本ManufacturerColorsの「Mirror」slot0が明示一致する研究時のみ。
  // 工場出荷色プレビューであり、保存C_liveryのOEM選択/ゲームShader結果とは区別する。
  if (profile === 'source_mirror_factory_preview') {
    const proof = renderContract?.original_accessory_research;
    const value = String(proof?.mirror_factory_rgb_hex || '');
    if (proof?.schema !== 'lo4fh6.source-original-accessory-mirror-oem-preview.v1'
        || proof?.source_slot !== 'Mirror' || proof?.source_selector !== 0
        || proof?.source_color_available !== true
        || !/^#[0-9a-fA-F]{6}$/.test(value)) {
      throw new Error('原本Mirror工場材質の研究色が未検証です。推測RGBへ代替しません');
    }
    // 元製品のtrim光学パラメータを維持し、色だけ原本パレットプレビューに変更。
    return { color:Number.parseInt(value.slice(1),16), roughness:0.56, metalness:0.18 };
  }
  // ミラーカバーの元carPaintは、車体と同じC_livery由来のベース色を使う。
  // 金属度・粗さは既存trim値のまま。車種専用の色や推測Shader係数を足さない。
  if (profile === 'source_body_color') {
    const raw = rgbaHexToColorNumber(assetRoutingBasePaintColorHex(), 0xc7cbd0);
    return { color: homeSoftBasePaintColor(raw, assetRoutingBasePaint()), roughness: 0.56, metalness: 0.18 };
  }
  switch (profile) {
    case 'lamp_glass':
    case 'lamp_glass_colored':
      // 原本がガラスShaderのランプのカバー（sourceBodyTrimColor）。明るいガラス色・高光沢・半透明。
      return { color: 0xe5e9f1, roughness: 0.04, metalness: 0.0, transparent: true,
        opacity: profile === 'lamp_glass_colored' ? 0.34 : 0.20, depthWrite: false };
    case 'dark':
      return { color: 0x11161b, roughness: 0.84, metalness: 0.04 };
    case 'headlight_lens':
      return { color: 0x73818d, roughness: 0.12, metalness: 0.03, transmission: 0.18, thickness: 0.2 };
    case 'taillight_lens':
      return { color: 0x7d2027, roughness: 0.16, metalness: 0.03, transmission: 0.14, thickness: 0.2 };
    case 'indicator_lens':
      return { color: 0xa96c1e, roughness: 0.18, metalness: 0.03, transmission: 0.12, thickness: 0.18 };
    case 'bright_metal':
      return { color: 0xc5ccd3, roughness: 0.22, metalness: 0.92 };
    case 'dark_trim':
      return { color: 0x293038, roughness: 0.72, metalness: 0.10 };
    case 'interior':
      return { color: 0x4a555f, roughness: 0.78, metalness: 0.08 };
    default:
      return { color: 0x56616a, roughness: 0.56, metalness: 0.18 };
  }
}

function wheelMetadataForMesh(mesh, key) {
  const primitiveValue = mesh.geometry?.userData?.[key];
  if (primitiveValue !== undefined && primitiveValue !== null && primitiveValue !== '') return primitiveValue;
  return mesh.userData?.[key];
}

function wheelPaintEvidenceRows() {
  const cars = renderContract?.wheel_paint_routing?.routing?.cars || [];
  const rows = [];
  for (const car of cars) {
    for (const row of car?.rows || []) rows.push(row);
  }
  return rows;
}

// 正常版の従来表示は維持。原本署名付きsource-verified比較だけ厳密スコープを採用。
// 公開画質が承認されるまで従来経路を変更しない。
function wheelPaintEvidenceRouteForMaterialId(materialId, mesh) {
  if (wheelSource !== 'source-verified') {
    return wheelPaintEvidenceRouteForMaterialIdLegacy(materialId);
  }
  return sourceBoundWheelPaintRoute(wheelPaintEvidenceRows(), {
    sourceEntry: wheelMetadataForMesh(mesh, 'lo4_source_entry'),
    materialId,
    materialName: wheelMetadataForMesh(mesh, 'lo4_wheel_material_name'),
    sourceModelbinSha256: wheelMetadataForMesh(mesh, 'lo4_wheel_source_modelbin_sha256'),
    materialInstanceSha256: mesh?.material?.userData?.material_instance_sha256,
    // 原本Viewerの自動色経路では無署名の旧合成テスト互換を無効化する。
    requireSourceSignature: true,
  });
}

function wheelPaintEvidenceRouteForMaterialIdLegacy(materialId) {
  const numericId = Number(materialId);
  if (!Number.isInteger(numericId) || numericId < 0) return null;
  const candidates = [];
  for (const row of wheelPaintEvidenceRows()) {
    if (Number(row?.material_id) !== numericId) continue;
    const routeKind = String(row?.route_kind || '');
    if (routeKind === 'axle_paint') {
      const frontGroup = String(row?.front_group || '');
      const rearGroup = String(row?.rear_group || '');
      const token = String(row?.material_token || row?.material_name || '').toLowerCase();
      if (frontGroup && rearGroup) candidates.push({token, routeKind, frontGroup, rearGroup});
    } else if (routeKind === 'generic_binding') {
      const group = String(row?.generic_group || '');
      const token = String(row?.material_token || row?.material_name || '').toLowerCase();
      if (group) candidates.push({token, routeKind, group});
    }
  }
  const signatures = new Map();
  for (const candidate of candidates) {
    const signature = candidate.routeKind === 'axle_paint'
      ? `${candidate.routeKind}:${candidate.frontGroup}:${candidate.rearGroup}`
      : `${candidate.routeKind}:${candidate.group}`;
    if (!signatures.has(signature)) signatures.set(signature, candidate);
  }
  return signatures.size === 1 ? [...signatures.values()][0] : null;
}

function wheelAxleForMesh(mesh) {
  const declared = String(wheelMetadataForMesh(mesh, 'lo4_wheel_morph_axle') || '').toLowerCase();
  if (declared === 'front') return 'Front';
  if (declared === 'rear') return 'Rear';
  const wheelName = String(
    wheelMetadataForMesh(mesh, 'lo4_source_wheel_name')
    || wheelMetadataForMesh(mesh, 'lo4_wheel_morph_wheel')
    || ''
  ).toLowerCase();
  if (wheelName.startsWith('front_') || wheelName.endsWith('_front')) return 'Front';
  if (wheelName.startsWith('rear_') || wheelName.endsWith('_rear')) return 'Rear';
  return '';
}

function wheelStyleEvidenceForMesh(mesh) {
  const partType = String(wheelMetadataForMesh(mesh, 'lo4_part_type') || '').toLowerCase();
  if (partType === 'wheelstyle') return true;
  const wheel = String(wheelMetadataForMesh(mesh, 'lo4_wheel_morph_wheel') || '');
  const materialId = Number(wheelMetadataForMesh(mesh, 'lo4_wheel_material_id'));
  const materialName = String(wheelMetadataForMesh(mesh, 'lo4_wheel_material_name') || '');
  return Boolean(wheel) && (Number.isInteger(materialId) || Boolean(materialName));
}

function wheelPaintRouteForMesh(mesh) {
  if (!wheelStyleEvidenceForMesh(mesh)) return null;
  const axle = wheelAxleForMesh(mesh);
  const materialId = wheelMetadataForMesh(mesh, 'lo4_wheel_material_id');
  const evidence = wheelPaintEvidenceRouteForMaterialId(materialId, mesh);
  if (evidence?.routeKind === 'generic_binding') {
    return { token: evidence.token, group: evidence.group, routeKind: evidence.routeKind, routeSource: 'material-id-evidence' };
  }
  // グループ割当の無い塗装材質：原本MatIの既定色の記録（Pythonが補った場合だけ存在）を使う。
  if (evidence?.routeKind === 'original_mati_default') {
    return { token: evidence.token, group: evidence.group, routeKind: evidence.routeKind, routeSource: 'material-id-evidence' };
  }
  if (evidence?.routeKind === 'axle_paint' && axle) {
    return {
      token: evidence.token,
      group: axle === 'Front' ? evidence.frontGroup : evidence.rearGroup,
      routeKind: evidence.routeKind,
      routeSource: 'material-id-evidence',
    };
  }

  // 厳密原本モードはg_CarUserColor0の検証済み接続以外では色を仮設定しない。
  if (wheelSource === 'source-verified') return null;
  const token = String(wheelMetadataForMesh(mesh, 'lo4_wheel_material_name') || '').replace(/\\/g, '/').split('/').pop().split('|')[0].replace(/\.materialbin$/i, '').toLowerCase();
  const axleChannels = { rim: 1, rim2: 2, inner_rim: 3, hub: 4, lug: 5 };
  const genericGroups = { rim3: 'Rims3', lip: 'RimsLip', detail: 'Wheel1', detail2: 'Wheel2' };
  if (Object.prototype.hasOwnProperty.call(genericGroups, token)) {
    return { token, group: genericGroups[token], routeKind: 'generic_binding', routeSource: 'material-token-fallback' };
  }
  const channel = axleChannels[token];
  if (!channel || !axle) return null;
  return { token, group: `${axle}WheelPaint${channel}`, routeKind: 'axle_paint', routeSource: 'material-token-fallback' };
}

// 外部の色の入力を持たない標準の材質（car_standard）のホイールの部品を、ペイントのホイールの記録の色で描く。
// ゲームはペイントでホイールを塗ると部品の材質を塗装の仕上げに差し替えるとみられ、記録の色のリムが
// サムネイルに出ている Car 634（ピンク）・1069（黒）・3595（赤）のリムは car_standard だった（40 車種で
// 記録が有効なのにリムが塗られていない例は無し）。参照製品 car_model_renderer.cpp の isWheelPaintMesh も
// 材質名（rim・rim2・inner_rim・hub・lug 等）でホイールの塗装に結び付ける（参照のみ）。部品と記録の対応は
// 既存の軸ごとの対応（rim→1、rim2→2、inner_rim→3、hub→4、lug→5）。記録の色が無効（仕上げだけの金などは
// 仕上げの材質の色）・記録が無いペイントは原本のまま。原本の Texture は残し、色と仕上げだけを替える。
const STANDARD_WHEEL_PAINT_CHANNELS = { rim: 1, rim2: 2, inner_rim: 3, hub: 4, lug: 5 };
function standardWheelPaintMaterial(mesh) {
  if (wheelSource !== 'source-verified') return null;
  const material = mesh?.material;
  const family = String(material?.userData?.shader_family || '').toLowerCase();
  if (!family.startsWith('car_standard') || typeof material?.clone !== 'function' || !material.color) return null;
  const token = String(wheelMetadataForMesh(mesh, 'lo4_wheel_material_name') || '').replace(/\\/g, '/')
    .split('/').pop().split('|')[0].replace(/\.materialbin$/i, '').toLowerCase();
  const channel = STANDARD_WHEEL_PAINT_CHANNELS[token];
  const axle = wheelAxleForMesh(mesh);
  if (!channel || !axle) return null;
  const group = `${axle}WheelPaint${channel}`;
  const record = renderContract?.wheel_paint_colors?.groups?.[group];
  if (!record) return null;
  let hex = record.primary_color_enabled === true ? String(record.primary_color_rgba_hex || '') : '';
  if (!hex && Number(record.finish_code_raw) > 0) hex = String(record.finish_material?.material_defined_rgba_hex || '');
  if (!/^#[0-9a-f]{8}$/i.test(hex) || hex.slice(7).toLowerCase() === '00') return null;
  const finish = sourceWheelFinishEvidence(record)?.candidate || null;
  const painted = material.clone();
  painted.color.setHex(Number.parseInt(hex.slice(1, 7), 16));
  if (finish) {
    painted.roughness = finish.roughness;
    painted.metalness = finish.metalness;
    painted.envMapIntensity = finish.envMapIntensity;
  }
  painted.userData = {...material.userData, lo4fh6_wheel_standard_material_paint: group};
  painted.needsUpdate = true;
  return {material: painted, group, colorHex: hex.toLowerCase()};
}

function wheelPaintFinishMaterialOptions(record) {
  // rM050: 原本カタログの署名・数値5項目を確認。null/欠落を0(鏡面)と誤解釈しない。
  // 既存の有効な製品描画は数値同一。正確なFH6 BRDFは未証明。
  const evidence = sourceWheelFinishEvidence(record);
  return evidence.candidate;
}

function wheelPaintColorForMesh(mesh) {
  let route = wheelPaintRouteForMesh(mesh);
  if (!route) return null;
  const groups = renderContract?.wheel_paint_colors?.groups || {};
  let record = groups[route.group];
  // 記録の色が無効で仕上げだけが指定されている場合（金・スチール・白・カーボン等）は、仕上げの材質が
  // 持つ色で描く（Python の material_defined_rgba_hex。Car 3645・4313 のサムネイルは金のホイール）。
  const definedHex = String(record?.finish_material?.material_defined_rgba_hex || '');
  if (record && record.primary_color_enabled !== true && Number(record.finish_code_raw) > 0
      && /^#[0-9a-f]{8}$/i.test(definedHex)) {
    record = {...record, primary_color_enabled: true, primary_color_rgba_hex: definedHex,
      color_origin: 'finish-material-defined'};
  }
  // ペイントに有効な記録が無いグループは、このメッシュの原本MatIの既定色を使う
  // （Pythonが原本MatI→親MaterialBin→ShaderBin既定値から補った場合だけ存在）。
  if (!record || record.primary_color_enabled !== true) {
    const matiSha = String(mesh?.material?.userData?.material_instance_sha256 || '').toLowerCase();
    const key = 'OriginalWheelMati:' + matiSha;
    const fallback = /^[0-9a-f]{64}$/.test(matiSha) ? groups[key] : null;
    if (fallback?.color_origin === 'original-wheel-mati-default') {
      route = {...route, group: key};
      record = fallback;
    }
  }
  if (!record || record.primary_color_enabled !== true || !record.primary_color_rgba_hex) return null;
  const color = rgbaHexToColorNumber(record.primary_color_rgba_hex, null);
  if (!Number.isInteger(color)) return null;
  // YRVLの色1は元の色0とは別。特殊Shaderで必要になる情報を捨てずに運ぶ。
  const secondaryColor = record.secondary_color_enabled === true
    ? rgbaHexToColorNumber(record.secondary_color_rgba_hex, null) : null;
  if (record.secondary_color_enabled === true && !Number.isInteger(secondaryColor)) return null;
  return {
    ...route,
    color,
    colorHex: String(record.primary_color_rgba_hex),
    secondaryColor,
    secondaryColorHex: record.secondary_color_enabled === true
      ? String(record.secondary_color_rgba_hex) : null,
    finishCode: Number.isInteger(Number(record.finish_code_raw)) ? Number(record.finish_code_raw) : null,
    // 原本ホイールMatIの既定色（ペイントにホイール記録が無いグループ）かどうか。
    colorOrigin: typeof record.color_origin === 'string' ? record.color_origin : null,
    finishMaterial: wheelPaintFinishMaterialOptions(record),
  };
}

// 参照製品の表示挙動を根拠とする研究限定候補。原本Material-ID/Shader外部入力
// が一致し、RimsLipがC_liveryに存在せず軸別WheelPaint1が明示される場合のみ。
// 通常ViewerのwheelPaintColorForMesh/routeProvenカウントは絶対に変更しない。
function wheelGenericPrimaryColorForMesh(mesh) {
  if (!sourceWheelStandardAutoEnabled || wheelSource !== 'source-verified') return null;
  const groups=renderContract?.wheel_paint_colors?.groups || {};
  const evidence=wheelPaintEvidenceRouteForMaterialId(
    wheelMetadataForMesh(mesh,'lo4_wheel_material_id'),mesh);
  // 材質IDの署名一致済みルートを使い、隠しモードの有効化引数は渡さない。
  const fallback=sourceWheelGenericPrimaryStandardRoute({
    evidenceRoute:evidence,axle:wheelAxleForMesh(mesh),groups,
  });
  if (!fallback) return null;
  const record=groups[fallback.group];
  const color=rgbaHexToColorNumber(record.primary_color_rgba_hex,null);
  if (!Number.isInteger(color)) return null;
  const secondaryColor=record.secondary_color_enabled === true
    ? rgbaHexToColorNumber(record.secondary_color_rgba_hex,null) : null;
  if (record.secondary_color_enabled === true && !Number.isInteger(secondaryColor)) return null;
  const rawFinish=record.finish_code_raw;
  const finishCode=rawFinish !== null && rawFinish !== undefined
    && rawFinish !== '' && Number.isInteger(Number(rawFinish))
    ? Number(rawFinish) : null;
  return {...fallback,color,finishCode,secondaryColor,
    secondaryColorHex:record.secondary_color_enabled === true
      ? String(record.secondary_color_rgba_hex) : null};
}

function wheelPaintMaterialOptions(mesh, profile) {
  const routed = wheelPaintColorForMesh(mesh);
  if (!routed) return null;
  const options = { ...neutralSurfaceMaterialOptions(profile), color: routed.color };
  const finish = routed.finishMaterial;
  if (finish) {
    options.roughness = finish.roughness;
    options.metalness = finish.metalness;
    options.envMapIntensity = finish.envMapIntensity;
    options.clearcoat = finish.clearcoat;
    options.clearcoatRoughness = finish.clearcoatRoughness;
  }
  return {
    options,
    routed,
    materialKeySuffix: finish
      ? `finish:${routed.finishCode}:${finish.materialName}:${finish.roughness}:${finish.metalness}:${finish.clearcoat}:${finish.clearcoatRoughness}:${finish.envMapIntensity}`
      : `finish:${routed.finishCode}:colour-only`,
  };
}

function allowedSlotArray(mask) {
  const allowed = new Float32Array(SECTION_COUNT);
  for (let slot = 0; slot < SECTION_COUNT; slot += 1) {
    allowed[slot] = (mask & (1 << slot)) !== 0 ? 1 : 0;
  }
  return allowed;
}

function meshPartOptionIds(mesh) {
  const values = mesh.userData?.lo4_part_option_ids;
  return Array.isArray(values) ? values.map(Number).filter(Number.isInteger) : [];
}

function partOptionKeyActive(key) {
  const [family, id] = String(key || '').split(':');
  return activePartOptions.get(family) === Number(id);
}

function meshPartVisible(mesh) {
  // 部品の選択肢の重ね合わせは選択中だけ表示し、置き換えられた純正の部品は隠す。
  const overlayKey = mesh.userData?.lo4_part_option_overlay;
  if (overlayKey) return partOptionKeyActive(overlayKey);
  const replacedBy = mesh.userData?.lo4_part_option_replaced_by;
  if (Array.isArray(replacedBy) && replacedBy.some(partOptionKeyActive)) return false;
  const optionIds = meshPartOptionIds(mesh);
  if (!optionIds.length) return true;
  const partType = String(mesh.userData?.lo4_part_type || '');
  const selected = selectedPartOptions.get(partType);
  if (Number.isInteger(selected)) return optionIds.includes(selected);
  return mesh.userData?.lo4_stock_part === true;
}

function partTypeLabel(value) {
  return String(value || 'Car part')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ');
}

let bodyKitVariantCatalog = [];
let activeBodyKitPartId = null;

function activeVehicleAssembly() {
  const variants = renderContract?.assembly_variants || {};
  const exact = Number.isInteger(activeBodyKitPartId) ? variants[String(activeBodyKitPartId)] : null;
  return exact || renderContract?.assembly || {};
}

function wheelAssemblyDimensions(assembly, name) {
  const exact = assembly?.wheel_dimensions?.[name] || {};
  const tireRadius = Number(exact.tire_radius ?? assembly?.tire_radius);
  const tireWidth = Number(exact.tire_width ?? assembly?.tire_width);
  const rimRadius = Number(exact.rim_radius ?? assembly?.rim_radius);
  return {tireRadius, tireWidth, rimRadius};
}

function validVehicleAssemblyFormat(assembly) {
  return ['lo4fh6_local_vehicle_assembly_v1', 'lo4fh6_local_vehicle_assembly_v2'].includes(String(assembly?.format || ''));
}

function bodyKitVariantLabel(variant) {
  const hint = String(variant?.variant_hint || 'variant');
  const key = ['stock', 'custom', 'wide'].includes(hint) ? `body_kit.${hint}` : 'body_kit.variant';
  const partId = Number(variant?.body_kit_part_id);
  return Number.isInteger(partId) ? `${t(key)} · ${partId}` : t(key);
}

function updateBodyKitControl() {
  bodyKitSelect.replaceChildren();
  for (const variant of bodyKitVariantCatalog) {
    const option = document.createElement('option');
    option.value = String(variant.body_kit_part_id);
    option.textContent = bodyKitVariantLabel(variant);
    bodyKitSelect.append(option);
  }
  if (Number.isInteger(activeBodyKitPartId)) bodyKitSelect.value = String(activeBodyKitPartId);
  bodyKitControl.classList.toggle('hidden', bodyKitVariantCatalog.length <= 1);
}

function parsePartOptionsParam(value) {
  const selected = new Map();
  for (const item of String(value || '').split(',')) {
    const match = /^([A-Za-z]{1,32}):(\d{1,12})$/.exec(item.trim());
    if (match) selected.set(match[1], Number(match[2]));
  }
  return selected;
}

// 製造元の名前（ブリッジが GameDB とゲームの文字列の表から加えたもの。無ければ空）。
function partOptionMaker(option) {
  if (option.is_stock || !option.manufacturer || typeof option.manufacturer !== 'object') return '';
  const name = option.manufacturer[getLanguage()] || option.manufacturer.en || option.manufacturer.ja;
  return typeof name === 'string' ? name : '';
}

// 表示名は「段階（製造元）」。段階と製造元が同じ選択肢が複数あれば、2 つ目から番号を付ける。
function partOptionLabel(option, sameLabelIndex) {
  const key = `part.level${option.level}`;
  const level = option.is_stock ? t('part.level0')
    : (t(key) !== key ? t(key) : `${t('part.level_other')} ${option.level}`);
  const maker = partOptionMaker(option);
  const label = maker ? t('part.option_maker', { level, maker }) : level;
  return sameLabelIndex > 0 ? `${label} ${sameLabelIndex + 1}` : label;
}

function updatePartOptionControls() {
  if (!partOptionControls) return;
  partOptionControls.replaceChildren();
  for (const entry of partOptionCatalog) {
    const label = document.createElement('label');
    label.className = 'setting-control';
    const caption = document.createElement('span');
    caption.textContent = t(`part.${entry.family}`);
    const select = document.createElement('select');
    select.dataset.family = entry.family;
    select.setAttribute('aria-label', entry.family);
    const labelCounts = new Map();
    for (const option of entry.options) {
      const labelKey = option.is_stock ? 'stock' : `${option.level}|${partOptionMaker(option)}`;
      const index = labelCounts.get(labelKey) || 0;
      labelCounts.set(labelKey, index + 1);
      const element = document.createElement('option');
      element.value = String(option.id);
      element.textContent = partOptionLabel(option, index);
      element.title = String(option.id);
      select.append(element);
    }
    const stock = entry.options.find(option => option.is_stock);
    select.value = String(activePartOptions.get(entry.family) ?? stock?.id ?? '');
    select.addEventListener('change', changePartOption);
    label.append(caption, select);
    partOptionControls.append(label);
  }
  partOptionControls.classList.toggle('hidden', partOptionCatalog.length === 0);
}

function partOptionsParamValue(selected) {
  return [...selected].map(([name, id]) => `${name}:${id}`).join(',');
}

async function changePartOption(event) {
  const select = event.target;
  const family = select?.dataset?.family;
  const entry = partOptionCatalog.find(item => item.family === family);
  const option = entry?.options.find(item => String(item.id) === select.value);
  if (!entry || !option) return;
  const next = new Map(activePartOptions);
  if (option.is_stock) next.delete(family); else next.set(family, option.id);
  if (!modelReady || !variantSourceModel || partOptionSwitching) {
    // モデルの準備前は従来どおり読み直す。
    saveViewerReloadState();
    const url = new URL(window.location.href);
    const value = partOptionsParamValue(next);
    if (value) url.searchParams.set('parts', value); else url.searchParams.delete('parts');
    viewerEvent('part-option-change', '', {family, optionId: option.id, reload: true});
    window.location.replace(url.toString());
    return;
  }
  const key = `${family}:${option.id}`;
  const previous = activePartOptions;
  const started = performance.now();
  partOptionSwitching = true;
  partOptionControls?.querySelectorAll('select').forEach(item => { item.disabled = true; });
  try {
    let rebuilt = false;
    if (!option.is_stock && !loadedPartOptionKeys.has(key)) {
      const [overlay] = await loadPartOptionOverlays(new Map([[family, option.id]]));
      if (!overlay) throw new Error(`Part option ${key} is unavailable.`);
      mergePartOptionBodyTrim([overlay]);
      await preloadSourceBodyTrimTextures();
      activePartOptions = next;
      applyPartOptionOverlays(variantSourceModel, [overlay]);
      rebuildMaterialVariants();
      rebuilt = true;
    } else {
      activePartOptions = next;
      refreshAllPartVisibility();
    }
    const value = partOptionsParamValue(next);
    replaceViewerParam('parts', value || '', '');
    viewerEvent('part-option-switched', `${key} ${Math.round(performance.now() - started)}ms${rebuilt ? ' rebuilt' : ''}`,
      {family, optionId: option.id, rebuilt});
  } catch (error) {
    activePartOptions = previous;
    select.value = String(previous.get(family) ?? entry.options.find(item => item.is_stock)?.id ?? '');
    viewerEvent('part-option-failed', key, {message: String(error?.message || error)});
  } finally {
    partOptionSwitching = false;
    partOptionControls?.querySelectorAll('select').forEach(item => { item.disabled = false; });
    requestRender();
  }
}

// 部品の表示・非表示とホイールの表示を、全ての材質の複製へ反映する。
function refreshAllPartVisibility() {
  for (const root of variantRoots.values()) {
    root.traverse(child => {
      if (!child.isMesh) return;
      child.visible = child.userData.lo4_base_visible !== false && meshPartVisible(child);
    });
  }
  for (const group of inspectionWheelGroups.values()) group.visible = wheelsVisible;
  if (wheelSource === 'stock' || wheelSource === 'source-verified') {
    for (const root of variantRoots.values()) setStockWheelAssetVisibility(root, wheelsVisible);
  }
  if (wheelTireInspectionScope) {
    for (const root of variantRoots.values()) isolateFinalWheelTireScene(root, wheelTireInspectionScope);
  }
  requestRender();
}

// 元のモデルに部品を加えた後、材質の複製だけを作り直す（GLB・Texture・ペイントは読み直さない）。
function rebuildMaterialVariants() {
  const materials = new Set();
  for (const root of variantRoots.values()) {
    scene.remove(root);
    root.traverse(child => {
      if (!child.isMesh) return;
      for (const material of Array.isArray(child.material) ? child.material : [child.material]) {
        if (material) materials.add(material);
      }
    });
  }
  // Textureは共有なので破棄しない。材質だけ破棄する（使われていれば描画時に作り直される）。
  for (const material of materials) material.dispose?.();
  paintMaterials = [];
  glassMaterials = [];
  variantRoots = new Map();
  variantPaintMaterials = new Map();
  variantGlassMaterials = new Map();
  inspectionWheelGroups = new Map();
  stockWheelAssetInventories = new Map();
  variantSourceModel.traverse(child => {
    if (!child.isMesh) return;
    const category = meshCategory(child);
    child.userData.lo4_base_visible = category !== 'hidden';
    child.visible = child.userData.lo4_base_visible && meshPartVisible(child);
  });
  variantSourceModel.updateMatrixWorld(true);
  variantSourceProjectionBounds = calculateProjectionBounds(variantSourceModel, renderContract);
  ensureVariantRoot('physical');
  if (!wheelTireInspectionScope) ensureVariantRoot(materialMode);
  model = variantRoots.get('physical') || variantRoots.get(materialMode) || null;
  model?.updateMatrixWorld(true);
  setVariantVisibility(materialMode);
  refreshAllPartVisibility();
}

// 選んだ部品の選択肢の重ね合わせのGLBと情報（置き換える純正の部品・部品の色）を読む。
// 初めての選択肢はサーバーが変換する（1 つ 1 秒未満）。失敗した選択肢は表示せず、理由を記録して続ける。
function loadPartOptionOverlays(selected, signal) {
  return Promise.all([...selected].map(([family, id]) => Promise.all([
    fetch(`./api/local-part-option-mesh/${family}/${id}`, {signal}).then(response => {
      if (!response.ok) throw new Error(`Part option ${family}:${id} load failed (${response.status}).`);
      return response.arrayBuffer();
    }).then(buffer => new GLTFLoader().parseAsync(buffer, '').then(adaptFirstpartyChassisMetadata)),
    fetch(`./api/local-part-option-meta/${family}/${id}`, {signal}).then(response => (response.ok ? response.json() : null)),
  ]).then(([item, meta]) => {
    item.scene.name = `part option ${family} ${id}`;
    item.scene.traverse(child => { child.userData.lo4_part_option_overlay = `${family}:${id}`; });
    trackObjectResources(item.scene);
    return {family, id, item, meta};
  }).catch(error => {
    if (viewerDisposed || signal?.aborted) throw error;
    viewerEvent('part-option-failed', `${family}:${id}`, {message: String(error?.message || error)});
    return null;
  })));
}

// 重ね合わせの部品の材質の色（部品の色付け）を契約の表へ加える（車体の分は上書きしない）。
function mergePartOptionBodyTrim(overlays) {
  const proof = renderContract?.body_trim_colors;
  if (!proof?.groups) return;
  for (const overlay of overlays || []) {
    for (const [sha, record] of Object.entries(overlay?.meta?.body_trim_groups || {})) {
      if (!(sha in proof.groups)) proof.groups[sha] = record;
    }
  }
}

// 置き換える純正の部品に印を付け（取り除かない）、重ね合わせの部品を加える。表示は meshPartVisible で決める。
function applyPartOptionOverlays(root, overlays) {
  for (const overlay of overlays || []) {
    if (!overlay?.item?.scene) continue;
    const info = overlay.meta?.overlay || overlay.item.scene.userData?.lo4fh6_part_option_overlay || {};
    const replaced = new Set(Array.isArray(info.replaced_instance_identities) ? info.replaced_instance_identities : []);
    const key = `${overlay.family}:${overlay.id}`;
    let replacedMeshes = 0;
    root.traverse(child => {
      if (!child.isMesh || child.userData?.lo4_part_option_overlay
          || !replaced.has(String(child.userData?.lo4_instance_identity || ''))) return;
      const marks = Array.isArray(child.userData.lo4_part_option_replaced_by) ? child.userData.lo4_part_option_replaced_by : [];
      if (!marks.includes(key)) child.userData.lo4_part_option_replaced_by = [...marks, key];
      replacedMeshes += 1;
    });
    root.add(overlay.item.scene);
    loadedPartOptionKeys.add(key);
    viewerEvent('part-option-added', key, {replacedMeshes, replacedInstances: replaced.size});
  }
}

// 重ね合わせの部品は、車体の監査に無い塗装の結び付けなら車体の地の色で描く（表示を止めない）。
// 車体の部品は従来どおり、対応しない結び付けを例外で止める。
function partOptionSafeFinish(child, resolve) {
  if (!child.userData?.lo4_part_option_overlay) return resolve();
  try {
    return resolve();
  } catch {
    return null;
  }
}

function changeBodyKit() {
  const partId = Number(bodyKitSelect.value);
  if (!Number.isInteger(partId) || partId === activeBodyKitPartId) return;
  saveViewerReloadState();
  const url = new URL(window.location.href);
  url.searchParams.set('body-kit', String(partId));
  url.searchParams.delete('part-selection');
  viewerEvent('body-kit-change', '', {bodyKitPartId: partId, playerSaveStateResolved: false});
  window.location.replace(url.toString());
}

function preparePartControls(options) {
  selectedPartOptions = new Map();
  selectablePartGroups = new Map();
  partControls.replaceChildren();
  for (const option of Array.isArray(options) ? options : []) {
    const partType = String(option?.part_type || '');
    const id = Number(option?.id);
    if (!partType || !Number.isInteger(id)) continue;
    if (!selectablePartGroups.has(partType)) selectablePartGroups.set(partType, []);
    selectablePartGroups.get(partType).push({
      id,
      level: Number(option?.level) || 0,
      stock: option?.stock === true,
    });
  }
  for (const [partType, optionsForPart] of selectablePartGroups) {
    optionsForPart.sort((a, b) => Number(b.stock) - Number(a.stock) || a.level - b.level || a.id - b.id);
    const alternatives = optionsForPart.filter(option => !option.stock);
    const requestedId = requestedPartSelection.get(partType);
    const requestedOption = Number.isInteger(requestedId)
      ? optionsForPart.find(option => option.id === requestedId) || null
      : null;
    // r207：BodyKitの明示的な研究指定でも、画面の操作部品と同じ選択状態を初期化する。
    // r206では変換対象Entry集合しか変えず、このMapがnullのままだったため、
    // Viewerが毎回lo4_stock_part幾何に戻っていた。
    selectedPartOptions.set(partType, requestedOption && !requestedOption.stock ? requestedOption.id : null);
    if (!alternatives.length) continue;
    const label = document.createElement('label');
    const select = document.createElement('select');
    const controlId = `part-${partType.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`;
    label.htmlFor = controlId;
    label.textContent = partTypeLabel(partType);
    select.id = controlId;
    select.dataset.partType = partType;
    const stockOption = document.createElement('option');
    stockOption.value = '';
    stockOption.textContent = 'Stock';
    stockOption.selected = true;
    select.append(stockOption);
    for (const option of alternatives) {
      const element = document.createElement('option');
      element.value = String(option.id);
      element.textContent = `Option ${option.level || option.id} · ${option.id}`;
      select.append(element);
    }
    select.value = requestedOption && !requestedOption.stock ? String(requestedOption.id) : '';
    partControls.append(label, select);
  }
  partControls.classList.toggle('hidden', partControls.childElementCount === 0);
}

async function loadTexture(url, color = false) {
  const response = await fetch(url, {signal: loadAbort.signal});
  if (!response.ok) throw new Error(`Texture load failed (${response.status}).`);
  const bitmap = await createImageBitmap(await response.blob(), {
    premultiplyAlpha: 'none', colorSpaceConversion: 'none',
  });
  if (viewerDisposed) { bitmap.close(); throw new Error('Viewer closed.'); }
  if (Math.max(bitmap.width, bitmap.height) > renderer.capabilities.maxTextureSize) {
    const dimensions = `${bitmap.width}x${bitmap.height}`;
    const maximum = renderer.capabilities.maxTextureSize;
    bitmap.close();
    throw new Error(
      `The prepared livery texture is ${dimensions}, but this graphics device supports up to ${maximum}px. `
      + 'Rebuild the preview with --quality 2.'
    );
  }
  const texture = trackTexture(new THREE.Texture(bitmap));
  texture.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  texture.flipY = false;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = color ? qualityProfile().anisotropy : 1;
  texture.needsUpdate = true;
  return texture;
}

function sectionArrays(contract, kind, projectionBounds) {
  const sourceRegions = Array.from({ length: SECTION_COUNT }, () => new THREE.Vector4());
  const paintRegions = Array.from({ length: SECTION_COUNT }, () => new THREE.Vector4());
  const facings = Array.from({ length: SECTION_COUNT }, () => new THREE.Vector3());
  const present = new Float32Array(SECTION_COUNT);
  const projectionAxes = Array.from({ length: SECTION_COUNT }, () => new THREE.Vector4());
  const projectionMinimum = Array.from({ length: SECTION_COUNT }, () => new THREE.Vector2(-1, -1));
  const projectionMaximum = Array.from({ length: SECTION_COUNT }, () => new THREE.Vector2(1, 1));
  const projectionMaskRegions = Array.from({ length: SECTION_COUNT }, () => new THREE.Vector4());
  for (const section of contract.sections || []) {
    const slot = Number(section.slot_index);
    if (!Number.isInteger(slot) || slot < 0 || slot >= SECTION_COUNT) continue;
    const source = section.source_region || [];
    const paint = section.paint_region || [];
    const facing = section.facing || [];
    const projectionAxis = section.projection_axis || [];
    const projectionMask = section.projection_mask_region || [];
    sourceRegions[slot].set(...source.map(Number));
    paintRegions[slot].set(...paint.map(Number));
    facings[slot].set(...facing.map(Number));
    projectionAxes[slot].set(...projectionAxis.map(Number));
    projectionMaskRegions[slot].set(...projectionMask.map(Number));
    const bounds = projectionBounds?.[slot];
    if (bounds?.valid) {
      projectionMinimum[slot].copy(bounds.minimum);
      projectionMaximum[slot].copy(bounds.maximum);
    }
    if (section.kind === kind) present[slot] = 1;
  }
  return {
    sourceRegions,
    paintRegions,
    facings,
    present,
    projectionAxes,
    projectionMinimum,
    projectionMaximum,
    projectionMaskRegions,
  };
}

function wheelArchSuppressionProfileForMesh(mesh) {
  const source = normalizedSourceEntry(mesh?.userData?.lo4_source_entry);
  const base = source.split('/').pop() || '';
  // r276：保全済みVivio GLBのピンクのWheel Arch面は従来のPaint領域だけでは説明できない。
  // フロントフェンダーと後部床にはUV3付きTrim Primitiveがあり、
  // meshCategory()がPaintへ補完している。
  // その内面はX方向で車輪中心より奥にあるため、タイヤ半径方向の切抜きは狭く保ち、
  // 対象面を実際に持つ原本Meshに対してだけ奥行きを広げる。
  if (base === 'fenders_a.modelbin') {
    return { key: 'deep-front-fenders', radiusScale: 1.015, halfWidthScale: 2.0, wheelMask: [true, true, false, false] };
  }
  if (base === 'body_a.modelbin') {
    return { key: 'deep-rear-body', radiusScale: 1.015, halfWidthScale: 2.0, wheelMask: [false, false, true, true] };
  }
  return { key: 'default', radiusScale: 1.015, halfWidthScale: 0.62, wheelMask: [true, true, true, true] };
}

function wheelArchCutoutUniformData(profile = null) {
  const assembly = activeVehicleAssembly();
  const order = ['front_left', 'front_right', 'rear_left', 'rear_right'];
  const centers = [];
  const halfWidths = [];
  let enabled = 0;
  const radiusScale = Number.isFinite(Number(profile?.radiusScale)) ? Number(profile.radiusScale) : 1.015;
  const halfWidthScale = Number.isFinite(Number(profile?.halfWidthScale)) ? Number(profile.halfWidthScale) : 0.62;
  const wheelMask = Array.isArray(profile?.wheelMask) && profile.wheelMask.length === 4
    ? profile.wheelMask.map(Boolean)
    : [true, true, true, true];
  for (let index = 0; index < order.length; index += 1) {
    const name = order[index];
    const center = assembly?.wheel_centers?.[name];
    const dims = wheelAssemblyDimensions(assembly, name);
    const radius = Number(dims?.tireRadius);
    const width = Number(dims?.tireWidth);
    if (Array.isArray(center) && center.length === 3 && center.every(v => Number.isFinite(Number(v))) && Number.isFinite(radius) && radius > 0) {
      const active = wheelMask[index] === true;
      centers.push(new THREE.Vector4(Number(center[0]), Number(center[1]), Number(center[2]), active ? radius * radiusScale : 0.0));
      halfWidths.push(active ? (Number.isFinite(width) && width > 0 ? width * halfWidthScale : radius * 0.42) : 0.0);
      enabled += 1;
    } else {
      centers.push(new THREE.Vector4(0, 0, 0, 0));
      halfWidths.push(0);
    }
  }
  return { centers, halfWidths, enabled };
}

function applyWheelArchSuppressionProfileToMaterial(material, profile) {
  if (!material) return;
  const data = wheelArchCutoutUniformData(profile);
  const uniforms = material.uniforms || material.userData?.lo4Uniforms;
  if (!uniforms) return;
  if (uniforms.lo4WheelArchCenters) uniforms.lo4WheelArchCenters.value = data.centers;
  if (uniforms.lo4WheelArchHalfWidths) uniforms.lo4WheelArchHalfWidths.value = data.halfWidths;
  if (uniforms.lo4WheelArchEnabled) uniforms.lo4WheelArchEnabled.value = data.enabled;
  material.userData.lo4WheelArchSuppressionProfile = profile?.key || 'default';
}

function sectionAwareMaterial(
  paintTexture,
  maskTextures,
  baseColor,
  kind,
  allowedSides,
  projectionSides,
  projectionBounds,
  directUv,
  transparent = false,
  displayMode = 'lit'
) {
  const arrays = sectionArrays(renderContract, kind, projectionBounds);
  const isGlass = kind === 'glass';
  const flatGlass = isGlass && glassMode === 'flat';
  const disableGlassLivery = isGlass && glassMode === 'off';
  const analysisOutput = displayMode === 'decal_alpha'
    ? `float value = decal.a;
        gl_FragColor = vec4(vec3(value), 1.0);`
    : displayMode === 'decal_luma'
      ? `float value = dot(decal.rgb, vec3(0.2126, 0.7152, 0.0722)) * decal.a;
        gl_FragColor = vec4(vec3(value), 1.0);`
      : displayMode === 'base_paint_mask'
        ? `float sectionMask = bestSlot >= 0 ? 1.0 : 0.0;
        float baseExposure = sectionMask * (1.0 - clamp(decal.a, 0.0, 1.0));
        gl_FragColor = vec4(baseColor * baseExposure, 1.0);`
      : '';
  const material = trackMaterial(new THREE.ShaderMaterial({
    uniforms: {
      paintMap: { value: paintTexture },
      maskMap0: { value: maskTextures[0] },
      maskMap1: { value: maskTextures[1] },
      maskMap2: { value: maskTextures[2] },
      sourceRegions: { value: arrays.sourceRegions },
      paintRegions: { value: arrays.paintRegions },
      sideFacing: { value: arrays.facings },
      enabledSlots: { value: arrays.present },
      meshAllowedSlots: { value: allowedSlotArray(allowedSides) },
      meshProjectionSlots: { value: allowedSlotArray(projectionSides) },
      projectionAxis: { value: arrays.projectionAxes },
      projectionMinimum: { value: arrays.projectionMinimum },
      projectionMaximum: { value: arrays.projectionMaximum },
      projectionMaskRegion: { value: arrays.projectionMaskRegions },
      useDirectUv: { value: directUv ? 1.0 : 0.0 },
      baseColor: { value: new THREE.Color(baseColor) },
      keyDirection: { value: new THREE.Vector3(0.45, 0.9, 0.55).normalize() },
      lo4GlassAlphaProfile: { value: (() => {
        const profile = glassOpacityProfileForEnvironment(environmentMode);
        return new THREE.Vector4(profile.front, profile.rear, profile.top, profile.side);
      })() },
      lo4GlassDefaultAlpha: { value: glassOpacityProfileForEnvironment(environmentMode).fallback },
      lo4WheelArchCenters: { value: wheelArchCutoutUniformData().centers },
      lo4WheelArchHalfWidths: { value: wheelArchCutoutUniformData().halfWidths },
      lo4WheelArchEnabled: { value: wheelArchCutoutUniformData().enabled },
    },
    vertexShader: `
      ${directUv ? 'attribute vec2 uv3;' : ''}
      varying vec2 atlasUv;
      varying vec3 worldNormalValue;
      varying vec3 worldPositionValue;
      void main() {
        atlasUv = ${directUv ? 'vec2(uv3.x * 0.5, uv3.y)' : 'vec2(0.0)'};
        vec4 worldPosition = modelMatrix * vec4(position, 1.0);
        worldPositionValue = worldPosition.xyz;
        worldNormalValue = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * viewMatrix * worldPosition;
      }
    `,
    fragmentShader: `
      uniform sampler2D paintMap;
      uniform sampler2D maskMap0;
      uniform sampler2D maskMap1;
      uniform sampler2D maskMap2;
      uniform vec4 sourceRegions[${SECTION_COUNT}];
      uniform vec4 paintRegions[${SECTION_COUNT}];
      uniform vec3 sideFacing[${SECTION_COUNT}];
      uniform float enabledSlots[${SECTION_COUNT}];
      uniform float meshAllowedSlots[${SECTION_COUNT}];
      uniform float meshProjectionSlots[${SECTION_COUNT}];
      uniform vec4 projectionAxis[${SECTION_COUNT}];
      uniform vec2 projectionMinimum[${SECTION_COUNT}];
      uniform vec2 projectionMaximum[${SECTION_COUNT}];
      uniform vec4 projectionMaskRegion[${SECTION_COUNT}];
      uniform float useDirectUv;
      uniform vec3 baseColor;
      uniform vec3 keyDirection;
      uniform vec4 lo4GlassAlphaProfile;
      uniform float lo4GlassDefaultAlpha;
      uniform vec4 lo4WheelArchCenters[4];
      uniform float lo4WheelArchHalfWidths[4];
      uniform int lo4WheelArchEnabled;
      varying vec2 atlasUv;
      varying vec3 worldNormalValue;
      varying vec3 worldPositionValue;

      float slotCoverage(int slot, vec4 page0, vec4 page1, vec4 page2) {
        if (slot == 0) return page0.r;
        if (slot == 1) return page0.g;
        if (slot == 2) return page0.b;
        if (slot == 3) return page0.a;
        if (slot == 4) return page1.r;
        if (slot == 5) return page1.g;
        if (slot == 6) return page1.b;
        if (slot == 7) return page1.a;
        if (slot == 8) return page2.r;
        if (slot == 9) return page2.g;
        return page2.b;
      }

      float axisComponent(vec3 value, float axis) {
        if (axis < 0.5) return value.x;
        if (axis < 1.5) return value.y;
        return value.z;
      }

      ${isGlass ? `float glassBaseAlpha(int slot) {
        ${flatGlass ? 'return 0.55;' : `
        if (slot == 6) return lo4GlassAlphaProfile.x;
        if (slot == 7) return lo4GlassAlphaProfile.y;
        if (slot == 8) return lo4GlassAlphaProfile.z;
        if (slot == 9 || slot == 10) return lo4GlassAlphaProfile.w;
        return lo4GlassDefaultAlpha;`}
      }` : ''}

      void main() {
        vec3 normalValue = normalize(worldNormalValue);
        float bestCoverage = 0.0;
        float bestFacing = -1.0;
        int bestSlot = -1;
        vec2 bestAtlasUv = atlasUv;
        ${directUv ? `vec4 directPage0 = texture2D(maskMap0, atlasUv);
        vec4 directPage1 = texture2D(maskMap1, atlasUv);
        vec4 directPage2 = texture2D(maskMap2, atlasUv);` : ''}
        for (int slot = 0; slot < ${SECTION_COUNT}; ++slot) {
          if (
            enabledSlots[slot] < 0.5
            || meshAllowedSlots[slot] < 0.5
            || dot(sideFacing[slot], normalValue) <= 0.0
          ) continue;
          vec2 candidateUv = atlasUv;
          if (useDirectUv < 0.5) {
            if (meshProjectionSlots[slot] < 0.5) continue;
            vec4 axis = projectionAxis[slot];
            vec2 minimum = projectionMinimum[slot];
            vec2 range = projectionMaximum[slot] - minimum;
            if (range.x <= 0.000001 || range.y <= 0.000001) continue;
            vec2 axisValue = vec2(
              axisComponent(worldPositionValue, axis.x) * axis.z,
              axisComponent(worldPositionValue, axis.y) * axis.w
            );
            vec2 normalized = (axisValue - minimum) / range;
            vec4 maskRegion = projectionMaskRegion[slot];
            candidateUv = vec2(
              mix(maskRegion.x, maskRegion.y, normalized.x),
              mix(maskRegion.z, maskRegion.w, normalized.y)
            );
          }
          if (
            candidateUv.x < 0.0 || candidateUv.x > 1.0
            || candidateUv.y < 0.0 || candidateUv.y > 1.0
          ) continue;
          vec4 page0 = ${directUv ? 'directPage0' : 'texture2D(maskMap0, candidateUv)'};
          vec4 page1 = ${directUv ? 'directPage1' : 'texture2D(maskMap1, candidateUv)'};
          vec4 page2 = ${directUv ? 'directPage2' : 'texture2D(maskMap2, candidateUv)'};
          float candidate = slotCoverage(slot, page0, page1, page2);
          if (candidate <= 0.5) continue;
          float facing = dot(sideFacing[slot], normalValue);
          bool better = useDirectUv >= 0.5
            ? candidate > bestCoverage
            : facing >= bestFacing;
          if (better) {
            bestCoverage = candidate;
            bestFacing = facing;
            bestSlot = slot;
            bestAtlasUv = candidateUv;
          }
        }

        vec4 decal = vec4(0.0);
        if (bestSlot >= 0 && bestCoverage > 0.5) {
          vec4 source = sourceRegions[bestSlot];
          vec2 sourceSize = source.zw - source.xy;
          if (sourceSize.x > 0.000001 && sourceSize.y > 0.000001) {
            vec2 sectionUv = clamp((bestAtlasUv - source.xy) / sourceSize, 0.0, 1.0);
            vec4 paint = paintRegions[bestSlot];
            vec2 paintUv = mix(paint.xy, paint.zw, sectionUv);
            decal = texture2D(paintMap, paintUv);
            decal.a *= bestCoverage;
          }
        }
        ${kind === 'body' ? `
        // r271：車体外板の裏面とGameDBで境界を定めたWheel開口内面は、
        // Paint／Liveryの受け面ではない。巻き方向の差に強いDoubleSideは維持しつつ、
        // 該当Fragmentを破棄してWheel Archから裏側の外板Paintが見えないようにする。
        if (!gl_FrontFacing) discard;
        for (int lo4Wheel = 0; lo4Wheel < 4; ++lo4Wheel) {
          if (lo4Wheel >= lo4WheelArchEnabled) break;
          vec4 arch = lo4WheelArchCenters[lo4Wheel];
          vec3 delta = worldPositionValue - arch.xyz;
          if (length(delta.yz) < arch.w && abs(delta.x) < lo4WheelArchHalfWidths[lo4Wheel]) discard;
        }` : ''}
        ${isGlass ? `
        if (!gl_FrontFacing || ${disableGlassLivery ? 'true' : 'false'}) {
          decal.a = 0.0;
        }` : ''}

        ${analysisOutput || `vec3 colorValue = mix(baseColor, decal.rgb, decal.a);
        float diffuse = 0.42 + 0.58 * max(dot(normalValue, keyDirection), 0.0);
        float edge = pow(
          1.0 - max(dot(normalValue, normalize(cameraPosition - worldPositionValue)), 0.0),
          3.0
        );
        vec3 lit = colorValue * diffuse + vec3(0.06, 0.11, 0.14) * edge;
        gl_FragColor = vec4(lit, ${isGlass ? 'mix(glassBaseAlpha(bestSlot), 1.0, decal.a)' : '1.0'});`}
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
    transparent,
    depthWrite: !transparent,
    side: THREE.DoubleSide,
  }));
  material.userData.lo4Uniforms = material.uniforms;
  return material;
}

function decalAlphaSectionAwareMaterial(
  paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides, projectionBounds, directUv, transparent = false
) {
  return sectionAwareMaterial(
    paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides,
    projectionBounds, directUv, transparent, 'decal_alpha'
  );
}

function decalLumaSectionAwareMaterial(
  paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides, projectionBounds, directUv, transparent = false
) {
  return sectionAwareMaterial(
    paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides,
    projectionBounds, directUv, transparent, 'decal_luma'
  );
}


function basePaintDirectSectionAwareMaterial(
  paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides, projectionBounds, directUv, transparent = false
) {
  const isGlass = kind === 'glass';
  const material = trackMaterial(new THREE.MeshBasicMaterial({
    color: isGlass ? 0x202a31 : baseColor,
    transparent: isGlass,
    opacity: isGlass ? 0.48 : 1.0,
    depthWrite: !isGlass,
    side: isGlass ? THREE.DoubleSide : THREE.FrontSide,
  }));
  material.userData.lo4MaterialMode = 'base-paint-direct-v2-body-frontside';
  return material;
}


function basePaintMaskSectionAwareMaterial(
  paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides, projectionBounds, directUv, transparent = false
) {
  return sectionAwareMaterial(
    paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides,
    projectionBounds, directUv, transparent, 'base_paint_mask'
  );
}

function liveryColorGradeForEnvironment(mode = environmentMode) {
  // 未承認の色味補正を既定で変えず、研究URLでは入力色補正の寄与のみ切り分ける。
  if (sourceLiveryNeutralResearch) return { saturation:1.0, brightness:1.0, contrast:1.0, warmChroma:1.0, warmDensity:1.0, pinkRedGain:1.0, pinkBlueGain:1.0 };
  return mode === 'home_soft'
    ? { saturation: 1.36, brightness: 1.00, contrast: 1.14, warmChroma: 1.22, warmDensity: 0.94, pinkRedGain: 0.96, pinkBlueGain: 1.08 }
    : { saturation: 1.0, brightness: 1.0, contrast: 1.0, warmChroma: 1.0, warmDensity: 1.0, pinkRedGain: 1.0, pinkBlueGain: 1.0 };
}

function glassOpacityProfileForEnvironment(mode = environmentMode) {
  return mode === 'home_soft'
    ? { front: 0.50, rear: 0.96, top: 0.96, side: 0.98, fallback: 0.96, baseColor: 0x0b1117 }
    : { front: 0.20, rear: 0.62, top: 0.70, side: 0.74, fallback: 0.68, baseColor: 0x202a31 };
}

function applyLiveryColorGrade() {
  const grade = liveryColorGradeForEnvironment(environmentMode);
  for (const material of [...paintMaterials, ...glassMaterials]) {
    const uniforms = material?.userData?.lo4Uniforms;
    if (!uniforms) continue;
    if (uniforms.lo4LiverySaturation) uniforms.lo4LiverySaturation.value = grade.saturation;
    if (uniforms.lo4LiveryBrightness) uniforms.lo4LiveryBrightness.value = grade.brightness;
    if (uniforms.lo4LiveryContrast) uniforms.lo4LiveryContrast.value = grade.contrast;
    if (uniforms.lo4LiveryWarmChroma) uniforms.lo4LiveryWarmChroma.value = grade.warmChroma;
    if (uniforms.lo4LiveryWarmDensity) uniforms.lo4LiveryWarmDensity.value = grade.warmDensity;
    if (uniforms.lo4LiveryPinkRedGain) uniforms.lo4LiveryPinkRedGain.value = grade.pinkRedGain;
    if (uniforms.lo4LiveryPinkBlueGain) uniforms.lo4LiveryPinkBlueGain.value = grade.pinkBlueGain;
    if (uniforms.lo4BaseClearcoatScale) {
      const materialScale = Number(material?.userData?.lo4BaseClearcoatScaleHomeSoft);
      const candidateScale = Number(basePaintViewerCandidate().base_clearcoat_scale_home_soft);
      uniforms.lo4BaseClearcoatScale.value = environmentMode === 'home_soft'
        ? (Number.isFinite(materialScale) ? materialScale : (Number.isFinite(candidateScale) ? candidateScale : 0.22))
        : 1.0;
    }
  }
}

function applyGlassOpacityProfile() {
  const profile = glassOpacityProfileForEnvironment(environmentMode);
  for (const material of glassMaterials) {
    const uniforms = material?.userData?.lo4Uniforms;
    if (!uniforms) continue;
    if (uniforms.lo4GlassAlphaProfile) {
      uniforms.lo4GlassAlphaProfile.value.set(profile.front, profile.rear, profile.top, profile.side);
    }
    if (uniforms.lo4GlassDefaultAlpha) uniforms.lo4GlassDefaultAlpha.value = profile.fallback;
    if (material?.color) material.color.setHex(profile.baseColor);
  }
}

function sectionAwarePbrMaterial(
  paintTexture,
  maskTextures,
  baseColor,
  kind,
  allowedSides,
  projectionSides,
  projectionBounds,
  directUv,
  transparent = false,
  profile = 'physical',
  sourceFinish = null
) {
  const arrays = sectionArrays(renderContract, kind, projectionBounds);
  const responseProbe = materialResponseProbe(profile);
  const sourceBoundPaint = profile === 'asset_routing' && kind === 'body' && sourceFinish
    ? researchSourceFinishCandidate(sourceFinish) : null;
  const baseCandidate = basePaintViewerCandidate(sourceBoundPaint || assetRoutingBasePaint());
  const candidateClearcoatScaleHomeSoft = Number(baseCandidate.base_clearcoat_scale_home_soft);
  const baseClearcoatScaleHomeSoft = Number.isFinite(Number(responseProbe.clearcoatScaleHomeSoft))
    ? Number(responseProbe.clearcoatScaleHomeSoft)
    : (Number.isFinite(candidateClearcoatScaleHomeSoft) ? candidateClearcoatScaleHomeSoft : 0.22);
  const uniforms = {
    paintMap: { value: paintTexture },
    maskMap0: { value: maskTextures[0] },
    maskMap1: { value: maskTextures[1] },
    maskMap2: { value: maskTextures[2] },
    sourceRegions: { value: arrays.sourceRegions },
    paintRegions: { value: arrays.paintRegions },
    sideFacing: { value: arrays.facings },
    enabledSlots: { value: arrays.present },
    meshAllowedSlots: { value: allowedSlotArray(allowedSides) },
    meshProjectionSlots: { value: allowedSlotArray(projectionSides) },
    projectionAxis: { value: arrays.projectionAxes },
    projectionMinimum: { value: arrays.projectionMinimum },
    projectionMaximum: { value: arrays.projectionMaximum },
    projectionMaskRegion: { value: arrays.projectionMaskRegions },
    useDirectUv: { value: directUv ? 1.0 : 0.0 },
    lo4LiverySaturation: { value: liveryColorGradeForEnvironment(environmentMode).saturation },
    lo4LiveryBrightness: { value: liveryColorGradeForEnvironment(environmentMode).brightness },
    lo4LiveryContrast: { value: liveryColorGradeForEnvironment(environmentMode).contrast },
    lo4LiveryWarmChroma: { value: liveryColorGradeForEnvironment(environmentMode).warmChroma },
    lo4LiveryWarmDensity: { value: liveryColorGradeForEnvironment(environmentMode).warmDensity },
    lo4LiveryPinkRedGain: { value: liveryColorGradeForEnvironment(environmentMode).pinkRedGain },
    lo4LiveryPinkBlueGain: { value: liveryColorGradeForEnvironment(environmentMode).pinkBlueGain },
    lo4BaseClearcoatScale: { value: environmentMode === 'home_soft' ? baseClearcoatScaleHomeSoft : 1.0 },
    lo4GlassAlphaProfile: { value: (() => {
      const profile = glassOpacityProfileForEnvironment(environmentMode);
      return new THREE.Vector4(profile.front, profile.rear, profile.top, profile.side);
    })() },
    lo4GlassDefaultAlpha: { value: glassOpacityProfileForEnvironment(environmentMode).fallback },
    lo4WheelArchCenters: { value: wheelArchCutoutUniformData().centers },
    lo4WheelArchHalfWidths: { value: wheelArchCutoutUniformData().halfWidths },
    lo4WheelArchEnabled: { value: wheelArchCutoutUniformData().enabled },
  };
  const isGlass = kind === 'glass';
  const assetRouting = isAssetRoutingMode(profile);
  const reflectionOnly = profile === 'reflection_only';
  const reflectionBoost = profile === 'reflection_boost';
  const physical = profile === 'physical' || assetRouting || reflectionOnly || reflectionBoost;
  const disableGlassLivery = isGlass && glassMode === 'off';
  const basePaint = (assetRouting || reflectionOnly || reflectionBoost) ? (sourceBoundPaint || assetRoutingBasePaint()) : {};
  const viewerCandidate = profile === 'asset_routing_r175_baseline'
    ? r175AutomotiveBaselineCandidate(basePaint)
    : basePaintViewerCandidate(basePaint);
  // 車体の塗装のラメの粒。部品ごとの仕上げでは、その部品の記録の第 2 色で描く（Car 2467・3953 など）。
  // 部品の記録が車体全体の塗装と別の仕上げ・色で、その仕上げを描けないときは、全体のラメを持ち込まない
  // （Car 4212 の羽根は仕上げ 1 の濃い灰色。全体の黒＋金色のラメを混ぜると金色になっていた）。
  const flakeLayer = assetRouting && kind === 'body'
    ? (sourceBoundPaint ? basePaintFlakeLayer(researchSourceFinishFlakeInput(sourceFinish))
      : (sourceFinishDiffersFromBasePaint(sourceFinish, basePaint) ? null : basePaintFlakeLayer(basePaint)))
    : null;
  uniforms.lo4FlakeColor = { value: flakeLayer ? flakeLayer.color : new THREE.Color(0, 0, 0) };
  uniforms.lo4FlakeFraction = { value: flakeLayer ? flakeLayer.fraction : 0.0 };
  uniforms.lo4FlakeStrength = { value: flakeLayer ? flakeLayer.strength : 0.0 };
  uniforms.lo4FlakeRoughness = { value: flakeLayer ? flakeLayer.roughness : 0.3 };
  uniforms.lo4FlakeDensity = { value: FLAKE_CELLS_PER_UNIT };
  uniforms.lo4FlakeTilt = { value: FLAKE_TILT };
  uniforms.lo4FlakeTint = { value: flakeLayer ? flakeLayer.tint : 0.0 };
  const assetBaseRoughness = Number.isFinite(Number(responseProbe.roughness))
    ? Number(responseProbe.roughness)
    : (Number.isFinite(Number(viewerCandidate.roughness)) ? Number(viewerCandidate.roughness) : 0.23);
  const assetIndirectSpecularScale = Number.isFinite(Number(responseProbe.iblScale)) ? Number(responseProbe.iblScale) : 1.0;
  const assetBaseMetalness = Number.isFinite(Number(viewerCandidate.metalness)) ? Number(viewerCandidate.metalness) : 0.06;
  const assetEnvMapIntensity = Number.isFinite(Number(viewerCandidate.env_map_intensity)) ? Number(viewerCandidate.env_map_intensity) : 1.32;
  const assetShaderFamily = String(basePaint?.shader_family || '').toLowerCase();
  const assetAutomotivePaint = [
    'car_automotive_paint', 'car_automotive_paint_user',
    'car_candy_paint', 'car_candy_paint_user',
    'car_glitter_paint', 'car_glitter_paint_user',
  ].includes(assetShaderFamily);
  const assetAutomotiveBaselineCandidate = assetAutomotivePaint ? r175AutomotiveBaselineCandidate(basePaint) : viewerCandidate;
  const assetAutomotiveBaselineEnvMapIntensity = Number.isFinite(Number(assetAutomotiveBaselineCandidate.env_map_intensity))
    ? Number(assetAutomotiveBaselineCandidate.env_map_intensity) : assetEnvMapIntensity;
  // r180：MeshStandard／PhysicalMaterialのenvMapIntensityは材質全体に作用する。
  // r176でFlakeの確認用に上げた結果、Livery画素の反射まで明るくなった。
  // 材質全体の基準値は維持し、r176の増分だけを露出Baseの間接鏡面反射へ移す。
  const assetLocalizedAutomotiveResponse = assetRouting && assetAutomotivePaint && profile !== 'asset_routing_r175_baseline';
  const assetMaterialEnvMapIntensity = assetLocalizedAutomotiveResponse
    ? assetAutomotiveBaselineEnvMapIntensity : assetEnvMapIntensity;
  const assetBaseExposureEnvScale = assetLocalizedAutomotiveResponse && assetAutomotiveBaselineEnvMapIntensity > 0.000001
    ? Math.max(0.5, Math.min(1.5, assetEnvMapIntensity / assetAutomotiveBaselineEnvMapIntensity))
    : 1.0;
  const assetClearcoat = Number.isFinite(Number(viewerCandidate.clearcoat)) ? Number(viewerCandidate.clearcoat) : 1.0;
  const assetClearcoatRoughness = Number.isFinite(Number(viewerCandidate.clearcoat_roughness)) ? Number(viewerCandidate.clearcoat_roughness) : 0.0;
  const assetFlakeResponseStrength = Number.isFinite(Number(viewerCandidate.flake_response_strength))
    ? Math.max(0.0, Math.min(1.0, Number(viewerCandidate.flake_response_strength))) : 0.0;
  const assetGlancingResponseStrength = Number.isFinite(Number(viewerCandidate.glancing_response_strength))
    ? Math.max(0.0, Math.min(0.35, Number(viewerCandidate.glancing_response_strength))) : 0.0;
  const assetGlancingFlopPower = Number.isFinite(Number(viewerCandidate.glancing_flop_power))
    ? Math.max(0.25, Math.min(8.0, Number(viewerCandidate.glancing_flop_power))) : 2.0;
  // Brushed法線をGlitterの元材質へ無断で流用しない。
  // 異なるShader familyに旧normalMapを流用しない。
  const detailNormalTexture = sourceBoundPaint && sourceBoundPaint.shader_family !== 'car_standard_user'
    ? null : detailNormalTextureForProfile(profile);
  const baseSettings = reflectionOnly
    ? {
        roughness: isGlass ? 0.06 : 0.015,
        metalness: isGlass ? 0.0 : Math.max(assetBaseMetalness, 0.72),
        envMapIntensity: isGlass ? 1.45 : 2.85,
      }
    : reflectionBoost
      ? {
          roughness: isGlass ? 0.07 : Math.min(assetBaseRoughness, 0.035),
          metalness: isGlass ? 0.0 : Math.max(assetBaseMetalness, 0.35),
          envMapIntensity: isGlass ? 1.28 : 2.1,
        }
      : physical
        ? {
            roughness: isGlass ? 0.16 : (assetRouting ? assetBaseRoughness : 0.23),
            metalness: isGlass ? 0.0 : (assetRouting ? assetBaseMetalness : 0.06),
            envMapIntensity: isGlass ? 1.05 : (assetRouting ? assetMaterialEnvMapIntensity : 1.32),
          }
        : {
            roughness: isGlass ? 0.22 : 0.38,
            metalness: isGlass ? 0.0 : 0.04,
            envMapIntensity: isGlass ? 0.38 : 0.48,
          };
  const constructor = physical ? THREE.MeshPhysicalMaterial : THREE.MeshStandardMaterial;
  // 上塗りの有無でシェーダーを分けない（2026-11-20）。three.js は clearcoat > 0 かどうかで別のシェーダーにするので、
  // 資源の割り当ての車体（ガラスでない）は、上塗りの無い仕上げでも three.js へは 0 より大きい値を渡し、シェーダーの中で
  // lo4ClearcoatEnabled（0 か 1）を掛けて強さを 0 にする。強さ 0 の上塗りの計算は「上塗り無し」と同じ値になる
  // （outgoingLight × (1 − 0 × Fcc) + 上塗りの映り込み × 0）。仕上げの違う新しいペイントのたびに作り直していた。
  const intendedClearcoat = isGlass ? 0.72 : (assetRouting ? assetClearcoat : 1.0);
  const unifiedClearcoat = physical && assetRouting && !isGlass;
  uniforms.lo4ClearcoatEnabled = { value: unifiedClearcoat && !(intendedClearcoat > 0) ? 0.0 : 1.0 };
  // 細かい凹凸の有無でシェーダーを分けない（2026-11-20）。three.js は normalMap の有無で別のシェーダーにするので、
  // 資源の割り当ての材質（ガラスでない）には、凹凸の無いペイントでも平らなテクスチャを渡し、シェーダーの中で
  // lo4DetailNormalEnabled（0 か 1）で凹凸の塊を飛ばす（法線は凹凸の前のまま＝以前の「normalMap 無し」と同じ値）。
  // カーボンの地の塗装のペイントへ差し替えるたびに、シェーダーを作り直していた。凹凸の UV の番号が 1 のときは、
  // three.js の側で今までどおり別のシェーダーになる（平らなテクスチャは番号 0）。
  const detailNormalSlot = assetRouting && !isGlass;
  uniforms.lo4DetailNormalEnabled = { value: detailNormalSlot && detailNormalTexture ? 1.0 : 0.0 };
  const material = trackMaterial(new constructor({
    color: baseColor,
    roughness: baseSettings.roughness,
    metalness: baseSettings.metalness,
    envMapIntensity: baseSettings.envMapIntensity,
    ...(detailNormalSlot ? {
      normalMap: detailNormalTexture || flatDetailNormal(),
      normalScale: new THREE.Vector2(1.0, 1.0),
    } : {}),
    transparent,
    opacity: 1.0,
    depthWrite: !transparent,
    side: THREE.DoubleSide,
    ...(physical ? {
      clearcoat: unifiedClearcoat && !(intendedClearcoat > 0) ? 1.0 : intendedClearcoat,
      clearcoatRoughness: isGlass ? 0.08 : ((reflectionBoost || reflectionOnly) ? 0.0 : (assetRouting ? assetClearcoatRoughness : 0.11)),
    } : {}),
  }));
  const shaderConstant = value => Number(Number(value).toFixed(6));
  uniforms.lo4ConstBaseRoughness = { value: shaderConstant(assetBaseRoughness) };
  uniforms.lo4ConstBaseMetalness = { value: shaderConstant(assetBaseMetalness) };
  uniforms.lo4ConstIndirectScale = { value: shaderConstant(assetIndirectSpecularScale * assetBaseExposureEnvScale) };
  uniforms.lo4ConstGlancingFlopPower = { value: shaderConstant(assetGlancingFlopPower) };
  uniforms.lo4ConstGlancingResponse = { value: shaderConstant(assetGlancingResponseStrength) };
  uniforms.lo4ConstFlakeResponse = { value: shaderConstant(assetFlakeResponseStrength) };
  const automotiveLightBlock = assetIndirectSpecularScale !== 1.0 || assetBaseExposureEnvScale !== 1.0
    || assetGlancingResponseStrength > 0.0 || assetFlakeResponseStrength > 0.0;
  // 粒と照明のブロックを使うかは uniform で渡す（2026-11-20）。シェーダーの文には両方の塊を常に入れ、使わない材質は
  // uniform の条件で塊を飛ばす（以前の「塊を入れない」と同じ計算になる）。ペイントの仕上げごとに別のシェーダーを
  // 作り直していた（新しいペイントの差し替えで 1 つ 300〜450 ms）。
  uniforms.lo4FlakeEnabled = { value: flakeLayer ? 1.0 : 0.0 };
  uniforms.lo4AutomotiveLight = { value: automotiveLightBlock ? 1.0 : 0.0 };
  material.userData.lo4Uniforms = uniforms;
  material.userData.lo4BaseClearcoatScaleHomeSoft = baseClearcoatScaleHomeSoft;
  material.userData.lo4MaterialMode = `${profile}-section-aware-v2`;
  // 塗装の仕上げの数値（地の塗装・部品の仕上げでペイントごとに変わる）は、シェーダーの文に埋め込まず uniform で
  // 渡す（2026-11-20、FH6 に近づける案 ③）。以前は文に埋め込んだため数値ごとに別のシェーダーになり、新しいペイント
  // のたびにシェーダーを作り直していた（0.15〜0.35 秒）。uniform の値は、以前の文の数値と同じく小数 6 桁に丸めて
  // から渡す（GLSL が文の数値を読んだときと同じ float の値になる）。Three.js は鍵が同じならシェーダーを共有し、
  // uniform は材質ごとに持つ。鍵には、シェーダーの文の形を変えるもの（反射の強さのブロックを入れるか）だけを入れる。
  // 2026-11-20：粒と照明のブロックは uniform にしたので鍵から外した。細かい凹凸の塊と法線のテクスチャは、資源の割り当て
  // でガラスでないときに常に入れ、有無は uniform で渡す（v10）。
  material.customProgramCacheKey = () => `lo4fh6-${profile}-v10:${kind}:${directUv ? 1 : 0}:${glassMode}:${detailNormalSlot ? 1 : 0}`;
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader.replace(
      '#include <common>',
      `#include <common>
      ${directUv ? 'attribute vec2 uv3;' : ''}
      varying vec2 lo4AtlasUv;
      varying vec3 lo4WorldNormal;
      varying vec3 lo4WorldPosition;`
    ).replace(
      '#include <worldpos_vertex>',
      `#include <worldpos_vertex>
      lo4AtlasUv = ${directUv ? 'vec2(uv3.x * 0.5, uv3.y)' : 'vec2(0.0)'};
      lo4WorldPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;
      lo4WorldNormal = normalize(mat3(modelMatrix) * normal);`
    );
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <common>',
      `#include <common>
      uniform sampler2D paintMap;
      uniform float lo4ConstBaseRoughness;
      uniform float lo4ConstBaseMetalness;
      uniform float lo4ConstIndirectScale;
      uniform float lo4ConstGlancingFlopPower;
      uniform float lo4ConstGlancingResponse;
      uniform float lo4ConstFlakeResponse;
      uniform float lo4FlakeEnabled;
      uniform float lo4AutomotiveLight;
      uniform float lo4ClearcoatEnabled;
      uniform float lo4DetailNormalEnabled;
      uniform sampler2D maskMap0;
      uniform sampler2D maskMap1;
      uniform sampler2D maskMap2;
      uniform vec4 sourceRegions[${SECTION_COUNT}];
      uniform vec4 paintRegions[${SECTION_COUNT}];
      uniform vec3 sideFacing[${SECTION_COUNT}];
      uniform float enabledSlots[${SECTION_COUNT}];
      uniform float meshAllowedSlots[${SECTION_COUNT}];
      uniform float meshProjectionSlots[${SECTION_COUNT}];
      uniform vec4 projectionAxis[${SECTION_COUNT}];
      uniform vec2 projectionMinimum[${SECTION_COUNT}];
      uniform vec2 projectionMaximum[${SECTION_COUNT}];
      uniform vec4 projectionMaskRegion[${SECTION_COUNT}];
      uniform float useDirectUv;
      uniform float lo4LiverySaturation;
      uniform float lo4LiveryBrightness;
      uniform float lo4LiveryContrast;
      uniform float lo4LiveryWarmChroma;
      uniform float lo4LiveryWarmDensity;
      uniform float lo4LiveryPinkRedGain;
      uniform float lo4LiveryPinkBlueGain;
      uniform float lo4BaseClearcoatScale;
      uniform vec3 lo4FlakeColor;
      uniform float lo4FlakeFraction;
      uniform float lo4FlakeStrength;
      uniform float lo4FlakeRoughness;
      uniform float lo4FlakeDensity;
      uniform float lo4FlakeTilt;
      uniform float lo4FlakeTint;
      float lo4FlakeHash(vec3 p) {
        p = fract(p * 0.1031);
        p += dot(p, p.zyx + 31.32);
        return fract((p.x + p.y) * p.z);
      }
      uniform vec4 lo4GlassAlphaProfile;
      uniform float lo4GlassDefaultAlpha;
      uniform vec4 lo4WheelArchCenters[4];
      uniform float lo4WheelArchHalfWidths[4];
      uniform int lo4WheelArchEnabled;
      varying vec2 lo4AtlasUv;
      varying vec3 lo4WorldNormal;
      varying vec3 lo4WorldPosition;
      float lo4LiveryCoverage = 0.0;
      float lo4HasSelectedSlot = 0.0;

      float lo4SlotCoverage(int slot, vec4 page0, vec4 page1, vec4 page2) {
        if (slot == 0) return page0.r;
        if (slot == 1) return page0.g;
        if (slot == 2) return page0.b;
        if (slot == 3) return page0.a;
        if (slot == 4) return page1.r;
        if (slot == 5) return page1.g;
        if (slot == 6) return page1.b;
        if (slot == 7) return page1.a;
        if (slot == 8) return page2.r;
        if (slot == 9) return page2.g;
        return page2.b;
      }

      float lo4AxisComponent(vec3 value, float axis) {
        if (axis < 0.5) return value.x;
        if (axis < 1.5) return value.y;
        return value.z;
      }

      ${isGlass ? `float lo4GlassBaseAlpha(float slot) {
        if (slot > 5.5 && slot < 6.5) return lo4GlassAlphaProfile.x;
        if (slot > 6.5 && slot < 7.5) return lo4GlassAlphaProfile.y;
        if (slot > 7.5 && slot < 8.5) return lo4GlassAlphaProfile.z;
        if (slot > 8.5 && slot < 10.5) return lo4GlassAlphaProfile.w;
        return lo4GlassDefaultAlpha;
      }` : ''}

      vec4 lo4SampleLivery(vec3 normalValue, vec3 worldPositionValue, out float selectedSlot) {
        float bestCoverage = 0.0;
        float bestFacing = -1.0;
        int bestSlot = -1;
        vec2 bestAtlasUv = lo4AtlasUv;
        ${directUv ? `vec4 directPage0 = texture2D(maskMap0, lo4AtlasUv);
        vec4 directPage1 = texture2D(maskMap1, lo4AtlasUv);
        vec4 directPage2 = texture2D(maskMap2, lo4AtlasUv);` : ''}
        for (int slot = 0; slot < ${SECTION_COUNT}; ++slot) {
          if (
            enabledSlots[slot] < 0.5
            || meshAllowedSlots[slot] < 0.5
            || dot(sideFacing[slot], normalValue) <= 0.0
          ) continue;
          vec2 candidateUv = lo4AtlasUv;
          if (useDirectUv < 0.5) {
            if (meshProjectionSlots[slot] < 0.5) continue;
            vec4 axis = projectionAxis[slot];
            vec2 minimum = projectionMinimum[slot];
            vec2 range = projectionMaximum[slot] - minimum;
            if (range.x <= 0.000001 || range.y <= 0.000001) continue;
            vec2 axisValue = vec2(
              lo4AxisComponent(worldPositionValue, axis.x) * axis.z,
              lo4AxisComponent(worldPositionValue, axis.y) * axis.w
            );
            vec2 normalized = (axisValue - minimum) / range;
            vec4 maskRegion = projectionMaskRegion[slot];
            candidateUv = vec2(
              mix(maskRegion.x, maskRegion.y, normalized.x),
              mix(maskRegion.z, maskRegion.w, normalized.y)
            );
          }
          if (
            candidateUv.x < 0.0 || candidateUv.x > 1.0
            || candidateUv.y < 0.0 || candidateUv.y > 1.0
          ) continue;
          vec4 page0 = ${directUv ? 'directPage0' : 'texture2D(maskMap0, candidateUv)'};
          vec4 page1 = ${directUv ? 'directPage1' : 'texture2D(maskMap1, candidateUv)'};
          vec4 page2 = ${directUv ? 'directPage2' : 'texture2D(maskMap2, candidateUv)'};
          float candidate = lo4SlotCoverage(slot, page0, page1, page2);
          if (candidate <= 0.5) continue;
          float facing = dot(sideFacing[slot], normalValue);
          bool better = useDirectUv >= 0.5
            ? candidate > bestCoverage
            : facing >= bestFacing;
          if (better) {
            bestCoverage = candidate;
            bestFacing = facing;
            bestSlot = slot;
            bestAtlasUv = candidateUv;
          }
        }
        selectedSlot = float(bestSlot);
        vec4 decal = vec4(0.0);
        if (bestSlot >= 0 && bestCoverage > 0.5) {
          vec4 source = sourceRegions[bestSlot];
          vec2 sourceSize = source.zw - source.xy;
          if (sourceSize.x > 0.000001 && sourceSize.y > 0.000001) {
            vec2 sectionUv = clamp((bestAtlasUv - source.xy) / sourceSize, 0.0, 1.0);
            vec4 paint = paintRegions[bestSlot];
            vec2 paintUv = mix(paint.xy, paint.zw, sectionUv);
            decal = texture2D(paintMap, paintUv);
            // r104：Horizon Home Softの表示調整。原本Atlasは変更せず、
            // 線形光空間でのViewer表示補正のみを行う。
            // r100は中立黒のコントラストを確立。r101は彩度に応じて暖色・ピンクを強調。
            // r102はXbox参照の花弁・髪・肌の彩度と金属的な余白反射、
            // 側窓の透過度を踏まえて強調値を再調整した研究履歴。
            float lo4LiveryLuma = dot(decal.rgb, vec3(0.2126, 0.7152, 0.0722));
            float lo4LiveryChroma = max(max(decal.r, decal.g), decal.b) - min(min(decal.r, decal.g), decal.b);
            float lo4WarmBias = max(decal.r - decal.g, min(decal.r, decal.b) - decal.g);
            float lo4WarmWeight = smoothstep(0.015, 0.20, lo4WarmBias) * smoothstep(0.02, 0.32, lo4LiveryChroma);
            float lo4AdaptiveSaturation = lo4LiverySaturation * mix(1.0, lo4LiveryWarmChroma, lo4WarmWeight);
            vec3 lo4LiveryColor = mix(vec3(lo4LiveryLuma), decal.rgb, lo4AdaptiveSaturation);
            lo4LiveryColor = (lo4LiveryColor - vec3(0.5)) * lo4LiveryContrast + vec3(0.5);
            // r104：r103の彩度を維持し、高彩度ピンクをXbox参照の暗めの赤紫へ寄せる。
            // 高彩度の暖色画素に限り赤を少し抑えて青を増やし、
            // 肌・中立白・黒への影響を極力避ける。
            float lo4PinkWeight = lo4WarmWeight * smoothstep(0.05, 0.28, lo4LiveryChroma);
            lo4LiveryColor *= mix(1.0, lo4LiveryWarmDensity, lo4WarmWeight);
            lo4LiveryColor.r *= mix(1.0, lo4LiveryPinkRedGain, lo4PinkWeight);
            lo4LiveryColor.b *= mix(1.0, lo4LiveryPinkBlueGain, lo4PinkWeight);
            // r277：Home Softの調整を強くする前に原作者の暗部色を保全する。
            // 旧線形光のコントラスト基準0.5では暗い暖色・中立色が黒や赤寄りに潰れ、
            // FH6原本にある金色・オリーブ色の区別が失われ得た。
            // 深い暗部は原本のままとし、中間調でのみr104の表示調整へ移行する。
            float lo4LiveryGradeStrength = smoothstep(0.055, 0.20, lo4LiveryLuma);
            vec3 lo4LiveryGraded = clamp(lo4LiveryColor * lo4LiveryBrightness, 0.0, 1.0);
            decal.rgb = mix(decal.rgb, lo4LiveryGraded, lo4LiveryGradeStrength);
            decal.a *= bestCoverage;
          }
        }
        return decal;
      }`
    ).replace(
      '#include <map_fragment>',
      `#include <map_fragment>
      ${kind === 'body' ? `// r271: reject exterior body backfaces and GameDB-bounded wheel-opening interiors while retaining DoubleSide
      // 巻き方向への耐性を保つラスタライズ処理。
      // Wheel Archから裏面の外板Base Paint／Liveryが露出するのを防ぐ。
      if (!gl_FrontFacing) discard;
      for (int lo4Wheel = 0; lo4Wheel < 4; ++lo4Wheel) {
        if (lo4Wheel >= lo4WheelArchEnabled) break;
        vec4 arch = lo4WheelArchCenters[lo4Wheel];
        vec3 delta = lo4WorldPosition - arch.xyz;
        if (length(delta.yz) < arch.w && abs(delta.x) < lo4WheelArchHalfWidths[lo4Wheel]) discard;
      }` : ''}
      float lo4SelectedSlot = -1.0;
      vec4 lo4Decal = lo4SampleLivery(normalize(lo4WorldNormal), lo4WorldPosition, lo4SelectedSlot);
      ${isGlass ? `if (!gl_FrontFacing || ${disableGlassLivery ? 'true' : 'false'}) lo4Decal.a = 0.0;` : ''}
      lo4LiveryCoverage = clamp(lo4Decal.a, 0.0, 1.0);
      lo4HasSelectedSlot = lo4SelectedSlot >= 0.0 ? 1.0 : 0.0;
      ${assetRouting && kind === 'body' ? '// ラメの細かい粒の平均の色を地の色に混ぜる（ステッカーの下）。粒を使わない材質は飛ばす。\n      if (lo4FlakeEnabled > 0.5) diffuseColor.rgb = mix(diffuseColor.rgb, lo4FlakeColor, lo4FlakeTint);' : ''}
      diffuseColor.rgb = mix(diffuseColor.rgb, lo4Decal.rgb, lo4Decal.a);
      ${reflectionOnly && !isGlass ? 'diffuseColor.rgb = vec3(0.0);' : ''}
      ${isGlass ? 'diffuseColor.a = mix(lo4GlassBaseAlpha(lo4SelectedSlot), 1.0, lo4Decal.a);' : ''}`
    );
    if (detailNormalSlot) {
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <normal_fragment_maps>',
        `vec3 lo4NormalBeforeDetail = normal;
        // 凹凸の無いペイント（平らなテクスチャを渡している）は塊を飛ばす（法線は凹凸の前のまま。2026-11-20）。
        if (lo4DetailNormalEnabled > 0.5) {
          #include <normal_fragment_maps>
          // r183：実行時のDetail Normalは露出したBase材質を表す。
          // Liveryで覆われた画素は幾何Normalを使い、
          // Carbon／Brushedの模様が不透明Vinylに透けて現れないようにする。
          float lo4DetailNormalExposure = lo4HasSelectedSlot * (1.0 - lo4LiveryCoverage);
          normal = normalize(mix(lo4NormalBeforeDetail, normal, lo4DetailNormalExposure));
        }`
      );
    }
    if (assetRouting && !isGlass) {
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <lights_physical_fragment>',
        `#include <lights_physical_fragment>
        #ifdef USE_CLEARCOAT
          // r104：AluminumPolishedはRoughness=0、Metalness=1へ既に解決される。
          // r102のRoughness／Metalness下限・上限は対象参照に影響しなかった。
          // 選択面の露出Base Paintだけで白い非金属Clearcoatを減らし、
          // 下地の金属ピンク反射を優先する。
          float lo4BasePaintExposure = lo4HasSelectedSlot * (1.0 - lo4LiveryCoverage);
          material.clearcoat *= mix(1.0, lo4BaseClearcoatScale, lo4BasePaintExposure);
          // 上塗りの無い仕上げは強さを 0 にする（three.js には 0 より大きい値を渡している。2026-11-20）。
          material.clearcoat *= lo4ClearcoatEnabled;
        #endif`
      ).replace(
        '#include <roughnessmap_fragment>',
        `#include <roughnessmap_fragment>
        // r56：原本Assetの割当研究。
        // 証拠付き候補がある場合、Baseの応答をGameDBで解決したPaint材質から取得する。
        // FH6原本にはLivery RMAOのR=254/255、Roughness_Shift=-0.85がある。
        float lo4AssetBaseRoughness = lo4ConstBaseRoughness;
        float lo4AssetLiveryRoughness = clamp((254.0 / 255.0) - 0.85, 0.0, 1.0);
        roughnessFactor = mix(lo4AssetBaseRoughness, lo4AssetLiveryRoughness, lo4LiveryCoverage);`
      ).replace(
        '#include <metalnessmap_fragment>',
        `#include <metalnessmap_fragment>
        // The shipped paint-livery RMAO G channel is 0: dielectric candidate.
        float lo4AssetBaseMetalness = lo4ConstBaseMetalness;
        metalnessFactor = mix(lo4AssetBaseMetalness, 0.0, lo4LiveryCoverage);`
      );
      {
        // 照明のブロックは常に文に入れ、使わない材質は uniform の条件で飛ばす（2026-11-20）。塊が使う
        // lo4BasePaintExposure は上塗りがあるときだけ宣言されるので、上塗りがあるときだけ入れる。
        shader.fragmentShader = shader.fragmentShader.replace(
          '#include <lights_fragment_end>',
          `#include <lights_fragment_end>
          #ifdef USE_CLEARCOAT
          if (lo4AutomotiveLight > 0.5) {
          // r180：r176の車体材質応答の増分は露出Base Paintだけに適用する。
          // 材質全体のenvMapIntensityはr175の基準値を保つ。
          // r176のFlake増分は既存のProbe／斜角反射補正と併せ、
          // 以下の範囲制限付きBase専用倍率で表し、Livery画素には作用させない。
          float lo4IndirectScale = mix(1.0, lo4ConstIndirectScale, lo4BasePaintExposure);
          float lo4NdotV = clamp(dot(normalize(geometryNormal), normalize(geometryViewDir)), 0.0, 1.0);
          float lo4GlancingTerm = pow(max(1.0 - lo4NdotV, 0.0), lo4ConstGlancingFlopPower);
          float lo4AutomotiveLift = lo4ConstGlancingResponse * lo4GlancingTerm
            + lo4ConstFlakeResponse * 0.035 * lo4GlancingTerm;
          reflectedLight.indirectSpecular *= lo4IndirectScale * (1.0 + lo4AutomotiveLift * lo4BasePaintExposure);
          }
          #endif`
        );
      }
      if (kind === 'body') {
        // 粒の塊は車体なら常に文に入れ、粒を使わない材質は uniform の条件で飛ばす（2026-11-20）。
        shader.fragmentShader = shader.fragmentShader.replace(
          '#include <aomap_fragment>',
          `#ifdef USE_ENVMAP
          if (lo4FlakeEnabled > 0.5) {
            // ラメの粒：升ごとに粒かどうかと向きを決め、粒の向きで環境の映り込みを足す。
            vec3 lo4FlakeCell = lo4WorldPosition * lo4FlakeDensity;
            vec3 lo4FlakeId = floor(lo4FlakeCell);
            float lo4FlakeFootprint = length(fwidth(lo4FlakeCell));
            float lo4FlakeDetail = 1.0 - smoothstep(0.6, 1.6, lo4FlakeFootprint);
            float lo4FlakeHere = step(lo4FlakeHash(lo4FlakeId), lo4FlakeFraction);
            vec3 lo4FlakeJitter = vec3(
              lo4FlakeHash(lo4FlakeId + 17.17),
              lo4FlakeHash(lo4FlakeId + 41.41),
              lo4FlakeHash(lo4FlakeId + 73.73)) - 0.5;
            vec3 lo4FlakeNormal = normalize(geometryNormal + lo4FlakeJitter * lo4FlakeTilt);
            vec3 lo4FlakeSharp = getIBLRadiance(geometryViewDir, lo4FlakeNormal, lo4FlakeRoughness);
            vec3 lo4FlakeAverage = getIBLRadiance(geometryViewDir, geometryNormal, min(1.0, lo4FlakeRoughness + 0.45));
            vec3 lo4FlakeRadiance = mix(lo4FlakeAverage * lo4FlakeFraction, lo4FlakeSharp * lo4FlakeHere, lo4FlakeDetail);
            // 光る粒は塗装が見えている割合だけ（ペイントで覆われた所は光らない。2026-11-19、Car 2542・3735・3051 の黒い車体）。
            float lo4FlakeExposure = 1.0 - lo4HasSelectedSlot * lo4LiveryCoverage;
            reflectedLight.indirectSpecular += lo4FlakeColor * lo4FlakeRadiance * lo4FlakeStrength * lo4FlakeExposure;
          }
          #endif
          #include <aomap_fragment>`
        );
      }
    }
    if ((reflectionOnly || reflectionBoost) && !isGlass) {
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <roughnessmap_fragment>',
        `#include <roughnessmap_fragment>
        // 反射診断では露出Baseの反射を強調し、Livery被覆画素は抑える。
        // 図柄の余白の反射状態を見分けやすくするための表示である。
        float lo4AssetBaseRoughness = lo4ConstBaseRoughness;
        float lo4AssetLiveryRoughness = clamp((254.0 / 255.0) - 0.85, 0.0, 1.0);
        float lo4RoughnessBaseExposure = lo4HasSelectedSlot * (1.0 - lo4LiveryCoverage);
        ${reflectionOnly
          ? 'roughnessFactor = mix(1.0, 0.015, lo4RoughnessBaseExposure);'
          : 'roughnessFactor = mix(lo4AssetLiveryRoughness, min(lo4AssetBaseRoughness, 0.035), lo4RoughnessBaseExposure);'}`
      ).replace(
        '#include <metalnessmap_fragment>',
        `#include <metalnessmap_fragment>
        float lo4AssetBaseMetalness = lo4ConstBaseMetalness;
        float lo4MetalnessBaseExposure = lo4HasSelectedSlot * (1.0 - lo4LiveryCoverage);
        ${reflectionOnly
          ? 'metalnessFactor = mix(0.0, max(lo4AssetBaseMetalness, 0.72), lo4MetalnessBaseExposure);'
          : 'metalnessFactor = mix(0.0, max(lo4AssetBaseMetalness, 0.35), lo4MetalnessBaseExposure);'}`
      );
    }
    material.userData.lo4CompiledShader = shader;
  };
  return material;
}

function basicSectionAwareMaterial(
  paintTexture,
  maskTextures,
  baseColor,
  kind,
  allowedSides,
  projectionSides,
  projectionBounds,
  directUv,
  transparent = false
) {
  return sectionAwarePbrMaterial(
    paintTexture,
    maskTextures,
    baseColor,
    kind,
    allowedSides,
    projectionSides,
    projectionBounds,
    directUv,
    transparent,
    'basic'
  );
}

function physicalSectionAwareMaterial(
  paintTexture,
  maskTextures,
  baseColor,
  kind,
  allowedSides,
  projectionSides,
  projectionBounds,
  directUv,
  transparent = false
) {
  return sectionAwarePbrMaterial(
    paintTexture,
    maskTextures,
    baseColor,
    kind,
    allowedSides,
    projectionSides,
    projectionBounds,
    directUv,
    transparent,
    'physical'
  );
}

function assetRoutingSectionAwareMaterial(
  paintTexture,
  maskTextures,
  baseColor,
  kind,
  allowedSides,
  projectionSides,
  projectionBounds,
  directUv,
  transparent = false,
  sourceFinish = null
) {
  return sectionAwarePbrMaterial(
    paintTexture,
    maskTextures,
    baseColor,
    kind,
    allowedSides,
    projectionSides,
    projectionBounds,
    directUv,
    transparent,
    'asset_routing',
    sourceFinish
  );
}

function assetRoutingProbeSectionAwareMaterial(profile, paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides, projectionBounds, directUv, transparent = false) {
  return sectionAwarePbrMaterial(
    paintTexture, maskTextures, baseColor, kind, allowedSides, projectionSides,
    projectionBounds, directUv, transparent, profile
  );
}

function assetRoutingR175BaselineSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('asset_routing_r175_baseline', ...args);
}

function carbonDetailUv0ProbeSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('carbon_detail_uv0_probe', ...args);
}

function carbonDetailUv1ProbeSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('carbon_detail_uv1_probe', ...args);
}

function carbonDetailTextureProbeSectionAwareMaterial(profile, _paintTexture, _maskTextures, _baseColor, kind, _allowedSides, _projectionSides, _projectionBounds, _directUv, transparent = false) {
  const texture = kind === 'body' ? detailNormalTextureForProfile(profile) : null;
  const material = trackMaterial(new THREE.MeshBasicMaterial({
    color: texture ? 0xffffff : (kind === 'glass' ? 0x202a31 : 0x24282d),
    map: texture,
    transparent: kind === 'glass' || transparent,
    opacity: kind === 'glass' ? 0.42 : 1.0,
    depthWrite: kind !== 'glass' && !transparent,
    side: THREE.DoubleSide,
    toneMapped: false,
  }));
  material.userData.lo4MaterialMode = `${profile}-raw-normal-texture`;
  return material;
}

function carbonDetailTextureUv0ProbeSectionAwareMaterial(...args) {
  return carbonDetailTextureProbeSectionAwareMaterial('carbon_detail_texture_uv0_probe', ...args);
}

function carbonDetailTextureUv1ProbeSectionAwareMaterial(...args) {
  return carbonDetailTextureProbeSectionAwareMaterial('carbon_detail_texture_uv1_probe', ...args);
}

function carbonMaskTextureProbeSectionAwareMaterial(profile, _paintTexture, _maskTextures, _baseColor, kind, _allowedSides, _projectionSides, _projectionBounds, _directUv, transparent = false) {
  const texture = kind === 'body' ? detailMaskTextureForProfile(profile) : null;
  const material = trackMaterial(new THREE.MeshBasicMaterial({
    color: texture ? 0xffffff : (kind === 'glass' ? 0x202a31 : 0x24282d),
    map: texture,
    transparent: kind === 'glass' || transparent,
    opacity: kind === 'glass' ? 0.42 : 1.0,
    depthWrite: kind !== 'glass' && !transparent,
    side: THREE.DoubleSide,
    toneMapped: false,
  }));
  material.userData.lo4MaterialMode = `${profile}-raw-mask-texture`;
  return material;
}

function carbonMaskTextureUv0ProbeSectionAwareMaterial(...args) {
  return carbonMaskTextureProbeSectionAwareMaterial('carbon_mask_texture_uv0_probe', ...args);
}

function carbonMaskTextureUv1ProbeSectionAwareMaterial(...args) {
  return carbonMaskTextureProbeSectionAwareMaterial('carbon_mask_texture_uv1_probe', ...args);
}

function assetRoutingRoughnessProbeSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('asset_routing_roughness', ...args);
}

function assetRoutingRoughness032ProbeSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('asset_routing_roughness_032', ...args);
}

function assetRoutingRoughness036ProbeSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('asset_routing_roughness_036', ...args);
}

function assetRoutingClearcoatProbeSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('asset_routing_clearcoat', ...args);
}

function assetRoutingIblProbeSectionAwareMaterial(...args) {
  return assetRoutingProbeSectionAwareMaterial('asset_routing_ibl', ...args);
}


function reflectionOnlySectionAwareMaterial(
  paintTexture,
  maskTextures,
  baseColor,
  kind,
  allowedSides,
  projectionSides,
  projectionBounds,
  directUv,
  transparent = false
) {
  return sectionAwarePbrMaterial(
    paintTexture,
    maskTextures,
    baseColor,
    kind,
    allowedSides,
    projectionSides,
    projectionBounds,
    directUv,
    transparent,
    'reflection_only'
  );
}

function reflectionBoostSectionAwareMaterial(
  paintTexture,
  maskTextures,
  baseColor,
  kind,
  allowedSides,
  projectionSides,
  projectionBounds,
  directUv,
  transparent = false
) {
  return sectionAwarePbrMaterial(
    paintTexture,
    maskTextures,
    baseColor,
    kind,
    allowedSides,
    projectionSides,
    projectionBounds,
    directUv,
    transparent,
    'reflection_boost'
  );
}

function calculateProjectionBounds(model, contract) {
  const sections = contract?.sections || [];
  const sectionBySlot = new Map(
    sections.map(section => [Number(section.slot_index), section])
  );
  const bounds = Array.from({ length: SECTION_COUNT }, () => ({
    valid: false,
    minimum: new THREE.Vector2(Infinity, Infinity),
    maximum: new THREE.Vector2(-Infinity, -Infinity),
  }));
  for (const section of sections) {
    const slot = Number(section.slot_index);
    const minimum = section.projection_minimum || [];
    const maximum = section.projection_maximum || [];
    if (
      !Number.isInteger(slot)
      || slot < 0
      || slot >= SECTION_COUNT
      || minimum.length !== 2
      || maximum.length !== 2
      || ![...minimum, ...maximum].map(Number).every(Number.isFinite)
    ) continue;
    bounds[slot].minimum.set(Number(minimum[0]), Number(minimum[1]));
    bounds[slot].maximum.set(Number(maximum[0]), Number(maximum[1]));
    bounds[slot].valid = bounds[slot].maximum.x > bounds[slot].minimum.x
      && bounds[slot].maximum.y > bounds[slot].minimum.y;
  }
  model.updateMatrixWorld(true);
  model.traverse(mesh => {
    if (!mesh.isMesh || mesh.geometry?.getAttribute('uv3')) return;
    const projectionSides = meshProjectionSides(mesh);
    if (!projectionSides) return;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    if (!mesh.geometry.boundingBox) return;
    const worldBounds = mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld);
    for (let slot = 0; slot < SECTION_COUNT; slot += 1) {
      const geometrySide = SLOT_GEOMETRY_SIDES[slot];
      if ((projectionSides & (1 << geometrySide)) === 0) continue;
      const axis = sectionBySlot.get(slot)?.projection_axis || [];
      if (axis.length !== 4) continue;
      const target = bounds[slot];
      if (target.valid) continue;
      const axisX = Number(axis[0]);
      const axisY = Number(axis[1]);
      const scaleX = Number(axis[2]);
      const scaleY = Number(axis[3]);
      if (![axisX, axisY, scaleX, scaleY].every(Number.isFinite)) continue;
      const axisMinimumX = axisX === 0 ? worldBounds.min.x : axisX === 1 ? worldBounds.min.y : worldBounds.min.z;
      const axisMaximumX = axisX === 0 ? worldBounds.max.x : axisX === 1 ? worldBounds.max.y : worldBounds.max.z;
      const axisMinimumY = axisY === 0 ? worldBounds.min.x : axisY === 1 ? worldBounds.min.y : worldBounds.min.z;
      const axisMaximumY = axisY === 0 ? worldBounds.max.x : axisY === 1 ? worldBounds.max.y : worldBounds.max.z;
      const x0 = axisMinimumX * scaleX;
      const x1 = axisMaximumX * scaleX;
      const y0 = axisMinimumY * scaleY;
      const y1 = axisMaximumY * scaleY;
      target.minimum.x = Math.min(target.minimum.x, x0, x1);
      target.minimum.y = Math.min(target.minimum.y, y0, y1);
      target.maximum.x = Math.max(target.maximum.x, x0, x1);
      target.maximum.y = Math.max(target.maximum.y, y0, y1);
      target.valid = target.maximum.x > target.minimum.x && target.maximum.y > target.minimum.y;
    }
  });

  const locators = contract?.assembly?.locators || {};
  const front = locators.bumper_front;
  const rear = locators.bumper_rear;
  if (Array.isArray(front) && Array.isArray(rear)) {
    for (const slot of [2, 3, 4]) {
      const axis = sectionBySlot.get(slot)?.projection_axis || [];
      if (
        Number(axis[0]) !== 2
        || !bounds[slot].valid
        || sectionBySlot.get(slot)?.projection_minimum
      ) continue;
      const first = Number(front[2]) * Number(axis[2]);
      const second = Number(rear[2]) * Number(axis[2]);
      if (Number.isFinite(first) && Number.isFinite(second) && Math.abs(first - second) >= 0.5) {
        bounds[slot].minimum.x = Math.min(first, second);
        bounds[slot].maximum.x = Math.max(first, second);
      }
    }
  }
  return bounds;
}

function stableInspectionBounds(model) {
  if (wheelTireInspectionScope) {
    const isolated = new THREE.Box3();
    let visible = 0;
    model.updateMatrixWorld(true);
    model.traverse(mesh => {
      if (!mesh.isMesh || mesh.visible === false || !wheelTireInspectionKeep(mesh, wheelTireInspectionScope)) return;
      if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
      if (!mesh.geometry.boundingBox) throw new Error('原本Wheel/TireのAABBがありません');
      isolated.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
      visible++;
    });
    if (!visible || isolated.isEmpty()) throw new Error('単体Wheel/Tireに可視幾何がありません');
    return isolated;
  }
  const bounds = new THREE.Box3();
  let found = false;
  model.traverse(mesh => {
    if (!mesh.isMesh || mesh.visible === false || mesh.userData?.lo4_stock_part === false) return;
    const category = meshCategory(mesh);
    if (category !== 'paint' && category !== 'glass') return;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    if (!mesh.geometry.boundingBox) return;
    bounds.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
    found = true;
  });
  return found ? bounds : new THREE.Box3().setFromObject(model);
}

/**
 * 車輪を含む撮影範囲のみ拡張。従来のpaint/glass境界は照明・床・影の
 * 既定表示に継続使用するため、写真に関係しない描画条件を変えない。
 */
function visibleCarCameraBounds(root, base) {
  const framed = base.clone();
  if (!root || framed.isEmpty()) return framed;
  root.updateMatrixWorld(true);
  root.traverse(mesh => {
    if (!mesh.isMesh || mesh.visible === false || mesh.userData?.lo4_stock_part === false) return;
    const part = String(mesh.userData?.lo4_part_type || '');
    if (part !== 'WheelStyle' && part !== 'Tire') return;
    if (!mesh.geometry?.boundingBox) mesh.geometry?.computeBoundingBox();
    if (!mesh.geometry?.boundingBox) return;
    framed.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
  });
  return framed;
}

function inspectionFloorY(assembly, fallback) {
  const centers = assembly?.wheel_centers || {};
  const bottoms = [];
  for (const name of ['front_left', 'front_right', 'rear_left', 'rear_right']) {
    const center = centers[name];
    const {tireRadius} = wheelAssemblyDimensions(assembly, name);
    if (!Array.isArray(center) || center.length !== 3 || !Number.isFinite(Number(center[1])) || !Number.isFinite(tireRadius) || tireRadius <= 0) continue;
    bottoms.push(Number(center[1]) - tireRadius);
  }
  return bottoms.length === 4 ? Math.min(...bottoms) : fallback;
}

function frameModel(bounds, preferredDirection = null, preferredUp = null) {
  // 車種共通の左前方サムネイル向き。6方向の手動選択は方向引数を優先。
  const isDefaultThumbnailCamera = preferredDirection === null;
  const direction = preferredDirection?.clone()
    || thumbnailCameraDirection((x, y, z) => new THREE.Vector3(x, y, z));
  const framed = frameVisibleCar(camera, bounds, direction, {up: preferredUp});
  controls.target.copy(framed.center);
  controls.minDistance = framed.extent * 0.45;
  controls.maxDistance = framed.extent * 20;
  controls.update();
  homeCamera = camera.position.clone();
  homeTarget = controls.target.clone();
  if (isDefaultThumbnailCamera) {
    // Livery/Stockともこの同一フレームを一括撮影。ブラウザーイベントで適用を確認。
    viewerEvent('thumbnail-camera-default', THUMBNAIL_CAMERA_PRESET_ID, {
      direction:THUMBNAIL_CAMERA_DIRECTION,
      modelCameraPosition:camera.position.toArray(),
      modelCameraTarget:framed.center.toArray(),
      exactXboxThumbnailCameraProven:false,
    });
  }
}

function medianFinite(values) {
  const ordered = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!ordered.length) return NaN;
  const middle = Math.floor(ordered.length * 0.5);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) * 0.5;
}

function stockWheelStyleFitmentAnchors(root, centers) {
  const required = ['front_left', 'front_right', 'rear_left', 'rear_right'];
  if (!root || !required.every(name => Array.isArray(centers?.[name]) && centers[name].length === 3)) {
    return {};
  }
  root.updateMatrixWorld(true);
  const candidates = Object.fromEntries(required.map(name => [name, []]));
  const frontZ = (Number(centers.front_left[2]) + Number(centers.front_right[2])) * 0.5;
  const rearZ = (Number(centers.rear_left[2]) + Number(centers.rear_right[2])) * 0.5;
  root.traverse(mesh => {
    if (!mesh.isMesh || mesh.visible === false) return;
    if (String(mesh.userData?.lo4_part_type || '') !== 'WheelStyle') return;
    if (meshCategory(mesh) === 'hidden') return;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    if (!mesh.geometry.boundingBox) return;
    const bounds = mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld);
    // 変換後のWheel Nodeには左右のInstanceが1つのMeshに同居する場合がある。
    // 車体中心線をまたぐNodeを個別WheelのAnchorとして扱わない。
    if (bounds.min.x < -1e-5 && bounds.max.x > 1e-5) return;
    const size = bounds.getSize(new THREE.Vector3());
    const radial = Math.max(size.y, size.z);
    const radialMinor = Math.min(size.y, size.z);
    // Wheel／Rim程度の大きさを持つ概ね円形の部品だけを基準にする。
    // Badge・Lugや無関係な近傍車体Meshを除き、
    // FH6で使う主WheelStyle Shell／Blur Rimの根拠を保持する。
    if (
      ![size.x, size.y, size.z, radial, radialMinor].every(Number.isFinite)
      || radial < 0.18
      || radial > 0.45
      || radialMinor < radial * 0.80
      || size.x > 0.20
    ) return;
    const center = bounds.getCenter(new THREE.Vector3());
    const side = center.x < 0 ? 'left' : 'right';
    const axle = Math.abs(center.z - frontZ) <= Math.abs(center.z - rearZ) ? 'front' : 'rear';
    const name = `${axle}_${side}`;
    candidates[name].push({
      center,
      radial,
      outboardEdge: side === 'left' ? bounds.min.x : bounds.max.x,
    });
  });

  const anchors = {};
  for (const name of required) {
    const wheelCandidates = candidates[name];
    if (!wheelCandidates.length) continue;
    const maxRadial = Math.max(...wheelCandidates.map(item => item.radial));
    const selected = wheelCandidates.filter(item => item.radial >= maxRadial * 0.95);
    if (selected.length < 2) continue;
    const center = [0, 1, 2].map(axis => medianFinite(selected.map(item => item.center.getComponent(axis))));
    const side = name.endsWith('_left') ? 'left' : 'right';
    const outboardEdge = side === 'left'
      ? Math.min(...selected.map(item => item.outboardEdge))
      : Math.max(...selected.map(item => item.outboardEdge));
    const locator = centers[name].map(Number);
    if (![...center, outboardEdge, ...locator].every(Number.isFinite)) continue;
    // 復元したStock Wheelの証拠を位置基準の周囲に限定する。
    // 原本MIT_LancerEvoIII_95ではX方向に約0.27mの差があり得る一方、
    // Y／Zは近い。より大きな不一致は曖昧な入力として扱う。
    if (
      Math.abs(center[0] - locator[0]) > 0.40
      || Math.abs(center[1] - locator[1]) > 0.15
      || Math.abs(center[2] - locator[2]) > 0.15
      || Math.abs(outboardEdge - center[0]) > 0.20
    ) continue;
    anchors[name] = {
      center,
      outboardEdge,
      evidenceCount: selected.length,
    };
  }

  if (!required.every(name => anchors[name])) return {};
  const symmetric = (
    Math.abs(Math.abs(anchors.front_left.center[0]) - Math.abs(anchors.front_right.center[0])) <= 0.08
    && Math.abs(Math.abs(anchors.rear_left.center[0]) - Math.abs(anchors.rear_right.center[0])) <= 0.08
    && Math.abs(anchors.front_left.center[1] - anchors.front_right.center[1]) <= 0.08
    && Math.abs(anchors.rear_left.center[1] - anchors.rear_right.center[1]) <= 0.08
    && Math.abs(anchors.front_left.center[2] - anchors.front_right.center[2]) <= 0.08
    && Math.abs(anchors.rear_left.center[2] - anchors.rear_right.center[2]) <= 0.08
  );
  if (!symmetric) return {};
  return anchors;
}

function proxyWheelFitmentOffset(positionX, outboardEdge, proxyTireWidth, fallbackOffset) {
  const inwardSign = positionX >= 0 ? -1 : 1;
  const outboardSign = -inwardSign;
  if (![positionX, outboardEdge, proxyTireWidth, fallbackOffset].every(Number.isFinite) || proxyTireWidth <= 0) {
    return fallbackOffset;
  }
  const desiredCenter = outboardEdge - outboardSign * proxyTireWidth * 0.5;
  const derivedOffset = desiredCenter - positionX;
  const movesInboard = derivedOffset * inwardSign > 0;
  if (!movesInboard || Math.abs(derivedOffset) > proxyTireWidth * 0.90) return fallbackOffset;
  return derivedOffset;
}

function stockWheelAssetInventory(root) {
  const inventory = {
    wheelStyleMeshCount: 0,
    tireLikeMeshCount: 0,
    visibleTireLikeMeshCount: 0,
    wheelLikeMeshCount: 0,
    wheelPaintAppliedMeshCount: 0,
    wheelPaintRoutableMeshCount: 0,
    wheelPaintUnroutedMeshCount: 0,
    wheelPaintNoColorMeshCount: 0,
    wheelPaintAppliedGroups: {},
    wheelPaintAppliedColors: {},
    wheelPaintRouteSources: {},
    wheelPaintMaterialTokens: {},
    wheelPaintFinishAppliedMeshCount: 0,
    wheelPaintFinishMaterials: {},
    wheelPaintFinishCandidates: {},
    partTypes: {},
    sampleNames: [],
  };
  if (!root) return inventory;
  root.traverse(mesh => {
    if (!mesh.isMesh) return;
    const partType = String(mesh.userData?.lo4_part_type || '');
    const identity = meshIdentity(mesh);
    const wheelStyle = partType === 'WheelStyle' || wheelStyleEvidenceForMesh(mesh);
    const tireLike = identity.includes('tire') || identity.includes('tyre');
    const wheelLike = wheelStyle || tireLike || identity.includes('wheel') || identity.includes('rim');
    if (wheelStyle) inventory.wheelStyleMeshCount += 1;
    if (tireLike) {
      inventory.tireLikeMeshCount += 1;
      if (mesh.visible !== false && mesh.userData?.lo4_base_visible !== false) inventory.visibleTireLikeMeshCount += 1;
    }
    if (wheelLike) inventory.wheelLikeMeshCount += 1;
    if (wheelStyle) {
      const route = wheelPaintRouteForMesh(mesh);
      const token = String(route?.token || wheelMetadataForMesh(mesh, 'lo4_wheel_material_name') || '-');
      inventory.wheelPaintMaterialTokens[token] = (inventory.wheelPaintMaterialTokens[token] || 0) + 1;
      if (route) {
        inventory.wheelPaintRoutableMeshCount += 1;
        const routedColor = wheelPaintColorForMesh(mesh);
        if (!routedColor) inventory.wheelPaintNoColorMeshCount += 1;
      } else {
        inventory.wheelPaintUnroutedMeshCount += 1;
      }
    }
    if (mesh.userData?.lo4_wheel_paint_applied === true) {
      inventory.wheelPaintAppliedMeshCount += 1;
      const group = String(mesh.userData?.lo4_wheel_paint_group || '');
      const color = String(mesh.userData?.lo4_wheel_paint_color || '');
      const routeSource = String(mesh.userData?.lo4_wheel_paint_route_source || '');
      const finishMaterial = String(mesh.userData?.lo4_wheel_paint_finish_material || '');
      if (group) inventory.wheelPaintAppliedGroups[group] = (inventory.wheelPaintAppliedGroups[group] || 0) + 1;
      if (color) inventory.wheelPaintAppliedColors[color] = (inventory.wheelPaintAppliedColors[color] || 0) + 1;
      if (routeSource) inventory.wheelPaintRouteSources[routeSource] = (inventory.wheelPaintRouteSources[routeSource] || 0) + 1;
      if (finishMaterial) {
        inventory.wheelPaintFinishAppliedMeshCount += 1;
        inventory.wheelPaintFinishMaterials[finishMaterial] = (inventory.wheelPaintFinishMaterials[finishMaterial] || 0) + 1;
        const signature = [
          `R${Number(mesh.userData?.lo4_wheel_paint_finish_roughness).toFixed(2)}`,
          `M${Number(mesh.userData?.lo4_wheel_paint_finish_metalness).toFixed(2)}`,
          `CC${Number(mesh.userData?.lo4_wheel_paint_finish_clearcoat).toFixed(2)}`,
          `CCR${Number(mesh.userData?.lo4_wheel_paint_finish_clearcoat_roughness).toFixed(2)}`,
          `Env${Number(mesh.userData?.lo4_wheel_paint_finish_env_map_intensity).toFixed(2)}`,
        ].join(' ');
        inventory.wheelPaintFinishCandidates[signature] = (inventory.wheelPaintFinishCandidates[signature] || 0) + 1;
      }
    }
    if (partType) inventory.partTypes[partType] = (inventory.partTypes[partType] || 0) + 1;
    if (wheelLike && inventory.sampleNames.length < 24) {
      inventory.sampleNames.push({
        name: String(mesh.name || ''),
        material: String(mesh.material?.name || ''),
        partType,
        stock: mesh.userData?.lo4_stock_part === true,
        visible: mesh.visible !== false,
      });
    }
  });
  return inventory;
}

function gameDerivedWheelStylePieces(root, centers, anchors) {
  const required = ['front_left', 'front_right', 'rear_left', 'rear_right'];
  if (!root || !required.every(name => anchors?.[name])) return {};
  root.updateMatrixWorld(true);
  const candidates = Object.fromEntries(required.map(name => [name, []]));

  // r211：r210はWheel大の円形Meshだけを保全し中心・Ringの位置を揃えたが、
  // Spoke・Hub／Cap・Lugなどの小さなWheelStyle子Meshまで欠落した。
  // 厳密な円形証拠は装着Anchorに限定し、検証済みAnchor付近の
  // Stock WheelStyle／Wheel Face子Meshをグループ化して保持する。
  root.traverse(mesh => {
    if (!mesh.isMesh || mesh.visible === false) return;
    if (meshCategory(mesh) === 'hidden') return;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    if (!mesh.geometry.boundingBox) return;
    const bounds = mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld);
    if (bounds.min.x < -1e-5 && bounds.max.x > 1e-5) return;
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    if (![size.x, size.y, size.z, center.x, center.y, center.z].every(Number.isFinite)) return;

    const partType = String(mesh.userData?.lo4_part_type || '');
    const identity = meshIdentity(mesh);
    const wheelStyle = partType === 'WheelStyle';
    const wheelFaceIdentity = [
      'wheel', 'rim', 'spoke', 'hub', 'center', 'centre', 'cap', 'discface', 'wheelstyle'
    ].some(token => identity.includes(token));
    const fastenerIdentity = ['lug', 'nut', 'bolt', 'stud'].some(token => identity.includes(token));
    const hubIdentity = ['hub', 'center', 'centre', 'cap'].some(token => identity.includes(token));
    const excludedIdentity = [
      'tire', 'tyre', 'brake', 'caliper', 'rotor', 'drum', 'suspension', 'axle', 'shadow'
    ].some(token => identity.includes(token));
    if ((!wheelStyle && !wheelFaceIdentity) || excludedIdentity || fastenerIdentity) return;

    // r213：r212でもNSXの中心に同じ玩具状の5ブロックが現れた。
    // 原因はLug／Nutという名称の一致だけでなく、再構成境界にある
    // 小型中心Cluster自体の識別が曖昧なことと判明した。
    // ゲーム原本由来の外周Rim／Spokeは保持し、明示的なSpoke／Rim名がない
    // 小型中心部品は表示しない。Hub／Cap／Fastenerの厳密な配置は
    // Viewer内で推測せずWheel Scene階層研究で別途確認する。
    const radial = Math.max(size.y, size.z);
    const radialMinor = Math.min(size.y, size.z);
    const outerFaceIdentity = ['rim', 'spoke', 'wheelstyle'].some(token => identity.includes(token));
    if (radial < 0.006 || radial > 0.55 || size.x > 0.28) return;

    // r216：r215の調査で、変換GLBではWheelStyleの階層・識別証拠が平坦化され、
    // 12個の小型WheelStyle Nodeは親なし・wheel_LODS0名・局所平行移動0・倍率1だった。
    // そのため名前に含まれるwheelstyle／spoke／rimだけでは、
    // Hub／Lug Clusterと有効なWheel Faceを安全に区別できない。
    // NSXは1輪につき約0.086×0.101×0.106mの小型Clusterを1つ持ち、
    // r211〜r213で見えた5ブロックの中心と一致する。
    // Converterが詳細な階層・材質情報を保持するまで、
    // 原本由来WheelStyleの半径0.18m以上の幾何だけを表示候補とする。
    if (wheelStyle && radial < 0.18) return;
    if (radial < 0.20 && !outerFaceIdentity) return;
    if (radial < 0.14 && wheelStyle && !identity.includes('spoke') && !identity.includes('rim')) return;

    const side = center.x < 0 ? 'left' : 'right';
    let bestName = null;
    let bestScore = Infinity;
    for (const name of required) {
      if (!name.endsWith(`_${side}`)) continue;
      const anchorCenter = anchors[name].center.map(Number);
      const dx = Math.abs(center.x - anchorCenter[0]);
      const dy = Math.abs(center.y - anchorCenter[1]);
      const dz = Math.abs(center.z - anchorCenter[2]);
      if (dx > 0.22 || dy > 0.18 || dz > 0.18) continue;
      const score = (dx / 0.22) ** 2 + (dy / 0.18) ** 2 + (dz / 0.18) ** 2;
      if (score < bestScore) {
        bestScore = score;
        bestName = name;
      }
    }
    if (!bestName) return;

    const approximatelyCircular = radial >= 0.18
      && radial <= 0.45
      && radialMinor >= radial * 0.80
      && size.x <= 0.20;
    candidates[bestName].push({
      mesh,
      center,
      radial,
      core: wheelStyle && approximatelyCircular,
    });
  });

  const selected = {};
  for (const name of required) {
    const items = candidates[name];
    if (!items.length || !items.some(item => item.core)) continue;
    // 厳密な円形ShellでWheel位置を証明できた場合は、付近のWheelStyle子を優先する。
    // WheelStyle以外の名前由来候補は同じAnchor近くで
    // Wheel Faceの細部として扱える場合のみ残す。
    selected[name] = items;
  }
  return selected;
}

function addGameDerivedWheelFit(root, assembly, variantMode = "") {
  const centers = assembly?.wheel_centers || {};
  const required = ['front_left', 'front_right', 'rear_left', 'rear_right'];
  if (
    !validVehicleAssemblyFormat(assembly)
    || !required.every(name => Array.isArray(centers[name]) && centers[name].length === 3)
    || !required.every(name => {
      const {tireRadius, tireWidth, rimRadius} = wheelAssemblyDimensions(assembly, name);
      return [tireRadius, tireWidth, rimRadius].every(Number.isFinite)
        && tireRadius > 0 && tireWidth > 0 && rimRadius > 0 && rimRadius < tireRadius;
    })
  ) return 0;

  const anchors = stockWheelStyleFitmentAnchors(root, centers);
  if (!required.every(name => anchors[name])) return 0;
  const piecesByWheel = gameDerivedWheelStylePieces(root, centers, anchors);
  if (!required.every(name => Array.isArray(piecesByWheel[name]) && piecesByWheel[name].length)) return 0;

  // r210／r211：Stock SceneのWheel MeshはFH6の有用な幾何を保持するが、
  // 原本階層・変換経路によって無関係なWheel状部品がArchの外に配置され得る。
  // 生のStock Wheel／Tire Nodeは非表示にし、円形WheelStyle Shellを装着証拠として
  // 維持した上で、FH6原本で確定したAnchor近傍のFace細部Clusterを再構成する。
  // 装着済みTire Mesh／半径の根拠が解決するまでは中立代替Tireを残す。
  setStockWheelAssetVisibility(root, false);

  const tireMaterial = trackMaterial(new THREE.MeshStandardMaterial({
    color: 0x1b2026,
    roughness: 0.80,
    metalness: 0.01,
  }));
  const sidewallMaterial = trackMaterial(new THREE.MeshStandardMaterial({
    color: 0x252b33,
    roughness: 0.76,
    metalness: 0.02,
  }));

  const wheelGroup = new THREE.Group();
  wheelGroup.name = `game-derived fitted wheels ${variantMode}`.trim();
  wheelGroup.visible = wheelsVisible;

  for (const name of required) {
    const anchor = anchors[name];
    const exactCenter = centers[name].map(Number);
    const sourceCenter = anchor.center.map(Number);
    const center = assembly?.source === 'local-fh6-gamedb' ? exactCenter : sourceCenter;
    const {tireRadius, tireWidth, rimRadius} = wheelAssemblyDimensions(assembly, name);
    const proxyTireWidth = Math.max(rimRadius * 0.32, tireWidth * 0.72);
    const tubeRadius = (tireRadius - rimRadius) * 0.5;
    const torusRadius = rimRadius + tubeRadius;
    const tireGeometry = new THREE.TorusGeometry(torusRadius, tubeRadius, 18, 64);
    tireGeometry.scale(1, 1, proxyTireWidth / (tubeRadius * 2));
    const sidewallRadius = Math.max(rimRadius * 1.03, tireRadius - tubeRadius * 0.30);
    const sidewallThickness = Math.max(proxyTireWidth * 0.085, rimRadius * 0.028);
    const sidewallGeometry = new THREE.CylinderGeometry(sidewallRadius, sidewallRadius, sidewallThickness, 48, 1, false);
    trackedGeometries.add(tireGeometry);
    trackedGeometries.add(sidewallGeometry);
    const wheel = new THREE.Group();
    wheel.name = `game-derived fitted wheel ${name}`;
    wheel.position.set(...center);
    wheel.userData.lo4_wheel_center_source = assembly?.source === 'local-fh6-gamedb' ? 'local-fh6-gamedb' : 'local-fh6-wheelstyle-center';
    wheel.userData.lo4_wheel_geometry_source = 'local-fh6-wheelstyle-cluster';
    wheel.userData.lo4_wheel_cluster_piece_count = piecesByWheel[name].length;

    const tire = new THREE.Mesh(tireGeometry, tireMaterial);
    tire.rotation.y = Math.PI / 2;
    tire.name = `${wheel.name} neutral tire fallback`;
    wheel.add(tire);

    const outboardSign = center[0] < 0 ? -1 : 1;
    const outerSidewall = new THREE.Mesh(sidewallGeometry, sidewallMaterial);
    outerSidewall.rotation.z = Math.PI / 2;
    outerSidewall.position.x = outboardSign * proxyTireWidth * 0.44;
    outerSidewall.name = `${wheel.name} sidewall outer`;
    wheel.add(outerSidewall);
    const innerSidewall = new THREE.Mesh(sidewallGeometry, sidewallMaterial);
    innerSidewall.rotation.z = Math.PI / 2;
    innerSidewall.position.x = -outboardSign * proxyTireWidth * 0.44;
    innerSidewall.name = `${wheel.name} sidewall inner`;
    wheel.add(innerSidewall);

    for (const item of piecesByWheel[name]) {
      const geometry = item.mesh.geometry.clone();
      geometry.applyMatrix4(item.mesh.matrixWorld);
      geometry.translate(-sourceCenter[0], -sourceCenter[1], -sourceCenter[2]);
      trackedGeometries.add(geometry);
      const fitted = new THREE.Mesh(geometry, item.mesh.material);
      fitted.name = `${wheel.name} ${item.mesh.name || 'WheelStyle'}`;
      fitted.userData = {
        ...item.mesh.userData,
        lo4_game_fit: true,
        lo4_source_wheel_name: name,
      };
      fitted.castShadow = true;
      fitted.receiveShadow = true;
      wheel.add(fitted);
    }
    wheelGroup.add(wheel);
  }
  root.add(wheelGroup);
  inspectionWheelGroups.set(variantMode || String(inspectionWheelGroups.size), wheelGroup);
  inspectionWheels = wheelGroup;
  return required.length;
}

function addNeutralTireFallbacks(root, assembly, variantMode = "", reason = "stock-tire-unavailable") {
  const centers = assembly?.wheel_centers || {};
  const required = ['front_left', 'front_right', 'rear_left', 'rear_right'];
  if (
    !validVehicleAssemblyFormat(assembly)
    || !required.every(name => Array.isArray(centers[name]) && centers[name].length === 3)
  ) return 0;

  const anchors = stockWheelStyleFitmentAnchors(root, centers);
  const tireMaterial = trackMaterial(new THREE.MeshStandardMaterial({
    color: 0x11151a,
    roughness: 0.88,
    metalness: 0.0,
  }));
  const sidewallMaterial = trackMaterial(new THREE.MeshStandardMaterial({
    color: 0x181d23,
    roughness: 0.84,
    metalness: 0.0,
  }));
  const tireGroup = new THREE.Group();
  tireGroup.name = `neutral tire-only fallback ${variantMode}`.trim();
  tireGroup.visible = wheelsVisible;
  tireGroup.userData.lo4_tire_fallback_reason = reason;

  for (const name of required) {
    const {tireRadius, tireWidth, rimRadius} = wheelAssemblyDimensions(assembly, name);
    if (![tireRadius, tireWidth, rimRadius].every(Number.isFinite)
        || tireRadius <= 0 || tireWidth <= 0 || rimRadius <= 0 || rimRadius >= tireRadius) return 0;
    const locator = centers[name].map(Number);
    const anchorPosition = Array.isArray(anchors[name]?.center) && anchors[name].center.length === 3
      ? anchors[name].center.map(Number)
      : locator;
    if (!anchorPosition.every(Number.isFinite)) return 0;
    const proxyTireWidth = Math.max(rimRadius * 0.32, tireWidth * 0.72);
    const tubeRadius = Math.max(0.001, (tireRadius - rimRadius) * 0.5);
    const torusRadius = rimRadius + tubeRadius;
    const tireGeometry = new THREE.TorusGeometry(torusRadius, tubeRadius, 18, 64);
    tireGeometry.scale(1, 1, proxyTireWidth / (tubeRadius * 2));
    const sidewallRadius = Math.max(rimRadius * 1.03, tireRadius - tubeRadius * 0.30);
    const sidewallThickness = Math.max(proxyTireWidth * 0.085, rimRadius * 0.028);
    const sidewallGeometry = new THREE.CylinderGeometry(
      sidewallRadius, sidewallRadius, sidewallThickness, 48, 1, false
    );
    trackedGeometries.add(tireGeometry);
    trackedGeometries.add(sidewallGeometry);

    const wheel = new THREE.Group();
    wheel.name = `neutral tire fallback ${name}`;
    wheel.position.set(...anchorPosition);
    wheel.userData.lo4_wheel_center_source = anchors[name]
      ? 'local-fh6-wheelstyle-center'
      : 'local-fh6-gamedb';

    const tire = new THREE.Mesh(tireGeometry, tireMaterial);
    tire.rotation.y = Math.PI / 2;
    tire.name = `${wheel.name} tread`;
    wheel.add(tire);

    const outboardSign = anchorPosition[0] < 0 ? -1 : 1;
    const outerSidewall = new THREE.Mesh(sidewallGeometry, sidewallMaterial);
    outerSidewall.rotation.z = Math.PI / 2;
    outerSidewall.position.x = outboardSign * proxyTireWidth * 0.44;
    outerSidewall.name = `${wheel.name} sidewall outer`;
    wheel.add(outerSidewall);
    const innerSidewall = new THREE.Mesh(sidewallGeometry, sidewallMaterial);
    innerSidewall.rotation.z = Math.PI / 2;
    innerSidewall.position.x = -outboardSign * proxyTireWidth * 0.44;
    innerSidewall.name = `${wheel.name} sidewall inner`;
    wheel.add(innerSidewall);
    tireGroup.add(wheel);
  }

  root.add(tireGroup);
  inspectionWheelGroups.set(`${variantMode || String(inspectionWheelGroups.size)}:tire-fallback`, tireGroup);
  inspectionWheels = tireGroup;
  viewerEvent('stock-tire-fallback', variantMode || '', {reason, wheelCount: required.length});
  return required.length;
}

function addInspectionWheels(root, assembly, variantMode = "") {
  const centers = assembly?.wheel_centers || {};
  const tireRadius = Number(assembly?.tire_radius);
  const tireWidth = Number(assembly?.tire_width);
  const rimRadius = Number(assembly?.rim_radius);
  const required = ['front_left', 'front_right', 'rear_left', 'rear_right'];
  if (
    !validVehicleAssemblyFormat(assembly)
    || !required.every(name => Array.isArray(centers[name]) && centers[name].length === 3)
    || ![tireRadius, tireWidth, rimRadius].every(Number.isFinite)
    || tireRadius <= 0
    || tireWidth <= 0
    || rimRadius <= 0
    || rimRadius >= tireRadius
  ) {
    return 0;
  }

  const tireMaterial = new THREE.MeshStandardMaterial({
    color: 0x1b2026,
    roughness: 0.80,
    metalness: 0.01,
  });
  const sidewallMaterial = new THREE.MeshStandardMaterial({
    color: 0x252b33,
    roughness: 0.76,
    metalness: 0.02,
  });
  const rimBarrelMaterial = new THREE.MeshStandardMaterial({
    color: 0x68717b,
    roughness: 0.32,
    metalness: 0.78,
  });
  const spokeMaterial = new THREE.MeshStandardMaterial({
    color: 0x9aa3ad,
    roughness: 0.24,
    metalness: 0.88,
  });
  const faceAccentMaterial = new THREE.MeshStandardMaterial({
    color: 0xa5336f,
    roughness: 0.20,
    metalness: 0.92,
  });
  const facePocketMaterial = new THREE.MeshStandardMaterial({
    color: 0x313741,
    roughness: 0.30,
    metalness: 0.36,
  });
  const rimLipMaterial = new THREE.MeshStandardMaterial({
    color: 0xd8dee5,
    roughness: 0.14,
    metalness: 0.96,
  });
  const hubMaterial = new THREE.MeshStandardMaterial({
    color: 0x454c55,
    roughness: 0.34,
    metalness: 0.68,
  });
  const rotorMaterial = new THREE.MeshStandardMaterial({
    color: 0xb4bcc4,
    roughness: 0.42,
    metalness: 0.84,
  });
  const caliperMaterial = new THREE.MeshStandardMaterial({
    color: 0x5b646d,
    roughness: 0.38,
    metalness: 0.24,
  });
  [
    tireMaterial,
    sidewallMaterial,
    rimBarrelMaterial,
    spokeMaterial,
    faceAccentMaterial,
    facePocketMaterial,
    rimLipMaterial,
    hubMaterial,
    rotorMaterial,
    caliperMaterial,
  ].forEach(trackMaterial);

  const proxyTireWidth = Math.max(rimRadius * 0.32, tireWidth * 0.72);
  const proxyInboardOffset = Math.min(proxyTireWidth * 0.32, rimRadius * 0.20);
  const stockFitmentAnchors = stockWheelStyleFitmentAnchors(root, centers);
  const tubeRadius = (tireRadius - rimRadius) * 0.5;
  const torusRadius = rimRadius + tubeRadius;
  const tireGeometry = new THREE.TorusGeometry(torusRadius, tubeRadius, 18, 64);
  tireGeometry.scale(1, 1, proxyTireWidth / (tubeRadius * 2));

  const sidewallRadius = Math.max(rimRadius * 1.03, tireRadius - tubeRadius * 0.30);
  const sidewallThickness = Math.max(proxyTireWidth * 0.085, rimRadius * 0.028);
  const sidewallGeometry = new THREE.CylinderGeometry(
    sidewallRadius,
    sidewallRadius,
    sidewallThickness,
    48,
    1,
    false
  );

  const rimBarrelDepth = proxyTireWidth * 0.64;
  const rimBarrelGeometry = new THREE.CylinderGeometry(
    rimRadius,
    rimRadius,
    rimBarrelDepth,
    48,
    1,
    false
  );
  const rotorRadius = rimRadius * 0.72;
  const rotorGeometry = new THREE.CylinderGeometry(
    rotorRadius,
    rotorRadius,
    Math.max(proxyTireWidth * 0.08, rimRadius * 0.02),
    40,
    1,
    false
  );
  const hubGeometry = new THREE.CylinderGeometry(
    rimRadius * 0.22,
    rimRadius * 0.22,
    proxyTireWidth * 0.62,
    28,
    1,
    false
  );
  const spokeHeight = rimRadius * 0.12;
  const spokeLength = rimRadius * 0.78;
  const spokeDepth = Math.max(proxyTireWidth * 0.16, rimRadius * 0.06);
  const spokeGeometry = new THREE.BoxGeometry(spokeLength, spokeHeight, spokeDepth);
  const faceDiscGeometry = new THREE.CylinderGeometry(
    rimRadius * 0.82,
    rimRadius * 0.82,
    Math.max(proxyTireWidth * 0.08, rimRadius * 0.03),
    40,
    1,
    false
  );
  const facePocketGeometry = new THREE.CylinderGeometry(
    rimRadius * 0.56,
    rimRadius * 0.56,
    Math.max(proxyTireWidth * 0.06, rimRadius * 0.025),
    32,
    1,
    false
  );
  const centerCapGeometry = new THREE.CylinderGeometry(
    rimRadius * 0.15,
    rimRadius * 0.15,
    Math.max(proxyTireWidth * 0.12, rimRadius * 0.05),
    28,
    1,
    false
  );
  const rimLipGeometry = new THREE.TorusGeometry(
    rimRadius * 0.91,
    rimRadius * 0.05,
    12,
    48
  );
  const caliperGeometry = new THREE.BoxGeometry(
    rimRadius * 0.22,
    rimRadius * 0.34,
    Math.max(proxyTireWidth * 0.28, rimRadius * 0.12)
  );
  const lugGeometry = new THREE.CylinderGeometry(
    rimRadius * 0.055,
    rimRadius * 0.055,
    Math.max(proxyTireWidth * 0.12, rimRadius * 0.05),
    14,
    1,
    false
  );

  [
    tireGeometry,
    sidewallGeometry,
    rimBarrelGeometry,
    rotorGeometry,
    hubGeometry,
    spokeGeometry,
    faceDiscGeometry,
    facePocketGeometry,
    centerCapGeometry,
    rimLipGeometry,
    caliperGeometry,
    lugGeometry,
  ].forEach(geometry => trackedGeometries.add(geometry));

  const wheelGroup = new THREE.Group();
  wheelGroup.name = `neutral locator-based inspection wheels ${variantMode}`.trim();
  wheelGroup.visible = wheelsVisible;
  for (const name of required) {
    const locatorPosition = centers[name].map(Number);
    if (!locatorPosition.every(Number.isFinite)) return 0;
    const stockAnchor = stockFitmentAnchors[name];
    const anchorPosition = Array.isArray(stockAnchor?.center) && stockAnchor.center.length === 3
      ? stockAnchor.center.map(Number)
      : locatorPosition;
    const usesStockAnchor = anchorPosition.every(Number.isFinite) && stockAnchor != null;
    const position = usesStockAnchor ? anchorPosition : locatorPosition;
    const wheel = new THREE.Group();
    wheel.name = `inspection wheel ${name}`;
    wheel.position.set(...position);
    wheel.userData.lo4_wheel_center_source = usesStockAnchor
      ? 'local-fh6-wheelstyle-center'
      : 'locator-fallback';

    const wheelAssembly = new THREE.Group();
    wheelAssembly.name = `${wheel.name} fitted proxy`;
    const inwardSign = position[0] >= 0 ? -1 : 1;
    const outboardSign = -inwardSign;
    const fallbackFitmentOffset = inwardSign * proxyInboardOffset;
    const effectiveFallbackFitmentOffset = usesStockAnchor ? 0 : fallbackFitmentOffset;
    const stockOutboardEdge = Number(stockAnchor?.outboardEdge);
    const fitmentOffset = proxyWheelFitmentOffset(
      position[0],
      stockOutboardEdge,
      proxyTireWidth,
      effectiveFallbackFitmentOffset
    );
    wheelAssembly.position.x = fitmentOffset;
    wheelAssembly.userData.lo4_fitment_source = usesStockAnchor && Number.isFinite(stockOutboardEdge)
      ? 'local-fh6-wheelstyle-center-and-edge'
      : 'neutral-proxy-fallback';
    wheel.add(wheelAssembly);

    const tire = new THREE.Mesh(tireGeometry, tireMaterial);
    tire.rotation.y = Math.PI / 2;
    tire.name = `${wheel.name} tire`;
    wheelAssembly.add(tire);

    const outerSidewall = new THREE.Mesh(sidewallGeometry, sidewallMaterial);
    outerSidewall.rotation.z = Math.PI / 2;
    outerSidewall.position.x = proxyTireWidth * 0.44;
    outerSidewall.name = `${wheel.name} sidewall outer`;
    wheelAssembly.add(outerSidewall);

    const innerSidewall = new THREE.Mesh(sidewallGeometry, sidewallMaterial);
    innerSidewall.rotation.z = Math.PI / 2;
    innerSidewall.position.x = -proxyTireWidth * 0.44;
    innerSidewall.name = `${wheel.name} sidewall inner`;
    wheelAssembly.add(innerSidewall);

    const rimBarrel = new THREE.Mesh(rimBarrelGeometry, rimBarrelMaterial);
    rimBarrel.rotation.z = Math.PI / 2;
    rimBarrel.name = `${wheel.name} rim barrel`;
    wheelAssembly.add(rimBarrel);

    const faceDisc = new THREE.Mesh(faceDiscGeometry, spokeMaterial);
    faceDisc.rotation.z = Math.PI / 2;
    faceDisc.position.x = outboardSign * proxyTireWidth * 0.18;
    faceDisc.name = `${wheel.name} face disc`;
    wheelAssembly.add(faceDisc);

    const facePocket = new THREE.Mesh(facePocketGeometry, facePocketMaterial);
    facePocket.rotation.z = Math.PI / 2;
    facePocket.position.x = outboardSign * proxyTireWidth * 0.17;
    facePocket.name = `${wheel.name} face pocket`;
    wheelAssembly.add(facePocket);

    const rimLip = new THREE.Mesh(rimLipGeometry, rimLipMaterial);
    rimLip.rotation.y = Math.PI / 2;
    rimLip.position.x = outboardSign * proxyTireWidth * 0.27;
    rimLip.name = `${wheel.name} rim lip`;
    wheelAssembly.add(rimLip);

    const rotor = new THREE.Mesh(rotorGeometry, rotorMaterial);
    rotor.rotation.z = Math.PI / 2;
    rotor.position.x = outboardSign * proxyTireWidth * 0.08;
    rotor.name = `${wheel.name} brake rotor`;
    wheelAssembly.add(rotor);

    const caliper = new THREE.Mesh(caliperGeometry, caliperMaterial);
    caliper.position.set(
      outboardSign * proxyTireWidth * 0.04,
      rimRadius * 0.48,
      -rimRadius * 0.18,
    );
    caliper.name = `${wheel.name} brake caliper`;
    wheelAssembly.add(caliper);

    for (let spokeIndex = 0; spokeIndex < 5; spokeIndex += 1) {
      const spoke = new THREE.Mesh(spokeGeometry, spokeMaterial);
      const angle = (spokeIndex / 5) * Math.PI * 2;
      const radius = rimRadius * 0.33;
      spoke.position.set(outboardSign * proxyTireWidth * 0.20, Math.cos(angle) * radius, Math.sin(angle) * radius);
      spoke.rotation.x = angle;
      spoke.rotation.z = outboardSign * 0.18;
      spoke.name = `${wheel.name} spoke ${spokeIndex + 1}`;
      wheelAssembly.add(spoke);
    }

    const hub = new THREE.Mesh(hubGeometry, hubMaterial);
    hub.rotation.z = Math.PI / 2;
    hub.position.x = outboardSign * proxyTireWidth * 0.14;
    hub.name = `${wheel.name} hub`;
    wheelAssembly.add(hub);

    const centerCap = new THREE.Mesh(centerCapGeometry, rimLipMaterial);
    centerCap.rotation.z = Math.PI / 2;
    centerCap.position.x = outboardSign * proxyTireWidth * 0.23;
    centerCap.name = `${wheel.name} center cap`;
    wheelAssembly.add(centerCap);

    for (let lugIndex = 0; lugIndex < 5; lugIndex += 1) {
      const lug = new THREE.Mesh(lugGeometry, rimLipMaterial);
      const angle = (lugIndex / 5) * Math.PI * 2 + Math.PI / 5;
      const radius = rimRadius * 0.12;
      lug.rotation.z = Math.PI / 2;
      lug.position.set(outboardSign * proxyTireWidth * 0.22, Math.cos(angle) * radius, Math.sin(angle) * radius);
      lug.name = `${wheel.name} lug ${lugIndex + 1}`;
      wheelAssembly.add(lug);
    }
    wheelGroup.add(wheel);
  }
  root.add(wheelGroup);
  inspectionWheelGroups.set(variantMode || String(inspectionWheelGroups.size), wheelGroup);
  inspectionWheels = wheelGroup;
  return required.length;
}

function paintBindingSurfacesForFilter(filterName) {
  const mapping = {
    front: ['front', 'front_windscreen'],
    back: ['back', 'rear_windscreen'],
    top: ['top', 'top_window'],
    left: ['left', 'left_window'],
    right: ['right', 'right_window'],
  };
  return filterName === 'all' ? null : (mapping[filterName] || [filterName]);
}

function updateFinishInfo(filterName = activeSectionFilter) {
  if (!finishInfo) return;
  const bindings = Array.isArray(renderContract?.paint_bindings) ? renderContract.paint_bindings : [];
  if (!bindings.length) {
    finishInfo.textContent = t('info.finish_unavailable');
    return;
  }
  const surfaces = paintBindingSurfacesForFilter(filterName);
  const selected = surfaces ? bindings.filter(item => surfaces.includes(String(item?.surface || ''))) : bindings;
  const valid = selected.filter(item => Number.isInteger(Number(item?.finish_code_raw)));
  if (!valid.length) {
    finishInfo.textContent = t('info.finish_no_record');
    return;
  }
  if (filterName === 'all') {
    const codes = [...new Set(valid.map(item => Number(item.finish_code_raw)))].sort((a, b) => a - b);
    const base = assetRoutingBasePaint();
    const candidate = basePaintViewerCandidate(base);
    const response = base?.material_name
      ? t('info.base_material', {
          material: base.material_name,
          roughness: Number.isFinite(Number(candidate.roughness)) ? Number(candidate.roughness).toFixed(2) : '-',
          metalness: Number.isFinite(Number(candidate.metalness)) ? Number(candidate.metalness).toFixed(2) : '-',
          env: Number.isFinite(Number(candidate.env_map_intensity)) ? Number(candidate.env_map_intensity).toFixed(2) : '-',
        })
      : '';
    const probe = materialResponseProbe(materialMode);
    const probeInfo = probe.infoKey ? t(probe.infoKey) : '';
    finishInfo.textContent = `${t('info.finish_all', {codes: codes.join(', ')})}${response ? ` · ${response}` : ''}${probeInfo ? ` · ${probeInfo}` : ''}`;
    return;
  }
  finishInfo.textContent = t('info.finish_filtered', {items: valid.map(item => `${item.surface}=${item.finish_code_raw}`).join(' · ')});
}

function updateLayerInfo(filterName = activeSectionFilter) {
  if (!layerInfo) return;
  const diagnostics = renderContract?.paint_layer_diagnostics || {};
  const selectedSurfaces = paintBindingSurfacesForFilter(filterName);
  const names = selectedSurfaces || Object.keys(diagnostics);
  const records = names.map(name => diagnostics[name]).filter(Boolean);
  if (!records.length) {
    layerInfo.textContent = t('info.layer_unavailable');
    return;
  }
  let count = 0;
  let opaque = 0;
  let semi = 0;
  let white = 0;
  for (const record of records) {
    count += Number(record.shape_count || 0);
    opaque += Number(record.alpha?.opaque_255 || 0);
    semi += Number(record.alpha?.semtransparent_1_254 || 0);
    white += Number(record.near_white_opaque_count || 0);
  }
  layerInfo.textContent = t('info.layer_stats', {
    surfaces: names.join(' + '), count, opaque, semi, white,
  });
}

function enabledForFilter(kind, filterName) {
  const enabled = new Float32Array(SECTION_COUNT);
  for (const section of renderContract.sections || []) {
    if (section.kind !== kind) continue;
    if (filterName === 'all' || section.filter === filterName) {
      enabled[Number(section.slot_index)] = 1;
    }
  }
  return enabled;
}

function setSectionFilter(filterName) {
  activeSectionFilter = filterName;
  const bodyFilter = enabledForFilter('body', filterName);
  const glassFilter = enabledForFilter('glass', filterName);
  paintMaterials.forEach(material => {
    const uniforms = material.uniforms || material.userData?.lo4Uniforms;
    if (uniforms?.enabledSlots) uniforms.enabledSlots.value = bodyFilter;
  });
  glassMaterials.forEach(material => {
    const uniforms = material.uniforms || material.userData?.lo4Uniforms;
    if (uniforms?.enabledSlots) uniforms.enabledSlots.value = glassFilter;
  });
  if (sectionFilterSelect) sectionFilterSelect.value = filterName;
  updateFinishInfo(filterName);
  updateLayerInfo(filterName);
  requestRender();
}

function buildVariantRoot(sourceModel, projectionBounds, paintTexture, masks, variantMode) {
  const [mask0, mask1, mask2] = masks;
  const root = sourceModel.clone(true);
  root.name = `inspection variant ${variantMode}`;
  const variantPaintList = [];
  const variantGlassList = [];
  const materialCache = new Map();
  const neutralMaterials = new Map();
  const wheelTextureDrawn = new Set();
  let wheelTextureRetained = 0;
  let wheelStandardMaterialPainted = 0;
  let wheelPaintOutputColorUnresolved = 0;
  let wheelPaintOutputColorRouteProven = 0;
  let wheelPaintOutputColorRouteMissing = 0;
  let wheelPaintColorResearchApplied = 0;
  const wheelPaintColorResearchRejected = {};
  // 研究ON時のみMesh UUIDを集め、実onBeforeRender提出UUIDと照合する。
  const wheelResearchAppliedUuids = new Set();
  const wheelLipResearchUuids = new Set();
  const bodyMaterialFactory = variantMode === 'asset_routing'
    ? assetRoutingSectionAwareMaterial
    : variantMode === 'asset_routing_r175_baseline'
      ? assetRoutingR175BaselineSectionAwareMaterial
    : variantMode === 'carbon_detail_uv0_probe'
      ? carbonDetailUv0ProbeSectionAwareMaterial
    : variantMode === 'carbon_detail_uv1_probe'
      ? carbonDetailUv1ProbeSectionAwareMaterial
    : variantMode === 'carbon_detail_texture_uv0_probe'
      ? carbonDetailTextureUv0ProbeSectionAwareMaterial
    : variantMode === 'carbon_detail_texture_uv1_probe'
      ? carbonDetailTextureUv1ProbeSectionAwareMaterial
    : variantMode === 'carbon_mask_texture_uv0_probe'
      ? carbonMaskTextureUv0ProbeSectionAwareMaterial
    : variantMode === 'carbon_mask_texture_uv1_probe'
      ? carbonMaskTextureUv1ProbeSectionAwareMaterial
    : variantMode === 'asset_routing_roughness'
      ? assetRoutingRoughnessProbeSectionAwareMaterial
    : variantMode === 'asset_routing_roughness_032'
      ? assetRoutingRoughness032ProbeSectionAwareMaterial
    : variantMode === 'asset_routing_roughness_036'
      ? assetRoutingRoughness036ProbeSectionAwareMaterial
    : variantMode === 'asset_routing_clearcoat'
      ? assetRoutingClearcoatProbeSectionAwareMaterial
    : variantMode === 'asset_routing_ibl'
      ? assetRoutingIblProbeSectionAwareMaterial
    : variantMode === 'base_paint_direct'
      ? basePaintDirectSectionAwareMaterial
    : variantMode === 'base_paint_mask'
      ? basePaintMaskSectionAwareMaterial
    : variantMode === 'reflection_only'
      ? reflectionOnlySectionAwareMaterial
    : variantMode === 'reflection_boost'
      ? reflectionBoostSectionAwareMaterial
    : variantMode === 'physical'
      ? physicalSectionAwareMaterial
    : variantMode === 'basic'
      ? basicSectionAwareMaterial
      : variantMode === 'decal_alpha'
        ? decalAlphaSectionAwareMaterial
        : variantMode === 'decal_luma'
          ? decalLumaSectionAwareMaterial
          : sectionAwareMaterial;
  const glassMaterialFactory = (variantMode === 'carbon_detail_texture_uv0_probe' || variantMode === 'carbon_detail_texture_uv1_probe' || variantMode === 'carbon_mask_texture_uv0_probe' || variantMode === 'carbon_mask_texture_uv1_probe')
    ? sectionAwareMaterial
    : (variantMode === 'decal_alpha' || variantMode === 'decal_luma' || variantMode === 'base_paint_mask' || variantMode === 'base_paint_direct')
    ? bodyMaterialFactory
    : glassMode === 'flat'
      ? sectionAwareMaterial
      : bodyMaterialFactory;
  const liveryMaterial = (kind, allowedSides, projectionSides, directUv, wheelArchProfile = null, sourceFinish = null) => {
    const wheelArchKey = kind === 'body' ? String(wheelArchProfile?.key || 'default') : 'none';
    const finishKey = sourceFinish ? ':original-finish:' + sourceFinish.originalMaterialBindingHash : '';
    const key = `${variantMode}:${kind}:${allowedSides}:${projectionSides}:${directUv ? 1 : 0}:${glassMode}:${wheelArchKey}${finishKey}`;
    if (!materialCache.has(key)) {
      const materialFactory = kind === 'glass' ? glassMaterialFactory : bodyMaterialFactory;
      // Base Paintの色は診断用材質応答モードから独立している。
      // 通常の車体表示ではFH6復号値をすべて維持し、
      // 反射専用・明示的な診断表示でのみ上書きする。
      const decodedBodyColor = rgbaHexToColorNumber(assetRoutingBasePaintColorHex(), 0xc7cbd0);
      const normalBasePaintMode = ['asset_routing', 'asset_routing_r175_baseline', 'carbon_detail_uv0_probe', 'carbon_detail_uv1_probe', 'carbon_detail_texture_uv0_probe', 'carbon_detail_texture_uv1_probe', 'carbon_mask_texture_uv0_probe', 'carbon_mask_texture_uv1_probe', 'base_paint_mask', 'reflection_boost', 'physical', 'basic'].includes(variantMode)
        || ['asset_routing_roughness', 'asset_routing_roughness_032', 'asset_routing_roughness_036', 'asset_routing_clearcoat', 'asset_routing_ibl'].includes(variantMode);
      const routedBodyColor = variantMode === 'base_paint_direct'
        ? decodedBodyColor
        : normalBasePaintMode
          ? homeSoftBasePaintColor(decodedBodyColor, assetRoutingBasePaint())
          : 0xc7cbd0;
      // 旧PR73で実GPU受入した原本材質Hash別の主色を通常表示へ復旧。
      // 入力色0の仕上げ（色を材質自体が持つ）はnullを返すため、車体の基本塗装の色を使う。
      const sourceFinishColor = sourceFinish ? sourceFinishTrialColor(sourceFinish, 'primary-only') : null;
      const bodyBaseColor = sourceFinishColor
        ?? (variantMode === 'reflection_only' ? 0x000000 : routedBodyColor);
      const baseColor = kind === 'glass' ? (glassMode === 'flat' ? 0x24303a : glassOpacityProfileForEnvironment(environmentMode).baseColor) : bodyBaseColor;
      const material = materialFactory(
        paintTexture,
        [mask0, mask1, mask2],
        baseColor,
        kind,
        allowedSides,
        projectionSides,
        projectionBounds,
        directUv,
        kind === 'glass',
        sourceFinish
      );
      if (sourceFinish) {
        material.userData.lo4fh6_source_mesh_finish_standard_auto = {
          original_binding_hash:sourceFinish.originalMaterialBindingHash,
          finish_code_raw:sourceFinish.finish_code_raw,
          required_input_colors:sourceFinish.required_input_colors,
          primary_color_rgba_hex:sourceFinish.primary_color_rgba_hex,
          secondary_color_rgba_hex:sourceFinish.secondary_color_rgba_hex,
          applied_source_color_slot:'primary',
          native_two_color_shader_applied:false,
          windows_visual_review_required:true,
        };
      }
      if (kind === 'body') applyWheelArchSuppressionProfileToMaterial(material, wheelArchProfile || wheelArchSuppressionProfileForMesh(null));
      // 未承認Facing候補を実行時切替にせず、受入済みの通常DoubleSideを維持。
      if (kind === 'glass') material.side = THREE.DoubleSide;
      materialCache.set(key, material);
      (kind === 'glass' ? variantGlassList : variantPaintList).push(material);
    }
    return materialCache.get(key);
  };

  let paintCount = 0;
  const sourceNeutralRoleCounts = {};
  viewerEvent('appearance-defaults', '', {sourceMaterial:sourceNeutralResearch, neutralLiveryGrade:sourceLiveryNeutralResearch, defaultOn:true, runtimeSwitches:false});
  if (sourceLiveryNeutralResearch) viewerEvent('source-livery-neutral-research', '', {originalGrade:liveryColorGradeForEnvironment('studio'),neutralizedColorGrade:true,lightsUnchanged:true,exposureUnchanged:true,xboxApproved:false});
  let glassCount = 0;
  let meshCount = 0;
  // 原本マテリアルの署名が存在するときだけFEOW経路を選ぶ。車種IDでは分岐しない。
  const sourceTireDxilAutoApply = shouldAutoApplySignedFeow(root, wheelSource);
  const sourceTireDxilAudit = sourceTireDxilAutoApply ? auditOriginalDxilTwoTextures(root) : null;
  // 通常GUIでは原本材質をOFFにしない。開発URLで明示OFFの場合は
  // FEOW原本画像の不一致と混同せず、未対応の組合せとして説明して停止する。
  if (sourceTireDxilAutoApply && !sourceNeutralResearch) {
    throw new Error('開発用の原本材質OFFは、確認済み原本FEOW側面文字との併用に対応していません。通常表示では原本材質ONで使用してください。');
  }
  if (sourceTireDxilAutoApply && !sourceTireDxilAudit?.ok) {
    const issues = Array.isArray(sourceTireDxilAudit?.issues) && sourceTireDxilAudit.issues.length
      ? sourceTireDxilAudit.issues : ['FEOW原本二画像の署名監査に失敗（詳細項目なし）'];
    throw new Error('原本FEOW-DXIL二画像の材質・出典不一致: ' + JSON.stringify(issues));
  }
  let sourceTireDxilApplied = 0;
  let sourceTireOriginalNormalRetained = 0;
  let sourceTireNormalAutoRetained = 0;
  let sourceTireCompoundAutoRetained = 0;
  // 側面文字あり（原本TextSwitch=1）の側面は、複合材質を掛けずNormalのみで残す（Python側で署名）。
  let sourceTireTextSidewallNormalOnly = 0;
  let sourceTireNeutralMaterialInstances = 0;
  const sourceTireNormalExpectedClaims = [];
  const sourceTireNormalWheelClaims = [];
  const sourceTireFeowWheelClaims = [];
  const wheelArchSuppressionProfiles = {};
  let sourceMirrorHousingCompared = 0;
  let sourceMirrorFactoryStandardApplied = 0;
  let sourceMirrorOriginalGlbRetained = 0;
  let sourceBodyTrimColorApplied = 0;
  const sourceBodyTrimMisses = [];
  const sourceBodyTrimApplied = [];
  const sourceMirrorOriginalGlbReasons = {};
  const sourceAccessoryReviewCounts = {};
  let sourceNonPaintTrimGuarded = 0;
  root.traverse(child => {
    if (!child.isMesh) return;
    meshCount += 1;
    const category = meshCategory(child);
    if (child.userData?.lo4fh6_mirror_housing_source_compare === true)
      sourceMirrorHousingCompared++;
    const accessoryClass = child.userData?.lo4fh6_source_accessory_compare;
    if (accessoryClass)
      sourceAccessoryReviewCounts[accessoryClass] = (sourceAccessoryReviewCounts[accessoryClass] || 0) + 1;
    if (child.userData?.lo4fh6_source_nonpaint_trim_guarded)
      sourceNonPaintTrimGuarded++;
    if (sourceNeutralResearch) {
      const evidence = sourceNeutralMaterialRole(child);
      const role = evidence.role || evidence.reason;
      sourceNeutralRoleCounts[role] = (sourceNeutralRoleCounts[role] || 0) + 1;
      if (evidence.role) child.userData.lo4fh6_research_source_material_role = evidence.role;
    }
    child.userData.lo4_base_visible = category !== 'hidden';
    child.visible = child.userData.lo4_base_visible && meshPartVisible(child);
    // 車種共通：署名済WheelStyleはpaint/glass等の名前分類よりも原本を優先。
    // GLB/GLTFLoader/UV署名が全一致したWheelだけを保持し、未署名への代替はしない。
    if (wheelSource === 'source-verified' && sourceNeutralResearch
        && retainVerifiedSourceWheelMap(child, wheelTextureDrawn)) {
      // MaterialBin/ShaderBinのBaseColorAlpha_Textureは真正Swatchだが、
      // car_automotive_paintのg_CarUserColor0合成後の完成色ではない。
      // 元GLTFLoader材質はそのまま維持し、誤った「色確認済み」を防ぐ。
      if (child.material?.userData?.lo4fh6_wheel_paint_output_color_unresolved === true) {
        wheelPaintOutputColorUnresolved++;
        // 署名済みGLBのModelBin/materialIdと外部g_CarUserColor0を結ぶ
        // 既存の厳密ルートだけ使う。ここでは色を適用せず入力証拠を計数する。
        const routed = wheelPaintColorForMesh(child);
        if (routed?.routeSource === 'material-id-evidence')
          wheelPaintOutputColorRouteProven++;
        else
          wheelPaintOutputColorRouteMissing++;
        // 原本map/UV/Shader署名を保持。出典済み自動ルート以外は通常表示しない。
        // リップ等（lip・rim3・detail・detail2）の組にペイントの記録が無く、原本 MatI の既定色になったときは、
        // 先に軸の第 1 のホイールの塗装（検証済みの補助の経路）を使う。参照製品と同じ順番。
        // 2026-11-18：Car 3128 のゲームのサムネイルで、記録の無いリップ（ビードロックのリング）は軸の
        // ホイールの色（黒）だった（原本 MatI の既定色は黄緑）。ホイールの記録が無いペイントは既定色のまま。
        const genericPrimaryRoute = (!routed || routed.colorOrigin === 'original-wheel-mati-default')
          ? wheelGenericPrimaryColorForMesh(child) : null;
        const previewRoute = genericPrimaryRoute || routed;
        const finishRecord = renderContract?.wheel_paint_colors?.groups?.[previewRoute?.group];
        // 原本MaterialBin/ShaderBin SHA・MatI外部色入力が一致するなら
        // NormalPaint ID1も通常接続。原本Swatchの緑RGBを完成塗装と誤認しない。
        const signedDecision = sourceWheelStandardAutoEligible(previewRoute, finishRecord);
        const signedStandard = sourceWheelStandardAutoEnabled && signedDecision.ok;
        let sourceWheelPaintApplied = false;
        let sourceWheelPaintRejectReason = signedDecision.reason;
        if (signedStandard) {
          const finishEvidence = wheelFinishDecision(finishRecord, {
            hasExactMeshRoute: sourceWheelFinishHasExactMeshRoute(previewRoute),
          });
          // 単一標準入口。研究用の強制実行分岐を介さず元署名で自動判定。
          const preview = sourceWheelPrimaryPaintStandard(child, previewRoute, {finishEvidence});
          if (preview.status === 'source-signed-applied') {
            child.material = trackMaterial(preview.material);
            child.userData.lo4fh6_wheel_paint_primary_standard = true;
            child.userData.lo4fh6_wheel_paint_finish_research = preview.finishName;
            sourceWheelPaintApplied = true;
            if (previewRoute?.fallbackEvidence)
              child.userData.lo4fh6_wheel_paint_fls_fallback_research = previewRoute.fallbackEvidence;
            wheelPaintColorResearchApplied++;
            // 標準署名ルートの実GPU提出もUUIDで照合する。
            wheelResearchAppliedUuids.add(child.uuid);
            if (previewRoute?.routeSource === 'source-signed-generic-primary' && previewRoute?.token === 'lip')
              wheelLipResearchUuids.add(child.uuid);
          } else {
            sourceWheelPaintRejectReason = preview.reason;
            wheelPaintColorResearchRejected[preview.reason] =
              (wheelPaintColorResearchRejected[preview.reason] || 0) + 1;
          }
        }
        if (child.visible && !sourceWheelPaintApplied) {
          // 不明なWheelPaintを緑Swatchや推測RGBで描画PASSにしない。
          // 各原本ModelBin+MatIの署名不一致位置を一度のWindows GPUログで特定する。
          const failureReason = String(sourceWheelPaintRejectReason
            || 'wheel-original-material-signature-unavailable');
          const meshSource = String(wheelMetadataForMesh(child, 'lo4_source_entry') || '');
          const materialId = wheelMetadataForMesh(child, 'lo4_wheel_material_id');
          const materialName = String(wheelMetadataForMesh(child, 'lo4_wheel_material_name') || '');
          const sourceKey = normalizedSourceEntry(meshSource);
          const exactSourceRows = wheelPaintEvidenceRows().filter(
            row => normalizedSourceEntry(String(row?.source_entry || '')) === sourceKey
          );
          const materialRows = exactSourceRows.filter(row => (
            materialId !== null && materialId !== undefined && materialId !== ''
            && Number(row?.material_id) === Number(materialId)
          ));
          const sourceRouteEvidence = {
            sourceEntry: meshSource,
            materialId: materialId ?? null,
            materialName,
            exactSourceRows: exactSourceRows.length,
            sourceMaterialIdRows: materialRows.length,
            candidateGroup: previewRoute?.group ?? null,
            originalGreenSwatchSourceInput:
              child.material?.userData?.lo4fh6_wheel_paint_original_green_source_input === true,
            reason: failureReason,
            xboxApproved: false,
          };
          viewerEvent('wheel-paint-route-unsigned-source-evidence',
            failureReason, sourceRouteEvidence);
          throw new Error('原本WheelPaintの完成色を解決できません: ' + failureReason
            + ' [原本材質ID=' + String(sourceRouteEvidence.materialId)
            + ',原本Source一致=' + exactSourceRows.length
            + ',Source+MatI一致=' + materialRows.length + ']');
        }
      }
      // 外部の色の入力を持たない標準の材質（car_standard）のホイールの部品（rim 等）も、ペイントの
      // ホイールの記録が有効なら、その色と仕上げで描く（standardWheelPaintMaterial）。記録が無ければ原本のまま。
      const standardPaint = child.material?.userData?.lo4fh6_wheel_paint_output_color_unresolved === true
        ? null : standardWheelPaintMaterial(child);
      if (standardPaint) {
        child.material = trackMaterial(standardPaint.material);
        child.userData.lo4fh6_wheel_standard_material_paint = standardPaint.group;
        child.userData.lo4_wheel_paint_color = standardPaint.colorHex;
        wheelStandardMaterialPainted++;
      }
      wheelTextureRetained++;
      return;
    }
    if (category === 'paint') {
      const directUv = Boolean(child.geometry.getAttribute('uv3'));
      const wheelArchProfile = wheelArchSuppressionProfileForMesh(child);
      const sourceFinish = variantMode === 'asset_routing' && sourceMeshFinishVerifiedGroups
        ? partOptionSafeFinish(child, () => sourceMeshFinishForPaintMesh(child.userData, sourceMeshFinishVerifiedGroups))
        : null;
      child.material = liveryMaterial(
        'body',
        meshAllowedSides(child, category),
        meshProjectionSides(child),
        directUv,
        wheelArchProfile,
        sourceFinish
      );
      child.userData.lo4_wheel_arch_suppression_profile = wheelArchProfile.key;
      wheelArchSuppressionProfiles[wheelArchProfile.key] = (wheelArchSuppressionProfiles[wheelArchProfile.key] || 0) + 1;
      paintCount += 1;
    } else if (category === 'glass') {
      const directUv = Boolean(child.geometry.getAttribute('uv3'));
      child.material = liveryMaterial(
        'glass',
        meshAllowedSides(child, category),
        meshProjectionSides(child),
        directUv
      );
      child.renderOrder = 2;
      glassCount += 1;
    } else if (category === 'hidden') {
      child.visible = false;
    } else {
      // 実ゲームのCB4/CB11実値がないため、明示研究起動時の模擬値でのみ
      // FEOW原本PS/VSO文字式をsidewall4メッシュに適用。車体・原本Wheel20・Treadは不変。
      // 文字MatIは役割名（sidewall/whitewall等）でなくPython側の原本文字署名で判定する。
      if (sourceTireDxilAutoApply && child.userData?.lo4_part_type === 'Tire'
          && child.material?.userData?.lo4fh6_original_feow_two_textures === true) {
        const e = child.material?.userData || {};
        child.material = trackMaterial(createDxilVsPsResearchMaterial(THREE, child, {
          sourceVerifiedAutomatic:true,
          shaderPsoSha:e.feow_dxil_shader_pso_sha256,
          shaderVsoSha:e.feow_dxil_shader_vso_sha256,
          texture30SwatchSha:e.feow_dxil_t30_swatch_sha256,
          texture29SwatchSha:e.feow_dxil_t29_swatch_sha256,
          // 原本MatI→親MaterialBin→ShaderBin DFPRで解決した値（FEOWは0.25,1.2/-0.28）。
          tiling:e.lo4fh6_source_text_uv_tiling,slide:e.lo4fh6_source_text_slide,
          runtimeSource:'synthetic-research-not-xbox',wheelParam:16,wheelBlend:0.5,
          xboxApproved:false,productDefaultChanged:true,
        }));
        child.userData.lo4fh6_feow_signed_auto_applied = true;
        sourceTireFeowWheelClaims.push({
          wheel:child.userData.lo4_tire_source_wheel,
          sourceModelbinSha256:child.userData.lo4_tire_original_modelbin_sha256,
          materialId:child.userData.lo4_tire_original_material_id,
        });
        sourceTireDxilApplied++;
        return;
      }
      // 原本MatI/ShaderBin/BC5+MeshBlob UVが揃ったTire Normal研究材質のみ、
      // GLTFLoaderで正常に生成されたnormalMapを維持。原本FEOWの4輪処理より後順位。
      // 署名済み研究GLB以外の通常タイヤ・Wheel・車体材質には一切影響しない。
      if (child.userData?.lo4_part_type === 'Tire'
          && child.material?.userData?.lo4fh6_original_tire_normal_research === true) {
        const proof = child.material.userData;
        if (wheelSource !== 'source-verified' || !sourceNeutralResearch
            || proof.shader_equivalent !== false || proof.xbox_approved !== false
            || !/^[0-9a-f]{64}$/.test(String(proof.source_swatch_sha256 || ''))
            || !child.material.normalMap || !child.geometry?.getAttribute('uv')) {
          throw new Error('原本Tire Normal研究材質のGLTFLoader/MatI/Shader署名が不一致');
        }
        sourceTireOriginalNormalRetained++;
        sourceTireNormalExpectedClaims.push(proof.lo4fh6_source_original_tire_normal_expected_mesh_count);
        // 新GLBでは元ModelBin LOD0の輪別Material-ID/役割数もGPU保持時に監査する。
        // 旧Windows受入済みGLBに本署名が無い場合は従来の12/16互換を維持。
        if (proof.lo4fh6_source_original_tire_normal_expected_wheel_role_count !== undefined) {
          sourceTireNormalWheelClaims.push({
            wheel: child.userData?.lo4_tire_source_wheel
              ?? child.geometry?.userData?.lo4_tire_source_wheel,
            sourceModelbinSha256: proof.source_modelbin_sha256,
            materialId: proof.source_original_mati_id,
            expectedWheelRoleCount: proof.lo4fh6_source_original_tire_normal_expected_wheel_role_count,
          });
        }
        if (proof.lo4fh6_source_signed_normal_auto === true) sourceTireNormalAutoRetained++;
        // NormalとExtra/BlurがGLTFLoader最終材質で両方保持された輪のみ計数。
        if (proof.lo4fh6_tire_source_rgba_compound_research === true
            && renderContract?.lo4fh6_source_tire_standard_required === 'original-normal-compound-source-signed-v1') {
          if (proof.lo4fh6_source_signed_normal_auto !== true
              || !child.material.aoMap || !child.material.roughnessMap
              || !['source_extra_swatch_sha256',
                   'source_blur_extra_swatch_sha256',
                   'source_blur_normal_swatch_sha256'].every(key =>
                      /^[0-9a-f]{64}$/.test(String(proof[key] || '')))) {
            throw new Error('統合Tireの原本Normal/Extra/BlurがGLTFLoaderで保持されていません');
          }
          sourceTireCompoundAutoRetained++;
        } else if (proof.source_text_sidewall_compound_skipped === true
            && proof.original_text_switch === 1
            && proof.lo4fh6_source_signed_normal_auto === true
            && renderContract?.lo4fh6_source_tire_standard_required === 'original-normal-compound-source-signed-v1') {
          // 原本TextSwitch=1の側面は文字を潰さないよう複合を掛けない。Normalのみ保持を確認して数える。
          sourceTireTextSidewallNormalOnly++;
        }
        child.userData.lo4fh6_tire_original_normal_research_retained = true;
        return;
      }
      // 署名済WheelはRole判定より先に保持済み。ここでは未証明材質のみ扱う。
      // 未署名Tireが初期仮材質→中立表示材質へ変更されても、
      // 原本Shader非適用という事実をGPU検査まで保持する。
      // 原本Normal/FEOWの署名済み経路は上のreturnで保護済み。
      if (child.userData?.lo4_part_type === 'Tire'
          || child.geometry?.userData?.lo4_part_type === 'Tire') {
        const originalName = String(child.material?.name || '');
        if (originalName === 'Local-source-tire-research-neutral'
            || originalName.startsWith('PRIVATE-diagnostic-original-tire-not-game-shader')) {
          child.userData.lo4fh6_original_tire_diagnostic_material_retained = true;
          sourceTireNeutralMaterialInstances++;
        }
      }
      const profile = neutralSurfaceProfile(child, category);
      if (profile === 'source_mirror_original_glb') {
        // 元GLTFLoaderの原本材質だけを保持。C_liveryの車体ピンクや
        // 未証明の工場白RGBを推測適用しない。材質実体が欠ければ明示エラー。
        const originals = Array.isArray(child.material) ? child.material : [child.material];
        if (!originals.length || originals.some(mat => !mat?.isMaterial))
          throw new Error('原本Mirror工場色候補がなく、保持するGLB材質もありません');
        const unavailable = child.userData.lo4fh6_mirror_factory_preview_unavailable;
        sourceMirrorOriginalGlbReasons[unavailable] = (sourceMirrorOriginalGlbReasons[unavailable] || 0) + 1;
        child.userData.lo4fh6_mirror_original_glb_material_retained = true;
        sourceMirrorOriginalGlbRetained++;
        return;
      }
      if (child.userData?.lo4fh6_signed_mirror_factory_color)
        sourceMirrorFactoryStandardApplied++;
      const wheelPaint = wheelPaintMaterialOptions(child, profile);
      // 原本の材質インスタンスはモデルファイルごとにmaterialIdが別空間。
      // 他製品と同じく部品(出典ModelBin)+材質スロットを一組で扱う。
      // 未承認研究ONのみに適用し、通常版のマテリアルcacheは完全不変。
      const originalMaterialProof = sourceNeutralResearch ? sourceNeutralMaterialRole(child) : null;
      const materialInstanceKey = originalMaterialProof?.role
        ? `:source:${normalizedSourceEntry(child.userData?.lo4_source_entry || child.userData?.source_archive_member || child.geometry?.userData?.lo4_source_entry || child.name)}:${originalMaterialProof.materialId ?? 'name-only'}:${originalMaterialProof.material}`
        : '';
      const bodyTrim = wheelPaint ? null : sourceBodyTrimColor(child, profile);
      if (!wheelPaint && !bodyTrim && sourceBodyTrimMisses.length < 40) {
        // 原本の色を使わなかった部品の記録（診断用。中立色のまま描く）。
        sourceBodyTrimMisses.push({
          mesh: String(child.userData?.lo4_source_mesh_name || child.name || '').slice(0, 80),
          profile, category,
          sha: String(child.userData?.lo4fh6_original_material_sha256 || '').slice(0, 12),
        });
      }
      const materialKey = wheelPaint
        ? `${profile}:wheel:${wheelPaint.routed.group}:${wheelPaint.routed.colorHex}:${wheelPaint.materialKeySuffix}${materialInstanceKey}`
        : `${profile}${materialInstanceKey}${bodyTrim ? ':bodytrim:' + bodyTrim.hex : ''}`;
      if (!neutralMaterials.has(materialKey)) {
        neutralMaterials.set(materialKey, trackMaterial(new THREE.MeshPhysicalMaterial(
          wheelPaint?.options
            || (bodyTrim?.lensProfile ? {...neutralSurfaceMaterialOptions(bodyTrim.lensProfile),
              ...(Number.isInteger(bodyTrim.lensColor) ? {color: bodyTrim.lensColor} : {})}
              // ランプの枠・反射板は不透明（レンズ用プロファイルの透過は使わない）。
              : bodyTrim ? {...neutralSurfaceMaterialOptions(SOURCE_LAMP_PROFILES.has(profile) ? 'trim' : profile),
                color: bodyTrim.color,
                ...(bodyTrim.texture ? {map: sourceBodyTrimTextureView(bodyTrim)} : {}),
                ...(bodyTrim.opacity ? {transparent: true, opacity: bodyTrim.opacity, depthWrite: false} : {}),
                ...(bodyTrim.alphaTexture ? {transparent: true, depthWrite: false, alphaTest: 0.02} : {})}
                : neutralSurfaceMaterialOptions(profile))
        )));
      }
      child.material = neutralMaterials.get(materialKey);
      if (bodyTrim) {
        child.userData.lo4fh6_body_trim_original_color = bodyTrim.hex;
        sourceBodyTrimColorApplied++;
        if (sourceBodyTrimApplied.length < 40)
          sourceBodyTrimApplied.push({
            mesh: String(child.userData?.lo4_source_mesh_name || child.name || '').slice(0, 80),
            profile, color: bodyTrim.hex,
          });
      }
      if (wheelPaint) {
        child.userData.lo4_wheel_paint_applied = true;
        child.userData.lo4_wheel_paint_group = wheelPaint.routed.group;
        child.userData.lo4_wheel_paint_color = wheelPaint.routed.colorHex;
        child.userData.lo4_wheel_paint_finish_code = wheelPaint.routed.finishCode;
        child.userData.lo4_wheel_paint_route_source = wheelPaint.routed.routeSource || '';
        child.userData.lo4_wheel_paint_finish_material = wheelPaint.routed.finishMaterial?.materialName || '';
        child.userData.lo4_wheel_paint_finish_roughness = wheelPaint.routed.finishMaterial?.roughness ?? null;
        child.userData.lo4_wheel_paint_finish_metalness = wheelPaint.routed.finishMaterial?.metalness ?? null;
        child.userData.lo4_wheel_paint_finish_clearcoat = wheelPaint.routed.finishMaterial?.clearcoat ?? null;
        child.userData.lo4_wheel_paint_finish_clearcoat_roughness = wheelPaint.routed.finishMaterial?.clearcoatRoughness ?? null;
        child.userData.lo4_wheel_paint_finish_env_map_intensity = wheelPaint.routed.finishMaterial?.envMapIntensity ?? null;
      }
    }
  });
  // 標準原本Normalを採用した車両では、同じ最終シーン内のTireを
  // 過去の診断用ラバーへ部分的に戻して「表示成功」としない。
  // FEOWだけの旧受入経路、未対応Tire単体の診断表示はここでは変更しない。
  // Pythonが通常入口で原本Normalを構築したと宣言したのに、
  // GLTFLoader/Viewer側で旧材質を描画してしまう完全後退も成功扱いしない。
  const feowNormalContract = renderContract?.lo4fh6_source_tire_standard_required
    === 'original-feow-sidewall-plus-normal-source-signed-v1';
  // 側面文字は4輪×文字MatI数（FEOWは4、OW_b_Horizon等は8）。
  if (feowNormalContract && (sourceTireDxilApplied < 4 || sourceTireDxilApplied % 4 !== 0
      || sourceTireNormalAutoRetained === 0)) {
    throw new Error('FEOW側面4輪と原本Tire Normalが揃いません。旧ラバー材質への後退を拒否');
  }
  if (sourceTireDxilApplied > 0 && sourceTireNormalAutoRetained > 0 && !feowNormalContract) {
    throw new Error('FEOW側面文字とTire Normalの未署名混在を拒否');
  }
  if ((renderContract?.lo4fh6_source_tire_standard_required === 'original-normal-source-signed-v1'
       || renderContract?.lo4fh6_source_tire_standard_required === 'original-normal-compound-source-signed-v1'
       || feowNormalContract)
      && (wheelSource !== 'source-verified' || sourceTireNormalAutoRetained === 0)) {
    throw new Error('原本Tire Normalの標準生成結果がViewerに接続されていません。'
      + '旧GLB・旧材質への後退を拒否');
  }
  if (wheelSource === 'source-verified' && sourceTireNormalAutoRetained > 0
      && sourceTireNeutralMaterialInstances > 0) {
    throw new Error('署名済み原本Tire Normalと旧診断用ラバー材質が混在。'
      + '旧材質への無告知後退を拒否: 原本Normal=' + sourceTireNormalAutoRetained
      + ' 診断Tire=' + sourceTireNeutralMaterialInstances);
  }
  if (sourceTireNeutralMaterialInstances > 0 && wheelSource === 'source-verified') {
    const materialWarning = {
      diagnosticTireMeshCount: sourceTireNeutralMaterialInstances,
      originalModelBinGeometryMayBePresent: true,
      originalTireShaderMaterialNotVerified: true,
      xboxAppearanceApproved: false,
    };
    viewerEvent('source-tire-neutral-material-unverified', '', materialWarning);
    appendDistinctAssemblyDiagnosticLine(
      '【材質未確認】原本Tireの診断用ラバー材質が '
      + sourceTireNeutralMaterialInstances
      + ' メッシュで残っています。原本ModelBin形状の表示とFH6材質再現は別判定です。');
  }
  if (sourceTireDxilAutoApply) {
    if (sourceTireDxilApplied !== sourceTireDxilAudit.sidewalls || sourceTireDxilApplied < 4)
      throw new Error('FEOW原本二画像側面材質4輪の保持数不一致');
    lo4fh6BuildId.sidewallMaterialsApplied = sourceTireDxilApplied;
    if (lo4fh6ModeLabel) lo4fh6ModeLabel.textContent = '描画モード: 原本側面文字 自動適用 ' + sourceTireDxilApplied + '/' + sourceTireDxilAudit.sidewalls;
    window.__lo4fh6FeowDxilResearch = {...sourceTireDxilAudit,
      applied:sourceTireDxilApplied,carParams:'APPROXIMATED_SOURCE_DERIVED',
      wheelParam:16,blend:0.5,sourceTexturesVerified:true,
      productDefaultChanged:true,xboxApproved:false};
    viewerEvent('tire-feow-dxil-standard','',window.__lo4fh6FeowDxilResearch);
    assemblyInfo.textContent += '\n【確認済み標準接続】原本側面文字4輪（原本MatI署名、CB4推定値、Xbox外観差は別途評価）';
  }
  if (sourceTireOriginalNormalRetained > 0) {
    // 原本の車輪がちょうど 4 つの角でない車（3 輪・6 輪）は、変換の段階が WheelStyle に印（偽）を付ける。
    let sourceWheelNonStandardRoles = false;
    root.traverse(child => {
      const flag = child.userData?.lo4fh6_feow_standard_four_corner_eligible
        ?? child.userData?.lo4_feow_standard_four_corner_eligible;
      if (flag === false) sourceWheelNonStandardRoles = true;
    });
    const normalGate = sourceTireNormalCountGate({
      retained:sourceTireOriginalNormalRetained,
      autoRetained:sourceTireNormalAutoRetained,
      dxilApplied:sourceTireDxilApplied,
      claims:sourceTireNormalExpectedClaims,
      wheelClaims:sourceTireNormalWheelClaims,
      feowWheelClaims:sourceTireFeowWheelClaims,
      nonStandardWheelRoles:sourceWheelNonStandardRoles,
    });
    if (renderContract?.lo4fh6_source_tire_standard_required === 'original-normal-compound-source-signed-v1'
        && sourceTireCompoundAutoRetained + sourceTireTextSidewallNormalOnly !== normalGate.expected) {
      throw new Error('原本Tire複合材質のLOD0材質が不足または旧材質へ後退: 原本='
        + normalGate.expected + ' 実保持=' + sourceTireCompoundAutoRetained
        + ' 文字側面Normalのみ=' + sourceTireTextSidewallNormalOnly);
    }
    const normalStandard = normalGate.standard;
    const normalReport = {schema:'lo4fh6.tire.source-normal-pbr-research.v1',
      retained:sourceTireOriginalNormalRetained, expected:normalGate.expected, sourcedImagesOnly:true,
      sourceSignedAutoNormalRetained:sourceTireNormalAutoRetained,
      sourceSignedCompoundRGBA:sourceTireCompoundAutoRetained,
      sourceTextSidewallNormalOnly:sourceTireTextSidewallNormalOnly,
      compoundPbrShaderEquivalent:false,
      sourceUV:'MeshBlob-UV0-affine-research', shaderEquivalent:false,
      xboxApproved:false, productDefaultChanged:normalStandard};
    window.__lo4fh6TireOriginalNormalResearch = normalReport;
    viewerEvent(normalStandard ? 'source-tire-original-normal-standard'
      : 'source-tire-original-normal-research', variantMode || '', normalReport);
    appendDistinctAssemblyDiagnosticLine(
      `原本Tire法線${normalStandard ? '標準自動' : '研究'}: 4輪原本${normalGate.expected}材質 / 原本Normal＋UV0 affine・GPU材質保持 ${sourceTireOriginalNormalRetained}（Xbox・Shader全式未承認）`);
  }
  if (renderContract?.body_trim_colors) {
    const counts = renderContract.body_trim_colors.counts || {};
    const report = {
      schema:'lo4fh6.body-trim-original-color.applied.v1',
      appliedMeshCount:sourceBodyTrimColorApplied,
      sourceMaterials:counts.materials ?? null, resolvedMaterials:counts.resolved ?? null,
      unresolved:counts.unresolved || {}, gameShaderExact:false, xboxApproved:false,
      appliedSample:sourceBodyTrimApplied, neutralSample:sourceBodyTrimMisses,
      texturesLoaded:sourceBodyTrimTextures.size, textureFailures:sourceBodyTrimTextureFailures,
    };
    window.__lo4fh6SourceBodyTrimColor = report;
    viewerEvent('source-body-trim-original-color', variantMode || '', report);
    appendDistinctAssemblyDiagnosticLine(
      `車体の非塗装部品：原本MatIの色 ${sourceBodyTrimColorApplied} mesh（原本材質 ${counts.resolved ?? '?'}/${counts.materials ?? '?'}、残りは従来の中立色。Shader・Xbox外観は未承認）`);
  }
  if (sourceMirrorOriginalGlbRetained > 0) {
    const report = {
      schema:'lo4fh6.source-mirror-factory.original-glb-retained.v1',
      retainedMeshCount:sourceMirrorOriginalGlbRetained,
      paletteUnavailableReasons:{...sourceMirrorOriginalGlbReasons},
      originalGlbMaterialUnchanged:true,
      factoryPreviewApplied:false,gameShaderExact:false,xboxApproved:false,
    };
    window.__lo4fh6SourceMirrorOriginalGlbRetained = report;
    viewerEvent('source-mirror-original-glb-retained', variantMode || '', report);
    appendDistinctAssemblyDiagnosticLine(
      `原本Mirror工場色候補が未確認: ${sourceMirrorOriginalGlbRetained} meshは元GLB材質を保持（工場色・Shader・Xbox外観は未承認）`);
  }
  if (sourceMirrorFactoryStandardApplied > 0) {
    const report = {
      schema:'lo4fh6.source-mirror-factory.standard-route.v1',
      original:'ModelBin+MatI+UV3+ManufacturerColors Mirror slot0',
      appliedMeshCount:sourceMirrorFactoryStandardApplied,
      gameShaderExact:false,saveStateSelectorProven:false,
      windowsMirrorVisualPreviouslyAccepted:true,
    };
    window.__lo4fh6SourceMirrorFactoryStandard = report;
    viewerEvent('source-mirror-factory-standard', variantMode || '', report);
    appendDistinctAssemblyDiagnosticLine(
      `原本Mirror工場色の標準適用: ${sourceMirrorFactoryStandardApplied} mesh（署名付き、Shader同値未証明）`);
  }
  // 表示に影響しない元MatI照合件数のみ標準診断として記録する。
  if (sourceAccessoryStandardAutoEnabled) {
    const mirrorReport = {
      schema:'lo4fh6.mirror_housing.source_diagnostic.v1',
      modelBinMatIValidatedCount:sourceMirrorHousingCompared,
      previewCategory:'trim',previewMaterialProfile:'source_body_color',
      sourceOnly:true,shaderParityApproved:false,xboxApproved:false,
      productDefaultChanged:false,
    };
    window.__lo4fh6MirrorHousingSourceCompare = mirrorReport;
    viewerEvent('source-mirror-housing-compare', variantMode || '', mirrorReport);
    appendDistinctAssemblyDiagnosticLine(
      `ミラーカバー原本材質比較: MatI署名 ${sourceMirrorHousingCompared} mesh（研究のみ・Xbox未承認）`);
  }
  if (sourceNeutralResearch) {
    window.__rm054SourceNeutralMaterialResearch = {
      roles: sourceNeutralRoleCounts, defaultChanged: false, xboxApproved: false,
      realMaterialNamesRequired: true, sourceSpecificColors: false,
    };
    viewerEvent('source-neutral-material-research', '', window.__rm054SourceNeutralMaterialResearch);
  }
  if (wheelSource === 'source-verified' && sourceNeutralResearch) {
    // GLTFLoaderで読めた原本画像を失わせた場合は灰色で成功扱いしない。
    if (sourceWheelMaterialAudit.glb !== wheelTextureRetained) {
      throw new Error(`原本Wheelテクスチャがシーン生成中に消失: GLB=${sourceWheelMaterialAudit.glb} 保持=${wheelTextureRetained}`);
    }
    sourceWheelMaterialAudit.variants.set(variantMode, {
      retained:wheelTextureRetained, drawn:wheelTextureDrawn, reported:false,
      unresolvedPaintOutputColor:wheelPaintOutputColorUnresolved,
      provenPaintInputRoutes:wheelPaintOutputColorRouteProven,
      unresolvedPaintInputRoutes:wheelPaintOutputColorRouteMissing,
      standardMaterialPainted:wheelStandardMaterialPainted,
      researchApplied:wheelPaintColorResearchApplied,
      researchRejected:{...wheelPaintColorResearchRejected},
      researchAppliedUuids:wheelResearchAppliedUuids,
      lipFallbackUuids:wheelLipResearchUuids,
    });
  }
  const stockWheelAssets = stockWheelAssetInventory(root);
  stockWheelAssetInventories.set(variantMode || String(stockWheelAssetInventories.size), stockWheelAssets);
  if (variantMode === 'physical') {
    viewerEvent('wheel-arch-suppression', '', { profiles: wheelArchSuppressionProfiles });
    viewerEvent('wheel-paint-application', '', {
      appliedMeshCount: stockWheelAssets.wheelPaintAppliedMeshCount,
      routableMeshCount: stockWheelAssets.wheelPaintRoutableMeshCount,
      unresolvedMeshCount: stockWheelAssets.wheelPaintUnroutedMeshCount,
      noColorMeshCount: stockWheelAssets.wheelPaintNoColorMeshCount,
      groups: stockWheelAssets.wheelPaintAppliedGroups,
      colors: stockWheelAssets.wheelPaintAppliedColors,
      routeSources: stockWheelAssets.wheelPaintRouteSources,
      materialTokens: stockWheelAssets.wheelPaintMaterialTokens,
      finishAppliedMeshCount: stockWheelAssets.wheelPaintFinishAppliedMeshCount,
      finishMaterials: stockWheelAssets.wheelPaintFinishMaterials,
      finishCandidates: stockWheelAssets.wheelPaintFinishCandidates,
    });
    if (assemblyInfo) {
      const deepFront = Number(wheelArchSuppressionProfiles['deep-front-fenders'] || 0);
      const deepRear = Number(wheelArchSuppressionProfiles['deep-rear-body'] || 0);
      if (deepFront > 0 || deepRear > 0) {
        assemblyInfo.textContent += `
${t('info.wheel_arch_suppression', { front: deepFront, rear: deepRear })}`;
      }
    }
    if (assemblyInfo && stockWheelAssets.wheelStyleMeshCount > 0) {
      const colors = Object.keys(stockWheelAssets.wheelPaintAppliedColors).join(', ') || '-';
      assemblyInfo.textContent += `\n${t('info.wheel_paint_application', {
        applied: stockWheelAssets.wheelPaintAppliedMeshCount,
        routable: stockWheelAssets.wheelPaintRoutableMeshCount,
        wheelstyle: stockWheelAssets.wheelStyleMeshCount,
        unresolved: stockWheelAssets.wheelPaintUnroutedMeshCount,
        nocolor: stockWheelAssets.wheelPaintNoColorMeshCount,
        colors,
      })}`;
      if (stockWheelAssets.wheelPaintFinishAppliedMeshCount > 0) {
        const materials = Object.keys(stockWheelAssets.wheelPaintFinishMaterials).join(', ') || '-';
        const candidates = Object.keys(stockWheelAssets.wheelPaintFinishCandidates).join(' / ') || '-';
        assemblyInfo.textContent += `\n${t('info.wheel_paint_finish_application', {
          applied: stockWheelAssets.wheelPaintFinishAppliedMeshCount,
          materials,
          candidates,
        })}`;
      }
      assemblyInfo.classList.remove('hidden');
    }
  }
  let wheelCount = 0;
  if (wheelSource === 'source-verified') {
    // 原本4輪と原本タイヤを同定できる場合だけ、偽物を追加せずに描画する。
    // 車輪装着・Shader・Xbox外観が一致したことは意味しない。通常は既定OFF。
    const report = requireVerifiedWheelSource(root);
    window.__rmVerifiedSourceWheel = report;
    viewerEvent('source-wheel-coverage', variantMode || '', report);
  } else if (wheelSource === 'proxy') {
    wheelCount = addInspectionWheels(root, activeVehicleAssembly(), variantMode);
  } else if (wheelSource === 'game-fit') {
    wheelCount = addGameDerivedWheelFit(root, activeVehicleAssembly(), variantMode);
    if (!wheelCount) {
      wheelCount = addInspectionWheels(root, activeVehicleAssembly(), variantMode);
      viewerEvent('game-fit-wheel-fallback', variantMode || '', {reason: 'validated WheelStyle pieces were incomplete'});
    }
  } else if (wheelSource === 'stock' && Number(stockWheelAssets.visibleTireLikeMeshCount || 0) === 0) {
    // r366：StockのFH6 WheelStyle幾何は復元済みのものを保全する。
    // 変換車両によっては有効なTire Meshがないため、
    // Rimを置換せず中立ゴムの代替だけを追加する。
    wheelCount = addNeutralTireFallbacks(root, activeVehicleAssembly(), variantMode, 'stock-tire-mesh-unavailable');
  }
  // 実WheelPaint/Tire原本Shader系統の材質解決が終わった後だけ隔離する。
  // 生成器の中立GLBを流用しない。通常起動は変更なし。
  // R側専用原本はGameDBの4輪Stockではない。既存アセンブリ内部に
  // 派生した他輪があっても、右輪の単体研究以外へ表示・転用しない。
  const tireRightSource = renderContract?.pr76_tire_corpus_research?.requested_original_tire_model_name;
  if (typeof tireRightSource === 'string' && tireRightSource.startsWith('R_')
      && (!wheelTireInspectionScope
          || !['front_right', 'rear_right'].includes(wheelTireInspectionScope.corner))) {
    throw new Error('右側専用TireR原本は右輪の研究撮影だけで表示します。通常四輪Stockへの代用は禁止');
  }
  if (wheelTireInspectionScope) {
    const isolation = isolateFinalWheelTireScene(root, wheelTireInspectionScope);
    viewerEvent('wheel-tire-final-scene-isolation', '', isolation);
  }
  applyGroundShadowCasterFlags(root);
  return {
    root,
    paintMaterials: variantPaintList,
    glassMaterials: variantGlassList,
    stockWheelAssets,
    counts: { paintCount, glassCount, meshCount, wheelCount },
  };
}

// 材質モードのプレビューは同じ検証済み原本GLB・Mask・Paintを使用する。
// 初回Paintの前に未使用の比較・Probeモードまで生成する必要はない。
function ensureVariantRoot(variantMode) {
  if (variantRoots.has(variantMode)) return variantRoots.get(variantMode);
  if (!MATERIAL_MODES.includes(variantMode) || !variantSourceModel) return null;
  const start = performance.now();
  const variant = buildVariantRoot(
    variantSourceModel, variantSourceProjectionBounds,
    variantSourcePaintTexture, variantSourceMasks, variantMode,
  );
  variant.root.visible = false;
  variantRoots.set(variantMode, variant.root);
  variantCounts.set(variantMode, variant.counts);
  variantPaintMaterials.set(variantMode, variant.paintMaterials);
  variantGlassMaterials.set(variantMode, variant.glassMaterials);
  paintMaterials.push(...variant.paintMaterials);
  glassMaterials.push(...variant.glassMaterials);
  scene.add(variant.root);
  timings.variantBuildMs = Math.round((Number(timings.variantBuildMs) || 0) + performance.now() - start);
  return variant.root;
}

async function reportViewerDisplayProfile() {
  // 初回保存プロファイルにも含めるため、明示指定されたPNG計測の終了を待つ。
  if (viewerDisplayReportSaved || !Number.isFinite(timings.firstPaintOpportunity) || !atlasPngProbeFinished) return;
  const nativeApi = window.pywebview?.api;
  if (!nativeApi?.report_viewer_display_profile) return;
  try {
    const response = await nativeApi.report_viewer_display_profile({
      // 転送するのは処理段階の時間とモード識別子のみ。
      // パス・Hardware ID・Paint幾何・色・C_liveryペイロードは含めない。
      format: 'lo4fh6_viewer_display_profile_v1',
      timings_ms: {...timings},
      initial_variant_count: Number(timings.initialVariantCount || 0),
      loaded_variant_count: variantRoots.size,
    });
    viewerDisplayReportSaved = Boolean(response?.ok);
  } catch (error) {
    // Profile計測の失敗でViewerのPaint表示を妨げない。
    console.warn('Viewer display timing report was not saved.', String(error?.message || error));
  }
}


// 原本Stock GLBは既存Viewerの同じrenderer/灯光/カメラ/描画ループを使用する。
// C_liveryやGPU Paintを要求する製品Liveryセッションとは独立した研究入口。
// 原本GLBの材質を一律カラー/簡易シェーダへ置換しない。
let stockOnlyGpuSession = null;
async function loadVerifiedStockBody(runtime) {
  if (wheelTireInspectionScope) throw new Error('Wheel/Tire完成画質検証は通常Viewer材質・ペイント処理を通すセッションだけに限定します');
  const contract = runtime?.stock_body_only;
  if (!runtime.local_mesh
      || contract?.format !== 'lo4fh6_source_stock_body_webgl2_session_v1'
      || contract.livery_present !== false
      || runtime.gpu_livery_runtime?.available) {
    throw new Error('原本Stock車体の署名済みWebGL2入力が不完全です');
  }
  const expectedSha = String(contract.glb_sha256 || '');
  if (!/^[a-f0-9]{64}$/.test(expectedSha)) {
    throw new Error('原本Stock GLBのSHA署名がありません');
  }
  phase('assets', t('phase.assets'));
  const response = await fetch('./api/local-mesh', {signal:loadAbort.signal, cache:'no-store'});
  if (!response.ok) throw new Error('原本Stock GLBのHTTP取得に失敗: ' + response.status);
  const buffer = await response.arrayBuffer();
  const digestBytes = new Uint8Array(await crypto.subtle.digest('SHA-256', buffer));
  const digest = [...digestBytes].map(n => n.toString(16).padStart(2, '0')).join('');
  if (digest !== expectedSha) throw new Error('Stock GLBのHTTP受信SHAが元署名と不一致です');
  const gltf = adaptFirstpartyChassisMetadata(await new GLTFLoader().parseAsync(buffer, ''));
  if (viewerDisposed) return;
  const original = trackObjectResources(gltf.scene);
  if (!original) throw new Error('原本Stock GLBに3Dシーンがありません');
  sourceWheelMaterialAudit.declared = sourceWheelDeclaredMaterialClaims(gltf);
  if (sourceWheelMaterialAudit.declared.signedWheelPrimitives > 0) {
    const reconciled = await reconcileLoadedSourceWheelMaterials(gltf);
    sourceWheelMaterialAudit.glb = countVerifiedSourceWheelMaps(original);
    if (!signedWheelSceneReconciled(reconciled, sourceWheelMaterialAudit.declared, sourceWheelMaterialAudit.glb)) {
      throw new Error('原本Stock Wheelの署名済み材質がGLTFLoaderで保持されていません: '
        + String(reconciled?.reason || 'primitive count mismatch'));
    }
  }
  preparePartControls(original.userData?.lo4_part_options);
  let visibleMeshes = 0;
  let glassCount = 0;
  original.traverse(child => {
    if (!child.isMesh) return;
    const category = meshCategory(child);
    child.userData.lo4_base_visible = category !== 'hidden';
    child.visible = child.userData.lo4_base_visible && meshPartVisible(child);
    if (child.visible) {
      visibleMeshes++;
      if (category === 'glass') glassCount++;
      // 画面の床だけが描かれた状態をStock車体GPU成功にしない。
      // 元の原本Wheel/Glass等の描画フックは保持し、呼出し数のみ別途計測。
      const existingBeforeRender = child.onBeforeRender;
      child.onBeforeRender = function(...args) {
        if (stockOnlyGpuSession) stockOnlyGpuSession.submittedBodyMeshes++;
        if (typeof existingBeforeRender === 'function') {
          return existingBeforeRender.apply(this, args);
        }
      };
    }
  });
  if (!visibleMeshes) throw new Error('原本Stock GLBに可視車体メッシュがありません');
  original.updateMatrixWorld(true);
  // C_liveryを合成せず、第一者GLBに入っている材質をそのままViewerの物理経路へ。
  materialMode = 'physical';
  materialModeSelect.value = 'physical';
  materialModeSelect.disabled = true;
  compareMode = 'off';
  compareModeSelect.value = 'off';
  compareModeSelect.disabled = true;
  if (sectionFilterSelect) sectionFilterSelect.disabled = true;
  paintMaterials = [];
  glassMaterials = [];
  variantRoots = new Map([['physical', original]]);
  variantCounts = new Map([['physical', {meshCount:visibleMeshes, paintCount:0,
                                            glassCount, wheelCount:0}]]);
  variantPaintMaterials = new Map();
  variantGlassMaterials = new Map();
  inspectionWheelGroups = new Map();
  stockWheelAssetInventories = new Map();
  model = original;
  scene.add(original);
  applyLightProfile(materialMode);
  if (!studioEnvironmentTarget) createStudioEnvironment(environmentMode, reflectionAngle);
  modelBounds = stableInspectionBounds(original);
  if (!modelBounds || modelBounds.isEmpty()) throw new Error('原本Stock GLBの車体境界が不正です');
  cameraFrameBounds = visibleCarCameraBounds(original, modelBounds);
  floor.position.y = inspectionFloorY(activeVehicleAssembly(), modelBounds.min.y) - 0.018;
  contactShadowCatcher.position.y = floor.position.y + 0.0025;
  configureGroundShadow(modelBounds);
  frameModel(cameraFrameBounds);
  updateCompareControls();
  updateFinishInfo();
  phase('scene', t('phase.scene'));
  stockOnlyGpuSession = {
    carId: contract.car_id, modelCode:contract.model_code,
    signedGlbSha256: expectedSha, visibleMeshes, glassCount, submittedBodyMeshes:0,
    // この研究用Stock GLBでは、確認済みGUI/FEOW全機能の受入は主張しない。
    productWheelFeowAccepted:false, xboxApproved:false,
  };
  modelReady = true;
  viewerEvent('stock-body-source-ready', '', stockOnlyGpuSession);
  requestRender();
}

// ---- 同じ車の次のペイントへの差し替え（ページを読み直さない。2026-11-19、利用者の承認「同じ車だけ差し替え」）----
// Python（窓の使い回し）が、同じ車体の GLB（同じファイル）の次のペイントの出力を同じサーバーに読み込んでから呼ぶ。
// 場面・材質・ペイントは、読み直したときと同じ loadPackage の手順で、新しい目録と同じ車体の GLB のデータから作り直す。
// 使い回すのは車体の GLB のデータ（転送を省く）と、Three.js のシェーダー（前の材質を新しい場面の最初の 1 枚の後に
// 捨てるので、同じ材質の設定のシェーダーをそのまま使う）だけ。差し替えの間は、前のペイントの最後の 1 枚を見せたままにする。
// 受け付けられないとき（読み込み・描画の途中、特別な表示、URL の設定の違い）は受け付けないと返し、
// Python が従来どおりページを読み直す。差し替えの途中で失敗したときは、新しい URL でページを読み直す。
let paintSwapInProgress = false;
let paintSwapPreloaded = null;
let paintSwapRetired = null;
// 同じ車の差し替えで持ち越すテクスチャ（覆い 3 枚。目録の file_sha256 が同じときだけ使う。2026-11-20）。
// 飾りの画像と見え方（sourceBodyTrimTextures・sourceBodyTrimTextureViews）は、名前が中身の SHA なので、そのまま持ち越す。
let paintSwapCarriedTextures = null;

function maskTextureShas(contract) {
  const names = Array.isArray(contract?.files?.masks) ? contract.files.masks : [];
  const hashes = contract?.file_sha256 || {};
  return [0, 1, 2].map(index => {
    const sha = String(hashes[String(names[index] || '')] || '');
    return /^[0-9a-f]{64}$/.test(sha) ? sha : '';
  });
}

function carryPaintSwapTextures() {
  const shas = maskTextureShas(renderContract);
  return {masks: [0, 1, 2].map(index => {
    const texture = variantSourceMasks?.[index];
    return texture?.isTexture && shas[index] ? {texture, sha: shas[index], reused: false} : null;
  })};
}

// 覆いのテクスチャ。差し替えで、前のペイントの覆いと中身（SHA）が同じなら、読み込みと GPU への送りを省いて使い回す。
function paintSwapMaskTexture(index, swapping) {
  const carried = swapping ? paintSwapCarriedTextures?.masks?.[index] : null;
  const sha = maskTextureShas(renderContract)[index];
  if (carried?.texture && sha && carried.sha === sha) {
    carried.reused = true;
    return Promise.resolve(carried.texture);
  }
  return loadTexture(`./api/local-render/mask/${index}`);
}

// 持ち越したのに使わなかった覆いを捨てる（差し替えの最初の 1 枚の後）。
function releaseUnusedCarriedTextures() {
  const carried = paintSwapCarriedTextures;
  paintSwapCarriedTextures = null;
  const unused = new Set();
  for (const item of carried?.masks || []) {
    if (item?.texture && !item.reused) unused.add(item.texture);
  }
  if (!unused.size) return 0;
  for (const texture of unused) trackedTextures.delete(texture);
  return releaseTextures(unused, currentPaintSceneResources().textures);
}
let lastMeshBuffer = null;
let paintSwapTimer = 0;
// GPU で作ったペイントの画像のキャンバス（差し替えで前のペイントのものを捨てるとき、その WebGL を手放す）。
const gpuAtlasCanvases = new WeakSet();
// 差し替えで値が変わってよい URL の設定（ペイントごとの部品の選択）。ほかの設定が違えば読み直す。
const PAINT_SWAP_VARIABLE_PARAMS = new Set(['part-selection']);

// 表示の設定（URL から決まる値と、操作で変わる値）。最初の読み込みの直前から変わっていれば、読み直したときと
// 同じにならないので差し替えない（操作による変更の多くは URL にも書かれ、URL の比較でも分かる）。
function paintSwapViewSettings() {
  return JSON.stringify([materialMode, glassMode, environmentMode, reflectionAngle, reflectionStrengthExplicit,
    reflectionStrength, renderQuality, aaMode, compareMode, compareSplit, differenceGain, displayPreset,
    wheelsVisible, Boolean(controls.autoRotate)]);
}
let paintSwapInitialViewSettings = null;

function emptyResourceSets() {
  return {geometries: new Set(), materials: new Set(), textures: new Set(), skeletons: new Set()};
}

function addMaterialTextures(material, into) {
  for (const value of Object.values(material)) {
    if (value?.isTexture) into.textures.add(value);
  }
  // 車体の材質の独自の uniform は material.userData.lo4Uniforms に持っている。
  for (const uniforms of [material.uniforms, material.userData?.lo4Uniforms]) {
    for (const uniform of Object.values(uniforms || {})) {
      for (const value of Array.isArray(uniform?.value) ? uniform.value : [uniform?.value]) {
        if (value?.isTexture) into.textures.add(value);
      }
    }
  }
}

function addObjectResources(object, into) {
  if (object.geometry?.isBufferGeometry) into.geometries.add(object.geometry);
  for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
    if (!material?.isMaterial) continue;
    into.materials.add(material);
    addMaterialTextures(material, into);
  }
  if (object.skeleton) into.skeletons.add(object.skeleton);
}

function collectPaintSceneResources(root, into) {
  root?.traverse?.(child => addObjectResources(child, into));
  return into;
}

// 今のペイントの場面（部品の組・元の車体）と、そのペイントの画像。
function currentPaintSceneResources() {
  const found = emptyResourceSets();
  for (const root of variantRoots.values()) collectPaintSceneResources(root, found);
  collectPaintSceneResources(variantSourceModel, found);
  for (const texture of [variantSourcePaintTexture, ...(variantSourceMasks || []), baseDetailNormalTexture,
    ...baseDetailNormalProbeTextures.values(), ...baseDetailMaskProbeTextures.values()]) {
    if (texture?.isTexture) found.textures.add(texture);
  }
  return found;
}

// ページに残す資源：最初の読み込みの前からある物、場面のうち車の部品の組の外にある物（床・接地の影・光）、
// 環境、画面の仕上げ・比較の描画先。
let paintSwapInitialTracked = null;
function trackedResourceSnapshot() {
  return {geometries: new Set(trackedGeometries), materials: new Set(trackedMaterials),
    textures: new Set(trackedTextures), skeletons: new Set(trackedSkeletons)};
}
// 最初の読み込みの直前（ページの初期化が済んだ後）に、差し替えで比べる表示の設定と、残す資源の控えを取る。
function capturePaintSwapBaseline() {
  paintSwapInitialTracked = trackedResourceSnapshot();
  paintSwapInitialViewSettings = paintSwapViewSettings();
}
function persistentPageResources() {
  const found = emptyResourceSets();
  for (const kind of Object.keys(found)) {
    for (const item of paintSwapInitialTracked?.[kind] || []) found[kind].add(item);
  }
  const roots = new Set(variantRoots.values());
  const walk = object => {
    if (roots.has(object)) return;
    addObjectResources(object, found);
    object.children.forEach(walk);
  };
  walk(scene);
  collectPaintSceneResources(presentationCompositeScene, found);
  collectPaintSceneResources(compareCompositeScene, found);
  for (const texture of [scene.environment, scene.background, studioEnvironmentTarget?.texture,
    presentationRenderTarget?.texture, compareRenderTargetA?.texture, compareRenderTargetB?.texture,
    flatDetailNormalTexture]) {
    if (texture?.isTexture) found.textures.add(texture);
  }
  // 同じ車の差し替えで写しを作る元の場面（形・画像・材質。2026-11-20）。
  collectPaintSceneResources(pristineMeshGltf?.gltf?.scene, found);
  // 同じ車の差し替えで持ち越すテクスチャ（覆い・飾りの画像と見え方）。
  for (const item of paintSwapCarriedTextures?.masks || []) {
    if (item?.texture?.isTexture) found.textures.add(item.texture);
  }
  for (const texture of [...sourceBodyTrimTextures.values(), ...sourceBodyTrimTextureViews.values()]) {
    if (texture?.isTexture) found.textures.add(texture);
  }
  return found;
}

const TRACKED_RESOURCE_SETS = () => [['geometries', trackedGeometries], ['materials', trackedMaterials],
  ['textures', trackedTextures], ['skeletons', trackedSkeletons]];

// 差し替えの始めに、前のペイントの資源（ページに残す物の外の、記録している物と場面の物）を記録から外す。
// 予算の確かめ・資源の量の計算を、読み直したときと同じ範囲にするため。捨てるのは最初の 1 枚の後。
function retirePaintResources() {
  const persistent = persistentPageResources();
  const retired = emptyResourceSets();
  retired.untracked = emptyResourceSets();
  for (const [kind, tracked] of TRACKED_RESOURCE_SETS()) {
    for (const item of [...tracked]) {
      if (persistent[kind].has(item)) continue;
      retired[kind].add(item);
      tracked.delete(item);
    }
  }
  const scenePaint = currentPaintSceneResources();
  for (const kind of Object.keys(scenePaint)) {
    for (const item of scenePaint[kind]) {
      if (persistent[kind].has(item) || retired[kind].has(item)) continue;
      retired[kind].add(item);
      retired.untracked[kind].add(item);
    }
  }
  return retired;
}

// 画像を捨て、画像の元（ImageBitmap）を、残す画像と共有していなければ閉じる。GPU で作ったペイントの画像の WebGL は
// 手放す（読み込みごとに新しく作るので、溜まると Chromium が古い文脈から落とす。一番古いのは Viewer 本体の文脈）。
function releaseTextures(textures, keepTextures) {
  const keptImages = new Set();
  for (const texture of keepTextures) if (texture.image) keptImages.add(texture.image);
  const released = new Set();
  for (const texture of textures) {
    if (keepTextures.has(texture)) continue;
    texture.dispose();
    const image = texture.image;
    if (!image || keptImages.has(image) || released.has(image)) continue;
    released.add(image);
    try {
      if (gpuAtlasCanvases.has(image)) {
        gpuAtlasCanvases.delete(image);
        image.getContext('webgl2')?.getExtension('WEBGL_lose_context')?.loseContext();
      } else if (typeof image.close === 'function') {
        image.close();
      }
    } catch (_error) {
      // 手放せなくても、参照が無くなれば解放される。
    }
  }
  return released.size;
}

// 差し替えの始めに、前のペイントの形と画像をすぐ捨てる。新しいペイントはこれらを使わない（使い回す覚えは空にする）
// ので、読み直しと同じく、前のペイントと新しいペイントの GPU のメモリーを同時に持たない。材質は、新しい材質が同じ
// シェーダーを使い始めるまで残す（先に捨てるとシェーダーも捨てられて作り直しになる）。前の 1 枚は画面に残る
// （差し替えの間は描かない）。
function releaseRetiredPaintData(retired) {
  const persistent = persistentPageResources();
  for (const geometry of retired.geometries) if (!persistent.geometries.has(geometry)) geometry.dispose();
  retired.releasedImages = releaseTextures(retired.textures, persistent.textures);
  retired.geometries.clear();
  retired.textures.clear();
}

// 前のペイントの材質のシェーダーを残すための材質（2026-11-20、FH6 に近づける案 ③）。Three.js は、材質を捨てて
// そのシェーダーを使う材質が無くなると、シェーダーも捨てる。同じ車でも、ペイントによってシェーダーの形が違う
// （下地の細部の法線の画像の有無など）ので、行き来するたびにシェーダーを作り直していた（1 回 約 0.25 秒）。
// 捨てる材質のうち、シェーダーの鍵の組ごとに 1 つを、描かずに持っておく（画像への参照は外す）。最近の 48 組まで。
const PROGRAM_KEEPER_LIMIT = 48;
const programKeepers = new Map();

function programKeySet(material) {
  const programs = renderer.properties.get(material)?.programs;
  if (!programs || !programs.size) return '';
  return [...programs.keys()].sort().join('\n');
}

function releaseKeeperTextures(material) {
  for (const [name, value] of Object.entries(material)) {
    if (value?.isTexture) material[name] = null;
  }
  for (const uniform of Object.values(material.userData?.lo4Uniforms || {})) {
    if (uniform?.value?.isTexture) uniform.value = null;
  }
}

// 捨てる代わりにシェーダーの持ち手にしたら true（呼び出し側は捨てない）。
function keepRetiredMaterialProgram(material) {
  const keys = programKeySet(material);
  if (!keys) return false;
  if (programKeepers.has(keys)) {
    const keeper = programKeepers.get(keys);
    programKeepers.delete(keys);
    programKeepers.set(keys, keeper);  // 最近使った順の後ろへ
    return false;
  }
  releaseKeeperTextures(material);
  programKeepers.set(keys, material);
  while (programKeepers.size > PROGRAM_KEEPER_LIMIT) {
    const [oldestKeys, oldest] = programKeepers.entries().next().value;
    programKeepers.delete(oldestKeys);
    oldest.dispose();
  }
  return true;
}

// 前のペイントの材質（と骨）を、新しい場面の最初の 1 枚を描いた後に捨てる（新しい材質がシェーダーを使い始めた後
// なので、同じシェーダーは捨てられない）。新しいペイントでも使っている物は捨てずに記録へ戻す。
function disposeRetiredPaintResources(retired) {
  const keep = currentPaintSceneResources();
  const persistent = persistentPageResources();
  for (const [kind, tracked] of TRACKED_RESOURCE_SETS()) {
    for (const item of tracked) keep[kind].add(item);
    for (const item of persistent[kind]) keep[kind].add(item);
  }
  let kept = 0;
  for (const [kind, tracked] of TRACKED_RESOURCE_SETS()) {
    for (const item of retired[kind]) {
      if (!keep[kind].has(item)) continue;
      kept += 1;
      if (!retired.untracked[kind].has(item)) tracked.add(item);
    }
  }
  for (const geometry of retired.geometries) if (!keep.geometries.has(geometry)) geometry.dispose();
  let programKeepersAdded = 0;
  for (const material of retired.materials) {
    if (keep.materials.has(material)) continue;
    if (keepRetiredMaterialProgram(material)) programKeepersAdded += 1;
    else material.dispose();
  }
  const released = releaseTextures(retired.textures, keep.textures);
  for (const skeleton of retired.skeletons) if (!keep.skeletons.has(skeleton)) skeleton.dispose?.();
  return {kept, released: (retired.releasedImages || 0) + released, programKeepersAdded,
    programKeepers: programKeepers.size};
}

function reportPaintSwap(payload) {
  try {
    const api = window.pywebview?.api;
    if (api?.report_paint_swap) void Promise.resolve(api.report_paint_swap(payload)).catch(() => false);
  } catch (_error) {
    // Python へ届かなくても、差し替えそのものは続ける（Python は時間切れで読み直す）。
  }
}

async function swapPaint(nextUrl) {
  const reject = reason => {
    reportPaintSwap({accepted: false, reason});
    return {accepted: false, reason};
  };
  if (paintSwapInProgress) return reject('swap-in-progress');
  if (viewerDisposed || !modelReady || !firstFrameReady) return reject('viewer-not-ready');
  if (stockOnlyGpuSession || wheelTireInspectionScope || partOptionSwitching || rmCaptureBusy || rmCaptureFormat) {
    return reject('special-view');
  }
  if (effectiveCompareMode() !== 'off' || demoMosaicBody?.checked || atlasPngProbeRequested) return reject('special-view');
  if (paintSwapViewSettings() !== paintSwapInitialViewSettings) return reject('view-settings');
  if (!(lastMeshBuffer instanceof ArrayBuffer) || !lastMeshBuffer.byteLength) return reject('no-mesh-buffer');
  let target;
  try {
    target = new URL(String(nextUrl), window.location.href);
  } catch (_error) {
    return reject('invalid-url');
  }
  if (target.origin !== window.location.origin || target.pathname !== window.location.pathname) {
    return reject('other-server');
  }
  const current = new URLSearchParams(window.location.search);
  for (const key of new Set([...current.keys(), ...target.searchParams.keys()])) {
    if (PAINT_SWAP_VARIABLE_PARAMS.has(key)) continue;
    if (JSON.stringify(current.getAll(key)) !== JSON.stringify(target.searchParams.getAll(key))) {
      return reject('parameter:' + key);
    }
  }
  let manifest;
  try {
    const response = await fetch('./api/manifest', {cache: 'no-store', signal: loadAbort.signal});
    if (!response.ok) return reject('manifest-http-' + response.status);
    manifest = await response.json();
  } catch (_error) {
    return reject('manifest-unavailable');
  }
  if (manifest?.inspection_runtime?.stock_body_only?.enabled === true) return reject('stock-body');
  paintSwapInProgress = true;
  reportPaintSwap({accepted: true});
  // 車ごとに同じテクスチャ（覆い・飾りの画像と見え方）は持ち越す（読み込みと GPU への送りを省く。2026-11-20）。
  paintSwapCarriedTextures = carryPaintSwapTextures();
  // 前のペイントの場面を外す（最後の 1 枚は画面に残る。資源は記録から外し、新しい場面の最初の 1 枚の後に捨てる）。
  const retired = retirePaintResources();
  for (const root of variantRoots.values()) scene.remove(root);
  releaseRetiredPaintData(retired);
  paintSwapRetired = retired;
  // URL と、URL から読む設定を新しいペイントにする（違ってよいのは部品の選択だけ）。
  window.history.replaceState(window.history.state, '', target.href);
  for (const key of [...viewerParams.keys()]) viewerParams.delete(key);
  for (const [key, value] of target.searchParams) viewerParams.append(key, value);
  requestedPartSelection = parseRequestedPartSelection();
  // 読み込みのたびに作り直す状態を、ページを読み込んだときと同じにする。
  modelReady = false;
  firstFrameReady = false;
  gpuOnlyPaintCompleted = false;
  sourceMeshFinishVerifiedGroups = null;
  receivedWheelGlbAudit = null;
  sourceWheelMaterialAudit.glb = 0;
  sourceWheelMaterialAudit.declared = null;
  sourceWheelMaterialAudit.variants = new Map();
  sourceWheelMaterialAudit.delivered = false;
  inspectionWheels = null;
  pendingCameraViewFrame = null;
  // 部品の重ねの読み込み済みの印と、部品の組ごとの数（どちらも前の車の場面のもの）。
  loadedPartOptionKeys.clear();
  variantCounts = new Map();
  // 車体の飾りの画像と見え方の覚えは持ち越す（画像の名前は中身の SHA、見え方の鍵は画像・UV・繰り返し・色合い。
  // 同じ車なので次のペイントも同じものを使う。読めなかった画像は読み直す）。
  sourceBodyTrimTextureFailures = 0;
  viewerDisplayReportSaved = false;
  model = null;
  for (const key of Object.keys(timings)) delete timings[key];
  startedAt = performance.now();
  latestViewerStage = 'script_loaded';
  if (renderErrorWarning) {
    renderErrorWarning.textContent = '';
    renderErrorWarning.classList.add('hidden');
  }
  viewerEvent('paint-swap-started', '', {meshBytes: lastMeshBuffer.byteLength});
  paintSwapPreloaded = {manifest, meshBuffer: lastMeshBuffer};
  // 最初の 1 枚が読み込みの時間切れまでに描けなければ、新しい URL でページを読み直す（最初の読み込みと同じ安全策）。
  window.clearTimeout(paintSwapTimer);
  paintSwapTimer = window.setTimeout(() => {
    if (paintSwapInProgress) window.location.replace(target.href);
  }, viewerLoadTimeoutMs);
  try {
    await loadPackage();
  } catch (error) {
    console.error(error);
  }
  if (!modelReady) {
    // 作り直しに失敗した。新しい URL でページを読み直す（読み直したときと同じ結果にする。失敗が続けば
    // 読み直しの側で従来どおりエラーを出す）。
    window.clearTimeout(paintSwapTimer);
    paintSwapInProgress = false;
    window.location.replace(target.href);
    return {accepted: true, reloaded: true};
  }
  return {accepted: true};
}
window.lo4fh6SwapPaint = swapPaint;
// 差し替えの準備の間、前のペイントの上に状態を出す（Python の準備の進み具合。最初の 1 枚を描くと消える）。
window.lo4fh6ShowPaintSwapStatus = message => setStatus(String(message || ''));

async function loadPackage() {
  // 差し替え（swapPaint）では、読み済みの目録と同じ車体の GLB のデータを使う。
  const preloaded = paintSwapPreloaded;
  paintSwapPreloaded = null;
  try {
    phase('manifest', t('phase.manifest'));
    let manifest;
    if (preloaded?.manifest) {
      manifest = preloaded.manifest;
    } else {
      const response = await fetch('./api/manifest', { cache: 'no-store', signal: loadAbort.signal });
      reportViewerStage('manifest_http', 'http_status=' + response.status);
      if (!response.ok) throw new Error(await response.text());
      manifest = await response.json();
    }
    reportViewerStage('manifest_parsed');
    currentManifest = manifest;
    updateDemoTitle();
    updateVehicleInfo();
    const runtime = manifest.inspection_runtime || {};
    renderContract = runtime.render_contract || {};
    if (runtime.stock_body_only?.enabled === true) {
      await loadVerifiedStockBody(runtime);
      return;
    }
    bodyKitVariantCatalog = Array.isArray(runtime.body_kit_variants)
      ? runtime.body_kit_variants.filter(item => Number.isInteger(Number(item?.body_kit_part_id)))
      : [];
    const legacyBodyKitOverlay = runtime.body_kit_overlay || {};
    const requestedVariant = Number.isInteger(requestedBodyKitPartId)
      ? bodyKitVariantCatalog.find(item => Number(item.body_kit_part_id) === requestedBodyKitPartId) || null
      : null;
    const legacyPartId = Number(legacyBodyKitOverlay?.body_kit_part_id);
    const legacyVariant = Number.isInteger(legacyPartId)
      ? bodyKitVariantCatalog.find(item => Number(item.body_kit_part_id) === legacyPartId) || null
      : null;
    const bodyKitOverlay = requestedVariant || legacyVariant || bodyKitVariantCatalog[0] || legacyBodyKitOverlay;
    activeBodyKitPartId = Number.isInteger(Number(bodyKitOverlay?.body_kit_part_id))
      ? Number(bodyKitOverlay.body_kit_part_id)
      : null;
    updateBodyKitControl();
    updateAssemblyInfo();
    const bodyKitRemovedEntries = Array.isArray(bodyKitOverlay.removed_entries) ? bodyKitOverlay.removed_entries : [];
    partOptionCatalog = Array.isArray(runtime.part_options?.catalog) ? runtime.part_options.catalog : [];
    activePartOptions = new Map([...requestedPartOptions].filter(([family, id]) => partOptionCatalog.some(
      entry => entry.family === family && entry.options.some(option => option.id === id && !option.is_stock))));
    updatePartOptionControls();
    updateRenderInfo();
    updateFinishInfo();
    if (
      !runtime.local_mesh
      || renderContract.format !== RENDER_CONTRACT_FORMAT
    ) {
      throw new Error(
        'The Viewer has not prepared this car\'s exact local FH6 livery mesh and section masks yet. '
        + 'Choose the FH6 Content folder and reopen the package.'
      );
    }
    const availableFilters = new Set(renderContract.filters || []);
    if (sectionFilterSelect) {
      for (const option of sectionFilterSelect.options) {
        option.disabled = !availableFilters.has(option.value);
      }
    }

    phase('assets', t('phase.assets'));
    const productionDetailNormal = renderContract?.base_paint_material?.detail_normal || {};
    const probeDetailNormal = renderContract?.base_paint_material?.detail_normal_probe || {};
    const detailMaskProbe = renderContract?.base_paint_material?.detail_mask_probe || {};
    const detailNormalEndpoint = productionDetailNormal?.local_render_endpoint || probeDetailNormal?.local_render_endpoint;
    const detailMaskEndpoint = detailMaskProbe?.local_render_endpoint;
    const assetsStart = performance.now();
    const bodyTrimTexturePreload = preloadSourceBodyTrimTextures();
    const loadResults = await Promise.all([
      Promise.resolve((() => {
        // GPU同士のShaderプリウォーム用: 1px透明テクスチャでCPUペイントではない。
        const placeholder = trackTexture(new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1));
        placeholder.colorSpace = THREE.SRGBColorSpace;
        placeholder.needsUpdate = true;
        return placeholder;
      })()),
      paintSwapMaskTexture(0, Boolean(preloaded)),
      paintSwapMaskTexture(1, Boolean(preloaded)),
      paintSwapMaskTexture(2, Boolean(preloaded)),
      detailNormalEndpoint ? loadTexture(`./${detailNormalEndpoint}`) : Promise.resolve(null),
      detailMaskEndpoint ? loadTexture(`./${detailMaskEndpoint}`) : Promise.resolve(null),
      (preloaded?.meshBuffer ? Promise.resolve(preloaded.meshBuffer) : fetch('./api/local-mesh', {signal: loadAbort.signal}).then(response => {
        if (!response.ok) throw new Error(`Car mesh load failed (${response.status}).`);
        return response.arrayBuffer();
      })).then(buffer => {
        // 同じ車の次のペイントへの差し替えで使い回す（GLTFLoader は受け取ったデータを変えない）。
        lastMeshBuffer = buffer;
        reportViewerStage('mesh_received');
        if (viewerDisposed) throw new Error('Viewer closed.');
        // ローカルmeshのHTTP応答そのものを調査。生成側のJSON証拠だけを信用しない。
        if (wheelSource === 'source-verified' && sourceNeutralResearch) {
          // 調べの結果は凍った物（Object.freeze）なので、同じデータでは同じ物を使い回す。
          receivedWheelGlbAudit = meshBufferFact(buffer, 'wheelAudit', () => inspectReceivedSourceWheelGlb(buffer));
          window.__lo4fh6ReceivedWheelGlbAudit = receivedWheelGlbAudit;
          viewerEvent('source-wheel-received-glb', '', receivedWheelGlbAudit);
        }
        const proof = renderContract?.source_paint_binding_diagnostics;
        if (proof?.carpaint_binding_complete_for_research === true) {
          if (!globalThis.crypto?.subtle) throw new Error('原本CarPaintのSHA-256検証APIがありません');
          return meshBufferSha256(buffer).then(sha => {
            sourceMeshFinishVerifiedGroups = validateSourceMeshFinishEvidence(proof, sha);
            viewerEvent('source-mesh-finish-standard-signed', '', {
              sourceGlbSha256:sha, materialGroups:sourceMeshFinishVerifiedGroups.size,
              appliedSourceColorSlot:'primary', nativeTwoColorShaderApplied:false,
              xboxApproved:false,
            });
            return parsedMeshGltf(buffer);
          });
        }
        if (proof || renderContract?.source_paint_binding_diagnostics_unavailable) {
          viewerEvent('source-mesh-finish-standard-incomplete', '', {
            reason:renderContract.source_paint_binding_diagnostics_unavailable
              || '元Carbin/YRVLの材質Hashが未完備',
            visibleFallbackIsUnverified:true,
          });
        }
        return parsedMeshGltf(buffer);
      }).then(item => {
        reportViewerStage('mesh_parsed');
        const removedCount = removeBodyKitReplacedMeshes(item.scene, bodyKitRemovedEntries);
        if (removedCount) viewerEvent('body-kit-baseline-removed', String(removedCount), { removed_entries: bodyKitRemovedEntries });
        trackObjectResources(item.scene);
        return item;
      }),
      bodyKitOverlay.mesh_available && bodyKitOverlay.endpoint
        ? fetch(`./${bodyKitOverlay.endpoint}`, {signal: loadAbort.signal}).then(response => {
            if (!response.ok) throw new Error(`Body-kit overlay load failed (${response.status}).`);
            return response.arrayBuffer();
          }).then(buffer => {
            if (viewerDisposed) throw new Error('Viewer closed.');
            return new GLTFLoader().parseAsync(buffer, '').then(adaptFirstpartyChassisMetadata);
          }).then(item => {
            item.scene.name = `body-kit overlay ${bodyKitOverlay.body_kit_part_id || ''}`.trim();
            item.scene.userData.lo4_body_kit_overlay = true;
            trackObjectResources(item.scene);
            return item;
          })
        : Promise.resolve(null),
      loadPartOptionOverlays(activePartOptions, loadAbort.signal),
    ]);
    await bodyTrimTexturePreload;
    // 部品の選択肢の重ね合わせの部品の色を契約へ加え、そのTextureも先に読む（読み済みは読み直さない）。
    mergePartOptionBodyTrim(loadResults[loadResults.length - 1]);
    await preloadSourceBodyTrimTextures();
    reportViewerStage('assets_ready');
    if (viewerDisposed) return;
    timings.assetLoadMs = Math.round(performance.now() - assetsStart);
    const assetBytes = resourceBytes();
    modelResourceBytes = assetBytes.geometry + assetBytes.textures;
    resize();
    if (resourceBytes().estimatedGpu > gpuBudgetBytes) throw new Error('The car exceeds the preview graphics memory budget.');
    phase('materials', t('phase.materials'));
    const [gpuPaintSeedTexture, mask0, mask1, mask2, detailNormal, detailMask, gltf, bodyKitGltf, partOptionOverlays] = loadResults;
    let paintTexture = gpuPaintSeedTexture;
    const prepareGpuPaintAtlas = async () => {
      // 契約不一致・入力欠落・WebGL障害時は明示エラー。CPUペイント経路なし。
      if (renderContract?.cpu_shadow_policy !== 'gpu-only'
          || renderContract?.paint_rasterizer !== 'webgl2-only'
          || renderContract?.files?.paint) {
        throw new Error('GPU-only paint contract is required; CPU paint is removed.');
      }
      if (!runtime?.gpu_livery_runtime?.available) {
        throw new Error('GPU-only paint runtime inputs are unavailable; CPU fallback is removed.');
      }
      phase('materials', getLanguage() === 'ja' ? 'GPUペイントを準備しています…' : 'Preparing GPU livery paint…');
      reportViewerStage('gpu_paint_start');
      const gpuAtlasStart = performance.now();
      const gpuResult = await buildProductionGpuPaintAtlas(renderContract);
      timings.gpuAtlasBuildMs = Math.round(performance.now() - gpuAtlasStart);
      if (!gpuResult?.usedGpu || !gpuResult.atlasCanvas
          || (gpuResult.rejectedSections || []).length) {
        throw new Error('GPU-only paint atlas incomplete: ' + String(gpuResult?.reason || 'no render target'));
      }
      if (gpuResult?.profile) {
        timings.gpuAtlasTileRenderMs = Math.round(gpuResult.profile.tileRenderMs || 0);
        timings.gpuAtlasComposeMs = Math.round(gpuResult.profile.composeMs || 0);
        timings.gpuAtlasPlanBuildMs = Math.round(gpuResult.profile.planBuildMs || 0);
        timings.gpuAtlasWebglRenderMs = Math.round(gpuResult.profile.webglRenderMs || 0);
      }
      if (atlasPngProbeRequested) atlasPngProbeCanvas = gpuResult.atlasCanvas;
      const texture = trackTexture(new THREE.CanvasTexture(gpuResult.atlasCanvas));
      gpuAtlasCanvases.add(gpuResult.atlasCanvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.flipY = false;
      texture.wrapS = THREE.ClampToEdgeWrapping;
      texture.wrapT = THREE.ClampToEdgeWrapping;
      texture.minFilter = THREE.LinearMipmapLinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.anisotropy = qualityProfile().anisotropy;
      texture.needsUpdate = true;
      paintTexture = texture;
      setGpuPaintStatus(true);
      showRasterOmissionNotice(gpuResult.rasterOmissions, gpuResult.rasterOmittedLayerCount);
      viewerEvent('gpu-livery-production-active', String(gpuResult.reason || ''), {
        sections: gpuResult.sections, gpuOnly: true,
      });
      await reportGpuLiveryProductionAdapter(gpuResult);
      gpuOnlyPaintCompleted = true;
      reportViewerStage('gpu_paint_ready');
      return true;
    };
    // 標準のWebGL2 GPUペイントを完成させてから実マテリアルへ接続する。
    await prepareGpuPaintAtlas();
    baseDetailNormalTexture = null;
    baseDetailNormalProbeTextures = new Map();
    baseDetailMaskProbeTextures = new Map();
    if (detailNormal) {
      const candidate = basePaintViewerCandidate();
      const configureDetailTexture = (texture, detail, channelOverride = null) => {
        texture.wrapS = THREE.RepeatWrapping;
        texture.wrapT = THREE.RepeatWrapping;
        texture.repeat.set(
          Number.isFinite(Number(detail.u_tiling)) ? Number(detail.u_tiling)
            : (Number.isFinite(Number(candidate.detail_normal_u_tiling)) ? Number(candidate.detail_normal_u_tiling) : 4.0),
          Number.isFinite(Number(detail.v_tiling)) ? Number(detail.v_tiling)
            : (Number.isFinite(Number(candidate.detail_normal_v_tiling)) ? Number(candidate.detail_normal_v_tiling) : 10.0)
        );
        const resolvedChannel = Number.isInteger(Number(channelOverride))
          ? Number(channelOverride)
          : (Number.isInteger(Number(detail.three_uv_channel))
            ? Number(detail.three_uv_channel)
            : (Number.isInteger(Number(candidate.detail_normal_three_uv_channel))
              ? Number(candidate.detail_normal_three_uv_channel) : 1));
        texture.channel = resolvedChannel;
        texture.anisotropy = qualityProfile().anisotropy;
        texture.needsUpdate = true;
        return texture;
      };
      if (productionDetailNormal?.available) {
        baseDetailNormalTexture = configureDetailTexture(detailNormal, productionDetailNormal);
      }
      if (probeDetailNormal?.available) {
        const candidates = Array.isArray(probeDetailNormal.uv_candidates)
          ? probeDetailNormal.uv_candidates.map(Number).filter(Number.isInteger)
          : [0, 1];
        for (const channel of candidates) {
          if (channel !== 0 && channel !== 1) continue;
          const probeTexture = trackTexture(detailNormal.clone());
          configureDetailTexture(probeTexture, probeDetailNormal, channel);
          baseDetailNormalProbeTextures.set(channel, probeTexture);
        }
      }
    }
    if (detailMask && detailMaskProbe?.available) {
      const configureMaskTexture = (texture, channel) => {
        texture.wrapS = THREE.RepeatWrapping;
        texture.wrapT = THREE.RepeatWrapping;
        texture.repeat.set(
          Number.isFinite(Number(detailMaskProbe.u_tiling)) ? Number(detailMaskProbe.u_tiling) : 32.0,
          Number.isFinite(Number(detailMaskProbe.v_tiling)) ? Number(detailMaskProbe.v_tiling) : 32.0
        );
        texture.channel = channel;
        texture.colorSpace = THREE.NoColorSpace;
        texture.anisotropy = qualityProfile().anisotropy;
        texture.needsUpdate = true;
        return texture;
      };
      const candidates = Array.isArray(detailMaskProbe.uv_candidates)
        ? detailMaskProbe.uv_candidates.map(Number).filter(Number.isInteger) : [0, 1];
      for (const channel of candidates) {
        if (channel !== 0 && channel !== 1) continue;
        const probeTexture = trackTexture(detailMask.clone());
        configureMaskTexture(probeTexture, channel);
        baseDetailMaskProbeTextures.set(channel, probeTexture);
      }
    }
    model = gltf.scene;
    if (bodyKitGltf?.scene) {
      model.add(bodyKitGltf.scene);
      viewerEvent('body-kit-overlay-added', String(bodyKitOverlay.body_kit_part_id || ''), {
        added_entries: bodyKitOverlay.added_entries || [],
        removed_entries: bodyKitRemovedEntries,
        player_save_state_resolved: bodyKitOverlay.player_save_state_resolved === true,
      });
    }
    applyPartOptionOverlays(model, partOptionOverlays);
    if (wheelSource === 'source-verified' && sourceNeutralResearch) {
      // BodyKitを含む実描画シーンのGLBを数える。車種専用の期待件数は置かない。
      sourceWheelMaterialAudit.declared = sourceWheelDeclaredMaterialClaims(gltf);
      // 原本GLBのmesh/primitive→material IDとGLTFLoader参照を照合する。
      // WebView2でmetadataだけが消失したときは署名済み原本材質を復元するが、
      // PNGテクスチャを読み込めていない状態は成功扱いしない。
      const sourceWheelMaterialReconcile = await reconcileLoadedSourceWheelMaterials(gltf);
      viewerEvent('source-wheel-material-reconcile', '', sourceWheelMaterialReconcile);
      sourceWheelMaterialAudit.glb = countVerifiedSourceWheelMaps(model);
      // サーバーから受け取った20等の個数を固定せず、実GLB署名数とローダー結果を照合。
      // 画像が消失した場合は黒円盤のまま成功扱いせず、理由を示して停止する。
      if (!signedWheelSceneReconciled(sourceWheelMaterialReconcile,
          sourceWheelMaterialAudit.declared, sourceWheelMaterialAudit.glb,
          receivedWheelGlbAudit)) {
        throw new Error(`原本WheelのHTTP受信→GLTFLoader材質認識不一致: 受信=${receivedWheelGlbAudit.signedWheelPrimitives} 認識=${sourceWheelMaterialAudit.glb}; 詳細=${sourceWheelMaterialReconcile.reason || '原本材質数とローダー数が不一致'}`);
      }
      viewerEvent('source-wheel-material-declared', '', sourceWheelMaterialAudit.declared);
      viewerEvent('source-wheel-material-glb', '', {
        signedMappedMeshes:sourceWheelMaterialAudit.glb,
        signedMaterials:sourceWheelMaterialAudit.declared.signedMaterials,
        signedWheelPrimitives:sourceWheelMaterialAudit.declared.signedWheelPrimitives,
        recognitionMismatch:sourceWheelMaterialAudit.declared.signedWheelPrimitives > 0
          && sourceWheelMaterialAudit.glb === 0,
        sourceOnly:true, pixelParityApproved:false,
      });
    }
    carbonUvAttributeSummary = summarizeCarbonUvAttributes(model);
    viewerEvent('carbon-uv-attributes', '', carbonUvAttributeSummary);
    preparePartControls(model.userData?.lo4_part_options);
    model.traverse(child => {
      if (!child.isMesh) return;
      const category = meshCategory(child);
      child.userData.lo4_base_visible = category !== 'hidden';
      child.visible = child.userData.lo4_base_visible && meshPartVisible(child);
    });
    model.updateMatrixWorld(true);
    paintMaterials = [];
    glassMaterials = [];
    variantRoots = new Map();
    variantPaintMaterials = new Map();
    variantGlassMaterials = new Map();
    inspectionWheelGroups = new Map();
    stockWheelAssetInventories = new Map();
    applyLightProfile(materialMode);
    if (materialMode !== 'diagnostic' && !studioEnvironmentTarget) createStudioEnvironment(environmentMode, reflectionAngle);
    const sceneBuildStart = performance.now();
    const projectionBounds = calculateProjectionBounds(model, renderContract);
    let recoveredPaintCount = 0;
    model.traverse(child => {
      if (!child.isMesh) return;
      meshCategory(child);
      recoveredPaintCount += child.userData?.lo4_role_recovery === 'trim_uv3_body' ? 1 : 0;
    });
    variantSourceModel = model;
    variantSourceProjectionBounds = projectionBounds;
    variantSourcePaintTexture = paintTexture;
    variantSourceMasks = [mask0, mask1, mask2];
    // Physical材質のバリエーションは境界とShader復元の基準として保持する。
    // 初期確保する追加バリエーションは現在選択中のものだけ。
    // その他は比較・材質Probeが表示されたときに必要に応じて生成する。
    ensureVariantRoot('physical');
    // PR76のWheel+Tire撮影では完成Physicalシーンだけを生成する。
    // 車体材質モードの二重クローンはCPU/VRAMを浪費するので禁止。
    // 通常Viewerとその表示切替には変更を加えない。
    if (!wheelTireInspectionScope) ensureVariantRoot(materialMode);
    timings.initialVariantCount = variantRoots.size;
    const {meshCount, paintCount, glassCount, wheelCount} = variantCounts.get('physical');
    const refreshPartSelection = refreshAllPartVisibility;
    partControls.querySelectorAll('select').forEach(select => {
      select.addEventListener('change', () => {
        const selected = select.value === '' ? null : Number(select.value);
        selectedPartOptions.set(select.dataset.partType, selected);
        refreshPartSelection();
      });
    });
    if (!meshCount || !paintCount) {
      throw new Error('The local car conversion did not preserve FH6 livery-bearing paint geometry.');
    }
    timings.sceneBuildMs = Math.round(performance.now() - sceneBuildStart);
    model = variantRoots.get('physical') || variantRoots.get(materialMode) || null;
    model?.updateMatrixWorld(true);
    modelBounds = stableInspectionBounds(model);
    cameraFrameBounds = visibleCarCameraBounds(model, modelBounds);
    floor.position.y = inspectionFloorY(activeVehicleAssembly(), modelBounds.min.y) - 0.018;
    contactShadowCatcher.position.y = floor.position.y + 0.0025;
    configureGroundShadow(modelBounds);
    frameModel(cameraFrameBounds);
    setSectionFilter(restoreViewerReloadState());
    updateCompareControls();
    phase('scene', t('phase.scene'));
    modelReady = true;
    console.info(
      `section-aware inspector: ${paintCount} paint (${recoveredPaintCount} recovered trim/UV3 body), ${glassCount} glass, `
      + `${meshCount} local meshes, ${wheelCount} neutral inspection wheels, `
      + `${(renderContract.sections || []).length} livery sections, `
      + `${variantRoots.size} material variants.`
    );
    requestRender();
  } catch (error) {
    failViewer(error?.message || String(error));
  }
}

// カメラ操作イベント自体はGPU描画の完了証明ではない。
// 右側原本Tireの撮影は、選択後の実WebGL2フレームを待つ。
let pendingCameraViewFrame = null;
const CAMERA_VIEW_DIRECTIONS = Object.freeze({
  front: new THREE.Vector3(0, 0, 1),
  back: new THREE.Vector3(0, 0, -1),
  left: new THREE.Vector3(1, 0, 0),
  right: new THREE.Vector3(-1, 0, 0),
  // 見た目は真上視点を維持しつつ、Up Vectorの完全な特異点を避ける。
  top: new THREE.Vector3(0, 1, 0.001),
  bottom: new THREE.Vector3(0, -1, 0.001),
});

function setActiveCameraView(viewName) {
  viewButtons.forEach(button => {
    button.classList.toggle('active', button.dataset.view === viewName);
  });
}

function clearCameraViewSelection() {
  setActiveCameraView('');
}

function frameCameraView(viewName) {
  if (!modelBounds) return;
  const direction = viewName === 'home' ? null : CAMERA_VIEW_DIRECTIONS[viewName];
  if (viewName !== 'home' && !direction) return;
  const damping = controls.enableDamping;
  const rotating = controls.autoRotate;
  controls.enableDamping = false;
  controls.autoRotate = false;
  controls.update();
  frameModel(cameraFrameBounds || modelBounds, direction);
  controls.enableDamping = damping;
  controls.autoRotate = rotating;
  setActiveCameraView(viewName);
  pendingCameraViewFrame = viewName;
  requestRender();
  viewerEvent('camera-view', '', {view: viewName});
}

function selectCameraView(event) {
  frameCameraView(String(event.currentTarget?.dataset?.view || 'home'));
}

function resetView() {
  frameCameraView('home');
}

function toggleAutoRotate() {
  controls.autoRotate = !controls.autoRotate;
  rotateButton.setAttribute('aria-pressed', String(controls.autoRotate));
  if (controls.autoRotate) clearCameraViewSelection();
  requestRender();
}

function setStockWheelAssetVisibility(root, visible) {
  if (!root) return;
  root.traverse(mesh => {
    if (!mesh.isMesh) return;
    const identity = meshIdentity(mesh);
    const partType = String(mesh.userData?.lo4_part_type || '');
    const wheelLike = partType === 'WheelStyle'
      || identity.includes('tire')
      || identity.includes('tyre')
      || identity.includes('wheel')
      || identity.includes('rim');
    if (wheelLike && mesh.userData?.lo4_base_visible !== false) {
      mesh.visible = visible && meshPartVisible(mesh);
    }
  });
}

function toggleWheels() {
  if (viewerDisposed) return;
  wheelsVisible = wheelsCheckbox.checked;
  for (const group of inspectionWheelGroups.values()) group.visible = wheelsVisible;
  if (inspectionWheels) inspectionWheels.visible = wheelsVisible;
  if (wheelSource === 'stock' || wheelSource === 'source-verified') {
    for (const root of variantRoots.values()) setStockWheelAssetVisibility(root, wheelsVisible);
  }
  requestRender();
  viewerEvent('wheels', '', {visible: wheelsVisible, source: wheelSource});
}

function reloadViewerOption(name, value) {
  saveViewerReloadState();
  const url = new URL(window.location.href);
  url.searchParams.set(name, value);
  window.location.replace(url.toString());
}

function restoreViewerReloadState() {
  const state = pendingReloadState;
  pendingReloadState = null;
  if (!state) return 'all';
  const cameraValue = Array.isArray(state.camera) ? state.camera.map(Number) : [];
  const targetValue = Array.isArray(state.target) ? state.target.map(Number) : [];
  if (
    cameraValue.length === 3 && targetValue.length === 3
    && [...cameraValue, ...targetValue].every(Number.isFinite)
  ) {
    camera.position.fromArray(cameraValue);
    controls.target.fromArray(targetValue);
    controls.update();
  }
  const section = String(state.section || 'all');
  const option = sectionFilterSelect
    ? [...sectionFilterSelect.options].find(item => item.value === section)
    : null;
  return option && !option.disabled ? section : 'all';
}

function changeMaterialMode() {
  markDisplayPresetCustom();
  materialMode = materialModeSelect.value;
  setStatus('');
  applyLightProfile(materialMode);
  if (!canCompareMaterials()) compareMode = 'off';
  replaceViewerParam('material', materialMode, 'asset_routing');
  updateCompareControls();
  rebuildStudioEnvironment();
  requestRender();
  viewerEvent('material-mode', '', {materialMode, compareMode: effectiveCompareMode()});
}

function changeCompareMode() {
  markDisplayPresetCustom();
  compareMode = compareModeSelect.value;
  if (!canCompareMaterials()) compareMode = 'off';
  replaceViewerParam('compare', compareMode, 'off');
  updateCompareControls();
  requestRender();
  viewerEvent('compare-mode', '', {compareMode: effectiveCompareMode()});
}

function previewCompareSplit() {
  compareSplitOutput.value = `${Math.round(Number(compareSplitInput.value) || 0)}%`;
}

function changeCompareSplit() {
  markDisplayPresetCustom();
  compareSplit = THREE.MathUtils.clamp(Number(compareSplitInput.value) || 50, 10, 90);
  syncCompareOutputs();
  replaceViewerParam('compare-split', compareSplit, 50);
  updateCompareInfo();
  requestRender();
}

function previewDifferenceGain() {
  const preview = THREE.MathUtils.clamp(Number(differenceGainInput.value) || 6, 1, 12);
  differenceGainOutput.value = `${preview.toFixed(preview % 1 === 0 ? 0 : 1)}×`;
}

function changeDifferenceGain() {
  markDisplayPresetCustom();
  differenceGain = THREE.MathUtils.clamp(Number(differenceGainInput.value) || 6, 1, 12);
  syncCompareOutputs();
  replaceViewerParam('difference-gain', differenceGain, 6);
  updateCompareInfo();
  requestRender();
}

function changeGlassMode() {
  markDisplayPresetCustom();
  reloadViewerOption('glass', glassModeSelect.value);
}

function changeEnvironmentMode() {
  markDisplayPresetCustom();
  environmentMode = environmentModeSelect.value;
  if (!reflectionStrengthExplicit) {
    reflectionStrength = defaultReflectionStrengthForEnvironment(environmentMode);
    applyReflectionStrength();
  }
  replaceViewerParam('environment', environmentMode, 'home_soft');
  applyEnvironmentPresentation();
  applyLightProfile(materialMode);
  updateCompareControls();
  rebuildStudioEnvironment();
  viewerEvent('environment-mode', '', {environmentMode, reflectionStrength});
}

function previewReflectionAngle() {
  reflectionAngleOutput.value = `${Math.round(Number(reflectionAngleInput.value) || 0)}°`;
}

function changeReflectionAngle() {
  markDisplayPresetCustom();
  reflectionAngle = THREE.MathUtils.clamp(Number(reflectionAngleInput.value) || 0, -90, 90);
  reflectionAngleInput.value = String(reflectionAngle);
  reflectionAngleOutput.value = `${Math.round(reflectionAngle)}°`;
  replaceViewerParam('reflection-angle', reflectionAngle, 0);
  if (environmentMode === 'sweep' || environmentMode === 'reference') rebuildStudioEnvironment();
  viewerEvent('reflection-angle', '', {reflectionAngle});
}


function applyReflectionStrength() {
  // Three.js r185ではmaterial.envMap=nullのPBR材質がscene.environmentからIBLを
  // 受け取る場合、Scene.environmentIntensityを用いる。
  // この構成でmaterial.envMapIntensityを変えても実際の環境反射は変わらないため、
  // r59の0.50〜2.50倍スイープは変化して見えなかった。
  scene.environmentIntensity = reflectionStrength;
  reflectionStrengthInput.value = String(reflectionStrength);
  reflectionStrengthOutput.value = `${reflectionStrength.toFixed(2)}×`;
  requestRender();
}

function previewReflectionStrength() {
  reflectionStrength = THREE.MathUtils.clamp(Number(reflectionStrengthInput.value) || defaultReflectionStrengthForEnvironment(environmentMode), 0.5, 2.5);
  applyReflectionStrength();
}

function changeReflectionStrength() {
  markDisplayPresetCustom();
  reflectionStrength = THREE.MathUtils.clamp(Number(reflectionStrengthInput.value) || defaultReflectionStrengthForEnvironment(environmentMode), 0.5, 2.5);
  reflectionStrengthExplicit = true;
  applyReflectionStrength();
  replaceViewerParam('reflection-strength', reflectionStrength, defaultReflectionStrengthForEnvironment(environmentMode));
  viewerEvent('reflection-strength', '', {reflectionStrength});
}

async function changeRenderQuality() {
  markDisplayPresetCustom();
  renderQuality = renderQualitySelect.value;
  replaceViewerParam('render-quality', renderQuality, 'reference');
  updateRenderInfo();
  requestRender();
  viewerEvent('render-quality', '', {renderQuality});
  const nativeApi = window.pywebview?.api;
  if (!nativeApi?.set_quality_preset) return;
  try {
    setStatus(t('status.quality_rebuild'));
    const result = await nativeApi.set_quality_preset(renderQuality);
    if (!result?.ok) {
      setStatus(t('error.quality_rebuild', {message: result?.error || 'unknown error'}), true);
      return;
    }
    if (result.reload) {
      window.location.reload();
    } else {
      setStatus('');
    }
  } catch (error) {
    setStatus(t('error.quality_rebuild', {message: error?.message || String(error)}), true);
  }
}

function changeAAMode() {
  markDisplayPresetCustom();
  aaMode = aaModeSelect.value;
  replaceViewerParam('aa', aaMode, 'off');
  updateRenderInfo();
  requestRender();
  viewerEvent('aa-mode', '', {aaMode});
}

function changeLanguage() {
  setLanguage(languageSelect.value);
  applyTranslations(document);
  updateBodyKitControl();
  updatePartOptionControls();
  syncCompareOutputs();
  updateCompareInfo();
  updateRenderInfo();
  updateVehicleInfo();
  updateDemoTitle();
  updateAssemblyInfo();
  updateFinishInfo(activeSectionFilter);
  requestRender();
}

function changeSectionFilter() {
  const option = sectionFilterSelect?.selectedOptions?.[0];
  if (!option || option.disabled) return;
  markDisplayPresetCustom();
  setSectionFilter(sectionFilterSelect.value);
  viewerEvent('section-filter', '', {section: activeSectionFilter});
}

function resetFromDoubleClick() {
  resetView();
}

/**
 * 同じ3DシーンとGPU最終レンダラーを6方向から順に使用。
 * 保存中はカメラ・ズーム・初期位置・回転設定を退避して必ず復元する。
 * Wheel材質・Tire・C_livery・Glass・UV3等の実装を一切変更しない。
 */
async function requestSixCarViews(format) {
  if (viewerDisposed || !modelReady || !firstFrameReady || rmCaptureBusy || rmCaptureFormat || !modelBounds) {
    setStatus(t('capture.six_not_ready'), true);
    return;
  }
  rmCaptureBusy = true;
  for (const button of [captureJpegButton,capturePngButton,sixViewsJpegButton,sixViewsPngButton]) button.disabled = true;
  const pose = {
    position: camera.position.clone(), up: camera.up.clone(), target: controls.target.clone(),
    quaternion: camera.quaternion.clone(), near: camera.near, far: camera.far, zoom: camera.zoom,
    damping: controls.enableDamping, rotation: controls.autoRotate,
    minDistance: controls.minDistance, maxDistance: controls.maxDistance,
    homePosition: homeCamera.clone(), homeTarget: homeTarget.clone(),
  };
  // 6 方向を描いた後、保存を始める前に元の向きへ戻して描き直す（2026-11-21）。各方向は見えている画面に描いて
  // 読み取るので、戻すのが保存の後だと、保存の窓が開いている間も最後の方向（下面）が画面に残っていた。
  // 同じ処理の中で描き直すので、画面が更新されるときには元の表示になっている。
  let poseRestored = false;
  const restoreSixViewPose = () => {
    if (poseRestored) return;
    poseRestored = true;
    // frameModelが毎回更新するhome位置も含め、元の通常Viewへ必ず戻す。
    camera.position.copy(pose.position); camera.up.copy(pose.up);
    camera.quaternion.copy(pose.quaternion);
    camera.near=pose.near; camera.far=pose.far; camera.zoom=pose.zoom;
    camera.updateProjectionMatrix();
    controls.target.copy(pose.target); controls.minDistance=pose.minDistance;
    controls.maxDistance=pose.maxDistance; controls.enableDamping=false;
    controls.autoRotate=false; controls.update();
    homeCamera.copy(pose.homePosition); homeTarget.copy(pose.homeTarget);
    controls.enableDamping=pose.damping; controls.autoRotate=pose.rotation;
    setVariantVisibility(null);
  };
  try {
    controls.enableDamping = false;
    controls.autoRotate = false;
    // 表示中のGPU解像度を維持する。画像を拡大して架空の高画質としない。
    const width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
    if (!width || !height || width !== canvas.width || height !== canvas.height) {
      throw new Error('6方向画像のGPU描画サイズが一致しません');
    }
    const viewCanvas = document.createElement('canvas');
    viewCanvas.width = width; viewCanvas.height = height;
    const viewCtx = viewCanvas.getContext('2d');
    if (!viewCtx) throw new Error('各方向の画像読込Canvasを作成できません');
    const image = composeSixCarViews({width,height,
      createCanvas: () => document.createElement('canvas'),
      renderView: directionName => {
        const direction = CAMERA_VIEW_DIRECTIONS[directionName];
        if (!direction) throw new Error('未対応のカメラ方向です: ' + directionName);
        const bounds = cameraFrameBounds || modelBounds;
        // 上面・下面だけ撮影時の上方向を原本の車体軸に合わせる。
        // 画像の事後回転ではなくGPUレンダリング時に横向きで大きく収める。
        const overheadUp = directionName === 'top' || directionName === 'bottom'
          ? horizontalOverheadCameraUp(bounds, (x, y, z) => new THREE.Vector3(x, y, z))
          : null;
        frameModel(bounds, direction, overheadUp);
        controls.update();
        if (demoMosaicBody.checked) renderDemoProtected(performance.now());
        else renderSelectedMode(performance.now());
        setVariantVisibility(null);
        if (gl.getParameter(gl.FRAMEBUFFER_BINDING) !== null) {
          throw new Error('6方向GPU描画の標準フレームバッファを復元できません');
        }
        frameBufferImage(viewCtx, bytes => {
          gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,bytes);
          const error = gl.getError();
          if (error !== gl.NO_ERROR) throw new Error('6方向GPU画素取得失敗: ' + error);
        },width,height);
        return viewCanvas;
      },
      // 各マスの見出しは画面の言葉に合わせる（日本語は今までどおり。2026-11-21）
      views:SIX_CAR_VIEWS.map(view => ({...view, label: t(`capture.view.${view.key}`)})),
    });
    restoreSixViewPose();
    if (demoMosaicBody.checked) renderDemoProtected(performance.now());
    else renderSelectedMode(performance.now());
    setVariantVisibility(null);
    const capturedAt = new Date();
    const name = captureFilename(format, capturedAt).replace('Livery-Viewer-for-FH6-', 'Livery-Viewer-for-FH6-SixViews-');
    // 画像の下に、タイトル・作成者・アップロード日・撮影日時の帯を付けて保存する
    const result = await saveCaptureImage(withCaptureCaption(image, capturedAt),name,
      {format,quality:0.95,downloadFallback:downloadImage});
    if (result.cancelled) showImageSaveNotice(t('capture.six_cancelled'));
    else if (result.requestedOnly) showImageSaveNotice(t('capture.six_download_requested'));
    else showImageSaveNotice(t('capture.six_saved', {path: result.path, bytes: result.bytes, width: result.width, height: result.height}));
  } catch(error) {
    showImageSaveNotice(t('capture.six_failed', {message: String(error?.message || error)}),true);
  } finally {
    // 途中で失敗したときも、元の通常Viewへ必ず戻す（戻し済みなら何もしない）。
    restoreSixViewPose();
    rmCaptureBusy = false;
    for (const button of [captureJpegButton,capturePngButton,sixViewsJpegButton,sixViewsPngButton]) button.disabled = false;
    requestRender();
  }
}

sixViewsJpegButton.addEventListener('click', () => { void requestSixCarViews('jpeg'); });
sixViewsPngButton.addEventListener('click', () => { void requestSixCarViews('png'); });

function requestRmCapture(format) {
  if (viewerDisposed || !modelReady || !firstFrameReady || rmCaptureBusy || rmCaptureFormat) {
    setStatus(t('capture.not_ready'), true);
    return;
  }
  rmCaptureFormat = format;
  rmCaptureBusy = true;
  captureJpegButton.disabled = true;
  capturePngButton.disabled = true;
  sixViewsJpegButton.disabled = true;
  sixViewsPngButton.disabled = true;
  requestRender();
}
function finishRmCapture(message, error = false) {
  rmCaptureBusy = false;
  captureJpegButton.disabled = false;
  capturePngButton.disabled = false;
  sixViewsJpegButton.disabled = false;
  sixViewsPngButton.disabled = false;
  showImageSaveNotice(message, error);
}
captureJpegButton.addEventListener('click', () => requestRmCapture('jpeg'));
capturePngButton.addEventListener('click', () => requestRmCapture('png'));
resetButton.addEventListener('click', resetView);
rotateButton.addEventListener('click', toggleAutoRotate);
wheelsCheckbox.addEventListener('change', toggleWheels);
demoHideTitle.addEventListener('change', changeDemoTextPrivacy);
demoHideSource.addEventListener('change', changeDemoTextPrivacy);
demoMosaicBody.addEventListener('change', changeDemoMosaicPrivacy);
demoMosaicStrength.addEventListener('change', requestRender);
demoMosaicStrength.disabled = true;
displayPresetSelect.addEventListener('change', changeDisplayPreset);
materialModeSelect.addEventListener('change', changeMaterialMode);
compareModeSelect.addEventListener('change', changeCompareMode);
compareSplitInput.addEventListener('input', previewCompareSplit);
compareSplitInput.addEventListener('change', changeCompareSplit);
differenceGainInput.addEventListener('input', previewDifferenceGain);
differenceGainInput.addEventListener('change', changeDifferenceGain);
glassModeSelect.addEventListener('change', changeGlassMode);
environmentModeSelect.addEventListener('change', changeEnvironmentMode);
reflectionAngleInput.addEventListener('input', previewReflectionAngle);
reflectionAngleInput.addEventListener('change', changeReflectionAngle);
reflectionStrengthInput.addEventListener('input', previewReflectionStrength);
reflectionStrengthInput.addEventListener('change', changeReflectionStrength);
renderQualitySelect.addEventListener('change', changeRenderQuality);
aaModeSelect.addEventListener('change', changeAAMode);
languageSelect.addEventListener('change', changeLanguage);
bodyKitSelect.addEventListener('change', changeBodyKit);
sectionFilterSelect?.addEventListener('change', changeSectionFilter);
viewButtons.forEach(button => button.addEventListener('click', selectCameraView));
controls.addEventListener('start', clearCameraViewSelection);
controls.addEventListener('change', requestRender);

function updateRenderInfo() {
  if (!renderInfo) return;
  const drawingBuffer = renderer.getDrawingBufferSize(new THREE.Vector2());
  const paintSize = Array.isArray(renderContract?.paint_size) ? renderContract.paint_size : [];
  const profile = qualityProfile();
  const qualityKey = renderQuality === 'reference'
    ? 'render.reference'
    : renderQuality === 'high'
      ? 'render.high'
      : renderQuality === 'minimum'
        ? 'render.minimum'
        : 'render.standard';
  const atlasText = paintSize.length === 2
    ? t('info.atlas', {
      scale: renderContract?.quality_scale || 1,
      width: paintSize[0],
      height: paintSize[1],
    })
    : '';
  const aaLabel = aaMode === 'off'
    ? t('aa.off')
    : presentationAAEnabled
      ? t('aa.post_mode', {mode: t(`aa_mode.${aaMode}`)})
      : presentationAAFallbackReason
        ? t('aa.fallback')
        : t('aa.off');
  const sectionCompositeSupersample = Math.max(1, Number(renderContract?.section_composite_supersample) || 1);
  const sourceAaText = sectionCompositeSupersample > 1
    ? t('info.source_aa', {scale: sectionCompositeSupersample})
    : '';
  renderInfo.textContent = t('info.render', {
    quality: t(qualityKey),
    width: Math.round(drawingBuffer.x),
    height: Math.round(drawingBuffer.y),
    dpr: renderPixelRatio.toFixed(2),
    atlas: atlasText,
    sourceAa: sourceAaText,
    aa: aaLabel,
  });
  renderInfo.title = presentationAAFallbackReason
    ? t('aa.fallback_reason', {reason: presentationAAFallbackReason})
    : '';
}

function resize() {
  const width = Math.max(1, viewport.clientWidth);
  const height = Math.max(1, viewport.clientHeight);
  const profile = qualityProfile();
  const resourcePixelBudget = Math.max(1, (gpuBudgetBytes - modelResourceBytes) * .9 / 40);
  const pixelBudget = Math.min(
    profile.pixelBudget,
    renderQuality === 'reference'
      ? Math.max(profile.minimumPixelBudget || 1, resourcePixelBudget)
      : resourcePixelBudget,
  );
  const devicePixelRatio = window.devicePixelRatio || 1;
  const referenceTargetRatio = renderQuality === 'reference'
    ? Math.min(profile.dprCap, Math.max(1, (profile.targetWidth || width) / width))
    : devicePixelRatio;
  const requestedPixelRatio = profile.forceSupersample
    ? Math.max(devicePixelRatio, referenceTargetRatio)
    : devicePixelRatio;
  const pixelRatio = Math.min(
    requestedPixelRatio,
    profile.dprCap,
    Math.sqrt(pixelBudget / (width * height))
  );
  if (width === renderWidth && height === renderHeight && pixelRatio === renderPixelRatio) {
    updateRenderInfo();
    return;
  }
  renderWidth = width;
  renderHeight = height;
  renderPixelRatio = pixelRatio;
  renderer.setPixelRatio(pixelRatio);
  renderer.setSize(width, height, false);
  disposeCompareTargets();
  disposePresentationTargets();
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  updateRenderInfo();
}

function renderFrame(timestamp) {
  animationFrameId = 0;
  if (viewerDisposed || document.hidden) return;
  // 差し替えの間は描かない（前のペイントの最後の 1 枚を見せたままにし、車の無い場面を一瞬も描かない）。
  if (paintSwapInProgress && !modelReady) return;
  // r402：非同期GPU Paint生成中でも面フィルターやUI操作から描画要求が入る。
  // 最終paintMapの受渡し確認前に、研究用の旧CPU仮画像を表示してはならない。
  // 高リフレッシュレート画面を含め、連続Animationは60Hz以下に制限する。
  if (lastFrameAt && timestamp - lastFrameAt < 15) { requestRender(); return; }
  const delta = lastFrameAt ? Math.min((timestamp - lastFrameAt) / 1000, .1) : 1 / 60;
  lastFrameAt = timestamp;
  const frameStart = performance.now();
  resize();
  const resizeFinish = performance.now();
  controls.update(delta);
  const controlsFinish = performance.now();
  const profilingFirstFrame = modelReady && !firstFrameReady;
  // r409：表示後に同一WebGLコンテキストで1回だけウォーム描画する。
  // 端末固有のコンパイル済みGPUバイナリは保存せず、Program再利用を計測する。
  const profilingSecondFrame = modelReady && firstFrameReady
    && !Number.isFinite(timings.secondFrameRenderMs);
  const glProfile = (profilingFirstFrame || profilingSecondFrame)
    ? createFirstFrameWebglProfiler(gl) : null;
  const renderPassProfile = profilingFirstFrame ? createFirstFrameRenderPassProfiler(renderer, gl) : null;
  const programsBefore = (profilingFirstFrame || profilingSecondFrame)
    ? (renderer.info.programs?.length || 0) : 0;
  try {
    if (demoMosaicBody.checked && modelReady) renderDemoProtected(timestamp);
    else renderSelectedMode(timestamp);
    setVariantVisibility(null);
    lastRenderableMaterialMode = materialMode;
  } catch (error) {
    setVariantVisibility(null);
    if (demoMosaicBody.checked) {
      viewport.classList.remove('demo-vehicle-pending');
      viewport.classList.add('demo-vehicle-failed');
      setStatus(t('demo.error'), true);
      return;
    }
    if (recoverMaterialShaderFailure(error)) return;
    failViewer(error?.message || String(error));
    return;
  } finally {
    if (renderPassProfile) Object.assign(timings, renderPassProfile.finish());
    if (glProfile) {
      const metrics = glProfile.finish();
      if (profilingSecondFrame) {
        timings.secondFrameGlGetProgramInfoLogMs = Number(metrics.firstFrameGlGetProgramInfoLogMs || 0);
        timings.secondFrameGlGetProgramParameterMs = Number(metrics.firstFrameGlGetProgramParameterMs || 0);
        timings.secondFrameGlTextureMs = Number(metrics.firstFrameGlTextureMs || 0);
        timings.secondFrameNewPrograms = Math.max(0, (renderer.info.programs?.length || 0) - programsBefore);
      } else {
        Object.assign(timings, metrics);
      }
    }
    if (profilingFirstFrame) {
      timings.firstFrameProgramsBefore = programsBefore;
      timings.firstFrameProgramsAfter = renderer.info.programs?.length || 0;
    }
  }
  // rM002: 旧r485と同じ最終描画を読み取るだけ。GPUの描画パスを変更しない。
  // アンチエイリアス・材質・ペイント・カメラは直前のrenderSelectedModeが確定済み。
  if (rmCaptureFormat && modelReady) {
    const format = rmCaptureFormat;
    rmCaptureFormat = null;
    try {
      const image = document.createElement('canvas');
      let releaseCaptureEvidence = null;
      const captureFinalFrame = () => {
        const width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
        if (width !== canvas.width || height !== canvas.height || width <= 0 || height <= 0) {
          throw new Error('GPU描画サイズと保存サイズが一致しません');
        }
        if (gl.getParameter(gl.FRAMEBUFFER_BINDING) !== null) {
          throw new Error('画面以外のGPUバッファが選択されているため保存を中止します');
        }
        image.width = width; image.height = height;
        const ctx = image.getContext('2d');
        if (!ctx) throw new Error('画像保存用Canvasを作成できません');
        frameBufferImage(ctx, bytes => {
          gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
          const error = gl.getError();
          if (error !== gl.NO_ERROR) throw new Error(`GPU読取に失敗: ${error}`);
        }, width, height);
        if (releaseSceneCaptureAuditRequested) {
          const auditVariant = sourceWheelMaterialAudit.variants.get(materialMode);
          const counts = variantCounts.get(materialMode) || {};
          const record = evaluateReleaseSceneCapture({
            webgl2:renderer.capabilities.isWebGL2 === true,
            frame:{width,height,pixelReadbackOk:true,defaultFramebuffer:true},
            compareMode:effectiveCompareMode(),demoMosaic:demoMosaicBody.checked,
            paint:{policy:renderContract?.cpu_shadow_policy,
              rasterizer:renderContract?.paint_rasterizer,completed:gpuOnlyPaintCompleted},
            body:{meshCount:counts.meshCount,paintCount:counts.paintCount,glassCount:counts.glassCount},
            wheels:{source:wheelSource,visible:wheelsVisible,
              declaredPrimitives:sourceWheelMaterialAudit.declared?.signedWheelPrimitives,
              receivedPrimitives:receivedWheelGlbAudit?.signedWheelPrimitives,
              loaderRecognized:sourceWheelMaterialAudit.glb,
              retained:auditVariant?.retained,
              submitted:auditVariant?.drawn?.size},
            appearance:{sourceMaterial:sourceNeutralResearch,neutralGrade:sourceLiveryNeutralResearch},
            requireGlass:releaseRequireGlass,
          });
          releaseCaptureEvidence = record;
          window.__lo4fh6ReleaseSceneCaptureAudit = record;
          viewerEvent('release-scene-capture-audit', record.status, record);
        }
        return {width, height};
      };
      // 画面前フレームのonBeforeRenderを使い回さない。受入URLでは撮影フレーム分を実測。
      let releaseCaptureFrameRead = false;
      withReferenceCaptureResolution({
        renderer, gl, cssWidth: renderWidth, cssHeight: renderHeight,
        pixelRatio: renderPixelRatio, reference: renderQuality === 'reference',
        maxPixels: Math.max(1, Math.floor(Math.min(
          qualityProfile().pixelBudget,
          Math.max(0, (gpuBudgetBytes - modelResourceBytes) * .9 / 40)
        ))),
        renderFrame: () => {
          if (releaseSceneCaptureAuditRequested && !releaseCaptureFrameRead) {
            for (const variant of sourceWheelMaterialAudit.variants.values()) variant.drawn?.clear?.();
          }
          if (demoMosaicBody.checked && modelReady) renderDemoProtected(timestamp);
          else renderSelectedMode(timestamp);
          setVariantVisibility(null);
        },
        capture: () => {
          const result = captureFinalFrame();
          releaseCaptureFrameRead = true;
          return result;
        },
      });
      const capturedAt = new Date();
      const filename = captureFilename(format, capturedAt);
      // 画像の下に、タイトル・作成者・アップロード日・撮影日時の帯を付けて保存する。受け入れの撮影の診断
      // （明示して起動したときだけ）は、GPU の描画と保存した画像の寸法を比べるので、帯を付けない。
      const output = releaseSceneCaptureAuditRequested ? image : withCaptureCaption(image, capturedAt);
      void saveCaptureImage(output, filename, {format, quality: 0.95, downloadFallback: downloadImage})
        .then(async result => {
          // 保存完了の実バイトSHAだけを撮影GPU証拠に結合。所有者の保存先パスは証拠JSONへ記録しない。
          if (releaseSceneCaptureAuditRequested && releaseCaptureEvidence) {
            const api = window.pywebview?.api;
            if (typeof api?.record_release_scene_capture === 'function') {
              const receipt = await api.record_release_scene_capture({
                audit:releaseCaptureEvidence,
                image:{verified:result?.verified===true,format,
                  sha256:result?.sha256??null,bytes:result?.bytes??null,
                  width:result?.width??null,height:result?.height??null},
              });
              viewerEvent('release-scene-capture-receipt', receipt?.ok ? 'verified' : 'failed',
                {status:receipt?.status??null,sha256:receipt?.sha256??null});
              if (!receipt?.ok) console.error('4K撮影証拠の記録に失敗:', receipt?.error || '不明');
            }
          }
          if (result.cancelled) finishRmCapture(t('capture.cancelled'));
          else if (result.requestedOnly) finishRmCapture(t('capture.download_requested'));
          else finishRmCapture(t('capture.saved', {path: result.path, bytes: result.bytes, width: result.width, height: result.height}));
        })
        .catch(error => finishRmCapture(t('capture.failed', {message: error.message}), true));
    } catch (error) {
      finishRmCapture(t('capture.failed', {message: error.message}), true);
    }
  }
  const sceneRenderFinish = performance.now();
  renderedFrames += 1;
  // requestRender() と camera-view 通知はフレーム描画前に発生するため、
  // 撮影者は本イベントの輪位置とフレーム番号を照合してからCanvasを保存する。
  // 元材質・カメラ位置・通常GUI描画には手を加えない。
  if (pendingCameraViewFrame !== null && modelReady
      && renderer.capabilities.isWebGL2 === true
      && !gl.isContextLost() && renderer.info.render.calls > 0) {
    viewerEvent('camera-view-rendered', '', {
      view: pendingCameraViewFrame,
      frame: renderedFrames,
      webgl2: true,
      drawCalls: renderer.info.render.calls,
    });
    pendingCameraViewFrame = null;
  }
  frameTime = performance.now() - frameStart;
  frameTimeTotal += frameTime;
  frameTimePeak = Math.max(frameTimePeak, frameTime);
  if (profilingSecondFrame) {
    timings.secondFrameRenderMs = Math.round(frameTime);
    // 初回Paintの時刻は前のフレームで取得済み。
    // 表示後Warmup描画の計測値で上書きしない。
    if (Number.isFinite(timings.firstPaintOpportunity)) {
      void reportViewerDisplayProfile();
    }
    if (atlasPngProbeRequested && !atlasPngProbeStarted) {
      atlasPngProbeStarted = true;
      timings.gpuAtlasPngProbeRequested = 1;
      // 負荷の高い可逆圧縮は2回の描画成功後まで延期する。
      window.setTimeout(async () => {
        const probeCanvas = atlasPngProbeCanvas;
        atlasPngProbeCanvas = null;
        try {
          const result = !viewerDisposed && probeCanvas
            ? await measureLosslessAtlasPng(probeCanvas, {measureReadback:true}) : null;
          // Timeoutで既に失敗レポートを書いている場合があるため競合させない。
          if (atlasPngProbeFinished) return;
          timings.gpuAtlasPngProbeSucceeded = result?.ok ? 1 : 0;
          timings.gpuAtlasPngProbeFailureCode = result?.ok ? 0 : (result?.failureCode || (viewerDisposed ? 6 : 5));
          if (result?.ok) {
            timings.gpuAtlasPngBytes = result.pngBytes;
            timings.gpuAtlasRawRgbaBytes = result.rawRgbaBytes;
            timings.gpuAtlasPngEncodeMs = result.encodeMs;
            timings.gpuAtlasPngWidth = result.width;
            timings.gpuAtlasPngHeight = result.height;
            // GPU Readbackは別の診断処理。失敗しても表示中のAtlasには影響させない。
            const roundTrip = result.roundTrip;
            timings.gpuAtlasReadbackSucceeded = roundTrip?.ok ? 1 : 0;
            timings.gpuAtlasReadbackFailureCode = roundTrip?.failureCode || 0;
            if (roundTrip?.ok) {
              timings.gpuAtlasReadbackDecodeMs = roundTrip.decodeMs;
              timings.gpuAtlasReadbackDrawMs = roundTrip.drawMs;
              timings.gpuAtlasReadbackCompareMs = roundTrip.compareMs;
              timings.gpuAtlasReadbackComparedComponents = roundTrip.comparedComponents;
              timings.gpuAtlasReadbackMismatchedComponents = roundTrip.mismatchedComponents;
              timings.gpuAtlasReadbackMaxAbsoluteError = roundTrip.maxAbsoluteError;
              timings.gpuAtlasReadbackPixelExact = roundTrip.pixelExact;
            }
            // r416：OPFSへ書くのは合成バイトだけで、実Paint／PNGは絶対に保存しない。
            // 初回Paint後に実施する任意処理であり、Storageが利用できない場合もある。
            const syntheticIo = await measureSyntheticOpfsIo(result.pngBytes);
            if (atlasPngProbeFinished || viewerDisposed) return;
            timings.gpuAtlasSyntheticIoSucceeded = syntheticIo.ok ? 1 : 0;
            timings.gpuAtlasSyntheticIoFailureCode = syntheticIo.failureCode || 0;
            timings.gpuAtlasSyntheticIoCleanupSucceeded = syntheticIo.cleanupSucceeded;
            if (syntheticIo.ok) {
              timings.gpuAtlasSyntheticIoBytes = syntheticIo.bytes;
              timings.gpuAtlasSyntheticIoWriteMs = syntheticIo.writeMs;
              timings.gpuAtlasSyntheticIoReadMs = syntheticIo.readMs;
              timings.gpuAtlasSyntheticIoVerifyMs = syntheticIo.verifyMs;
            }
            // 実際のPNGペイロード容量だけを比較し、Tile保存や表示中Atlasの変更はしない。
            const sparse = await measureSparseAtlasTiles(probeCanvas);
            if (atlasPngProbeFinished || viewerDisposed) return;
            timings.gpuAtlasSparsePngSucceeded = sparse.ok ? 1 : 0;
            timings.gpuAtlasSparsePngFailureCode = sparse.failureCode || 0;
            if (sparse.ok) {
              timings.gpuAtlasSparsePngBytes = sparse.encodedBytes;
              timings.gpuAtlasSparsePngTotalTiles = sparse.totalTiles;
              timings.gpuAtlasSparsePngNonzeroTiles = sparse.nonzeroTiles;
              timings.gpuAtlasSparsePngZeroTiles = sparse.zeroTiles;
              timings.gpuAtlasSparsePngEncodeMs = sparse.encodeMs;
            }
          }
        } catch (_) {
          if (!atlasPngProbeFinished) {
            timings.gpuAtlasPngProbeSucceeded = 0;
            timings.gpuAtlasPngProbeFailureCode = 3;
          }
        } finally {
          if (!atlasPngProbeFinished) {
            atlasPngProbeFinished = true;
            if (!viewerDisposed) void reportViewerDisplayProfile();
          }
        }
      }, 50);
    }
  }
  if (modelReady && !firstFrameReady) {
    firstFrameReady = true;
    reportViewerStage('first_frame');
    if (paintSwapRetired) {
      // 差し替えの新しい場面を描けた。前のペイントの資源を捨てる（新しい材質がシェーダーを使い始めた後なので、
      // シェーダーは捨てられない）。
      const retired = paintSwapRetired;
      paintSwapRetired = null;
      paintSwapInProgress = false;
      window.clearTimeout(paintSwapTimer);
      paintSwapTimer = 0;
      const disposal = disposeRetiredPaintResources(retired);
      disposal.released += releaseUnusedCarriedTextures();
      viewerEvent('paint-swapped', '', {retiredMaterials: retired.materials.size, retiredTextures: retired.textures.size,
        retiredGeometries: retired.geometries.size, kept: disposal.kept, releasedImages: disposal.released});
    }
    timings.firstFrame = Math.round(performance.now() - startedAt);
    timings.firstFrameRenderMs = Math.round(frameTime);
    timings.firstFrameResizeMs = Math.round(resizeFinish - frameStart);
    timings.firstFrameControlsMs = Math.round(controlsFinish - resizeFinish);
    timings.firstFrameSceneRenderMs = Math.round(sceneRenderFinish - controlsFinish);
    if (Number.isFinite(timings.scene)) {
      timings.sceneToFirstFrameMs = Math.max(0, timings.firstFrame - timings.scene);
    }
    // 次のAnimation Callbackは画面表示可能になる最初の機会の概算であり、
    // 実測のDisplay Scanout時刻ではない。
    window.requestAnimationFrame(() => {
      if (viewerDisposed) return;
      timings.firstPaintOpportunity = Math.round(performance.now() - startedAt);
      // r409の同一コンテキスト内Warm Cache調査には追加描画が1回必要。
      // この時点で通常の厳密なPaint描画は完了している。
      requestRender();
      // 初回Shader失敗は既存の同期Three.js例外処理に任せる。
      // 2フレーム目の計測とレポート保存は通常経路で継続する。
    });
    if (atlasPngProbeRequested) {
      window.setTimeout(() => {
        if (viewerDisposed || atlasPngProbeFinished) return;
        // 表示レポート全体を永久に止めるのではなく、安全に失敗として処理する。
        atlasPngProbeFinished = true;
        timings.gpuAtlasPngProbeRequested = 1;
        if (timings.gpuAtlasPngProbeSucceeded === 1) {
          // r413：任意のTile処理だけがTimeoutしても、有効な全体PNG計測値は保持する。
          timings.gpuAtlasSparsePngSucceeded = 0;
          timings.gpuAtlasSparsePngFailureCode = 5;
        } else {
          timings.gpuAtlasPngProbeSucceeded = 0;
          // 7：Encode Callbackが診断時間の上限内に終了しなかった。
          // 8：後続フレームを予約できなかった。
          timings.gpuAtlasPngProbeFailureCode = atlasPngProbeStarted ? 7 : 8;
        }
        void reportViewerDisplayProfile();
      }, 30000);
    }
    for (const delayMs of [250, 1000, 3000]) {
      window.setTimeout(() => { if (!viewerDisposed && !viewerDisplayReportSaved) void reportViewerDisplayProfile(); }, delayMs);
    }
    window.clearTimeout(loadTimeout);
    if (stockOnlyGpuSession) {
      const stockGpuValid = renderer.capabilities.isWebGL2 === true
        && !gl.isContextLost() && gl.getError() === gl.NO_ERROR
        && renderer.info.render.triangles > 0 && stockOnlyGpuSession.visibleMeshes > 0
        && stockOnlyGpuSession.submittedBodyMeshes > 0;
      if (!stockGpuValid) {
        failViewer('原本Stock GLBのWebGL2描画フレーム検証に失敗');
        return;
      }
      viewerEvent('stock-body-gpu-first-frame', '', {
        ...stockOnlyGpuSession,
        webgl2:true, triangles:renderer.info.render.triangles,
        // 実GPUフレームのみ。Xbox見た目・Windows GUI・公開は別判定。
        xboxApproved:false, releaseApproved:false,
      });
    }
    setStatus('');
    viewerEvent('ready');
  }
  if (controls.autoRotate || effectiveCompareMode() === 'flicker') requestRender();
}

function requestRender() {
  if (!viewerDisposed && !document.hidden && !animationFrameId) {
    renderRequests += 1;
    animationFrameId = requestAnimationFrame(renderFrame);
  }
}

function handleResize() {
  resize();
  requestRender();
}

function handleVisibilityChange() {
  lastFrameAt = 0;
  if (document.hidden && animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = 0;
  } else {
    resize();
    requestRender();
  }
}

function releaseRendererContext() {
  if (rendererContextReleased) return;
  rendererContextReleased = true;
  renderer.renderLists.dispose();
  renderer.dispose();
  renderer.forceContextLoss();
}

function disposeViewer(releaseContext = true) {
  if (!viewerDisposed) {
    viewerDisposed = true;
    window.clearTimeout(loadTimeout);
    loadAbort.abort();
    if (animationFrameId) cancelAnimationFrame(animationFrameId);
    animationFrameId = 0;
    controls.removeEventListener('change', requestRender);
    controls.dispose();
    resetButton.removeEventListener('click', resetView);
    rotateButton.removeEventListener('click', toggleAutoRotate);
    rmCaptureFormat = null;
    wheelsCheckbox.removeEventListener('change', toggleWheels);
    demoHideTitle.removeEventListener('change', changeDemoTextPrivacy);
    demoHideSource.removeEventListener('change', changeDemoTextPrivacy);
    demoMosaicBody.removeEventListener('change', changeDemoMosaicPrivacy);
    demoMosaicStrength.removeEventListener('change', requestRender);
    demoVehicleMosaic?.dispose();
    demoVehicleMosaic = null;
    displayPresetSelect.removeEventListener('change', changeDisplayPreset);
    materialModeSelect.removeEventListener('change', changeMaterialMode);
    compareModeSelect.removeEventListener('change', changeCompareMode);
    compareSplitInput.removeEventListener('input', previewCompareSplit);
    compareSplitInput.removeEventListener('change', changeCompareSplit);
    differenceGainInput.removeEventListener('input', previewDifferenceGain);
    differenceGainInput.removeEventListener('change', changeDifferenceGain);
    glassModeSelect.removeEventListener('change', changeGlassMode);
    environmentModeSelect.removeEventListener('change', changeEnvironmentMode);
    reflectionAngleInput.removeEventListener('input', previewReflectionAngle);
    reflectionAngleInput.removeEventListener('change', changeReflectionAngle);
    reflectionStrengthInput.removeEventListener('input', previewReflectionStrength);
    reflectionStrengthInput.removeEventListener('change', changeReflectionStrength);
    renderQualitySelect.removeEventListener('change', changeRenderQuality);
    languageSelect.removeEventListener('change', changeLanguage);
    bodyKitSelect.removeEventListener('change', changeBodyKit);
    sectionFilterSelect?.removeEventListener('change', changeSectionFilter);
    viewButtons.forEach(button => button.removeEventListener('click', selectCameraView));
    controls.removeEventListener('start', clearCameraViewSelection);
    window.removeEventListener('dblclick', resetFromDoubleClick);
    window.removeEventListener('resize', handleResize);
    document.removeEventListener('visibilitychange', handleVisibilityChange);
    canvas.removeEventListener('webglcontextlost', handleContextLost);
    partControls.replaceChildren();
    selectedPartOptions.clear();
    selectablePartGroups.clear();
    trackedSkeletons.forEach(skeleton => skeleton.dispose());
    trackedGeometries.forEach(geometry => geometry.dispose());
    trackedMaterials.forEach(material => material.dispose());
    trackedTextures.forEach(texture => {
      texture.dispose();
      if (typeof texture.image?.close === 'function') texture.image.close();
    });
    trackedSkeletons.clear();
    trackedGeometries.clear();
    trackedMaterials.clear();
    trackedTextures.clear();
    if (studioEnvironmentTarget) {
      studioEnvironmentTarget.dispose();
      studioEnvironmentTarget = null;
    }
    disposeCompareTargets();
    disposePresentationTargets();
    compareCompositeScene = null;
    compareCompositeCamera = null;
    compareCompositeMaterial = null;
    presentationCompositeScene = null;
    presentationCompositeCamera = null;
    presentationCompositeMaterial = null;
    scene.environment = null;
    scene.clear();
    model = null;
    inspectionWheels = null;
    modelBounds = null;
    cameraFrameBounds = null;
    paintMaterials = [];
    glassMaterials = [];
    variantRoots.clear();
    variantPaintMaterials.clear();
    variantGlassMaterials.clear();
    variantCounts.clear();
    variantSourceModel = null;
    variantSourceProjectionBounds = null;
    variantSourcePaintTexture = null;
    variantSourceMasks = null;
    inspectionWheelGroups.clear();
    stockWheelAssetInventories.clear();
  }
  if (releaseContext) releaseRendererContext();
  return viewerDiagnostics();
}

function viewerDiagnostics() {
  return {
    disposed: viewerDisposed,
    contextReleased: rendererContextReleased,
    animationActive: Boolean(animationFrameId),
    ready: firstFrameReady,
    stockBodyOnly: stockOnlyGpuSession ? {...stockOnlyGpuSession} : null,
    wheels: {
      source: wheelSource,
      visible: (wheelSource === 'stock' || wheelSource === 'source-verified') ? wheelsVisible : (inspectionWheels?.visible ?? wheelsVisible),
      proxyCount: inspectionWheels?.children.length || 0,
      stockInventories: Object.fromEntries(stockWheelAssetInventories),
    },
    timings: {...timings},
    bytes: resourceBytesForDiagnostics(),
    device: {
      ...graphicsDevice,
      pixelRatio: renderPixelRatio,
      anisotropy: qualityProfile().anisotropy,
    },
    quality: {
      scale: renderContract?.quality_scale || 1,
      source: renderContract?.quality_source || '',
      paintSize: renderContract?.paint_size || [],
      renderQuality,
      aaMode,
      displayPreset,
      materialMode,
      glassMode,
      environmentMode,
      reflectionAngle,
      reflectionStrength,
      groundShadow: {
        requested: groundShadowRequested,
        enabled: groundShadowEnabledForPresentation(),
        mapSize: groundShadowMapSize(),
        type: 'PCFSoftShadowMap',
        receiver: 'ShadowMaterial',
        strength: groundShadowStrength,
      },
      sceneEnvironmentIntensity: scene.environmentIntensity,
      presentationAAEnabled,
      presentationAAFallbackReason,
      presentationAAProfile: presentationAAProfile(),
      sectionCompositeSupersample: Math.max(1, Number(renderContract?.section_composite_supersample) || 1),
      compareMode: effectiveCompareMode(),
      compareSplit,
      differenceGain,
      activeSectionFilter,
      paintBindingCount: Array.isArray(renderContract?.paint_bindings) ? renderContract.paint_bindings.length : 0,
      dprCap: qualityProfile().dprCap,
      pixelBudget: qualityProfile().pixelBudget,
    },
    tracked: {
      geometries: trackedGeometries.size,
      materials: trackedMaterials.size,
      textures: trackedTextures.size,
      skeletons: trackedSkeletons.size,
    },
    renderer: {
      geometries: renderer.info.memory.geometries,
      textures: renderer.info.memory.textures,
      programs: renderer.info.programs?.length || 0,
    },
    rendering: {
      requests: renderRequests,
      frames: renderedFrames,
      cpuFrameMs: frameTime,
      meanCpuFrameMs: renderedFrames ? frameTimeTotal / renderedFrames : 0,
      peakCpuFrameMs: frameTimePeak,
      calls: renderer.info.render.calls,
      triangles: renderer.info.render.triangles,
    },
  };
}

function handleContextLost(event) {
  event.preventDefault();
  if (viewerDisposed) return;
  const detail = 'after_stage=' + latestViewerStage;
  setStatus('WebGL2の描画コンテキストが消失しました。3D表示は未完了です。', true);
  const delivered = reportViewerStage('context_lost', detail);
  try { viewerEvent('context-lost', detail); } catch (_ignored) {}
  let finalized = false;
  const finish = () => { if (!finalized) { finalized = true; disposeViewer(false); } };
  const timeout = window.setTimeout(finish, 900);
  Promise.resolve(delivered).finally(() => { window.clearTimeout(timeout); finish(); });
}

renderer.debug.onShaderError = () => { throw new Error('The graphics device could not compile the livery shader.'); };
canvas.addEventListener('webglcontextlost', handleContextLost);

window.addEventListener('dblclick', resetFromDoubleClick);
window.addEventListener('resize', handleResize);
document.addEventListener('visibilitychange', handleVisibilityChange);
window.addEventListener('pagehide', disposeViewer);
window.addEventListener('beforeunload', disposeViewer);
window.__lo4fh6DisposeViewer = disposeViewer;
window.__lo4fh6ViewerDiagnostics = viewerDiagnostics;
window.__lo4fh6ViewerBooted = true;
window.clearTimeout(window.__lo4fh6ViewerBootTimer);
updateCompareControls();
// 最初の読み込みの前からある資源（床など）は、同じ車の次のペイントへの差し替えでも捨てない。
capturePaintSwapBaseline();
loadPackage();
installGpuLiveryRuntimeCapabilityHandshake();
resize();
requestRender();
