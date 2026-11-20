/** 確認済みFEOWの署名済み原本材質を検出した場合のみ標準自動適用する。 */
export function shouldAutoApplySignedFeow(root, wheelSource) {
  if (wheelSource !== 'source-verified') return false;
  let found = false;
  root?.traverse?.(mesh => {
    // 文字MatIは役割名（sidewall/whitewall等）でなく、Python側が付けた原本文字署名で判定する。
    if (mesh?.isMesh && mesh.userData?.lo4_part_type === 'Tire'
        && mesh.material?.userData?.lo4fh6_original_feow_two_textures === true) found = true;
  });
  return found;
}
