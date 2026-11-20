// rM054研究差分: 原本材質名が確認できるミラー/側面反射板のみを区別する。
// 車種ID・リバリーID・見た目だけから材質を推定しない。製品既定で呼び出さない。
const normalizeMaterial = (value) => {
  if (typeof value !== 'string' || !value.trim()) return '';
  return value.trim().toLowerCase().replace(/\\/g, '/').replace(/\.materialbin$/, '').split('/').pop().split('|')[0];
};

export function sourceNeutralMaterialRole(mesh) {
  const data = mesh?.userData || {};
  const geometryData = mesh?.geometry?.userData || {};
  // 他製品の材質スロット参照を出典確認に利用（外部コードは移植しない）。
  // 自前で保全したGLB extrasのみ検査し、スロット矛盾なら研究OFF扱い。
  const buckets = [geometryData.lo4fh6_source_draw_bucket, data.lo4fh6_source_draw_bucket]
    .filter(value => value && typeof value === 'object');
  const idRows = [
    ['primitive', geometryData.lo4_material_id],
    ['node', data.lo4_material_id],
    ...buckets.map((bucket, i) => [`draw-bucket-${i}`, bucket.material_id]),
  ].filter(([, value]) => Number.isInteger(Number(value)) && value !== null && value !== '' && Number(value) >= 0);
  const ids = [...new Set(idRows.map(([, value]) => Number(value)))];
  if (ids.length > 1) return {role:null, reason:'material-slot-conflict', materialIds:ids};
  const materialId = ids.length === 1 ? ids[0] : null;
  const provenance = [
    ...buckets.map((bucket, i) => [`draw-bucket-${i}`, bucket.source_material]),
    ['primitive', geometryData.lo4_material_name],
    ['primitive-original', geometryData.lo4fh6_original_material],
    ['node', data.lo4_material_name],
    ['node-original', data.lo4fh6_original_material],
  ].filter(([, value]) => typeof value === 'string' && value.trim());
  // 元GLBで材質名がprimitive/nodeへ届かない場合に限り、元glTF material.nameを使う。
  // 不一致を名前優先で上書きしない。複数の値は完全一致したもののみ受け入れる。
  const original = provenance.length ? provenance : [['gltf-material', mesh?.material?.name]];
  const names = original.map(([, value]) => normalizeMaterial(value)).filter(Boolean);
  if (!names.length) return {role:null, reason:'material-unavailable'};
  if (names.some(name => name !== names[0])) return {role:null, reason:'material-conflict'};
  const material = names[0];
  // 原本部品の出典パスを優先する。mesh.nameだけで別部品を鏡へ分類しない。
  const declaredSource = String(data.lo4_source_entry || geometryData.lo4_source_entry || data.source_archive_member || geometryData.source_archive_member || '')
    .toLowerCase().replace(/\\/g, '/');
  const source = declaredSource || String(mesh?.name || '').toLowerCase();
  // 原本body_a内のアンテナは別ModelBinではなくメッシュ名で材質を区別する。
  // |bodyantenna_a は原本材質のインスタンス接尾辞で、ベース材質名には含めない。
  const originalMeshName=String(data.lo4_source_mesh_name || geometryData.lo4_source_mesh_name || '')
    .toLowerCase();
  if (declaredSource.endsWith('.modelbin') && /antenna(?:_|$)/.test(originalMeshName)) {
    if (material === 'plastic_smooth')
      return {role:'antenna_plastic',reason:'source-mesh-and-material',material,materialId};
    if (material === 'rubber_rough')
      return {role:'antenna_rubber',reason:'source-mesh-and-material',material,materialId};
  }

  // 元ModelBinの部品/材質の組み合わせが揃ったときだけ採用する。
  if (source.includes('wingmirror') || source.includes('mirrorbase')) {
    if (['mirror_left', 'mirror_right', 'mirrorleft', 'mirrorright', 'mirrorcenter', 'mirror_center'].includes(material))
      return {role:'mirror_surface', reason:'verified-material-name', material, materialId};
    if (material === 'rubber_rough') return {role:'mirror_rubber', reason:'verified-material-name', material, materialId};
    if (material === 'carpaint') return {role:'mirror_carpaint', reason:'verified-material-name', material, materialId};
    // Jaguar XJSFE: mirrorLeft/Right以外に金属台座と樹脂カバーを別素材で持つ。
    // 金属素材は原本どおり従来bright_metalを維持し、樹脂を金属にしない。
    if (material === 'plastic_smooth') return {role:'mirror_plastic', reason:'verified-material-name', material, materialId};
    if (['metal_anodized', 'metal_brushed'].includes(material))
      return {role:'mirror_metal', reason:'verified-material-name', material, materialId};
  }
  if (source.includes('sidemarker')) {
    if (['reflector_square', 'reflector', 'reflector_ch1'].includes(material))
      return {role:'marker_reflector', reason:'verified-material-name', material, materialId};
    if (['glass', 'glass_reflector', 'gls_colored'].includes(material))
      return {role:'marker_glass', reason:'verified-material-name', material, materialId};
    if (['plastic_mgl', 'plastic_smooth'].includes(material))
      return {role:'marker_plastic', reason:'verified-material-name', material, materialId};
  }
  return {role:null, reason:'unmatched-source-role', material, materialId};
}


