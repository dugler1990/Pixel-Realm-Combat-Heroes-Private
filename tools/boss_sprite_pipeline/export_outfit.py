"""Game packs from an outfit run: the last step of the outfit pipeline (outfit.py runs it; PROCESS_outfit.md).

    python -m tools.boss_sprite_pipeline.export_outfit <character> <outfit>

body    the painted body into the clips blend (swap_body.py), exported as Graphics/Meshes/<pack> (skinned,
        40k tris, 1024 texture, idle / move / attack), body capsules baked, clips.json copied from the barb's
        pack. Prints the PlayerSelectionDict.json entry to add (not written: paste it).
armour  one pack per slot (explode2/slot_packs.py: rigid on the clips' skeleton) in <run>/packs/<slot>/;
cut     the game cannot draw slot packs yet, so they stay out of Graphics/. Check: every pack loads as a
        PlayerMesh, frames and size printed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from tools.boss_sprite_pipeline import outfit as of

REPO = Path(__file__).resolve().parents[2]
TRIS, TEX, TRIS_MIN = 40000, 1024, 3000
CLIPS = "idle,move,attack"


def run(cmd: list, ok: str | None = None) -> str:
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=REPO)
    out = r.stdout + r.stderr
    if r.returncode or (ok and ok not in out):
        print(out[-3000:])
        sys.exit(f"STOPPED: {Path(str(cmd[3] if str(cmd[1]) == '-m' else cmd[1])).name} (exit {r.returncode}{', no ' + ok if ok else ''})")
    return out


def clips_json(dst: Path, made_by: str) -> None:
    src = REPO / "Graphics" / "Meshes" / "barb" / "clips.json"
    c = json.loads(src.read_text(encoding="utf-8"))
    c["made_by"] = made_by
    (dst / "clips.json").write_text(json.dumps(c, indent=2), encoding="utf-8")


def export_body(o: dict, ctx: of.Ctx) -> dict:
    painted = ctx.painted()
    blend = ctx.work / "pack" / "player_body.blend"
    blend.parent.mkdir(parents=True, exist_ok=True)
    run([ctx.bpy, of.TOOLS / "swap_body.py", ctx.data(o["clips_blend"]), painted, blend], ok="SWAP_BODY_OK")
    pack = REPO / "Graphics" / "Meshes" / o["pack"]
    out = run([ctx.bpy, of.TOOLS / "export_mesh_runtime.py", blend, pack, TRIS, TEX, "--skin", "--only", CLIPS])
    run([sys.executable, "-m", "tools.boss_sprite_pipeline.bake_body_capsules", o["pack"]], ok="baked")
    clips_json(pack, f"export_outfit.py {ctx.character}/{ctx.outfit}: {painted} in {o['clips_blend']}")
    entry = {"selection_position": {"x": 0, "y": 1}, "name": f"{o['pack']}_mesh",
             "display_name": o.get("display_name", f"Barbarian ({ctx.outfit}, mesh)"), "painting": "barbarian.png",
             "roster_stats": ["strength", "vitality"], "player_info_dir": "../Graphics/barb/", "mesh_pack": o["pack"],
             "evasion_loadout": ["slide", "leap_slam"],
             "base_stats": {"health": 2000, "energy": 20, "attack": 10, "magic": 7, "speed": 5, "strength": 20,
                            "vitality": 20, "agility": 4, "charisma": 3}}
    if o.get("start_equipment"):          # what the hero starts wearing / carrying (equipment.start_equipment)
        entry["start_equipment"] = o["start_equipment"]
    print("\nAdd to Graphics/PlayerSelectionDict.json (players list; pick a free selection_position):")
    print(json.dumps(entry, indent=1))
    check = load_check(str(pack))
    return {"pack": str(pack), "selection_entry": entry, "load": check,
            "max_err": next((l.split("max_err")[1].strip() for l in out.splitlines() if "wrote skin.npz" in l), None)}


def export_slots(o: dict, ctx: of.Ctx) -> dict:
    slots = ctx.out("slots", "slots")
    packs = ctx.work / "packs"
    run([ctx.bpy, of.TOOLS / "explode2" / "slot_packs.py", ctx.data(o["clips_blend"]), ctx.data(o["rig_game"]),
         ctx.data(o["roles"]), slots, packs], ok="SLOT_PACKS_OK")
    info = json.loads((packs / "slot_packs.json").read_text(encoding="utf-8"))
    total = sum(v["faces"] for v in info.values())
    result = {}
    for slot, v in sorted(info.items()):
        tris = max(TRIS_MIN, round(TRIS * v["faces"] / total))
        dst = packs / slot
        if dst.exists():
            shutil.rmtree(dst)
        run([ctx.bpy, of.TOOLS / "export_mesh_runtime.py", packs / f"{slot}.blend", dst, tris, TEX, "--skin",
             "--only", CLIPS])
        run([sys.executable, "-m", "tools.boss_sprite_pipeline.bake_body_capsules", slot, "--mesh-root", packs],
            ok="baked")
        clips_json(dst, f"export_outfit.py {ctx.character}/{ctx.outfit} slot {slot}")
        result[slot] = {"pack": str(dst), "tris": tris, "load": load_check(str(dst))}
    return {"packs": result}


def load_check(pack: str) -> dict:
    """The pack loads as the game loads a mesh player: frames per clip, height on screen for a 56 px figure."""
    code = ("import os,sys,json; os.environ.setdefault('SDL_VIDEODRIVER','dummy'); sys.path.insert(0,'Code'); "
            "os.chdir('Code'); import pygame; pygame.init(); pygame.display.set_mode((8,8)); "
            "from player_mesh import PlayerMesh; m=PlayerMesh(sys.argv[1], 56); "
            "print('LOAD_OK', json.dumps({'ranges': m.skin.pack.ranges, 'height_px': round(m.height_px, 1)}))")
    out = run([sys.executable, "-c", code, pack], ok="LOAD_OK")
    got = json.loads(out.split("LOAD_OK", 1)[1].strip().splitlines()[0])
    print(f"  loads: {pack} {got}", flush=True)
    return got


def main(argv=None) -> None:
    character, outfit = (argv or sys.argv[1:])[:2]
    ctx = of.Ctx(character, outfit)
    o = ctx.o
    result = export_body(o, ctx) if o["kind"] == "body" else export_slots(o, ctx)
    print("EXPORT_OK", json.dumps(result)[:400])


if __name__ == "__main__":
    main()
