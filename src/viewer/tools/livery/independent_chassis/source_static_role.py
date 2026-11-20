"""参照製品静止Carbinプレビューの分類契約を参照した第一者実装。

元参照製品 Program.cs ClassifyRole/RenderedLiverySides/ProjectionLiverySidesを
動作仕様として確認。FH6 Shader/Mask画素の等価性は意味しない。研究専用。
車種・リバリー個別の分岐、外部ソースコード直接利用なし。
"""
from __future__ import annotations

# 参照元の定数は原本材質識別ハッシュ。画像やゲームの原本バイトを含まない。
_WINDOW_BINDING = 0x9582FD1BA2FFF9A4
_PANEL_BINDINGS = frozenset((
    0x4FF3746D9B055F1D, 0xE00E033E6A20B977, 0xE00E023E6A20B7C4,
    0xE00E053E6A20BCDD, 0xE00E043E6A20BB2A, 0xE00DFF3E6A20B2AB,
    0xE00DFE3E6A20B0F8, 0xE00E013E6A20B611, 0xE00E003E6A20B45E,
    0xE00DFB3E6A20ABDF, 0xE00DFA3E6A20AA2C,
))
_CARPAINT_BINDINGS = frozenset((
    0xF7DBE8A7C839A675, 0x48E5B27611922B17, 0x496F92FA5A6AAA57,
    0xE3AEF60D5E234B88, 0xE3AEF90D5E2350A1, 0xBF98CB3AA93337A4,
    0xBF98CE3AA9333CBD, 0xBF98CD3AA9333B0A, 0xBF98C83AA933328B,
    0xBF98C73AA93330D8, 0xBF98CA3AA93335F1, 0xBF98C93AA933343E,
    0xBF98C43AA9332BBF, 0xBF98C33AA9332A0C, 0x471A5FA481625396,
    0x6AC1E9D87FE5D953, 0x4FD95FB5F29A1C11, 0x78D434B9676BAFE1,
    0x1E5FF0F50C741122, 0x115F3B8D0531FAE2, 0x23E6ED8FEF16F8E0,
    0xCD48110253EE319A, 0x06506BFF10D8BBBA, 0x9A883D636B6F3798,
    0xBCEA13C28AA26965, 0x6E3810972EA4DBF4, 0xB0C163FF8ADE48FD,
))

# 車体の塗装の材質（原本の MaterialBin）。MatI の名前が塗装の名前でなくても、親がこれなら車体の塗装。
_BODY_PAINT_MATERIALBIN_SUFFIX = '/carpaint_default/carpaint.materialbin'
# 親の材質だけで塗装とみなす部品の種類（外装の塗装面のある部品）。内装のロールケージ（ChassisStiffness）等は除く。
_EXTERIOR_PAINT_PART_TYPES = frozenset(('CarBody', 'Hood', 'FrontBumper', 'RearBumper', 'SideSkirts', 'RearWing'))
FRONT, BACK, TOP, LEFT, RIGHT, SPOILER = (1, 2, 4, 8, 16, 32)
GFRONT, GBACK, GTOP, GLEFT, GRIGHT = (64, 128, 256, 512, 1024)
ALL_BODY, ALL_GLASS = 31, 0x7C0


def _mesh_label(raw: str) -> str:
    return raw.split('|', 1)[0].casefold()


def _window_side(label: str) -> int:
    n = _mesh_label(label)
    if 'int' in n:
        return 0
    if n.startswith(('glassrf', 'glassrr', 'glassrm')):
        return GRIGHT
    if n.startswith(('glasslf', 'glasslr', 'glasslm')):
        return GLEFT
    if n.startswith(('glassf_', 'glassflivery')) or 'windshield' in n or 'windsheild' in n:
        return GFRONT
    if n.startswith(('glassr_', 'glassrlivery')) or 'backglass' in n or 'rearglass' in n:
        return GBACK
    if n.startswith(('glasstop_', 'glassroof_')):
        return GTOP
    return 0


