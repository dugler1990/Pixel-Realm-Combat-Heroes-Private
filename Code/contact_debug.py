"""Where recent hits landed, for the camera's debug dots (Settings.DEBUG_DRAW_CONTACTS).

InteractionResolver.apply records each landed hit's contact while ENABLED, with what it met on a body
that has worn layers ("plate": a worn piece, "skin": the hide; None otherwise); the camera draws the
ones younger than KEEP_MS. At most the last 64 are kept.
"""

from collections import deque

from Settings import DEBUG_DRAW_CONTACTS

ENABLED = DEBUG_DRAW_CONTACTS
KEEP_MS = 600

_RECENT = deque(maxlen=64)


def kind_of(target, point):
    """"plate" / "skin" for a hit at `point` on a body that can wear pieces (body_regions.hit_layers),
    None for anything else. Debug only: runs only while ENABLED."""
    if getattr(target, "body_def", None) is None or getattr(target, "defence", None) is None:
        return None
    import body_regions

    spot = body_regions.hit_layers(target, point)
    if spot.point is not None:
        return "plate" if spot.piece else "skin"
    return "plate" if len(spot.layers) > 1 else "skin"


def record(point, now_ms, kind=None):
    """Keep one hit's world pixel and what it met, stamped with the time it landed."""
    _RECENT.append((now_ms, int(point[0]), int(point[1]), kind))


def recent(now_ms, keep_ms=None):
    """(x, y, kind) of the hits that landed in the last `keep_ms` (default KEEP_MS)."""
    keep = KEEP_MS if keep_ms is None else keep_ms
    return [(x, y, kind) for t, x, y, kind in _RECENT if now_ms - t <= keep]


def clear():
    _RECENT.clear()
