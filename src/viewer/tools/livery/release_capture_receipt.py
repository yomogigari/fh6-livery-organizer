"""PRIVATE受入時のみ、実GPU 4K技術判定とWindows保存ファイルSHAを結び付ける。

ゲーム原本、本人C_livery、個人フォルダー、外観画像を含まない。
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DIGEST = re.compile(r'^[0-9a-f]{64}$')
_REASON = re.compile(r'^[a-z][a-z0-9-]{0,95}$')
_OBS = ('bodyMeshes', 'paintMeshes', 'glassMeshes', 'signedWheelPrimitives',
        'receivedWheelPrimitives', 'gltfLoaderWheelPrimitives',
        'retainedWheelTextures', 'captureFrameWheelGpuSubmissions')


def _count(value, *, positive=False, max_value=10_000_000):
    if type(value) is not int or not (1 if positive else 0) <= value <= max_value:
        raise ValueError('撮影結果の整数範囲が不正です')
    return value


def sanitize_release_capture(payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {'audit', 'image'}:
        raise ValueError('受入結果の項目構成が不正です')
    audit, image = payload['audit'], payload['image']
    if not isinstance(audit, dict) or not isinstance(image, dict):
        raise ValueError('撮影結果がオブジェクトではありません')
    if audit.get('schema') != 'lo4fh6.release.complete-scene-capture-audit.v1':
        raise ValueError('描画監査スキーマ不一致')
    status = audit.get('status')
    if status not in ('TECHNICAL_CAPTURE_READY', 'REVIEW_REQUIRED'):
        raise ValueError('受入ステータス不正')
    reasons = audit.get('reasons')
    if not isinstance(reasons, list) or len(reasons) > 32 or any(
       not isinstance(v, str) or not _REASON.fullmatch(v) for v in reasons
    ):
        raise ValueError('監査理由の形式が不正')
    if len(set(reasons)) != len(reasons):
        raise ValueError('監査理由が重複')
    if (status == 'TECHNICAL_CAPTURE_READY') != (len(reasons) == 0):
        raise ValueError('READYと不合格理由が矛盾')
    for k in ('releaseApproved','redistributionApproved','gameXboxVisualApproved','fileSavedOrShaVerified'):
        if audit.get(k) is not False:
            raise ValueError('未承認ステータスを書き換えられません')
    if audit.get('gameOriginalBytesIncluded') is not False or audit.get('vehicleSpecificCorrection') is not False:
        raise ValueError('原本データ・車種個別補正を含む結果を拒否')
    frame = audit.get('frame')
    observed = audit.get('observed')
    if not isinstance(frame, dict) or not isinstance(observed, dict):
        raise ValueError('GPUフレーム測定がありません')
    width = _count(frame.get('width'), positive=True, max_value=16384)
    height = _count(frame.get('height'), positive=True, max_value=16384)
    if frame.get('glReadPixelsOk') is not True:
        raise ValueError('WebGL2 readPixels未実施のため証拠保存不可')
    obs = {k:(_count(observed[k]) if observed.get(k) is not None else None) for k in _OBS}
    if set(observed) != set(_OBS):
        raise ValueError('原本Wheel/外板の測定項目が欠損・過剰')
    if image.get('format') not in ('jpeg', 'png'):
        raise ValueError('画像形式不正')
    verified = image.get('verified') is True
    # キャンセルやブラウザダウンロード要求のみの場合、保存SHA証拠として誤採用しない。
    if verified:
        digest=image.get('sha256')
        if not isinstance(digest,str) or not _DIGEST.fullmatch(digest):
            raise ValueError('Windows保存実バイトSHA未確認')
        size=_count(image.get('bytes'),positive=True,max_value=256_000_000)
        imgwidth=_count(image.get('width'),positive=True,max_value=16384)
        imgheight=_count(image.get('height'),positive=True,max_value=16384)
        if (imgwidth,imgheight)!=(width,height):
            raise ValueError('GPUとJPEG保存寸法不一致')
    else:
        digest=None;size=None;imgwidth=None;imgheight=None
    return {
      'schema':'lo4fh6.release.capture-saved-evidence.v1',
      'audit':{
        'schema':audit['schema'],'status':status,'reasons':reasons,
        'frame':{'width':width,'height':height,'glReadPixelsOk':True},
        'observed':obs,'gameXboxVisualApproved':False,
        'redistributionApproved':False,'releaseApproved':False,
      },
      'saved_image':{
        'status':'SHA_VERIFIED' if verified else 'NOT_VERIFIED',
        'format':image['format'],'bytes':size,'sha256':digest,
        'width':imgwidth,'height':imgheight,
      },
      'same_capture_frame_sha_verified': status=='TECHNICAL_CAPTURE_READY' and verified,
      'release_status':'REVIEW_REQUIRED',
      'owner_folder_or_original_bytes_included':False,
    }


def save_release_capture_receipt(output_dir: Path, payload: dict) -> dict:
    clean=sanitize_release_capture(payload)
    root=Path(output_dir)
    if root.is_symlink():
        raise ValueError('出力先がシンボリックリンクです')
    root.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M-JST')
    clean['created_at_jst']=datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST')
    serialized=(json.dumps(clean,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode('utf-8')
    digest=hashlib.sha256(serialized).hexdigest()
    suffix=(clean['saved_image']['sha256'][:12] + '-' if clean['saved_image']['sha256'] else '') + digest[:12]
    destination=root/f'release-scene-capture-{stamp}-{suffix}.json'
    # 監査結果は追記可能でなければならないが、既存実体への無告知上書きは禁止。
    # 同じGPU撮影を同分に保存したときだけ実バイト同一なら再利用。
    if destination.exists():
        if destination.is_symlink() or destination.read_bytes()!=serialized:
            raise ValueError('既存撮影受入記録の上書きを拒否')
    else:
        with destination.open('xb') as fh:
            fh.write(serialized)
    return {'ok':True,'status':clean['audit']['status'],
            'same_capture_frame_sha_verified':clean['same_capture_frame_sha_verified'],
            'path':str(destination),'sha256':digest,'bytes':len(serialized)}
