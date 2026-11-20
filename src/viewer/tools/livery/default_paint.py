from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .manufacturer_colors import ManufacturerColorError, resolve_vehicle_manufacturer_color
from .vehicle_assets import VehicleAsset


def _normalize(value: str) -> str:
    return value.replace('\\', '/')


def _game_refs(data: bytes, minimum: int = 12) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(rb"[ -~]{%d,}" % minimum, data):
        value = match.group(0).decode('ascii', errors='ignore').strip()
        if value.casefold().startswith(('game:\\', 'game:/')):
            refs.append(value)
    return sorted(set(refs), key=str.casefold)


def _manifest_body_record(data: bytes) -> dict[str, Any]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    for model in root.findall('.//Model'):
        path = _normalize(str(model.attrib.get('path') or ''))
        if not path.casefold().endswith('/scene/exterior/platform/body_a.modelbin'):
            continue
        return {
            'path': path,
            'materials': [str(x.attrib.get('path') or '') for x in model.findall('Material')],
            'swatchbins': [str(x.attrib.get('path') or '') for x in model.findall('Swatchbin')],
        }
    return {}


def inspect_vehicle_default_paint_candidates(asset: VehicleAsset) -> dict[str, Any]:
    """Collect read-only evidence for an implicit/default base-paint descriptor.

    The function never chooses a default colour.  It exposes candidate references
    from the vehicle archive so a later revision can establish the actual rule.
    """
    result: dict[str, Any] = {
        'archive_name': asset.archive_name,
        'model_code': asset.model_code,
        'manufacturer_selector_zero': None,
        'manifest_body': {},
        'body_embedded_game_refs': [],
        'carbin_embedded_game_refs': [],
        'base_livery_refs': [],
        'carpaint_material_refs': [],
        'archive_member_candidates': [],
    }
    try:
        result['manufacturer_selector_zero'] = resolve_vehicle_manufacturer_color(asset, 0)
    except ManufacturerColorError as exc:
        result['manufacturer_selector_zero'] = {
            'selector': 0,
            'resolved': False,
            'error': f'{type(exc).__name__}: {exc}',
        }

    with zipfile.ZipFile(asset.archive_path) as bundle:
        names = [info.filename.replace('\\', '/') for info in bundle.infolist() if not info.is_dir()]
        manifest = next((n for n in names if n.casefold() == 'manifest.xml'), None)
        if manifest:
            result['manifest_body'] = _manifest_body_record(bundle.read(manifest))

        body_entry = next(
            (n for n in names if n.casefold().endswith('/scene/exterior/platform/body_a.modelbin')),
            None,
        )
        if body_entry:
            result['body_embedded_game_refs'] = _game_refs(bundle.read(body_entry))

        carbin_entries = [n for n in names if n.casefold().endswith('.carbin')]
        expected = f'{asset.model_code}.carbin'.casefold()
        ordered = sorted(
            carbin_entries,
            key=lambda n: (Path(n).name.casefold() != expected, len(n), n.casefold()),
        )
        if ordered:
            result['carbin_embedded_game_refs'] = _game_refs(bundle.read(ordered[0]))

        result['archive_member_candidates'] = sorted(
            [
                n for n in names
                if n.casefold().endswith('.materialbin')
                and any(token in n.casefold() for token in ('baselivery', 'carpaint', 'carcolors'))
            ],
            key=str.casefold,
        )

    all_refs: list[str] = []
    body = result.get('manifest_body') or {}
    for value in list(body.get('materials') or []) + list(result['body_embedded_game_refs']) + list(result['carbin_embedded_game_refs']):
        if value and value not in all_refs:
            all_refs.append(value)
    result['base_livery_refs'] = [x for x in all_refs if 'baselivery' in x.casefold()]
    result['carpaint_material_refs'] = [
        x for x in all_refs
        if x.casefold().endswith('.materialbin') and 'carpaint' in x.casefold()
    ]
    return result

def resolve_vehicle_default_paint(asset: VehicleAsset, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve an implicit/default paint conservatively from vehicle evidence.

    The rule is intentionally fail-closed.  A descriptor with no explicit finish,
    RGB, or manufacturer selector is treated as ManufacturerColors selector 0 only
    when the vehicle body itself uses the generic FH6 carpaint material, selector 0
    resolves successfully, and no BaseLivery material is actually referenced by the
    body/carbin evidence.  Merely having a BaseLivery member in the ZIP is not enough
    to override this rule because such members may be present but unreferenced.
    """
    diagnostics = diagnostics if diagnostics is not None else inspect_vehicle_default_paint_candidates(asset)
    manufacturer_zero = diagnostics.get('manufacturer_selector_zero') or {}
    body = diagnostics.get('manifest_body') or {}
    body_materials = [str(value) for value in body.get('materials') or []]
    normalized_body_materials = [value.replace('/', '\\').casefold() for value in body_materials]
    generic_carpaint = 'game:\\media\\cars\\_library\\materials\\_fmnext\\carpaint_default\\carpaint.materialbin'
    has_generic_carpaint = generic_carpaint in normalized_body_materials
    base_livery_refs = list(diagnostics.get('base_livery_refs') or [])

    resolved = bool(manufacturer_zero.get('resolved')) and has_generic_carpaint and not base_livery_refs
    result: dict[str, Any] = {
        'archive_name': diagnostics.get('archive_name'),
        'model_code': diagnostics.get('model_code'),
        'selector': 0,
        'resolved': resolved,
        'resolution_source': 'implicit_default_manufacturer_selector_zero',
        'evidence': {
            'manufacturer_selector_zero_resolved': bool(manufacturer_zero.get('resolved')),
            'manifest_body_uses_generic_carpaint': has_generic_carpaint,
            'referenced_base_livery_count': len(base_livery_refs),
            'archive_member_candidate_count': len(diagnostics.get('archive_member_candidates') or []),
        },
        'candidate_diagnostics': diagnostics,
    }
    if resolved:
        result['color'] = manufacturer_zero.get('color')
        result['member'] = manufacturer_zero.get('member')
        result['palette_size'] = manufacturer_zero.get('palette_size')
        result['reason'] = (
            'implicit/default descriptor uses the vehicle generic carpaint path; '
            'ManufacturerColors selector 0 is the resolved default and no BaseLivery '
            'material is referenced'
        )
    else:
        result['reason'] = 'default paint rule evidence is incomplete or conflicting'
        if manufacturer_zero.get('error'):
            result['error'] = manufacturer_zero.get('error')
    return result

