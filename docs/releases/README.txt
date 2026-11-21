Livery Organizer for FH6 v0.4.63 Preview
=========================================

公開日: YYYY-MM-DD（公開時に記入）

Livery Organizer for FH6 は、PC版 Forza Horizon 6 でダウンロードした
ペイント（Livery）を、ローカル環境で一覧化・検索・整理するためのツールです。

この配布物には、次の3つのツールが入っています。

・Livery Organizer for FH6（本体）
  ダウンロード済みペイントを一覧化・検索・整理し、HTML / Excelのレポートを生成します。
・Livery Viewer for FH6（任意・実験的）
  レポートのペイントを、FH6の車体に貼った3Dで表示します。この版から同梱しました。
・Navigator Bridge for FH6（任意）
  Organizerで選んだペイントの位置まで、FH6「マイデザイン」のカーソルを移動します。

このリリースはプレビュー版です。

v0.4.63では、3Dプレビューの Livery Viewer for FH6 を同梱しました。Organizerのレポートの
各カードから、そのペイントを車体に貼った3D表示を開けます。Livery Viewer for FH6 は実験的な機能で、
表示はゲーム内の見た目と完全には一致しません。

3つのツールは、言語・表示テーマ（システム設定 / ライト / ダーク）・FH6本体とGameSaveの
フォルダーなどの設定を共有し、同じ見た目の画面にそろえました。

配布ZIPには、EXEとEXEの動作に必要なファイルだけを含めます。前の版まで同梱していた
Python版（pythonフォルダー）は含めません。ソースコードはGitHubのリポジトリで公開しています。

同梱車両メタデータは、2026-11更新・667車種・package revision 4へ更新しました。


■ 配布ファイル

配布ZIP（Livery-Organizer-for-FH6-v0.4.63-preview.zip）を展開すると、
版の名前のフォルダー（Livery-Organizer-for-FH6-v0.4.63-preview）の中に次のファイルがあります。

Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe（と、同じフォルダーの動作に必要なファイル）
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
LICENSE.txt
THIRD-PARTY-NOTICES.txt

前の版から更新して、新しいフォルダーから使う場合は、新しいOrganizerの「連携の登録・解除」で
「まとめて登録」を実行してください（Viewerの「Organizer連携を登録」とNavigator Bridgeの「連携を登録」を
それぞれ行っても同じです。どちらの登録にも、EXEの絶対パスが保存されるため）。

Livery Viewer for FH6 は、Livery-Viewer-for-FH6 フォルダーの中のファイルを一緒に使います。
フォルダーごと置いて使い、EXEだけを別の場所へ取り出さないでください。

Livery Viewer for FH6 と Navigator Bridge for FH6 は任意機能です。
一覧化・検索・整理・CSV / Excel出力など、Organizer本体の機能だけを使う場合は不要です。

ソースコード（Python・Rust）は、次のGitHubのリポジトリで公開しています。
https://github.com/yomogigari/fh6-livery-organizer
Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、配布物にもリポジトリにも含めていません。


■ 言語 / 表示テーマ / 英語ドキュメント

Organizer・Viewer・Navigator Bridgeの利用者向け表示は、日本語と英語に対応しています。
言語と表示テーマ（システム設定 / ライト / ダーク）は3つのツールで共有します。
言語の変更は、OrganizerとNavigator Bridgeでは次回起動時から、Viewerの設定画面では選んだときに反映されます。
3Dプレビューの画面は、共有の言語の設定ではなく、Windowsの表示言語で始まり（日本語でなければ英語）、
画面の上の「言語」で切り替えられます。3Dプレビューの画面の配色は、暗い色だけです。
生成HTML / Excelは、レポート生成時点のOrganizer言語を使用します。
Liveryタイトル、説明、作成者名、車名、タグ、メモ等の利用者データは翻訳しません。

日本語を主要ドキュメントの正本、英語を共通の第二言語として扱います。
英語の概要は同梱の README_EN.txt、Bridgeの英語詳細は NAVIGATOR-BRIDGE-README_EN.txt を参照してください。

英語表示で不自然な表現や誤訳を見つけた場合は、Issue等でのフィードバックを歓迎します。
可能であれば、GitHubリポジトリの次のファイルに対する具体的な変更、
またはPull Requestとして提案していただけると助かります。
・Organizer：src/organizer/locales/en.py
・Livery Viewer for FH6：src/viewer/viewer_gui.py の中の対訳（設定画面）、
  src/viewer/tools/livery-inspector/locales/en.js（3Dの画面）
