import {createRasterPlacement, GpuRasterDecalPass} from './gpu-raster-logo.js';
/*
 * Livery Organizer for FH6 — independent WebGL2 livery paint research path.
 *
 * r291 deliberately keeps this module separate from the shipping Viewer path.
 * It consumes LO4FH6-owned binary placement/geometry streams and produces a
 * premultiplied-alpha offscreen texture. No external renderer source is copied.
 */

export const VECTOR_MAGIC = 'LO4GPVS1';
export const VECTOR_VERSION = 1;
export const VECTOR_RECORD_BYTES = 40;
export const GEOMETRY_MAGIC = 'LO4GVG1\u0000';
export const GEOMETRY_VERSION = 1;
export const GEOMETRY_ENTRY_BYTES = 24;
export const GEOMETRY_VERTEX_BYTES = 12;

const textDecoder = new TextDecoder('ascii');

// r394: For every 8-bit premultiplied channel and alpha, reuse the exact
// old Math.min(255, Math.round(channel * 255 / alpha)) value. The lookup
// is allocated lazily only when the GPU readback conversion is needed.
let straightChannelLookup = null;
function getStraightChannelLookup() {
  if (straightChannelLookup) return straightChannelLookup;
  const table = new Uint8Array(256 * 256);
  for (let alpha = 1; alpha < 256; alpha += 1) {
    const offset = alpha << 8;
    for (let channel = 0; channel < 256; channel += 1) {
      table[offset + channel] = Math.min(255, Math.round(channel * 255 / alpha));
    }
  }
  straightChannelLookup = table;
  return table;
}

// Exposed for exact regression tests; do not use this for foreign byte formats.
export function straightPremultipliedBottomUpRgba(raw, width, height, useLookup = true) {
  const rowBytes = width * 4;
  const out = new Uint8Array(raw.length);
  const lookup = useLookup ? getStraightChannelLookup() : null;
  for (let y = 0; y < height; y += 1) {
    const sourceRowStart = (height - y - 1) * rowBytes;
    const targetRowStart = y * rowBytes;
    for (let x = 0; x < rowBytes; x += 4) {
      const source = sourceRowStart + x;
      const target = targetRowStart + x;
      const alpha = raw[source + 3];
      out[target + 3] = alpha;
      if (alpha === 0) continue;
      if (lookup) {
        const index = alpha << 8;
        out[target] = lookup[index + raw[source]];
        out[target + 1] = lookup[index + raw[source + 1]];
        out[target + 2] = lookup[index + raw[source + 2]];
      } else {
        out[target] = Math.min(255, Math.round(raw[source] * 255 / alpha));
        out[target + 1] = Math.min(255, Math.round(raw[source + 1] * 255 / alpha));
        out[target + 2] = Math.min(255, Math.round(raw[source + 2] * 255 / alpha));
      }
    }
  }
  return out;
}

function requireRange(view, offset, bytes, label) {
  if (!Number.isInteger(offset) || !Number.isInteger(bytes) || offset < 0 || bytes < 0 || offset + bytes > view.byteLength) {
    throw new Error(`${label} is outside the binary payload`);
  }
}

export function parseLiveryVectorStream(buffer) {
  const view = new DataView(buffer);
  requireRange(view, 0, 24, 'vector stream header');
  const magic = textDecoder.decode(new Uint8Array(buffer, 0, 8));
  const version = view.getUint32(8, true);
  const recordCount = view.getUint32(12, true);
  const sectionCount = view.getUint32(16, true);
  const recordBytes = view.getUint32(20, true);
  if (magic !== VECTOR_MAGIC || version !== VECTOR_VERSION || recordBytes !== VECTOR_RECORD_BYTES) {
    throw new Error('unsupported GPU livery vector stream');
  }
  requireRange(view, 24, recordCount * recordBytes, 'vector records');
  const records = [];
  for (let index = 0; index < recordCount; index += 1) {
    const offset = 24 + index * recordBytes;
    const section = view.getUint8(offset);
    const flags = view.getUint8(offset + 1);
    const shapeWord = view.getUint16(offset + 2, true);
    const rasterId = view.getUint32(offset + 4, true);
    const data = [];
    for (let item = 0; item < 6; item += 1) data.push(view.getFloat32(offset + 8 + item * 4, true));
    const color = [
      view.getUint8(offset + 32), view.getUint8(offset + 33),
      view.getUint8(offset + 34), view.getUint8(offset + 35),
    ];
    records.push({ index, section, flags, shapeWord, rasterId, data, color });
  }
  return { version, sectionCount, records };
}

export function parseLiveryGeometryPack(buffer) {
  const view = new DataView(buffer);
  requireRange(view, 0, 20, 'geometry pack header');
  const magic = textDecoder.decode(new Uint8Array(buffer, 0, 8));
  const version = view.getUint32(8, true);
  const entryCount = view.getUint32(12, true);
  const entryBytes = view.getUint32(16, true);
  if (magic !== GEOMETRY_MAGIC || version !== GEOMETRY_VERSION || entryBytes !== GEOMETRY_ENTRY_BYTES) {
    throw new Error('unsupported GPU livery geometry pack');
  }
  const directoryEnd = 20 + entryCount * entryBytes;
  requireRange(view, 20, entryCount * entryBytes, 'geometry directory');
  const entries = new Map();
  for (let entryIndex = 0; entryIndex < entryCount; entryIndex += 1) {
    const offset = 20 + entryIndex * entryBytes;
    const word = view.getUint16(offset, true);
    const flags = view.getUint16(offset + 2, true);
    const vertexCount = view.getUint32(offset + 4, true);
    const indexCount = view.getUint32(offset + 8, true);
    const vertexOffset = view.getUint32(offset + 12, true);
    const indexOffset = view.getUint32(offset + 16, true);
    if (vertexOffset < directoryEnd || indexOffset < directoryEnd) throw new Error('geometry payload overlaps directory');
    requireRange(view, vertexOffset, vertexCount * GEOMETRY_VERTEX_BYTES, 'geometry vertices');
    requireRange(view, indexOffset, indexCount * 4, 'geometry indices');
    const vertices = [];
    for (let vertexIndex = 0; vertexIndex < vertexCount; vertexIndex += 1) {
      const vertex = vertexOffset + vertexIndex * GEOMETRY_VERTEX_BYTES;
      vertices.push({
        x: view.getFloat32(vertex, true),
        y: view.getFloat32(vertex + 4, true),
        alpha: view.getUint8(vertex + 8),
      });
    }
    const indices = [];
    for (let index = 0; index < indexCount; index += 1) {
      const value = view.getUint32(indexOffset + index * 4, true);
      if (value >= vertexCount) throw new Error('geometry index is outside its vertex array');
      indices.push(value);
    }
    entries.set(word, { word, flags, vertices, indices });
  }
  return { version, entries };
}

// r395: placement rotation is invariant across all vertices of one vinyl.
// Calculate it once per placement; keep the exact floating-point formula and
// operation order used by the original point conversion.
function placementRotation(record) {
  const theta = -record.data[4] * Math.PI / 180.0;
  return {cosine: Math.cos(theta), sine: Math.sin(theta)};
}

function placementWorldPoint(record, localX, localY, rotation = null) {
  const [x, y, sx, sy, authoredRotation, memorySkew] = record.data;
  const skew = -memorySkew;
  const localScaledX = localX * sx + skew * localY * sy;
  const localScaledY = localY * sy;
  const theta = -authoredRotation * Math.PI / 180.0;
  const cosine = rotation ? rotation.cosine : Math.cos(theta);
  const sine = rotation ? rotation.sine : Math.sin(theta);
  const editorX = x + localScaledX * cosine - localScaledY * sine;
  const editorY = -y + localScaledX * sine + localScaledY * cosine;
  return [editorX, -editorY];
}

