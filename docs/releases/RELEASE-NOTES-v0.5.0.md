# Livery Organizer for FH6 v0.5.0 Preview — Release Notes

公開日: 2026-11-22

Livery Organizer for FH6 v0.5.0 Previewでは、レポートのペイントを車体に貼って3Dで確かめられる **Livery Viewer for FH6** を同梱しました。あわせて、Livery Organizer for FH6・Livery Viewer for FH6・Navigator Bridge for FH6 の3つを同じ版の番号 **v0.5.0** にそろえ、言語・表示テーマ・画面の見た目と、Organizer連携の登録をまとめて扱えるようにしました。

同梱する車両メタデータは **2026-11更新 / 667車種 / package revision 4** へ更新しました。

## Livery Viewer for FH6（3Dプレビュー）

レポートの各カードに「プレビュー」を追加しました。押すと、そのペイントを車体に貼った3D表示が Livery Viewer for FH6 の窓で開きます。

- FH6本体のゲームアセットとGameSaveのペイントを読み取り専用で読み、パソコンの中でWebGL2で描画します。GameSaveやゲームのファイルを書き換えることはありません。
- 窓は1つを使い回し、次のペイントも同じ窓で開きます。同じ車のペイントは約1秒で切り替わります。
- 初めて表示する車の準備の結果を、レポートの出力先の中の `preview-cache`（既定は `%USERPROFILE%\Documents\Livery-Organizer-for-FH6\preview-cache`）に残し、2回目から速く開きます。
- 窓を閉じた後も10分間は裏で待機し、次の表示を速くします。Organizerの起動時にも、窓を出さずにViewerを準備しておきます（Viewerの設定画面の「Organizerの起動時に3Dプレビューを準備しておく」で切り替えられます）。
- 表示はゲーム内の見た目と完全には一致しません。

### 画像の保存

プレビュー画面から、現在の視点の画像と、6方向をまとめた画像を JPEG / PNG で保存できます。画像の下には、タイトル・作成者・アップロード日・撮影日時を入れます。「デモ用保護」の「タイトル・作成者を隠す」で、タイトルと作成者を伏せられます。

### 操作の整理

よく使う操作（表示をリセット・自動回転・画像の保存）は常に表示し、次の4つは折りたたみにまとめました（最初は閉じています）。

- 車体・部品（ボディキット・部品・ホイール）
- 表示の調整
- デモ用保護
- 詳しい設定・診断

### GameDB と three.js

- 利用者がローカルに用意したFH6のGameDBがあれば、ゲームのロゴのステッカーの画像と、ホイールとタイヤの位置・寸法・種類に使います。GameDBは配布物に含めません。
- GameDBが無いときは、ゲームのロゴのステッカーを省き、ホイールとタイヤを簡易の形で表示し、画面に注意を出します。
- 初めて3Dプレビューを開くときに、three.js を npm の公式配布から取得し、照合値を確かめてから使います。

### `preview-cache` の大きさ

`preview-cache` が増えすぎないように、ペイントの準備は最近の3件だけ残し、最近使った3台のほかの車の車体の形は消して、次に開くときに作り直します。古い版のViewerが作った物も消します。大きさの上限は、任意で `preview-settings.json` の `vehicle_cache_limit_gb`（GB）に決められます。

## 3つのツールの共通化

### 版の番号

この版から、Livery Organizer for FH6・Livery Viewer for FH6・Navigator Bridge for FH6 の3つを同じ版の番号で公開します。これからも3つを一緒に上げます（直しだけの版は v0.5.1、機能を足した版は v0.6.0 のように上げます）。

Organizerは v0.4.62 の次を、Navigator Bridgeは v0.0.28 の次を v0.5.0 としました。

### 連携の登録・解除

Organizerに「連携の登録・解除」を追加しました。Livery Viewer for FH6 と Navigator Bridge for FH6 のOrganizer連携を、まとめて登録・解除できます。今の登録が、このOrganizerと同じ配布の物かどうかも確かめられます。それぞれの画面の登録も、そのまま使えます。

