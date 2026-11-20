import {parseRasterDecalPack} from './gpu-raster-logo.js';
import {
  GpuLiveryOffscreenRenderer,
  buildGpuLiveryDrawPlan,
  parseLiveryGeometryPack,
  parseLiveryVectorStream,
} from './gpu-livery-renderer.js';
import {GpuOnlyDirectAtlas} from './gpu-only-direct-atlas.js';
import {GpuPaintUnavailableError, requireGpuPaintRuntime, assertGpuAtlasComplete} from './gpu-paint-runtime-gate.js';

const RUNTIME_FORMAT = 'lo4fh6_gpu_livery_production_runtime_v1';

async function fetchJson(path) {
  const response = await fetch(path, {cache: 'no-store'});
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

async function fetchBytes(path) {
  const response = await fetch(path, {cache: 'no-store'});
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.arrayBuffer();
}

function createCanvas(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.trunc(width));
  canvas.height = Math.max(1, Math.trunc(height));
  return canvas;
}

function sectionPixels(section, paintSize) {
  const region = Array.from(section?.paint_region || []).map(Number);
  if (region.length !== 4 || region.some(value => !Number.isFinite(value))) {
    throw new Error(`GPU livery paint region is invalid for ${section?.section || '?'}`);
  }
  const left = Math.round(region[0] * paintSize[0]);
  const top = Math.round(region[1] * paintSize[1]);
  const right = Math.round(region[2] * paintSize[0]);
  const bottom = Math.round(region[3] * paintSize[1]);
  if (right <= left || bottom <= top) throw new Error('GPU livery paint region has no area');
  return {left, top, width: right - left, height: bottom - top};
}

// r427：描画計画から任意の概略空間統計を作る。
// 画素座標・原本の色・画像・作者ID・Liveryメタデータを外へ出さない。
// 4×4区画は面相対であり、通常モードの合成処理は変更しない。
export function buildSourceCoverageDiagnostic(plan, runtimeManifest, sectionName, meta = {}) {
  const profile = runtimeManifest?.canonical_section_profiles?.[sectionName] || {};
  const categoryCounts = {
    paint_solid: 0,
    paint_vertex_alpha: 0,
    mask_solid: 0,
    mask_vertex_alpha: 0,
  };
  let fullyInside = 0;
  let partiallyClipped = 0;
  let fullyOutside = 0;
  for (const placement of plan?.placements || []) {
    const key = `${placement.mode === 'mask' ? 'mask' : 'paint'}_${placement.hasVertexAlpha ? 'vertex_alpha' : 'solid'}`;
    if (Object.prototype.hasOwnProperty.call(categoryCounts, key)) categoryCounts[key] += 1;
    const bounds = Array.from(placement?.clipBounds || []).map(Number);
    if (bounds.length !== 4 || bounds.some(value => !Number.isFinite(value))) continue;
    const [minX, minY, maxX, maxY] = bounds;
    if (maxX < -1 || minX > 1 || maxY < -1 || minY > 1) fullyOutside += 1;
    else if (minX >= -1 && maxX <= 1 && minY >= -1 && maxY <= 1) fullyInside += 1;
    else partiallyClipped += 1;
  }
  const expectedStream = Number(profile.stream_record_count ?? runtimeManifest?.section_counts?.[sectionName] ?? 0);
  return {
    canonical_shape_count: Number(profile.canonical_shape_count || 0),
    valid_affine_shape_count: Number(profile.valid_affine_shape_count || 0),
    manifest_stream_record_count: expectedStream,
    dropped_before_stream_count: Number(profile.dropped_before_stream_count || 0),
    canonical_paint_shape_count: Number(profile.paint_shape_count || 0),
    canonical_mask_shape_count: Number(profile.mask_shape_count || 0),
    canonical_raster_shape_count: Number(profile.raster_shape_count || 0),
    canonical_opaque_color_shape_count: Number(profile.opaque_color_shape_count || 0),
    canonical_semitransparent_color_shape_count: Number(profile.semitransparent_color_shape_count || 0),
    canonical_transparent_color_shape_count: Number(profile.transparent_color_shape_count || 0),
    draw_plan_source_record_count: Number(plan?.sourceRecordCount || 0),
    draw_plan_vector_record_count: Number(plan?.vectorRecordCount || 0),
    record_count_delta: Number(plan?.sourceRecordCount || 0) - expectedStream,
    placement_count: Number(plan?.placements?.length || 0),
    triangle_count: Number(plan?.triangleCount || 0),
    raster_record_count: Number(plan?.rasterRecordCount || 0),
    missing_geometry_count: Number(plan?.missingGeometryCount || 0),
    paint_solid_placement_count: categoryCounts.paint_solid,
    paint_vertex_alpha_placement_count: categoryCounts.paint_vertex_alpha,
    mask_solid_placement_count: categoryCounts.mask_solid,
    mask_vertex_alpha_placement_count: categoryCounts.mask_vertex_alpha,
    fully_inside_viewport_placement_count: fullyInside,
    partially_clipped_viewport_placement_count: partiallyClipped,
    fully_outside_viewport_placement_count: fullyOutside,
    source_size: Array.from(meta?.source_size || []).map(Number),
    tile_size: Array.from(meta?.tile_size || []).map(Number),
    world_bounds: Array.from(meta?.world_bounds || []).map(Number),
  };
}

