/**
 * GLTFLoaderの実シーンへ配信済み原本Wheelのテクスチャ材質を接続する。
 * parser.associations の mesh/primitive ID とJSONの署名を突き合わせるため、
 * WebView2でextrasがMaterial/meshへコピーされない場合も原本材質を失わない。
 * 原本mapを実際にロードできなければ修復せず、具体的な失敗数を返す。
 * 推測色・新しいShader・車種/ホイール固有の分岐は一切追加しない。
 */
import {sourceWheelUvAttributeName, sourceWheelTextureChannel} from './source-wheel-uv-channel.mjs';

const ORIGIN = 'fh6-local-original-modelbin-materialbin-shaderbin-texture2d-v1';
const isIndex = (n, list) => Number.isSafeInteger(n) && n >= 0 && n < list.length;
const hasMap = material => material?.map?.isTexture === true;
// 新旧GLBの双方を許可する。ただし矛盾した二重宣言は正常材質として扱わない。
function wheelPartType(extras) {
  const current = extras?.lo4fh6_part_type;
  const legacy = extras?.lo4_part_type;
  if (current !== undefined && legacy !== undefined && current !== legacy) return null;
  return current ?? legacy;
}

/**
 * 第一者GLBで保存済みのWheelStyle出典を、既存Rendererが読む互換名へ戻す。
 * 同一Mesh/PrimitiveとGLB Material-IDの署名が一致する場合だけ復旧し、
 * 新旧名や材質IDの不一致では、推測ルートを作らず対象を拒否する。
 */
function signedWheelRoutingAliases(meshDef, primitiveDef, materialDef, loadedData) {
  const meshExtras=meshDef?.extras || {};
  const primitiveExtras=primitiveDef?.extras || {};
  const fields=['source_entry','wheel_material_id','wheel_material_name',
    'wheel_morph_axle','wheel_morph_wheel','wheel_source_modelbin_sha256',
    'wheel_render_pass_bucket_flags',
    'stock_part','part_option_ids'];
  const aliases={};
  for(const field of fields) {
    const currentKey='lo4fh6_'+field;
    const legacyKey='lo4_'+field;
    const meshValue=meshExtras[currentKey];
    const primitiveValue=primitiveExtras[currentKey];
    // PrimitiveとMeshが重複保持する車輪IDは一致が必須。
    if (meshValue !== undefined && primitiveValue !== undefined
        && JSON.stringify(meshValue) !== JSON.stringify(primitiveValue)) return null;
    // Mesh/Primitive/Loaderの旧名も全件照合。?? ではnullや複数宣言の矛盾を見落とす。
    const legacyValues=[meshExtras[legacyKey],primitiveExtras[legacyKey],
      loadedData?.[legacyKey]].filter(v=>v !== undefined);
    // 旧GLBはlo4_*だけを持つ。署名付きGLB内の値が一意なら復元可能。
    // current/legacy両者がある場合の不一致拒否は下の検査を維持する。
    const value=primitiveValue !== undefined ? primitiveValue
      : meshValue !== undefined ? meshValue
      : legacyValues[0];
    if (value !== undefined && legacyValues.some(v=>
        JSON.stringify(value) !== JSON.stringify(v))) return null;
    if (legacyValues.length>1 && legacyValues.some(v=>
        JSON.stringify(v) !== JSON.stringify(legacyValues[0]))) return null;
    if (value !== undefined) aliases[legacyKey]=value;
  }
  const source=aliases.lo4_source_entry;
  if (source !== undefined && (typeof source !== 'string'
      || !source.toLowerCase().replace(/\\/g,'/').includes('/wheels/')
      || !source.toLowerCase().endsWith('.modelbin'))) return null;
  const id=aliases.lo4_wheel_material_id;
  if (id !== undefined && (!Number.isSafeInteger(id) || id < 0
      || (materialDef?.extras?.modelbin_material_id !== undefined
          && materialDef.extras.modelbin_material_id !== id))) return null;
  const modelSha=aliases.lo4_wheel_source_modelbin_sha256;
  if (modelSha !== undefined && (typeof modelSha !== 'string'
      || !/^[0-9a-f]{64}$/i.test(modelSha)
      || (materialDef?.extras?.source_modelbin_sha256 !== undefined
          && materialDef.extras.source_modelbin_sha256 !== modelSha))) return null;
  const name=aliases.lo4_wheel_material_name;
  if (name !== undefined && (typeof name !== 'string' || !name)) return null;
  const axle=aliases.lo4_wheel_morph_axle;
  if (axle !== undefined && axle !== 'front' && axle !== 'rear') return null;
  return aliases;
}


