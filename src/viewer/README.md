# Livery Viewer for FH6

**Forza Horizon 6 のリバリーを、ご自身のゲームのローカルデータを使って 3D プレビューする非公式ツールです。**
「Livery Organizer for FH6」から起動できるほか、Viewer 単独の GUI からも使えます。

> **配布・動作状況**：このソースは公開準備中です。動作確認はテスト版の段階で、環境によってはすぐに実行できるとは限りません。正式な配布物が公開された場合は、その配布物の手順・ライセンス表記・対応バージョンを優先してください。

## できること

- ご自身の FH6 のローカルデータから、車体・ホイール・タイヤとリバリーを 3D で表示する
- マウス操作で車両を回転・拡大縮小して外観を確認する
- Viewer 単独の GUI、または Livery Organizer for FH6 のレポートから起動する
- プレビュー画面の **「現在視点JPEG」「現在視点PNG」「6方向JPEG」「6方向PNG」** から画像を保存する

車種・ペイント・保存データの状態によって、表示できない要素や未対応の図形があります。変換できない入力は推測で補わず、エラーとして表示します。

## 動作環境

- **Windows 11**（画面の表示に **Microsoft Edge WebView2** を使います）
- **uv** と **Python 3.12**
- **初回起動時のインターネット接続**：次の 2 つを自動で取得します。
  - Python のパッケージ（Pillow・numpy・psutil・pywebview）：`uv` が取得します。
  - 描画ライブラリ Three.js 0.185.1（MIT ライセンス）：npm の公式配布から取得し、7 ファイルの SHA-256 を照合してから
    `%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\dependencies\three-0.185.1` に置きます。
    Three.js はソースのみの配布には含まれません。2 回目以降は、照合済みのファイルを使います。
- **Forza Horizon 6 のご自身のインストール**（`Content` フォルダー）と、プレビューしたい `Livery_<Car ID>_*` フォルダー
- **GameDB（任意）**：復号済みの FH6 GameDB（SQLite）をご自身で用意すると、より正確に表示できます。
  - ゲームのロゴのステッカー：GameDB で画像を引きます。無いときは省いて表示します。
  - ホイールとタイヤ：GameDB でゲームのホイールとタイヤの位置・寸法・種類を求めます。無いときは簡易の形で表示します。
  - GameDB が無いために省いたり簡易にしたりしたときは、プレビュー画面の上に注意を表示します。
  - Viewer は GameDB を作成・復号せず、同梱もしません。用意の方法は案内していません。

ゲーム本体・車両データ・ペイント・GameDB などの原本は、本ツールに同梱していません。ご自身が利用を認められたデータを指定してください。ゲームのファイルやセーブデータは読み取るだけで、書き換えません。

## GUI から 3D プレビューを開く

1. このフォルダー（`src/viewer`）の `start-viewer-gui.cmd` を実行します。Viewer の設定画面が開きます。
2. **「FH6フォルダー」** で、ゲームのインストール先、またはその中の `Content` フォルダーを指定します。
3. **「Livery_* フォルダー」** で、対象のリバリーを指定します。
4. **「3Dプレビューを開く」** を選びます。

初回は、車両データの準備と Three.js の取得に時間がかかります。表示できない場合は、画面のエラーと、下の「問題が起きた場合」のログを確認してください。

## Livery Organizer for FH6 から開く

Organizer のレポートにある 3D プレビューのリンクは、Windows の URI（`liveryorganizerpreviewforfh6:`）で Viewer を起動します。

1. Viewer の設定画面で **「Organizer連携を登録」** を選びます。
   - 初回は、Viewer 専用の Python の環境（`%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\runtime`）を `uv` で作ります。
   - 現在のユーザーのレジストリ（HKCU）に URI を登録します。登録する起動の命令は、その環境の `pythonw.exe`
     （黒い窓を出さない Python）で、**登録を実行した Viewer のフォルダー**の `organizer_preview_bridge.py` を直接起動する
     ものです（Navigator Bridge と同じ形）。
2. Organizer でレポートを作り、3D プレビューのリンクを開きます。

Viewer のフォルダーを移動・コピーした場合は、新しい場所の設定画面からもう一度 **「Organizer連携を登録」** を実行してください。登録を消すには **「連携登録を解除」** を選びます。Viewer 単独で使うだけなら、連携の登録は不要です。

## 画像を保存する

3D プレビューの画面で、次のいずれかを選びます。

- **現在視点JPEG / PNG**：表示中の視点を保存
- **6方向JPEG / PNG**：左・前・右・後・上・下の 6 方向を 1 枚にまとめて保存

保存先を選ぶダイアログが開きます。JPEG は品質 95 で保存します。保存できたかどうかは、保存先のファイルで確認してください。

## Viewer が使うローカルの場所

すべて `%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge` の下です。

| 場所 | 内容 |
| --- | --- |
| `preview-settings.json` | Organizer と共有する設定（GameDB の場所など） |
| `preview-bridge.log` | 起動・変換のログ（UTF-8） |
| `dependencies\three-0.185.1` | 初回起動時に取得・照合した Three.js |
| `runtime` | Organizer 連携の起動に使う Viewer 専用の Python の環境 |

GameDB は、次の順に探します：環境変数 `LO4FH6_GAMEDB` → 共有の設定 `preview-settings.json` →
`%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite`。

## 問題が起きた場合

- **GUI が起動しない**：Windows 11、Microsoft Edge WebView2、`uv`、Python 3.12 を確認してください。`start-viewer-gui.cmd` をコマンドプロンプトから実行すると、エラーを確認できます。
- **初回起動で止まる**：インターネット接続を確認してください（Python パッケージと Three.js の取得）。Three.js の照合に失敗した場合は、取得したファイルを使わずに止まります。
- **車両が表示されない**：FH6 フォルダー・`Livery_*` の指定とエラーを確認し、`preview-bridge.log` を確認してください。
- **Organizer から起動しない**：Viewer を単独で起動できるか確認し、設定画面から連携を登録し直してください。
- **画像を保存できない**：保存先フォルダーへの書き込み権限を確認してください。

不具合を報告するときは、配布バージョン・再現手順・エラーメッセージを添えてください。**ゲームの原本・個人のセーブデータ・非公開のペイントファイルは、公開の場所に添付しないでください。**

## 権利と注意事項

本ツールは非公式のファンメイドツールです。Microsoft、Xbox、Turn 10 Studios、Playground Games とは提携・承認の関係にありません。ゲームに関する名称・商標・データの権利は、それぞれの権利者に帰属します。

第三者コンポーネントは Three.js（MIT ライセンス）だけで、初回起動時に公式配布から取得します。詳しくは `tools/livery-inspector/THIRD_PARTY.md` を参照してください。**このソースが公開されていることは、第三者のファイルやゲームデータの再配布許諾を意味しません。**
