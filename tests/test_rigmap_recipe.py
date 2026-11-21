"""The barb recipe must reproduce the bake graded good on 2026-11-15. No Blender."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.boss_sprite_pipeline.rigmap.recipe import RECIPES, bake_env, resolve

BARB_ROLES = {"root": "bone_0", "spine": "bone_1", "neck": "bone_4", "head": "bone_5",
              "arm_l": {"shoulder": "bone_6"}}
BARB_ROW = {"id": "barb", "recipe": "human", "source": "anunaki"}

# barb/anim_test/retarget_ik2/run.json, the IK bake in the ik_test2 viewer
GOLDEN = {
    "SOURCE": "anunaki",
    "RETARGET_MODE": "ik",
    "IK_BODY": "0.35",
    "BIND_MATCH": "1",
    "BIND_SKIP": "bone_0,bone_4",
    "BIND_REF": "frame1",
    "ARM_ELEV_CAP": "90.0",
    "CLAVICLE_DAMP": "1.0",
    "ROOT_LOC": "1",
}
GOLDEN_RUN = (Path(__file__).resolve().parents[2] / "Pixel-Realm-Combat-Heroes-Boss" / "generated"
              / "bosses" / "barb" / "anim_test" / "retarget_ik2" / "run.json")


def test_barb_recipe_is_the_graded_ik_bake():
    assert bake_env(resolve(BARB_ROW), BARB_ROLES) == GOLDEN


def test_the_panel_values_the_barb_has_saved_change_nothing():
    assert bake_env(resolve(BARB_ROW, {"bind_match": True, "arm_cap": 90}), BARB_ROLES) == GOLDEN


@pytest.mark.skipif(not GOLDEN_RUN.is_file(), reason="Boss worktree not next to this one")
def test_golden_matches_the_run_json_on_disk():
    run = json.loads(GOLDEN_RUN.read_text(encoding="utf-8"))
    assert run["mode"] == GOLDEN["RETARGET_MODE"]
    assert run["IK_BODY"] == float(GOLDEN["IK_BODY"])
    assert run["BIND_MATCH"] is True
    assert ",".join(run["BIND_SKIP"]) == GOLDEN["BIND_SKIP"]
    assert run["ARM_ELEV_CAP"] == float(GOLDEN["ARM_ELEV_CAP"])
    assert run["CLAVICLE_DAMP"] == float(GOLDEN["CLAVICLE_DAMP"])
    assert run["ROOT_LOC"] is True
    assert run["SOURCE"] == GOLDEN["SOURCE"]
    assert run["settings_from"]["bind_ref"]["value"] == GOLDEN["BIND_REF"]


def test_demon_keeps_what_the_page_sent_before():
    env = bake_env(resolve({"id": "demon", "recipe": "creature", "source": "soma"}), {})
    assert env["SOURCE"] == "soma"
    assert env["RETARGET_MODE"] == "rot"
    assert env["BIND_MATCH"] == "0"
    assert env["ARM_ELEV_CAP"] == "35.0"
    assert env["BIND_SKIP"] == ""


def test_order_recipe_then_character_then_panel():
    row = dict(BARB_ROW, arm_cap=60)
    s = resolve(row, {"bind_match": False, "barrel_chest": 1})
    assert s["mode"] == {"value": "ik", "from": "recipe:human"}
    assert s["arm_cap"] == {"value": 60, "from": "character"}
    assert s["bind_match"] == {"value": False, "from": "panel"}
    assert s["clavicle_damp"] == {"value": 0.0, "from": "panel"}
    s = resolve(row, {"arm_cap": 45})
    assert s["arm_cap"]["from"] == "panel"


def test_every_knob_is_sent():
    for kind in RECIPES:
        env = bake_env(resolve({"id": "x", "recipe": kind}), {})
        assert len(env) == 9 and all(isinstance(v, str) for v in env.values())


def test_unknown_recipe_is_refused():
    with pytest.raises(ValueError):
        resolve({"id": "x", "recipe": "bird"})
