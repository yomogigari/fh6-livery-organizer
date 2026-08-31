"""Japanese UI strings (fallback language)."""

STRINGS = {
    "app.subtitle": (
        "Livery_*を解析し、Windows版FH6本体の車両アセットZIPから"
        "Car ID・車両内部名・推定車名を自動取得して整理します。"
    ),
    "path.save_root": "保存領域",
    "path.game_root": "FH6本体",
    "path.output_root": "出力先",
    "path.output_bundle": "出力構成",
    "settings.auto_saved": "設定は自動保存されます: {path}",
    "settings.save_warning": "設定保存警告: {error}",
    "option.embed_thumbnails": "サムネイルをHTMLへ埋め込む（OFF時は thumbnails フォルダへコピー）",
    "option.export_analysis": "解析用データを data フォルダへ出力（JSON / CSV / 車両DB）",
    "preflight.title": "実行前チェック",
    "preflight.checking": "確認中",
    "preflight.item_checking": "{label}: 確認中",
    "safety.title": "安全設計",
    "safety.body": (
        "・GameSave配下への書込み、削除、移動、リネーム機能はありません。\n"
        "・過去スナップショットの同一コピーは重複除外し、現在の再ダウンロード重複は別ペイントとして表示します。\n"
        "・「残す / 削除候補」はHTMLのブラウザlocalStorageだけに保存されます。\n"
        "・Car IDはフォルダ名とC_livery展開後0x10の一致を検証します。\n"
        "・出力先はGameSaveディレクトリ全体の配下を拒否します。\n"
        "・設定ファイルはユーザー領域へ保存し、GameSave配下には作成しません。"
    ),
    "button.scan": "ペイントデータチェック",
    "button.open_output": "出力先を開く",
    "button.recheck": "設定を再確認",
    "button.quick_start": "初回利用ガイド",
    "button.support_info": "環境・サポート情報",
    "button.browse": "参照…",
    "log.ready": "準備完了。{app} v{version} / FH6を完全終了してから実行してください。",
    "log.settings_file": "設定ファイル: {path}",
    "dialog.output_required": "出力先を指定してください。",
    "dialog.save_root_required": "保存領域を先に指定してください。",
    "dialog.create_output_failed": "出力先を作成できません。\n\n{error}",
    "cli.usage_prefix": "使い方:",
    "cli.options_prefix": "オプション:",
    "cli.help_builtin": "このヘルプを表示して終了",
    "cli.description": "Livery Organizer for FH6 v{version}（FH6保存データ読み取り専用）",
    "cli.root_help": "走査する保存領域。例: C:¥XboxGames¥GameSave¥pgs",
    "cli.out_help": "レポートの出力先フォルダー",
    "cli.game_root_help": "車両アセットを解析するFH6本体のインストール先",
    "cli.print_game_roots_help": "自動検出したFH6本体の候補を表示して終了",
    "cli.no_embed_help": "サムネイルをHTMLへ埋め込まず、thumbnails/へコピーして出力",
    "cli.export_analysis_help": "ペイント情報と車両DBのJSON/CSVをdata/へ出力",
    "cli.environment_check_help": "走査せずに環境・設定・実行前チェック情報を表示して終了",
    "cli.inspect_assets_help": "FH6本体のZIPを読み取り専用で検査し、空ZIPと読み取り不可ZIPの詳細を表示して終了",
    "cli.cli_help": "GUIを使わずコマンドラインモードで実行",
    "cli.print_roots_help": "自動検出したFH6保存領域の候補を表示して終了",
}