・Navigator Bridge：src/navigator_bridge/navigator-bridge-for-fh6.py の中の対訳の表
翻訳は機能の意味、既存用語、UIレイアウト、テスト等も確認してから反映するため、
レビュー・反映には時間がかかる場合があります。

今後、日本語・英語以外のUI言語が追加された場合でも、その言語専用の詳細文書一式を
個別に増やす予定はありません。日本語を読めない場合は英語ドキュメントを共通参照として利用してください。


■ Livery Viewer for FH6 とは

Livery Viewer for FH6 は、Organizerのレポートのペイントを、FH6の車体に貼って3Dで表示する
実験的なツールです。FH6本体のゲームアセットと、GameSaveのペイント（Livery_* フォルダー）を
読み取り専用で読み、パソコンの中で描画します（WebGL2）。

・レポートの各カードの「プレビュー」から、そのペイントを開けます。
・Viewerの設定画面から、Livery_* フォルダーを選んで開くこともできます。
・初めて表示する車は、準備に開発用のPCで約10秒かかります。
  このPCで初めてViewerを開くときは、描画の部品を初めて作るため、15～28秒ほどかかります。
  準備した結果は preview-cache に残すので、同じ車の2回目からは速くなります。
・次のペイントも同じ窓で開きます（同じ車のペイントなら、開発用のPCで約1秒で切り替わります）。
・窓を閉じても、次に開くときに速いよう、10分間は裏で待機します（窓は表示しません）。
  10分たつと終了します。待っている間もメモリーを使い、タスクマネージャーに残って見えます。
・Organizerを起動すると、Viewerを窓を出さずに起動して準備しておくので、最初の3Dプレビューが
  少し速く開きます（開発用のPCで約0.3秒。既定はオン）。Organizerが動いている間はViewerも残り、Organizerを閉じた後は
  上と同じ10分で終わります。Viewerの設定画面のチェック
  「Organizerの起動時に3Dプレビューを準備しておく」で切り替えます。
  Organizer連携を登録していないときは動きません。
・表示はゲーム内の見た目と完全には一致しません。Xbox版・PC版のゲーム画面と同じであることは
  確認していません。

Viewerはペイントを読み取って表示するだけで、GameSaveやFH6本体へ書き込みません。


■ Livery Viewer for FH6 の使い方

1. 配布のフォルダーを使う場所に置いてから、Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe を起動し、
   設定画面で「Organizer連携を登録」を一度実行します。
   Windowsへの登録にはViewerの絶対パスが保存されるので、先に置き場所を決めてください。
   Viewerを別のフォルダーへ移動した場合は、移動後のViewerから「Organizer連携を登録」をもう一度実行してください。
   登録の後は、設定画面を閉じてかまいません。3Dプレビューを開くと、Viewerが自動で起動します。
   Organizerの「連携の登録・解除」で「まとめて登録」を実行すると、ViewerとNavigator Bridgeを
   まとめて登録できます（この手順と同じです）。
2. Organizerでレポートを生成します。
   FH6本体のインストール先を確認できたレポートでは、各カードに「プレビュー」が表示されます。
3. 「プレビュー」をクリックします。
   ブラウザから外部アプリを開く確認が表示された場合は、内容を確認して許可してください。
   OrganizerとViewerのローカル連携には liveryorganizerpreviewforfh6:// を使用します。
4. Viewerの窓に、そのペイントを貼った車が表示されます。
   別のペイントの「プレビュー」をクリックすると、同じ窓で表示が切り替わります。

設定画面から開く場合は、「FH6フォルダー」「Livery_* フォルダー」「preview-cache」を確認して
「3Dプレビューを開く」を実行します。

初めて3Dプレビューを開くときは、3D表示に使う three.js（MIT License）を、npmの公式配布から取得します
（インターネットへの接続が必要です）。取得したファイルは照合値を確かめてから使い、次回からは再利用します。


■ Livery Viewer for FH6 と GameDB

Livery Viewer for FH6 は、FH6のGameDB（ゲームのデータベースを復号したSQLiteのファイル）があると、
より正確に表示できます。GameDBが無くても3D表示はできますが、次の部分が変わります。

