"""One-off: today's rigs become v1 and each gets a character file. Safe to re-run (skips what exists).

    python -m tools.boss_sprite_pipeline.rigging.migrate

Reads the old anim_library/characters.json and fits/<id>.json once; neither is read afterwards.
"""
from __future__ import annotations

import json
import shutil

from . import paths
from . import roles as R
from .map import character as C
from .rig import version as V

RIGS = {
    "barb": dict(template="human", glb="bosses/barb/rigfix/barb_final_nb.glb",
                 roles="bosses/barb/gear_test/barb_roles.json",
                 base="bosses/barb/viewer/anim_suite/base.glb",
                 history="UniRig (gear_test/barb_base_rigged.glb) -> anun_roles.py (barb_roles.json) -> "
                         "rig_reweight.py heat 0.5 + repaint (manual) -> rigfix/barb_final.glb -> "
                         "explode2/fix_neutral_bone.py -> rigfix/barb_final_nb.glb (PROCESS_rigfix.md, "
                         "PROCESS_explode2.md)."),
    "demon": dict(template="demon", glb="bosses/demon/rig/jaw/rigged_jaw_hinge.glb",
                  roles="bosses/demon/rig/jaw/bone_roles.json",
                  base="bosses/demon/viewer/anim_suite/base.glb",
                  history="UniRig seed 12345 -> hand roles (arms off by one) -> add_wing_bones.py -> "
                          "face_parts.py SAM3 jaw (rig/jaw/rigged_jaw.glb) -> fix_wing_parent -> "
                          "fix_shoulder_parent -> wing weights -> fix_head_weights -> fix_chest_weights -> "
                          "fix_smooth_weights -> fix_jaw_hinge -> rig/jaw/rigged_jaw_hinge.glb. Order "
                          "between 09-24 and 09-26 not recorded (NOTES_rig_jaw_sam3.md, rigfix/)."),
    "icewiz": dict(template="human", glb="pod_sync/20261116/out/unirig_icewiz/rigged.glb",
                   roles="bosses/icewiz/rig/icewiz_roles.json",
                   base="bosses/icewiz/viewer/anim_suite/base.glb",
                   history="UniRig on the pod 2026-11-16 -> anun_roles.py. No fixes."),
}
for _i in range(4):
    RIGS[f"anun{_i}"] = dict(template="human", glb=f"bosses/anunaki/rig/anun{_i}_rigged.glb",
                             roles=f"bosses/anunaki/rig/anun{_i}_roles.json", base=None,
                             history="UniRig 2026-09-26 (PROCESS.md §6b) -> anun_roles.py. No fixes.")


def _old_panel(cid: str) -> dict:
    """fits/<id>.json (panel) -> map keys. barrel_chest is kept width; clavicle_damp the opposite."""
    p = paths.generated() / "bosses" / "anim_library" / "fits" / f"{cid}.json"
    if not p.is_file():
        return {}
    old = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    if old.get("arm_cap") is not None:
        out["arm_cap"] = float(old["arm_cap"])
    if old.get("bind_match") is not None:
        out["bind_default"] = bool(old["bind_match"])
    if old.get("barrel_chest") is not None:
        out["clavicle_damp"] = round(1.0 - max(0.0, min(1.0, float(old["barrel_chest"]))), 4)
    return out


def run() -> list[str]:
    done = []
    for cid, r in RIGS.items():
        glb = paths.resolve(r["glb"])
        roles_file = paths.resolve(r["roles"])
        if not glb.is_file() or not roles_file.is_file():
            done.append(f"{cid}: skipped, missing {glb if not glb.is_file() else roles_file}")
            continue
        style = "demon_hand" if r["template"] == "demon" else "anun"
        if not V.versions(cid):
            roles = R.canonical(json.loads(roles_file.read_text(encoding="utf-8")), style)
            V.import_v1(cid, r["glb"], roles, r["history"])
        if not C.exists(cid):
            char = C.create(cid, r["template"], rig=1, note=f"migrated 2026-11-21 from {r['roles']}")
            patch = _old_panel(cid)
            if patch:
                C.set_map(cid, patch)
        if r["base"]:
            src = paths.resolve(r["base"])
            dst = paths.character_dir(cid) / "view" / "v1" / "base.glb"
            if src.is_file() and not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dst)
        done.append(f"{cid}: v{C.load(cid)['rig']} {C.load(cid)['template']}")
    return done


if __name__ == "__main__":
    for line in run():
        print(line)
