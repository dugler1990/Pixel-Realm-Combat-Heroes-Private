"""Compact, exact serialization of obstacle pixel masks for the multiplayer wire.

Stage B2.5 (multiplayer plan). Stage B2 gave the server the map's obstacle
*rects*; for plain rectangular walls that's exact. But level 6 also has
IRREGULAR obstacles (trees/decor: image objects whose `mask` is
`pygame.mask.from_surface(image)`, smaller than their bounding rect --
[tmx_layout_manager.py](tmx_layout_manager.py) :1052/:1060). The client collides
the player against that *mask*; a rect-only server would push a position the
client legitimately allowed in the obstacle's transparent area back out, and the
*other* client would see that as a pop. B2.5 ships those masks so the server
gates on the same silhouette the client does -- eliminating the false correction.

Only irregular masks travel (see `is_irregular`): a solid wall tile's mask equals
its rect, so the rect already says everything. Format: row-major bitfield
(`numpy.packbits`, bit i = y*width + x).

Split by side so neither depends on global pygame *display* state:
- `pack_mask` (client, Code/) renders the pygame mask via `surfarray` -- the
  client always has a live display, so this is fast and safe there.
- `unpack_mask` (server, headless) returns a plain numpy boolean grid -- NO
  pygame surface/mask, so it can't segfault on a process whose SDL video was
  left in an odd state, and the server's overlap test is a numpy slice anyway.
One module owns the bit convention so the two sides can never drift.
"""

import numpy
import pygame


def is_irregular(mask, width, height) -> bool:
    """True iff `mask` has transparent pixels its bounding rect would wrongly
    treat as solid -- i.e. it's worth shipping. Returns False for no mask, a
    full-coverage mask (solid tile: rect is already exact), or a mask whose
    size doesn't match the rect (treat as a plain rect -- safe, and the
    server's overlap offset convention assumes mask-aligned-to-rect)."""
    if mask is None:
        return False
    if mask.get_size() != (int(width), int(height)):
        return False
    return mask.count() < int(width) * int(height)


def pack_mask(mask) -> bytes:
    """Pack a `pygame.mask.Mask` into a row-major bitfield (bit i = y*w + x).

    Exact and fast (no per-pixel Python): render the mask to a surface, read its
    red channel as a numpy array, and `packbits`. Inverse of `unpack_mask`.
    """
    width, height = mask.get_size()
    surface = mask.to_surface(setcolor=(255, 0, 0, 255), unsetcolor=(0, 0, 0, 255))
    set_pixels = pygame.surfarray.array_red(surface) > 127  # (w, h) bool
    return numpy.packbits(set_pixels.T.ravel()).tobytes()    # row-major y*w + x


def unpack_mask(width, height, packed) -> "numpy.ndarray":
    """Rebuild the silhouette `pack_mask` shipped as a (height, width) boolean
    grid: `grid[y, x]` is True where the obstacle is solid. No pygame surface or
    mask -- pure numpy, so it's headless- and global-state-safe.
    """
    width, height = int(width), int(height)
    bits = numpy.unpackbits(numpy.frombuffer(packed, dtype=numpy.uint8), count=width * height)
    return bits.astype(bool).reshape((height, width))        # row-major -> (h, w)


def rect_hits_mask(grid, mask_left, mask_top, rect) -> bool:
    """True if `rect` covers any solid pixel of an obstacle whose `grid`
    (from `unpack_mask`) sits with its top-left at (`mask_left`, `mask_top`) in
    the same coordinate space as `rect`. The rect is treated as fully solid (the
    player's hitbox) -- the server's stand-in for the per-frame player mask.
    """
    height, width = grid.shape
    col0 = max(0, int(rect.left) - int(mask_left))
    row0 = max(0, int(rect.top) - int(mask_top))
    col1 = min(width, int(rect.right) - int(mask_left))
    row1 = min(height, int(rect.bottom) - int(mask_top))
    if col0 >= col1 or row0 >= row1:
        return False
    return bool(grid[row0:row1, col0:col1].any())