def _panel(label: str) -> str | None:
    name = label.casefold()
    if 'mirror' not in name and ('spoiler' in name or 'wing' in name):
        return 'spoiler'
    if name.startswith('trunk'):
        return 'trunk'
    return None


def static_mesh_role(source_entry: str, mesh_name: str, material_name: str, *,
                     material_binding_hash: int, has_uv3: bool,
                     window_hint: bool = False, parent_materialbin: str = '',
                     part_type: str = '') -> str:
    """変換元の参照製品分類を静止プレビュー用に再現。ゲームShader分類とは別。"""
    if not all(isinstance(v, str) for v in (source_entry, mesh_name, material_name)):
        raise ValueError('Static preview source role requires original strings')
    if type(material_binding_hash) is not int or not 0 <= material_binding_hash <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError('Static preview source role requires original uint64 binding hash')
    if type(has_uv3) is not bool or type(window_hint) is not bool:
        raise ValueError('Static preview source role requires exact boolean declarations')
    identity = f'{source_entry} {mesh_name} {material_name}'.casefold()
    mesh, material = _mesh_label(mesh_name), material_name.casefold()
    rejected = any(value in material for value in ('screw','frame','label','bulb','light'))
    is_window = not rejected and any(s in material for s in (
        'window','windshield','windsheild','blackglass'))
    if mesh.startswith('glass') and 'int' in mesh:
        return 'hidden'
    if (_window_side(mesh) and not rejected and (
            material_binding_hash == _WINDOW_BINDING or window_hint or is_window
            or '/windows/' in identity or '\\windows\\' in identity)):
        return 'glass'
    is_body_paint = (
        not any(t in material for t in ('caliper','texture')) and
        (material.startswith(('carpaint', 'car_paint', 'paint_'))
         or material.endswith('_paint') or '_paint_' in material)
    )
    # 名前が塗装でなくても、親の材質が車体の塗装（CarPaint_Default）で、車体の塗装グループに結び付き、
    # UV3 があり、外装の部品なら塗装（例：ALF_GiuliaGTAm_21 のボンネットの本体。MatI 名は chrome）。
    paint_by_parent = (
        has_uv3 and material_binding_hash in _CARPAINT_BINDINGS
        and part_type in _EXTERIOR_PAINT_PART_TYPES and '/interior/' not in identity
        and isinstance(parent_materialbin, str)
        and parent_materialbin.replace('\\', '/').casefold().endswith(_BODY_PAINT_MATERIALBIN_SUFFIX)
    )
    if (is_body_paint or paint_by_parent or material_binding_hash in _PANEL_BINDINGS or
            (has_uv3 and 'livery' in identity and material_binding_hash in _CARPAINT_BINDINGS)):
        return 'paint'
    if 'shadow' in identity:
        return 'hidden'
    if any(s in identity for s in ('blackglass','gls_clear','undercarriage','tire')):
        return 'dark'
    return 'trim'


def static_livery_sides(role: str, mesh_name: str, part_type: str) -> tuple[int, int]:
    """参照製品表示可能面とworld projection面。Mask実画素の許可ではない。"""
    if role not in ('paint','glass','hidden','dark','trim') or not isinstance(part_type, str):
        raise ValueError('Static preview role/part type is invalid')
    if role == 'glass':
        return ALL_GLASS, _window_side(mesh_name)
    if role != 'paint':
        return 0, 0
    panel = _panel(mesh_name)
    if panel == 'spoiler':
        return SPOILER, SPOILER
    if panel == 'trunk':
        return BACK | TOP, BACK | TOP
    by_part = {
        'FrontBumper': FRONT | LEFT | RIGHT,
        'RearBumper': BACK | LEFT | RIGHT,
        'Hood': TOP,
        'SideSkirts': LEFT | RIGHT,
        'RearWing': SPOILER,
    }
    return ALL_BODY, by_part.get(part_type, ALL_BODY)
