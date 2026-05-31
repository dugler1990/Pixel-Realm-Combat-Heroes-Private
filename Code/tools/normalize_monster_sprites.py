#!/usr/bin/env python3
"""Rewrite monster animation PNGs so opaque body size is consistent on each canvas."""

import argparse
import os
import sys

import pygame

_CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from Support import _animation_frame_sort_key, normalize_animation_frame  # noqa: E402

_PROJECT_ROOT = os.path.dirname(_CODE_DIR)
_DEFAULT_MONSTERS = ("eskimo_worker",)


def _process_folder(folder, *, dry_run=False):
    changed = 0
    for root, _dirs, files in os.walk(folder):
        pngs = [f for f in files if f.lower().endswith(".png")]
        if not pngs:
            continue
        for filename in sorted(pngs, key=_animation_frame_sort_key):
            path = os.path.join(root, filename)
            surf = pygame.image.load(path).convert_alpha()
            normalized = normalize_animation_frame(surf)
            if surf.get_size() != normalized.get_size():
                continue
            if pygame.image.tostring(surf, "RGBA") == pygame.image.tostring(
                normalized, "RGBA"
            ):
                continue
            changed += 1
            if not dry_run:
                pygame.image.save(normalized, path)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "monsters",
        nargs="*",
        default=list(_DEFAULT_MONSTERS),
        help=f"Monster folder names under Graphics/Monsters (default: {_DEFAULT_MONSTERS})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write files")
    args = parser.parse_args()

    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    total = 0
    monsters_root = os.path.join(_PROJECT_ROOT, "Graphics", "Monsters")
    for monster in args.monsters:
        folder = os.path.join(monsters_root, monster)
        if not os.path.isdir(folder):
            print(f"skip missing: {folder}", file=sys.stderr)
            continue
        count = _process_folder(folder, dry_run=args.dry_run)
        total += count
        action = "would update" if args.dry_run else "updated"
        print(f"{action} {count} frames in {monster}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
