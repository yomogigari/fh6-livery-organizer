# Livery Organizer for FH6

**English:** [README_EN.md](README_EN.md)

**Livery Organizer for FH6** は、PC版 **Forza Horizon 6** でダウンロードしたペイント（Livery）を、ローカル環境で一覧化・検索・整理するためのWindows向けツールです。

GameSaveから取得した情報をもとに、サムネイル付きのHTMLレポートとExcelを生成します。生成されたHTMLでは、検索・絞り込み・並び替え・整理状態・タグ・メモ・バックアップなどを利用できます。

このリポジトリと配布物には、次の3つのツールが入っています。

| ツール | 役割 |
| --- | --- |
| **Livery Organizer for FH6**（本体） | ダウンロード済みペイントを一覧化・検索・整理し、HTML / Excelのレポートを生成します。 |
| **Livery Viewer for FH6**（任意・実験的） | レポートのペイントを、FH6の車体に貼った3Dで表示します。v0.4.63から同梱しました。 |
| **Navigator Bridge for FH6**（任意） | Organizerで選んだペイントの位置まで、FH6「マイデザイン」のカーソルを移動します。 |

**v0.4.63 Preview**（公開日 YYYY-MM-DD：公開時に記入）では、3Dプレビューの **Livery Viewer for FH6** を同梱しました。Organizerのレポートの各カードから、そのペイントを車体に貼った3D表示を開けます。あわせて、3つのツールの設定と見た目をそろえ、配布ZIPをEXEとEXEの動作に必要なファイルだけにしました。

> [!IMPORTANT]
> 本リリースはプレビュー版です。FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理の一部は実データの観測に基づいています。Livery Viewer for FH6 の3D表示は実験的な機能で、ゲーム内の見た目と完全には一致しません。

## v0.4.63 Previewの主な更新

### Livery Viewer for FH6（3Dプレビュー・実験的）を同梱

Organizerのレポートの各カードに「3Dプレビュー（実験）」を追加しました。クリックすると、Livery Viewer for FH6 の窓に、そのペイントを貼った車が表示されます。

- FH6本体のゲームアセットとGameSaveのペイントを読み取り専用で読み、パソコンの中でWebGL2で描画します。
- 同じ車の別のペイントへの切り替えは、開いている窓の中で行います（開発用のPCで約1秒）。
- 初めて表示する車の準備には時間がかかります（開発用のPCで10～20秒ほど）。準備の結果を `preview-cache` に残すので、同じ車の2回目からは速くなります。
- 窓を閉じた後も、次に開くときに速いよう、10分間は裏で待機します（窓は表示しません）。
- ゲームのロゴのステッカーを使うペイントの表示には、利用者がローカルに用意したFH6のGameDBが必要です（配布物には含めません）。

### 3つのツールの共通化

Organizer・Viewer・Navigator Bridgeで、言語・表示テーマ（システム設定 / ライト / ダーク）・FH6本体とGameSaveのフォルダーなどの設定を共有し、同じ配色・文字・余白の画面にそろえました。Navigator Bridgeにも、言語と表示テーマの切り替えを追加しました。

### 配布物

配布ZIPには、EXEとEXEの動作に必要なファイルだけを含めます。前の版まで同梱していたPython版（`python` フォルダー）は含めません。ソースコード（Python・Rust）は、このリポジトリで公開しています。同梱する第三者の部品とそのライセンスは、ZIPの `THIRD-PARTY-NOTICES.txt` にまとめました。

Navigator Bridge for FH6 は **v0.0.29** です。同梱車両メタデータは **2026-11更新 / 667車種 / package revision 4** へ更新しました。

詳しい変更内容は [docs/releases/CHANGELOG.md](docs/releases/CHANGELOG.md) を参照してください。

## 特徴

