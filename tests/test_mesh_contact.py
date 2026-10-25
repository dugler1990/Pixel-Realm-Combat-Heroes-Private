"""Headless checks for 3D ground-frame mesh contact."""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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

from Settings import VIEW_ELEVATION_DEG  # noqa: E402
from body_contact import (  # noqa: E402
    Body,
    closest_points_segments,
    collision_body,
    ground_to_screen,
    mesh_contact,
    model_to_ground,
)
from hashRect import HashableRect  # noqa: E402
from mesh_boss import (  # noqa: E402
    MeshBoss,
    MeshBossPack,
    build_body_mask,
    project_model_points,
)

DEMON_PACK = REPO_ROOT / "Graphics" / "Meshes" / "demon"
DEMON_BODY = DEMON_PACK / "body.json"

pytestmark = pytest.mark.skipif(
    not DEMON_BODY.exists(),
    reason="run tools/boss_sprite_pipeline/bake_body_capsules.py demon first",
)


def _reference_project(points, pivot, facing_deg, scale, elevation_deg=45.0):
    """Frozen copy of project_model_points as it stood before the ground rewrite."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim == 1:
        pts = pts.reshape(1, 3)
    pivot = np.asarray(pivot, dtype=np.float64)
    yaw = math.radians(float(facing_deg))
    cy, sy = math.cos(yaw), math.sin(yaw)
    elev = math.radians(float(elevation_deg))
    ce, se = math.cos(elev), math.sin(elev)
    p = pts - pivot
    xr = p[:, 0] * cy - p[:, 1] * sy
    yr = p[:, 0] * sy + p[:, 1] * cy
    sx = xr * float(scale)
    sy_ = -(p[:, 2] * ce + yr * se) * float(scale)
    return np.column_stack([sx, sy_])


def test_projection_lock():
    rng = np.random.default_rng(0)
    pivot = np.array([0.1, -0.2, 0.05], dtype=np.float64)
    scale = 1020.7
    points = rng.normal(size=(50, 3))
    for facing in (0, 37, 90, 211):
        for elev in (30, 45, 60):
            ref = _reference_project(points, pivot, facing, scale, elev)
            via_ground = ground_to_screen(
                model_to_ground(points, pivot, facing, scale), elev
            )
            via_project = project_model_points(points, pivot, facing, scale, elev)
            assert np.allclose(via_ground, ref, atol=1e-9)
            assert np.allclose(via_project, ref, atol=1e-9)


def _upright_direct(feet_xy, height, radius):
    """Direct Body in ground pixels (no upright_body / world)."""
    r = float(radius)
    h = float(height)
    fx, fy = float(feet_xy[0]), float(feet_xy[1])
    A = np.array([[fx, fy, r]], dtype=np.float64)
    B = np.array([[fx, fy, max(r, h - r)]], dtype=np.float64)
    R = np.array([r], dtype=np.float64)
    return Body(A, B, R, np.array([fx, fy], dtype=np.float64))


def test_overhead_shin():
    shin = Body(
        np.array([[0.0, 0.0, 10.0]]),
        np.array([[0.0, 150.0, 300.0]]),
        np.array([15.0]),
        np.array([0.0, 0.0]),
    )
    under = _upright_direct((0.0, 150.0), 100.0, 15.0)
    c_under = mesh_contact(under, shin, VIEW_ELEVATION_DEG)
    assert not c_under.touching

    at_foot = _upright_direct((0.0, 20.0), 100.0, 15.0)
    c_foot = mesh_contact(at_foot, shin, VIEW_ELEVATION_DEG)
    assert c_foot.touching


def test_normal_direction():
    pillar = Body(
        np.array([[0.0, 0.0, 15.0]]),
        np.array([[0.0, 0.0, 100.0]]),
        np.array([15.0]),
        np.array([0.0, 0.0]),
    )
    player = _upright_direct((20.0, 0.0), 100.0, 10.0)
    c = mesh_contact(player, pillar, VIEW_ELEVATION_DEG)
    assert c.touching
    assert c.normal is not None
    assert c.normal[0] > 0


def test_degenerate_segments():
    # Zero-length (sphere) vs vertical segment: distance is horizontal gap.
    sphere = Body(
        np.array([[0.0, 0.0, 50.0]]),
        np.array([[0.0, 0.0, 50.0]]),
        np.array([5.0]),
        np.array([0.0, 0.0]),
    )
    seg = Body(
        np.array([[10.0, 0.0, 0.0]]),
        np.array([[10.0, 0.0, 100.0]]),
        np.array([5.0]),
        np.array([10.0, 0.0]),
    )
    C1, C2, dist = closest_points_segments(
        sphere.A[:, None, :],
        sphere.B[:, None, :],
        seg.A[None, :, :],
        seg.B[None, :, :],
    )
    assert abs(float(dist[0, 0]) - 10.0) < 1e-6

    # Two parallel vertical capsules 30 apart.
    a = Body(
        np.array([[0.0, 0.0, 0.0]]),
        np.array([[0.0, 0.0, 100.0]]),
        np.array([5.0]),
        np.array([0.0, 0.0]),
    )
    b = Body(
        np.array([[30.0, 0.0, 0.0]]),
        np.array([[30.0, 0.0, 100.0]]),
        np.array([5.0]),
        np.array([30.0, 0.0]),
    )
    _, _, dist2 = closest_points_segments(
        a.A[:, None, :], a.B[:, None, :], b.A[None, :, :], b.B[None, :, :]
    )
    assert abs(float(dist2[0, 0]) - 30.0) < 1e-6


def test_south_of_feet_real_demon():
    pack = MeshBossPack.get("demon")
    height_px = pack.height_units * 1020.7
    scale = height_px / pack.height_units
    E = VIEW_ELEVATION_DEG
    facing = 0.0
    player_height_true = 100.0
    # Wide enough that a filled 2r x reach mask still hits the silhouette south of the feet.
    player_r = 50.0
    ce = math.cos(math.radians(E))
    collision_reach = player_height_true * ce

    A_m, B_m = pack.posed_capsule_ends(0)
    Ag = model_to_ground(A_m, pack.pivot, facing, scale)
    Bg = model_to_ground(B_m, pack.pivot, facing, scale)
    R = pack.capsule_radii * scale
    demon = Body(Ag.copy(), Bg.copy(), R.copy(), np.array([0.0, 0.0]))

    # Southernmost ground extent of capsules whose meat is below player height.
    south = -1e9
    for i in range(len(R)):
        for end in (Ag[i], Bg[i]):
            if end[2] - R[i] <= player_height_true:
                south = max(south, float(end[1]) + float(R[i]))
        for t in np.linspace(0.0, 1.0, 8):
            p = Ag[i] * (1 - t) + Bg[i] * t
            if p[2] <= player_height_true:
                south = max(south, float(p[1]) + float(R[i]))

    assert south > -1e8
    player_fy = south + player_r + 5.0
    player = _upright_direct((0.0, player_fy), player_height_true, player_r)

    demon_mask, dx, dy = build_body_mask(pack, 0, facing, scale, E)
    pw = max(1, int(round(2 * player_r)))
    ph = max(1, int(round(collision_reach)))
    player_mask = pygame.mask.Mask((pw, ph), fill=True)

    def _screen_overlap(fy):
        feet_screen = ground_to_screen(np.array([[0.0, fy, 0.0]]), E)[0]
        player_tl_x = feet_screen[0] - pw / 2.0
        player_tl_y = feet_screen[1] - ph
        offset = (int(round(player_tl_x - dx)), int(round(player_tl_y - dy)))
        return demon_mask.overlap_area(player_mask, offset)

    # If just-past-south is empty on screen, walk north to a spot that still
    # overlaps on screen while staying south of the feet (fy > 0).
    if _screen_overlap(player_fy) == 0:
        fy = player_fy
        found = False
        while fy > 1.0:
            fy -= 2.0
            if _screen_overlap(fy) > 0:
                player_fy = fy
                player = _upright_direct((0.0, player_fy), player_height_true, player_r)
                found = True
                break
        assert found, "no south-of-feet position with screen-mask overlap"

    assert player_fy > 0.0
    assert _screen_overlap(player_fy) > 0
    c = mesh_contact(player, demon, E)
    assert not c.touching


def test_demon_vs_demon():
    pack = MeshBossPack.get("demon")
    height_px = pack.height_units * 1020.7
    scale = height_px / pack.height_units
    E = VIEW_ELEVATION_DEG
    A_m, B_m = pack.posed_capsule_ends(0)
    Ag = model_to_ground(A_m, pack.pivot, 0.0, scale)
    Bg = model_to_ground(B_m, pack.pivot, 0.0, scale)
    R = pack.capsule_radii * scale

    max_x = 0.0
    for i in range(len(R)):
        max_x = max(max_x, abs(float(Ag[i, 0])) + float(R[i]))
        max_x = max(max_x, abs(float(Bg[i, 0])) + float(R[i]))

    gap = 2.0 * max_x + 20.0
    a = Body(Ag.copy(), Bg.copy(), R.copy(), np.array([0.0, 0.0]))
    b_far = Body(
        Ag + np.array([gap, 0.0, 0.0]),
        Bg + np.array([gap, 0.0, 0.0]),
        R.copy(),
        np.array([gap, 0.0]),
    )
    assert not mesh_contact(a, b_far, E).touching

    # Modest overlap along x so the deepest pair's horizontal normal points toward self.
    near = 2.0 * max_x - 50.0
    b_near = Body(
        Ag + np.array([near, 0.0, 0.0]),
        Bg + np.array([near, 0.0, 0.0]),
        R.copy(),
        np.array([near, 0.0]),
    )
    c = mesh_contact(a, b_near, E)
    assert c.touching
    assert c.normal is not None
    assert c.normal[0] < 0


def test_bare_snapshot():
    pack = MeshBossPack.get("demon")
    boss = MeshBoss("demon")
    height_px = pack.height_units * 1020.7
    E = VIEW_ELEVATION_DEG
    demon = SimpleNamespace(
        mesh_boss=boss,
        mesh_height_px=height_px,
        hitbox=pygame.Rect(0, 0, 40, 40),
        get_facing_deg=lambda: 0.0,
    )
    demon.hitbox.midbottom = (100, 200)
    snap = HashableRect(pygame.Rect(50, 50, 40, 80), _id=7)
    body = collision_body(snap, E)
    assert body.A.shape[0] == 1
    mesh_contact(collision_body(demon, E), body, E)  # must not raise


def test_determinism():
    shin = Body(
        np.array([[0.0, 0.0, 10.0]]),
        np.array([[0.0, 150.0, 300.0]]),
        np.array([15.0]),
        np.array([0.0, 0.0]),
    )
    player = _upright_direct((0.0, 20.0), 100.0, 15.0)
    a = mesh_contact(player, shin, VIEW_ELEVATION_DEG)
    b = mesh_contact(player, shin, VIEW_ELEVATION_DEG)
    assert a.touching == b.touching
    assert a.normal == b.normal
    assert np.array_equal(a.a_hits, b.a_hits)


def test_sprite_sprite_untouched(monkeypatch):
    from Entity import Entity

    def boom(*_a, **_k):
        raise RuntimeError("mesh_contact should not run for sprite-sprite")

    monkeypatch.setattr("body_contact.mesh_contact", boom)

    self_e = SimpleNamespace(
        mesh_boss=None,
        mask=pygame.mask.Mask((20, 40), fill=True),
        rect=pygame.Rect(0, 0, 20, 40),
        hitbox=pygame.Rect(0, 0, 20, 20),
        direction=pygame.math.Vector2(0, 0),
        type="player",
        combat_config={},
        benchmark_runtime=SimpleNamespace(enabled=False),
        _apply_mask_collision_min_deflect=Entity._apply_mask_collision_min_deflect,
        _use_mask_entity_collision_normal=lambda self=None: False,
        _mask_collision_push_normal=Entity._mask_collision_push_normal,
        _apply_entity_displacement=lambda *a, **k: None,
        _apply_benchmark_pushback_tuners=lambda self, x: x,
    )
    # Bind unbound methods properly
    other = HashableRect(
        pygame.Rect(100, 0, 20, 40),
        _id=2,
        direction=pygame.math.Vector2(0, 0),
        mask=pygame.mask.Mask((20, 40), fill=True),
    )
    # Far apart — no overlap; must not call mesh_contact
    Entity._resolve_entity_collision_legacy(
        self_e,
        other,
        None,
        self_e.rect,
        self_e.hitbox,
        self_e.mask,
        self_e.rect.centerx,
        self_e.rect.centery,
        0.0,
        20 * 40,
        1.0,
        1.0,
        4,
    )