function sectionReport(sectionName, width, height, sourceCoverage = null) {
  const report = {
    section: sectionName,
    tile_width: width,
    tile_height: height,
    tile_pixels: Math.max(1, width * height),
    accepted: true,
    acceptance_mode: 'webgl2-gpu-only-fbo',
  };
  if (sourceCoverage) report.source_coverage_diagnostic = sourceCoverage;
  return report;
}

export function resolveSectionIndex(runtimeManifest, sectionName) {
  const contractValue = runtimeManifest?.contract_section_index?.[sectionName];
  const legacyValue = runtimeManifest?.section_index?.[sectionName];
  const value = contractValue ?? legacyValue;
  const sectionIndex = Number(value);
  if (!Number.isInteger(sectionIndex) || sectionIndex < 0) {
    throw new Error(`GPU livery section index is unavailable for ${sectionName || '?'}`);
  }
  return sectionIndex;
}

export function resolveProductionRenderSize(sourceSize, adapter = {}) {
  const supersample = Math.max(1, Math.trunc(Number(adapter.section_composite_supersample || 1)));
  return {
    supersample,
    width: Math.max(1, Math.trunc(Number(sourceSize?.[0] || 0))) * supersample,
    height: Math.max(1, Math.trunc(Number(sourceSize?.[1] || 0))) * supersample,
  };
}

// 原本canonical → GPUストリーム → WebGL2描画計画で、図形を1件も欠落させない。
// 診断JSONで差分を報告するだけではなく、製品描画を開始する前に停止する。
export function requireGpuSourceSectionComplete(plan, runtimeManifest, sectionName) {
  const profile = runtimeManifest?.canonical_section_profiles?.[sectionName];
  if (!profile || !Array.isArray(plan?.placements)) {
    throw new GpuPaintUnavailableError('原本GPU図形完全性: 製品11面の署名済み計数がありません: ' + sectionName);
  }
  const counts = [
    profile.canonical_shape_count,
    profile.valid_affine_shape_count,
    profile.stream_record_count,
    profile.dropped_before_stream_count,
    plan.sourceRecordCount,
    plan.vectorRecordCount,
    plan.rasterRecordCount,
    plan.placements.length,
  ];
  if (!counts.every(n => Number.isSafeInteger(n) && n >= 0)) {
    throw new GpuPaintUnavailableError('原本GPU図形完全性: 面の件数が不正です: ' + sectionName);
  }
  const [canonical, validAffine, stream, dropped, source, vector, raster, placements] = counts;
  if (canonical !== validAffine || dropped !== 0 || stream !== canonical
      || source !== canonical || vector + raster !== canonical
      || placements !== canonical
      || plan.missingGeometryCount !== 0 || plan.missingRasterCount !== 0) {
    throw new GpuPaintUnavailableError('原本GPU図形完全性: 欠落を検出しました: ' + sectionName);
  }
  return {sourceRecordCount: canonical, gpuPlacementCount: placements};
}

