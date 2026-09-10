# Livery Organizer for FH6 v0.4.61 Preview — Release Notes

公開日: 2026-09-11

Livery Organizer for FH6 v0.4.61 Previewでは、日常的な整理作業で使う作成者情報とバックアップ機能を強化し、FH6 Series 5に合わせて同梱車両メタデータを更新しました。

任意の補助ツール **Navigator Bridge for FH6** は **v0.0.28** へ更新し、移動キーの送信先確認をタイトル + プロセス + 対象HWNDの再検証へ強化しています。

## 作成者カラーを一覧で管理

カード上で設定できる作成者カラーを「その他の操作」から一覧管理できるようになりました。

- 現在のレポートにいる作成者と、保存済みだが現在はいない作成者を一覧表示
- 作成者名検索
- 「設定済みのみ」で絞り込み
- 8色から変更、またはカラー解除
- ダークテーマでも色を識別しやすいよう表示を調整

作成者カラーはユーザーデータとして保存され、バックアップ / 復元にも含まれます。

## 作成者アップロード日をカード表示・ソート

FH6「マイデザイン」に表示される作成者アップロード日を、通常のカードでも `DD/MM/YYYY` 形式で確認できるようにしました。

並び順には次の2項目を追加しています。

- アップロード日:新しい順
- アップロード日:古い順

日付を取得できないカードは、どちらの並び順でも末尾に配置します。同じ日付の場合も取得日時などを使って順序を安定させています。

また、作成者カラー表示を含む通常カードで、作成者名の先頭位置を取得日時・バイナル数などの値と揃えました。FH6実スロット / 位置番号もクリック可能な操作対象として分かりやすくしています。

## レポート外のユーザーデータも復元・再バックアップ

過去のHTMLから保存したユーザーデータを新しいHTMLへ復元するとき、現在のレポートに存在しないペイントの整理情報も保持できるようになりました。

復元したレポート外データはlocalStorageに残るだけでなく、その後に作成するユーザーデータバックアップにも含まれます。このため、一時的に現在のGameSave / レポートから外れているペイントの整理状態・タグ・メモ等を次のレポートへ引き継げます。

完全置換で復元する場合は、現行・旧namespaceの既存ユーザーデータを整理してからバックアップ内容を復元します。

## Series 5車両メタデータ

同梱する `fh6-vehicle-metadata.json` を、FH6公式車種リストの **2026-09-08更新（Series 5 / Car Pass additions）** に合わせて更新しました。

- 収録車種: **636 → 647**
- metadata package revision: **2**
- source updated: **2026-09-08**
- Generator: **Vehicle DB Generator for FH6 v0.6.2**

Car ID `3735` のFH6ゲーム内表示名を `2022 Subaru BRZS` とする既存の補正は継続します。

起動時の自動通信や強制更新はありません。任意の更新確認、SHA-256 / manifest検証、検証済みcache利用、失敗時の同梱データ利用というv0.4.60の仕組みを継続します。

## Navigator Bridge for FH6 v0.0.28

Bridgeのキー送信先判定をさらに安全側へ強化しました。

FH6候補として扱うには、次の両方が必要です。

1. 前後の通常スペースを除いたウィンドウタイトルが `Forza Horizon 6` と完全一致する
2. そのウィンドウの所有プロセスが `forzahorizon6.exe` である

条件を満たす候補が複数ある場合、Bridgeは任意の1つを自動選択せず停止します。

通常の位置移動で送信する左 / 右 / 下キーは、**1回送信するごとに**同じ対象HWNDが現在も前面・タイトル完全一致・FH6プロセス所有であることを確認します。移動途中で別アプリへフォーカスを切り替えた場合は、次の移動キーを送る前に停止します。

送信可能な通常移動キーが左 / 右 / 下だけであること、任意設定の初期位置リセットだけが固定 `Esc → Return` を使うこと、FH6のGameSave・ゲームファイル・ゲームメモリを書き換えないことは従来どおりです。

## テスト / 保守

- 古いOrganizer versionを直接assertするテストが残らないよう監査範囲を拡張
- リリース時のOrganizer versionと `pyproject.toml` のversion一致をテスト
- Python版配布物の一覧へ `vehicle_metadata_update.py`、metadata、manifestを明記

## 配布予定構成

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

Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、通常の配布物には含めていません。

## 注意

本リリースはPreviewです。FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理の一部は実データの観測に基づいています。

Livery Organizer for FH6 / Navigator Bridge for FH6 は非公式・非営利のファンメイドツールです。Microsoft、Xbox、Turn 10 Studios、Playground Games、Forzaとの提携・承認・後援を受けた公式ソフトウェアではありません。