- ダウンロード済みペイントを車種ごとに一覧化
- FH6本体のゲームアセットから車名・メーカー・年式等を可能な範囲で取得
- サムネイルを埋め込んだローカルHTMLレポート
- サムネイル付きExcel出力
- 車種・メーカー・作成者・年式などによる検索、絞り込み、並び替え
- レポートの各カードから、ペイントを車体に貼った3D表示（Livery Viewer for FH6・実験的）
- Organizer GUI / Viewer / Navigator Bridge / 生成HTML / Excelの日本語・英語表示
- 3つのツールで共有する言語・表示テーマ（システム設定 / ライト / ダーク）・フォルダーの設定
- `/` で検索欄へ移動、`?` でヘルプを開くキーボードショートカット
- 大規模レポート向けに軽量化したライブ検索
- FH6「マイデザイン」順での表示
- 実スロット番号と `#列U / D` によるFH6上の位置表示
- 「残す / 削除候補 / 未決定」の整理状態
- お気に入り、後で確認、タグ、メモ
- 作成者カラーの設定と一覧管理
- 作成者アップロード日の表示と新しい順 / 古い順ソート
- 類似サムネイル候補の確認
- 再ダウンロード重複ペイントの比較・整理
- 比較画面からの整理状態変更と「FH6で削除済み（仮）」反映
- 車種ごとの整理進捗
- 「FH6で削除済み（仮）」による一時非表示、検索・復元、位置再計算
- `C_livery` の構造を5項目で確認する作成方法監査スコアと高い順 / 低い順ソート
- Undo / Redo
- ユーザーデータ、判定状態のバックアップと復元（現在のレポート外データも保持）
- CSV出力
- ブラウザ内の動作診断
- 任意の **Navigator Bridge for FH6** との連携

作成方法監査スコアは、保存済み `C_livery` の形状・色・変形値などから5項目の統計的特徴を確認し、一致した項目数を `0/5`～`5/5` で表示するものです。作成方法の判定結果、自動生成の確率や信頼度、ペイント品質、作者を評価する値ではありません。

## Livery Viewer for FH6

**Livery Viewer for FH6** は、Organizerのレポートのペイントを、FH6の車体に貼って3Dで表示する実験的なツールです。FH6本体のゲームアセットと、GameSaveのペイント（`Livery_*` フォルダー）を読み取り専用で読み、パソコンの中で描画します（WebGL2）。

1. `Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe` を起動し、設定画面で **「Organizer連携を登録」** を一度実行します。
2. Organizerでレポートを生成します。FH6本体のインストール先を確認できたレポートでは、各カードに「3Dプレビュー（実験）」が表示されます。
3. 「3Dプレビュー（実験）」をクリックすると、Viewerの窓にそのペイントを貼った車が表示されます。別のペイントをクリックすると、同じ窓で表示が切り替わります。

Viewerの設定画面から、`Livery_*` フォルダーを選んで開くこともできます。プレビュー画面からは、表示中の視点や6方向の画像をJPEG / PNGで保存できます。

Windowsへの連携登録には、Viewerの**絶対パス**が保存されます。Viewerのフォルダーを移動した場合は、移動後のViewerから「Organizer連携を登録」をもう一度実行してください。Viewerを削除する場合は、先に設定画面の「連携登録を解除」を実行してください。

初回の起動では、3D表示に使う three.js（MIT License）を、npmの公式配布から取得します（インターネットへの接続が必要です）。取得したファイルは照合値を確かめてから使い、次回からは再利用します。

### GameDB

ゲームのロゴのステッカーを使うペイントを表示するには、FH6のGameDB（復号済みのSQLite）が必要です。ロゴのステッカーを使わないペイントは、GameDBが無くても表示できます。

GameDBは配布物にもリポジトリにも含めません。Organizer・ViewerがGameDBを作成・復号・コピー・変更することもありません。利用者がローカルに用意したGameDBを次の場所に置いた場合だけ、読み取り専用で使用します。

```text
%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite
```

詳しくは [docs/3D-PREVIEW-GAMEDB.md](docs/3D-PREVIEW-GAMEDB.md) を参照してください。

## Navigator Bridge for FH6

**Navigator Bridge for FH6 v0.0.29** は、Livery Organizer for FH6で選んだペイント位置へ、FH6本体の「マイデザイン」画面上のカーソルを移動するための任意の補助ツールです。

Organizerでは、各ペイントに次のような現在位置を表示します。

```text
#603 / #302U
```

`#603` は現在の実スロット通し番号、`#302U` はFH6「マイデザイン」の302列目・上段（U）を表します。

番号を移動対象として選択し、`F` キーまたは「FH6で選択デザインへ移動」を実行すると、OrganizerからNavigator Bridgeへ移動先を渡します。

Navigator Bridgeは、FH6「マイデザイン」の `#001U` を起点として必要な `左 / 右 / 下` のカーソル操作を計算し、FH6を前面化したうえで、設定された間隔でWindowsの標準入力APIからキー入力します。

主な用途は次の2つです。

1. Organizerで使いたいダウンロード済みペイントを先に探し、FH6上の該当位置へ移動して、利用者が「デザインを読み込み」を実行する
2. Organizerで整理対象を選び、FH6上で利用者が確認・削除した後、「FH6で削除済み（仮）」へ反映して残りの位置を再計算し、次の整理対象へ進む