function appendVertex(target, record, vertex, worldBounds, placementAlpha, rasterOptions) {
  const [minX, minY, maxX, maxY] = worldBounds;
  const [worldX, worldY] = placementWorldPoint(record, vertex.x, vertex.y, rasterOptions?.placementRotation);
  let clipX;
  let clipY;
  const solidRasterMode = rasterOptions?.solidRasterMode || 'continuous';
  const hasVertexAlpha = Boolean(rasterOptions?.hasVertexAlpha);
  const viewportSize = rasterOptions?.viewportSize || null;
  if (!hasVertexAlpha && solidRasterMode !== 'continuous') {
    if (!Array.isArray(viewportSize) || viewportSize.length !== 2) {
      throw new Error('viewportSize is required for Pillow-grid solid raster modes');
    }
    const [width, height] = viewportSize;
    const canvasX = (worldX - minX) * width / (maxX - minX);
    const canvasY = (maxY - worldY) * height / (maxY - minY);
    let snappedX;
    let snappedY;
    let offset;
    if (solidRasterMode === 'pillow-grid-corners' || solidRasterMode === 'pillow-grid-centers') {
      snappedX = Math.trunc(canvasX);
      snappedY = Math.trunc(canvasY);
      offset = solidRasterMode === 'pillow-grid-centers' ? 0.5 : 0.0;
    } else if (solidRasterMode === 'pillow-round-corners' || solidRasterMode === 'pillow-round-centers') {
      snappedX = Math.round(canvasX);
      snappedY = Math.round(canvasY);
      offset = solidRasterMode === 'pillow-round-centers' ? 0.5 : 0.0;
    } else {
      throw new Error('solidRasterMode is invalid');
    }
    const sampleX = snappedX + offset;
    const sampleY = snappedY + offset;
    clipX = (sampleX / width) * 2.0 - 1.0;
    clipY = 1.0 - (sampleY / height) * 2.0;
  } else {
    clipX = ((worldX - minX) / (maxX - minX)) * 2.0 - 1.0;
    clipY = ((worldY - minY) / (maxY - minY)) * 2.0 - 1.0;
  }
  const alpha = placementAlpha * (vertex.alpha / 255.0);
  target.push(
    clipX, clipY,
    record.color[0] / 255.0,
    record.color[1] / 255.0,
    record.color[2] / 255.0,
    alpha,
  );
  return [clipX, clipY];
}

// 配置 1 件の三角形を展開する（既定の経路）。
// 頂点の変換は placementWorldPoint と appendVertex と同じ式・同じ演算の順で書き、配置ごとに決まる値
// （位置・倍率・回転・範囲・色・塗りの方式）だけを先に取り出す。頂点ごとの配列・オブジェクトは作らない。
// 結果は Float32（描画に渡す値）に 1 回だけ丸める（従来の values.set(JS の配列) と同じ）。範囲は丸める前の値で求める。
// Math.min / Math.max は訪れる順に依らないので、範囲は使われる頂点を最初に変換したときに 1 回だけ足す。
// 式を変えるときは appendVertex と一緒に変え、tests/test_gpu_livery_plan_expand.mjs で参照の経路との一致を確かめる。
function expandPlacementTriangles(record, geometry, worldBounds, placementAlpha, rasterOptions) {
  const minX = worldBounds[0];
  const minY = worldBounds[1];
  const maxX = worldBounds[2];
  const maxY = worldBounds[3];
  const data = record.data;
  const x = data[0];
  const y = data[1];
  const sx = data[2];
  const sy = data[3];
  const skew = -data[5];
  const rotation = rasterOptions?.placementRotation || placementRotation(record);
  const cosine = rotation.cosine;
  const sine = rotation.sine;
  const solidRasterMode = rasterOptions?.solidRasterMode || 'continuous';
  const snapping = !rasterOptions?.hasVertexAlpha && solidRasterMode !== 'continuous';
  let width = 0;
  let height = 0;
  let offset = 0.0;
  let rounding = false;
  if (snapping) {
    const viewportSize = rasterOptions?.viewportSize || null;
    if (!Array.isArray(viewportSize) || viewportSize.length !== 2) {
      throw new Error('viewportSize is required for Pillow-grid solid raster modes');
    }
    width = viewportSize[0];
    height = viewportSize[1];
    if (solidRasterMode === 'pillow-grid-corners' || solidRasterMode === 'pillow-grid-centers') {
      offset = solidRasterMode === 'pillow-grid-centers' ? 0.5 : 0.0;
    } else if (solidRasterMode === 'pillow-round-corners' || solidRasterMode === 'pillow-round-centers') {
      rounding = true;
      offset = solidRasterMode === 'pillow-round-centers' ? 0.5 : 0.0;
    } else {
      throw new Error('solidRasterMode is invalid');
    }
  }
  const red = record.color[0] / 255.0;
  const green = record.color[1] / 255.0;
  const blue = record.color[2] / 255.0;
  const sourceVertices = geometry.vertices;
  const indices = geometry.indices;
  const vertexCount = sourceVertices.length;
  const validIndexCount = Math.floor(indices.length / 3) * 3;
  const values = new Float32Array(validIndexCount * 6);
  const transformed = new Float32Array(vertexCount * 6);
  const ready = new Uint8Array(vertexCount);
  let cursor = 0;
  let minClipX = Infinity;
  let minClipY = Infinity;
  let maxClipX = -Infinity;
  let maxClipY = -Infinity;
  let triangles = 0;
  for (let index = 0; index + 2 < indices.length; index += 3) {
    for (let corner = 0; corner < 3; corner += 1) {
      const vertexIndex = indices[index + corner];
      const source = vertexIndex * 6;
      if (ready[vertexIndex] === 0) {
        const vertex = sourceVertices[vertexIndex];
        const localX = vertex.x;
        const localY = vertex.y;
        // placementWorldPoint と同じ式。
        const localScaledX = localX * sx + skew * localY * sy;
        const localScaledY = localY * sy;
        const editorX = x + localScaledX * cosine - localScaledY * sine;
        const editorY = -y + localScaledX * sine + localScaledY * cosine;
        const worldX = editorX;
        const worldY = -editorY;
        // appendVertex と同じ式。
        let clipX;
        let clipY;
        if (snapping) {
          const canvasX = (worldX - minX) * width / (maxX - minX);
          const canvasY = (maxY - worldY) * height / (maxY - minY);
          const snappedX = rounding ? Math.round(canvasX) : Math.trunc(canvasX);
          const snappedY = rounding ? Math.round(canvasY) : Math.trunc(canvasY);
          const sampleX = snappedX + offset;
          const sampleY = snappedY + offset;
          clipX = (sampleX / width) * 2.0 - 1.0;
          clipY = 1.0 - (sampleY / height) * 2.0;
        } else {
          clipX = ((worldX - minX) / (maxX - minX)) * 2.0 - 1.0;
          clipY = ((worldY - minY) / (maxY - minY)) * 2.0 - 1.0;
        }
        transformed[source] = clipX;
        transformed[source + 1] = clipY;
        transformed[source + 2] = red;
        transformed[source + 3] = green;
        transformed[source + 4] = blue;
        transformed[source + 5] = placementAlpha * (vertex.alpha / 255.0);
        minClipX = Math.min(minClipX, clipX);
        minClipY = Math.min(minClipY, clipY);
        maxClipX = Math.max(maxClipX, clipX);
        maxClipY = Math.max(maxClipY, clipY);
        ready[vertexIndex] = 1;
      }
      values[cursor] = transformed[source];
      values[cursor + 1] = transformed[source + 1];
      values[cursor + 2] = transformed[source + 2];
      values[cursor + 3] = transformed[source + 3];
      values[cursor + 4] = transformed[source + 4];
      values[cursor + 5] = transformed[source + 5];
      cursor += 6;
    }
    triangles += 1;
  }
  return {values, triangles, clipBounds: [minClipX, minClipY, maxClipX, maxClipY]};
}

