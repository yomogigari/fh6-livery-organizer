# Livery Organizer for FH6 v0.4.59 Preview — Release Notes — 2026-09-04

**English documentation:** [README_EN.md](https://github.com/yomogigari/fh6-livery-organizer/blob/main/README_EN.md)

Livery Organizer for FH6 v0.4.59 Previewでは、当初予定していた**日本語 / 英語の多言語対応**に加え、実際の利用・検証で見つかった生成HTMLの操作性と検索性能の改善をまとめて反映しました。

任意の補助ツール **Navigator Bridge for FH6 v0.0.27** では、FH6以外のウィンドウを誤認しにくくするため、ウィンドウタイトル判定を安全側へ厳格化しています。

## 主な変更

### 日本語 / 英語表示

Organizerの次の範囲を日本語 / 英語で利用できるようにしました。

- デスクトップGUI
- CLIの主要表示
- 生成HTMLレポート
- Excelレポート
- エラー / 診断 / Help等のOrganizer生成文言

言語設定は `settings.json` に保存され、変更は次回起動時から反映されます。生成HTML / Excelは、レポート生成時点のOrganizer言語を使用します。

Liveryタイトル、説明、作成者名、車名、メーカー、タグ、メモ、各種IDなどの利用者・ゲームデータは翻訳しません。

### 大規模レポートの検索を軽量化

900〜1000件規模の生成HTMLでも検索入力を滑らかに保ちやすくするため、ライブ検索時の処理を見直しました。

- カードごとの静的な検索文字列をページ内で再利用
- タグ・メモ・お気に入り等のユーザーメタデータを検索ごとにlocalStorageから読み直さない
- 検索条件の解析を1更新につき1回へ集約
- 検索文字の変更だけでは不要な全体再ソート・全状態再集計を行わない
- フラット表示では確定済みの並び順を再利用
- 候補件数等の追従処理は入力停止後へ分離

検索・絞り込みの意味そのものは変更していません。

### キーボード操作

生成HTMLへ次のショートカットを追加しました。

- `/` — 検索欄へ移動
- `?` — ヘルプを開く

既存のFH6マイデザインジャンプ、FH6移動、整理用ショートカットも継続します。

### FH6移動対象のUI整理

FH6移動対象の実スロット番号 / FH6位置を一体の操作グループとして扱い、選択状態を分かりやすくしました。同じ対象をもう一度クリックすると解除できます。

### Navigator Bridge for FH6 v0.0.27

FH6ウィンドウ判定を次のように変更しました。

- 前後の通常スペースを除いたタイトルが **`Forza Horizon 6` と完全一致する場合だけ** FH6として扱う
- ゲーム名をタイトルに含むだけのブラウザ、GitHubページ、Organizer、Bridge等は対象外
- キー送信直前にも現在のフォアグラウンドウィンドウを再確認
- 条件を満たさない場合はカーソルキーを送信しない

Bridgeは従来どおりGameSave、ゲームファイル、ゲームメモリを書き換えません。通常移動で送信可能なキーは左 / 右 / 下だけで、`#001Uへ戻す` をONにした場合のみ固定操作 Esc → Return を追加します。ペイントの読み込み・選択・削除・確定は自動化しません。

## 英語ドキュメントと翻訳フィードバック

主要ドキュメントはこれまでどおり**日本語を正本**とし、英語を共通の第二言語として提供します。

GitHub:

- `README.md` — 日本語
- `README_EN.md` — English
- `docs/I18N.md` — 日本語の国際化・翻訳方針
- `docs/I18N_EN.md` — English i18n / translation policy

配布ZIPにも `README_EN.txt` と `NAVIGATOR-BRIDGE-README_EN.txt` を含めます。

英語表示で不自然な表現や誤訳を見つけた場合は、Issue等でのフィードバックを歓迎します。可能であれば、`src/organizer/locales/en.py` に対する具体的な変更またはPull Requestとして提案していただけると助かります。

翻訳は機能の意味、既存用語、UIレイアウト、テストとの整合まで確認するため、レビュー・反映には時間がかかる場合があります。

今後、日本語・英語以外のUI言語が追加されても、その言語専用のREADME / CHANGELOG / Release Notes / Bridge詳細ガイド一式を個別に増やす予定はありません。日本語を読めない場合は英語版を共通参照として利用してください。

## 配布ファイル

通常の配布ZIPは次の構成です。Python版Organizerは多言語リソースを別モジュールとして読み込むため、Python関連ファイルを `python/` フォルダーへまとめています。

```text
Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
python/
  livery-organizer-for-fh6-v0459.py
  i18n.py
  navigator-bridge-for-fh6-v027.py
  locales/
    __init__.py
    ja.py
    en.py
```

Organizer / Navigator BridgeはいずれもEXE版とPython版のどちらか一方を利用できます。Python版Organizerでは `python/i18n.py` と `python/locales/` をOrganizer本体と一緒に保持してください。Navigator Bridgeは任意機能です。

Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、通常の配布物には含めていません。

## 動作環境について

開発・確認はMicrosoft Store / Xbox App版を中心に行っています。

OrganizerについてはSteam版でも利用者から正常動作の報告がありますが、開発側でSteam環境を正式に検証したものではありません。Navigator BridgeもSteam環境での正式検証は行っておらず、利用にはFH6ウィンドウタイトルが `Forza Horizon 6` と一致する必要があります。

## プレビュー版について

FH6の内部データ形式は公式仕様として公開されているものではなく、解析処理の一部は実データの観測に基づいています。ゲーム側の更新、保存形式・配置の変更、環境差などにより、将来のバージョンで解析方法や表示内容が変更される可能性があります。

本プロジェクトは非公式・非営利のファンメイドツールであり、Microsoft、Xbox、Turn 10 Studios、Playground Games、Forzaとの提携・承認・後援を受けた公式ソフトウェアではありません。