/**
 * Three.js r185 GLTFLoader実装に合わせて、Mesh/Primitiveを所有するglTF nodeを照合。
 * 単一PrimitiveはMesh自身のassociation.nodes、複数Primitiveは
 * 親Groupのassociation.nodesに置かれる。親を遡っても原本node.meshが
 * 合わなければ採用しない。node数や車輪数の固定制約は設けない。
 */
function owningWheelNodeAssociation(child, directAssociation, parser) {
  let current=child;
  const seen=new Set();
  while (current && !seen.has(current)) {
    seen.add(current);
    const mapped=current===child ? directAssociation : parser.associations.get(current);
    if (mapped?.nodes !== undefined) return mapped;
    current=current.parent;
  }
  return null;
}

/** 原本署名済Wheelは塗装・ガラスの名前ベース分類よりも優先して保持する。
 * 原本map、対応するUVチャネル、WheelStyleの三条件が揃わなければ厳格に拒否。
 * GLTFLoaderによる原本材質は作り直さず、そのまま描画しGPU提出だけ追跡する。
 */
export function isVerifiedSourceWheelMap(mesh) {
  if (mesh?.isMesh !== true || mesh.userData?.lo4_part_type !== 'WheelStyle') return false;
  const uvName = sourceWheelUvAttributeName(mesh.material?.map?.channel ?? 0);
  return uvName !== null && Boolean(mesh.geometry?.getAttribute?.(uvName))
    && mesh.material?.map?.isTexture === true
    && mesh.material?.userData?.lo4fh6_original_source_wheel_texture === ORIGIN;
}

export function retainVerifiedSourceWheelMap(mesh, drawn) {
  if (!isVerifiedSourceWheelMap(mesh)) return false;
  if (!drawn || typeof drawn.add !== 'function') throw new TypeError('Wheel GPU submission tracker missing');
  mesh.userData.lo4fh6_original_source_wheel_texture_applied = true;
  const previous = mesh.onBeforeRender;
  mesh.onBeforeRender = function (...args) {
    drawn.add(this.uuid);
    if (typeof previous === 'function') previous.apply(this, args);
  };
  return true;
}

