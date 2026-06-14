"""Auto-crop transparent padding BELOW the feet from sprite frames.

Writes to a COPY (dst) — never touches the source. Sprites are centered on their hitbox,
and hitbox = rect.inflate(0, -10), so a sprite floats above its shadow by exactly its
bottom transparent padding (minus the 5px inset). Removing that bottom padding grounds it.

We trim ONLY the bottom (down to the lowest opaque row across all of an animation's
frames). Top and sides are left untouched: they don't affect grounding, and trimming them
unequally between animations of differing width would shift the sprite horizontally.

    python3 crop_sprite_padding.py <src_dir> <dst_dir>
"""
import os
import sys
import pygame

pygame.display.init()
pygame.display.set_mode((1, 1))


def union_bbox(frames):
    bb = None
    for f in frames:
        for r in pygame.mask.from_surface(f).get_bounding_rects():
            bb = r if bb is None else bb.union(r)
    return bb


def crop_tree(src, dst):
    for root, _dirs, files in os.walk(src):
        pngs = sorted(f for f in files if f.lower().endswith(".png"))
        rel = os.path.relpath(root, src)
        out = os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        if not pngs:
            continue
        frames = [pygame.image.load(os.path.join(root, f)).convert_alpha() for f in pngs]
        bb = union_bbox(frames)
        w, h = frames[0].get_size()
        if bb is None or bb.bottom >= h:    # nothing below the feet — copy unchanged
            for f, fr in zip(pngs, frames):
                pygame.image.save(fr, os.path.join(out, f))
            continue
        box = pygame.Rect(0, 0, w, bb.bottom)   # full width, full top, trim bottom only
        for f, fr in zip(pngs, frames):
            pygame.image.save(fr.subsurface(box).copy(), os.path.join(out, f))
        print(f"{rel:>40}: {w}x{h} -> {w}x{bb.bottom}  trimmed bottom {h-bb.bottom}px")


if __name__ == "__main__":
    crop_tree(sys.argv[1], sys.argv[2])
