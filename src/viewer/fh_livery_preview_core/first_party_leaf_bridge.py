"""rM003: independent FH6 group/leaf authority for the r485 canonical surface path.

The project-owned r32/rL structural parser validates every ordered drawable leaf
before its word, color and offset are used. r485 retains ALL transforms, mask
inheritance, raster rendering, shader, camera and GUI. Unknown dialects and any
mismatch fall back to r485 byte-for-byte layer values, not guessed semantics.

No source bytes, original artwork or private offsets are written to a log.
"""
from __future__ import annotations

from .native_structure import decode_livery_structure
from .native_graphic_dispatch import classify_original_graphics
from .source_leaf_records import reference_word_alias


def bind_native_leaf_identity(payload: bytes, layers: list[dict]) -> tuple[list[dict], dict]:
    """Use first-party source leaf fields ONLY after full ordered parity with r485.

    Return (layers, aggregate_report). The input list and its members are never
    modified. The r485 layer array remains the source of all transforms/masks.
    """
    fallback = {'mode': 'r485_fallback', 'identity_source': 'r485',
                'transform_source': 'r485', 'mask_source': 'r485',
                'native_transform_parity_verified': False,
                'xbox_parity_verified': False}
    try:
        parsed = decode_livery_structure(payload)
        own = [shape for section in parsed.sections for shape in section.shapes]
        if len(own) != len(layers):
            return layers, {**fallback, 'reason': 'leaf_count_mismatch',
                            'r485_leaves': len(layers), 'native_leaves': len(own)}
        # Validate the entire sequence before changing ANY value. Avoid set-only
        # checks: duplicate offsets or swapped layer order would corrupt masks.
        for shape, layer in zip(own, layers):
            if (shape.section != layer.get('section')
                    or shape.source_offset != layer.get('source_offset')
                    or reference_word_alias(shape.shape_word) != layer.get('shape_id')
                    or list(shape.color_rgba) != layer.get('color_rgba')):
                return layers, {**fallback, 'reason': 'ordered_leaf_identity_mismatch',
                                'r485_leaves': len(layers), 'native_leaves': len(own)}
        # rL graphics dispatch distinguishes high-bit original raster IDs from
        # Vinyls.zip vectors. No rectangle/unknown-ID substitution is permitted.
        dispatch = classify_original_graphics(payload, parsed)
        raster_count = sum(bool(layer.get('is_raster_logo')) for layer in layers)
        if raster_count != dispatch['rasterLeaves']:
            return layers, {**fallback, 'reason': 'raster_dispatch_mismatch',
                            'r485_leaves': len(layers), 'native_leaves': len(own)}
        native_layers = []
        for shape, layer in zip(own, layers):
            item = dict(layer)
            item['shape_id'] = reference_word_alias(shape.shape_word)
            item['color_rgba'] = list(shape.color_rgba)
            item['source_offset'] = shape.source_offset
            native_layers.append(item)
        return native_layers, {
            'mode': 'native_leaf_fields', 'identity_source': 'rL-first-party',
            'transform_source': 'r485', 'mask_source': 'r485',
            'native_leaves': len(own),
            'native_groups': sum(len(s.groups) for s in parsed.sections),
            'max_group_depth': max((len(s.group_chain) for s in own), default=0),
            'native_raster_leaves': dispatch['rasterLeaves'],
            'native_vector_leaves': dispatch['vectorLeaves'],
            'all_ordered_leaves_verified': True,
            'native_transform_parity_verified': False,
            'xbox_parity_verified': False,
        }
    except Exception as error:  # fail-safe: never break the known-good r485 path
        return layers, {**fallback, 'reason': 'native_decoder_rejected',
                        'error_type': type(error).__name__,
                        'r485_leaves': len(layers)}