export function buildGpuLiveryDrawPlan(vectorStream, geometryPack, options) {
  const sectionIndex = Number(options?.sectionIndex);
  const worldBounds = Array.from(options?.worldBounds || []);
  const solidRasterMode = String(options?.solidRasterMode || 'continuous');
  const solidMaskRasterMode = String(options?.solidMaskRasterMode || solidRasterMode);
  const solidMaskPlacementAlphaMode = String(options?.solidMaskPlacementAlphaMode || 'binary');
  const viewportSize = Array.from(options?.viewportSize || []);
  if (!Number.isInteger(sectionIndex) || sectionIndex < 0 || sectionIndex >= vectorStream.sectionCount) {
    throw new Error('sectionIndex is invalid');
  }
  if (worldBounds.length !== 4 || worldBounds.some((value) => !Number.isFinite(value)) || worldBounds[2] <= worldBounds[0] || worldBounds[3] <= worldBounds[1]) {
    throw new Error('worldBounds is invalid');
  }
  const validSolidRasterModes = [
    'continuous',
    'pillow-grid-corners',
    'pillow-grid-centers',
    'pillow-round-corners',
    'pillow-round-centers',
  ];
  if (!validSolidRasterModes.includes(solidRasterMode)) {
    throw new Error('solidRasterMode is invalid');
  }
  if (!validSolidRasterModes.includes(solidMaskRasterMode)) {
    throw new Error('solidMaskRasterMode is invalid');
  }
  if (!['binary', 'placement-alpha'].includes(solidMaskPlacementAlphaMode)) {
    throw new Error('solidMaskPlacementAlphaMode is invalid');
  }
  if (solidRasterMode !== 'continuous' || solidMaskRasterMode !== 'continuous') {
    if (viewportSize.length !== 2 || viewportSize.some((value) => !Number.isInteger(value) || value < 1)) {
      throw new Error('viewportSize is invalid for Pillow-grid solid raster modes');
    }
  }
  const batches = [];
  const placements = [];
  let current = null;
  let sourceRecordCount = 0;
  let vectorRecordCount = 0;
  let triangleCount = 0;
  let missingGeometryCount = 0;
  let rasterRecordCount = 0;
  let missingRasterCount = 0;
  const missingShapeWords = new Set();

  for (const record of vectorStream.records) {
    if (record.section !== sectionIndex) continue;
    sourceRecordCount += 1;
    if ((record.flags & 0x02) !== 0) {
      rasterRecordCount += 1;
      const asset = options?.rasterDecals?.entries?.get(record.rasterId);
      if (!asset || !record.rasterId) {
        missingRasterCount += 1;
        continue;
      }
      // 原本Decalsから復号したRGBAを元Shapeの直後にGPU描画。
      // 図形順とMask消去順を保持し、通常モードは上流の研究Gateで拒否する。
      const placement = createRasterPlacement(
        record, worldBounds, asset,
        (x, y) => placementWorldPoint(record, x, y),
      );
      const rasterMode = placement.mode;
      if (current === null || current.mode !== rasterMode) {
        current = {mode: rasterMode, recordCount: 0, triangleCount: 0};
        batches.push(current);
      }
      current.recordCount += 1;
      current.triangleCount += 2;
      placements.push(placement);
      triangleCount += 2;
      continue;
    }
    const geometry = geometryPack.entries.get(record.shapeWord);
    if (!geometry) {
      missingGeometryCount += 1;
      missingShapeWords.add(record.shapeWord);
      continue;
    }
    const mode = (record.flags & 0x01) !== 0 ? 'mask' : 'paint';
    const hasVertexAlpha = (geometry.flags & 0x0002) !== 0;
    // Historical parity diagnostics used binary solid-mask coverage.  The
    // production section renderer, however, scales every mask placement by its
    // authored placement alpha before erase composition.  Keep the legacy
    // binary mode as an explicit research option while allowing production to
    // select the observed section-renderer contract.
    const placementAlpha = mode === 'mask' && !hasVertexAlpha && solidMaskPlacementAlphaMode === 'binary'
      ? 1.0
      : record.color[3] / 255.0;
    // r395: stage the exact Float32 values directly, instead of filling a
    // separate JS double array and copying it after the triangle expansion.
    // Invalid/incomplete trailing triangle indices are ignored as before.
    const useTypedVertexStaging = options?.useTypedVertexStaging !== false;
    const reuseVertexTransforms = options?.reuseVertexTransforms !== false;
    const directClipBounds = options?.directClipBounds !== false;
    const effectiveSolidRasterMode = mode === 'mask' && !hasVertexAlpha ? solidMaskRasterMode : solidRasterMode;
    const rasterOptions = { solidRasterMode: effectiveSolidRasterMode, viewportSize, hasVertexAlpha,
      placementRotation: options?.reusePlacementRotation === false ? null : placementRotation(record) };
    // 既定の組み合わせは型付きの配列で展開する。従来の展開は、一致を確かめる参照として選べるように残す。
    if (useTypedVertexStaging && reuseVertexTransforms && directClipBounds && options?.typedVertexTransformCache !== false) {
      const expanded = expandPlacementTriangles(record, geometry, worldBounds, placementAlpha, rasterOptions);
      triangleCount += expanded.triangles;
      if (current === null || current.mode !== mode) {
        current = { mode, recordCount: 0, triangleCount: 0 };
        batches.push(current);
      }
      current.recordCount += 1;
      current.triangleCount += expanded.triangles;
      placements.push({
        mode,
        recordIndex: record.index,
        shapeWord: record.shapeWord,
        hasVertexAlpha,
        triangleCount: expanded.triangles,
        clipBounds: expanded.clipBounds,
        vertices: expanded.values,
      });
      vectorRecordCount += 1;
      continue;
    }
    const validIndexCount = Math.floor(geometry.indices.length / 3) * 3;
    const values = useTypedVertexStaging ? new Float32Array(validIndexCount * 6) : [];
    let vertexValueCursor = 0;
    // Each triangle index can refer to the same authored vertex repeatedly.
    // Cache its complete transformed payload only within this placement: the
    // raster mode, colour and placement alpha may differ for the next record.
    // The opt-out is retained for reference-parity tests.
    const transformedVertexCache = reuseVertexTransforms ? new Array(geometry.vertices.length) : null;
    const getTransformedVertex = (vertexIndex) => {
      if (transformedVertexCache?.[vertexIndex] !== undefined) return transformedVertexCache[vertexIndex];
      const vertexValues = [];
      const point = appendVertex(vertexValues, record, geometry.vertices[vertexIndex],
        worldBounds, placementAlpha, rasterOptions);
      const cached = {values: vertexValues, point};
      if (transformedVertexCache) transformedVertexCache[vertexIndex] = cached;
      return cached;
    };
    let minClipX = Infinity;
    let minClipY = Infinity;
    let maxClipX = -Infinity;
    let maxClipY = -Infinity;
    let placementTriangles = 0;
    // r408: Avoid allocating a temporary point-array for every triangle.
    // Bounds are updated in exactly the original vertex visitation order.
    // Keep the original path available for byte-for-byte regression checks.
    for (let index = 0; index + 2 < geometry.indices.length; index += 3) {
      const points = directClipBounds ? null : [];
      for (let vertex = 0; vertex < 3; vertex += 1) {
        const transformed = getTransformedVertex(geometry.indices[index + vertex]);
        if (useTypedVertexStaging) {
          values.set(transformed.values, vertexValueCursor);
          vertexValueCursor += 6;
        } else {
          values.push(...transformed.values);
        }
        if (directClipBounds) {
          const [clipX, clipY] = transformed.point;
          minClipX = Math.min(minClipX, clipX);
          minClipY = Math.min(minClipY, clipY);
          maxClipX = Math.max(maxClipX, clipX);
          maxClipY = Math.max(maxClipY, clipY);
        } else {
          points.push(transformed.point);
        }
      }
      if (points) {
        for (const [clipX, clipY] of points) {
          minClipX = Math.min(minClipX, clipX);
          minClipY = Math.min(minClipY, clipY);
          maxClipX = Math.max(maxClipX, clipX);
          maxClipY = Math.max(maxClipY, clipY);
        }
      }
      placementTriangles += 1;
      triangleCount += 1;
    }
    if (current === null || current.mode !== mode) {
      current = { mode, recordCount: 0, triangleCount: 0 };
      batches.push(current);
    }
    current.recordCount += 1;
    current.triangleCount += placementTriangles;
    placements.push({
      mode,
      recordIndex: record.index,
      shapeWord: record.shapeWord,
      hasVertexAlpha,
      triangleCount: placementTriangles,
      clipBounds: [minClipX, minClipY, maxClipX, maxClipY],
      vertices: useTypedVertexStaging ? values : new Float32Array(values),
    });
    vectorRecordCount += 1;
  }
  const strictReady = missingRasterCount === 0 && missingGeometryCount === 0;
  return {
    sectionIndex,
    worldBounds,
    representation: 'premultiplied-alpha',
    coverageResolve: 'per-placement-max-alpha',
    solidRasterMode,
    solidMaskRasterMode,
    solidMaskPlacementAlphaMode,
    sourceRecordCount,
    vectorRecordCount,
    triangleCount,
    rasterRecordCount,
    missingRasterCount,
    missingGeometryCount,
    missingShapeWords: Array.from(missingShapeWords).sort((a, b) => a - b),
    strictReady,
    batches,
    placements,
  };
}

