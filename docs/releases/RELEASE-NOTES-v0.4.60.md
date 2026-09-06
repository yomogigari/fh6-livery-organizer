# Livery Organizer for FH6 v0.4.60 Preview — Release Notes

公開日: 2026-09-06


**English documentation:** [README_EN.md](https://github.com/yomogigari/fh6-livery-organizer/blob/main/README_EN.md)

Livery Organizer for FH6 v0.4.60 Previewでは、車両情報を更新しやすくする仕組みを追加し、生成HTMLの表示密度、FH6移動設定、ダークテーマの視認性を改善しました。

任意の補助ツール **Navigator Bridge for FH6** は今回変更しておらず、公開版 **v0.0.27** を継続します。

## 主な変更

### 車両メタデータを独立したファイルで管理

Organizer内部に固定していた車両名などの補正データを、独立した `fh6-vehicle-metadata.json` として管理する構成へ変更しました。

- Organizer本体コードと車両メタデータを分離
- メタデータと更新情報ファイル（manifest）の形式・内容を検証
- 同梱メタデータを常にオフラインで利用可能
- Organizer起動時には自動でインターネットへ接続しない

### 任意の車両メタデータ更新

車両メタデータの更新確認と取得は、利用者が明示的に実行した場合だけ行います。

- manifestを使って更新の有無を確認
- GUI / CLIから任意に更新確認
- ダウンロードしたファイルの内容とSHA-256を確認してからcacheへ保存
- メタデータとmanifestの組み合わせを確認
- 更新途中の不完全なcacheを残さない形で保存
- 検証済みcacheは次回のOrganizer起動時から利用
- 更新に失敗した場合やcacheが不正な場合は、同梱メタデータを利用

更新は**任意**です。起動時の自動更新や強制更新は行いません。

### FH6ゲーム内表示名の補正

公式車両名とは別に、FH6ゲーム内UIで確認した表示名を反映できるようにしました。

今回の同梱メタデータでは、Car ID `3735` の表示名をFH6ゲーム内表示に合わせて **`2022 Subaru BRZS`** としています。

公式リスト側の `2022 Subaru BRZ` という情報は別に保持し、FH6ゲーム内で確認した表示名の補正と区別して記録します。

### 生成HTMLの表示密度を改善

コンパクト表示、とくに **FH6マイデザイン順** のカード幅と状態表示を見直しました。

- ブラウザ幅をより有効に利用
- FH6マイデザイン順のカードを高密度化
- 実スロット番号 / U・D位置と状態バッジを整理
- 長い作成者名などの収まりを改善
- 小さい画面でも使いやすいよう表示を調整

### FH6移動設定を全ソートで共通化

FH6移動設定を、特定の並び順だけでなく生成HTMLの全ソートで共通して利用できるよう整理しました。

Navigator Bridgeのキー送信方法や安全確認の仕組み自体は変更していません。

### ダークテーマの視認性を改善

ダークテーマで「絞り込み」「FH6移動」などの青い文字が暗く見えやすかったため、文字用のアクセント色を明るくしました。

- ダークテーマの文字アクセント: `#B7C5FF`
- ライトテーマ: 変更なし
- 選択中の青背景: 変更なし

## Navigator Bridge for FH6

今回Navigator Bridge本体には変更を加えていません。

同梱する場合は引き続き **Navigator Bridge for FH6 v0.0.27** を使用します。

通常移動で送信するキーは左 / 右 / 下だけです。FH6がフォアグラウンドであることを確認できない場合はキーを送信しません。GameSave、ゲームファイル、ゲームメモリを書き換えません。

PCやゲーム側の負荷などにより、ごく稀に移動位置が1列ずれる可能性があります。現在の初期設定は開発環境でほぼ安定しているため、今回は動作を変更せず、今後の利用者フィードバックを見ながら必要に応じて再検討します。

## 配布ファイル

通常の配布ZIPは次の構成を予定しています。Python版Organizerでは、車両メタデータ関連ファイルもOrganizer本体と同じ `python/` フォルダー内で使用します。

```text
Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
python/
  livery-organizer-for-fh6-v0460.py
  i18n.py
  vehicle_metadata_update.py
  fh6-vehicle-metadata.json
  fh6-vehicle-metadata-manifest.json
  navigator-bridge-for-fh6-v027.py
  locales/
    __init__.py
    ja.py
    en.py
```

実ファイル数は **16件** です。

Organizer / Navigator BridgeはいずれもEXE版とPython版のどちらか一方を利用できます。Navigator Bridgeは任意機能です。

Python版Organizerを利用する場合は、`i18n.py`、`vehicle_metadata_update.py`、`fh6-vehicle-metadata.json`、`fh6-vehicle-metadata-manifest.json`、`locales/` をOrganizer本体と一緒に保持してください。

Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、通常の配布物には含めていません。

## 動作環境について

開発・確認はMicrosoft Store / Xbox App版を中心に行っています。

OrganizerについてはSteam版でも利用者から正常動作の報告がありますが、開発側でSteam環境を正式に検証したものではありません。Navigator BridgeもSteam環境での正式検証は行っておらず、利用にはFH6ウィンドウタイトルが `Forza Horizon 6` と一致する必要があります。

## プレビュー版について

FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理の一部は実データの観測に基づいています。ゲーム側の更新、保存形式・配置の変更、環境差などにより、将来のバージョンで解析方法や表示内容が変更される可能性があります。

本プロジェクトは非公式・非営利のファンメイドツールであり、Microsoft、Xbox、Turn 10 Studios、Playground Games、Forzaとの提携・承認・後援を受けた公式ソフトウェアではありません。
