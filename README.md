# Livery Organizer for FH6

**English:** [README_EN.md](README_EN.md)

**Livery Organizer for FH6** は、PC版 **Forza Horizon 6** でダウンロードしたペイント（Livery）を、ローカル環境で一覧化・検索・整理するためのWindows向けツールです。

GameSaveから取得した情報をもとに、サムネイル付きのHTMLレポートとExcelを生成します。生成されたHTMLでは、検索・絞り込み・並び替え・整理状態・タグ・メモ・バックアップなどを利用できます。

**v0.4.61 Preview**（2026-09-11公開）では、作成者カラーの一覧管理、作成者アップロード日のカード表示・新旧順ソート、現在のレポートに含まれないペイントのユーザーデータ復元・再バックアップを追加しました。同梱車両メタデータは2026-09-08更新のFH6公式車種リストへ追随し、647車種を収録しています。任意の補助ツール **Navigator Bridge for FH6 v0.0.28** では、FH6ウィンドウのタイトルに加えて所有プロセスを確認し、各移動キーの送信直前にも対象ウィンドウを再検証します。

> [!IMPORTANT]
> 本リリースはプレビュー版です。FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理の一部は実データの観測に基づいています。

## v0.4.61 Previewの主な更新

作成者ごとに設定した色を一覧で確認・変更できる「作成者カラー管理」を追加しました。カードではFH6に表示される作成者アップロード日を通常の並び順でも確認でき、「アップロード日:新しい順 / 古い順」で並び替えできます。

ユーザーデータのバックアップ / 復元は、現在のHTMLレポートに存在しないペイントの整理情報も保持できるようになりました。過去レポートから復元したデータを、その後のバックアップでも失わずに引き継げます。

同梱車両メタデータはFH6公式車種リストの2026-09-08更新へ追随し、636車種から647車種へ更新しました。メタデータpackage revisionは2です。起動時の自動通信や強制更新は引き続き行いません。

Python版では、Organizer本体に加えて `i18n.py`、`vehicle_metadata_update.py`、`fh6-vehicle-metadata.json`、`fh6-vehicle-metadata-manifest.json`、`locales/` を同じ `python/` フォルダー内に保持してください。

## 特徴

- ダウンロード済みペイントを車種ごとに一覧化
- FH6本体のゲームアセットから車名・メーカー・年式等を可能な範囲で取得
- サムネイルを埋め込んだローカルHTMLレポート
- サムネイル付きExcel出力
- 車種・メーカー・作成者・年式などによる検索、絞り込み、並び替え
- Organizer GUI / 生成HTML / Excelの日本語・英語表示
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
- 車種ごとの整理進捗
- 「FH6で削除済み（仮）」による一時非表示と位置再計算
- Undo / Redo
- ユーザーデータ、判定状態のバックアップと復元（現在のレポート外データも保持）
- CSV出力
- ブラウザ内の動作診断
- Python標準ライブラリのみで動作するPython版
- 任意の **Navigator Bridge for FH6** との連携

## Navigator Bridge for FH6

**Navigator Bridge for FH6 v0.0.28** は、Livery Organizer for FH6で選んだペイント位置へ、FH6本体の「マイデザイン」画面上のカーソルを移動するための任意の補助ツールです。

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

現在のBridgeは、前後の通常スペースを除いたウィンドウタイトルが **`Forza Horizon 6` と完全一致**し、かつそのウィンドウの所有プロセスが **`forzahorizon6.exe`** の場合だけFH6候補として扱います。条件を満たす候補が複数ある場合は自動選択せず停止します。通常の左 / 右 / 下キーは1回送信するごとに、同じ対象ウィンドウが現在も前面・タイトル完全一致・FH6プロセス所有であることを再確認し、条件を満たさなくなった時点で次の移動キーを送信しません。

次の操作は自動化しません。

- 「デザインを読み込み」
- ペイントの選択
- ペイントの削除
- 確定操作

FH6画面の画像認識や解析、ゲーム内部の現在カーソル位置の読み取りも行いません。最終的な確認・読み込み・削除・確定操作は利用者自身がFH6上で行います。

## 配布版

GitHub Releasesでは、EXE版・Python版・日本語/英語ドキュメントをまとめたZIPを配布します。

```text
Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
python/
  livery-organizer-for-fh6-v0461.py
  i18n.py
  vehicle_metadata_update.py
  fh6-vehicle-metadata.json
  fh6-vehicle-metadata-manifest.json
  navigator-bridge-for-fh6-v028.py
  locales/
    __init__.py
    ja.py
    en.py
```

OrganizerはEXE版とPython版のどちらか一方を選んで利用できます。Python版Organizerは多言語リソースを使用するため、`python` フォルダー内の `i18n.py` と `locales` フォルダーを削除・移動せず、そのままの構成で使用してください。

Navigator BridgeもEXE版とPython版のどちらか一方を利用します。Navigator Bridgeを使用しない場合は、Bridgeのファイルを起動する必要はありません。

Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、通常の配布物には含めていません。

## 言語・ドキュメント

Organizerの利用者向け表示は、現在 **日本語** と **英語** に対応しています。言語設定は `settings.json` に保存され、変更は次回起動時から反映されます。生成HTML / Excelは、レポートを生成した時点のOrganizer言語を使用します。Liveryタイトル、説明、作成者名、車名、タグ、メモなどの利用者データは翻訳しません。

このプロジェクトでは、**日本語を主要ドキュメントの正本、英語を共通の第二言語**として扱います。GitHubではこの `README.md` を日本語の基準文書とし、英語は [README_EN.md](README_EN.md) を参照してください。配布ZIPにも `README_EN.txt` と `NAVIGATOR-BRIDGE-README_EN.txt` を含めます。

英語表示で不自然な表現、誤訳、用語の不統一を見つけた場合は、Issue等でのフィードバックを歓迎します。可能であれば、**`src/organizer/locales/en.py` に対する具体的な変更**またはPull Requestとして提案していただけると助かります。翻訳は意味・既存用語・UIレイアウトなども確認してから反映するため、レビューや反映に時間がかかる場合があります。

今後、日本語・英語以外のUI言語が追加された場合でも、その言語専用のREADME・CHANGELOG・詳細ガイド一式を個別に維持する予定はありません。日本語を読めない場合は、英語ドキュメントを共通参照として利用してください。

開発・翻訳方針の詳細は [docs/I18N.md](docs/I18N.md) / [docs/I18N_EN.md](docs/I18N_EN.md) を参照してください。

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

**OrganizerについてはSteam版でも利用者から正常動作の報告があります**が、開発側でSteam環境を正式に検証したものではありません。環境によってFH6本体やセーブデータの保存先・ファイル構成などが異なる可能性があります。Navigator BridgeもSteam環境での正式検証は行っておらず、利用にはウィンドウタイトルが `Forza Horizon 6` と一致し、所有プロセスをFH6本体として確認できる必要があります。

Python版はPython標準ライブラリのみを使用し、GUIにはTkinterを使用します。

## 使い方

### Organizer EXE版

```text
Livery-Organizer-for-FH6.exe
```

を起動します。

### Organizer Python版

配布ZIPを展開したフォルダーで、次のように実行します。

```powershell
python python\livery-organizer-for-fh6-v0461.py
```

uvを使用する場合:

```powershell
uv run python\livery-organizer-for-fh6-v0461.py
```

`python` フォルダー内の `i18n.py` と `locales` フォルダーはOrganizerの日本語/英語表示に必要です。

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
python python\navigator-bridge-for-fh6-v028.py
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
