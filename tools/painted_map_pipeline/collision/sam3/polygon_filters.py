"""Tag SAM3 polygons for TMX merge (class + collision_mode)."""

from __future__ import annotations

from typing import Any

CANOPY_CLASSES = frozenset({"tree"})


def normalize_sam3_class(raw: Any) -> str:
    if raw is None:
        raise ValueError("SAM3 polygon missing class")
    text = str(raw).strip().lower()
    if not text:
        raise ValueError("SAM3 polygon missing class")
    return text


def tag_polygon(poly: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with sam3_class and collision_mode set."""
    out = dict(poly)
    raw_class = out.get("class")
    if raw_class is None or (isinstance(raw_class, str) and not raw_class.strip()):
        raw_class = out.get("prompt")
    sam3_class = normalize_sam3_class(raw_class)
    out["sam3_class"] = sam3_class
    out["collision_mode"] = "canopy" if sam3_class in CANOPY_CLASSES else "solid"
    return out