export async function reconcileLoadedSourceWheelMaterials(gltf) {
  const parser = gltf?.parser;
  const json = parser?.json;
  const root = gltf?.scene;
  const report = {declared:0,seenInScene:0,retained:0,retainedSceneInstances:0,
    recoveredMetadata:0,
    recoveredPaintMetadata:0,recoveredSourceSignatures:0,
    recoveredMap:0,missingMap:0,missingUv:0,unmappedSceneMeshes:0,
    invalidSource:0,sourceOnly:true,shaderParityApproved:false};
  if (!json || !root?.traverse || !parser?.associations?.get || typeof parser.getDependency !== 'function') {
    report.reason = 'GLTFLoader scene/parser associations unavailable';
    return report;
  }
  const materials = Array.isArray(json.materials) ? json.materials : [];
  const meshes = Array.isArray(json.meshes) ? json.meshes : [];
  const nodes = Array.isArray(json.nodes) ? json.nodes : [];
  const target = new Map();
  for (let meshIndex=0; meshIndex<meshes.length; meshIndex++) {
    const mesh = meshes[meshIndex];
    const partType = wheelPartType(mesh?.extras);
    if (partType === null) { report.invalidSource++; continue; }
    if (partType !== 'WheelStyle') continue;
    for (let pi=0;pi<(mesh.primitives?.length||0);pi++) {
      const primitive=mesh.primitives[pi],id=primitive?.material;
      if (!isIndex(id,materials) || materials[id]?.extras?.lo4fh6_original_source_wheel_texture !== ORIGIN) continue;
      report.declared++;
      target.set(`${meshIndex}:${pi}`, {id,primitive,mesh});
    }
  }
  // glTF 2.0は別nodeから同一Mesh/Primitiveへの参照を許す。
  // 別nodeであることを原本JSONのIDで照合できたときだけ複数保持する。
  const seenSignedPrimitives=new Map();
  const retainedSignedPrimitives=new Set();
  const sceneMeshes=[];
  root.traverse(child => { if(child?.isMesh === true) sceneMeshes.push(child); });
  for(const child of sceneMeshes) {
    const association=parser.associations.get(child);
    let meshIndex=association?.meshes;
    // Some GLTFLoader builds retain only the node association for a single-primitive mesh.
    if(!isIndex(meshIndex,meshes) && isIndex(association?.nodes,nodes)) meshIndex=nodes[association.nodes].mesh;
    // Without a primitive association, index zero is only safe for a single-primitive mesh.
    // Multi-primitive wheels must not silently borrow the first material.
    const primitiveIndex=association?.primitives ?? (isIndex(meshIndex,meshes) && meshes[meshIndex].primitives?.length===1 ? 0 : -1);
    if (!isIndex(meshIndex,meshes) || !Number.isSafeInteger(primitiveIndex)) {
      if(child.userData?.lo4_part_type==='WheelStyle' && hasMap(child.material)) report.unmappedSceneMeshes++;
      continue;
    }
    const match=target.get(`${meshIndex}:${primitiveIndex}`);
    if(!match) continue;
    // A signed source primitive can only be accounted for once. Duplicated scene
    // associations are not evidence of two independently retained GLB primitives.
    const primitiveKey=`${meshIndex}:${primitiveIndex}`;
    const ownerAssociation=owningWheelNodeAssociation(child,association,parser);
    const nodeIndex=ownerAssociation?.nodes;
    const validNode=isIndex(nodeIndex,nodes)
      && nodes[nodeIndex]?.mesh===meshIndex
      && (ownerAssociation.meshes===undefined || ownerAssociation.meshes===meshIndex);
    // 子Primitiveにnodeがない場合も、実GLTFLoaderが作る親Groupで原本照合。
    // 偽node・親mesh矛盾・同じnode/primitiveの二重登録は拒否する。
    if(nodeIndex!==undefined && !validNode) {report.invalidSource++;continue;}
    const priorNodes=seenSignedPrimitives.get(primitiveKey);
    if(priorNodes) {
      if(!validNode || priorNodes.has(null) || priorNodes.has(nodeIndex)) {
        report.invalidSource++;continue;
      }
      priorNodes.add(nodeIndex);
    } else {
      seenSignedPrimitives.set(primitiveKey,new Set([validNode?nodeIndex:null]));
      report.seenInScene++;
    }
    const materialDef=materials[match.id];
    // WheelPaintの「原本RGBは完成色ではない」署名はGLB JSONのMaterial IDを正本とする。
    // WebView2でextrasが落ちたときも、当該materialの宣言と一致する場合だけ復旧する。
    const sourcePaintFlag=materialDef?.extras?.lo4fh6_wheel_paint_output_color_unresolved;
    if (sourcePaintFlag !== undefined && typeof sourcePaintFlag !== 'boolean') {
      report.invalidSource++;continue;
    }
    const baseTexture=materialDef?.pbrMetallicRoughness?.baseColorTexture;
    if(!isIndex(baseTexture?.index,Array.isArray(json.textures)?json.textures:[])) {
      report.invalidSource++;continue;
    }
    // glTF texCoord defaults to UV0. Never claim a signed source texture
    // was retained when its actual UV channel is absent from the geometry.
    // KHR_texture_transform.texCoord overrides the top-level texCoord per glTF 2.0.
    // GLTFLoader uses the override when binding the texture. Check that exact UV
    // channel, not an unrelated UV0 which happens to exist on the wheel mesh.
    const texCoord=sourceWheelTextureChannel(baseTexture);
    if(texCoord===null) {report.invalidSource++;continue;}
    // Three.js r185の実UV属性名を受信バイト検査・製品描画と共通化する。
    const uvName = sourceWheelUvAttributeName(texCoord);
    if(!child.geometry?.getAttribute?.(uvName)) {report.missingUv++;continue;}
    // 署名とローダー側メタデータを材質・色フラグの変更前に照合する。
    // 拒否されたprimitiveの共有Materialを部分的に書き換えない。
    // ローダー側の旧名PartTypeも署名済みWheelStyleと矛盾すれば拒否する。
    if (child.userData?.lo4_part_type !== undefined
        && child.userData.lo4_part_type !== 'WheelStyle') {
      report.invalidSource++;continue;
    }
    const aliases=signedWheelRoutingAliases(match.mesh, match.primitive,
      materialDef,child.userData);
    if (aliases === null) { report.invalidSource++;continue; }
    let material=child.material;
    if(Array.isArray(material)) {report.invalidSource++;continue;}
    // Always check the GLTFLoader material for *this exact* primitive's signed GLB
    // material ID. An unrelated map on the mesh must never become a false PASS.
    // GLTFLoader may reject an unavailable source texture or material dependency.
    // Report the missing original map rather than aborting the entire vehicle load.
    let loaded;
    try { loaded=await parser.getDependency('material',match.id); }
    catch (_error) { report.missingMap++;continue; }
    if(!hasMap(loaded)) {report.missingMap++;continue;}
    // 原本のtexCoordとGLTFLoaderが実描画に使うchannelも一致させる。
    // UV属性があるだけで誤った原本mapを保持したことにはしない。
    if((loaded.map.channel ?? 0)!==texCoord) {report.invalidSource++;continue;}
    // 共有materialの色署名を変更する前に、GLB正本とLoader候補の両方を検証する。
    // 拒否時にchild.materialを置換しない（原子的なfail-closed）。
    // GLB正本の署名を、既に別の出典を宣言する実材質へ上書きしない。
    // GLTFLoaderがextrasを落とした場合のundefinedは許容するが、矛盾する明示値は拒否。
    const origins=[material?.userData?.lo4fh6_original_source_wheel_texture,
      loaded?.userData?.lo4fh6_original_source_wheel_texture];
    if (origins.some(origin => origin !== undefined && origin !== ORIGIN)) {
      report.invalidSource++;continue;
    }
    const flags=[material?.userData?.lo4fh6_wheel_paint_output_color_unresolved,
      loaded?.userData?.lo4fh6_wheel_paint_output_color_unresolved];
    if (flags.some(flag => flag !== undefined && typeof flag !== 'boolean')
        || flags.some(flag => (sourcePaintFlag === true && flag === false)
          || (sourcePaintFlag !== true && flag === true))) {
      report.invalidSource++;continue;
    }
    // ModelBin / MatIのSHAは生成GLBのMaterial IDに保持済み。
    // GLTFLoader/WebView2がextrasを欠落させたときだけ、同じMaterial IDに
    // 記録された実バイト署名を復元する。Loaderの単独申告を証拠にしない。
    const signedSourceFields={};
    let sourceSignatureInvalid=false;
    for (const field of ['source_modelbin_sha256','material_instance_sha256',
                          'lo4fh6_wheel_paint_original_green_source_input']) {
      const declared=materialDef?.extras?.[field];
      const loadedFields=[material?.userData?.[field],loaded?.userData?.[field]];
      if (declared === undefined) {
        if (loadedFields.some(value=>value!==undefined)) sourceSignatureInvalid=true;
        continue;
      }
      const isGreenFlag=field==='lo4fh6_wheel_paint_original_green_source_input';
      if ((isGreenFlag ? typeof declared!=='boolean'
             : typeof declared!=='string' || !/^[0-9a-f]{64}$/i.test(declared))
          || loadedFields.some(value=>value!==undefined && (
            isGreenFlag ? value!==declared
              : typeof value!=='string' || value.toLowerCase()!==declared.toLowerCase()))) {
        sourceSignatureInvalid=true;
        break;
      }
      signedSourceFields[field]=isGreenFlag?declared:declared.toLowerCase();
    }
    if (sourceSignatureInvalid) {report.invalidSource++;continue;}
    // ModelBin SHAだけを材質から取り出しても、Meshのパス・Material IDがない
    // 場合は車輪ルートを推測しない。宣言済みMeshの旧名と矛盾しても拒否。
    if (signedSourceFields.source_modelbin_sha256 &&
        aliases.lo4_source_entry && aliases.lo4_wheel_material_id!==undefined) {
      const declaredOnMesh=aliases.lo4_wheel_source_modelbin_sha256;
      if (declaredOnMesh!==undefined &&
          declaredOnMesh.toLowerCase()!==signedSourceFields.source_modelbin_sha256) {
        report.invalidSource++;continue;
      }
      if (declaredOnMesh===undefined)
        aliases.lo4_wheel_source_modelbin_sha256=signedSourceFields.source_modelbin_sha256;
    }
    const replaceMap=!hasMap(material) || material.map !== loaded.map;
    const chosen=replaceMap ? loaded : material;
    const recoverPaint=sourcePaintFlag === true
      && chosen?.userData?.lo4fh6_wheel_paint_output_color_unresolved !== true;
    const recoverSourceSignatures=Object.entries(signedSourceFields).some(([field,value])=>
      chosen?.userData?.[field]!==value);
    const missingAliases=Object.entries(aliases).some(([key,value])=>
      JSON.stringify(child.userData?.[key]) !== JSON.stringify(value));
    const recoverMetadata=child.userData?.lo4_part_type !== 'WheelStyle'
      || chosen?.userData?.lo4fh6_original_source_wheel_texture !== ORIGIN
      || missingAliases;
    // GLTFLoaderは複数primitiveで同じMaterialを共有し得る。
    // 署名の補完は当該primitiveだけへ適用し、他のprimitiveの材質を変更しない。
    if (recoverPaint || recoverSourceSignatures || (recoverMetadata
        && chosen?.userData?.lo4fh6_original_source_wheel_texture !== ORIGIN)) {
      if (typeof chosen?.clone !== 'function') {
        report.invalidSource++;continue;
      }
      material=chosen.clone();
      material.userData={...chosen.userData};
    } else {
      material=chosen;
    }
    if(recoverPaint) {
      material.userData={...material.userData,
        lo4fh6_wheel_paint_output_color_unresolved:true};
      report.recoveredPaintMetadata++;
    }
    if(recoverSourceSignatures) {
      material.userData={...material.userData,...signedSourceFields};
      report.recoveredSourceSignatures++;
    }
    if(recoverMetadata) {
      child.userData={...child.userData,...aliases,lo4_part_type:'WheelStyle'};
      if(material.userData?.lo4fh6_original_source_wheel_texture !== ORIGIN)
        material.userData={...material.userData,lo4fh6_original_source_wheel_texture:ORIGIN};
      report.recoveredMetadata++;
    }
    if (replaceMap || material !== child.material) child.material=material;
    if (replaceMap) report.recoveredMap++;
    report.retainedSceneInstances++;
    if(!retainedSignedPrimitives.has(primitiveKey)) {
      retainedSignedPrimitives.add(primitiveKey);
      report.retained++;
    }
  }
  // 共有Wheelで一部nodeだけ正常な場合も、残りの欠損をPASSに隠さない。
  // Primitive一意件数だけでは可視インスタンスの欠落を検出できない。
  if(report.declared !== report.retained || report.invalidSource > 0
      || report.missingUv > 0 || report.missingMap > 0
      || report.unmappedSceneMeshes > 0){
    const missing=report.declared-report.seenInScene;
    report.reason=`scene missing=${missing}, UV missing=${report.missingUv}, map missing=${report.missingMap}, bad source=${report.invalidSource}, unmapped=${report.unmappedSceneMeshes}`;
  }
  return report;
}


/**
 * HTTP受信した一意Primitive、GLTFLoaderでの保持Primitive、シーン描画
 * インスタンスを別々に照合。GLBの同一Meshを別nodeで使う正規glTF構造を許し、
 * 署名欠損・重複・未保持・別材質の混入では必ずfalseを返す。
 */
export function signedWheelSceneReconciled(reconciled, declared, mappedMeshes, received=null) {
  const primitives=declared?.signedWheelPrimitives;
  return Number.isSafeInteger(primitives) && primitives>=0
    && Number.isSafeInteger(mappedMeshes) && mappedMeshes>=0
    && reconciled?.sourceOnly===true
    && reconciled?.declared===primitives
    && reconciled?.seenInScene===primitives
    && reconciled?.retained===primitives
    && reconciled?.retainedSceneInstances===mappedMeshes
    && reconciled?.invalidSource===0
    && reconciled?.missingUv===0
    && reconciled?.missingMap===0
    && reconciled?.unmappedSceneMeshes===0
    && !reconciled?.reason
    && (received==null || (
      received.signedWheelPrimitives===primitives
      && received.signedMaterials===declared.signedMaterials));
}
