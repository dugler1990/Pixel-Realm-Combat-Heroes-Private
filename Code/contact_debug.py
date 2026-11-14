"""Where recent hits landed, for the camera's debug dots (Settings.DEBUG_DRAW_CONTACTS).

InteractionResolver.apply records each landed hit's contact while ENABLED; the camera
draws the ones younger than keep_ms. At most the last 64 are kept.
"""

from collections import deque

from Settings import DEBUG_DRAW_CONTACTS

ENABLED = DEBUG_DRAW_CONTACTS

_RECENT = deque(maxlen=64)


def record(point, now_ms):
    """Keep one hit's world pixel, stamped with the time it landed."""
    _RECENT.append((now_ms, int(point[0]), int(point[1])))


def recent(now_ms, keep_ms=600):
    """The world pixels of the hits that landed in the last `keep_ms`."""
    return [(x, y) for t, x, y in _RECENT if now_ms - t <= keep_ms]


def clear():
    _RECENT.clear()