function renderGpuTile(renderer, vectorStream, geometryPack, rasterDecals, section, runtimeManifest, directAtlas, box) {
  if (!directAtlas) throw new GpuPaintUnavailableError('direct GPU atlas missing');
  const meta = section?.gpu_paint_adapter || {};
  if (meta.format !== 'lo4fh6_gpu_paint_adapter_section_v1') {
    throw new GpuPaintUnavailableError('GPU section metadata missing: ' + String(section?.section || '?'));
  }
  const sourceSize = Array.from(meta.source_size || []).map(Number);
  const tileSize = Array.from(meta.tile_size || []).map(Number);
  const worldBounds = Array.from(meta.world_bounds || []).map(Number);
  for (const [label, size] of [['source', sourceSize], ['tile', tileSize]]) {
    if (size.length !== 2 || size.some(value => !Number.isSafeInteger(value) || value < 1)) {
      throw new GpuPaintUnavailableError('GPU livery ' + label + ' size invalid');
    }
  }
  const sectionIndex = resolveSectionIndex(runtimeManifest, section.section);
  const adapter = runtimeManifest.adapter || {};
  const renderSize = resolveProductionRenderSize(sourceSize, adapter);
  const planStart = performance.now();
  const plan = buildGpuLiveryDrawPlan(vectorStream, geometryPack, {
    sectionIndex,
    worldBounds,
    solidRasterMode: String(adapter.solid_raster_mode || 'pillow-grid-centers'),
    solidMaskRasterMode: String(adapter.solid_mask_raster_mode || 'pillow-grid-centers'),
    solidMaskPlacementAlphaMode: String(adapter.solid_mask_placement_alpha_mode || 'binary'),
    viewportSize: [renderSize.width, renderSize.height],
    rasterDecals,
  });
  if (!plan.strictReady) {
    throw new GpuPaintUnavailableError(`section ${section.section} incomplete: missing=${plan.missingGeometryCount} raster=${plan.rasterRecordCount}`);
  }
  requireGpuSourceSectionComplete(plan, runtimeManifest, String(section.section || ''));
  const sourceCoverage = buildSourceCoverageDiagnostic(plan, runtimeManifest, String(section.section || ''), meta);
  const planBuildMs = performance.now() - planStart;
  const webglStart = performance.now();
  const target = renderer.render(plan, renderSize.width, renderSize.height, {captureOwners: false});
  const webglRenderMs = performance.now() - webglStart;
  const composeStart = performance.now();
  try {
    directAtlas.compose(target, meta, box, Number(meta.padding_pixels || 0));
    return {sourceCoverage, profile: {
      planBuildMs, webglRenderMs, composeMs: performance.now() - composeStart,
      readbackResolveMs: 0, readPixelsMs: 0, pixelConvertMs: 0, canvasResolveMs: 0,
    }};
  } finally {
    if (target.ownerTarget) renderer.disposeTarget(target.ownerTarget);
    renderer.disposeTarget(target);
  }
}