・ゲームのロゴのステッカー：GameDBで画像を引きます。無いときは省いて表示します。
・ホイールとタイヤ：GameDBでゲームのホイールとタイヤの位置・寸法・種類を求めます。
  無いときは簡易の形で表示します。
GameDBが無いために省いたり簡易にしたりしたときは、Viewerの画面の上に注意を表示します。

GameDBは配布物に含めません。Organizer・ViewerがGameDBを作成・復号・コピー・変更することもありません。
利用者がローカルに用意したGameDBを、次の場所に置くと、読み取り専用で使用します。

%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite

ほかの場所に置いたときは、Livery Viewer for FH6 の設定画面（Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe を開く）の
「GameDB」の欄で、「参照...」から選びます。使えるかを確かめてから登録し、欄の下に今の状態を表示します
（Organizer も同じ設定を使います）。「設定を外す」で登録を外します（GameDBのファイルは消しません）。

ほかの指定の仕方（環境変数など）は、GitHubのリポジトリの docs/3D-PREVIEW-GAMEDB.md を参照してください。

GameDBの用意の方法は案内していません。用意する場合は、利用者自身の責任で、
ゲームの利用規約等を確認してください。


■ Navigator Bridge for FH6 とは

Navigator Bridgeは、Organizerで選んだ #603 / #302U などの位置番号に対応する
FH6「マイデザイン」上のペイントへ、カーソルを自動で移動するための任意の補助ツールです。

Organizerは選択した移動先と現在の最終実スロット番号、移動設定をBridgeへ渡します。
BridgeはFH6「マイデザイン」の #001U を起点として、指定位置までに必要な
左 / 右 / 下のカーソル操作を計算し、FH6を前面化して、設定された間隔でキー入力します。
左右は、右へ進む経路と左キーで最終列へ循環する経路のうち、入力回数が少ない方を使います。

つまり、#603 / #302U をクリックして F キーまたは「FH6で選択デザインへ移動」を実行すると、
Bridgeが #001U から #302U までのカーソル移動を計算してFH6へ自動入力し、
指定したペイント位置までカーソルを移動します。


FH6標準の「マイデザイン」では、各ペイントについて表示される情報が
「サムネイル / タイトル / 作成者 / 作成者がUPした日付」の4項目に限られます。
ダウンロード済みペイントが増えるほど、目的の車種や使いたいデザインをFH6画面だけから
探し出すのは手間がかかります。

Livery Organizerでは、車種・メーカー・年式・作成者・タイトルなどの情報を使って検索・絞り込み・
並び替えができます。目的のデザインをOrganizer側で特定したあと、その位置をNavigator Bridgeへ
渡してFH6「マイデザイン」の該当位置まで移動し、利用者がFH6の「デザインを読み込み」を実行すれば、
現在運転しているマシンへ目的のペイントを適用できます。

Navigator Bridgeは「デザインを読み込み」の決定操作そのものは行いません。
Bridgeが行うのは対象位置までのカーソル移動で、読み込み・選択・確定は利用者がFH6上で行います。

BridgeはFH6の画面や内部の現在カーソル位置を読み取って追跡する仕組みではありません。
そのため、PCやFH6の負荷によってキー入力が取りこぼされると位置がずれる場合があります。
詳しい仕組み、開始位置、調整方法、安全境界は NAVIGATOR-BRIDGE-README.txt を参照してください。


■ 動作環境

主な対象:
Windows 11
PC版 Forza Horizon 6

Livery Viewer for FH6 には、さらに次が必要です。
・WebGL2を使えるGPU
・Microsoft Edge WebView2 ランタイム（Windows 11には標準で入っています）
・初めて3Dプレビューを開くときの、three.js の取得のためのインターネット接続

開発・動作確認はMicrosoft Store / Xbox App版を中心に行っています。
OrganizerについてはSteam版でも利用者から正常動作の報告がありますが、開発側でSteam環境を
正式に検証したものではありません。Navigator Bridge・Livery Viewer for FH6 もSteam環境での正式検証は行っていません。
Navigator Bridgeの利用にはFH6ウィンドウタイトルが「Forza Horizon 6」と完全一致し、所有プロセスをFH6本体として確認できる必要があります。

ソースコードからPythonで動かす場合の情報は、GitHubのリポジトリを参照してください。


