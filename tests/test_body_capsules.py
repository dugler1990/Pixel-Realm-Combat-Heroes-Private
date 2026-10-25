"""Headless checks for mesh body capsules (no display / no GL draw)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
os.chdir(CODE_DIR)

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from mesh_boss import (  # noqa: E402
    BODY_MASK_CACHE,
    MeshBoss,
    MeshBossPack,
    build_body_mask,
    capsule_screen_bounds,
    sha1_file,
    _pose_capsule_ends,
)
from combat_unit import CombatUnit  # noqa: E402

DEMON_PACK = REPO_ROOT / "Graphics" / "Meshes" / "demon"
DEMON_BODY = DEMON_PACK / "body.json"
DEMON_SKIN = DEMON_PACK / "skin.npz"

pytestmark = pytest.mark.skipif(
    not DEMON_BODY.exists(),
    reason="run tools/boss_sprite_pipeline/bake_body_capsules.py demon first",
)


@pytest.fixture(autouse=True)
def _clear_caches():
    BODY_MASK_CACHE.clear()
    MeshBossPack.clear_cache()
    yield
    BODY_MASK_CACHE.clear()
    MeshBossPack.clear_cache()


def test_identical_mask_and_cache_hit():
    pack = MeshBossPack.get("demon")
    a = build_body_mask(pack, 0, 90.0, 1000.0, 45.0)
    b = build_body_mask(pack, 0, 90.0, 1000.0, 45.0)
    # Cache returns the same object on hit; also check identity of contents.
    assert a is b
    assert a[0].get_size() == b[0].get_size()
    assert a[0].count() == b[0].count()
    assert BODY_MASK_CACHE.builds == 1
    assert BODY_MASK_CACHE.hits == 1
    # A fresh clear + rebuild must match the first mask bit-for-bit via overlap.
    BODY_MASK_CACHE.clear()
    c = build_body_mask(pack, 0, 90.0, 1000.0, 45.0)
    assert c[0].get_size() == a[0].get_size()
    assert c[0].count() == a[0].count()
    assert c[0].overlap_area(a[0], (0, 0)) == a[0].count()
    assert c[1] == a[1] and c[2] == a[2]


def test_rest_pose_capsules_contain_owned_verts():
    pack = MeshBossPack.get("demon")
    data = np.load(DEMON_SKIN)
    rest = np.asarray(data["rest_pos"], dtype=np.float64)
    joints = np.asarray(data["joints"])
    weights = np.asarray(data["weights"], dtype=np.float64)
    owner = joints[np.arange(joints.shape[0]), np.argmax(weights, axis=1)].astype(np.int32)

    for cap in pack.capsules:
        pts = rest[owner == cap["bone"]]
        if pts.shape[0] == 0:
            continue
        a = cap["a"]
        b = cap["b"]
        axis = b - a
        length = float(np.linalg.norm(axis))
        if length < 1e-9:
            continue
        axis = axis / length
        # Distance to the finite capsule: clamp projection to the segment, then
        # radial distance. Require 90% of owned verts inside radius * 1.05.
        t = ((pts - a) @ axis)
        t = np.clip(t, 0.0, length)
        closest = a + np.outer(t, axis)
        dists = np.linalg.norm(pts - closest, axis=1)
        inside = dists <= (cap["radius"] * 1.05)
        assert float(inside.mean()) >= 0.90, (
            f"bone {cap['bone']}: only {inside.mean():.2%} of owned verts inside capsule"
        )


def test_missing_body_json_raises(tmp_path):
    # Copy pack without body.json into a temp mesh root and point MESH_ROOT at it.
    import mesh_boss as mb

    src = DEMON_PACK
    dst = tmp_path / "demon"
    dst.mkdir()
    for name in ("pack.json", "skin.npz", "albedo.png"):
        shutil.copy2(src / name, dst / name)
    old = mb.MESH_ROOT
    mb.MESH_ROOT = str(tmp_path)
    MeshBossPack.clear_cache()
    try:
        with pytest.raises(FileNotFoundError):
            MeshBossPack("demon")
    finally:
        mb.MESH_ROOT = old
        MeshBossPack.clear_cache()


def test_tampered_body_hash_raises(tmp_path):
    import mesh_boss as mb

    src = DEMON_PACK
    dst = tmp_path / "demon"
    dst.mkdir()
    for name in ("pack.json", "skin.npz", "albedo.png", "body.json"):
        shutil.copy2(src / name, dst / name)
    body = json.loads((dst / "body.json").read_text(encoding="utf-8"))
    body["skin_sha1"] = "0" * 40
    (dst / "body.json").write_text(json.dumps(body), encoding="utf-8")
    old = mb.MESH_ROOT
    mb.MESH_ROOT = str(tmp_path)
    MeshBossPack.clear_cache()
    try:
        with pytest.raises(ValueError, match="sha1"):
            MeshBossPack("demon")
    finally:
        mb.MESH_ROOT = old
        MeshBossPack.clear_cache()


def test_sprite_enemy_untouched_by_body_path():
    """A unit without mesh_boss keeps the sheet plant; no collision override."""
    assert "collision" not in CombatUnit.__dict__
    assert "_apply_collision_mask" not in CombatUnit.update.__code__.co_names
    assert "_apply_body_mask" not in CombatUnit.update.__code__.co_names
    assert "_apply_body_mask" not in CombatUnit.animate.__code__.co_names
    assert "mesh_boss" in CombatUnit.plant_sprite_on_hitbox.__code__.co_names
    assert "_sync_mesh_layout" in CombatUnit.animate.__code__.co_names


def test_capsule_bounds_match_mask_aabb():
    """Gameplay bounds AABB matches the tool-path mask size and offset."""
    pack = MeshBossPack.get("demon")
    frame, facing, scale, elev = 0, 45.0, 1000.0, 45.0
    dx, dy, w, h, ground_r = capsule_screen_bounds(pack, frame, facing, scale, elev)
    mask, mdx, mdy = build_body_mask(pack, frame, facing, scale, elev)
    assert mask.get_size() == (w, h)
    assert dx == mdx and dy == mdy
    assert ground_r > 0
    assert w > 0 and h > 0


def test_mesh_body_bounds_without_backend():
    boss = MeshBoss("demon")
    dx, dy, w, h, ground_r = boss.body_bounds(45.0, 850.0)
    assert w > 0 and h > 0
    assert ground_r > 0
    assert isinstance(dx, float) and isinstance(dy, float)
    # Tool path still available; not used by CombatUnit hot path.
    mask, mdx, mdy = boss.body_mask(45.0, 850.0)
    assert mask.get_size() == (w, h)
    assert mdx == dx and mdy == dy
    from render_backend import StubBackend

    stub = StubBackend(64, 64)
    assert stub.draw_mesh_boss(boss.pack, 0, (0, 0), 0.0, 1.0, 45.0, (0, 0, 1), 0.3) is False


def test_mesh_layout_does_not_rasterize_mask(monkeypatch):
    """CombatUnit mesh plant must never call build_body_mask / from_surface."""
    import mesh_boss as mb

    calls = {"build": 0}

    real_build = mb.build_body_mask

    def _counting_build(*args, **kwargs):
        calls["build"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(mb, "build_body_mask", _counting_build)

    boss = MeshBoss("demon")
    unit = object.__new__(CombatUnit)
    unit.mesh_boss = boss
    unit.mesh_height_px = 250.0
    unit._body_bounds = None
    unit._mesh_layout_key = None
    unit.mask = object()  # pretend animate() assigned a sheet mask
    unit.hitbox = pygame.Rect(100, 200, 20, 20)
    unit.hitbox.midbottom = (110, 220)
    unit.get_facing_deg = lambda: 90.0

    unit._sync_mesh_layout()
    unit.plant_sprite_on_hitbox()
    unit._sync_mesh_layout()  # sticky: same key, no recompute needed beyond mask clear
    unit.plant_sprite_on_hitbox()

    assert calls["build"] == 0
    assert unit.mask is None
    assert unit._body_bounds is not None
    assert unit.rect.width > 0 and unit.rect.height > 0
    assert unit.collision_reach_px >= 0
    assert unit.collision_ground_radius_px > 0