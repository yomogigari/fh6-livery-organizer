# 実験的3DプレビューとGameDB

Livery Organizer for FH6 の実験的3Dプレビューは、利用者がローカルに用意した復号済みFH6 GameDB SQLiteを任意で参照できます。

GameDBは配布物へ同梱しません。OrganizerもGameDBを生成・復号・コピー・変更しません。登録済みGameDBが利用できる場合だけ、Preview Bridgeへローカルパスを引き渡します。GameDBが見つからない場合は、従来の非GameDB経路を維持します。

## 解決順序

GameDBの解決順序は次のとおりです。

1. 呼び出し側が明示したパス
2. `LO4FH6_GAMEDB` 環境変数
3. Preview Bridgeと共有する保存済み設定
4. 利用者のDocuments配下にある安定したgame-data候補

任意ドライブの走査は行いません。候補はSQLiteヘッダーと必要な車両テーブルを読み取り専用で確認してから採用します。

## ホイール配置

GameDBを利用できる場合、Preview Bridge側ではGameDB由来のホイール寸法・配置情報を利用できます。

現在の研究経路では、WheelStyleのidentityを正規化したうえでGameDB配置を適用し、4輪の最大移動量が0.15 mを超える場合はcarbin配置へ戻すguardを使用します。GameDBがない場合や必要な証拠を得られない場合は、推測で大きく移動させません。

## 公開時の境界

- GameDBはリリースZIPへ同梱しません。
- GameDBは3Dプレビューの任意入力であり、Organizerの一覧生成、HTML / Excel、Navigator Bridgeなどの既存機能には必須ではありません。
- GameDBファイルは読み取り専用で扱います。
- 共有設定からGameDBパスを解除しても、GameDBファイル自体は削除しません。
- 個別のペイントを識別できる保存名、タイトル、作者、共有コード、保存時刻などは、この開発文書へ記録しません。