■ Organizerの使い方

Livery-Organizer-for-FH6.exe を起動してください。

GUIが起動したら、必要に応じて以下を確認してから解析を実行します。

・FH6保存領域
・FH6本体のインストール先
・レポート出力先

通常は自動検出されます。
解析前にFH6を完全に終了しておくことを推奨します。


■ 主な出力

通常モードでは、レポート出力先に以下を生成します。

livery-organizer-for-fh6.html
livery-organizer-for-fh6.xlsx

必要に応じて data フォルダーへJSON / CSVの解析データも出力できます。
HTML上からユーザーデータ、判定バックアップ、CSVなどを保存する場合は、
次のファイル名を使用します。

livery-organizer-for-fh6-userdata.json
livery-organizer-for-fh6-decisions-backup.json
livery-organizer-for-fh6-decisions.csv
livery-organizer-for-fh6-decisions-filtered.csv

通常のHTMLではサムネイル画像を埋め込むため、HTML単体で閲覧できます。
Excelにもサムネイル画像を埋め込みます。


■ 主な機能

・車種、メーカー、年式、作成者などによる検索・絞り込み・並び替え
・「残す / 削除候補 / 未決定」による整理
・お気に入り、後で確認、タグ、メモ
・作成者カラーの設定と一覧管理
・作成者アップロード日の表示と新しい順 / 古い順ソート
・車種ごとの整理進捗と未完了車種ナビゲーション
・Undo / Redo
・ユーザーデータと判定状態のバックアップ / 復元（現在のレポート外データも保持）
・CSV出力、サムネイル付きExcel出力
・FH6本体の表示に合わせた「FH6マイデザイン順」表示
・実スロット番号 #001... とFH6位置 #001U / #001D... の表示
・位置番号または車種名によるFH6マイデザイン内ジャンプ
・FH6画面と同じ DD/MM/YYYY 形式の作成者アップロード日
・画像一致 / 同一作者・同名による類似候補の比較
・現在のGameSave内にある再ダウンロード完全一致ペイントの別カード表示
・再DL重複の専用整理画面
・FH6で削除したデザインをOrganizer上で一時的に非表示にし、残りの位置を詰め直す「FH6で削除済み（仮）」
・任意の一覧や比較画面からFH6移動対象を選択
・Fキーまたは「FH6で選択デザインへ移動」でNavigator Bridgeへ移動指示
・Organizerで目的のペイントを探し、Bridgeで該当位置へ移動してFH6の「デザインを読み込み」へつなぐ
・「FH6で削除済み（仮）」とNavigator Bridgeを組み合わせ、FH6「マイデザイン」を連続して整理
・レポートの各カードから、Livery Viewer for FH6 でペイントを3D表示

「再DL重複を整理」「削除候補」「FH6で削除済み（仮）」などのOrganizer内の操作は、
FH6のGameSave内のLiveryファイルを直接削除・変更する機能ではありません。


■ Organizer + Navigator Bridgeで目的のデザインを見つけて適用する

FH6標準の「マイデザイン」で確認できる情報は、
「サムネイル / タイトル / 作成者 / 作成者がUPした日付」の4項目です。
そのため、ダウンロード済みのペイントが増えると、目的の車種に使いたいデザインや、
以前ダウンロードした特定のペイントをFH6画面だけから探し出すのが難しくなります。

Organizerでは、車種・メーカー・年式・作成者・タイトルなどからダウンロード済みペイントを
検索・絞り込み・並び替えできます。そこで目的のデザインを見つけ、カードに表示される
#実スロット / #列U・D をクリックして移動対象に設定します。

1. Organizerで、現在のマシンへ適用したいペイントを検索・絞り込みして見つけます。
2. #603 / #302U などの番号をクリックし、Fキーまたは「FH6で選択デザインへ移動」を実行します。
3. Navigator BridgeがFH6「マイデザイン」の対象位置までカーソルを移動します。
4. FH6上で対象を確認し、利用者が「デザインを読み込み」を実行します。
5. 選んだペイントが現在運転しているマシンへ適用されます。

この使い方により、「FH6の一覧を見ながら目的のペイントを探し続ける」のではなく、
Organizerの検索・整理情報で先に目的のデザインを特定してから、その位置へ移動できます。
ペイントの見た目を車体で確かめたい場合は、移動の前に「プレビュー」で確認することもできます。

