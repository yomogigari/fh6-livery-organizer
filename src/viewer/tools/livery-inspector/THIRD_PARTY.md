# Livery Inspector が使う第三者ライブラリ

この Viewer（`src/viewer` 一式）には、第三者のファイルを置かず、同梱もしません。
描画に必要な Three.js だけは、初回起動時に公式配布から取得して、利用者のローカル領域に置きます。

| ライブラリ | 版 | ライセンス | 取得元 |
| --- | --- | --- | --- |
| Three.js | 0.185.1 | MIT | https://registry.npmjs.org/three/-/three-0.185.1.tgz（https://github.com/mrdoob/three.js/tree/r185） |

## 取得と配置

- 取得・照合の処理：`tools/livery/local_three_dependency.py`
- 版と照合値（SHA256、7 ファイル）：`tools/livery/three_runtime_manifest.py`
- 置き場所：`%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\dependencies\three-0.185.1`
- 7 ファイルの SHA256 がすべて一致した場合だけ置きます。一致しない場合は置かずに止まります。
  既に置かれたファイルが一致しない場合も、書き換えずに止まります。
- Viewer のローカルサーバーは、`vendor/three/` への要求をこの置き場所から返します。
  照合値に載った 7 ファイル以外は返しません。

取得する 7 ファイル：

- `build/three.module.min.js`
- `build/three.core.min.js`
- `examples/jsm/controls/OrbitControls.js`
- `examples/jsm/loaders/GLTFLoader.js`
- `examples/jsm/utils/BufferGeometryUtils.js`
- `examples/jsm/utils/SkeletonUtils.js`
- `LICENSE`（MIT ライセンスの原文）

ゲームのモデル・テクスチャ・その他の原本は、このフォルダーにも配布物にも含めません。
描画に使う原本のデータは、利用者のゲームのインストールから、その場で読み取ります。
