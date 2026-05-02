#!/usr/bin/env python3
"""
Write idle.png beside each hit_animation folder: first sorted PNG (same order as Support.import_folder).

Run from repo root: python3 tools/generate_chest_idle_from_hit.py

Requires pygame for saving surfaces (matches game load path). Uses Code/ cwd like the game.
"""
from __future__ import annotations

import json
import os
import sys

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_CODE = os.path.join(_REPO, "Code")
_PROFILES = os.path.join(_REPO, "levels", "tmx", "env_interactable_profiles.json")


def main() -> int:
    os.chdir(_CODE)
    sys.path.insert(0, _CODE)
    import pygame
    from Support import import_folder, resolve_env_interactable_path

    pygame.init()
    try:
        pygame.display.set_mode((1, 1), pygame.HIDDEN)
    except pygame.error:
        pass

    with open(_PROFILES, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    seen: set[str] = set()
    for profile_id, prof in profiles.items():
        raw = prof.get("hit_animation")
        if not raw or not str(raw).strip():
            continue
        s = str(raw).strip()
        if s in seen:
            continue
        seen.add(s)

        hit_path = resolve_env_interactable_path(s, None)
        if not hit_path or not os.path.isdir(hit_path):
            print(f"skip {profile_id}: not a directory: {hit_path!r}", file=sys.stderr)
            continue

        try:
            frames = import_folder(hit_path)
        except Exception as e:
            print(f"skip {profile_id}: import_folder {hit_path!r}: {e}", file=sys.stderr)
            continue

        if not frames:
            print(f"skip {profile_id}: empty {hit_path!r}", file=sys.stderr)
            continue

        parent = os.path.dirname(os.path.normpath(hit_path))
        out_path = os.path.join(parent, "idle.png")
        try:
            pygame.image.save(frames[0], out_path)
        except Exception as e:
            print(f"fail {profile_id} -> {out_path}: {e}", file=sys.stderr)
            continue
        print(f"{profile_id}: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
