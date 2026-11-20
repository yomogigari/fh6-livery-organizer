"""Independent FH6 livery package input adapter.

The original game data is parsed by the first-party source envelope and tree.
The historic package schema names are preserved only for backward-compatible
serialization; no 参照製品 code or module is imported. Unknown source grammar,
privacy wrappers and unsupported identity metadata are rejected.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Iterable, Any

from fh_livery_preview_core.source_envelope import unpack_source_bytes, unpack_source_file
from fh_livery_preview_core.source_structure import extract_livery_sections, SECTION_LABELS
from fh_livery_preview_core.native_canonical_layers import native_layers
from fh_livery_preview_core.first_party_privacy_absence import inspect_absent_protected_groups

LIVERY_SECTION_NAMES = SECTION_LABELS


def unwrap_forza_container(path: Path | str) -> bytes:
    return unpack_source_file(Path(path))


def unwrap_forza_container_bytes(blob: bytes, path: Path | str | None = None) -> bytes:
    del path
    return unpack_source_bytes(blob)


def extract_livery_payload(payload: bytes):
    return extract_livery_sections(payload)


def inspect_clivery_privacy(payload: bytes) -> dict[str, Any]:
    result = inspect_absent_protected_groups(payload)
    if result is None:
        raise ValueError('unsupported/ambiguous protected group; native-only mode cannot fall back')
    return result


def clivery_to_layers(payload: bytes):
    layers, report, _ = native_layers(payload)
    return layers, report


def layers_to_lo4_json_layers(layers: Iterable[dict[str, Any]], game: str | None = 'fh6'):
    """Legacy JSON package shape contract assembled without third-party code.

    The resource family/name is taken only from the SHA-pinned installed
    numerical catalog. Unknown identities remain unannotated; no shape changes.
    """
    if game is not None and str(game).lower() != 'fh6':
        raise ValueError('only independently verified FH6 source identities are supported')
    out = []
    for n, layer in enumerate(layers, 1):
        word = int(layer['shape_id']) & 0xffff
        if not word:
            raise ValueError('zero/invalid graphic word')
        is_raster = bool(layer.get('is_raster_logo'))
        shape = {
            'type': 0x100000 + word, 'type_word': word,
            'type_word_hex': f'0x{word:04x}',
            'data': [float(v) if isinstance(v, (int,float)) else v for v in layer['data']],
            'color': [int(v) for v in layer['color_rgba']],
            'mask': bool(layer.get('mask')),
            'score': 0, 'source_format': 'forza_file_export',
            'source_shape_index': n, 'source_offset': layer.get('source_offset'),
            'source_marker': layer.get('marker_hex'), 'source_game': 'fh6',
        }
        if is_raster:
            shape['is_raster_logo'] = True
            shape['raster_id'] = int(layer.get('raster_id') or (word & 0x7fff))
            shape['source_raw_type_word'] = word
            shape['source_raw_type_word_hex'] = f'0x{word:04x}'
        if layer.get('section'):
            shape['source_section'] = layer['section']
        out.append(shape)
    return out, []