### 設定と画面

- 言語・表示テーマ（システム設定 / ライト / ダーク）・FH6本体とGameSaveのフォルダー等を、3つのツールで共有します（`%APPDATA%\Livery-Organizer-for-FH6\desktop-suite-settings.json`）。
- OrganizerとNavigator Bridgeの画面を、Viewerと同じ配色・文字・余白にそろえました。
- 3つのツールの画面の文字を約2割大きくしました（本文 9 → 11 ポイント）。
- 設定画面を、中身に合わせた大きさで開くようにしました。

## Navigator Bridge for FH6

- 言語と表示テーマの切り替えを追加しました。
- 新しく入れたときの「RET後の待ち時間」の初期値を 800ms から 1000ms にしました。FH6 の更新で、マイデザインを開き直して操作できるようになるまでの時間が延びたためです。保存済みの設定は変わりません。
- FH6候補をタイトル完全一致 + `forzahorizon6.exe` の所有プロセスで確認し、送信直前にも同じ対象を再検証する安全境界と、送るキーは変えていません。

## 車両メタデータ

- 収録車種: **667**
- metadata package revision: **4**
- source updated: **2026-11**
- Generator: **Vehicle DB Generator for FH6 0.6.3**

車両メタデータの更新日を、月の精度（例: `2026-11`）でも扱えるようにしました。車両メタデータについて、起動時の自動通信や強制更新はありません。

## 配布物の構成

```text
Livery-Organizer-for-FH6-v0.5.0-preview/
  Livery-Organizer-for-FH6.exe
  Navigator-Bridge-for-FH6.exe
  Livery-Viewer-for-FH6/
    Livery-Viewer-for-FH6.exe
    （Viewerの動作に必要なファイル）
  README.txt
  README_EN.txt
  NAVIGATOR-BRIDGE-README.txt
  NAVIGATOR-BRIDGE-README_EN.txt
  CHANGELOG.md
  LICENSE.txt
  THIRD-PARTY-NOTICES.txt
```

- 配布ZIP（`Livery-Organizer-for-FH6-v0.5.0-preview.zip`）は、EXEとEXEの動作に必要なファイルだけを含みます。Python版（`python` フォルダー）は含めません。
- Livery Viewer for FH6 はフォルダーの形です。`Livery-Viewer-for-FH6` フォルダーごと使ってください。計算を速くする自前の部品 `lo4fh6_native.dll`（Rust）を含みます。
- 同梱する第三者の部品とライセンスは `THIRD-PARTY-NOTICES.txt` に載せています。
- ソースコード（Python・Rust）は、GitHubのリポジトリで公開しています。

Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、通常の配布物には含めていません。

## 更新するときの注意

- 新しいフォルダーから使う場合は、新しいOrganizerの「連携の登録・解除」で「まとめて登録」を実行してください。Organizer連携の登録には、EXEの絶対パスが保存されるためです。
- v0.4.62の配布ZIPの `python\navigator-bridge-for-fh6-v028.py` でBridgeを登録していた場合も、「まとめて登録」でやり直してください。

## ソースから動かす場合

Livery Viewer for FH6 のソース（`src/viewer`）も公開しています。uv と Python 3.12 を使い、`start-viewer-gui.cmd`（黒い窓を出さない場合は `start-viewer-gui-quiet.vbs`）で設定画面を開きます。ソースには速くする部品（DLL）が無く、同じ計算をPythonで行うため、表示までの時間は長くなります。

## 注意

本リリースはPreviewです。FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理と3D表示の一部は実データの観測に基づいています。

Livery Viewer for FH6 は、利用者のパソコンにあるFH6本体のゲームアセットを読み取り専用で使って表示します。ゲームアセットやGameDBを配布物に含めることはありません。

Livery Organizer for FH6 / Livery Viewer for FH6 / Navigator Bridge for FH6 は非公式・非営利のファンメイドツールです。Microsoft、Xbox、Turn 10 Studios、Playground Games、Forzaとの提携・承認・後援を受けた公式ソフトウェアではありません。