/**
 * ミラーカバーの原本carPaintを車体Livery投影から分離する研究用ゲート。
 * 既存の通常paint分類・Mirror鏡面・サイドマーカーは変更しない。
 * 元ModelBin+元MatI ID+元Shader材質名が揃った場合だけ比較を許す。
 * FH6最終の塗装可否・Xbox白色を確定するものではない。
 */
// 標準Viewerの原本Mirror材質の単一署名ゲート。実行スイッチは持たない。
export function sourceMirrorHousingPaintStandardGate(mesh) {
  const data=mesh?.userData || {};
  const geometryData=mesh?.geometry?.userData || {};
  const source=String(data.lo4_source_entry || geometryData.lo4_source_entry || '')
    .toLowerCase().replace(/\\/g,'/');
  // 出典がない場合はmesh.nameの「mirror」という単語で代用しない。
  if (!/(?:^|\/)(?:wingmirror|mirrorbase)[^/]*\.modelbin$/.test(source))
    return {ok:false,reason:'mirror-original-modelbin-source-unavailable'};
  const role=String(data.lo4_role || geometryData.lo4_role || '').toLowerCase();
  if (role !== 'paint') return {ok:false,reason:'source-paint-role-not-declared'};
  const evidence=sourceNeutralMaterialRole(mesh);
  if (evidence.role !== 'mirror_carpaint')
    return {ok:false,reason:'mirror-material-signature-unavailable'};
  // 元MatIは従来のViewer材質IDとは異なる名前空間に保持される場合がある。
  // 通常描画に使うsourceNeutralMaterialRoleを変更せず、研究ゲートだけで元MatIを検査。
  const originalId=originalSourceMatI(mesh);
  if (!originalId.ok) return {ok:false,reason:originalId.reason};
  if (mesh?.geometry?.getAttribute?.('uv3') == null)
    return {ok:false,reason:'original-uv3-signature-unavailable'};
  return {ok:true,role:'mirror_carpaint',materialId:originalId.materialId,
    candidateProfile:'source_body_color',sourceOnly:true,
    shaderParityApproved:false,xboxApproved:false,productDefaultChanged:false};
}


/**
 * Windows実機/Xbox目視で受入済みのミラー工場色を通常入口へ接続する署名ゲート。
 * カラーは元ManufacturerColors.binのMirror slot0由来で車種/リバリー固定ではない。
 * 元ModelBin/MatI/UV3が一致しない部品へは使わず、選択状態やShader同値は主張しない。
 */