const VERTEX_SHADER = `#version 300 es
layout(location = 0) in vec2 a_position;
layout(location = 1) in vec4 a_color;
out vec4 v_color;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
  v_color = a_color;
}`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;
in vec4 v_color;
out vec4 out_color;
void main() {
  out_color = vec4(v_color.rgb * v_color.a, v_color.a);
}`;

const COMPOSITE_VERTEX_SHADER = `#version 300 es
const vec2 POSITIONS[3] = vec2[3](
  vec2(-1.0, -1.0),
  vec2( 3.0, -1.0),
  vec2(-1.0,  3.0)
);
void main() {
  gl_Position = vec4(POSITIONS[gl_VertexID], 0.0, 1.0);
}`;

const COMPOSITE_FRAGMENT_SHADER = `#version 300 es
precision highp float;
uniform sampler2D u_source;
uniform ivec2 u_source_size;
uniform int u_expand_mode;
out vec4 out_color;

vec4 fetch_clamped(ivec2 point) {
  ivec2 maximum = max(u_source_size - ivec2(1), ivec2(0));
  return texelFetch(u_source, clamp(point, ivec2(0), maximum), 0);
}

void main() {
  ivec2 point = ivec2(gl_FragCoord.xy);
  vec4 center = fetch_clamped(point);
  if (u_expand_mode == 0) {
    out_color = center;
    return;
  }

  float alpha_value = center.a;
  alpha_value = max(alpha_value, fetch_clamped(point + ivec2(-1,  0)).a);
  alpha_value = max(alpha_value, fetch_clamped(point + ivec2( 1,  0)).a);
  alpha_value = max(alpha_value, fetch_clamped(point + ivec2( 0, -1)).a);
  alpha_value = max(alpha_value, fetch_clamped(point + ivec2( 0,  1)).a);
  if (u_expand_mode == 2) {
    alpha_value = max(alpha_value, fetch_clamped(point + ivec2(-1, -1)).a);
    alpha_value = max(alpha_value, fetch_clamped(point + ivec2(-1,  1)).a);
    alpha_value = max(alpha_value, fetch_clamped(point + ivec2( 1, -1)).a);
    alpha_value = max(alpha_value, fetch_clamped(point + ivec2( 1,  1)).a);
  }
  out_color = vec4(0.0, 0.0, 0.0, alpha_value);
}`;

const OWNER_FRAGMENT_SHADER = `#version 300 es
precision highp float;
uniform sampler2D u_source;
uniform ivec2 u_source_size;
uniform vec3 u_owner_rgb;
uniform float u_owner_alpha;
out vec4 out_color;
void main() {
  ivec2 point = ivec2(gl_FragCoord.xy);
  ivec2 maximum = max(u_source_size - ivec2(1), ivec2(0));
  float coverage = texelFetch(u_source, clamp(point, ivec2(0), maximum), 0).a;
  if (coverage <= (1.0 / 255.0)) discard;
  out_color = vec4(u_owner_rgb, u_owner_alpha);
}`;



// r312 diagnostic: accumulate only the destination alpha with an explicitly
// integer-rounded Porter-Duff source-over rule derived independently from the
// canonical Pillow oracle. Hardware blend rounding is intentionally bypassed.
const EXACT_ALPHA_FRAGMENT_SHADER = `#version 300 es
precision highp float;
precision highp int;
uniform sampler2D u_source;
uniform sampler2D u_destination;
uniform ivec2 u_source_size;
uniform int u_expand_mode;
uniform int u_operation;
out vec4 out_color;

vec4 exact_fetch_clamped(sampler2D texture_value, ivec2 point) {
  ivec2 maximum = max(u_source_size - ivec2(1), ivec2(0));
  return texelFetch(texture_value, clamp(point, ivec2(0), maximum), 0);
}

int byte_alpha(vec4 value) {
  return int(floor(value.a * 255.0 + 0.5));
}

int source_alpha_at(ivec2 point) {
  int alpha_value = byte_alpha(exact_fetch_clamped(u_source, point));
  if (u_expand_mode == 0) return alpha_value;
  alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2(-1,  0))));
  alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2( 1,  0))));
  alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2( 0, -1))));
  alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2( 0,  1))));
  if (u_expand_mode == 2) {
    alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2(-1, -1))));
    alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2(-1,  1))));
    alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2( 1, -1))));
    alpha_value = max(alpha_value, byte_alpha(exact_fetch_clamped(u_source, point + ivec2( 1,  1))));
  }
  return alpha_value;
}

