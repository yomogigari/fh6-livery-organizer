# Livery Organizer for FH6

**Livery Organizer for FH6** は、PC版 **Forza Horizon 6** でダウンロードしたペイント（Livery）を、ローカル環境で一覧化・検索・整理するためのWindows向けツールです。

GameSaveから取得した情報をもとに、サムネイル付きのHTMLレポートとExcelを生成します。生成されたHTMLでは、検索・絞り込み・並び替え・整理状態・タグ・メモ・バックアップなどを利用できます。

**v0.4.58 Preview** では、Organizerで見つけたペイントに対応するFH6「マイデザイン」上の位置へカーソルを移動する、任意の補助ツール **Navigator Bridge for FH6 v0.0.26** を初めて同梱しました。

> [!IMPORTANT]
> 本リリースはプレビュー版です。FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理の一部は実データの観測に基づいています。

## 特徴

- ダウンロード済みペイントを車種ごとに一覧化
- FH6本体のゲームアセットから車名・メーカー・年式等を可能な範囲で取得
- サムネイルを埋め込んだローカルHTMLレポート
- サムネイル付きExcel出力
- 車種・メーカー・作成者・年式などによる検索、絞り込み、並び替え
- FH6「マイデザイン」順での表示
- 実スロット番号と `#列U / D` によるFH6上の位置表示
- 「残す / 削除候補 / 未決定」の整理状態
- お気に入り、後で確認、タグ、メモ
- 類似サムネイル候補の確認
- 再ダウンロード重複ペイントの比較・整理
- 車種ごとの整理進捗
- 「FH6で削除済み（仮）」による一時非表示と位置再計算
- Undo / Redo
- ユーザーデータ、判定状態のバックアップと復元
- CSV出力
- ブラウザ内の動作診断
- Python標準ライブラリのみで動作するPython版
- 任意の **Navigator Bridge for FH6** との連携

## Navigator Bridge for FH6

**Navigator Bridge for FH6 v0.0.26** は、Livery Organizer for FH6で選んだペイント位置へ、FH6本体の「マイデザイン」画面上のカーソルを移動するための任意の補助ツールです。

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
- EXE版からPython版、またはPython版からEXE版へ切り替えた

移動前に「解除」を行う必要はありません。変更後のBridgeから再登録すると、新しい場所へ登録が上書きされます。

同じフォルダ・同じファイル名のEXEを新しいバージョンで上書きしただけの場合は、通常は再登録不要です。

## 安全性

### Livery Organizer for FH6

Livery Organizer for FH6 は、**FH6のGameSaveとFH6本体のゲームアセットを読み取り専用で扱います**。

解析元に対して、書き込み・削除・移動・リネーム・上書きは行いません。レポートの出力先としてGameSave配下を指定することもできません。

HTML上の「削除候補」や「FH6で削除済み（仮）」は、Organizer内で整理するための状態です。GameSave内のファイルを削除する機能ではありません。

設定ファイル、キャッシュ、生成レポートはGameSave外へ保存されます。

### Navigator Bridge for FH6

Navigator Bridgeは、FH6のGameSave・ゲームファイル・ゲームメモリを書き換えません。

Bridgeが行うのは、FH6ウィンドウを検出して前面化し、FH6「マイデザイン」内の指定位置まで移動するためのカーソルキーをWindowsの標準入力APIから送信することです。

次の操作は自動化しません。

- 「デザインを読み込み」
- ペイントの選択
- ペイントの削除
- 確定操作

FH6画面の画像認識や解析、ゲーム内部の現在カーソル位置の読み取りも行いません。最終的な確認・読み込み・削除・確定操作は利用者自身がFH6上で行います。

## 配布版

GitHub Releasesでは、次の7ファイルをまとめたZIPを配布します。

```text
Livery-Organizer-for-FH6.exe
livery-organizer-for-fh6-v0458.py
Navigator-Bridge-for-FH6.exe
navigator-bridge-for-fh6-v026.py
README.txt
NAVIGATOR-BRIDGE-README.txt
CHANGELOG.md
```

OrganizerはEXE版とPython版のどちらか一方を選んで利用できます。

Navigator BridgeもEXE版とPython版のどちらか一方を利用します。Navigator Bridgeを使用しない場合は、Bridgeのファイルを起動する必要はありません。

Windows EXEを再現するためのBuild Kitは、通常の配布ZIPには含めず、別ファイルとして提供します。

## 動作デモ

実際に生成したHTMLの内容を匿名化・ダミー化した動作デモです。

[Livery Organizer for FH6 動作デモ](https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html)

公開デモでは、安全のためNavigator Bridgeの起動とFH6へのキー入力を無効化しています。

## 動作環境

主な対象環境は以下です。

- Windows 11
- PC版 Forza Horizon 6
- 一般的なデスクトップWebブラウザ

開発・動作確認は **Microsoft Store / Xbox App版** を中心に行っています。

**Steam版でも利用者から正常動作の報告があります**が、開発側でSteam環境を正式に検証したものではありません。環境によってFH6本体やセーブデータの保存先・ファイル構成などが異なる可能性があります。

Python版はPython標準ライブラリのみを使用し、GUIにはTkinterを使用します。

## 使い方

### Organizer EXE版

```text
Livery-Organizer-for-FH6.exe
```

を起動します。

### Organizer Python版

```powershell
python livery-organizer-for-fh6-v0458.py
```

uvを使用する場合:

```powershell
uv run livery-organizer-for-fh6-v0458.py
```

GUIが起動したら、必要に応じて次の項目を確認して解析を実行します。

- FH6保存領域
- FH6本体のインストール先
- レポート出力先

通常は自動検出されます。

解析前にFH6を完全に終了しておくことを推奨します。

### Navigator Bridge EXE版

```text
Navigator-Bridge-for-FH6.exe
```

を起動し、初回は「連携を登録」を実行します。

### Navigator Bridge Python版

```powershell
python navigator-bridge-for-fh6-v026.py
```

Organizerから利用する場合は、Python版Bridgeを単独起動して「連携を登録」を行ってください。

詳しい仕様と操作方法は、配布ZIP内の `NAVIGATOR-BRIDGE-README.txt` を参照してください。

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

### 無保証・免責

本ソフトウェアは無保証で提供されます。

**適用法令で認められる最大限の範囲において、作者は、本ソフトウェアの使用または使用不能から生じた直接・間接の損害、データ損失、利益損失、その他一切の請求・損害・責任を負いません。**

正式な条件は [`LICENSE`](LICENSE) のMIT License本文を参照してください。

---

© 2026 [Yomogigari](https://x.com/Yomogigari)
