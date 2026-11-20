// r416: opt-in synthetic-browser-storage I/O timing. NEVER write paint/PNG bytes.
// File content is deterministic synthetic data; always attempt cleanup.
// OPFS is browser-origin storage, not a guarantee of physical SSD I/O.
export async function measureSyntheticOpfsIo(pngBytes, options = {}) {
  const clock = options.clock || (() => performance.now());
  const failed = code => ({ok:false,failureCode:code,bytes:0,writeMs:0,readMs:0,verifyMs:0,cleanupSucceeded:0});
  if (!Number.isSafeInteger(pngBytes) || pngBytes < 1 || pngBytes > 16*1024*1024) return failed(1);
  const storage = options.storage || (typeof navigator !== 'undefined' ? navigator.storage : null);
  const cryptoApi = options.cryptoApi || (typeof crypto !== 'undefined' ? crypto : null);
  if (typeof storage?.getDirectory !== 'function' || typeof cryptoApi?.randomUUID !== 'function') return failed(2);
  let root, filename, fileCreated = false, writeMs=0, readMs=0, verifyMs=0;
  let failureCode = 0, cleanupSucceeded = 0;
  try {
    root = await storage.getDirectory();
    filename = `lo4fh6-r416-synthetic-${cryptoApi.randomUUID()}.bin`;
    const bytes = new Uint8Array(pngBytes);
    // No C_livery, canvas, PNG, titles or identifiers can enter this buffer.
    for (let i=0;i<bytes.length;i++) bytes[i] = (i * 37 + 17) & 255;
    const handle = await root.getFileHandle(filename,{create:true});
    fileCreated=true;
    let start=clock();
    const writer=await handle.createWritable({keepExistingData:false});
    try { await writer.write(bytes); await writer.close(); }
    catch (error) { try { await writer.abort?.(); } catch (_) {} throw error; }
    writeMs=Math.max(0,Math.round(clock()-start));
    start=clock();
    const readFile=await (await root.getFileHandle(filename)).getFile();
    const readBytes=new Uint8Array(await readFile.arrayBuffer());
    readMs=Math.max(0,Math.round(clock()-start));
    start=clock();
    if (readBytes.length!==bytes.length) failureCode=5;
    else {
      for(let i=0;i<bytes.length;i++) if (bytes[i]!==readBytes[i]) {failureCode=5;break;}
    }
    verifyMs=Math.max(0,Math.round(clock()-start));
  } catch (_) {
    failureCode = fileCreated ? (writeMs ? 4 : 3) : 3;
  } finally {
    // Always attempt cleanup. If cleanup fails, never claim a clean probe.
    if (fileCreated && root && filename) {
      try { await root.removeEntry(filename); cleanupSucceeded=1; }
      catch (_) { failureCode=6; }
    }
  }
  if (failureCode || !cleanupSucceeded) return {ok:false,failureCode:failureCode||6,bytes:0,writeMs,readMs,verifyMs,cleanupSucceeded};
  return {ok:true,failureCode:0,bytes:pngBytes,writeMs,readMs,verifyMs,cleanupSucceeded};
}