Navigator Bridgeはペイントの読み込み・選択・確定操作を自動化しません。
対象位置までのカーソル移動だけを補助し、「デザインを読み込み」は利用者がFH6上で実行します。


■ 「FH6で削除済み（仮）」+ Navigator Bridgeでマイデザインを整理する

「FH6で削除済み（仮）」は、Navigator Bridgeと組み合わせることで特に有効です。
FH6「マイデザイン」から不要なペイントを実際に削除すると、その後ろにあるペイントの
実スロット番号と #302U のようなFH6位置は前へ詰まります。

OrganizerはFH6側で削除されたことを自動では読み取りません。そのため、FH6で削除したあと、
Organizerの「FH6マイデザイン順」で同じデザインを「FH6で削除済み」にすると、そのカードを
一時的に一覧から除外し、残っている全ペイントの #実スロット / #列U・D をすぐに再計算します。

この再計算結果はNavigator Bridgeの次の移動にも使われます。たとえば次のように整理できます。

1. Organizerの削除候補、再DL重複整理、類似比較などから整理したいペイントを選びます。
2. #603 / #302U などの番号をクリックし、Fキーまたは「FH6で選択デザインへ移動」を実行します。
3. Navigator BridgeがFH6「マイデザイン」の対象位置までカーソルを移動します。
4. FH6上でペイントを目視確認し、不要なら利用者自身が削除します。
5. Organizerへ戻り、「FH6マイデザイン順」の該当カードを「FH6で削除済み」にします。
6. Organizerが残りの位置番号を詰め直すので、次に選ぶ #実スロット / #列U・D が現在のFH6と対応します。
7. 次の対象を選び、同じ手順を繰り返します。

これにより、Organizerで「どれを整理するか」を判断し、Navigator BridgeでFH6上の実物へ移動し、
FH6で削除した結果を「FH6で削除済み（仮）」でOrganizerへ反映する、という流れで
「マイデザイン」を順番に整理できます。

Navigator Bridgeはペイントの選択・削除・確定操作を行いません。最終確認と削除はFH6上で利用者が行います。
また、Bridgeの通常移動は #001U を起点に計算するため、「#001Uへ戻す」をOFFで使う場合は、
移動前にFH6のカーソルを #001U に合わせてください。繰り返し整理では必要に応じて
「#001Uへ戻す」をONにすると、毎回の起点をそろえやすくなります。

「FH6で削除済み（仮）」は同じ生成HTML専用のlocalStorageへ保存される一時情報です。
GameSaveを書き換えず、新しくHTMLを生成した場合は引き継ぎません。


■ FH6上の選択デザインへ移動する

この機能には Navigator Bridge for FH6 v0.0.29 を使用します。
Bridgeの仕組みは同梱の NAVIGATOR-BRIDGE-README.txt の冒頭で、
#603 / #302U を例に詳しく説明しています。

1. Navigator Bridgeを単独起動し、「連携を登録」を一度実行します（Organizerの「連携の登録・解除」で
   「まとめて登録」を実行しても同じです）。
   GUIには「実行形式: Windows EXE / Python」と現在の「連携登録先」が表示されます。
   Bridge本体を別のフォルダーへ移動した場合、ファイル名を変更した場合、EXEとソースからの実行（Python）を
   切り替えた場合、新しい版の配布ZIPを別のフォルダーに展開して使う場合、v0.4.62の配布ZIPの
   pythonフォルダーのBridgeで登録していた場合は、新しいBridgeから「連携を登録」を再実行してください。
   Windows登録にはBridgeの絶対パスが保存されます。
   同じパス・同じファイル名のEXEを新しい版で上書きしただけであれば、通常は再登録不要です。
2. Organizerで生成したHTMLを開きます。
3. カードや比較画面に表示される #603 / #302U などの番号をクリックします。
4. Fキー、または「FH6で選択デザインへ移動」を実行します。
5. Navigator BridgeがFH6を前面へ切り替え、対象の「マイデザイン」位置までカーソルを移動します。
6. 目的に応じて、FH6上で「デザインを読み込み」を実行するか、内容を確認して整理・削除します。

「デザインを読み込み」は現在運転しているマシンへ選択したペイントを適用するFH6側の操作です。
Navigator Bridgeはこの読み込み操作や削除操作を自動実行せず、対象位置までの移動だけを補助します。