export async function buildProductionGpuPaintAtlas(renderContract, options = {}) {
  // 実行素材の取得前にGPU専用契約を検査し、CPUペイントAtlasへの代替を拒否する。
  if (renderContract?.cpu_shadow_policy !== 'gpu-only'
      || renderContract?.paint_rasterizer !== 'webgl2-only'
      || renderContract?.files?.paint) {
    throw new GpuPaintUnavailableError('only signed WebGL2 livery paint contracts are accepted');
  }
  const paintSize = Array.from(renderContract.paint_size || []).map(Number);
  if (paintSize.length !== 2 || paintSize.some(n => !Number.isSafeInteger(n) || n < 1)) {
    throw new GpuPaintUnavailableError('paint dimensions invalid');
  }
  const sections = renderContract.sections;
  if (!Array.isArray(sections) || sections.length < 1 || new Set(sections.map(s => s.section)).size !== sections.length) {
    throw new GpuPaintUnavailableError('paint section contract empty or duplicated');
  }
  const glCanvas = createCanvas(paintSize[0], paintSize[1]);
  const gl = glCanvas.getContext('webgl2', {
    alpha: true, antialias: false, depth: false, stencil: false,
    premultipliedAlpha: true, preserveDrawingBuffer: true,
  });
  requireGpuPaintRuntime(renderContract, gl);
  let manifest, vectorBuffer, geometryBuffer;
  try {
    [manifest, vectorBuffer, geometryBuffer] = await Promise.all([
      fetchJson('./api/gpu-livery-runtime/manifest'),
      fetchBytes('./api/gpu-livery-runtime/vector-stream'),
      fetchBytes('./api/gpu-livery-runtime/geometry-pack'),
    ]);
  } catch (error) {
    throw new GpuPaintUnavailableError('runtime input failed: ' + String(error?.message || error));
  }
  if (manifest?.format !== RUNTIME_FORMAT) throw new GpuPaintUnavailableError('GPU runtime format invalid');
  const vectorStream = parseLiveryVectorStream(vectorBuffer);
  const geometryPack = parseLiveryGeometryPack(geometryBuffer);
  const rasterCount = Number(manifest?.raster_decals?.count || 0);
  // 原本Decals.zipから確定IDだけを抽出したセッション限定packを通常GPUへ接続。
  // 研究URLフラグで描画可否を切替えず、出典・件数不足は原本画像欠損として明示停止。
  if (!Number.isSafeInteger(rasterCount) || rasterCount < 0
      || (rasterCount > 0 && (manifest.raster_decals?.source_verified !== true
          || !/^[0-9a-f]{64}$/.test(manifest.raster_decals?.source_archive_sha256 || '')
          || manifest.raster_decals?.research_only === true))) {
    throw new GpuPaintUnavailableError('Raster Logo原本の署名済みGPU入力契約が不足しています');
  }
  const rasterDecals = rasterCount
    ? parseRasterDecalPack(await fetchBytes('./api/gpu-livery-runtime/raster-decal-pack'))
    : {entries: new Map()};
  if (rasterDecals.entries.size !== rasterCount) {
    throw new GpuPaintUnavailableError('FH6原本Raster Logo入力が不足しています');
  }
  let renderer = null, directAtlas = null;
  const reports = [];
  const profile = {tileRenderMs:0, composeMs:0, planBuildMs:0, webglRenderMs:0};
  try {
    renderer = new GpuLiveryOffscreenRenderer(gl);
    directAtlas = new GpuOnlyDirectAtlas(gl, glCanvas, ...paintSize, {
      experimentalBoxResolve: options?.gpuBoxResolve === true,
      // PRIVATE比較だけ：任意件数の消去矩形を32件単位のGPU passへ展開。
      experimentalChunkedClearRects: options?.gpuChunkedClearRects === true,
    });
    for (const section of sections) {
      if (typeof gl.isContextLost === 'function' && gl.isContextLost()) {
        throw new GpuPaintUnavailableError('WebGL2 context lost during paint');
      }
      const box = sectionPixels(section, paintSize);
      const started = performance.now();
      const rendered = renderGpuTile(renderer, vectorStream, geometryPack, rasterDecals, section, manifest, directAtlas, box);
      profile.tileRenderMs += performance.now() - started;
      for (const field of ['planBuildMs','webglRenderMs','composeMs']) profile[field] += rendered.profile[field];
      const name = String(section.section || '');
      const coverage = name === 'Left' || name === 'Right' ? rendered.sourceCoverage : null;
      const report = sectionReport(name, box.width, box.height, coverage);
      reports.push(report);
    }
    assertGpuAtlasComplete(directAtlas, sections.length);
    directAtlas.finish(sections.length);
    // ゲームに無いステッカーは、準備の段階で透明にして省いてある（目録の raster_decals.omitted）。画面で知らせる。
    const rasterOmissions = Array.isArray(manifest.raster_decals?.omitted)
      ? manifest.raster_decals.omitted.filter(item => Number.isSafeInteger(Number(item?.raster_id)))
      : [];
    return {usedGpu:true, reason:'gpu-atlas-strict-gpu-only', sections:reports,
      acceptedSections:reports.map(r => r.section), rejectedSections:[],
      gpuSectionCount:reports.length, atlasCanvas:glCanvas, profile,
      rasterOmissions, rasterOmittedLayerCount: Number(manifest.raster_decals?.omitted_layer_count || 0)};
  } catch (error) {
    if (error instanceof GpuPaintUnavailableError) throw error;
    throw new GpuPaintUnavailableError('GPU raster or atlas failure: ' + String(error?.message || error));
  } finally {
    if (renderer) renderer.dispose();
    if (directAtlas) directAtlas.dispose();
  }
}
