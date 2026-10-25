"""Generate building interiors: the walkthrough.

    python -m tools.painted_map_pipeline.interiors.cli new \\
        --level-image levels/.../background.png --identify sam3

Asks the two things that cannot be derived -- what the object is, and how its entrance looks
-- hands both to the local SAM3 as prompts, and shows you every building it found so you can
throw out the wrong ones before anything is generated. Names and art paths follow from the
building; nothing is authored in Tiled first, and the map is written only at the end.

    ... new --map levels/.../map.tmx          (--identify tmx, the default)

is the other way in: a building already drawn by hand in Tiled, whose polygon and door are
read off the map. Unchanged, and still the right answer for a building you drew yourself.

Either way the spec that comes out feeds the same loop:

    plan     paint the floor plan flat, trace it, check it, rank the draws
    emit     the traced plan -> chamber, collision quads and rooms, into a scratch map
    preview  walk the doorway in the real engine and save the frames
    render   paint the stonework with the plan as a control image
    accept   write the interior asset and the geometry into the shipped map

Every step but `render` is cheap or free, and the order is deliberate: you look at the
transition in flat colour and throw the plan away if it is wrong, before any stone is
painted. The old generator had one loop that re-rolled the layout and the art together on
every retry, which is why it never converged on either.

An accepted interior is then furnished, with a gate after every step:

    ... furnish --building great_pyramid --config <image backend json>

    decorate  1. the room decorated once per line of decor/styles.txt (one edit call each)
    sheet     2. a sprite sheet of what each kept variant added (one edit call each)
    extract   3. the sheets cut into the shared prop set (Graphics/Props/<object>), tagged
    locate    4. each variant's props put back where they stood; the room rebuilt from them
    place     5. the props written into the map as Tiled objects, one set per variant

Steps 1-3 automate what was done by hand -- decorating the room, drawing a sprite sheet of
what was added, cutting the sheet -- and 4-5 locate those props in each variant and write
them into the map. Only 1 and 2 call the image model. Each step is also a command of its
own that opens its gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ..building_interiors import BuildingInteriorError, load_building
from . import art as art_mod
from . import ask_model
from . import checks as layout_checks
from . import discover as discover_mod
from . import emit as emit_mod
from . import identify as identify_mod
from . import plan as plan_mod
from . import sam_local
from . import spec as spec_mod

WORK_ROOT = Path("generated/building_interiors")

# What a step at a gate can fail with and still leave the session worth keeping: the image
# backend refusing or timing out (ImageClientError and BuildingInteriorError are both
# RuntimeErrors), the emitter refusing a plan (ValueError), a file a viewer is holding
# (OSError). A programming error is none of these and still stops with its traceback.
STEP_ERRORS = (RuntimeError, ValueError, OSError)


def _failed(step: str, exc: Exception) -> None:
    """A step at a gate failed: say which and why, in place of a traceback. The caller puts
    you back at the decision that led to it, with whatever was already drawn."""
    print(f"\n  {step} failed -- {type(exc).__name__}: {exc}", file=sys.stderr)


# The steps after the plan, by the files each one writes. They run in a chain -- plan,
# render, floor trace, map -- and every step reuses whatever it finds in the folder. So when
# something new is kept or made at one step, everything after it is moved aside: that is how
# a new plan got shown a render of the old one, and a new render the old one's floor trace.
RENDER_FILES = ("render*", "augment*", "control.png")
FLOOR_FILES = ("floor*",)


def _set_aside(work: Path, patterns) -> None:
    """Move the files matching `patterns` into `old/<date_time>/`. Moved, not deleted: a
    render is paid for. Raises OSError naming the file when one cannot be moved."""
    from datetime import datetime

    found = sorted({path for pattern in patterns for path in Path(work).glob(pattern)
                    if path.is_file()})
    if not found:
        return
    stamp = Path(work) / "old" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder, n = stamp, 1
    while folder.exists():
        folder, n = stamp.with_name(f"{stamp.name}_{n}"), n + 1
    folder.mkdir(parents=True)
    for path in found:
        try:
            shutil.move(str(path), str(folder / path.name))
        except OSError as exc:
            raise OSError(f"could not move {path.name} aside -- close whatever has it "
                          f"open ({exc})") from exc
    print(f"  set aside {len(found)} file(s) made from the previous choice -> {folder}")


def _keep_plan(plan, work: Path) -> None:
    """Make `plan` the working plan. If it is not the plan already kept, what was rendered
    and traced from that one is set aside first, so no later step can reuse it."""
    import pickle

    import numpy as np
    from PIL import Image

    control = plan_mod.control_image(plan).convert("RGB")
    kept = work / "plan_control.png"
    same = False
    if kept.exists():
        with Image.open(kept) as previous:
            same = np.array_equal(np.asarray(previous.convert("RGB")), np.asarray(control))
    if not same:
        _set_aside(work, RENDER_FILES + FLOOR_FILES)
    control.save(kept)
    (work / "plan.pickle").write_bytes(pickle.dumps(plan))


def _drop_floor_trace(work: Path) -> None:
    """A new render makes the floor trace of the old one stale: set it aside."""
    try:
        _set_aside(work, FLOOR_FILES)
    except OSError as exc:
        print(f"  warning: {exc}. The floor step may reuse the old render's trace -- close "
              f"it and press [r] at the floor gate", file=sys.stderr)


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


def _inside(path: Path, folder: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
    except ValueError:
        return False
    return True


def _spec_path(building: str) -> Path:
    return _work(building) / "interior.json"


# ---------------------------------------------------------------- commands

def furnish_status(building: str, map_xml: str = "") -> str:
    """How far furnishing has got for `building`, read off disk: "" before it has started.

    Read, never recomputed: the room's hash is the one step 1 last wrote, so a room
    re-rendered since shows up when `furnish` is next run, not here.
    """
    from . import decorate as decor_mod
    from . import extract as extract_mod
    from . import kit as kit_mod
    from . import locate as locate_mod

    work = _work(building)
    if not (work / decor_mod.DECOR / decor_mod.BASE_META).exists():
        return ""
    sha1 = decor_mod._read_json(work / decor_mod.DECOR / decor_mod.BASE_META).get("sha1", "")
    found = decor_mod.variants(work, sha1)
    usable = [v for v in found if v.usable]
    states = [kit_mod.sheet_state(v) for v in usable]
    sheets = [s for s in states if s.usable]
    cut = sum(1 for s in sheets if extract_mod.is_current(s))
    located = sum(1 for s in sheets if locate_mod.read_placements(s.variant).get("placements"))
    placed = len({m for m in re.findall(r'name="%s_prop_(v\d\d)_' % re.escape(building), map_xml)})
    stale = sum(1 for v in found if v.stale) + sum(1 for s in states if s.stale)
    return (f"furnished: decorated {len(usable)}, sheets {len(sheets)}, cut {cut}, "
            f"located {located}, placed {placed}" + (f", {stale} stale" if stale else ""))


def cmd_list(args) -> int:
    rows = buildings_on(Path(args.map))
    if not rows:
        print("no buildings with interior art on this map")
        return 0
    map_xml = Path(args.map).read_text(encoding="utf-8")
    print(f"buildings on {args.map}:")
    for index, row in enumerate(rows, start=1):
        state = "has interior" if row["interior"] else "NO INTERIOR"
        door = "" if row["has_door"] else "  (no door_x/door_y authored)"
        print(f"  {index}. {row['name']:<22} {state}{door}")
        furnished = furnish_status(row["name"], map_xml)
        if furnished:
            print(f"     {'':<22} {furnished}")
    return 0


def _interview(args) -> tuple:
    """The four answers. Two are SAM3's prompts, one is the only creative call, one is a
    check. Everything else on the spec is computed and shown back rather than asked."""
    object_prompt = args.object or _ask(
        "\nWhat is this object?  (used to find its silhouette in the art)", "")
    entrance_prompt = args.entrance or _ask(
        "\nHow would you describe its entrance?", "")
    intent = args.intent or _ask("\nWhat is inside?  (the only creative call)", "")
    rooms = args.rooms
    if rooms is None:
        answer = _ask("\nHow many rooms?  (blank to skip the check)", "")
        rooms = int(answer) if answer.isdigit() else None
    return object_prompt, entrance_prompt, intent, rooms


def cmd_new(args) -> int:
    """The interview, from a level image or from a building already drawn in Tiled."""
    return _new_from_image(args) if args.identify == "sam3" else _new_from_map(args)


def _score_against_map(candidates, map_path: Path, object_prompt: str) -> str:
    """A second opinion on each silhouette, free, from obstacles the collision pass found.

    Only where that pass has already run; `gate` degrades to a note when it has not. That
    "nothing to check against" note is about the map, not about any one candidate, so it is
    returned to be said once rather than stamped onto every row.
    """
    if not map_path.exists():
        return ""
    shared = []
    for candidate in candidates:
        scored = identify_mod.gate(
            identify_mod.Identified(silhouette=candidate.silhouette,
                                    door_point=candidate.door_point, source="sam3"),
            map_path, object_prompt)
        candidate.iou = scored.iou
        candidate.fragments = scored.fragments
        if scored.iou is None:
            shared = list(scored.notes)          # the same sentence for every candidate
        else:
            candidate.notes = candidate.notes + scored.notes
    return "  " + "\n  ".join(shared) if shared else ""


def _show(path: Path) -> None:
    """Open the overlay. Looking at a threshold change is the point of making one."""
    try:
        os.startfile(str(Path(path).resolve()))       # noqa: S606  (Windows)
    except (AttributeError, OSError):
        pass                                          # not Windows, or no viewer: the path prints


def _rest(choice: str) -> str:
    """Whatever was typed after the menu letter, e.g. "a 1.5" -> "1.5"."""
    parts = choice.strip().split(None, 1)
    return parts[1] if len(parts) > 1 else ""


def _number(question: str, current: float, given: str = "") -> float:
    """Ask for a number, or take one already typed on the menu line.

    `given` is whatever followed the menu letter. Typing `a 1.5` used to drop the 1.5
    silently and then offer the OLD value as the default, so pressing enter kept the old
    one and the control looked broken.
    """
    if given.strip():
        try:
            return float(given.strip())
        except ValueError:
            print(f"  {given.strip()!r} is not a number")
    answer = _ask(f"{question}", str(current)).strip()
    try:
        return float(answer)
    except ValueError:
        print(f"  {answer!r} is not a number; keeping {current}")
        return current


def _tune(located, image: Path, work: Path, map_path: Path, object_prompt: str, args) -> list:
    """Adjust the thresholds against the picture until the set is right.

    Every pass through here is pure arithmetic on the polygons already in memory -- the SAM
    run happened once, before this was called. So changing your mind is free, which is the
    only reason it is worth asking.
    """
    confidence = args.min_confidence
    min_area, max_area = args.min_area, args.max_area

    while True:
        candidates = located.filtered(min_confidence=confidence,
                                      min_area_fraction=min_area / 100.0,
                                      max_area_fraction=max_area / 100.0)
        print()
        print(located.spread())
        if not candidates:
            print("  nothing passes these thresholds")
        else:
            shared = _score_against_map(candidates, map_path, object_prompt)
            print()
            print(discover_mod.table(candidates))
            if shared:
                print(shared)
            overlay = discover_mod.numbered_overlay(image, candidates,
                                                    work / "candidates.png")
            print(f"\n  {overlay}")
            _show(overlay)

        print(f"\n{len(candidates)} shape(s) at confidence {confidence}, "
              f"size {min_area}%-{max_area}% of the map")
        choice = _ask("  [enter] these are the right buildings   [c] confidence   [a] smallest size   "
                      "[x] largest size   [q] give up", "").strip().lower()
        if not choice:
            if candidates:
                # The tuned values go back with the candidates. Refine re-runs the same
                # question at full resolution, and answering it to a different standard than
                # the one you just settled on is how a rejected fragment becomes a building.
                return candidates, confidence
            print("  nothing to accept")
            continue
        if choice.startswith("q"):
            return [], confidence
        if choice.startswith("c"):
            confidence = _number("  lowest score to keep?", confidence, _rest(choice))
        elif choice.startswith("a"):
            min_area = _number("  smallest building, as % of the map?", min_area, _rest(choice))
        elif choice.startswith("x"):
            max_area = _number("  largest building, as % of the map?", max_area, _rest(choice))
        else:
            print(f"  {choice!r}?")


def _pick(question: str, buildings: list):
    """One building by the number PRINTED BESIDE IT, not by its position in the list.

    These differ the moment anything is accepted: the table keeps a building's own number so
    it does not move under you, while its position shifts as others leave. Indexing by
    position silently selects the wrong building -- which it did.
    """
    answer = _ask(question, "").strip()
    if not answer.isdigit():
        print(f"  {answer!r} is not a number")
        return None
    wanted = int(answer)
    for building in buildings:
        if building.index == wanted:
            return building
    listed = ", ".join(str(b.index) for b in buildings)
    print(f"  {wanted} is not one of: {listed}")
    return None


def _unaccept(settled: dict, crops: dict) -> tuple:
    """Put an accepted building back in question. Mistakes here are cheap and common --
    accepting the wrong number is one keystroke -- so undoing one has to be too."""
    if not settled:
        print("  nothing has been accepted yet")
        return settled, crops
    print(f"  accepted: {', '.join(sorted(settled))}")
    answer = _ask("  put which building back in question, or 'all'?", "").strip().lower()
    if answer == "all":
        print(f"  put {len(settled)} back in question")
        return {}, {}
    for name, building in list(settled.items()):
        if str(building.index) == answer:
            settled.pop(name)
            crops.pop(name, None)
            print(f"  {name} is back in question")
            return settled, crops
    print(f"  {answer!r} is not one of the accepted numbers")
    return settled, crops


def _review_buildings(scans: list, work: Path, map_path: Path, object_prompt: str,
                      confidence: float) -> list:
    """Loop A: is this the right set of buildings.

    Every pass is arithmetic over hits already in memory -- stage A ran before this was
    called -- so changing the floor costs nothing and can go both ways.
    """
    settled, settled_crops = {}, {}
    while True:
        # Settled buildings are done and out of the way: the floor no longer moves them and
        # they no longer clutter the view, so what is left on screen is only what is still in
        # question. That is the whole point of settling one at a time.
        buildings, crops = [], {}
        for scan in scans:
            for building in scan.filtered(confidence):
                if building.name in settled:
                    continue
                buildings.append(building)
                crops[building.name] = (scan.crop_path, scan.origin)

        print()
        for scan in scans:
            print(f"  {scan.candidate.name}: {len(scan.hits)} raw, best "
                  f"{scan.best_score():.2f}")
        if not buildings:
            print("  nothing passes this confidence")
        else:
            shared = _score_against_map(buildings, map_path, object_prompt)
            print()
            print(discover_mod.table(buildings, doors=False))
            if shared:
                print(shared)
            sheet = discover_mod.contact_sheet(buildings, crops, work / "buildings.png")
            print(f"\n  {sheet}")
            _show(sheet)

        done = (f"   ({len(settled)} already accepted: {', '.join(sorted(settled))})"
                if settled else "")
        print(f"\n{len(buildings)} still in question, at confidence {confidence}{done}")
        choice = _ask("  [enter] accept every building listed above   [a] accept just one   "
                      "[u] put one back (number, or 'all')   [c] confidence   [s] show again   "
                      "[q] give up", "").strip().lower()
        if not choice:
            if buildings or settled:
                return list(settled.values()) + buildings
            print("  nothing to accept")
        elif choice.startswith("q"):
            return []
        elif choice.startswith("c"):
            confidence = _number("  lowest score to keep?", confidence, _rest(choice))
        elif choice.startswith("a"):
            picked = _pick("  which building?", buildings)
            if picked:
                settled[picked.name] = picked
                settled_crops[picked.name] = crops[picked.name]
                print(f"  accepted {picked.name}; {len(buildings) - 1} left in question")
        elif choice.startswith("u"):
            settled, settled_crops = _unaccept(settled, settled_crops)
        elif choice.startswith("s"):
            continue
        else:
            print(f"  {choice!r}?")


def _review_doors(buildings: list, image: Path, work: Path, entrance_prompt: str,
                  args) -> list:
    """Loop B: did the doors land in the right place.

    The door is what the threshold, the arch quad, the collision gap and the walk-through are
    all derived from, so a wrong one is not a cosmetic problem -- and a building with none
    cannot usefully go past `new` at all, which this says out loud rather than noting.
    """
    scans, crops = {}, {}
    for building in buildings:
        print(f"\n{building.name}: looking for the {entrance_prompt!r} ...")
        try:
            scan = discover_mod.scan_door(building, image, entrance_prompt, work,
                                          tile=args.refine_tiles, rescan=args.rescan)
        except (sam_local.SamLocalError, ValueError) as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
            continue
        scans[building.name] = scan
        crops[building.name] = (scan.crop_path, scan.origin)

    confidence = args.entrance_min_confidence
    min_area, max_area = args.entrance_min_area, args.entrance_max_area
    stepped, settled = set(), {}
    while True:
        chosen = {b.name: b.door_choice for b in buildings if b.name in stepped}
        discover_mod.attach_doors(buildings, scans, min_confidence=confidence,
                                  min_area_fraction=min_area / 100.0,
                                  max_area_fraction=max_area / 100.0)
        # attach_doors resets every choice to the top-ranked match; put back the ones you
        # stepped to yourself, or changing an unrelated threshold would undo them.
        for building in buildings:
            if building.name in chosen:
                discover_mod.select_door(building, chosen[building.name])
        with_door = [b for b in buildings if b.door_point]
        print()
        for building in buildings:
            scan = scans.get(building.name)
            if scan:
                print(scan.spread(confidence, min_area / 100.0, max_area / 100.0))
        print()
        print(discover_mod.table(buildings))
        sheet = discover_mod.contact_sheet(buildings, crops, work / "doors.png")
        print(f"\n  {sheet}")
        _show(sheet)

        print(f"\n{len(with_door)} of {len(buildings)} have a door, at entrance confidence "
              f"{confidence}, size {min_area}%-{max_area}% of the crop")
        if len(with_door) < len(buildings):
            print("  a building with no door cannot go further than `new` -- the door plane "
                  "is what plan, the arch and the collision gap come from")
        done = f"   ({len(settled)} already accepted: "               f"{', '.join(sorted(settled))})" if settled else ""
        print(f"  [enter] accept every building listed above   [a] accept just one   "
              f"[n] show a building's next possible door{done}")
        choice = _ask("  [u] put one back (number, or 'all')   [c] confidence   [m] smallest door   "
                      "[x] largest door   [s] show again   [q] give up", "").strip().lower()
        if not choice:
            return list(settled.values()) + buildings
        if choice.startswith("q"):
            return []
        if choice.startswith("c"):
            confidence = _number("  lowest door score to keep?", confidence, _rest(choice))
        elif choice.startswith("a"):
            picked = _pick("  which building?", buildings)
            if picked:
                settled[picked.name] = picked
                buildings = [b for b in buildings if b.name != picked.name]
                print(f"  accepted {picked.name}; {len(buildings)} left in question")
                if not buildings:
                    return list(settled.values())
        elif choice.startswith("u"):
            returning, _ = _unaccept(settled, {})
            back = [b for b in settled.values() if b.name not in returning]
            settled = returning
            buildings = sorted(buildings + back, key=lambda b: b.index)
        elif choice.startswith("m"):
            min_area = _number("  smallest door, as % of the building?", min_area, _rest(choice))
        elif choice.startswith("x"):
            max_area = _number("  largest door, as % of the building?", max_area, _rest(choice))
        elif choice.startswith("n"):
            picked = _pick("  show the next possible door for which building?", buildings)
            if picked and picked.door_options:
                discover_mod.select_door(picked, picked.door_choice + 1)
                print(f"  {picked.name}: door {picked.door_choice + 1} of "
                      f"{len(picked.door_options)}")
                stepped.add(picked.name)
            elif picked:
                print(f"  {picked.name} has no other possible doors")

        elif choice.startswith("s"):
            continue
        else:
            print(f"  {choice!r}?")


def _new_from_image(args) -> int:
    """Level image in, SAM3 finds the buildings, you pick which ones get interiors.

    Nothing is read out of the TMX to get here. The map is only where the result is written,
    at accept, and it is consulted before then for one optional thing: obstacles the
    collision pass already found, which give a second opinion on each silhouette for free.
    """
    image = Path(args.level_image)
    if not image.exists():
        print(f"no level image at {image}", file=sys.stderr)
        return 2
    map_path = Path(args.map) if args.map else image.parent / "map.tmx"

    object_prompt, entrance_prompt, intent, rooms = _interview(args)

    work_root = WORK_ROOT / "_discovery"
    try:
        located = discover_mod.locate(image, object_prompt, work_root,
                                      downscale=args.downscale, rescan=args.rescan)
    except (sam_local.SamLocalError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    candidates, confidence = _tune(located, image, work_root, map_path, object_prompt, args)
    if not candidates:
        return 2

    if args.building:
        picked = [c for c in candidates if c.name == args.building]
        if not picked:
            print(f"no candidate named {args.building!r}", file=sys.stderr)
            return 2
    else:
        try:
            picked = discover_mod.parse_selection(
                _ask("\nWhich ones get interiors?  (numbers, or 'all')", "all"), candidates)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if not picked:
        print("nothing picked")
        return 0

    # Stage A: one pass per picked building. The expensive half, and it costs per building
    # rather than per map.
    scans = []
    for candidate in picked:
        print(f"\n{candidate.name}: re-segmenting at full resolution ...")
        try:
            scans.append(discover_mod.scan_building(candidate, image, object_prompt,
                                                    work_root, tile=args.refine_tiles,
                                                    rescan=args.rescan))
        except (sam_local.SamLocalError, ValueError) as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
    if not scans:
        print("nothing survived refinement", file=sys.stderr)
        return 2

    refined = _review_buildings(scans, work_root, map_path, object_prompt, confidence)
    if not refined:
        print("nothing accepted")
        return 0

    # Stage B: one pass per accepted building, then the same treatment for the doors.
    if entrance_prompt:
        refined = _review_doors(refined, image, work_root, entrance_prompt, args)
        if not refined:
            print("nothing accepted")
            return 0

    written = []
    for candidate in refined:
        work = _work(candidate.name)
        work.mkdir(parents=True, exist_ok=True)
        print(f"\n{candidate.name}:")
        origin, size = art_mod.bbox_of(candidate.silhouette)
        crop = art_mod.crop_exterior(image, origin, size,
                                     work / f"{candidate.name}_exterior.png")
        try:
            wall = ask_model.wall_thickness(crop, size, intent=intent,
                                            refresh=args.rescan)
        except ask_model.WallThicknessError as exc:
            # Stop, do not skip to the next building. There is no usable default for this
            # and a wrong chamber is not something to discover three steps later.
            print(f"\nerror: {exc}", file=sys.stderr)
            return 2
        try:
            art = art_mod.art_from_polygon(
                candidate.name, candidate.silhouette, image, work,
                wall=wall, door_point_world=candidate.door_point,
                door_polygon_world=candidate.door_polygon,
                level_dir=map_path.parent)
        except BuildingInteriorError as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
            continue
        spec = spec_mod.from_building(
            art, map_path,
            object_prompt=object_prompt, entrance_prompt=entrance_prompt,
            intent=intent, rooms=rooms, wall=wall)
        print(spec_mod.describe(spec))
        path = spec.save(_spec_path(candidate.name))
        written.append(path)

        # What it decided, as a picture, next to the numbers. The outline and the door are
        # the two things everything downstream is built on, and reading them as coordinates
        # is not the same as seeing them sit on the building.
        local = discover_mod.Candidate(
            index=candidate.index, name=candidate.name,
            silhouette=tuple((x - origin[0], y - origin[1])
                             for x, y in candidate.silhouette),
            confidence=candidate.confidence, approximate=False)
        if candidate.door_point:
            local.door_point = (candidate.door_point[0] - origin[0],
                                candidate.door_point[1] - origin[1])
        outline = discover_mod.numbered_overlay(crop, [local],
                                                work / f"{candidate.name}_outline.png")
        print(f"  spec        {path}")
        print(f"  outline     {outline}")

    if not written:
        return 2
    print(f"\nwrote {len(written)} spec(s) under {WORK_ROOT}. Next, one building at a time:")
    for path in written:
        print(f"  ... plan --building {path.parent.name} --config <cfg> --draws 3")
    return 0


def _new_from_map(args) -> int:
    """The building is already drawn in Tiled: read the polygon and door off the map."""
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

    object_prompt, entrance_prompt, intent, rooms = _interview(args)

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


def _load_spec(building: str, args=None):
    """The saved spec, with any interview flags on the command line applied over it.

    `--rooms` used to be read only by `new`; passing it to `build` did nothing, silently, and
    the plan went to the model instead of being the deterministic one room -- a paid draw for
    a layout that needed no drawing. Flags given to any command now update the spec and are
    saved, so the next run without them gets the same answer.
    """
    path = _spec_path(building)
    if not path.exists():
        raise SystemExit(f"no interior spec for {building!r}: run `new` first ({path})")
    spec = spec_mod.InteriorSpec.load(path)
    changed = False
    if args is not None:
        for flag, field in (("rooms", "rooms"), ("object", "object_prompt"),
                            ("entrance", "entrance_prompt"), ("intent", "intent")):
            value = getattr(args, flag, None)
            if value is not None and value != getattr(spec, field):
                setattr(spec, field, value)
                changed = True
        for flag, field in (("corridor", "corridor_players"), ("rooms_across", "room_players")):
            value = getattr(args, flag, None)
            if value is not None and tuple(value) != getattr(spec, field):
                setattr(spec, field, tuple(value))
                changed = True
    # The door on the map is not read back. It is the door's frame, written by the emitter
    # at every accept for the game to draw over a body passing under it; the opening it was
    # grown from is `spec.doors`, kept here. Reading the map back used to make the frame the
    # opening on the next run.
    if changed:
        spec.save(path)
    return spec


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
    spec = _load_spec(args.building, args)
    work = _work(args.building)
    if spec.rooms == 1 or args.synthetic:
        work.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        if spec.rooms == 1:
            best, stem = plan_mod.single_room_plan(spec), "plan_single_room"
        else:
            best, stem = plan_mod.synthetic_plan(spec), "plan_synthetic"
        best.painted_path = work / f"{stem}.png"
        best.composited_path = work / f"{stem}_overlay.png"
        roof = Image.open(spec.roof_image).convert("RGBA")
        plan_mod.overlay(best, roof).save(best.composited_path)
        print(layout_checks.format_report(best.report, stem))
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
    try:
        _keep_plan(best, work)
    except STEP_ERRORS as exc:
        _failed("keeping the plan", exc)
        return 2
    print(f"  kept #1 as the working plan: {work / 'plan.pickle'}")
    if not best.passed:
        print("\n  NOTE: the best draw still fails. Re-run `plan` for more draws before "
              "emitting -- a plan that fails here fails in the engine too.")
    return 0


# ---------------------------------------------------------------- the build flow

def _redoor(spec, gap: float) -> None:
    """Re-cut the door plane at a new width.

    The arch quad, the gap collision leaves and the threshold the prompt describes are all
    derived from the same call, so changing the width has to go back through it -- setting the
    number alone would leave three descriptions of one doorway disagreeing.
    """
    from .runtime import building_geometry

    if not spec.door_origin:
        print("  this building has no door plane to re-cut")
        return
    origin, inward, arch = building_geometry().door_plane_from_polygon(
        spec.silhouette, spec.door_origin, door_gap=gap)
    spec.door_gap = gap
    spec.door_origin = tuple(origin)
    spec.door_inward = tuple(inward)
    spec.arch_quad = tuple((float(x), float(y)) for x, y in arch)
    print(f"  doorway now {spec.door_width:.0f} px")


def _prompt_sent(work: Path, name: str, rebuild) -> str:
    """The prompt file the pass wrote, or a rebuild of it if there is none yet.

    The file is what actually went, criticism from a retry included. Rebuilding it from the
    spec prints the prompt a fresh draw WOULD get, which after an `r1` is a different thing --
    and printing the wrong one is exactly the failure this whole block exists to stop.
    """
    path = Path(work) / name
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            pass
    return rebuild()


def _sent(prompt: str, images) -> None:
    """The prompt in full, and the images that went with it, by path.

    Both halves matter and only one was ever printed. A render is the exterior plus a control
    image plus these words, and judging the result without seeing all three is guesswork --
    the same guesswork that had us reading numbers off draws for hours.
    """
    print("\n  ---- prompt sent ----")
    for line in (prompt or "").rstrip().splitlines():
        print(f"  | {line}")
    print("  ---- images sent ----")
    for label, path in images:
        if not path:
            print(f"  | {label:<10} -")
            continue
        mark = "" if Path(path).exists() else "   (not written yet)"
        print(f"  | {label:<10} {path}{mark}")
    print("  ---------------------")


def _mask_sent(work: Path, pass_name: str) -> Path:
    """The mask file that actually went with the last call of this pass.

    `_run_edit` names it after the draw -- `render_mask.png` for a single draw,
    `render_draw1_mask.png` for several -- so naming one of those here is wrong half the time
    and prints "(not written yet)" beside a mask that was very much sent. The mask is the same
    for every draw of a pass, so the first one on disk is the one to show.
    """
    found = sorted(work.glob(f"{pass_name}*_mask.png"))
    return found[0] if found else work / f"{pass_name}_mask.png"


def _geometry_summary(spec) -> str:
    """The numbers a plan is about to be drawn against, in the unit the prompt uses.

    In PLAYERS, not tiles. The prompt says "19 x 15 people across" while this used to say
    "6.8 x 5.4 characters" about the same building -- two units for one thing, differing by
    2.8x, which is how the corridors came out too narrow in the first place.
    """
    from .player_size import player_size
    from .prompt import CORRIDOR_PLAYERS, MIN_CORRIDOR_PLAYERS, ROOM_PLAYERS

    player = player_size(scale=spec.world_scale)
    across = spec.size[0] / player.width
    down = spec.size[1] / player.width
    lines = [f"  player     {player.width} x {player.height} px "
             f"({player.character}) -- one unit",
             f"  chamber    {across:.0f} x {down:.0f} people "
             f"({spec.size[0]} x {spec.size[1]} px)",
             f"  corridor   gate >= {MIN_CORRIDOR_PLAYERS * player.width:.0f} px "
             f"({MIN_CORRIDOR_PLAYERS} people) -- the hard minimum",
             f"  asked for  {(spec.corridor_players or CORRIDOR_PLAYERS)[0]:g} to "
             f"{(spec.corridor_players or CORRIDOR_PLAYERS)[1]:g} people wide corridors, "
             f"rooms {(spec.room_players or ROOM_PLAYERS)[0]:g} to "
             f"{(spec.room_players or ROOM_PLAYERS)[1]:g} people across",
             f"  rooms      {spec.rooms if spec.rooms else 'no target set'}"
             + ("  -- one chamber, no corridors" if spec.rooms == 1 else ""),
             f"  wall       {spec.wall or 0} px shell "
             f"({(spec.wall or 0) / player.width:.1f} people), measured from the art",
             f"  partition  {spec.partition} px between rooms "
             f"({spec.partition / player.width:.1f} people)"
             + ("" if spec.inner_wall else " -- derived from the shell")]
    if spec.door_width:
        share = spec.door_width / max(1.0, spec.size[0])
        source = "measured from the art" if spec.door_gap else "GAME DEFAULT -- not measured"
        lines.append(f"  doorway    {spec.door_width / player.width:.1f} people "
                     f"({spec.door_width:.0f} px, {share:.0%} of the frontage) -- {source}")
    return "\n".join(lines)


def _retrace(plan, spec):
    """The stored plan, re-derived against the spec as it is NOW.

    A pickled plan carries the spec it was made with, so a door drawn in Tiled after the
    plan was kept -- the normal order on a building already on the map -- would never be
    seen by anything that reloads the pickle: the floor would not be held out of it, the
    render would keep the model's door, the emitter would not skip it. The pickle is only
    the floor; everything else (masks, classes, checks) is cheap and comes from the spec.
    """
    silhouette, chamber, editable = plan_mod.geometry_masks(spec)
    unpainted = next((c.get("fraction", 0.0) for c in plan.report.get("checks", ())
                      if c.get("name") == "unpainted"), 0.0)
    traced = plan_mod.trace_plan_from_mask(plan.floor & editable, spec, silhouette, chamber,
                                           editable, unpainted=unpainted)
    traced.painted_path = plan.painted_path
    traced.composited_path = plan.composited_path
    traced.shape_path = getattr(plan, "shape_path", None)
    return traced


def _draw_or_reuse(spec, work: Path, args, redraw: bool, criticism: str = "", attach=()):
    """The plan draws, from disk when they exist.

    Reuse is what makes `[b] back to plan` honest. If stepping back from the preview redrew
    the plans, every trip round the loop would cost API calls -- and a gate you will not use
    because it is expensive is decoration.
    """
    import pickle

    cache = work / "plans.pickle"
    if cache.exists() and not redraw:
        plans = [_retrace(plan, spec) for plan in pickle.loads(cache.read_bytes())]
        print(f"  reusing {len(plans)} plan draw(s) from the last run -- [r] to draw more")
        return plans

    work.mkdir(parents=True, exist_ok=True)
    # One room is not a layout question, so it is not put to the model: the chamber is the
    # room. Deterministic and free -- and the same every time, which a painted plan never is.
    if spec.rooms == 1 or args.synthetic:
        from PIL import Image

        if spec.rooms == 1:
            best = plan_mod.single_room_plan(spec)
            stem = "plan_single_room"
            print("  one room: using the chamber as the floor -- no draw needed")
        else:
            best = plan_mod.synthetic_plan(spec)
            stem = "plan_synthetic"
        best.painted_path = work / f"{stem}.png"
        best.composited_path = work / f"{stem}_overlay.png"
        plan_mod.overlay(best, Image.open(spec.roof_image).convert("RGBA")).save(
            best.composited_path)
        plans = [best]
    else:
        plans = plan_mod.draw_plans(spec, _config(args), work, draws=args.draws,
                                    criticism=criticism, attach=attach)
    cache.write_bytes(pickle.dumps(plans))
    return plans


# The two texts that go with the shape overlay, imported rather than restated. They are the
# strongest wording in the project -- "this is the most important directive it takes precedence
# over any other contradictory statements earlier in the prompt" -- and the interiors passes
# had never sent them.
def _shape_texts():
    from ..world_levels.checks import FOOTPRINT_OVERLAY_DIRECTIVE, FOOTPRINT_OVERLAY_NOTE

    return FOOTPRINT_OVERLAY_NOTE, FOOTPRINT_OVERLAY_DIRECTIVE


def _parse_gate_retry(raw: str, overlay):
    """`r1` / `r <why> @image <note>` at a gate -> (criticism, attachments).

    Shares `world_levels.retry` with the level review loop so there is one syntax to remember.
    A bare `r` is NOT handled here: it still means "draw more" in both gates, exactly as it
    always has, and the caller checks for it first.
    """
    from ..world_levels.retry import shape_retry, split_retry

    if raw[:2].lower() == "r1":
        if not overlay or not Path(overlay).is_file():
            raise FileNotFoundError(
                "no shape overlay for this draw (nothing to point at) -- draw one first")
        note, directive = _shape_texts()
        _reason, image, text = shape_retry(raw, Path(overlay), note, directive)
        return text, [image]
    reason, image, note = split_retry(raw)
    criticism = " ".join(part for part in (reason, note) if part).strip()
    return criticism, ([image] if image else [])


def _parse_augment_retry(answer: str, shape, composited) -> tuple:
    """`r2` / `r12` on an augmented render -> (criticism, attachments).

    r2 attaches the drift overlay -- the base with every changed pixel in red -- and the
    text that goes with it. r12 attaches that AND the shape overlay, shape first, so the
    two are image 3 and image 4 and each text names its own. `<tag>_drift.png` sits beside
    `<tag>_composited.png` like the shape file does; the fraction beside it in `.txt`.
    """
    from . import render as render_mod

    drift = Path(str(composited).replace("_composited.png", "_drift.png"))
    fraction_file = drift.with_suffix(".txt")
    if not drift.is_file():
        raise FileNotFoundError(
            "no drift overlay for this augment (nothing to point at) -- augment first")
    try:
        fraction = float(fraction_file.read_text().strip())
    except (OSError, ValueError):
        fraction = 0.0

    texts, attach = [], []
    if answer == "r12":
        if not shape or not Path(shape).is_file():
            raise FileNotFoundError("no shape overlay for this augment -- use r2")
        note, directive = _shape_texts()
        texts.append(f"IMAGE 3 is {note}. {directive}")
        attach.append(shape)
    note, directive = render_mod.drift_texts(fraction, 3 + len(attach))
    texts.append(f"{note} {directive}")
    attach.append(drift)
    return "\n".join(texts), attach


def _plan_gate(spec, work: Path, args, redraw: bool = False):
    """Draw floor plans, rank them by the free checks, and let you pick one."""
    blocked = plan_mod.preflight(spec)
    if blocked:
        print(f"\n  cannot draw a plan for {spec.building}: {blocked}", file=sys.stderr)
        return None

    choice = 0
    criticism, attach = "", ()
    plans = None
    while True:
        try:
            plans = _draw_or_reuse(spec, work, args, redraw, criticism, attach)
        except STEP_ERRORS as exc:
            _failed("drawing the plan", exc)
            if not plans:
                return None
            print("  back at the plan gate with the draws you had", file=sys.stderr)
        redraw, criticism, attach = False, "", ()
        if not plans:
            print("  no plans drawn", file=sys.stderr)
            return None
        choice %= len(plans)

        sheet = (plans[0].composited_path if args.synthetic else
                 plan_mod.ranked_sheet(plans, work / "plan_draws.png"))
        print(f"\n{len(plans)} plan(s), ranked best first:")
        for rank, plan in enumerate(plans, start=1):
            mark = ">" if rank - 1 == choice else " "
            verdict = "PASS" if plan.passed else "fails: " + ", ".join(plan.failed)
            print(f"  {mark} #{rank}  {Path(plan.painted_path).stem:<18} {verdict}")
        print(f"\n  {sheet}")
        _show(sheet)

        current = plans[choice]
        if not current.passed:
            print("  this draw fails its checks -- it will fail in the engine too")
        shape = getattr(current, "shape_path", None)
        _sent(_prompt_sent(work, "plan_prompt.txt", lambda: plan_mod.plan_prompt(spec)), [
            ("exterior", work / "plan_input.png"),
            ("mask", _mask_sent(work, "plan")),
            ("shape err", shape),
        ])
        print(_geometry_summary(spec))
        raw_answer = _ask(f"\n  [enter] use #{choice + 1}   [n] next draw   [r] draw more"
                          f"\n  [w] corridor width   [o] rooms   [g] doorway gap   "
                          f"(each redraws -- one API call per draw)"
                          f"\n  [r1] redraw showing this draw's shape error   "
                          f"[r <why> @img] redraw with criticism"
                          f"\n  [s] show again   [q] stop", "").strip()
        answer = raw_answer.lower()
        if not answer:
            # Asked here rather than discovered by `write_plan` after the gate has closed:
            # a refusal leaves you on this draw, at this menu, with every draw still in hand.
            refused = emit_mod.problem(current)
            if refused:
                print(f"\n  #{choice + 1} cannot be emitted: {refused}", file=sys.stderr)
                print("  still at the plan gate -- [n] another draw, [r] draw more, or [q]",
                      file=sys.stderr)
                continue
            try:
                _keep_plan(current, work)
            except STEP_ERRORS as exc:
                _failed("keeping the plan", exc)
                print("  still at the plan gate -- press enter again once it is closed",
                      file=sys.stderr)
                continue
            # The gate's [o] [w] [z] [g] [i] edit the spec in memory; keep them, or the next
            # run reloads the old numbers and `o 1` silently goes back to painted plans.
            spec.save(_spec_path(spec.building))
            return current
        if answer.startswith("q"):
            return None
        # `r1` and `r <something>` are retries with context; a bare `r` still means draw more.
        if answer == "r1" or answer.startswith("r1 ") or answer.startswith("r "):
            if args.synthetic:
                print("  --synthetic draws one plan; there is nothing to redraw")
                continue
            try:
                criticism, attach = _parse_gate_retry(raw_answer, shape)
            except (FileNotFoundError, OSError) as exc:
                print(f"  {exc}")
                criticism, attach = "", ()
                continue
            for path in attach:
                print(f"  attaching {Path(path).name}")
            redraw, choice = True, 0
        elif answer.startswith("n"):
            choice += 1
        elif answer.startswith("r"):
            if args.synthetic:
                print("  --synthetic draws one plan; there is nothing to redraw")
            else:
                redraw, choice = True, 0
        elif answer.startswith("w"):
            current = (spec.corridor_players or plan_mod.CORRIDOR_PLAYERS)[0]
            wide = _number("  how many players wide should a corridor be?", current)
            spec.corridor_players = (wide, wide * 1.6)
            redraw, choice = True, 0
        elif answer.startswith("z"):
            from .prompt import ROOM_PLAYERS

            current = (spec.room_players or ROOM_PLAYERS)[0]
            across = _number("  how many people across should a room be?", current)
            # A range rather than a number: the prompt reads better as "4 to 8 people", and
            # a single figure would have the model draw every room identical.
            spec.room_players = (across, across * 2)
            redraw, choice = True, 0
        elif answer.startswith("o"):
            rooms = _number("  how many rooms?  (0 for no target)", spec.rooms or 0)
            spec.rooms = int(rooms) or None
            redraw, choice = True, 0
        elif answer.startswith("g"):
            gap = _number("  doorway gap in px?", spec.door_gap or spec.door_width)
            _redoor(spec, gap)
            redraw, choice = True, 0
        elif answer.startswith("i"):
            # Both the wall band the render pass is shown and the collision quads read this,
            # so changing it moves the picture and what the player walks into together.
            spec.inner_wall = int(_number("  wall between rooms, in px?", spec.partition))
            redraw, choice = True, 0
        elif not answer.startswith("s"):
            print(f"  {answer!r}?")


def _preview_gate(plan) -> str:
    """Walk the doorway in the real engine and look at it. 'ok', 'back' or 'stop'."""
    from . import preview as preview_mod

    work = _work(plan.spec.building).resolve()
    try:
        scratch = emit_mod.scratch_level(plan.spec)
        result = emit_mod.write_plan(plan, scratch / "map.tmx")
        print(f"  scratch  : {scratch}")
        print(f"  walls {result['walls']}, rooms {result['rooms']}")
        frames = preview_mod.filmstrip(plan.spec, scratch, work / "preview")
        strip = preview_mod.contact_strip(frames, work / "preview" / "transition.png")
    except Exception as exc:                                   # noqa: BLE001
        # A preview that cannot run is not a reason to lose the plan behind it.
        print(f"  preview failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        answer = _ask("  [enter] carry on anyway   [b] back to plan   [q] stop", "")
        return {"b": "back", "q": "stop"}.get(answer.strip().lower()[:1], "ok")

    print(f"\n  {strip}")
    _show(strip)
    while True:
        answer = _ask("\n  [enter] the transition looks right   [b] back to plan   "
                      "[s] show again   [q] stop", "").strip().lower()
        if not answer:
            return "ok"
        if answer.startswith("b"):
            return "back"
        if answer.startswith("q"):
            return "stop"
        if answer.startswith("s"):
            _show(strip)
        else:
            print(f"  {answer!r}?")


def _render_gate(plan, work: Path, args):
    """Paint the stonework and choose which render to keep."""
    from . import render as render_mod

    choice, drawn = 0, None
    criticism, attach = "", ()
    # (base, additions) of the last augment, so `r1` on an augmented render re-augments the
    # same base with the same request plus the shape error -- not a fresh room from the roof.
    last_augment = None
    # Reuse is for ARRIVING at the gate, never for a redraw asked for at it. `[r]` used to
    # clear `drawn` and fall straight back into the reuse branch, which found the composites
    # still on disk and handed the same pictures back -- so "draw more" re-opened the last
    # render and cost nothing, which is why it looked like a button that only opens an image.
    force = bool(args.redraw)
    # The renders on screen before a redraw was asked for: what a failed redraw leaves you with.
    shown = None
    while True:
        if drawn is None:
            existing = (sorted(work.glob("render*_composited.png"))
                        + sorted(work.glob("augment*_composited.png")))
            if existing and not force:
                drawn = existing
                print(f"  reusing {len(drawn)} render(s) from the last run -- [r] for more")
            else:
                try:
                    drawn = render_mod.render_interior(plan, _config(args), work,
                                                       draws=args.draws,
                                                       criticism=criticism, attach=attach)
                    _drop_floor_trace(work)
                except STEP_ERRORS as exc:
                    _failed("the render", exc)
                    drawn = shown
                    if not drawn:
                        print("  back to the plan gate", file=sys.stderr)
                        return "back"
                    print("  back at the render gate with the renders you had", file=sys.stderr)
            criticism, attach, force = "", (), False
        if not drawn:
            print("  nothing rendered", file=sys.stderr)
            return None
        shown = drawn
        choice %= len(drawn)

        # The shape overlay for the render being looked at, not for draw 1. `<tag>_shape.png`
        # sits beside `<tag>_composited.png`, so the name follows from the one on screen.
        shape = Path(str(drawn[choice]).replace("_composited.png", "_shape.png"))
        is_augment = Path(drawn[choice]).name.startswith("augment")
        prompt_file = "augment_prompt.txt" if is_augment else "render_prompt.txt"
        _sent(_prompt_sent(work, prompt_file,
                           lambda: render_mod.render_prompt(plan.spec)), [
            ("exterior", plan.spec.roof_image),
            ("control", work / "control.png"),
            ("mask", _mask_sent(work, "render")),
            ("shape err", shape),
        ])
        print(f"\n{len(drawn)} render(s):")
        for rank, path in enumerate(drawn, start=1):
            print(f"  {'>' if rank - 1 == choice else ' '} #{rank}  {path}")
        _show(drawn[choice])
        augment_help = ("\n  [r2] re-add showing where it changed pixels it should not have   "
                        "[r12] both r1 and r2" if is_augment else "")
        raw_answer = _ask(f"\n  [enter] keep #{choice + 1}   [n] next   "
                          f"[r] try again (one API call)   [b] back to plan"
                          f"\n  [r1] try again showing this render's shape error   "
                          f"[r <why> @img] try again with criticism{augment_help}"
                          f"\n  [a <what to add>] keep #{choice + 1} and add to it   "
                          f"[s] show again   [q] stop", "").strip()
        answer = raw_answer.lower()
        if not answer:
            return drawn[choice]
        if answer.startswith("q"):
            return None
        if answer.startswith("b"):
            return "back"
        # Additive: this render, plus what was asked for. Its results replace the list, so
        # the next `a` stacks on the augmented one and [enter] keeps it.
        if answer == "a" or answer.startswith("a "):
            additions = raw_answer[1:].strip()
            if not additions:
                additions = _ask("  what should be added?", "").strip()
            if not additions:
                print("  nothing to add")
                continue
            base = drawn[choice]
            print(f"  augmenting {Path(base).name}: {additions}")
            try:
                augmented = render_mod.augment_interior(plan, _config(args), work, base,
                                                        additions, draws=args.draws)
            except STEP_ERRORS as exc:
                _failed("the augment", exc)
                continue
            if augmented:
                _drop_floor_trace(work)
                drawn, choice, last_augment = augmented, 0, (base, additions)
            continue
        # `r1` and `r <something>` are retries with context; a bare `r` still means draw more.
        # `r2` / `r12` exist only for an augment: the drift overlay is what it changed that
        # it should not have, which a from-scratch render has no notion of.
        is_drift_retry = is_augment and answer in ("r2", "r12")
        if is_drift_retry or answer == "r1" or answer.startswith("r1 ") or answer.startswith("r "):
            try:
                if is_drift_retry:
                    criticism, attach = _parse_augment_retry(answer, shape, drawn[choice])
                else:
                    criticism, attach = _parse_gate_retry(raw_answer, shape)
            except (FileNotFoundError, OSError) as exc:
                print(f"  {exc}")
                criticism, attach = "", ()
                continue
            for path in attach:
                print(f"  attaching {Path(path).name}")
            # On an augmented render, the retry is the same augment shown its own miss. The
            # base and request come from this session when it made the augment, else from
            # the sidecar it wrote -- a resumed session must not fall through to a fresh
            # render from the roof, which is what `r1` on an augment used to do.
            if is_augment and last_augment is None:
                meta = Path(str(drawn[choice]).replace("_composited.png", "_meta.json"))
                try:
                    loaded = json.loads(meta.read_text(encoding="utf-8"))
                    last_augment = (Path(loaded["base"]), loaded["additions"])
                except (OSError, ValueError, KeyError):
                    print(f"  no record of what {Path(drawn[choice]).name} was made from "
                          f"({meta.name} missing) -- use [a <what>] on the base render instead")
                    criticism, attach = "", ()
                    continue
            if is_augment and last_augment is not None:
                base, additions = last_augment
                print(f"  re-augmenting {Path(base).name}: {additions}")
                try:
                    augmented = render_mod.augment_interior(
                        plan, _config(args), work, base, additions, draws=args.draws,
                        criticism=criticism, attach=attach)
                except STEP_ERRORS as exc:
                    _failed("the augment", exc)
                    augmented = None
                criticism, attach = "", ()
                if augmented:
                    _drop_floor_trace(work)
                    drawn, choice = augmented, 0
                continue
            drawn, choice, force = None, 0, True
        elif answer.startswith("n"):
            choice += 1
        elif answer.startswith("r"):
            drawn, choice, force = None, 0, True
        elif not answer.startswith("s"):
            print(f"  {answer!r}?")


def _write_into_map(plan, written: Path) -> None:
    """The one step that changes the shipped level."""
    map_path = Path(plan.spec.map_path)
    roof = Path(plan.spec.roof_image)
    if not _inside(roof, map_path.parent):
        # The map resolves art relative to its own folder, and on the sam3 path the
        # exterior is a crop sitting in the work directory. Copy it in beside the interior
        # so the level stays self-contained.
        destination = map_path.parent / "buildings" / f"{plan.spec.building}_roof.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(roof, destination)
        plan.spec.roof_image = str(destination)
        print(f"  exterior : {destination}")
    result = emit_mod.write_plan(plan, map_path)
    print(f"  interior : {written}")
    print(f"  map      : {result['map']}  ({result['walls']} walls, {result['shell']} shell, "
          f"{result['rooms']} rooms"
          f"{', building object added' if result.get('building_object') else ''})")


# The two checks a floor must pass before it is written. A floor that does not reach the
# doorway walls the passage; an unpainted one is not a trace at all. Everything else the
# report says is for the eye, together with the overlay.
FLOOR_GATE_CHECKS = ("floor_behind_door", "unpainted")


def _floor_gate(plan, kept: Path, work: Path, args):
    """Trace the accepted render into the room the model painted, look at it, write it.

    What comes out is the chamber (floor and walls), the collision (the floor's edge) and
    the trigger for "inside" -- everything the engine will believe about this building. So
    it is shown over the render it traced, and it is not written until it has been looked
    at. `[f <path>]` feeds a painting made by hand into the same tracer.

    `[enter]` writes, here, so that a write the emitter refuses -- or one a held file stops
    -- leaves you at this menu with this painting rather than ending the session. Returns
    the traced plan once written, None on [q], and "back" when the floor painting could not
    be drawn and there is none to show: the decision before this one is the render.
    """
    from . import floor as floor_mod
    from . import render as render_mod

    painting, previous, force = None, None, bool(args.redraw)
    while True:
        if painting is None:
            try:
                painting = floor_mod.draw_floor(plan, _config(args), work, kept, force=force)
            except STEP_ERRORS as exc:
                _failed("the floor painting", exc)
                painting = previous
                if painting is None:
                    print("  back to the render gate", file=sys.stderr)
                    return "back"
                print("  back at the floor gate with the painting you had", file=sys.stderr)
            force = False
        traced = floor_mod.trace_floor(painting, plan.spec)
        shown = floor_mod.floor_overlay(traced, kept, work / "floor_overlay.png")
        print(layout_checks.format_report(traced.report, "floor"))
        _sent(_prompt_sent(work, "floor_prompt.txt", lambda: floor_mod.floor_prompt(plan.spec)), [
            ("render", kept),
            ("plan", work / "floor_plan.png"),
            ("mask", _mask_sent(work, "floor")),
            ("trace", shown),
        ])
        failed = [c for c in traced.report["checks"]
                  if c["name"] in FLOOR_GATE_CHECKS and not c["passed"]]
        _show(shown)
        if failed:
            names = ", ".join(c["name"] for c in failed)
            print(f"\n  NOT WRITABLE -- {names} failed: "
                  + ("the painted floor does not reach the doorway, so the passage would be "
                     "walled. " if any(c["name"] == "floor_behind_door" for c in failed) else "")
                  + "Fix the painting with [f], or [q] and redraw the render.")
        raw_answer = _ask(f"\n  {'[enter] write   ' if not failed else ''}"
                          f"[r] trace again (one API call)   [f <path>] use this painting instead"
                          f"\n  [s] show again   [q] stop", "").strip()
        answer = raw_answer.lower()
        if not answer:
            if failed:
                print("  not written")
                continue
            refused = emit_mod.problem(traced)
            if refused:
                print(f"\n  not written: {refused}", file=sys.stderr)
                print("  still at the floor gate -- [r] trace again, [f <path>] another "
                      "painting, or [q]", file=sys.stderr)
                continue
            try:
                _write_into_map(traced, render_mod.accept(traced, kept))
            except STEP_ERRORS as exc:
                _failed("writing the map", exc)
                print("  still at the floor gate", file=sys.stderr)
                continue
            return traced
        if answer.startswith("q"):
            return None
        if answer.startswith("f"):
            path = Path(raw_answer[1:].strip().strip('"'))
            if not path.is_file():
                print(f"  no painting at {path}")
                continue
            from PIL import Image

            try:
                painting = Image.open(path).convert("RGB")
            except OSError as exc:
                _failed(f"reading {path.name}", exc)
                continue
            print(f"  tracing {path.name}")
        elif answer.startswith("r"):
            previous, painting, force = painting, None, True
        elif not answer.startswith("s"):
            print(f"  {answer!r}?")


def _accept_and_write(plan, kept: Path, work: Path, args):
    """From a kept render to the shipped map: trace its floor, cut the asset, write.

    The one accept path, for `build`, `render` and `accept` alike. The floor gate's
    `[enter] write` is the confirmation, and the write happens there; there is no second
    "write into map?" prompt. True when written, False when stopped, "back" when the floor
    gate sent you back to choose a render.
    """
    blocked = plan_mod.preflight(plan.spec)
    if blocked:
        print(f"\n  cannot accept {plan.spec.building}: {blocked}", file=sys.stderr)
        return False
    traced = _floor_gate(plan, kept, work, args)
    if traced is None or traced == "back":
        print("  map untouched")
        return False if traced is None else "back"
    return True


def _build(spec, args) -> bool:
    """One building, from its spec to an accepted interior in the map.

    The same shape as the discovery loops: run the expensive thing once, show it, accept or
    adjust. `[b] back to plan` is the reason preview sits before render rather than after --
    a bad layout is cheap to discover and expensive to paint.
    """
    work = _work(spec.building)
    print(f"\n{'=' * 70}\n{spec.building}\n{'=' * 70}")
    print(spec_mod.describe(spec))

    # --redraw means draw fresh once, not redraw on every trip round the loop. Coming back
    # from the preview has to be free or nobody comes back from the preview.
    redraw = args.redraw
    while True:
        plan = _plan_gate(spec, work, args, redraw)
        redraw = False
        if plan is None:
            return False

        # Emit is free and derived, so it always runs -- the scratch map is what a manual
        # in-game check loads. The PREVIEW is opt-in: it boots a real Level4, and walking the
        # doorway yourself tells you more than a filmstrip does. Both show the REQUEST: the
        # room the model actually paints is traced at accept, after the render exists, and
        # cannot be previewed before it.
        try:
            scratch = emit_mod.scratch_level(plan.spec)
            result = emit_mod.write_plan(plan, scratch / "map.tmx")
        except STEP_ERRORS as exc:
            _failed("writing the scratch map", exc)
            print("  back to the plan gate", file=sys.stderr)
            continue
        print(f"  scratch  : {scratch}")
        print(f"  walls {result['walls']}, rooms {result['rooms']}")
        if args.preview:
            verdict = _preview_gate(plan)
            if verdict == "stop":
                return False
            if verdict == "back":
                continue

        if args.synthetic:
            print("\n  --synthetic stops here: a procedural plan has no stonework to paint. "
                  "Re-run with --config to generate the interior.")
            return True

        written = _render_then_accept(plan, work, args)
        if written != "back":
            return written


def _render_then_accept(plan, work: Path, args):
    """The render gate, then the floor gate, with a way back from the second to the first.

    True when the map was written, False when stopped, "back" for the plan gate. The floor
    gate hands back "back" when it has no floor painting to show -- the draw failed -- and the
    decision before it is which render to keep, so that is where you land.
    """
    while True:
        kept = _render_gate(plan, work, args)
        if kept is None or kept == "back":
            return False if kept is None else "back"
        written = _accept_and_write(plan, Path(kept), work, args)
        if written != "back":
            return written
        # --redraw means draw fresh once. Coming back to choose a render again must reuse
        # the ones already bought, not buy another.
        args.redraw = False


# ---------------------------------------------------------------- furnishing

def _require_accepted(spec) -> None:
    if not Path(spec.interior_image).exists():
        raise SystemExit(f"no accepted interior for {spec.building} at {spec.interior_image}: "
                         f"run `build` first")


def _room_plan(spec, work: Path, args):
    """The plan decorate shows the model: the painted room's trace, else the requested one."""
    from . import decorate as decor_mod

    plan = decor_mod.room_plan(spec, work)
    if plan is None:
        print("  no floor trace on disk -- showing the model the requested plan, which may "
              "not match the painted room")
        plan = _load_plan(spec.building, args)
    return plan


def _numbers_then_text(rest: str) -> tuple:
    """"2 5 too busy" -> ([2, 5], "too busy"): the variants, then any criticism."""
    numbers, words = [], rest.replace(",", " ").split()
    while words and words[0].isdigit():
        numbers.append(int(words.pop(0)))
    return numbers, " ".join(words)


def _decorate_gate(plan, spec, work: Path, args):
    """Step 1: the room decorated once per line of decor/styles.txt, and which to keep.

    Arriving draws every variant never drawn -- one API call each, the way the render gate
    draws on arrival -- and reuses the rest. A stale variant (its line edited, or the room
    re-rendered under it) is shown, not redrawn: a redraw costs a call, so it is asked for.
    Returns the variants kept, or None on [q].
    """
    from . import decorate as decor_mod
    from . import render as render_mod

    styles = decor_mod.ensure_styles(spec, work, args.variants)
    base, base_sha1 = decor_mod.write_base(spec, work)
    dry_run = bool(getattr(args, "dry_run", False))
    print(f"\n  step 1, decorate: one variant per line of {styles}")
    redraw = {}                      # variant number -> criticism, asked for at the gate
    arriving = True
    while True:
        found = decor_mod.variants(work, base_sha1, dry_run)
        if arriving:
            for variant in found:
                if variant.kept and (args.redraw or not variant.drawn):
                    redraw.setdefault(variant.number, "")
            arriving = False
        for variant in found:
            if variant.number not in redraw:
                continue
            criticism = redraw[variant.number]
            print(f"\n  drawing {variant.tag}: {variant.additions}"
                  + (f"\n  criticism: {criticism}" if criticism else ""))
            try:
                if variant.drawn:
                    _set_aside(variant.folder, decor_mod.DRAW_FILES)
                decor_mod.draw_variant(plan, _config(args), variant, base, base_sha1,
                                       criticism=criticism)
            except STEP_ERRORS as exc:
                _failed(f"drawing {variant.tag}", exc)
        redraw = {}

        found = decor_mod.variants(work, base_sha1, dry_run)
        strip = decor_mod.decor_strip(base, found, decor_mod.decor_dir(work) / decor_mod.STRIP)
        shown = next((v for v in found if v.drawn), None)
        if shown is not None:
            _sent(_prompt_sent(shown.folder, decor_mod.PROMPT,
                               lambda: render_mod.augment_prompt(spec, shown.additions,
                                                                 decorate=True)), [
                ("room", shown.folder / "augment_input.png"),
                ("plan", shown.folder / "control.png"),
                ("mask", _mask_sent(shown.folder, "augment")),
            ])
            print(f"  ({shown.tag}'s; each variant's prompt differs only in its ADD line)")
        print(f"\n{len(found)} variant(s):")
        for variant in found:
            print(f"  {variant.tag}  {variant.status():<26} {variant.additions or '-'}")
        print(f"\n  strip: {strip}")
        _show(strip)

        pending = [v for v in found if v.kept and v.additions and (not v.drawn or v.stale)]
        draw_help = (f"   [d] draw the {len(pending)} not drawn or stale ({len(pending)} API "
                     f"call{'' if len(pending) == 1 else 's'})" if pending else "")
        raw_answer = _ask(
            "\n  [enter] go on with the ones kept   [x 2 5] drop   [u 2] undo a drop"
            "\n  [r 2 5] redraw (one API call each)   [r 2 <why>] redraw with criticism"
            f"{draw_help}"
            "\n  [o 2] open one full size, with what it changed   [e] edit styles.txt   "
            "[s] show again   [q] stop", "").strip()
        answer = raw_answer.lower()
        if not answer:
            usable = [v for v in found if v.usable]
            if not usable:
                print("  nothing to go on with: no variant is drawn, kept and current")
                continue
            left = [v.tag for v in found if v.kept and v.additions and not v.usable]
            if left:
                print(f"  going on without {', '.join(left)} (not drawn or stale)")
            return usable
        if answer.startswith("q"):
            return None
        letter = answer[0]
        numbers, text = _numbers_then_text(raw_answer[1:])
        by_number = {v.number: v for v in found}
        unknown = [n for n in numbers if n not in by_number]
        if unknown:
            print(f"  no variant {', '.join(map(str, unknown))}")
        chosen = [by_number[n] for n in numbers if n in by_number]
        if letter in "rdu":
            lineless = [v.tag for v in chosen if not v.additions]
            if lineless:
                print(f"  {', '.join(lineless)}: no line in styles.txt to draw from")
            chosen = [v for v in chosen if v.additions]
        if letter == "x":
            for variant in chosen:
                decor_mod.set_kept(variant, False)
        elif letter == "u":
            for variant in chosen:
                decor_mod.set_kept(variant, True)
        elif letter == "r":
            if not numbers:
                print("  which? [r 2] or [r 2 5 <why>]")
            for variant in chosen:
                redraw[variant.number] = text
        elif letter == "d":
            for variant in pending:
                redraw[variant.number] = ""
        elif letter == "o":
            for variant in chosen:
                if not variant.drawn:
                    print(f"  {variant.tag} is not drawn")
                    continue
                _show(variant.composited)
                _show(variant.folder / "augment_drift.png")
        elif letter == "e":
            _show(styles)
            print(f"  editing {styles} -- save it, then [s] here to see what changed")
        elif letter != "s":
            print(f"  {answer!r}?")


def _style_source(spec, which: str, states: list):
    """What `[m <which>]` names: a variant's sheet (`m 2`) or a sheet of the set (`m s01`)."""
    from . import kit as kit_mod

    which = which.strip().lower()
    if which.isdigit():
        state = next((s for s in states if s.variant.number == int(which)), None)
        if state is None or not state.drawn:
            print(f"  no sheet drawn for variant {which}")
            return None
        return state.sheet
    found = sorted((kit_mod.prop_set_dir(spec) / "_sheets").glob(f"{which}.*"))
    if not found:
        print(f"  no sheet {which!r} in {kit_mod.prop_set_dir(spec) / '_sheets'}")
        return None
    return found[0]


def _sheet_gate(plan, spec, work: Path, args, kept: list):
    """Step 2: a sprite sheet per kept variant, and which to go on with.

    Arriving draws a sheet for every kept variant that has none -- one API call each, the
    way the decorate gate draws on arrival -- and reuses the rest. A stale sheet (its room
    redrawn at step 1) is shown, not redrawn. Returns the states with a current sheet to go
    on with, None on [q], "back" on [b].
    """
    from . import decorate as decor_mod
    from . import kit as kit_mod

    dry_run = bool(getattr(args, "dry_run", False))
    print(f"\n  step 2, sprite sheets: one per kept variant, into {kit_mod.prop_set_dir(spec)}")
    redraw, arriving = {}, True
    while True:
        states = [kit_mod.sheet_state(v, dry_run) for v in kept]
        if arriving:
            for state in states:
                if args.redraw or not state.drawn:
                    redraw.setdefault(state.variant.number, "")
            arriving = False
        for state in states:
            if state.variant.number not in redraw:
                continue
            criticism = redraw[state.variant.number]
            print(f"\n  drawing {state.tag}'s sheet"
                  + (f"\n  criticism: {criticism}" if criticism else ""))
            try:
                if state.drawn:
                    _set_aside(state.variant.folder, kit_mod.SHEET_FILES)
                kit_mod.draw_sheet(plan, _config(args), state.variant, criticism=criticism)
            except STEP_ERRORS as exc:
                _failed(f"drawing {state.tag}'s sheet", exc)
        redraw = {}

        states = [kit_mod.sheet_state(v, dry_run) for v in kept]
        strip = kit_mod.sheets_strip(states, decor_mod.decor_dir(work) / kit_mod.STRIP)
        shown = next((s for s in states if s.drawn), None)
        style = kit_mod.style_master(spec)
        if shown is not None:
            folder = shown.variant.folder
            _sent(_prompt_sent(folder, kit_mod.SHEET_PROMPT, lambda: kit_mod.sheet_prompt(
                spec, shown.variant.additions, bool(style))), [
                ("room", folder / kit_mod.SHEET_ROOM),
                ("style", style),
            ])
            print(f"  ({shown.tag}'s; each variant sends its own room)")
        if style is None:
            print(f"\n  no style master for {kit_mod.prop_set_dir(spec).name} yet: [m 2] locks "
                  f"v02's sheet (or [m s01] a sheet already in the set) as the style later "
                  f"sheets are drawn to")
        print(f"\n{len(states)} sheet(s):")
        for state in states:
            print(f"  {state.tag}  {state.status()}")
        print(f"\n  strip: {strip}")
        _show(strip)

        pending = [s for s in states if not s.drawn or s.stale]
        draw_help = (f"   [d] draw the {len(pending)} not drawn or stale ({len(pending)} API "
                     f"call{'' if len(pending) == 1 else 's'})" if pending else "")
        raw_answer = _ask(
            "\n  [enter] go on   [r 2 5] redraw (one API call each)   [r 2 <why>] redraw with "
            f"criticism{draw_help}"
            "\n  [o 2] open v02's room and sheet   [m 2] lock v02's sheet as the set's style"
            "\n  [b] back to decorate   [s] show again   [q] stop", "").strip()
        answer = raw_answer.lower()
        if not answer:
            usable = [s for s in states if s.usable]
            if not usable:
                print("  nothing to go on with: no sheet is drawn and current")
                continue
            left = [s.tag for s in states if not s.usable]
            if left:
                print(f"  going on without {', '.join(left)} (not drawn or stale)")
            return usable
        if answer.startswith("q"):
            return None
        if answer.startswith("b"):
            return "back"
        letter = answer[0]
        if letter == "m":
            source = _style_source(spec, answer[1:], states)
            if source is not None:
                target = kit_mod.use_as_style(spec, source)
                print(f"  style master: {target} (from {source}); sheets drawn from now on "
                      f"are shown it -- [r] the others to draw them to it")
            continue
        numbers, text = _numbers_then_text(raw_answer[1:])
        by_number = {s.variant.number: s for s in states}
        unknown = [n for n in numbers if n not in by_number]
        if unknown:
            print(f"  no kept variant {', '.join(map(str, unknown))}")
        chosen = [by_number[n] for n in numbers if n in by_number]
        if letter == "r":
            if not numbers:
                print("  which? [r 2] or [r 2 5 <why>]")
            for state in chosen:
                redraw[state.variant.number] = text
        elif letter == "d":
            for state in pending:
                redraw[state.variant.number] = ""
        elif letter == "o":
            for state in chosen:
                if not state.drawn:
                    print(f"  {state.tag} has no sheet")
                    continue
                _show(state.variant.composited)
                _show(state.sheet)
        elif letter != "s":
            print(f"  {answer!r}?")


def _extract_gate(spec, work: Path, args, sheets: list):
    """Step 3: each sheet cut into the prop set, tagged, and the cuts reviewed.

    Free: cutting and tagging cost no image call (tags are asked through `claude -p`, and
    not at all under --dry-run). A sheet is cut on arrival when it has not been cut since it
    was drawn. `[enter]` writes the set's tileset and goes on; only kept props are placed.
    Returns the sheet states to go on with, None on [q], "back" on [b].
    """
    from tools.sprite_assets import props as props_mod

    from . import decorate as decor_mod
    from . import extract as extract_mod

    dry_run = bool(getattr(args, "dry_run", False))
    catalog = extract_mod.load_catalog(spec)
    cut = sheets
    print(f"\n  step 3, extract: each sheet cut into {extract_mod.set_dir(spec)}")
    for state in cut:
        if extract_mod.is_current(state):
            continue
        try:
            record = extract_mod.extract_variant(spec, state, catalog)
            extract_mod.save_catalog(spec, catalog)
            print(f"  {state.tag}: {len(record['props'])} prop(s) cut from its sheet, "
                  f"logged as {record['sheet']}")
        except STEP_ERRORS as exc:
            _failed(f"cutting {state.tag}'s sheet", exc)

    def ask_for_tags():
        if dry_run:
            print("  --dry-run: no tags asked for")
            return
        for state in cut:
            key = extract_mod.extracted(state.variant).get("sheet")
            if key and extract_mod.tag_variant(spec, catalog, key):
                extract_mod.save_catalog(spec, catalog)

    ask_for_tags()
    while True:
        by_id = {p["id"]: p for p in catalog["props"]}
        rows = []
        print(f"\n{len(sheets)} variant(s):")
        for state in sheets:
            record = extract_mod.extracted(state.variant)
            key = record.get("sheet", "")
            props = extract_mod.props_of(catalog, key) if key else []
            kept = sum(1 for p in props if p.get("keep", True))
            notes = []
            if extract_mod.untagged(props):
                notes.append(f"{len(extract_mod.untagged(props))} untagged")
            print(f"  {state.tag}  {key or '-':<4} {kept} kept of {len(props)}"
                  + (f"  ({', '.join(notes)})" if notes else ""))
            if key:
                rows.append((f"{state.tag}  {key}: {kept} kept of {len(props)}",
                             extract_mod.refresh_contact(spec, catalog, key)))
        strip = extract_mod.extract_strip(spec, rows, decor_mod.decor_dir(work) / "extract_strip.png")
        print(f"\n  contact sheets: {strip}")
        _show(strip)
        raw_answer = _ask(
            "\n  [enter] write the tileset and go on   [x s10_03 s10_07] strike   [u s10_03] "
            "bring back"
            "\n  [t s10_03 urn floor <name>] tag one by hand   [a] ask for the missing tags"
            "\n  [o 2] open v02's contact sheet and what was cut   [b] back to the sheets   "
            "[s] show again   [q] stop", "").strip()
        answer = raw_answer.lower()
        if not answer:
            path = props_mod.write_tileset(extract_mod.set_dir(spec), catalog)
            extract_mod.save_catalog(spec, catalog)
            print(f"  tileset  : {path}")
            return sheets
        if answer.startswith("q"):
            return None
        if answer.startswith("b"):
            return "back"
        letter, words = answer[0], raw_answer[1:].split()
        if letter in "xu":
            unknown = [w for w in words if w not in by_id]
            if unknown:
                print(f"  no prop {', '.join(unknown)}")
            for word in words:
                if word in by_id:
                    by_id[word]["keep"] = letter == "u"
            extract_mod.save_catalog(spec, catalog)
        elif letter == "t":
            if len(words) < 3 or words[0] not in by_id:
                print("  [t <id> <category> <floor|wall> <name...>]")
                continue
            wrong = extract_mod.set_tag(by_id[words[0]], words[1], words[2], " ".join(words[3:]))
            if wrong:
                print(f"  {wrong}")
            else:
                extract_mod.save_catalog(spec, catalog)
        elif letter == "a":
            ask_for_tags()
        elif letter == "o":
            numbers, _text = _numbers_then_text(raw_answer[1:])
            for state in cut:
                if state.variant.number in numbers:
                    key = extract_mod.extracted(state.variant).get("sheet")
                    if key:
                        _show(extract_mod.contact_sheet(spec, key))
                        _show(extract_mod.set_dir(spec) / "_debug" / f"{key}_overlay.png")
        elif letter != "s":
            print(f"  {answer!r}?")


def _placements_current(state, threshold: float, kept_ids: set) -> bool:
    """Are this variant's placements from its room and sheet as they are, at `threshold`,
    with every prop they place still kept?"""
    from . import kit as kit_mod
    from . import locate as locate_mod

    record = locate_mod.read_placements(state.variant)
    if not record or record.get("threshold") != threshold:
        return False
    return (record.get("composited_sha1") == kit_mod.file_sha1(state.variant.composited)
            and record.get("sheet_sha1") == kit_mod.file_sha1(state.sheet)
            and all(p["prop"] in kept_ids for p in record.get("placements", [])))


def _locate_gate(plan, spec, work: Path, args, sheets: list):
    """Step 4: each prop cut from a variant's sheet found in its room, and the room rebuilt.

    Free. Arriving locates every variant whose placements are missing or out of date -- its
    room or sheet redrawn, a prop it placed struck since -- and reuses the rest. Judged on
    decorated | recreated: the recreated room is the bare interior with the real cut-outs on
    it, which is what the game will show. Returns [(state, placements)] to place, None on
    [q], "back" on [b].
    """
    from . import decorate as decor_mod
    from . import extract as extract_mod
    from . import locate as locate_mod

    base, _sha1 = decor_mod.write_base(spec, work)
    threshold = locate_mod.MATCH_THRESHOLD
    dropped = set()
    redo, arriving = set(), True
    print("\n  step 4, locate: each variant's props put back in its room")
    while True:
        catalog = extract_mod.load_catalog(spec)
        kept_ids = {p["id"] for p in catalog["props"] if p.get("keep", True)}
        live = [s for s in sheets if s.variant.number not in dropped]
        if arriving:
            redo = {s.variant.number for s in live
                    if args.redraw or not _placements_current(s, threshold, kept_ids)}
            arriving = False
        for state in live:
            if state.variant.number not in redo:
                continue
            print(f"  locating {state.tag} ...", flush=True)
            try:
                placed, missing = locate_mod.locate_variant(spec, plan, state, catalog, base,
                                                            threshold)
                print(f"  {state.tag}: {len(placed)} prop(s) placed, {len(missing)} not found")
            except STEP_ERRORS as exc:
                _failed(f"locating {state.tag}", exc)
        redo = set()

        rows, ready = [], []
        print(f"\n{len(live)} variant(s), match threshold {threshold:.2f}:")
        for state in live:
            record = locate_mod.read_placements(state.variant)
            placements = record.get("placements", [])
            line = (f"{state.tag}  {len(placements)} placed, "
                    f"{len(record.get('missing', []))} not found")
            print(f"  {line}" if record else f"  {state.tag}  not located")
            rows.append((line + "      decorated  |  recreated",
                         state.variant.folder / locate_mod.COMPARE))
            if placements:
                ready.append((state, record))
        strip = locate_mod.review_strip(rows, decor_mod.decor_dir(work) / "locate_strip.png")
        print(f"\n  decorated | recreated: {strip}")
        _show(strip)
        raw_answer = _ask(
            "\n  [enter] place these   [x 2] drop v02   [u 2] bring it back   "
            "[l 0.5] locate again at another match threshold"
            "\n  [o 2] open v02 full size, with what was placed where   [b] back to extract   "
            "[s] show again   [q] stop", "").strip()
        answer = raw_answer.lower()
        if not answer:
            if not ready:
                print("  nothing to place")
                continue
            return ready
        if answer.startswith("q"):
            return None
        if answer.startswith("b"):
            return "back"
        letter = answer[0]
        if letter == "l":
            try:
                threshold = float(raw_answer[1:].strip())
            except ValueError:
                print("  [l <threshold>], e.g. [l 0.5]: higher places fewer, surer props")
                continue
            redo = {s.variant.number for s in live}
            continue
        numbers, _text = _numbers_then_text(raw_answer[1:])
        by_number = {s.variant.number: s for s in sheets}
        for number in numbers:
            state = by_number.get(number)
            if state is None:
                print(f"  no variant {number} here")
            elif letter == "x":
                dropped.add(number)
                decor_mod.set_kept(state.variant, False)
            elif letter == "u":
                dropped.discard(number)
                decor_mod.set_kept(state.variant, True)
            elif letter == "o":
                _show(state.variant.folder / locate_mod.COMPARE)
                _show(state.variant.folder / locate_mod.LOCATED)
        if letter not in "xuos":
            print(f"  {answer!r}?")


def _place_gate(spec, work: Path, args, located: list):
    """Step 5: the placements written into the map as Tiled objects, one set per variant.

    Written to the scratch level first, where `[p]` walks it in the game. `[a]` writes the
    shipped map, after a copy of it is put in the work folder. Never under --dry-run: the
    copy backend's props do not go near the shipped map. True once written, False on [q],
    "back" on [b].
    """
    from datetime import datetime

    from tools.sprite_assets import props as props_mod

    from . import decorate as decor_mod
    from . import extract as extract_mod
    from . import kit as kit_mod
    from . import preview as preview_mod

    catalog = extract_mod.load_catalog(spec)
    tsx = props_mod.write_tileset(kit_mod.prop_set_dir(spec), catalog)
    span = int(catalog["next_tile_id"])
    variants = [(state.tag, record["placements"]) for state, record in located]
    dry_run = bool(getattr(args, "dry_run", False))
    print(f"\n  step 5, place: {sum(len(p) for _t, p in variants)} props in "
          f"{len(variants)} variant(s), from {tsx}")
    try:
        scratch = emit_mod.scratch_level(spec)
        result = emit_mod.write_props(spec, variants, scratch / "map.tmx", tsx, span)
    except STEP_ERRORS as exc:
        _failed("writing the scratch map", exc)
        return "back"
    print(f"  scratch  : {result['map']}  (open it in Tiled, or [p] to walk it in the game)")
    while True:
        accept = "" if dry_run else "[a] write them into the shipped map   "
        answer = _ask(f"\n  {accept}[p] walk the scratch level in the game   "
                      f"[b] back to locate   [q] stop", "").strip().lower()
        if answer.startswith("q"):
            return False
        if answer.startswith("b"):
            return "back"
        if answer.startswith("p"):
            try:
                frames = preview_mod.filmstrip(spec, scratch, work.resolve() / "preview")
                strip = preview_mod.contact_strip(frames, work.resolve() / "preview" /
                                                  "furnished.png")
            except Exception as exc:                               # noqa: BLE001
                print(f"  preview failed ({type(exc).__name__}: {exc})", file=sys.stderr)
                continue
            print(f"  {strip}")
            _show(strip)
        elif answer.startswith("a"):
            if dry_run:
                print("  --dry-run: the shipped map is not written")
                continue
            map_path = Path(spec.map_path)
            backup = decor_mod.decor_dir(work) / (
                f"map_before_props_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.tmx")
            try:
                shutil.copyfile(map_path, backup)
                written = emit_mod.write_props(spec, variants, map_path, tsx, span)
            except STEP_ERRORS as exc:
                _failed("writing the map", exc)
                continue
            print(f"  map      : {written['map']}  ({written['props']} props in "
                  f"{written['variants']} variant(s), tileset at firstgid {written['firstgid']})")
            print(f"  backup   : {backup}")
            return True
        else:
            print(f"  {answer!r}?")


def _furnish(spec, args) -> bool:
    """One accepted building, furnished, with a gate after every step.

    Steps 1-3 are what used to be done by hand -- decorate the room (Leonardo), draw a sprite
    sheet of what was added (Leonardo), cut the sheet (`extract-props`) -- and 4-5 locate those
    props in each variant and place them in the map. `[b]` at a gate goes back one step;
    coming back reuses what is on disk, and `--redraw` draws fresh on the first pass only.
    """
    _require_accepted(spec)
    _furnishing_run(args)
    work = _work(spec.building)
    print(f"\n{'=' * 70}\n{spec.building}: furnishing\n{'=' * 70}")
    plan = _room_plan(spec, work, args)
    step, kept, sheets, cut, located = 1, None, None, None, None
    while True:
        if step == 1:
            kept = _decorate_gate(plan, spec, work, args)
            result = kept
        elif step == 2:
            sheets = _sheet_gate(plan, spec, work, args, kept)
            result = sheets
        elif step == 3:
            cut = _extract_gate(spec, work, args, sheets)
            result = cut
        elif step == 4:
            located = _locate_gate(plan, spec, work, args, cut)
            result = located
        else:
            result = _place_gate(spec, work, args, located)
            if result is True:
                return True
        if result is None or result is False:
            return False
        if result == "back":
            # --redraw draws fresh on the way in, once; stepping back reuses what is there.
            args.redraw, step = False, step - 1
            continue
        if step == 1:
            print(f"\n  kept {len(kept)} variant(s): {', '.join(v.tag for v in kept)}")
        step += 1


def _furnishing_run(args) -> None:
    """Per-run setup shared by `furnish` and its single-step commands."""
    from . import kit as kit_mod

    if getattr(args, "dry_run", False):
        kit_mod.dry_run_sets()
        print(f"  --dry-run: prop sets go to {kit_mod.PROPS_ROOT}, the shipped map is not "
              f"written")


def cmd_build(args) -> int:
    """Walk one existing spec from plan to accepted interior."""
    return 0 if _build(_load_spec(args.building, args), args) else 2


def _load_plan(building: str, args=None):
    """The kept plan, re-derived against the spec as it is now (see `_retrace`)."""
    import pickle

    path = _work(building) / "plan.pickle"
    if not path.exists():
        raise SystemExit(f"no traced plan for {building!r}: run `plan` first")
    return _retrace(pickle.loads(path.read_bytes()), _load_spec(building, args))


def cmd_emit(args) -> int:
    """The requested plan, written to the scratch level. What is on the shipped map after
    accept is the TRACED room; re-emitting that is `accept` again, free once its floor
    painting exists."""
    plan = _load_plan(args.building, args)
    try:
        scratch = emit_mod.scratch_level(plan.spec)
        result = emit_mod.write_plan(plan, scratch / "map.tmx")
    except STEP_ERRORS as exc:
        _failed("emit", exc)
        return 2
    print(f"scratch level : {scratch}")
    print(f"walls         : {result['walls']} segments, {result['shell']} shell")
    print(f"chamber       : {len(result['chamber'])} vertices")
    print(f"rooms         : {result['rooms']} spawn areas")
    print(f"doors         : {result['doors']}")
    print(f"\nnext:  ... preview --building {args.building}")
    return 0


def cmd_preview(args) -> int:
    """Walk the doorway in the game and save the frames. Run it with the game's Python
    (`Code\\sprite_venv\\Scripts\\python.exe`): the engine needs pytmx."""
    from . import preview as preview_mod

    work = _work(args.building).resolve()
    if args.level:
        # The real level, with whatever accept last wrote into it.
        spec = _load_spec(args.building, args)
        layouts = Path(spec.map_path).resolve().parent
    else:
        spec = _load_plan(args.building, args).spec
        layouts = emit_mod.scratch_level(spec)
    frames = preview_mod.filmstrip(spec, layouts, work / "preview")
    strip = preview_mod.contact_strip(frames, work / "preview" / "transition.png")
    print(f"\n  the transition: {strip}")
    return 0


def cmd_render(args) -> int:
    """Resume at the render gate: the plan you kept, the renders you already have.

    This used to draw fresh and print paths -- a paid call with no gate, and no way to get
    back to a render you had already made without walking `build` from the plan step. Now it
    opens the render gate on whatever is in the work dir, so `a <what to add>` is one command
    away from an interior you finished yesterday. `--redraw` still draws fresh first.
    """
    plan = _load_plan(args.building, args)
    work = _work(args.building)
    return 0 if _render_then_accept(plan, work, args) is True else 2


def cmd_accept(args) -> int:
    """A render you already have -> the shipped map, through the floor gate.

    Also how a building is re-emitted after the emitter changes: the floor painting is
    reused from disk when it was traced from this same render, so it costs nothing.
    """
    plan = _load_plan(args.building, args)
    work = _work(args.building)
    composited = Path(args.image) if args.image else work / "render_composited.png"
    if not composited.exists():
        raise SystemExit(f"no render at {composited}; pass --image")
    return 0 if _accept_and_write(plan, composited, work, args) is True else 2


def _accepted_buildings(map_path=None) -> list:
    """Every building with a spec and an accepted interior, by name; on `map_path` if given."""
    names = []
    for path in sorted(Path(WORK_ROOT).glob("*/interior.json")):
        try:
            spec = spec_mod.InteriorSpec.load(path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not Path(spec.interior_image).exists():
            continue
        if map_path and Path(spec.map_path).resolve() != Path(map_path).resolve():
            continue
        names.append(spec.building)
    return names


def cmd_furnish(args) -> int:
    """Furnish an accepted interior, gate by gate -- or, with --all, every one in turn."""
    if not getattr(args, "all", False):
        return 0 if _furnish(_load_spec(args.building, args), args) else 2
    names = _accepted_buildings(args.map)
    if not names:
        raise SystemExit("no building has an accepted interior" +
                         (f" on {args.map}" if args.map else "") + ": run `build` first")
    print(f"furnishing {len(names)} building(s), one at a time: {', '.join(names)}")
    redraw = args.redraw
    for number, name in enumerate(names, start=1):
        print(f"\n[{number}/{len(names)}] {name}")
        args.redraw = redraw
        if not _furnish(_load_spec(name, args), args):
            print(f"\n  stopped at {name}; {len(names) - number} building(s) not furnished")
            return 2
    return 0


def cmd_decorate(args) -> int:
    """Furnishing step 1 on its own: the decorate gate, on whatever variants are on disk."""
    spec = _load_spec(args.building, args)
    _require_accepted(spec)
    work = _work(spec.building)
    return 0 if _decorate_gate(_room_plan(spec, work, args), spec, work, args) is not None else 2


def _usable_variants(spec, work: Path, args) -> list:
    """The variants step 1 would go on with, read off disk: drawn, kept and current."""
    from . import decorate as decor_mod

    _base, sha1 = decor_mod.write_base(spec, work)
    usable = [v for v in decor_mod.variants(work, sha1, bool(getattr(args, "dry_run", False)))
              if v.usable]
    if not usable:
        raise SystemExit(f"no decorated variant of {spec.building} is drawn, kept and current: "
                         f"run `decorate` first")
    return usable


def _usable_sheets(spec, work: Path, args) -> list:
    """The variants step 2 would go on with, read off disk: a current sheet."""
    from . import kit as kit_mod

    dry_run = bool(getattr(args, "dry_run", False))
    states = [kit_mod.sheet_state(v, dry_run) for v in _usable_variants(spec, work, args)]
    usable = [s for s in states if s.usable]
    if not usable:
        raise SystemExit(f"no variant of {spec.building} has a current sheet: run "
                         f"`sheet` first")
    return usable


def _step_command(args):
    """(spec, work) for a single-step furnishing command, with the run set up."""
    spec = _load_spec(args.building, args)
    _require_accepted(spec)
    _furnishing_run(args)
    return spec, _work(spec.building)


def cmd_sheet(args) -> int:
    """Furnishing step 2 on its own: the sheet gate, for the variants step 1 kept."""
    spec, work = _step_command(args)
    found = _sheet_gate(_room_plan(spec, work, args), spec, work, args,
                        _usable_variants(spec, work, args))
    return 0 if found not in (None, "back") else 2


def cmd_extract(args) -> int:
    """Furnishing step 3 on its own: cut the current sheets into the prop set, review them."""
    spec, work = _step_command(args)
    found = _extract_gate(spec, work, args, _usable_sheets(spec, work, args))
    return 0 if found not in (None, "back") else 2


def cmd_locate(args) -> int:
    """Furnishing step 4 on its own: put each variant's props back in its room."""
    from . import extract as extract_mod

    spec, work = _step_command(args)
    sheets = _usable_sheets(spec, work, args)
    uncut = [s.tag for s in sheets if not extract_mod.is_current(s)]
    if uncut:
        print(f"  {', '.join(uncut)}: sheet not cut since it was drawn -- run `extract` first; "
              f"skipped")
        sheets = [s for s in sheets if s.tag not in uncut]
        if not sheets:
            return 2
    found = _locate_gate(_room_plan(spec, work, args), spec, work, args, sheets)
    return 0 if found not in (None, "back") else 2


def cmd_place(args) -> int:
    """Furnishing step 5 on its own: write what step 4 placed into the map."""
    from . import locate as locate_mod

    spec, work = _step_command(args)
    located = [(s, locate_mod.read_placements(s.variant)) for s in _usable_sheets(spec, work, args)]
    located = [(s, record) for s, record in located if record.get("placements")]
    if not located:
        raise SystemExit(f"nothing of {spec.building} is located: run `locate` first")
    return 0 if _place_gate(spec, work, args, located) is True else 2


COMMANDS = {
    "list": cmd_list, "new": cmd_new, "build": cmd_build, "plan": cmd_plan,
    "emit": cmd_emit, "preview": cmd_preview, "render": cmd_render, "accept": cmd_accept,
    "furnish": cmd_furnish, "decorate": cmd_decorate, "sheet": cmd_sheet,
    "extract": cmd_extract, "locate": cmd_locate, "place": cmd_place,
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
    parser.add_argument("--corridor", type=float, nargs=2, metavar=("MIN", "MAX"),
                        help="how many players wide a corridor is (default 1.5 2.5); saved "
                             "to the spec, same as [w] at the plan gate")
    parser.add_argument("--rooms-across", type=float, nargs=2, metavar=("MIN", "MAX"),
                        dest="rooms_across",
                        help="how many players across a room is (default 4 8); saved to the "
                             "spec, same as [z] at the plan gate")
    parser.add_argument("--config", type=Path, help="image backend config json")
    parser.add_argument("--draws", type=int, default=1, metavar="N",
                        help="draw N times and rank them; each draw is one API call")
    parser.add_argument("--image", type=Path, help="accept: which render to write")
    parser.add_argument("--level-image", type=Path, dest="level_image",
                        help="new --identify sam3: the level's background art, the image "
                             "the buildings are found in")
    parser.add_argument("--downscale", type=int, default=None, metavar="N",
                        help="new --identify sam3: shrink the map by 1/N for the LOCATE pass "
                             "only. Defaults to the smallest factor that lets the file open. "
                             "It is not a quality setting -- SAM resizes whatever it is given "
                             "to 560px, so locate sees the same thing at any factor. Each "
                             "building you pick is then re-segmented at full resolution")
    parser.add_argument("--min-area", type=float, default=0.05, dest="min_area",
                        metavar="PCT",
                        help="new --identify sam3: smallest share of the level, in percent, a "
                             "match can be and still count as a building (default 0.05). Set "
                             "low on purpose -- a first pass that hides a real building is "
                             "worse than one showing junk you can see and tighten against. On "
                             "sunspine the four pyramids are 0.19%%, 0.21%%, 0.31%% and 2.01%%")
    parser.add_argument("--max-area", type=float, default=5.0, dest="max_area", metavar="PCT",
                        help="new --identify sam3: largest share of the level a match can be "
                             "(default 5). SAM returned the whole landmass as a pyramid "
                             "covering 48.7%% of the map; nothing that big is a building")
    parser.add_argument("--min-confidence", type=float, default=0.15, dest="min_confidence",
                        metavar="S",
                        help="new --identify sam3: drop matches scoring below this (default "
                             "0.2). SAM3's own threshold is 0.0, so it returns everything. On "
                             "the first sunspine pass 538 of 685 polygons scored under 0.2 "
                             "and the great_pyramid scored 0.965, with nothing at all between "
                             "0.25 and 0.85")
    parser.add_argument("--entrance-min-area", type=float, default=0.1, metavar="PCT",
                        dest="entrance_min_area",
                        help="new --identify sam3: smallest share an entrance can be, in "
                             "percent (default 0.1). Measured against the BUILDING'S CROP, "
                             "not the level -- a doorway is a small part of a pyramid where a "
                             "pyramid is a large part of a map, so the two floors cannot be "
                             "the same number")
    parser.add_argument("--entrance-max-area", type=float, default=10.0, metavar="PCT",
                        dest="entrance_max_area",
                        help="new --identify sam3: largest share of the building's crop an "
                             "entrance can be (default 10). Asked for a 'pyramid entrance' "
                             "inside a pyramid, SAM's best match in every crop was the whole "
                             "pyramid at 43-47%% -- whose centroid is a door in the middle of "
                             "the room. This is what stops that")
    parser.add_argument("--entrance-min-confidence", type=float, default=0.2, metavar="S",
                        dest="entrance_min_confidence",
                        help="new --identify sam3: score floor for entrances (default 0.2)")
    parser.add_argument("--redraw", action="store_true",
                        help="build: draw new plans and renders instead of reusing the ones "
                             "already in the work directory. Reuse is what makes stepping "
                             "back from the preview free, so it is the default")
    parser.add_argument("--preview", action="store_true",
                        help="build: boot a real Level4 and walk the doorway, saving a "
                             "filmstrip. Off by default -- emit still writes the scratch "
                             "level, so checking it in the game yourself needs no flag")
    parser.add_argument("--level", action="store_true",
                        help="preview: walk the real level, with what accept wrote into it, "
                             "instead of the scratch copy")
    parser.add_argument("--rescan", action="store_true",
                        help="new --identify sam3: re-run every SAM pass even when the last "
                             "answer for the same crop and prompts is on disk. Without it a "
                             "re-run skips straight to the review loops, which is the point: "
                             "a pass is the only slow thing here, and the same request cannot "
                             "have a different answer")
    parser.add_argument("--refine-tiles", action="store_true", dest="refine_tiles",
                        help="new --identify sam3: tile the refine passes for 1:1 pixels "
                             "instead of sending each crop whole. Costs ~63 tiles per prompt "
                             "per building to recover about 6px of edge accuracy, so it is "
                             "off. Reach for it only if a doorway looks wrong in `preview`")
    parser.add_argument("--identify", default="tmx", choices=("tmx", "sam3"),
                        help="new: where the silhouette and entrance come from. tmx reads "
                             "the polygon authored in Tiled (offline default); sam3 finds "
                             "every building in --level-image from the two prompts")
    parser.add_argument("--synthetic", action="store_true",
                        help="plan: build a procedural crypt from the door plane instead of "
                             "painting one. No API key, no spend -- runs the emitter, the "
                             "checks and the preview end to end at the real scale")
    parser.add_argument("--dry-run", action="store_true",
                        help="force the copy backend: every trace, check and gate runs for "
                             "real on the exterior's own pixels, no spend")
    parser.add_argument("--variants", type=int, default=4, metavar="N",
                        help="furnish/decorate: how many lines a new decor/styles.txt starts "
                             "with, one variant each (default 4). Once the file exists its "
                             "lines are the variants -- edit it to change them")
    parser.add_argument("--all", action="store_true",
                        help="furnish: every building with an accepted interior (on --map, "
                             "if given), one at a time through the same gates. [q] at any "
                             "gate stops the run")
    args = parser.parse_args(argv)
    for flag in ("corridor", "rooms_across"):
        value = getattr(args, flag)
        if value is not None and not 0 < value[0] <= value[1]:
            parser.error(f"--{flag.replace('_', '-')} MIN MAX: 0 < MIN <= MAX")

    if args.command == "new" and args.identify == "sam3":
        if not args.level_image:
            parser.error("new --identify sam3 needs --level-image (nothing is read from the "
                         "map to find the buildings)")
    elif args.command in {"list", "new"} and not args.map:
        parser.error(f"{args.command} needs --map")
    if (args.command not in {"list", "new"} and not args.building
            and not (args.command == "furnish" and args.all)):
        parser.error(f"{args.command} needs --building"
                     + (" (or --all)" if args.command == "furnish" else ""))
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
