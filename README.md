# FH6 Livery Organizer

**Preview Release — v0.4.53**

FH6 Livery Organizer は、Windows / Xbox App版 **Forza Horizon 6** でダウンロードしたペイント（Livery）を、ローカル環境で一覧化・検索・整理するためのツールです。

GameSaveから取得した情報をもとに、サムネイル付きのHTMLレポートとExcelを生成します。生成されたHTMLでは、検索・絞り込み・並び替え・判定・タグ・メモ・バックアップなどを行えます。

> [!IMPORTANT]
> 本リリースはプレビュー版です。FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理の一部は実データの観測に基づいています。

## 特徴

- ダウンロード済みペイントを車種ごとに一覧化
- FH6本体のゲームアセットから車名・メーカー・年式等を可能な範囲で取得
- サムネイルを埋め込んだローカルHTMLレポート
- サムネイル付きExcel出力
- 車種・メーカー・作成者・年式などによる検索、絞り込み、並び替え
- 「残す / 削除候補 / 未決定」の整理状態
- お気に入り、後で確認、タグ、メモ
- 類似サムネイル候補の確認
- 車種ごとの整理進捗
- Undo / Redo
- ユーザーデータ、判定状態のバックアップと復元
- CSV出力
- ブラウザ内の動作診断
- Python標準ライブラリのみで動作するPython版

## 安全性

FH6 Livery Organizer は、**FH6のGameSaveとFH6本体のゲームアセットを読み取り専用で扱います**。

解析元に対して、書き込み・削除・移動・リネーム・上書きは行いません。レポートの出力先としてGameSave配下を指定することもできません。

HTML上の「削除候補」は、整理のためのラベルです。GameSave内のファイルを削除する機能ではありません。

設定ファイルや生成レポートはGameSave外へ保存されます。

## 配布版

GitHub Releasesでは、次の3ファイルをまとめたZIPを配布する予定です。

```text
FH6-Livery-Organizer.exe
fh6-livery-organizer-v0453.py
README.txt
```

EXE版とPython版は、どちらか一方を選んで利用できます。

EXEを自分でビルドするためのファイルや詳細なビルド手順は、配布ZIPには含めません。

## 動作デモ

実際に作成したHTMLの内容をダミーに変更した動作デモです。

[FH6 Livery Organizer動作デモ](https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html)


## 動作環境

本プログラムは、PC版 Forza Horizon 6 を対象としています。

PC版にはMicrosoft Store版とSteam版がありますが、
本プログラムの開発・動作検証はMicrosoft Store版の環境で行っています。
Steam版では動作確認を行っていません。

Steam版ではFH6本体やセーブデータの保存先・ファイル構成などが
Microsoft Store版と異なる可能性があるため、
本プログラムが正常に動作しない場合があります。

## 使い方

### EXE版

`FH6-Livery-Organizer.exe` を起動します。

### Python版

```powershell
python fh6-livery-organizer-v0453.py
```

uvを使用する場合:

```powershell
uv run fh6-livery-organizer-v0453.py
```

GUIが起動したら、必要に応じてFH6保存領域、FH6本体のインストール先、レポート出力先を確認して解析を実行します。通常は自動検出されます。

解析前にFH6を完全に終了しておくことを推奨します。

## 生成ファイル

通常モードでは、主に次の2ファイルを生成します。

```text
fh6-livery-organizer.html
fh6-liveries.xlsx
```

HTMLにはサムネイル画像が埋め込まれるため、通常はHTML単体で閲覧できます。Excelにもサムネイル画像が埋め込まれます。

必要に応じて、解析用JSON / CSVなどを追加出力するモードもあります。

## HTMLで保存される整理情報

ペイントに対する以下の情報は、ブラウザの `localStorage` に保存されます。

- 残す / 削除候補 / 未決定
- お気に入り
- 後で確認
- タグ
- メモ
- 一部の画面設定

これらはFH6のGameSaveへ書き戻されません。重要な整理情報は、HTML内のバックアップ機能で定期的に保存することを推奨します。

## 対象環境

主な開発・確認対象は以下です。

- Windows 11
- Xbox App版 Forza Horizon 6
- 一般的なデスクトップWebブラウザ

Python版はPython標準ライブラリのみを使用し、GUIにはTkinterを使用します。

## プレビュー版としての注意

FH6の保存データやゲームアセットの内部構造は、本プロジェクトが管理する仕様ではありません。ゲーム側のアップデート、保存形式や配置の変更、環境差などにより、解析できないデータや誤認識が発生する可能性があります。

不具合を報告する場合は、個人情報や実際のGameSaveファイルそのものを公開しないよう注意してください。

## 非公式プロジェクト

本プロジェクトは非公式の個人開発ツールです。ゲームの開発元、販売元、プラットフォーム運営元とは関係ありません。

製品名、サービス名、商標その他の権利は、それぞれの権利者に帰属します。

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
