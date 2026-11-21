"""Role match and fit. No Blender."""
from pathlib import Path

import pytest

from tools.boss_sprite_pipeline.rigmap import (
    apply_patch, edits, fit, knob_env, label_bvh, label_roles, load_bvh, match,
)
from tools.boss_sprite_pipeline.rigmap.fit import AXIS_SKIP_DEG
from tools.boss_sprite_pipeline.rigmap.label import bone_names
from tools.boss_sprite_pipeline.rigmap.legacy import ANUN_PATHS, SOMA_PATHS

BOSS = Path(r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated")

BVH = """HIERARCHY
ROOT Root
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
  JOINT Hips
  {
    OFFSET 0 100 0
    CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
    JOINT Spine1
    {
      OFFSET 5 0 0
      CHANNELS 3 Zrotation Yrotation Xrotation
      JOINT Spine2
      {
        OFFSET 5 0 0
        CHANNELS 3 Zrotation Yrotation Xrotation
        JOINT Chest
        {
          OFFSET 5 0 0
          CHANNELS 3 Zrotation Yrotation Xrotation
          JOINT Neck1
          {
            OFFSET 4 0 0
            CHANNELS 3 Zrotation Yrotation Xrotation
            JOINT Neck2
            {
              OFFSET 2 0 0
              CHANNELS 3 Zrotation Yrotation Xrotation
              JOINT Head
              {
                OFFSET 3 0 0
                CHANNELS 3 Zrotation Yrotation Xrotation
                JOINT Jaw
                {
                  OFFSET 0 -2 1
                  CHANNELS 3 Zrotation Yrotation Xrotation
                }
                JOINT LeftEye
                {
                  OFFSET 1 2 2
                  CHANNELS 3 Zrotation Yrotation Xrotation
                }
                JOINT RightEye
                {
                  OFFSET 1 2 -2
                  CHANNELS 3 Zrotation Yrotation Xrotation
                }
              }
            }
          }
          JOINT LeftShoulder
          {
            OFFSET 0 2 8
            CHANNELS 3 Zrotation Yrotation Xrotation
            JOINT LeftArm
            {
              OFFSET 10 0 0
              CHANNELS 3 Zrotation Yrotation Xrotation
              JOINT LeftForeArm
              {
                OFFSET 10 0 0
                CHANNELS 3 Zrotation Yrotation Xrotation
                JOINT LeftHand
                {
                  OFFSET 8 0 0
                  CHANNELS 3 Zrotation Yrotation Xrotation
                }
              }
            }
          }
          JOINT RightShoulder
          {
            OFFSET 0 2 -8
            CHANNELS 3 Zrotation Yrotation Xrotation
            JOINT RightArm
            {
              OFFSET 10 0 0
              CHANNELS 3 Zrotation Yrotation Xrotation
              JOINT RightForeArm
              {
                OFFSET 10 0 0
                CHANNELS 3 Zrotation Yrotation Xrotation
                JOINT RightHand
                {
                  OFFSET 8 0 0
                  CHANNELS 3 Zrotation Yrotation Xrotation
                }
              }
            }
          }
        }
      }
    }
    JOINT LeftLeg
    {
      OFFSET -5 -20 4
      CHANNELS 3 Zrotation Yrotation Xrotation
      JOINT LeftShin
      {
        OFFSET 0 -20 0
        CHANNELS 3 Zrotation Yrotation Xrotation
        JOINT LeftFoot
        {
          OFFSET 0 -18 0
          CHANNELS 3 Zrotation Yrotation Xrotation
          JOINT LeftToeBase
          {
            OFFSET 0 -2 6
            CHANNELS 3 Zrotation Yrotation Xrotation
          }
        }
      }
    }
    JOINT RightLeg
    {
      OFFSET -5 -20 -4
      CHANNELS 3 Zrotation Yrotation Xrotation
      JOINT RightShin
      {
        OFFSET 0 -20 0
        CHANNELS 3 Zrotation Yrotation Xrotation
        JOINT RightFoot
        {
          OFFSET 0 -18 0
          CHANNELS 3 Zrotation Yrotation Xrotation
          JOINT RightToeBase
          {
            OFFSET 0 -2 6
            CHANNELS 3 Zrotation Yrotation Xrotation
          }
        }
      }
    }
  }
}
MOTION
Frames: 0
"""

DEMON = {
    "root": "bone_0", "spine": "bone_1", "chest": "bone_12",
    "neck": "bone_13", "head": "bone_34",
    "arm_l": {"shoulder": "bone_14", "elbow": "bone_15", "wrist": "bone_16", "hand": "bone_17",
              "fingers": ["bone_18"]},
    "arm_r": {"shoulder": "bone_19", "elbow": "bone_20", "wrist": "bone_21", "hand": "bone_22"},
    "leg_l": {"hip": "bone_2", "knee": "bone_3", "ankle": "bone_4", "foot": "bone_5"},
    "leg_r": {"hip": "bone_7", "knee": "bone_8", "ankle": "bone_9", "foot": "bone_10"},
}

BARB = {
    "root": "bone_0", "spine": "bone_1", "spine2": "bone_2", "chest": "bone_3",
    "neck": "bone_4", "head": "bone_5",
    "arm_l": {"shoulder": "bone_6", "elbow": "bone_7", "wrist": "bone_8", "hand": "bone_9",
              "fingers": ["bone_f"]},
    "arm_r": {"shoulder": "bone_13", "elbow": "bone_14", "wrist": "bone_15", "hand": "bone_16"},
    "leg_l": {"hip": "bone_20", "knee": "bone_21", "ankle": "bone_22", "foot": "bone_23"},
    "leg_r": {"hip": "bone_24", "knee": "bone_25", "ankle": "bone_26", "foot": "bone_27"},
}

DEMON_20 = {
    "root", "spine", "chest", "head",
    "clavicle.L", "upper_arm.L", "forearm.L", "hand.L",
    "clavicle.R", "upper_arm.R", "forearm.R", "hand.R",
    "thigh.L", "shin.L", "ankle.L", "foot.L",
    "thigh.R", "shin.R", "ankle.R", "foot.R",
}
HUMAN_22 = DEMON_20 | {"spine2", "neck"}


def _soma():
    sk = load_bvh(BVH)
    roles = label_bvh(sk.names, "soma")
    return sk, roles


def test_bvh_rest_places_the_hips_above_the_root():
    sk = load_bvh(BVH)
    assert sk.world["Hips"][1] == 100
    assert "Jaw" in sk.names and "LeftEye" in sk.names


def test_soma_labels_eyes_and_jaw():
    sk, roles = _soma()
    assert roles["LeftEye"] == "eye.L"
    assert roles["Jaw"] == "jaw"
    assert roles["Neck2"] == "neck2"
    assert roles["Head"] == "head"


def test_demon_pairs_are_the_locked_twenty_and_head_lands_on_neck():
    _, src = _soma()
    dst = label_roles(DEMON, "creature")
    got = match(src, dst, bone_names(DEMON))
    assert set(got["roles"]) == DEMON_20
    head = next(p for p in got["paired"] if p["role"] == "head")
    assert head["source"] == "Head"
    assert head["target"] == "bone_13"          # the file's key "neck"
    assert "bone_34" in got["unmapped"]         # the file's key "head", the snout
    assert "spine2" in got["missing"] and "neck" in got["missing"]
    assert "eye.L" in got["missing"] and "jaw" in got["missing"]


def test_barb_pairs_are_the_locked_twenty_two_and_eyes_and_jaw_are_missing():
    _, src = _soma()
    dst = label_roles(BARB, "human")
    got = match(src, dst, bone_names(BARB))
    assert set(got["roles"]) == HUMAN_22
    assert {"eye.L", "eye.R", "jaw", "neck2"} <= set(got["missing"])
    assert "bone_f" in got["unmapped"]
    neck = next(p for p in got["paired"] if p["role"] == "neck")
    assert neck["target"] == "bone_4"


def test_legacy_paths_match_those_sets():
    assert len(SOMA_PATHS) == 20
    assert SOMA_PATHS["Head"] == ("neck",)
    assert "Spine2" not in SOMA_PATHS and "Neck1" not in SOMA_PATHS
    assert len(ANUN_PATHS) == 22
    assert ANUN_PATHS["Head"] == ("head",)
    assert ANUN_PATHS["Neck1"] == ("neck",)
    assert ANUN_PATHS["Spine2"] == ("spine2",)


def test_wider_shoulders_keep_their_width_and_short_arms_change_reach():
    roles = ["clavicle.L", "clavicle.R", "upper_arm.L", "forearm.L", "hand.L",
             "upper_arm.R", "forearm.R", "hand.R", "head", "foot.L"]
    paired = [{"role": r, "source": "s_" + r, "target": "t_" + r} for r in roles]
    src = {
        "s_clavicle.L": (0, 10, -1), "s_clavicle.R": (0, 10, 1),
        "s_upper_arm.L": (0, 10, -2), "s_forearm.L": (0, 10, -4), "s_hand.L": (0, 10, -5),
        "s_upper_arm.R": (0, 10, 2), "s_forearm.R": (0, 10, 4), "s_hand.R": (0, 10, 5),
        "s_head": (0, 18, 0), "s_foot.L": (0, 0, 0),
    }
    dst = {
        "t_clavicle.L": (0, 10, -4), "t_clavicle.R": (0, 10, 4),   # wider than the source: ratio clamps to 1
        "t_upper_arm.L": (0, 10, -4.2), "t_forearm.L": (0, 10, -4.7), "t_hand.L": (0, 10, -5.0),
        "t_upper_arm.R": (0, 10, 4.2), "t_forearm.R": (0, 10, 4.7), "t_hand.R": (0, 10, 5.0),
        "t_head": (0, 18, 0), "t_foot.L": (0, 0, 0),
    }
    f = fit({"paired": paired}, src, dst, "human")
    assert f["barrel_chest"]["measured"] == 1.0
    assert f["limb_reach"]["measured"] < 1
    assert f["arm_cap"]["measured"] == 90.0
    creature = fit({"paired": paired}, src, dst, "creature")
    assert creature["arm_cap"]["measured"] == 35.0


def test_a_crossed_head_axis_is_bind_skipped():
    _, src_roles = _soma()
    sk = load_bvh(BVH)
    dst_roles = label_roles(BARB, "human")
    got = match(src_roles, dst_roles)
    src_w = {p["source"]: sk.world[p["source"]] for p in got["paired"]}
    dst_w = {}
    for p in got["paired"]:
        x, y, z = sk.world[p["source"]]
        if p["role"] in ("neck", "head"):
            x, y = y, x
        dst_w[p["target"]] = (x, y, z)
    f = fit(got, src_w, dst_w, "human")
    assert "head" in f["bind_skip"] or "neck" in f["bind_skip"]
    assert AXIS_SKIP_DEG == 45.0


def test_human_recipe_adds_eyes_and_jaw_and_the_creature_recipe_adds_nothing():
    sk, src = _soma()
    barb = match(src, label_roles(BARB, "human"), bone_names(BARB))
    added = edits(barb, src, sk.world, "human")
    assert {e["role"] for e in added} == {"eye.L", "eye.R", "jaw"}
    assert all(e["parent"] == "head" and e["op"] == "add_bone" for e in added)
    assert not any(e["role"] == "neck2" for e in added)
    demon = match(src, label_roles(DEMON, "creature"), bone_names(DEMON))
    assert edits(demon, src, sk.world, "creature") == []


def test_knobs_face_the_bake_the_right_way():
    env = knob_env({"barrel_chest": 1, "arm_cap": 90, "bind_match": False})
    assert env["CLAVICLE_DAMP"] == "0.0000"
    assert env["ARM_ELEV_CAP"] == "90.0"
    assert env["BIND_MATCH"] == "0"
    patched = apply_patch({"barrel_chest": {"measured": 0.4, "override": None}}, {"barrel_chest": 1})
    assert patched["barrel_chest"]["override"] == 1
    assert "IK_BODY" not in env


@pytest.mark.skipif(not (BOSS / "bosses" / "barb" / "gear_test" / "barb_roles.json").is_file(),
                    reason="barb roles live on the Boss tree")
def test_real_barb_and_demon_files_and_a_real_walk():
    import json
    barb = json.loads((BOSS / "bosses" / "barb" / "gear_test" / "barb_roles.json").read_text(encoding="utf-8"))
    demon = json.loads((BOSS / "bosses" / "demon" / "rig" / "jaw" / "bone_roles.json").read_text(encoding="utf-8"))
    walk = BOSS / "bosses" / "kimodo_new_blender" / "walk_v1_00.bvh"
    sk = load_bvh(walk.read_text(encoding="utf-8", errors="replace"))
    src = label_bvh(sk.names, "soma")
    assert src["LeftEye"] == "eye.L" and src["Jaw"] == "jaw"
    barb_m = match(src, label_roles(barb, "human"), bone_names(barb))
    demon_m = match(src, label_roles(demon, "creature"), bone_names(demon))
    assert set(barb_m["roles"]) == HUMAN_22
    assert {"eye.L", "eye.R", "jaw"} <= set(barb_m["missing"])
    assert set(demon_m["roles"]) == DEMON_20
    head = next(p for p in demon_m["paired"] if p["role"] == "head")
    assert head["target"] == demon["neck"]
