/**
 * Windows Viewer用の画像保存アダプター。保存成功はOSで実ファイルを書き終えた時だけ。
 * 既存GPU描画・JPEG/PNGエンコード・各方向カメラは変更しない。
 */
const CHUNK_BYTES = 384 * 1024;

function bytesToBase64(bytes) {
  const parts = [];
  for (let i=0; i<bytes.length; i+=16384) {
    parts.push(String.fromCharCode(...bytes.subarray(i, Math.min(i+16384,bytes.length))));
  }
  return btoa(parts.join(''));
}

export async function saveCaptureImage(canvas, filename, {format='jpeg',quality=0.95, downloadFallback}={}) {
  if (!canvas || !Number.isSafeInteger(canvas.width) || !Number.isSafeInteger(canvas.height)
      || canvas.width<=0 || canvas.height<=0 || !['jpeg','png'].includes(format)) {
    throw new Error('画像保存の形式・寸法が不正です');
  }
  const nativeApi = window.pywebview?.api;
  if (!nativeApi?.begin_image_save || !nativeApi?.append_image_save || !nativeApi?.finish_image_save) {
    // 通常ブラウザーはダウンロード設定に従うため、ファイル書き込み済みとは断定しない。
    if (!downloadFallback) throw new Error('Windowsの画像保存APIが利用できません。保存できていません。');
    const result = await downloadFallback(canvas,filename,{format,quality});
    return {...result, requestedOnly:true};
  }
  const response = await nativeApi.begin_image_save(filename,format);
  if (response?.cancelled) return {cancelled:true};
  if (!response?.ok || typeof response.token!=='string') throw new Error('保存ダイアログ: '+(response?.error||'失敗'));
  const token = response.token;
  try {
    const mime = format==='jpeg'?'image/jpeg':'image/png';
    const blob = await new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('画像エンコードに失敗')),
      mime,format==='jpeg'?quality:undefined));
    if (blob.type!==mime || blob.size<=0) throw new Error('画像のエンコード形式・サイズが不正です');
    for(let pos=0;pos<blob.size;pos+=CHUNK_BYTES) {
      const buffer = await blob.slice(pos,Math.min(blob.size,pos+CHUNK_BYTES)).arrayBuffer();
      const result = await nativeApi.append_image_save(token,bytesToBase64(new Uint8Array(buffer)));
      if (!result?.ok) throw new Error('画像データの書き込みに失敗: '+(result?.error||'不明'));
    }
    const result=await nativeApi.finish_image_save(token,blob.size);
    if (!result?.ok || !result.path || result.bytes!==blob.size || !/^[0-9a-f]{64}$/.test(result.sha256||'')) {
      throw new Error('保存ファイルの実バイト照合に失敗: '+(result?.error||'不明'));
    }
    return {path:result.path,bytes:result.bytes,sha256:result.sha256,
      width:canvas.width,height:canvas.height,verified:true};
  } catch(error) {
    try {await nativeApi.abort_image_save?.(token);} catch {}
    throw error;
  }
}
