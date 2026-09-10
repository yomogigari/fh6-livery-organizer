Livery Organizer for FH6 v0.4.61 Preview
=========================================

公開日: 2026-09-11

Livery Organizer for FH6 は、PC版 Forza Horizon 6 でダウンロードした
ペイント（Livery）を、ローカル環境で一覧化・検索・整理するためのツールです。

このリリースはプレビュー版です。

v0.4.61では、作成者カラーを一覧で管理できる画面を追加し、カードに作成者アップロード日を
表示して「新しい順 / 古い順」で並び替えられるようにしました。バックアップ / 復元では、
現在のレポートに含まれないペイントのユーザーデータも保持し、次のバックアップへ引き継げます。

同梱車両メタデータは2026-09-08更新のFH6公式車種リストへ追随し、647車種・package revision 2へ
更新しました。任意の補助ツール Navigator Bridge for FH6 は v0.0.28 となり、タイトル完全一致に
加えて所有プロセスがforzahorizon6.exeであることを確認し、各移動キーの直前にも同じ対象を
再検証します。条件を満たす候補が複数ある場合は自動選択しません。


■ 配布ファイル

Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
python\livery-organizer-for-fh6-v0461.py
python\i18n.py
python\vehicle_metadata_update.py
python\fh6-vehicle-metadata.json
python\fh6-vehicle-metadata-manifest.json
python\navigator-bridge-for-fh6-v028.py
python\locales\__init__.py
python\locales\ja.py
python\locales\en.py

OrganizerはEXE版とPython版のどちらか一方を選んで利用できます。
Python版Organizerでは日本語/英語の翻訳モジュールを使用するため、pythonフォルダー内の
i18n.pyとlocalesフォルダーを削除・移動せず、そのままの構成で使用してください。
Navigator BridgeもEXE版とPython版のどちらか一方を利用します。

Navigator Bridgeは任意機能です。
一覧化・検索・整理・CSV / Excel出力など、Organizer本体の機能だけを使う場合は不要です。

Windows EXEを自分でビルドするためのBuild Kitや詳細なビルド手順は、通常の配布物には含めていません。


■ 言語 / 英語ドキュメント

Organizerの利用者向け表示は、日本語と英語に対応しています。
言語設定はsettings.jsonへ保存され、変更は次回起動時から反映されます。
生成HTML / Excelは、レポート生成時点のOrganizer言語を使用します。
Liveryタイトル、説明、作成者名、車名、タグ、メモ等の利用者データは翻訳しません。

日本語を主要ドキュメントの正本、英語を共通の第二言語として扱います。
英語の概要は同梱の README_EN.txt、Bridgeの英語詳細は NAVIGATOR-BRIDGE-README_EN.txt を参照してください。

英語表示で不自然な表現や誤訳を見つけた場合は、Issue等でのフィードバックを歓迎します。
可能であれば、GitHubリポジトリの src/organizer/locales/en.py に対する具体的な変更、
またはPull Requestとして提案していただけると助かります。
翻訳は機能の意味、既存用語、UIレイアウト、テスト等も確認してから反映するため、
レビュー・反映には時間がかかる場合があります。

今後、日本語・英語以外のUI言語が追加された場合でも、その言語専用の詳細文書一式を
個別に増やす予定はありません。日本語を読めない場合は英語ドキュメントを共通参照として利用してください。


■ Navigator Bridge for FH6 とは

Navigator Bridgeは、Organizerで選んだ `#603 / #302U` などの位置番号に対応する
FH6「マイデザイン」上のペイントへ、カーソルを自動で移動するための任意の補助ツールです。

Organizerは選択した移動先と現在の最終実スロット番号、移動設定をBridgeへ渡します。
BridgeはFH6「マイデザイン」の #001U を起点として、指定位置までに必要な
左 / 右 / 下のカーソル操作を計算し、FH6を前面化して、設定された間隔でキー入力します。
左右は、右へ進む経路と左キーで最終列へ循環する経路のうち、入力回数が少ない方を使います。

つまり、`#603 / #302U` をクリックして F キーまたは「FH6で選択デザインへ移動」を実行すると、
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
詳しい仕組み、開始位置、調整方法、安全境界は `NAVIGATOR-BRIDGE-README.txt` を参照してください。


■ 動作環境

