"""Viewerが使う Three.js（MIT ライセンスの第三者ライブラリ）の版と照合値。

Three.js はリポジトリにも配布物（src/viewer 一式）にも同梱しない。初回起動時に npm の
公式配布から取得し、下記7ファイルの SHA256 が一致した場合だけ利用者のローカル領域
（%LOCALAPPDATA%\\Livery Organizer for FH6\\PreviewBridge\\dependencies\\three-<版>）へ置く。
照合値は Viewer 自身（src/viewer）に持ち、src/viewer だけを別のリポジトリへコピーしても動く。

2026-11-17：npm three@0.185.1 の7ファイルが下記の照合値と一致することを確認済み。
（以前の取得先 0.185.0 は build/three.core.min.js 等が一致せず、取得が常に失敗していた。）
"""
from __future__ import annotations

THREE_VERSION = "0.185.1"
PACKAGE_URL = f"https://registry.npmjs.org/three/-/three-{THREE_VERSION}.tgz"

THREE_SHA = {
    "LICENSE": "8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc",
    "build/three.core.min.js": "05b2609338c76cd65daf74f3ac515bc9a5045e1b3b33edc07d8c9bd55250fa90",
    "build/three.module.min.js": "86bcee248b64f44bcfc23c331ae74619061957d59cab040171dcb6fb5900beb6",
    "examples/jsm/controls/OrbitControls.js": "faabb4e8dfd9235ee4a9fd7c9a3d75f90f1689dbd4944bd6fd32117dacec5f93",
    "examples/jsm/loaders/GLTFLoader.js": "97642d720f16cc9a0c9844934198e4d0c023bea8e89576d0f7545d03b2d103d2",
    "examples/jsm/utils/BufferGeometryUtils.js": "5c552223a9309883743b80538d6e9cdb45e3227f30d3ec56fb2c39b46e78d595",
    "examples/jsm/utils/SkeletonUtils.js": "b1632a703206c3d830de9fcbe515696770d04b71a15ee6b50afa6d2c3298c86f",
}
