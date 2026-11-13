"""Mesh player (player_mesh.py): clip choice, facing, the barb pack, selection wiring, camera draw. No GL."""
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

import player_mesh  # noqa: E402
from body_contact import model_to_ground  # noqa: E402
from player_mesh import PlayerMesh, choose_clip, next_facing, yaw_for_heading  # noqa: E402


def test_choose_clip():
    assert choose_clip(True, True) == "attack"
    assert choose_clip(False, True) == "move"
    assert choose_clip(False, False) == "idle"


def test_facing_diagonals_and_latch():
    assert next_facing(90.0, 1, 1, False, "right") == pytest.approx(45.0)
    assert next_facing(90.0, -1, -1, False, "left") == pytest.approx(225.0)
    # Standing still, or a dash / leap zeroing the direction: the last heading stays.
    assert next_facing(225.0, 0, 0, False, "left_idle") == 225.0


def test_attack_snaps_to_its_4way_direction():
    # Up+right held: the status (and the weapon's placement) says right, so the swing faces right.
    assert next_facing(315.0, 1, -1, True, "right_attack") == 0.0
    assert next_facing(45.0, 0, 0, True, "down_idle") == 90.0


@pytest.mark.parametrize("heading", [0, 45, 90, 135, 180, 225, 270, 315])
def test_yaw_turns_the_model_forward_onto_the_heading(heading):
    fwd = math.radians(player_mesh.MODEL_FORWARD_DEG)
    tip = np.array([[math.cos(fwd), math.sin(fwd), 0.0]])
    g = model_to_ground(tip, np.zeros(3), yaw_for_heading(heading), 1.0)[0]
    assert math.degrees(math.atan2(g[1], g[0])) % 360 == pytest.approx(heading % 360, abs=1e-6)


@pytest.mark.parametrize("pack_name", ["barb", "barb_armour"])
def test_barb_pack_loads_with_its_clips(pack_name):
    mesh = PlayerMesh(pack_name, figure_px=56)
    ranges = mesh.skin.pack.ranges
    assert set(ranges) == {"idle", "move", "attack"}
    assert mesh.px_per_frame > 0
    # His rest pose facing the camera stands as tall on screen as the sprite figure.
    from mesh_boss import project_model_points
    pack = mesh.skin.pack
    scale = mesh.height_px / pack.height_units
    screen = project_model_points(pack.rest_pos, pack.pivot, yaw_for_heading(90.0), scale)
    assert float(np.ptp(screen[:, 1])) == pytest.approx(56, abs=0.5)


def _fake_player(**kw):
    p = SimpleNamespace(attacking=False, distance_moved=0.0, direction=pygame.math.Vector2(),
                        status="down_idle", attack_time=None, attack_cooldown=400, weapon="sword")
    p.__dict__.update(kw)
    return p


def test_move_is_phased_on_distance_and_attack_restarts():
    mesh = PlayerMesh("barb", figure_px=56)
    p = _fake_player(distance_moved=mesh.px_per_frame * 3, direction=pygame.math.Vector2(1, 1), status="right")
    mesh.update(p, 1 / 30)
    assert mesh.skin.action == "move" and mesh.skin.frame == pytest.approx(3.0)
    assert mesh.facing_deg == pytest.approx(45.0)

    p.attacking, p.attack_time, p.status = True, 1000, "right_attack"
    mesh.update(p, 1 / 30)
    assert mesh.skin.action == "attack" and 0 < mesh.skin.frame < 10
    for _ in range(40):                     # past the swing's 500 ms: holds its last frame
        mesh.update(p, 1 / 30)
    lo, hi = mesh.skin.pack.ranges["attack"]
    assert int(mesh.skin.frame) == hi - lo
    p.attack_time = 2000                    # the next swing starts from its first frame
    mesh.update(p, 1 / 30)
    assert mesh.skin.frame < 10


def test_missing_pack_stays_a_sprite():
    from Player import SpecificPlayer
    stub = SimpleNamespace(image=pygame.Surface((64, 63)), mesh_skin=None)
    SpecificPlayer._attach_mesh(stub, "no_such_pack")
    assert stub.mesh_skin is None
    SpecificPlayer._attach_mesh(stub, "barb")
    assert isinstance(stub.mesh_skin, PlayerMesh)


def test_selection_passes_mesh_pack():
    import PlayerSelection as PS
    i = PS.unlocked_player_names.index("barb_mesh")
    assert PS.unlocked_player_mesh_packs[i] == "barb"
    assert PS.unlocked_player_mesh_packs[PS.unlocked_player_names.index("barb_armour_mesh")] == "barb_armour"
    assert PS.unlocked_player_mesh_packs[PS.unlocked_player_names.index("barb")] is None
    sel = PS.PlayerSelection.__new__(PS.PlayerSelection)
    sel.game = SimpleNamespace(in_player_selection=True)
    sel.select_player(i)
    assert sel.selected_mesh_pack == "barb"
    sel.select_player(PS.unlocked_player_names.index("barb"))
    assert sel.selected_mesh_pack is None


class _Backend:
    def __init__(self, draws):
        self.draws = draws
        self.blits = []
        self.meshes = 0

    def draw_mesh_boss(self, *a):
        self.meshes += 1
        return self.draws

    def blit(self, img, pos, cache_key=None):
        self.blits.append(img)


def _camera(backend):
    from YsortCameraGroup import YSortCameraGroup
    cam = YSortCameraGroup.__new__(YSortCameraGroup)
    cam.backend = backend
    cam.offset = pygame.math.Vector2()
    return cam


def _mesh_sprite():
    img = pygame.Surface((64, 63), pygame.SRCALPHA)
    img.fill((255, 0, 0, 255))
    s = SimpleNamespace(image=img, rect=img.get_rect(), mask=pygame.mask.from_surface(img),
                        hitbox=img.get_rect(), mesh_skin=PlayerMesh("barb", figure_px=56))
    weapon = SimpleNamespace(image=img, sprite_type="weapon", owner=s)
    return s, weapon


def test_camera_draws_mesh_and_hides_its_weapon_picture():
    be = _Backend(draws=True)
    cam = _camera(be)
    player, weapon = _mesh_sprite()
    cam._draw_sorted_sprite(player, (0, 0))
    cam._draw_sorted_sprite(weapon, (0, 0))
    assert be.meshes == 1 and be.blits == []


def test_camera_falls_back_to_the_sprite_without_gpu():
    be = _Backend(draws=False)
    cam = _camera(be)
    player, weapon = _mesh_sprite()
    cam._draw_sorted_sprite(player, (0, 0))
    cam._draw_sorted_sprite(weapon, (0, 0))
    assert be.blits == [player.image, weapon.image]