void main() {
  ivec2 point = ivec2(gl_FragCoord.xy);
  int source_alpha = source_alpha_at(point);
  int destination_alpha = byte_alpha(exact_fetch_clamped(u_destination, point));
  int result_alpha;
  if (u_operation == 1) {
    // Pillow paste-to-transparent mask erase: round(dst * (1 - src)).
    result_alpha = (destination_alpha * (255 - source_alpha) + 127) / 255;
  } else {
    // Pillow alpha_composite alpha channel: round(src + dst * (1 - src)).
    result_alpha = (source_alpha * 255 + destination_alpha * (255 - source_alpha) + 127) / 255;
  }
  out_color = vec4(0.0, 0.0, 0.0, float(result_alpha) / 255.0);
}`;

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) || 'unknown shader compilation error';
    gl.deleteShader(shader);
    throw new Error(message);
  }
  return shader;
}

function createProgram(gl, vertexSource, fragmentSource) {
  const vertex = compileShader(gl, gl.VERTEX_SHADER, vertexSource);
  const fragment = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const message = gl.getProgramInfoLog(program) || 'unknown program link error';
    gl.deleteProgram(program);
    throw new Error(message);
  }
  return program;
}

function createRgbaTarget(gl, width, height) {
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  const framebuffer = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
    gl.deleteFramebuffer(framebuffer);
    gl.deleteTexture(texture);
    throw new Error('GPU livery framebuffer is incomplete');
  }
  return { texture, framebuffer, width, height };
}

function placementScissor(placement, width, height) {
  const bounds = placement?.clipBounds || [];
  if (bounds.length !== 4 || bounds.some((value) => !Number.isFinite(value))) return null;
  const [minX, minY, maxX, maxY] = bounds;
  const left = Math.max(0, Math.floor((minX * 0.5 + 0.5) * width) - 1);
  const bottom = Math.max(0, Math.floor((minY * 0.5 + 0.5) * height) - 1);
  const right = Math.min(width, Math.ceil((maxX * 0.5 + 0.5) * width) + 1);
  const top = Math.min(height, Math.ceil((maxY * 0.5 + 0.5) * height) + 1);
  if (right <= left || top <= bottom) return null;
  return [left, bottom, right - left, top - bottom];
}

// r392: keep placement order and per-placement scissor/compositing identical,
// but upload one contiguous vertex stream per section instead of reallocating
// the GPU ARRAY_BUFFER thousands of times. Large sections fall back to the
// original per-placement upload path without changing draw semantics.
export const MAX_PACKED_PLACEMENT_BYTES = 64 * 1024 * 1024;

export function packLiveryPlacementVertices(placements, maxBytes = MAX_PACKED_PLACEMENT_BYTES) {
  if (!Array.isArray(placements) || !Number.isSafeInteger(maxBytes) || maxBytes < 0) return null;
  let floatCount = 0;
  const ranges = [];
  for (const placement of placements) {
    const values = placement?.vertices;
    if (!(values instanceof Float32Array) || values.length % 6 !== 0) return null;
    if (values.byteLength > maxBytes - floatCount * 4) return null;
    ranges.push({first: floatCount / 6, count: values.length / 6});
    floatCount += values.length;
  }
  if (!floatCount) return null;
  try {
    const vertices = new Float32Array(floatCount);
    let cursor = 0;
    for (const placement of placements) {
      vertices.set(placement.vertices, cursor);
      cursor += placement.vertices.length;
    }
    return {vertices, ranges};
  } catch (error) {
    // Failure to allocate the bounded staging buffer is not a reason to
    // change the renderer or its GPU/CPU acceptance policy.
    if (error instanceof RangeError) return null;
    throw error;
  }
}

export class GpuLiveryOffscreenRenderer {
  constructor(gl) {
    if (!gl || typeof gl.createFramebuffer !== 'function' || typeof gl.drawArrays !== 'function') {
      throw new Error('a WebGL2 rendering context is required');
    }
    this.gl = gl;
    this.program = createProgram(gl, VERTEX_SHADER, FRAGMENT_SHADER);
    // 通常ViewerではRaster研究Shaderを生成せず、既存WebGL2動作を維持。
    this.rasterPass = null;
    this.compositeProgram = createProgram(gl, COMPOSITE_VERTEX_SHADER, COMPOSITE_FRAGMENT_SHADER);
    this.compositeSource = gl.getUniformLocation(this.compositeProgram, 'u_source');
    this.compositeSourceSize = gl.getUniformLocation(this.compositeProgram, 'u_source_size');
    this.compositeExpandMode = gl.getUniformLocation(this.compositeProgram, 'u_expand_mode');
    this.ownerProgram = createProgram(gl, COMPOSITE_VERTEX_SHADER, OWNER_FRAGMENT_SHADER);
    this.ownerSource = gl.getUniformLocation(this.ownerProgram, 'u_source');
    this.ownerSourceSize = gl.getUniformLocation(this.ownerProgram, 'u_source_size');
    this.ownerRgb = gl.getUniformLocation(this.ownerProgram, 'u_owner_rgb');
    this.ownerAlpha = gl.getUniformLocation(this.ownerProgram, 'u_owner_alpha');
    this.exactAlphaProgram = createProgram(gl, COMPOSITE_VERTEX_SHADER, EXACT_ALPHA_FRAGMENT_SHADER);
    this.exactAlphaSource = gl.getUniformLocation(this.exactAlphaProgram, 'u_source');
    this.exactAlphaDestination = gl.getUniformLocation(this.exactAlphaProgram, 'u_destination');
    this.exactAlphaSourceSize = gl.getUniformLocation(this.exactAlphaProgram, 'u_source_size');
    this.exactAlphaExpandMode = gl.getUniformLocation(this.exactAlphaProgram, 'u_expand_mode');
    this.exactAlphaOperation = gl.getUniformLocation(this.exactAlphaProgram, 'u_operation');
    this.buffer = gl.createBuffer();
    this.vao = gl.createVertexArray();
    this.compositeVao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    const stride = 6 * 4;
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 4, gl.FLOAT, false, stride, 2 * 4);
    gl.bindVertexArray(null);
  }

  render(plan, width, height, options = {}) {
    const gl = this.gl;
    width = Math.max(1, Math.trunc(width));
    height = Math.max(1, Math.trunc(height));
    if (!plan?.strictReady) throw new Error('GPU livery plan has unsupported raster or missing geometry records');
    if (!Array.isArray(plan.placements)) throw new Error('GPU livery plan has no placement coverage commands');
    const solidMaskCoverageMode = String(options?.solidMaskCoverageMode || 'none');
    if (!['none', 'cross-1px', 'box-1px'].includes(solidMaskCoverageMode)) {
      throw new Error('solidMaskCoverageMode is invalid');
    }

    const target = createRgbaTarget(gl, width, height);
    const coverage = createRgbaTarget(gl, width, height);
    const captureOwners = Boolean(options?.captureOwners);
    const owners = captureOwners ? createRgbaTarget(gl, width, height) : null;
    gl.viewport(0, 0, width, height);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.DITHER);
    gl.enable(gl.BLEND);

    gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
    gl.disable(gl.SCISSOR_TEST);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (owners) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, owners.framebuffer);
      gl.disable(gl.SCISSOR_TEST);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }

    const packed = packLiveryPlacementVertices(plan.placements);
    if (packed) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.bufferData(gl.ARRAY_BUFFER, packed.vertices, gl.STREAM_DRAW);
    }
    for (const [placementIndex, placement] of plan.placements.entries()) {
      if (!placement.vertices.length) continue;
      const scissor = placementScissor(placement, width, height);
      if (!scissor) continue;
      gl.enable(gl.SCISSOR_TEST);
      gl.scissor(...scissor);

      // CPU canonical first resolves every triangle belonging to one placement
      // into one coverage layer. MAX reproduces its union / vertex-alpha
      // maximum semantics and prevents repeated alpha accumulation where native
      // triangles overlap.
      gl.bindFramebuffer(gl.FRAMEBUFFER, coverage.framebuffer);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.bindVertexArray(this.vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      if (!packed) gl.bufferData(gl.ARRAY_BUFFER, placement.vertices, gl.STREAM_DRAW);
      gl.blendEquation(gl.MAX);
      gl.blendFunc(gl.ONE, gl.ONE);
      const first = packed ? packed.ranges[placementIndex].first : 0;
      if (placement.rasterId) {
        if (!this.rasterPass) this.rasterPass = new GpuRasterDecalPass(gl);
        this.rasterPass.paint(placement, first, placement.vertices.length / 6);
      } else {
        gl.useProgram(this.program);
        gl.drawArrays(gl.TRIANGLES, first, placement.vertices.length / 6);
      }

      // Composite the resolved placement once, matching Pillow's per-layer
      // alpha_composite / mask erase order in render_typecode_layers_canvas().
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
      gl.useProgram(this.compositeProgram);
      gl.bindVertexArray(this.compositeVao);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, coverage.texture);
      gl.uniform1i(this.compositeSource, 0);
      gl.uniform2i(this.compositeSourceSize, width, height);
      let expandMode = 0;
      if (placement.mode === 'mask' && !placement.hasVertexAlpha) {
        if (solidMaskCoverageMode === 'cross-1px') expandMode = 1;
        if (solidMaskCoverageMode === 'box-1px') expandMode = 2;
      }
      gl.uniform1i(this.compositeExpandMode, expandMode);
      gl.blendEquation(gl.FUNC_ADD);
      if (placement.mode === 'mask') {
        gl.blendFunc(gl.ZERO, gl.ONE_MINUS_SRC_ALPHA);
      } else {
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      }
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      if (owners) {
        const encoded = Math.max(0, Math.trunc(Number(placement.recordIndex || 0)) + 1);
        const red = (encoded & 0xFF) / 255.0;
        const green = ((encoded >>> 8) & 0xFF) / 255.0;
        const blue = ((encoded >>> 16) & 0xFF) / 255.0;
        gl.bindFramebuffer(gl.FRAMEBUFFER, owners.framebuffer);
        gl.disable(gl.BLEND);
        gl.useProgram(this.ownerProgram);
        gl.bindVertexArray(this.compositeVao);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, coverage.texture);
        gl.uniform1i(this.ownerSource, 0);
        gl.uniform2i(this.ownerSourceSize, width, height);
        gl.uniform3f(this.ownerRgb, red, green, blue);
        // r370 diagnostic: preserve the last touching placement id for both paint and mask.
        // Mask records must remain attributable; otherwise most post-mask mismatches become 'unowned'.
        gl.uniform1f(this.ownerAlpha, 1.0);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        gl.enable(gl.BLEND);
      }
    }

    gl.disable(gl.SCISSOR_TEST);
    gl.bindVertexArray(null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.deleteFramebuffer(coverage.framebuffer);
    gl.deleteTexture(coverage.texture);
    return {
      ...target,
      representation: 'premultiplied-alpha',
      coverageResolve: 'per-placement-max-alpha',
      solidMaskCoverageMode,
      ownerTarget: owners,
    };
  }

  renderExactAlpha(plan, width, height, options = {}) {
    const gl = this.gl;
    width = Math.max(1, Math.trunc(width));
    height = Math.max(1, Math.trunc(height));
    if (!plan?.strictReady) throw new Error('GPU livery plan has unsupported raster or missing geometry records');
    if (!Array.isArray(plan.placements)) throw new Error('GPU livery plan has no placement coverage commands');
    const solidMaskCoverageMode = String(options?.solidMaskCoverageMode || 'none');
    if (!['none', 'cross-1px', 'box-1px'].includes(solidMaskCoverageMode)) {
      throw new Error('solidMaskCoverageMode is invalid');
    }

    const coverage = createRgbaTarget(gl, width, height);
    const destination = createRgbaTarget(gl, width, height);
    const scratch = createRgbaTarget(gl, width, height);
    gl.viewport(0, 0, width, height);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.DITHER);
    gl.enable(gl.BLEND);
    for (const target of [destination, scratch]) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
      gl.disable(gl.SCISSOR_TEST);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }

    const packed = packLiveryPlacementVertices(plan.placements);
    if (packed) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.bufferData(gl.ARRAY_BUFFER, packed.vertices, gl.STREAM_DRAW);
    }
    for (const [placementIndex, placement] of plan.placements.entries()) {
      if (!placement.vertices.length) continue;
      const scissor = placementScissor(placement, width, height);
      if (!scissor) continue;
      const [left, bottom, spanWidth, spanHeight] = scissor;
      gl.enable(gl.SCISSOR_TEST);
      gl.scissor(...scissor);

      gl.bindFramebuffer(gl.FRAMEBUFFER, coverage.framebuffer);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.bindVertexArray(this.vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      if (!packed) gl.bufferData(gl.ARRAY_BUFFER, placement.vertices, gl.STREAM_DRAW);
      gl.blendEquation(gl.MAX);
      gl.blendFunc(gl.ONE, gl.ONE);
      const first = packed ? packed.ranges[placementIndex].first : 0;
      if (placement.rasterId) {
        if (!this.rasterPass) this.rasterPass = new GpuRasterDecalPass(gl);
        this.rasterPass.paint(placement, first, placement.vertices.length / 6);
      } else {
        gl.useProgram(this.program);
        gl.drawArrays(gl.TRIANGLES, first, placement.vertices.length / 6);
      }

      let expandMode = 0;
      if (placement.mode === 'mask' && !placement.hasVertexAlpha) {
        if (solidMaskCoverageMode === 'cross-1px') expandMode = 1;
        if (solidMaskCoverageMode === 'box-1px') expandMode = 2;
      }
      gl.bindFramebuffer(gl.FRAMEBUFFER, scratch.framebuffer);
      gl.disable(gl.BLEND);
      gl.useProgram(this.exactAlphaProgram);
      gl.bindVertexArray(this.compositeVao);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, coverage.texture);
      gl.uniform1i(this.exactAlphaSource, 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, destination.texture);
      gl.uniform1i(this.exactAlphaDestination, 1);
      gl.uniform2i(this.exactAlphaSourceSize, width, height);
      gl.uniform1i(this.exactAlphaExpandMode, expandMode);
      gl.uniform1i(this.exactAlphaOperation, placement.mode === 'mask' ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      gl.disable(gl.SCISSOR_TEST);
      gl.bindFramebuffer(gl.READ_FRAMEBUFFER, scratch.framebuffer);
      gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, destination.framebuffer);
      gl.blitFramebuffer(
        left, bottom, left + spanWidth, bottom + spanHeight,
        left, bottom, left + spanWidth, bottom + spanHeight,
        gl.COLOR_BUFFER_BIT, gl.NEAREST,
      );
      gl.enable(gl.BLEND);
    }

    gl.disable(gl.SCISSOR_TEST);
    gl.bindVertexArray(null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.deleteFramebuffer(coverage.framebuffer);
    gl.deleteTexture(coverage.texture);
    gl.deleteFramebuffer(scratch.framebuffer);
    gl.deleteTexture(scratch.texture);
    return {
      ...destination,
      representation: 'exact-alpha-only',
      alphaResolve: 'pillow-integer-round127',
      solidMaskCoverageMode,
    };
  }

  readAlpha(target) {
    const gl = this.gl;
    const { framebuffer, width, height } = target;
    const raw = new Uint8Array(width * height * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, raw);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    const out = new Uint8Array(width * height);
    for (let y = 0; y < height; y += 1) {
      const sourceRow = height - 1 - y;
      for (let x = 0; x < width; x += 1) {
        out[y * width + x] = raw[(sourceRow * width + x) * 4 + 3];
      }
    }
    return out;
  }

  readStraightRgba(target, profile = null) {
    const gl = this.gl;
    const { framebuffer, width, height } = target;
    const raw = new Uint8Array(width * height * 4);
    const readPixelsStart = profile ? performance.now() : 0;
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, raw);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (profile) profile.readPixelsMs += performance.now() - readPixelsStart;
    const pixelConvertStart = profile ? performance.now() : 0;
    const out = straightPremultipliedBottomUpRgba(raw, width, height);
    if (profile) profile.pixelConvertMs += performance.now() - pixelConvertStart;
    return out;
  }

  disposeTarget(target) {
    if (!target) return;
    if (target.framebuffer) this.gl.deleteFramebuffer(target.framebuffer);
    if (target.texture) this.gl.deleteTexture(target.texture);
  }

  dispose() {
    if (this.rasterPass) this.rasterPass.dispose();
    if (this.buffer) this.gl.deleteBuffer(this.buffer);
    if (this.vao) this.gl.deleteVertexArray(this.vao);
    if (this.compositeVao) this.gl.deleteVertexArray(this.compositeVao);
    if (this.program) this.gl.deleteProgram(this.program);
    if (this.compositeProgram) this.gl.deleteProgram(this.compositeProgram);
    if (this.ownerProgram) this.gl.deleteProgram(this.ownerProgram);
    if (this.exactAlphaProgram) this.gl.deleteProgram(this.exactAlphaProgram);
    this.buffer = null;
    this.vao = null;
    this.compositeVao = null;
    this.program = null;
    this.compositeProgram = null;
    this.ownerProgram = null;
    this.exactAlphaProgram = null;
    this.compositeSource = null;
    this.compositeSourceSize = null;
    this.compositeExpandMode = null;
    this.ownerSource = null;
    this.ownerSourceSize = null;
    this.ownerRgb = null;
    this.ownerAlpha = null;
    this.exactAlphaSource = null;
    this.exactAlphaDestination = null;
    this.exactAlphaSourceSize = null;
    this.exactAlphaExpandMode = null;
    this.exactAlphaOperation = null;
  }
}

export function compareAlphaBytes(referenceRgba, candidateAlpha) {
  if (!(referenceRgba instanceof Uint8Array || referenceRgba instanceof Uint8ClampedArray) ||
      !(candidateAlpha instanceof Uint8Array || candidateAlpha instanceof Uint8ClampedArray) ||
      referenceRgba.length % 4 !== 0 || referenceRgba.length / 4 !== candidateAlpha.length) {
    throw new Error('alpha comparison buffers are invalid');
  }
  let mismatchPixels = 0;
  let candidateHigherPixels = 0;
  let candidateLowerPixels = 0;
  let absTotal = 0;
  let maxAbs = 0;
  for (let index = 0; index < candidateAlpha.length; index += 1) {
    const referenceAlpha = referenceRgba[index * 4 + 3];
    const candidate = candidateAlpha[index];
    if (referenceAlpha === candidate) continue;
    mismatchPixels += 1;
    const delta = candidate - referenceAlpha;
    if (delta > 0) candidateHigherPixels += 1;
    else candidateLowerPixels += 1;
    const abs = Math.abs(delta);
    absTotal += abs;
    maxAbs = Math.max(maxAbs, abs);
  }
  return {
    alpha_mismatch_pixels: mismatchPixels,
    alpha_candidate_higher_pixels: candidateHigherPixels,
    alpha_candidate_lower_pixels: candidateLowerPixels,
    alpha_mean_abs: mismatchPixels ? absTotal / mismatchPixels : 0,
    alpha_max_abs: maxAbs,
  };
}

export function compareStraightRgba(reference, candidate, width = null, height = null) {
  if (!(reference instanceof Uint8Array || reference instanceof Uint8ClampedArray) ||
      !(candidate instanceof Uint8Array || candidate instanceof Uint8ClampedArray) ||
      reference.length !== candidate.length || reference.length % 4 !== 0) {
    throw new Error('RGBA buffers must be equal-length byte arrays');
  }
  const pixels = reference.length / 4;
  const hasDimensions = Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0 && width * height === pixels;
  let maxAbs = 0;
  let totalAbs = 0;
  let comparedChannels = 0;
  let rgbComparedChannels = 0;
  let rgbAbsTotal = 0;
  let rgbMaxAbs = 0;
  let rgbLargeMismatchPixels = 0;
  const rgbLargeMismatchAbsThreshold = 64;
  let alphaMismatchPixels = 0;
  let alphaCandidateHigherPixels = 0;
  let alphaCandidateLowerPixels = 0;
  let alphaAbsTotal = 0;
  let visiblePixels = 0;
  let referenceVisiblePixels = 0;
  let candidateVisiblePixels = 0;
  let bothVisiblePixels = 0;
  let referenceOnlyVisiblePixels = 0;
  let candidateOnlyVisiblePixels = 0;
  let alphaBinaryMismatchPixels = 0;
  let alphaIntermediateMismatchPixels = 0;
  let alphaIntermediateAbsTotal = 0;
  let alphaIntermediateMaxAbs = 0;
  let alphaIntermediateBothVisiblePixels = 0;
  let alphaIntermediateVisibilityMismatchPixels = 0;
  let alphaIntermediateAbsLe1Pixels = 0;
  let alphaIntermediateAbsLe2Pixels = 0;
  let alphaIntermediateAbsLe4Pixels = 0;
  let alphaIntermediateAbsLe8Pixels = 0;
  let alphaIntermediateAbsGt8Pixels = 0;
  const referenceOnlyIndices = [];
  const candidateOnlyIndices = [];
  const binaryReferenceOnlyIndices = [];
  const binaryCandidateOnlyIndices = [];
  const alphaIntermediateMismatchIndices = [];

  for (let pixel = 0; pixel < pixels; pixel += 1) {
    const offset = pixel * 4;
    const ra = reference[offset + 3];
    const ca = candidate[offset + 3];
    const referenceVisible = ra > 0;
    const candidateVisible = ca > 0;
    if (referenceVisible) referenceVisiblePixels += 1;
    if (candidateVisible) candidateVisiblePixels += 1;
    if (referenceVisible && candidateVisible) bothVisiblePixels += 1;
    if (referenceVisible && !candidateVisible) {
      referenceOnlyVisiblePixels += 1;
      if (hasDimensions) referenceOnlyIndices.push(pixel);
    }
    if (!referenceVisible && candidateVisible) {
      candidateOnlyVisiblePixels += 1;
      if (hasDimensions) candidateOnlyIndices.push(pixel);
    }
    if (ra !== ca) {
      alphaMismatchPixels += 1;
      alphaAbsTotal += Math.abs(ra - ca);
      if (ca > ra) alphaCandidateHigherPixels += 1;
      if (ca < ra) alphaCandidateLowerPixels += 1;
      if ((ra === 0 && ca === 255) || (ra === 255 && ca === 0)) {
        alphaBinaryMismatchPixels += 1;
        if (hasDimensions) {
          if (ra === 255) binaryReferenceOnlyIndices.push(pixel);
          else binaryCandidateOnlyIndices.push(pixel);
        }
      } else {
        alphaIntermediateMismatchPixels += 1;
        const alphaDelta = Math.abs(ra - ca);
        alphaIntermediateAbsTotal += alphaDelta;
        alphaIntermediateMaxAbs = Math.max(alphaIntermediateMaxAbs, alphaDelta);
        if (ra > 0 && ca > 0) alphaIntermediateBothVisiblePixels += 1;
        else alphaIntermediateVisibilityMismatchPixels += 1;
        if (alphaDelta <= 1) alphaIntermediateAbsLe1Pixels += 1;
        if (alphaDelta <= 2) alphaIntermediateAbsLe2Pixels += 1;
        if (alphaDelta <= 4) alphaIntermediateAbsLe4Pixels += 1;
        if (alphaDelta <= 8) alphaIntermediateAbsLe8Pixels += 1;
        if (alphaDelta > 8) alphaIntermediateAbsGt8Pixels += 1;
        if (hasDimensions) alphaIntermediateMismatchIndices.push(pixel);
      }
    }
    if (referenceVisible || candidateVisible) {
      visiblePixels += 1;
      let pixelRgbMaxAbs = 0;
      for (let channel = 0; channel < 4; channel += 1) {
        const delta = Math.abs(reference[offset + channel] - candidate[offset + channel]);
        maxAbs = Math.max(maxAbs, delta);
        totalAbs += delta;
        comparedChannels += 1;
        if (channel < 3 && referenceVisible && candidateVisible) {
          rgbAbsTotal += delta;
          rgbComparedChannels += 1;
          rgbMaxAbs = Math.max(rgbMaxAbs, delta);
          pixelRgbMaxAbs = Math.max(pixelRgbMaxAbs, delta);
        }
      }
      if (referenceVisible && candidateVisible && pixelRgbMaxAbs >= rgbLargeMismatchAbsThreshold) {
        rgbLargeMismatchPixels += 1;
      }
    }
  }

  function neighborhoodContainsAlpha(buffer, pixel, radius, alpha) {
    if (!hasDimensions) return false;
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    const minX = Math.max(0, x - radius);
    const maxX = Math.min(width - 1, x + radius);
    const minY = Math.max(0, y - radius);
    const maxY = Math.min(height - 1, y + radius);
    for (let py = minY; py <= maxY; py += 1) {
      for (let px = minX; px <= maxX; px += 1) {
        if (px === x && py === y) continue;
        if (buffer[(py * width + px) * 4 + 3] === alpha) return true;
      }
    }
    return false;
  }

  function nearVisible(buffer, pixel, radius) {
    if (!hasDimensions) return false;
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    const minX = Math.max(0, x - radius);
    const maxX = Math.min(width - 1, x + radius);
    const minY = Math.max(0, y - radius);
    const maxY = Math.min(height - 1, y + radius);
    for (let py = minY; py <= maxY; py += 1) {
      for (let px = minX; px <= maxX; px += 1) {
        if (px === x && py === y) continue;
        if (buffer[(py * width + px) * 4 + 3] > 0) return true;
      }
    }
    return false;
  }

  function nearAlphaGradient(buffer, pixel, radius) {
    if (!hasDimensions) return false;
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    const minX = Math.max(0, x - radius);
    const maxX = Math.min(width - 1, x + radius);
    const minY = Math.max(0, y - radius);
    const maxY = Math.min(height - 1, y + radius);
    let minAlpha = 255;
    let maxAlpha = 0;
    for (let py = minY; py <= maxY; py += 1) {
      for (let px = minX; px <= maxX; px += 1) {
        const alpha = buffer[(py * width + px) * 4 + 3];
        minAlpha = Math.min(minAlpha, alpha);
        maxAlpha = Math.max(maxAlpha, alpha);
      }
    }
    return maxAlpha > minAlpha;
  }

  let alphaIntermediateCandidateInReference1Pixels = 0;
  let alphaIntermediateCandidateInReference2Pixels = 0;
  let alphaIntermediateReferenceInCandidate1Pixels = 0;
  let alphaIntermediateReferenceInCandidate2Pixels = 0;
  let alphaIntermediateEdgeExchange1Pixels = 0;
  let alphaIntermediateEdgeExchange2Pixels = 0;
  let alphaIntermediateReferenceGradient1Pixels = 0;
  let alphaIntermediateReferenceGradient2Pixels = 0;
  let alphaIntermediateCandidateGradient1Pixels = 0;
  let alphaIntermediateCandidateGradient2Pixels = 0;
  let alphaIntermediateGradientBoundary1Pixels = 0;
  let alphaIntermediateGradientBoundary2Pixels = 0;
  if (hasDimensions) {
    for (const pixel of alphaIntermediateMismatchIndices) {
      const offset = pixel * 4;
      const referenceAlpha = reference[offset + 3];
      const candidateAlpha = candidate[offset + 3];
      const candidateInReference1 = neighborhoodContainsAlpha(reference, pixel, 1, candidateAlpha);
      const candidateInReference2 = candidateInReference1 || neighborhoodContainsAlpha(reference, pixel, 2, candidateAlpha);
      const referenceInCandidate1 = neighborhoodContainsAlpha(candidate, pixel, 1, referenceAlpha);
      const referenceInCandidate2 = referenceInCandidate1 || neighborhoodContainsAlpha(candidate, pixel, 2, referenceAlpha);
      if (candidateInReference1) alphaIntermediateCandidateInReference1Pixels += 1;
      if (candidateInReference2) alphaIntermediateCandidateInReference2Pixels += 1;
      if (referenceInCandidate1) alphaIntermediateReferenceInCandidate1Pixels += 1;
      if (referenceInCandidate2) alphaIntermediateReferenceInCandidate2Pixels += 1;
      if (candidateInReference1 && referenceInCandidate1) alphaIntermediateEdgeExchange1Pixels += 1;
      if (candidateInReference2 && referenceInCandidate2) alphaIntermediateEdgeExchange2Pixels += 1;
      const referenceGradient1 = nearAlphaGradient(reference, pixel, 1);
      const referenceGradient2 = referenceGradient1 || nearAlphaGradient(reference, pixel, 2);
      const candidateGradient1 = nearAlphaGradient(candidate, pixel, 1);
      const candidateGradient2 = candidateGradient1 || nearAlphaGradient(candidate, pixel, 2);
      if (referenceGradient1) alphaIntermediateReferenceGradient1Pixels += 1;
      if (referenceGradient2) alphaIntermediateReferenceGradient2Pixels += 1;
      if (candidateGradient1) alphaIntermediateCandidateGradient1Pixels += 1;
      if (candidateGradient2) alphaIntermediateCandidateGradient2Pixels += 1;
      if (referenceGradient1 || candidateGradient1) alphaIntermediateGradientBoundary1Pixels += 1;
      if (referenceGradient2 || candidateGradient2) alphaIntermediateGradientBoundary2Pixels += 1;
    }
  }

  let referenceOnlyBoundary1Pixels = 0;
  let candidateOnlyBoundary1Pixels = 0;
  let referenceOnlyBoundary2Pixels = 0;
  let candidateOnlyBoundary2Pixels = 0;
  if (hasDimensions) {
    for (const pixel of binaryReferenceOnlyIndices) {
      if (nearVisible(candidate, pixel, 1)) referenceOnlyBoundary1Pixels += 1;
      if (nearVisible(candidate, pixel, 2)) referenceOnlyBoundary2Pixels += 1;
    }
    for (const pixel of binaryCandidateOnlyIndices) {
      if (nearVisible(reference, pixel, 1)) candidateOnlyBoundary1Pixels += 1;
      if (nearVisible(reference, pixel, 2)) candidateOnlyBoundary2Pixels += 1;
    }
  }

  return {
    pixels,
    visiblePixels,
    referenceVisiblePixels,
    candidateVisiblePixels,
    bothVisiblePixels,
    referenceOnlyVisiblePixels,
    candidateOnlyVisiblePixels,
    alphaMismatchPixels,
    alphaCandidateHigherPixels,
    alphaCandidateLowerPixels,
    alphaBinaryMismatchPixels,
    alphaIntermediateMismatchPixels,
    alphaIntermediateMeanAbs: alphaIntermediateMismatchPixels ? alphaIntermediateAbsTotal / alphaIntermediateMismatchPixels : 0,
    alphaIntermediateMaxAbs,
    alphaIntermediateBothVisiblePixels,
    alphaIntermediateVisibilityMismatchPixels,
    alphaIntermediateAbsLe1Pixels,
    alphaIntermediateAbsLe2Pixels,
    alphaIntermediateAbsLe4Pixels,
    alphaIntermediateAbsLe8Pixels,
    alphaIntermediateAbsGt8Pixels,
    alphaIntermediateCandidateInReference1Pixels,
    alphaIntermediateCandidateInReference2Pixels,
    alphaIntermediateReferenceInCandidate1Pixels,
    alphaIntermediateReferenceInCandidate2Pixels,
    alphaIntermediateEdgeExchange1Pixels,
    alphaIntermediateEdgeExchange2Pixels,
    alphaIntermediateEdgeExchange1Ratio: alphaIntermediateMismatchPixels ? alphaIntermediateEdgeExchange1Pixels / alphaIntermediateMismatchPixels : 1,
    alphaIntermediateEdgeExchange2Ratio: alphaIntermediateMismatchPixels ? alphaIntermediateEdgeExchange2Pixels / alphaIntermediateMismatchPixels : 1,
    alphaIntermediateInteriorGt1Pixels: Math.max(0, alphaIntermediateMismatchPixels - alphaIntermediateEdgeExchange1Pixels),
    alphaIntermediateInteriorGt2Pixels: Math.max(0, alphaIntermediateMismatchPixels - alphaIntermediateEdgeExchange2Pixels),
    alphaIntermediateInteriorGt2CanvasRatio: pixels ? Math.max(0, alphaIntermediateMismatchPixels - alphaIntermediateEdgeExchange2Pixels) / pixels : 0,
    alphaIntermediateReferenceGradient1Pixels,
    alphaIntermediateReferenceGradient2Pixels,
    alphaIntermediateCandidateGradient1Pixels,
    alphaIntermediateCandidateGradient2Pixels,
    alphaIntermediateGradientBoundary1Pixels,
    alphaIntermediateGradientBoundary2Pixels,
    alphaIntermediateGradientBoundary1Ratio: alphaIntermediateMismatchPixels ? alphaIntermediateGradientBoundary1Pixels / alphaIntermediateMismatchPixels : 1,
    alphaIntermediateGradientBoundary2Ratio: alphaIntermediateMismatchPixels ? alphaIntermediateGradientBoundary2Pixels / alphaIntermediateMismatchPixels : 1,
    alphaIntermediateGradientInteriorGt1Pixels: Math.max(0, alphaIntermediateMismatchPixels - alphaIntermediateGradientBoundary1Pixels),
    alphaIntermediateGradientInteriorGt2Pixels: Math.max(0, alphaIntermediateMismatchPixels - alphaIntermediateGradientBoundary2Pixels),
    alphaIntermediateGradientInteriorGt2CanvasRatio: pixels ? Math.max(0, alphaIntermediateMismatchPixels - alphaIntermediateGradientBoundary2Pixels) / pixels : 0,
    alphaBinaryMismatchCanvasRatio: pixels ? alphaBinaryMismatchPixels / pixels : 0,
    alphaMismatchMeanAbs: alphaMismatchPixels ? alphaAbsTotal / alphaMismatchPixels : 0,
    referenceOnlyBoundary1Pixels,
    candidateOnlyBoundary1Pixels,
    referenceOnlyBoundary2Pixels,
    candidateOnlyBoundary2Pixels,
    binaryBoundary1Pixels: referenceOnlyBoundary1Pixels + candidateOnlyBoundary1Pixels,
    binaryBoundary2Pixels: referenceOnlyBoundary2Pixels + candidateOnlyBoundary2Pixels,
    referenceOnlyInteriorGt1Pixels: Math.max(0, binaryReferenceOnlyIndices.length - referenceOnlyBoundary1Pixels),
    candidateOnlyInteriorGt1Pixels: Math.max(0, binaryCandidateOnlyIndices.length - candidateOnlyBoundary1Pixels),
    referenceOnlyInteriorGt2Pixels: Math.max(0, binaryReferenceOnlyIndices.length - referenceOnlyBoundary2Pixels),
    candidateOnlyInteriorGt2Pixels: Math.max(0, binaryCandidateOnlyIndices.length - candidateOnlyBoundary2Pixels),
    binaryInteriorGt1Pixels: Math.max(0, alphaBinaryMismatchPixels - (referenceOnlyBoundary1Pixels + candidateOnlyBoundary1Pixels)),
    binaryInteriorGt2Pixels: Math.max(0, alphaBinaryMismatchPixels - (referenceOnlyBoundary2Pixels + candidateOnlyBoundary2Pixels)),
    binaryBoundary1Ratio: alphaBinaryMismatchPixels ? (referenceOnlyBoundary1Pixels + candidateOnlyBoundary1Pixels) / alphaBinaryMismatchPixels : 1,
    binaryBoundary2Ratio: alphaBinaryMismatchPixels ? (referenceOnlyBoundary2Pixels + candidateOnlyBoundary2Pixels) / alphaBinaryMismatchPixels : 1,
    maxAbs,
    meanAbs: comparedChannels ? totalAbs / comparedChannels : 0,
    rgbMeanAbs: rgbComparedChannels ? rgbAbsTotal / rgbComparedChannels : 0,
    rgbMaxAbs,
    rgbLargeMismatchAbsThreshold,
    rgbLargeMismatchPixels,
    rgbLargeMismatchVisibleRatio: bothVisiblePixels ? rgbLargeMismatchPixels / bothVisiblePixels : 0,
  };
}