主な対象:
Windows 11
PC版 Forza Horizon 6

開発・動作確認はMicrosoft Store / Xbox App版を中心に行っています。
OrganizerについてはSteam版でも利用者から正常動作の報告がありますが、開発側でSteam環境を
正式に検証したものではありません。Navigator BridgeもSteam環境での正式検証は行っておらず、
利用にはFH6ウィンドウタイトルが「Forza Horizon 6」と完全一致し、所有プロセスをFH6本体として確認できる必要があります。

Python版はPython標準ライブラリのみで動作し、GUIにはTkinterを使用します。


■ Organizerの使い方

EXE版:
Livery-Organizer-for-FH6.exe を起動してください。

Python版:
配布ZIPを展開したフォルダーで、python\livery-organizer-for-fh6-v0461.py を実行してください。

例:
python python\livery-organizer-for-fh6-v0461.py

uvを利用している場合:
uv run python\livery-organizer-for-fh6-v0461.py

python\i18n.py と python\locales フォルダーは多言語表示に必要です。
Organizer本体と同じpythonフォルダー構成のまま使用してください。

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

この機能には Navigator Bridge for FH6 v0.0.28 を使用します。
Bridgeの仕組みは同梱の `NAVIGATOR-BRIDGE-README.txt` の冒頭で、
#603 / #302U を例に詳しく説明しています。

1. Navigator Bridgeを単独起動し、「連携を登録」を一度実行します。
   GUIには「実行形式: Windows EXE / Python」と現在の「連携登録先」が表示されます。
   Bridge本体を別フォルダへ移動した場合、ファイル名を変更した場合、EXE版とPython版を切り替えた場合は、
   移動・変更後のBridgeから「連携を登録」を再実行してください。Windows登録にはBridgeの絶対パスが保存されます。
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
RET後の待ち時間          800ms

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

Organizer / Bridge共通のFH6移動設定:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json

Vehicle DBキャッシュ:
%LOCALAPPDATA%\Livery-Organizer-for-FH6\cache\

Navigator BridgeのIPC / ログ:
%LOCALAPPDATA%\Navigator-Bridge-for-FH6\

旧バージョンの設定・キャッシュが見つかった場合は、互換性維持のため必要に応じて
旧 FH6-Livery-Organizer 系の保存場所や旧localStorageキーから移行します。


■ Navigator Bridgeを移動・名前変更した場合

Organizer連携のWindows登録には、Navigator Bridge本体の絶対パスが保存されます。
そのため、Bridgeを別フォルダへ移動した場合、Bridgeのファイル名を変更した場合、
またはEXE版とPython版を切り替えた場合は、変更後のBridgeを単独起動し、
「連携を登録」をもう一度実行してください。事前に「解除」を行う必要はありません。
現在のBridgeから再登録すると、navigatorbridgeforfh6:// の登録先が新しい場所へ更新されます。

Bridge GUIの「実行形式」と「連携登録先」で、現在の実行形式とWindowsに登録されている対象を確認できます。
登録先が現在のBridgeと一致しない場合、Organizer連携欄は「再登録が必要」と表示します。

同じフォルダ・同じファイル名のままEXEを新しいバージョンへ置き換えただけの場合は、
登録されている絶対パスが変わらないため、通常は再登録する必要はありません。


■ Navigator Bridgeの連携解除 / 削除

Navigator Bridgeを削除する場合は、先にBridgeを単独起動し、GUIから「連携を解除」を
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


■ 安全性について

Livery Organizer for FH6は、FH6のGameSaveおよびFH6本体のゲームアセットを
解析対象として読み取り専用で扱います。

解析元に対して、書き込み・削除・移動・リネーム・上書きは行いません。
レポートの出力先としてGameSave配下を指定することもできません。

Organizer / Navigator Bridgeのいずれにも、利用者のLiveryデータを外部サーバーへ
送信するためのネットワーク機能はありません。


■ プレビュー版について

FH6の内部データ形式は公式仕様として公開されているものではなく、
解析処理の一部は実データの観測に基づいています。
ゲーム側の更新などにより、将来のバージョンで解析方法や表示内容が
変更される可能性があります。

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

MIT License。
本ソフトウェアは現状有姿で提供されます。
利用前に必要なデータのバックアップを行い、利用者自身の責任で使用してください。