Navigator Bridgeは任意機能です。Organizer単体でも一覧化・検索・整理・CSV / Excel出力などを利用できます。

### Organizer連携の登録

Navigator Bridgeを初めて使用するときは、Bridgeを単独起動し、**「連携を登録」** を一度実行します。

BridgeのGUIには次の情報を表示します。

```text
実行形式: Windows EXE
連携登録先: C:\...\Navigator-Bridge-for-FH6.exe
```

Windowsの連携登録にはBridge本体の**絶対パス**が保存されます。

そのため、次の場合は変更後のBridgeから「連携を登録」を再実行してください。

- Bridgeを別フォルダへ移動した
- Bridge本体のファイル名を変更した
- EXEとソースからの実行（Python）を切り替えた

移動前に「解除」を行う必要はありません。変更後のBridgeから再登録すると、新しい場所へ登録が上書きされます。

同じフォルダ・同じファイル名のEXEを新しいバージョンで上書きしただけの場合は、通常は再登録不要です。

詳しい仕様と操作方法は、[docs/releases/NAVIGATOR-BRIDGE-README.txt](docs/releases/NAVIGATOR-BRIDGE-README.txt) を参照してください。

## 安全性

### Livery Organizer for FH6 / Livery Viewer for FH6

Livery Organizer for FH6 と Livery Viewer for FH6 は、**FH6のGameSaveとFH6本体のゲームアセットを読み取り専用で扱います**。

解析元に対して、書き込み・削除・移動・リネーム・上書きは行いません。レポートの出力先としてGameSave配下を指定することもできません。

HTML上の「削除候補」や「FH6で削除済み（仮）」は、Organizer内で整理するための状態です。GameSave内のファイルを削除する機能ではありません。

設定ファイル、キャッシュ、生成レポート、Viewerの準備の結果は、GameSave外へ保存されます。

Organizer / Viewer / Navigator Bridgeのいずれにも、利用者のLiveryデータを外部サーバーへ送信するためのネットワーク機能はありません。Livery Viewer for FH6 が外部へ接続するのは、初回に three.js をnpmの公式配布（`registry.npmjs.org`）から取得するときだけです。

### Navigator Bridge for FH6

Navigator Bridgeは、FH6のGameSave・ゲームファイル・ゲームメモリを書き換えません。

Bridgeが行うのは、FH6ウィンドウを検出して前面化し、FH6「マイデザイン」内の指定位置まで移動するためのカーソルキーをWindowsの標準入力APIから送信することです。

現在のBridgeは、前後の通常スペースを除いたウィンドウタイトルが **`Forza Horizon 6` と完全一致**し、かつそのウィンドウの所有プロセスが **`forzahorizon6.exe`** の場合だけFH6候補として扱います。条件を満たす候補が複数ある場合は自動選択せず停止します。通常の左 / 右 / 下キーは1回送信するごとに、同じ対象ウィンドウが現在も前面・タイトル完全一致・FH6プロセス所有であることを再確認し、条件を満たさなくなった時点で次の移動キーを送信しません。

次の操作は自動化しません。

- 「デザインを読み込み」
- ペイントの選択
- ペイントの削除
- 確定操作

FH6画面の画像認識や解析、ゲーム内部の現在カーソル位置の読み取りも行いません。最終的な確認・読み込み・削除・確定操作は利用者自身がFH6上で行います。

## 配布版

GitHub Releasesでは、EXEとEXEの動作に必要なファイル、日本語 / 英語のドキュメントをまとめたZIPを配布します。