ブラウザから外部アプリを開く確認が表示された場合は、内容を確認して許可してください。
OrganizerとBridgeのローカル連携には navigatorbridgeforfh6:// を使用します。

Bridgeがすでに起動している場合は、別ウィンドウを増やさず既存インスタンスへ指示を渡します。
Organizerから必要時に起動されたBridgeモードでは通常GUIを表示しません。


■ FH6移動設定

標準値:

キー間隔                 50ms
FH6切替後                500ms
横→上下                  200ms
左循環後の追加待ち       400ms
#001Uへ戻す              OFF
ESC後の待ち時間          500ms
RET後の待ち時間          1000ms

「#001Uへ戻す」をONにした場合だけ、移動前に固定操作 ESC → RET を各1回送って
マイデザインを開き直してから移動します。

OrganizerのHTML上で変更した移動設定はブラウザのlocalStorageへ保存されます。
「共通設定を保存」を実行すると、Bridgeと共有する設定ファイルにも保存され、
次に新しいOrganizer HTMLを生成するときの初期値として利用されます。


■ Navigator Bridgeの安全設計

Navigator BridgeはFH6の「マイデザイン」位置移動だけを目的とした補助ツールです。

通常の位置移動でFH6へ送信できるキーは以下の3種類だけです。

・左
・右
・下

「#001Uへ戻す」をONにした場合だけ、移動開始前の固定操作として
Escを1回、Return（RET / Enter）を1回、この順序で送信します。

任意のキーコード、キー名、キー順序を外部から指定する機能はありません。
上、文字キー、ファンクションキーなどを位置移動用として送信しません。

Bridgeは前後の通常スペースを除いたウィンドウタイトルが「Forza Horizon 6」と完全一致し、
所有プロセスがforzahorizon6.exeのウィンドウだけをFH6候補として扱います。候補が複数ある場合は
誤送信防止のため自動選択しません。通常の左 / 右 / 下キーは1回送信するごとに、同じ対象HWNDが
現在も前面・タイトル完全一致・FH6プロセス所有であることを確認し、条件を満たさない場合は
次の移動キーを送信しません。
標準のWindows入力APIを使用し、ゲームのメモリ、実行コード、ゲームファイル、
GameSaveを書き換えません。

Navigator Bridgeは、FH6の画面内容を画像認識・解析したり、ゲーム内部のペイント位置やカーソル位置を読み取ったりせず、
Organizerから渡された移動先と設定値をもとに、指定された間隔で固定されたキー入力を送信するだけです。
（FH6ウィンドウの検出・前面化と、入力前の前面状態の確認は行います。）

そのため、PCやFH6の処理負荷、フレームレート、ウィンドウ切替の遅延などによって
キー入力が取りこぼされたり処理が追いつかなかった場合、Organizerで指定したペイント位置へ
正しく移動できず、カーソル位置がずれることがあります。位置がずれる場合は、
「キー間隔」「FH6切替後」「横→上下」「左循環後の追加待ち」などを長めに調整してください。

ゲーム進行、経済、報酬、ランキング、競争行為、削除確定などを自動化することを
目的としていません。最終的な確認、選択、削除などは利用者自身が行います。


■ 整理データについて

HTML上の整理情報はブラウザのlocalStorageへ保存されます。
必要に応じてHTML内のバックアップ・復元機能を使用してください。

同じペイントを再ダウンロードした場合など、現在のGameSave内に同一内容の
別Liveryスロットが存在するときは、それぞれを別カードとして扱います。

「FH6で削除済み（仮）」の状態も、その生成HTML専用のlocalStorageへ保存されます。
新しくHTMLを生成した場合には引き継ぎません。


■ 設定・キャッシュの保存場所

Organizer設定:
%APPDATA%\Livery-Organizer-for-FH6\settings.json

3つのツールの共有設定（言語・表示テーマ・FH6本体とGameSaveのフォルダーなど）:
%APPDATA%\Livery-Organizer-for-FH6\desktop-suite-settings.json

Organizer / Bridge共通のFH6移動設定:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json

Organizerのキャッシュ（車両DB・作成方法監査）:
%LOCALAPPDATA%\Livery-Organizer-for-FH6\cache\

