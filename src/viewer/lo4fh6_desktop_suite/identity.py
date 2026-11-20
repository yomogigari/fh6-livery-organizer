"""公開テスト版の正式名称と実行ファイル名の唯一の対応表。"""
from __future__ import annotations

from types import MappingProxyType

DISPLAY_NAMES = MappingProxyType({
    'organizer': 'Livery Organizer for FH6',
    'viewer': 'Livery Viewer for FH6',
    'navigator_bridge': 'Navigator Bridge for FH6',
})
EXE_NAMES = MappingProxyType({
    app: name.replace(' ', '-') + '.exe'
    for app, name in DISPLAY_NAMES.items()
})
# 実機確認前のEXE作成を完了と誤認しない。名称・ファイル名の契約のみ。