export function sourceMirrorFactoryStandardEligible(mesh, proof) {
  const cover = sourceMirrorHousingPaintStandardGate(mesh);
  if (!cover.ok) return {ok:false,reason:cover.reason};
  if (!proof || proof.schema !== 'lo4fh6.source-original-accessory-mirror-oem-preview.v1'
      || proof.source_slot !== 'Mirror' || proof.source_selector !== 0
      || proof.source_color_available !== true)
    return {ok:false,reason:'mirror-manufacturercolors-slot0-signature-unavailable'};
  if (typeof proof.manufacturer_palette_member !== 'string'
      || !/(?:^|[\\/])manufacturercolors\.bin$/i.test(proof.manufacturer_palette_member))
    return {ok:false,reason:'mirror-original-palette-member-unverified'};
  if (typeof proof.source_material_path !== 'string'
      || !/^game:\\media\\cars\\_library\\materials\\_fmnext\\carpaint_calibrated\\[^\\]+\.materialbin$/i.test(proof.source_material_path))
    return {ok:false,reason:'mirror-original-calibrated-material-unverified'};
  const colorHex=proof.mirror_factory_rgb_hex;
  if (typeof colorHex !== 'string' || !/^#[0-9a-f]{6}$/i.test(colorHex))
    return {ok:false,reason:'mirror-original-factory-rgb-unverified'};
  return {ok:true,profile:'source_mirror_factory_preview',colorHex,
    materialId:cover.materialId,source:'original-ManufacturerColors-Mirror-selector0',
    gameShaderExact:false,saveStateSelectorProven:false};
}

/**
 * Mirror Factory previewが元車両に明示的に存在しない場合のみ、元GLB材質を
 * 置換せず保持できる。OEM候補色はC_liveryの最終適用色とは異なるため、
 * 「工場色プレビューなし」と「署名があるのに不整合」を区別する。
 *
 * 元原本の読込エラーも製品画面に残し、工場色が確認済みだったと主張しない。
 * 欠損・型不正・矛盾した署名つきPalette候補は対象外で、そのままエラー。
 */
export function sourceMirrorOriginalMaterialRetentionAllowed(proof) {
  // Python製品Prepareが「Palette候補を復号できなかった」と明示した契約だけ。
  // 不完全な署名済み色を「候補なし」と偽装して受け入れないため、
  // 選択色・出典など署名候補のフィールドが混在した場合は保持せず停止。
  return proof?.schema === 'lo4fh6.source-original-accessory-mirror-oem-preview.v1'
    && proof.source_color_available === false
    && typeof proof.unavailable_reason === 'string'
    && proof.unavailable_reason.length > 0
    && proof.selected_game_color_approved === false
    && proof.game_shader_rgb_equivalent === false
    && proof.xbox_approved === false
    && ['source_slot','source_selector','mirror_factory_rgb_hex',
      'source_material_path','manufacturer_palette_member'].every(key => !Object.hasOwn(proof,key));
}

/**
 * 第一者GLBのMatIは文字列 "5" と数値5の双方が保存形式として存在する。
 * 同じ値への正規変換だけを認め、不明・矛盾・負数・非整数は拒否。
 * 元GLBの他の材質ID名前空間（lo4_material_id）は書き換えない。
 */
export function originalSourceMatI(mesh) {
  const data=mesh?.userData||{},geo=mesh?.geometry?.userData||{};
  const raw=[geo.lo4fh6_original_matI_id,data.lo4fh6_original_matI_id]
    .filter(v=>v!==null&&v!==undefined);
  if(!raw.length)return {ok:false,reason:'original-mati-id-unavailable'};
  const parsed=raw.map(v => {
    if(typeof v==='number' && Number.isSafeInteger(v)&&v>=0)return v;
    if(typeof v==='string' && /^(0|[1-9][0-9]*)$/.test(v)){
      const n=Number(v);return Number.isSafeInteger(n)?n:null;
    }
    return null;
  });
  if(parsed.some(v=>v===null) || parsed.some(v=>v!==parsed[0]))
    return {ok:false,reason:'original-mati-id-unavailable-or-conflict'};
  return {ok:true,materialId:parsed[0]};
}

/**
 * 原本部品の材質とMesh名により、Livery投影ではない部品を比較する。
 * 例: body_a.modelbin 内のアンテナ（樹脂/ゴム）。
 * 全車両共通で出典を照合し、未知なら色を推測しない。
 */
// 標準Viewer原本Accessory。署名不足は理由付き拒否、研究有効化不要。
export function sourceOriginalAccessoryStandardGate(mesh) {
  const data=mesh?.userData||{},geo=mesh?.geometry?.userData||{};
  const src=String(data.lo4_source_entry||geo.lo4_source_entry||'').toLowerCase().replace(/\\/g,'/');
  if(!/\.modelbin$/.test(src))return {ok:false,reason:'source-modelbin-missing'};
  const originalRole=String(data.lo4_role||geo.lo4_role||'').toLowerCase();
  if(originalRole==='hidden')return {ok:false,reason:'hidden-part'};
  const materialEvidence=sourceNeutralMaterialRole(mesh);
  if(!['antenna_plastic','antenna_rubber'].includes(materialEvidence.role))
    return {ok:false,reason:'source-accessory-role-unknown'};
  const mati=originalSourceMatI(mesh);
  if(!mati.ok)return mati;
  return {ok:true,sourceRole:materialEvidence.role,originalMatIId:mati.materialId,
    category:'trim',materialProfile:'dark_trim',gameMaterialEquivalent:false,
    xboxApproved:false,productDefaultChanged:false};
}

/**
 * 研究GLBの一般Trimに実原本の非塗装素材が明示されている場合、
 * UV3や「body/exterior」という広い単語だけでPaintへ昇格させない。
 * 暗黙のMaterialBin名・Body名から元の色は推定しない。
 */
export function sourceOriginalNonPaintTrimGuard(mesh) {
  const data=mesh?.userData||{},geo=mesh?.geometry?.userData||{};
  if(String(data.lo4_role||geo.lo4_role||'').toLowerCase()!=='trim')
    return {guard:false,reason:'not-declared-trim'};
  const source=String(data.lo4_source_entry||geo.lo4_source_entry||'').toLowerCase().replace(/\\/g,'/');
  if(!source.endsWith('.modelbin'))return {guard:false,reason:'source-unavailable'};
  const id=originalSourceMatI(mesh);
  if(!id.ok)return {guard:false,reason:id.reason};
  const raw=[data.lo4_material_name,geo.lo4_material_name,geo.lo4fh6_original_material,
    data.lo4fh6_original_material].filter(x=>typeof x==='string'&&x.trim());
  if(!raw.length)return {guard:false,reason:'material-unavailable'};
  const names=raw.map(normalizeMaterial);
  if(names.some(n=>!n||n!==names[0]))
    return {guard:false,reason:'material-conflict'};
  const name=names[0];
  const originalNonPaint=/^(?:plastic(?:_|$)|rubber(?:_|$)|glass(?:_|$)|gls_|black(?:frame|hole|glass|$)|mirror(?:_|left|right|center)|reflector(?:_|$)|chrome(?:_|$)|screw(?:_|$)|aluminum(?:_|$)|steel(?:_|$)|gunmetal(?:_|$)|label(?:_|$)|grille(?:_|$))/.test(name);
  return {guard:originalNonPaint,originalMaterial:name,originalMatIId:id.materialId,
    reason:originalNonPaint?'source-original-nonpaint-trim':'not-proven-nonpaint'};
}

// 履歴研究テストのみの互換入口。通常Viewer/Organizer/撮影の呼出元には置かない。
export function sourceMirrorHousingPaintResearchGate(mesh, {enabled=false}={}) {
  if (enabled !== true) return {ok:false,reason:'research-off'};
  return sourceMirrorHousingPaintStandardGate(mesh);
}
export function sourceOriginalAccessoryResearchGate(mesh, {enabled=false}={}) {
  if (enabled !== true) return {ok:false,reason:'research-off'};
  return sourceOriginalAccessoryStandardGate(mesh);
}