Navigator BridgeのIPC / ログ:
%LOCALAPPDATA%\Navigator-Bridge-for-FH6\

Livery Viewer for FH6 の設定・ログ・取得した three.js・窓（WebView2）の保存:
%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\
（Organizerの %LOCALAPPDATA%\Livery-Organizer-for-FH6 と名前が似ていますが、別のフォルダーです。
中の webview-profile は、2回目から速く開くための保存です。消すと、次はこのPCで初めて開くときと
同じく時間がかかります。）

Livery Viewer for FH6 の準備の結果（車ごとの形・画像など）:
Organizerから開くときは、レポートの出力先の中の preview-cache
（既定は %USERPROFILE%\Documents\Livery-Organizer-for-FH6\preview-cache\）。
Viewerの設定画面から開くときは、設定画面の「preview-cache」の欄の場所。

増えすぎないように、次のようにしています。
・ペイントの準備は、最近の3件だけ残します。
・最近使った3台のほかの車は、車体の形を消し、次にその車を開くときに作り直します（その分、時間がかかります）。
・古い版のViewerが作った物は、自動で消します。

参考：開発者の環境で、GameSaveにあるダウンロード済みの全ペイント 999件を順に表示した後、
preview-cache は約 0.7 GB でした。

大きさの上限は、既定では決めていません。決めるときは、下の preview-settings.json に
"vehicle_cache_limit_gb": 2 のようにGBで書きます。上限の90%を超えると75%まで消します。
表示中の車と、7日以内に使った物は消さないので、少し超えることがあります。

preview-cache を消すときは、Viewerが終わってから消してください（窓を閉じて10分たった後。
Organizerの起動時の準備がオンなら、Organizerも閉じた後）。次に表示するときに作り直します。

Viewerの設定（preview-settings.json）:
%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\preview-settings.json
・viewer_keep_alive_seconds：窓を閉じた後に裏で待機する時間（秒。0で待機しない。既定は600）
・viewer_standby_with_organizer：Organizerの起動時の準備（true / false。既定はtrue。
  ふだんはViewerの設定画面のチェックで切り替えます）
・vehicle_cache_limit_gb：preview-cache の大きさの上限（GB。既定は上限なし）

旧バージョンの設定・キャッシュが見つかった場合は、互換性維持のため必要に応じて
旧 FH6-Livery-Organizer 系の保存場所や旧localStorageキーから移行します。


■ Livery Viewer for FH6 を移動・削除する場合

Organizer連携のWindows登録には、Livery Viewer for FH6 本体の絶対パスが保存されます。
Livery-Viewer-for-FH6 フォルダーを別の場所へ移動した場合は、移動後のViewerを起動し、
設定画面の「Organizer連携を登録」をもう一度実行してください。

Viewerを削除する場合は、先にViewerを起動して設定画面の「連携登録を解除」を実行し、
liveryorganizerpreviewforfh6:// のWindows登録を解除してください。
その後、Viewerが終わってから（窓を閉じて10分たった後。Organizerの起動時の準備がオンなら、
Organizerも閉じた後。すぐに終わらせたいときは、タスクマネージャーで Livery-Viewer-for-FH6.exe を
終えてもかまいません）、不要であれば Livery-Viewer-for-FH6 フォルダーと、上記のViewer用の保存場所を
削除できます。使用中のファイルは削除できません。


■ Navigator Bridgeを移動・名前変更した場合

Organizer連携のWindows登録には、Navigator Bridge本体の絶対パスが保存されます。
そのため、Bridgeを別のフォルダーへ移動した場合、Bridgeのファイル名を変更した場合、
EXEとソースからの実行（Python）を切り替えた場合、新しい版の配布ZIPを別のフォルダーに展開して使う場合、
またはv0.4.62の配布ZIPのpythonフォルダーのBridgeで登録していた場合は、変更後のBridgeを単独起動し、
「連携を登録」をもう一度実行してください。事前に「解除」を行う必要はありません。
現在のBridgeから再登録すると、navigatorbridgeforfh6:// の登録先が新しい場所へ更新されます。

Bridge GUIの「実行形式」と「連携登録先」で、現在の実行形式とWindowsに登録されている対象を確認できます。
登録先が現在のBridgeと一致しない場合、Organizer連携欄は「再登録が必要」と表示します。

