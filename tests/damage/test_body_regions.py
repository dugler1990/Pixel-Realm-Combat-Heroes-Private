"""Which region a hit lands on (damage chunk 4): Graphics/Meshes/barb/regions.json and body_regions.py."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

import body_regions as br  # noqa: E402
import defence_profile as dp  # noqa: E402
from mesh_boss import MeshBossPack, projected_capsules  # noqa: E402
from player_mesh import PlayerMesh  # noqa: E402

slot = dp.region_slot
PACK = MeshBossPack.get("barb")


def test_every_capsule_bone_has_a_region():
    bones = br.load_bone_regions(PACK)
    assert {c["bone"] for c in PACK.capsules} <= set(bones)


def test_regions_agree_with_the_rest_capsules():
    """Sides by the x of the capsule (+X is his left); trunk, legs and head in order of height."""
    bones = br.load_bone_regions(PACK)
    lo = float(PACK.bbox_lo[2])
    heights = {}
    for cap in PACK.capsules:
        region, side = bones[cap["bone"]]
        mid_x = (cap["a"][0] + cap["b"][0]) / 2
        if side == "l":
            assert mid_x > 0, (cap["bone"], region)
        elif side == "r":
            assert mid_x < 0, (cap["bone"], region)
        mid_z = (cap["a"][2] + cap["b"][2]) / 2 - lo
        heights.setdefault(region, []).append(mid_z)
    order = ["foot", "shin", "thigh", "waist", "torso", "neck", "head"]
    means = [sum(heights[r]) / len(heights[r]) for r in order]
    assert means == sorted(means), dict(zip(order, means))


def test_bad_regions_file_fails(tmp_path):
    fake = SimpleNamespace(root=str(tmp_path), name="fake", capsules=[{"bone": 0}, {"bone": 1}])
    (tmp_path / "regions.json").write_text(json.dumps({"version": 1, "bones": {"0": ["waist", None]}}))
    with pytest.raises(br.RegionsError, match=r"without a region: \[1\]"):
        br.load_bone_regions(fake)
    (tmp_path / "regions.json").write_text(json.dumps({"version": 1, "bones": {"0": ["forearm", None]}}))
    with pytest.raises(br.RegionsError, match="no region slot 'forearm'"):
        br.load_bone_regions(fake)


# --- the mesh hero -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def hero_skin():
    skin = PlayerMesh("barb", 64)
    skin.skin.set_action("idle")
    skin.facing_deg = 90.0          # facing down the screen, toward the camera
    return skin


def _capsule_mid(skin, bone):
    """World point at the middle of a bone's capsule, feet at (1000, 1000)."""
    scale = skin.height_px / PACK.height_units
    xy, _depth, radii, bones = projected_capsules(PACK, skin.skin.frame_index, round(skin.yaw_deg()) % 360, scale)
    i = bones.index(bone)
    a, b = xy[2 * i], xy[2 * i + 1]
    return (1000 + (a[0] + b[0]) / 2, 1000 + (a[1] + b[1]) / 2)


FEET = (1000, 1000)


# Facing the camera, the middle of these capsules shows that region. (Capsule middles near a fatter
# neighbour's end show the neighbour: the spine's under the chin is head, the shin's under the knee
# is thigh. The capsules are as fat as the body; region_map in the plan's log shows the whole figure.)
@pytest.mark.parametrize("bone, expected", [
    (5, slot("head")), (6, slot("chest")), (13, slot("chest")),
    (8, slot("forearm", "l")), (15, slot("forearm", "r")),
    (22, slot("foot", "l")), (26, slot("foot", "r")),
])
def test_capsule_middles_give_their_region(hero_skin, bone, expected):
    assert br.mesh_slot(hero_skin, FEET, _capsule_mid(hero_skin, bone)) == expected


def test_his_left_is_on_screen_right_when_he_faces_the_camera(hero_skin):
    left, right = _capsule_mid(hero_skin, 20), _capsule_mid(hero_skin, 24)
    assert left[0] > right[0]


def test_from_the_side_the_near_arm_is_hit_not_the_hidden_one(hero_skin):
    hero_skin.facing_deg = 0.0          # facing right: his right side is toward the camera
    try:
        assert br.mesh_slot(hero_skin, FEET, _capsule_mid(hero_skin, 15)) == slot("forearm", "r")
        assert br.mesh_slot(hero_skin, FEET, _capsule_mid(hero_skin, 8)) != slot("forearm", "l")
    finally:
        hero_skin.facing_deg = 90.0


def test_torso_is_chest_from_the_front_and_back_from_behind(hero_skin):
    point = _capsule_mid(hero_skin, 6)
    # He faces down (+y). An attack travelling up (-y) meets his front.
    assert br.mesh_slot(hero_skin, FEET, point, toward=(0, -12)) == slot("chest")
    assert br.mesh_slot(hero_skin, FEET, point, toward=(0, 12)) == slot("back")
    assert br.mesh_slot(hero_skin, FEET, point) == slot("chest")


def test_projection_is_kept_for_the_frame(hero_skin):
    br.mesh_slot(hero_skin, FEET, _capsule_mid(hero_skin, 5))
    kept = hero_skin._region_projection
    br.mesh_slot(hero_skin, FEET, _capsule_mid(hero_skin, 0))
    assert hero_skin._region_projection is kept
    hero_skin.facing_deg = 0.0
    br.mesh_slot(hero_skin, FEET, _capsule_mid(hero_skin, 0))
    assert hero_skin._region_projection is not kept
    hero_skin.facing_deg = 90.0


def test_hero_slot_uses_the_feet_the_camera_draws_at(hero_skin):
    hero = SimpleNamespace(mesh_skin=hero_skin, hitbox=pygame.Rect(980, 960, 40, 40),
                           sprite_anchor_px=(0, 0), rect=pygame.Rect(0, 0, 1, 1))
    assert br.hero_slot(hero, _capsule_mid(hero_skin, 5)) == slot("head")


# --- the sprite hero ---------------------------------------------------------------------

HITBOX = pygame.Rect(80, 100, 40, 100)   # feet at (100, 200), figure 100 px


@pytest.mark.parametrize("height, status, x, expected", [
    (95, "down", 100, slot("head")),
    (65, "down", 100, slot("neck")),
    (47, "down", 100, slot("waist")),
    (3, "down", 110, slot("foot", "l")),       # facing the camera: his left on screen right
    (3, "down", 90, slot("foot", "r")),
    (35, "up_idle", 110, slot("thigh", "r")),  # back to the camera: the reverse
    (15, "right_attack", 100, slot("shin", "r")),
    (15, "left", 100, slot("shin", "l")),
])
def test_sprite_bands(height, status, x, expected):
    assert br.sprite_slot(HITBOX, 100, (x, 200 - height), status) == expected


def test_sprite_torso_by_direction():
    assert br.sprite_slot(HITBOX, 100, (100, 145), "down", toward=(0, -10)) == slot("chest")
    assert br.sprite_slot(HITBOX, 100, (100, 145), "down", toward=(0, 10)) == slot("back")
