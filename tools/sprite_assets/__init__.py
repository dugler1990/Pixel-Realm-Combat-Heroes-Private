"""Sprite-sheet helpers: cut cells, matte painted backgrounds, pack frame folders.

Designed for AI / concept sheets that are labeled, uneven, and painted on stone
floors rather than chroma keys. First customer: meteor attack sheets.
"""
from __future__ import annotations

__all__ = [
    "cut_cells",
    "detect_gutter_grid",
    "matte_stone_floor",
    "pack_sequence",
    "write_contact_sheet",
]
