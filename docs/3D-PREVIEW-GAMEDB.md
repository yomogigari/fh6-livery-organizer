# Livery Viewer for FH6 とGameDB

**Livery Viewer for FH6** は、FH6のGameDB（ゲームのデータベースを復号したSQLiteのファイル）があると、3Dプレビューをより正確に表示できます。GameDBは任意です。無くても3Dプレビューは表示できます。

GameDBは、配布物にもリポジトリにも含めません。Livery Viewer for FH6 と Livery Organizer for FH6 は、GameDBを作成・復号・コピー・変更しません。GameDBの用意の方法は案内していません。用意する場合は、利用者自身の責任で、ゲームの利用規約等を確認してください。

## GameDBで変わるところ

| 部分 | GameDBがあるとき | GameDBが無いとき |
| --- | --- | --- |
| ゲームのロゴのステッカー | GameDBで画像を引いて表示します。 | 省いて表示します。 |
| ホイールとタイヤ | GameDBで、ゲームのホイールとタイヤの位置・寸法・種類を求めて表示します。 | 簡易の形で表示します。 |

- GameDBが無いために省いたり簡易にしたりしたときは、プレビュー画面の上に注意を表示します。
- ゲームに無いステッカー（FH6以外から取り込んだペイントなど）は、GameDBがあっても省き、同じく注意を表示します。
- GameDBの位置が、車体のデータにある位置から大きく外れるときは、ホイールを車体のデータの位置のまま表示します。

GameDBを使うのは3Dプレビューだけです。Organizerの一覧化・検索・整理、HTML / Excelの生成、Navigator Bridgeには必要ありません。

## GameDBを置く場所

用意したGameDBは、次の名前で、次の場所に置いてください。

```text
%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite
```

- GameDBを登録・解除する画面はありません。Viewerの設定画面にも、OrganizerにもGameDBの欄はありません。
- 同じフォルダーに置いた `fh6-gamedb-*.sqlite` の形の名前のファイルも使います。`fh6-gamedb.sqlite` が無い（使えない）ときは、更新日時の新しい物から順に、使える物を使います。
- GameDBは読み取り専用で開きます。書き換えません。
- GameDBを後から置いた場合も、次に3Dプレビューを開くときから使います。

### GameDBを動かしたり消したりしたとき

Organizerは、レポートを作るときにGameDBを探し、見つけた場所をレポートに記録します。レポートから3Dプレビューを開くと、Viewerは記録された場所のGameDBを使います。

そのため、レポートを作った後にGameDBを動かしたり消したりすると、そのレポートからは3Dプレビューを開けません（理由は `%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\preview-bridge.log` に記録されます）。GameDBを動かしたり消したりしたら、Organizerでレポートを作り直してください。

## GameDBを探す順

Viewerは次の順にGameDBを探し、最初に使える物を使います。ドライブ全体を探し回ることはしません。Organizerも、レポートを作るときに2～6の順で探します。

1. 起動のときの指定（Organizerのレポートから開いたときは、レポートに記録された場所）
2. 環境変数 `LO4FH6_GAMEDB`
3. 3つのツールの共有設定 `%APPDATA%\Livery-Organizer-for-FH6\desktop-suite-settings.json` の `paths.gamedb_file`
4. 以前の形の設定 `%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\preview-settings.json` に記録された場所
5. `%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite`
6. 5と同じフォルダーの `fh6-gamedb-*.sqlite`（更新日時の新しい順）

「使える」とは、ファイルがあり、SQLiteのファイルで、必要な車の表がそろっていることです。

- 1と2が使えないとき（ファイルが無い・SQLiteのファイルでない・必要な表が無い）は、エラーで止まります。1は、レポートを作り直すか、指定を直してください。2は、環境変数を直すか、消してください（2が使えないときは、Organizerもレポートに3Dプレビューを付けません）。
- 3～6が使えないときは、飛ばして次を見ます。どれも使えないときは、GameDBが無いときの表示になります。

## ソースから動かす場合

ソースから動かす場合は、`src\viewer\organizer_preview_bridge.py` に次の引数を付けて動かすと、GameDBの場所を登録・解除できます（上の3と4に書きます）。ソースから動かすときの準備は、[src/viewer/README.md](../src/viewer/README.md) を参照してください。

| 引数 | 内容 |
| --- | --- |
| `--remember-database <GameDBのファイル>` | 確かめてから登録します。ファイルの写しは作りません。 |
| `--forget-database` | 登録を外します。GameDBのファイルは消しません。 |
| `--show-database` | 今使うGameDBの場所と、どこで見つけたかを表示します。 |

`--database <GameDBのファイル>` を付けると、その起動だけ、指定したGameDBを使います（上の1）。