同じフォルダー・同じファイル名のままEXEを新しい版へ置き換えただけの場合は、
登録されている絶対パスが変わらないため、通常は再登録する必要はありません。


■ Navigator Bridgeの連携解除 / 削除

Navigator Bridgeを削除する場合は、先にBridgeを単独起動し、Organizer連携の欄の「解除」を
実行して navigatorbridgeforfh6:// のWindows登録を解除してください。
その後、不要であればBridge本体と上記のBridge用ローカルフォルダーを削除できます。

共有移動設定を残したい場合は、
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json
を削除しないでください。


■ 適用中Liveryの判定について

適用中Liveryを推定する参照探索は現在一時停止しています。
現時点の通常レポートでは適用Livery状態を未判定として扱います。


■ 動作デモ

https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html

デモは公開用のダミーデータを使用しています。
実際のGameSave、作成者、タイトル、説明、サムネイル等は公開デモへ使用しません。
安全のため、デモではNavigator Bridgeの起動とFH6へのキー入力を無効にしています。
3Dプレビュー（Livery Viewer for FH6）は、デモでは使えません。デモの画面は、v0.4.62で生成したものです。


■ 困ったときは（Livery Viewer for FH6）

・「プレビュー」を押しても開かない：
  Viewerの設定画面で「Organizer連携を登録」を実行したか、ブラウザが外部のアプリを開く確認を
  出していないかを確かめてください。Viewerのフォルダーを移動した場合は、登録し直してください。
・初めて開くときに止まったように見える：
  このPCで初めて開くときは15～28秒ほどかかります。初めて3Dプレビューを開くときは、
  three.js の取得のためにインターネットへの接続が必要です。
・車が表示されない・エラーが出る：
  画面のエラーと、次の記録のファイルを確かめてください。
  %LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\preview-bridge.log（準備・起動の記録）
  %LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\viewer-gui.log（設定画面の記録）
・窓を閉じてもViewerが終わらない：
  窓を閉じても10分は裏で待機します。Organizerの起動時の準備がオンなら、Organizerを閉じるまで残ります。

不具合を報告するときは、版・手順・エラーの文と、上の記録のファイルを添えてください。
ゲームの原本・個人のセーブデータ・非公開のペイントのファイルは、公開の場所に添付しないでください。


■ 安全性について

Livery Organizer for FH6・Livery Viewer for FH6 は、FH6のGameSaveおよびFH6本体のゲームアセットを
解析対象として読み取り専用で扱います。

解析元に対して、書き込み・削除・移動・リネーム・上書きは行いません。
レポートの出力先としてGameSave配下を指定することもできません。

Organizer / Viewer / Navigator Bridgeのいずれにも、利用者のLiveryデータを外部サーバーへ
送信するためのネットワーク機能はありません。
Livery Viewer for FH6 が外部へ接続するのは、初めて3Dプレビューを開くときに three.js を npm の公式配布
（registry.npmjs.org）から取得するときだけです。


■ プレビュー版について

FH6の内部データ形式は公式仕様として公開されているものではなく、
解析処理の一部は実データの観測に基づいています。
ゲーム側の更新などにより、将来のバージョンで解析方法や表示内容が
変更される可能性があります。

Livery Viewer for FH6 の3D表示は、ゲームのファイルから独自に再現したもので、
ゲーム内の見た目と完全には一致しません。

本ツールは非公式・非営利のファンメイドツールであり、Microsoft、Xbox、
Turn 10 Studios、Playground Games、Forzaその他の権利者とは関係ありません。
提携、承認、後援を受けた公式ソフトウェアではありません。

Microsoft、Xbox、Forzaおよび関連する名称・商標・著作物は、それぞれの権利者に帰属します。
利用者は、Microsoft / Xbox / Forzaの各利用規約および適用される法令を確認し、
自己の責任で本ツールを利用してください。

参考: Xbox ゲーム コンテンツ利用規約
https://www.xbox.com/ja-JP/developers/rules

詳細な変更内容は同梱の CHANGELOG.md を参照してください。


■ ライセンス / 免責

MIT License（同梱の LICENSE.txt）。
同梱する第三者の部品とそのライセンスは、同梱の THIRD-PARTY-NOTICES.txt を参照してください。
本ソフトウェアは現状有姿で提供されます。
利用前に必要なデータのバックアップを行い、利用者自身の責任で使用してください。