```text
Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
Livery-Viewer-for-FH6\
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

Livery Viewer for FH6 は、`Livery-Viewer-for-FH6` フォルダーの中のファイルを一緒に使います。フォルダーごと置いて使い、EXEだけを別の場所へ取り出さないでください。

Livery Viewer for FH6 と Navigator Bridge for FH6 は任意機能です。使用しない場合は、起動する必要はありません。

配布ZIPには、ソースコードとPython版は含めません。ソースコードは、このリポジトリで公開しています。Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、配布物にもリポジトリにも含めていません。

## このリポジトリの構成

| 場所 | 内容 |
| --- | --- |
| `src/organizer/` | Livery Organizer for FH6（Python） |
| `src/navigator_bridge/` | Navigator Bridge for FH6（Python） |
| `src/viewer/` | Livery Viewer for FH6（Python・JavaScript・Rust） |
| `docs/` | 多言語対応の方針、3DプレビューとGameDB、配布物の文書（`docs/releases/`） |
| `tests/` | テスト |

`src/viewer/tools/livery/native/lo4fh6_native/` は、Viewerの一部の計算を速くする部品のRustのソースです。配布版のViewerには、このソースから作った部品（DLL）を入れています。ソースから動かす場合はこの部品が無く、同じ計算をPythonで行います（時間は長くなります）。

## 言語・ドキュメント

Organizer・Viewer・Navigator Bridgeの利用者向け表示は、現在 **日本語** と **英語** に対応しています。言語と表示テーマは3つのツールで共有し、言語の変更は次回起動時から反映されます。生成HTML / Excelは、レポートを生成した時点のOrganizer言語を使用します。Liveryタイトル、説明、作成者名、車名、タグ、メモなどの利用者データは翻訳しません。

このプロジェクトでは、**日本語を主要ドキュメントの正本、英語を共通の第二言語**として扱います。GitHubではこの `README.md` を日本語の基準文書とし、英語は [README_EN.md](README_EN.md) を参照してください。配布ZIPにも `README_EN.txt` と `NAVIGATOR-BRIDGE-README_EN.txt` を含めます。

英語表示で不自然な表現、誤訳、用語の不統一を見つけた場合は、Issue等でのフィードバックを歓迎します。可能であれば、**`src/organizer/locales/en.py` に対する具体的な変更**またはPull Requestとして提案していただけると助かります。翻訳は意味・既存用語・UIレイアウトなども確認してから反映するため、レビューや反映に時間がかかる場合があります。

今後、日本語・英語以外のUI言語が追加された場合でも、その言語専用のREADME・CHANGELOG・詳細ガイド一式を個別に維持する予定はありません。日本語を読めない場合は、英語ドキュメントを共通参照として利用してください。

開発・翻訳方針の詳細は [docs/I18N.md](docs/I18N.md) / [docs/I18N_EN.md](docs/I18N_EN.md) を参照してください。

## 動作デモ

実際に生成したHTMLの内容を匿名化・ダミー化した動作デモです。

[Livery Organizer for FH6 動作デモ](https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html)

公開デモでは、安全のためNavigator Bridgeの起動とFH6へのキー入力を無効化しています。3Dプレビュー（Livery Viewer for FH6）は、公開デモでは使えません。

## 動作環境

主な対象環境は以下です。

- Windows 11
- PC版 Forza Horizon 6
- 一般的なデスクトップWebブラウザ

Livery Viewer for FH6 には、さらに次が必要です。

- WebGL2を使えるGPU
- Microsoft Edge WebView2 ランタイム（Windows 11には標準で入っています）
- 初回の three.js の取得のためのインターネット接続

開発・動作確認は **Microsoft Store / Xbox App版** を中心に行っています。

**OrganizerについてはSteam版でも利用者から正常動作の報告があります**が、開発側でSteam環境を正式に検証したものではありません。環境によってFH6本体やセーブデータの保存先・ファイル構成などが異なる可能性があります。Navigator Bridge・Livery Viewer for FH6 もSteam環境での正式検証は行っていません。Navigator Bridgeの利用には、ウィンドウタイトルが `Forza Horizon 6` と一致し、所有プロセスをFH6本体として確認できる必要があります。

## 使い方

### 配布版（EXE）

- **Organizer**：`Livery-Organizer-for-FH6.exe` を起動します。
- **Livery Viewer for FH6**：`Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe` を起動し、初回は「Organizer連携を登録」を実行します。
- **Navigator Bridge**：`Navigator-Bridge-for-FH6.exe` を起動し、初回は「連携を登録」を実行します。

OrganizerのGUIが起動したら、必要に応じて次の項目を確認して解析を実行します。

- FH6保存領域
- FH6本体のインストール先
- レポート出力先

通常は自動検出されます。

解析前にFH6を完全に終了しておくことを推奨します。

### ソースから動かす

OrganizerとNavigator Bridgeは、Python 3.12以上の標準ライブラリだけで動作します（GUIはTkinter）。このリポジトリのフォルダーで、次のように実行します。

```powershell
python src\organizer\livery-organizer-for-fh6.py
python src\navigator_bridge\navigator-bridge-for-fh6.py
```

uvを使用する場合:

```powershell
uv run src\organizer\livery-organizer-for-fh6.py
uv run src\navigator_bridge\navigator-bridge-for-fh6.py
```

Navigator Bridgeは、`src\navigator_bridge\start-navigator-bridge-quiet.vbs` から黒いウィンドウを出さずに起動することもできます（uvが必要です）。ソースから動かすBridgeをOrganizerから使う場合は、そのBridgeを単独起動して「連携を登録」を行ってください。

Livery Viewer for FH6 は、uvとPython 3.12を使います。`src\viewer\start-viewer-gui.cmd`（黒いウィンドウを出さない場合は `start-viewer-gui-quiet.vbs`）を実行すると、Viewerの設定画面が開きます。初回は、uvが必要なPythonのパッケージ（Pillow・numpy・psutil・pywebview）を取得します。詳しくは [src/viewer/README.md](src/viewer/README.md) を参照してください。

## 生成ファイル

通常モードでは、主に次の2ファイルを生成します。

```text
livery-organizer-for-fh6.html
livery-organizer-for-fh6.xlsx
```

HTMLにはサムネイル画像が埋め込まれるため、通常はHTML単体で閲覧できます。Excelにもサムネイル画像が埋め込まれます。

必要に応じて `data` フォルダーへ解析用JSON / CSVを追加出力できます。

HTML上からユーザーデータ、判定バックアップ、CSVなどを保存する場合は、主に次のファイル名を使用します。

```text
livery-organizer-for-fh6-userdata.json
livery-organizer-for-fh6-decisions-backup.json
livery-organizer-for-fh6-decisions.csv
livery-organizer-for-fh6-decisions-filtered.csv
```

設定・キャッシュの保存場所は、配布物の [README.txt](docs/releases/README.txt) の「設定・キャッシュの保存場所」を参照してください。

## HTMLで保存される整理情報

ペイントに対する以下の情報は、ブラウザの `localStorage` に保存されます。

- 残す / 削除候補 / 未決定
- お気に入り
- 後で確認
- タグ
- メモ
- FH6で削除済み（仮）
- 一部の画面設定

これらはFH6のGameSaveへ書き戻されません。

「FH6で削除済み（仮）」は同じ生成HTML専用の一時情報で、新しくHTMLを生成した場合は引き継ぎません。

重要な整理情報は、HTML内のバックアップ機能で定期的に保存することを推奨します。

## プレビュー版としての注意

FH6の保存データやゲームアセットの内部構造は、本プロジェクトが管理する仕様ではありません。

ゲーム側のアップデート、保存形式や配置の変更、環境差などにより、解析できないデータや誤認識が発生する可能性があります。

Livery Viewer for FH6 の3D表示は、ゲームのファイルから独自に再現したもので、ゲーム内の見た目と完全には一致しません。Xbox版・PC版のゲーム画面と同じであることは確認していません。

Navigator Bridgeも、FH6内部の現在位置を読み取って補正する仕組みではありません。入力の取りこぼし、想定外の画面状態、FH6側の応答遅延などによってカーソル位置がずれる可能性があります。実行前後の位置は利用者自身で確認してください。

不具合を報告する場合は、個人情報や実際のGameSaveファイルそのものを公開しないよう注意してください。

## 非公式プロジェクト

本プロジェクトは、非公式・非営利のファンメイドツールです。

Microsoft、Xbox、Turn 10 Studios、Playground Games、Forzaとの提携・承認・後援を受けた公式ソフトウェアではありません。

ゲームの進行、競争、経済、ランキング等の自動化を目的としたツールではありません。

製品名、サービス名、商標その他の権利は、それぞれの権利者に帰属します。

利用にあたっては、利用者自身の責任で適用される規約等を確認してください。

## License

Copyright (c) 2026 Yomogigari

作者: [Yomogigari](https://x.com/Yomogigari)

このプロジェクトは [MIT License](LICENSE) の下で公開します。

MIT Licenseは、著作権表示とライセンス表示を保持することを条件に、利用・複製・改変・配布などを広く認めるパーミッシブなライセンスです。

配布版のZIPに同梱する第三者の部品とそのライセンスは、ZIPの `THIRD-PARTY-NOTICES.txt` を参照してください。

### 無保証・免責

本ソフトウェアは無保証で提供されます。

**適用法令で認められる最大限の範囲において、作者は、本ソフトウェアの使用または使用不能から生じた直接・間接の損害、データ損失、利益損失、その他一切の請求・損害・責任を負いません。**

正式な条件は [`LICENSE`](LICENSE) のMIT License本文を参照してください。

---

© 2026 [Yomogigari](https://x.com/Yomogigari)
