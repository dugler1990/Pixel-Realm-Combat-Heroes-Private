"""Generate building interiors: the walkthrough.

    python -m tools.painted_map_pipeline.interiors.cli --map levels/.../map.tmx

Lists the buildings on a map that have no accepted interior, asks the two things that cannot
be derived -- what the object is, and how its entrance looks -- computes and shows everything
else, then runs the loop:

    plan     paint the floor plan flat, trace it, check it, rank the draws
    emit     the traced plan -> chamber, collision quads and rooms, into a scratch map
    preview  walk the doorway in the real engine and save the frames
    render   paint the stonework with the plan as a control image
    accept   write the interior asset and the geometry into the shipped map

Every step but `render` is cheap or free, and the order is deliberate: you look at the
transition in flat colour and throw the plan away if it is wrong, before any stone is
painted. The old generator had one loop that re-rolled the layout and the art together on
every retry, which is why it never converged on either.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ..building_interiors import BuildingInteriorError, load_building
from . import checks as layout_checks
from . import emit as emit_mod
from . import identify as identify_mod
from . import plan as plan_mod
from . import spec as spec_mod

WORK_ROOT = Path("generated/building_interiors")


# ---------------------------------------------------------------- discovery

def buildings_on(map_path: Path) -> list:
    """Every object carrying interior art, with whether its interior exists yet."""
    root = ET.parse(map_path).getroot()
    found = []
    for group in root.iter("objectgroup"):
        for obj in group.findall("object"):
            props = {p.get("name"): p.get("value") for p in obj.findall("properties/property")}
            if not props.get("interior_image"):
                continue
            interior = map_path.parent / props["interior_image"]
            found.append({
                "name": obj.get("name"),
                "roof": (map_path.parent / props.get("roof_image", "")).exists(),
                "interior": interior.exists(),
                "has_door": bool(props.get("door_x")),
            })
    return found


def _ask(question, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}\n> ").strip()
    except EOFError:
        answer = ""
    return answer or default


def _work(building: str) -> Path:
    return WORK_ROOT / building


def _spec_path(building: str) -> Path:
    return _work(building) / "interior.json"


# ---------------------------------------------------------------- commands

def cmd_list(args) -> int:
    rows = buildings_on(Path(args.map))
    if not rows:
        print("no buildings with interior art on this map")
        return 0
    print(f"buildings on {args.map}:")
    for index, row in enumerate(rows, start=1):
        state = "has interior" if row["interior"] else "NO INTERIOR"
        door = "" if row["has_door"] else "  (no door_x/door_y authored)"
        print(f"  {index}. {row['name']:<22} {state}{door}")
    return 0


def cmd_new(args) -> int:
    """The interview. Two questions, then everything computed is shown back."""
    map_path = Path(args.map)
    rows = buildings_on(map_path)
    if not rows:
        print("no buildings with interior art on this map", file=sys.stderr)
        return 2

    building = args.building
    if not building:
        print("Buildings with no accepted interior:")
        pending = [r for r in rows if not r["interior"]] or rows
        for index, row in enumerate(pending, start=1):
            print(f"  {index}. {row['name']}")
        choice = _ask("Which one?", "1")
        try:
            building = pending[int(choice) - 1]["name"]
        except (ValueError, IndexError):
            building = choice

    object_prompt = args.object or _ask(
        "\nWhat is this object?  (used to find its silhouette in the art)", "")
    entrance_prompt = args.entrance or _ask(
        "\nHow would you describe its entrance?", "")
    intent = args.intent or _ask("\nWhat is inside?  (the only creative call)", "")
    rooms = args.rooms
    if rooms is None:
        answer = _ask("\nHow many rooms?  (blank to skip the check)", "")
        rooms = int(answer) if answer.isdigit() else None

    try:
        found = identify_mod.identify(map_path, building, object_prompt, entrance_prompt,
                                      provider=args.identify)
        print("\nIdentified:")
        print(found.report())
        spec = spec_mod.from_map(
            map_path, building,
            object_prompt=object_prompt, entrance_prompt=entrance_prompt,
            intent=intent, rooms=rooms)
    except (BuildingInteriorError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("\nComputed - not asked:")
    print(spec_mod.describe(spec))
    path = spec.save(_spec_path(building))
    print(f"\nwrote {path}")
    print(f"\nnext:  python -m tools.painted_map_pipeline.interiors.cli plan "
          f"--building {building} --config <cfg> --draws 3")
    return 0


def _load_spec(building: str):
    path = _spec_path(building)
    if not path.exists():
        raise SystemExit(f"no interior spec for {building!r}: run `new` first ({path})")
    return spec_mod.InteriorSpec.load(path)


def _config(args) -> dict:
    if not args.config:
        raise SystemExit("--config is required for this step")
    config = json.loads(Path(args.config).read_text())
    config.setdefault("config_source", Path(args.config).name)
    if args.dry_run:
        # Copy, not manifest: manifest writes a request and no image, so the trace and the
        # gate would never run. Copy returns the input, exercising every step for free.
        config["provider"] = "copy"
    return config


def cmd_plan(args) -> int:
    spec = _load_spec(args.building)
    work = _work(args.building)
    if args.synthetic:
        work.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        best = plan_mod.synthetic_plan(spec)
        best.painted_path = work / "plan_synthetic.png"
        best.composited_path = work / "plan_synthetic_overlay.png"
        roof = Image.open(spec.roof_image).convert("RGBA")
        plan_mod.overlay(best, roof).save(best.composited_path)
        print(layout_checks.format_report(best.report, "synthetic"))
        plans = [best]
        sheet = best.composited_path
    else:
        plans = plan_mod.draw_plans(spec, _config(args), work, draws=args.draws)
        sheet = plan_mod.ranked_sheet(plans, work / "plan_draws.png")

    print(f"\n{len(plans)} plan(s), ranked best first:")
    for rank, plan in enumerate(plans, start=1):
        verdict = "PASS" if plan.passed else "fails: " + ", ".join(plan.failed)
        print(f"  #{rank}  {Path(plan.painted_path).stem:<16} {verdict}")
    print(f"\n  compare them: {sheet}")

    best = plans[0]
    plan_mod.control_image(best).save(work / "plan_control.png")
    import pickle

    (work / "plan.pickle").write_bytes(pickle.dumps(best))
    print(f"  kept #1 as the working plan: {work / 'plan.pickle'}")
    if not best.passed:
        print("\n  NOTE: the best draw still fails. Re-run `plan` for more draws before "
              "emitting -- a plan that fails here fails in the engine too.")
    return 0


def _load_plan(building: str):
    import pickle

    path = _work(building) / "plan.pickle"
    if not path.exists():
        raise SystemExit(f"no traced plan for {building!r}: run `plan` first")
    return pickle.loads(path.read_bytes())


def cmd_emit(args) -> int:
    plan = _load_plan(args.building)
    scratch = emit_mod.scratch_level(plan.spec)
    result = emit_mod.write_plan(plan, scratch / "map.tmx")
    print(f"scratch level : {scratch}")
    print(f"walls         : {result['walls']} segments")
    print(f"chamber       : {result['chamber']}")
    print(f"rooms         : {result['rooms']} spawn areas")
    print(f"\nnext:  ... preview --building {args.building}")
    return 0


def cmd_preview(args) -> int:
    from . import preview as preview_mod

    plan = _load_plan(args.building)
    scratch = emit_mod.scratch_level(plan.spec)
    work = _work(args.building).resolve()
    frames = preview_mod.filmstrip(plan.spec, scratch, work / "preview")
    strip = preview_mod.contact_strip(frames, work / "preview" / "transition.png")
    print(f"\n  the transition: {strip}")
    return 0


def cmd_render(args) -> int:
    from . import render as render_mod

    plan = _load_plan(args.building)
    work = _work(args.building)
    out = render_mod.render_interior(plan, _config(args), work, draws=args.draws)
    print(f"\n{len(out)} render(s):")
    for path in out:
        print(f"  {path}")
    return 0


def cmd_accept(args) -> int:
    from . import render as render_mod

    plan = _load_plan(args.building)
    work = _work(args.building)
    composited = Path(args.image) if args.image else work / "render_composited.png"
    if not composited.exists():
        raise SystemExit(f"no render at {composited}; pass --image")

    written = render_mod.accept(plan, composited)
    result = emit_mod.write_plan(plan, Path(plan.spec.map_path))
    print(f"interior : {written}")
    print(f"map      : {result['map']}  ({result['walls']} walls, {result['rooms']} rooms)")
    return 0


COMMANDS = {
    "list": cmd_list, "new": cmd_new, "plan": cmd_plan,
    "emit": cmd_emit, "preview": cmd_preview, "render": cmd_render, "accept": cmd_accept,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=sorted(COMMANDS), nargs="?", default="new")
    parser.add_argument("--map", type=Path, help="the level's map.tmx")
    parser.add_argument("--building", help="building name (defaults to asking)")
    parser.add_argument("--object", help="skip the interview question: what the object is")
    parser.add_argument("--entrance", help="skip the interview question: the entrance")
    parser.add_argument("--intent", help="skip the interview question: what is inside")
    parser.add_argument("--rooms", type=int, help="expected room count")
    parser.add_argument("--config", type=Path, help="image backend config json")
    parser.add_argument("--draws", type=int, default=1, metavar="N",
                        help="draw N times and rank them; each draw is one API call")
    parser.add_argument("--image", type=Path, help="accept: which render to write")
    parser.add_argument("--identify", default="tmx", choices=("tmx", "sam3"),
                        help="new: where the silhouette and entrance come from. tmx reads "
                             "the authored polygon (offline default); sam3 segments them "
                             "out of the exterior art with the two prompts")
    parser.add_argument("--synthetic", action="store_true",
                        help="plan: build a procedural crypt from the door plane instead of "
                             "painting one. No API key, no spend -- runs the emitter, the "
                             "checks and the preview end to end at the real scale")
    parser.add_argument("--dry-run", action="store_true",
                        help="force the copy backend: every trace, check and gate runs for "
                             "real on the exterior's own pixels, no spend")
    args = parser.parse_args(argv)

    if args.command in {"list", "new"} and not args.map:
        parser.error(f"{args.command} needs --map")
    if args.command not in {"list", "new"} and not args.building:
        parser.error(f"{args.command} needs --building")
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
