"""Entity generation pipeline.

    python -m tools.entity_pipeline.cli run --session necron --image path/to/map.png
    python -m tools.entity_pipeline.cli cut --session necron --sheet path/to/sheet.png
    python -m tools.entity_pipeline.cli stats --session necron
    python -m tools.entity_pipeline.cli anim --session necron --name beastman_warrior --sprite cells/beastman_warrior.png --seconds 4
    python -m tools.entity_pipeline.cli all --session necron --each 1
    python -m tools.entity_pipeline.cli anim-all --session necron --seconds 4
    python -m tools.entity_pipeline.cli frames --session necron --name beastman_warrior
    python -m tools.entity_pipeline.cli wire --session necron --name beastman_warrior --map levels/.../map.tmx --template tribey_spear
    python -m tools.entity_pipeline.cli fight --session necron --map levels/.../map.tmx --each 1

Each paid step (scene, sheet, each anim clip) prints the prompt and images it sent, opens the
result, and asks before going on. --yes keeps every result without asking.
all animates every cut sprite without asking, then opens the game on the warrior_brawl
validation scenario so they fight on screen. anim-all and fight stay separate.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.entity_pipeline.figures import cut_sheet  # noqa: E402
from tools.entity_pipeline.frames import (  # noqa: E402
    ACTIONS,
    battle_scale,
    fit_actions,
    foot_and_height,
    height_times_man,
    load_action,
    pack_monster,
    sheet_man_height,
)
from tools.entity_pipeline.session import load_session, record_call, save_session, session_dir  # noqa: E402
from tools.entity_pipeline.stats import (  # noqa: E402
    DEFAULT_STATS_CONFIG,
    StatsClientError,
    adopt_names,
    ask_scores,
    build_prompt,
    load_scores,
    numbered_sheet,
    parse_scores,
    print_scores,
    save_scores,
    sheet_cells,
)
from tools.entity_pipeline.wire import (  # noqa: E402
    DEFAULT_X,
    DEFAULT_Y,
    add_placed_entity,
    fight_placements,
    roster_counts,
    format_entry,
    install_monster_entries,
    rescore_monster_entries,
    template_entry,
)
from tools.painted_map_pipeline.review_gate import (  # noqa: E402
    ask,
    prompt_sent,
    sent,
    show,
    split_retry,
    with_criticism,
)

DEFAULT_CONFIG = Path("tools/painted_map_pipeline/leonardo.sunspine.json")
SHEET_SIZE = (1024, 1024)

SCENE_PROMPT = (
    "A battle scene in this place, in the same painted style as the map. "
    "Show the ground fighters who would fight here. No text, no labels, no border."
)
SHEET_PROMPT = (
    "An idle sprite sheet of every distinct warrior in this battle. "
    "One warrior per cell, facing right, at a similar scale, with a clear gap between cells. "
    "No text labels."
)
ANIM_ACTIONS = {
    "idle": "A game idle animation. Clean and simple, don't add anything",
    "move": "Walking in place",
    "attack": "One attack",
}
ANIM_PROMPT = (
    "This exact warrior, facing right, on a solid black background. {action}."
)
MENU = (
    "\n  [enter] keep   [r] redraw (one paid call)   [r <why> @img] redraw with criticism"
    "\n  [s] show again   [q] stop"
)
CLIP_MENU = (
    "\n  [enter] keep   [r] redraw (one paid call)   [r <why>] redraw with criticism"
    "\n  [s] show again   [q] stop   (a clip takes one start image, so no @img here)"
)


def _generate(prompt: str, sources: list[Path], dest: Path, config_path: Path) -> dict:
    from PIL import Image

    from tools.painted_map_pipeline.leonardo_api import generate_with_image_reference

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["width"], config["height"] = SHEET_SIZE
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The reference upload wants a file on disk. Pass each source as it is.
    for source in sources:
        with Image.open(source):
            pass
    return generate_with_image_reference(
        prompt=prompt,
        input_images=list(sources),
        output_path=dest,
        width=SHEET_SIZE[0],
        height=SHEET_SIZE[1],
        config=config,
    )


def _paid_call(step: str, call) -> dict:
    """Make one paid call. A Leonardo or API-key failure prints and exits 1; anything else raises."""
    try:
        return call()
    except Exception as exc:
        name = type(exc).__name__
        if name in {"LeonardoApiError", "ImageClientError"} or "API key" in str(exc):
            print(f"{step} failed: {exc}", file=sys.stderr)
            raise SystemExit(1)
        raise


def _set_aside(paths: list[Path]) -> None:
    """Move whichever of `paths` exist into old/<date_time>/ beside them. A draw is paid for,
    so it is moved, not deleted."""
    found = [path for path in paths if path.is_file()]
    if not found:
        return
    stamp = found[0].parent / "old" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder, n = stamp, 1
    while folder.exists():
        folder, n = stamp.with_name(f"{stamp.name}_{n}"), n + 1
    folder.mkdir(parents=True)
    for path in found:
        shutil.move(str(path), str(folder / path.name))
    print(f"  moved the last draw to {folder}")


def _draw(dest: Path, prompt: str, images: list[tuple[str, Path]], draw) -> None:
    """Move the last draw aside, write the prompt that is about to go, then make the call."""
    prompt_file = dest.with_name(f"{dest.stem}_prompt.txt")
    _set_aside([dest, prompt_file])
    dest.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")
    draw(prompt, [path for _label, path in images], dest)


def _gate(args, step: str, dest: Path, base_prompt: str, source: Path, label: str,
          draw, attach_ok: bool = True) -> bool:
    """One paid step: draw `dest` if needed, show what went and what came back, then ask.

    True when you keep the result, False when you stop. `draw(prompt, paths, dest)` makes
    one paid call. `attach_ok` is False for a clip: Veo takes one start image, so an `@img`
    on a redraw has nowhere to go.
    """
    prompt_file = dest.with_name(f"{dest.stem}_prompt.txt")
    images = [(label, source)]
    if dest.exists() and not args.force:
        print(f"{step}: already have {dest}")
    else:
        _draw(dest, base_prompt, images, draw)
    menu = MENU if attach_ok else CLIP_MENU
    shown = False
    while True:
        if not shown:
            sent(prompt_sent(dest.parent, prompt_file.name, lambda: base_prompt), images)
            print(f"  result: {dest}")
            if args.yes:
                return True
            show(dest)
            shown = True
        raw = ask(menu).strip()
        answer = raw.lower()
        if answer == "":
            return True
        if answer == "q":
            print(f"  stopped at {step}")
            return False
        if answer == "s":
            shown = False
            continue
        if answer != "r" and not answer.startswith("r "):
            print(f"  not an option: {raw}")
            continue
        criticism, attach = "", []
        if answer.startswith("r "):
            if "@" in raw and not attach_ok:
                print("  a clip takes one start image, so @img cannot be sent. "
                      "Type r <why> without the @.")
                continue
            try:
                reason, image, note = split_retry(raw)
            except FileNotFoundError as exc:
                print(f"  {exc}")
                continue
            criticism = " ".join(part for part in (reason, note) if part)
            attach = [image] if image else []
        images = [(label, source)] + [("attached", path) for path in attach]
        _draw(dest, with_criticism(base_prompt, criticism, attach), images, draw)
        shown = False


def _image_draw(args, step: str):
    """The paid still-image call for `step`, in the shape `_gate` calls it."""
    def draw(prompt: str, paths: list[Path], dest: Path) -> None:
        result = _paid_call(step, lambda: _generate(prompt, paths, dest, Path(args.config)))
        record_call(args.session, step, result)
        print(f"{step}: {dest}  cost_usd={result.get('cost_usd')}")
    return draw


def cmd_scene(args: argparse.Namespace) -> int:
    work = session_dir(args.session)
    source = Path(args.image)
    if not source.exists():
        print(f"map image not found: {source}", file=sys.stderr)
        return 1
    kept = _gate(args, "scene", work / "scene.png", SCENE_PROMPT, source, "map",
                 _image_draw(args, "scene"))
    data = load_session(args.session)
    data["map_image"] = str(source)
    save_session(args.session, data)
    return 0 if kept else 1


def cmd_sheet(args: argparse.Namespace) -> int:
    work = session_dir(args.session)
    source = work / "scene.png"
    if not source.exists():
        print(f"no battle picture at {source}; run scene first", file=sys.stderr)
        return 1
    kept = _gate(args, "sheet", work / "sheet.png", SHEET_PROMPT, source, "scene",
                 _image_draw(args, "sheet"))
    return 0 if kept else 1


def cmd_cut(args: argparse.Namespace) -> int:
    from PIL import Image

    work = session_dir(args.session)
    sheet = Path(args.sheet) if args.sheet else work / "sheet.png"
    if not sheet.exists():
        print(f"sheet not found: {sheet}", file=sys.stderr)
        return 1
    with Image.open(sheet) as image:
        figures = cut_sheet(image, work)
    print(f"cut: {len(figures)} sprites -> {work / 'cells'}")
    for fig in figures:
        print(f"  {fig.name} {list(fig.box)}")
    contact = work / "contact.png"
    print(f"  contact: {contact}")
    if not args.yes and contact.exists():
        show(contact)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Score every cut warrior 1-10 from the sheet. One paid call. Nothing is written unless
    the reply scores every warrior."""
    work = session_dir(args.session)
    cells = sheet_cells(work)
    names = [name for name, _box in cells]
    if (work / "stats.json").exists() and not args.force:
        saved = load_scores(work)      # prints why when it is stale
        if not saved:
            return 1
        print(f"stats: already have {work / 'stats.json'} (--force asks again)")
        print_scores(saved)
        return 0
    sheet = Path(args.sheet) if args.sheet else work / "sheet.png"
    if not sheet.exists():
        print(f"sheet not found: {sheet}", file=sys.stderr)
        return 1
    config_path = Path(args.stats_config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model = args.model or config.get("model")
    if not model:
        print(f"set model in {config_path} or pass --model", file=sys.stderr)
        return 1
    numbered = numbered_sheet(sheet, cells, work / "stats_sheet.png")
    print(f"stats: sending {numbered} ({len(names)} warriors) to {model}")
    try:
        text = ask_scores(numbered, build_prompt(len(names)), config, model)
    except StatsClientError as exc:
        print(f"stats failed: {exc}", file=sys.stderr)
        return 1
    try:
        scores = parse_scores(text, names)
        cells, scores, renamed = adopt_names(work, cells, scores)
    except StatsClientError as exc:
        print(f"stats failed: {exc}\n--- reply ---\n{text}", file=sys.stderr)
        return 1
    for old, new in renamed:
        print(f"stats: {old} -> {new}")
    out = save_scores(work, model, sheet, cells, scores)
    print_scores(scores)
    print(f"stats: {out}")
    return 0


def _sprite_path(args: argparse.Namespace) -> Path:
    if args.sprite:
        return Path(args.sprite)
    return session_dir(args.session) / "cells" / f"{args.name}.png"


def _cell_names(session: str) -> list[str]:
    cells = session_dir(session) / "cells"
    if not cells.is_dir():
        return []
    return sorted(path.stem for path in cells.glob("*.png"))


def _video_settings(args: argparse.Namespace, config: dict) -> dict:
    return {
        "model": args.model or config.get("video_model") or "veo-3.1-lite",
        "seconds": int(args.seconds if args.seconds is not None else config.get("video_seconds") or 4),
        "width": int(args.width if args.width is not None else config.get("video_width") or 1280),
        "height": int(args.height if args.height is not None else config.get("video_height") or 720),
        "audio": bool(args.audio),
    }


def cmd_anim(args: argparse.Namespace) -> int:
    """One video per action. The cut sprite is the start frame. Each clip is kept or redrawn
    before the next one is paid for."""
    from tools.painted_map_pipeline.leonardo_api import generate_image_to_video

    sprite = _sprite_path(args)
    if not sprite.exists():
        print(f"sprite not found: {sprite}", file=sys.stderr)
        return 1
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    settings = _video_settings(args, config)
    out = session_dir(args.session) / "anim" / args.name
    out.mkdir(parents=True, exist_ok=True)

    def video_draw(action: str):
        step = f"anim:{action}"

        def draw(prompt: str, paths: list[Path], dest: Path) -> None:
            result = _paid_call(step, lambda: generate_image_to_video(
                prompt=prompt,
                input_image=paths[0],
                output_path=dest,
                config=config,
                model=settings["model"],
                seconds=settings["seconds"],
                width=settings["width"],
                height=settings["height"],
                audio=settings["audio"],
            ))
            record_call(args.session, f"anim:{args.name}:{action}", result)
            print(
                f"{step}: {dest}  {settings['seconds']}s  "
                f"{settings['model']}  style=Graphic Design 2D  "
                f"cost_usd={result.get('cost_usd')}"
            )
        return draw

    for action in ACTIONS:
        prompt = ANIM_PROMPT.format(action=ANIM_ACTIONS[action])
        kept = _gate(args, f"anim:{action}", out / f"{action}.mp4", prompt, sprite, "sprite",
                     video_draw(action), attach_ok=False)
        if not kept:
            return 1
    print(f"anim: {out}")
    return 0


def cmd_anim_all(args: argparse.Namespace) -> int:
    """Every cut sprite, all three actions, kept without asking. Then the frame folders."""
    names = _cell_names(args.session)
    if not names:
        print(f"no cells in {session_dir(args.session) / 'cells'}; run cut first", file=sys.stderr)
        return 1
    args.yes = True
    print(f"anim-all: {len(names)} sprites, keeping every clip")
    for name in names:
        args.name = name
        args.sprite = None
        args.idle = None
        args.move = None
        args.attack = None
        print(f"anim-all: {name}")
        if cmd_anim(args) != 0:
            return 1
        if cmd_frames(args) != 0:
            return 1
    print(f"anim-all: {len(names)} sprites")
    return 0


def _default_action_path(work: Path, action: str) -> Path:
    video = work / f"{action}.mp4"
    if video.exists():
        return video
    return work / f"{action}.png"


def cmd_frames(args: argparse.Namespace) -> int:
    work = session_dir(args.session) / "anim" / args.name
    paths = {
        "idle": Path(args.idle) if args.idle else _default_action_path(work, "idle"),
        "move": Path(args.move) if args.move else _default_action_path(work, "move"),
        "attack": Path(args.attack) if args.attack else _default_action_path(work, "attack"),
    }
    for action, path in paths.items():
        if not path.exists():
            print(f"missing {action} sheet: {path}", file=sys.stderr)
            return 1
    loaded = {action: load_action(path) for action, path in paths.items()}
    work_root = session_dir(args.session)
    cell = work_root / "cells" / f"{args.name}.png"
    target = None
    if cell.exists():
        from PIL import Image

        with Image.open(cell) as sprite:
            figure = foot_and_height(sprite.convert("RGBA"))[2]
        scale = 1.0
        man = figure
        scene_path = work_root / "scene.png"
        cell_paths = sorted((work_root / "cells").glob("*.png"))
        if scene_path.exists() and cell_paths:
            cell_images = [Image.open(path).convert("RGBA") for path in cell_paths]
            try:
                man = sheet_man_height(cell_images)
                with Image.open(scene_path) as scene:
                    scale = battle_scale(scene.convert("RGB"), cell_images, getattr(args, "band", "near"))
            except RuntimeError as exc:
                print(f"  scale: {exc}; using the cut cell")
            finally:
                for image in cell_images:
                    image.close()
        scored = load_scores(work_root).get(args.name) or {}
        times = height_times_man(scored.get("size"), figure, man)
        target = max(1, round(man * scale * times))
        print(f"  scale: {scale:.2f}, {times:.2f} men, figure {figure}px -> {target}px")
    fitted = fit_actions(loaded, target)
    monster = pack_monster(args.name, fitted)
    sizes = {action: fitted[action][0].size for action in ACTIONS}
    print(f"frames: {monster}")
    for action in ACTIONS:
        print(f"  {action}: {len(fitted[action])} frames, {sizes[action][0]}x{sizes[action][1]}")
    contact = monster / "_contact.png"
    print(f"  contact: {contact}")
    if not args.yes and contact.exists():
        show(contact)
    return 0


def cmd_wire(args: argparse.Namespace) -> int:
    entry = template_entry(args.template)
    print(format_entry(args.name, entry))
    print("Paste that into monster_data in Code/Settings.py before you launch. wire does not write Settings.py.")
    x = DEFAULT_X if args.x is None else args.x
    y = DEFAULT_Y if args.y is None else args.y
    if not args.yes:
        while True:
            answer = ask(f"\n  [enter] add {args.name} to {args.map} at ({x}, {y})"
                         f"   [q] leave the map alone").strip().lower()
            if answer == "":
                break
            if answer == "q":
                print("map: not changed")
                return 0
            print(f"  not an option: {answer}")
    object_id = add_placed_entity(Path(args.map), args.name, x=x, y=y)
    print(f"map: {args.map} object {object_id} {args.name} at ({x}, {y})")
    return 0


def cmd_fight(args: argparse.Namespace) -> int:
    """Place `each` copies of every cut warrior on two teams that already fight each other.

    monster_data entries are copied from the template when the name is missing.
    An object that is already on the map is left where it is.
    """
    if args.each < 1:
        print("--each must be at least 1", file=sys.stderr)
        return 1
    names = _cell_names(args.session)
    if not names:
        print(f"no cells in {session_dir(args.session) / 'cells'}; run cut first", file=sys.stderr)
        return 1
    for name in names:
        folder = Path("Graphics/Monsters") / name / "idle"
        if not folder.is_dir():
            print(f"fight: {name} has no frames in {folder}")
    added = install_monster_entries(names, args.template)
    if added:
        print(f"fight: added monster_data {', '.join(added)} (copied from {args.template})")
    else:
        print("fight: monster_data already has every warrior")
    x = DEFAULT_X if args.x is None else args.x
    y = DEFAULT_Y if args.y is None else args.y
    placed = 0
    for spot in fight_placements(names, args.each, x, y):
        try:
            object_id = add_placed_entity(
                Path(args.map),
                spot["name"],
                x=spot["x"],
                y=spot["y"],
                entity_type=spot["entity_type"],
                team_id=spot["team_id"],
            )
        except SystemExit as exc:
            if "already has" in str(exc):
                print(f"map: {spot['name']} already placed")
                continue
            raise
        placed += 1
        print(
            f"map: {args.map} object {object_id} {spot['name']} "
            f"type={spot['entity_type']} team={spot['team_id']} at ({spot['x']}, {spot['y']})"
        )
    print(f"fight: {placed} new objects, {args.each} of each")
    return 0


def cmd_brawl(args: argparse.Namespace) -> int:
    """Open the visible validation scenario with one line of each warrior fighting the other."""
    if args.each < 1:
        print("--each must be at least 1", file=sys.stderr)
        return 1
    names = _cell_names(args.session)
    if not names:
        print(f"no cells in {session_dir(args.session) / 'cells'}; run cut first", file=sys.stderr)
        return 1
    for name in names:
        folder = Path("Graphics/Monsters") / name / "idle"
        if not folder.is_dir():
            print(f"brawl: {name} has no frames in {folder}", file=sys.stderr)
            return 1
    added = install_monster_entries(names, args.template)
    if added:
        print(f"brawl: added monster_data {', '.join(added)} (copied from {args.template})")
    scores = load_scores(session_dir(args.session))
    if not scores:
        print("brawl: no usable stats.json, warriors keep the numbers already in monster_data")
    else:
        changed = rescore_monster_entries({n: scores[n] for n in names if n in scores}, args.template)
        if changed:
            print(f"brawl: applied stats.json to {', '.join(changed)}")
        else:
            print("brawl: stats.json already applied")
        unscored = [n for n in names if n not in scores]
        if unscored:
            print(f"brawl: no score for {', '.join(unscored)}; they keep the template numbers")
    counts = roster_counts({name: scores[name] for name in names if name in scores})
    if counts:
        print("brawl: " + ", ".join(
            f"{counts[name] * args.each} {scores[name].get('label') or name}" for name in names if name in counts
        ))
    spots = [
        {
            "type": spot["entity_type"],
            "team": spot["team_id"],
            "dx": spot["x"],
            "dy": spot["y"],
        }
        for spot in fight_placements(names, args.each, x=0, y=0, packed=True, counts=counts or None)
    ]
    roster = session_dir(args.session) / "brawl.json"
    roster.write_text(json.dumps({"each": args.each, "spots": spots}, indent=2) + "\n", encoding="utf-8")
    code_dir = _ROOT / "Code"
    env = os.environ.copy()
    env["PRCH_ENTITY_BRAWL"] = str(roster.resolve())
    hold = str(args.hold)
    level = getattr(args, "level", None) or "../levels/benchmark"
    roster_note = "by label" if counts else f"{args.each} of each"
    print(f"brawl: opening {level}, {roster_note}, on screen for {hold}s")
    proc = subprocess.run(
        [
            sys.executable,
            "rts_validation.py",
            "--scenario",
            "warrior_brawl",
            "--layout-dir",
            level,
            "--hold-seconds",
            hold,
            "--max-seconds",
            "30",
        ],
        cwd=code_dir,
        env=env,
        check=False,
    )
    return proc.returncode


def _confirm_brawl(args: argparse.Namespace) -> bool:
    """Say the frames are ready, then start or change the brawl. Enter starts."""
    menu = (
        f"\n  ready. {args.each:g} of each warrior, on screen for {args.hold:g}s."
        "\n  [enter] start the brawl"
        "\n  [each <n>] copies of each warrior"
        "\n  [hold <n>] seconds on screen"
        "\n  [q] stop"
    )
    while True:
        raw = ask(menu).strip()
        answer = raw.lower()
        if answer == "":
            return True
        if answer == "q":
            print("brawl: not started")
            return False
        kind, _, value = answer.partition(" ")
        if kind in {"each", "hold"} and value:
            try:
                number = float(value)
            except ValueError:
                print(f"  not a number: {value}")
                continue
            if kind == "each":
                if number < 1 or not number.is_integer():
                    print("  each must be a whole number, at least 1")
                    continue
                args.each = int(number)
            else:
                if number <= 0:
                    print("  hold must be more than 0")
                    continue
                args.hold = number
            print(f"  {args.each:g} of each, {args.hold:g}s")
            continue
        print(f"  not an option: {raw}")


def cmd_all(args: argparse.Namespace) -> int:
    """Animate every cut sprite, keep every clip, then ask before the brawl."""
    auto = args.yes
    if cmd_anim_all(args) != 0:
        return 1
    if not auto and not _confirm_brawl(args):
        return 0
    return cmd_brawl(args)


def cmd_run(args: argparse.Namespace) -> int:
    """scene, sheet, cut, then stop. anim, frames, and wire stay separate."""
    if cmd_scene(args) != 0:
        return 1
    if cmd_sheet(args) != 0:
        return 1
    if cmd_cut(args) != 0:
        return 1
    print("run stopped after cut. Look at the cells before anim.")
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--yes", action="store_true",
                        help="show each prompt and keep each result without asking")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.entity_pipeline.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    scene = sub.add_parser("scene", help="map image -> battle picture")
    _add_common(scene)
    scene.add_argument("--image", required=True)
    scene.set_defaults(func=cmd_scene)

    sheet = sub.add_parser("sheet", help="battle picture -> idle sheet")
    _add_common(sheet)
    sheet.set_defaults(func=cmd_sheet)

    cut = sub.add_parser("cut", help="idle sheet -> one clean sprite per warrior")
    _add_common(cut)
    cut.add_argument("--sheet", default=None)
    cut.set_defaults(func=cmd_cut)

    stats = sub.add_parser("stats", help="score each cut warrior 1-10 from the sheet (one paid call)")
    stats.add_argument("--session", required=True)
    stats.add_argument("--sheet", default=None, help="the sheet cut used. Default <session>/sheet.png")
    stats.add_argument("--stats-config", default=str(DEFAULT_STATS_CONFIG))
    stats.add_argument("--model", default=None, help="overrides model in the stats config")
    stats.add_argument("--force", action="store_true", help="ask again even if stats.json exists")
    stats.set_defaults(func=cmd_stats)

    anim = sub.add_parser("anim", help="one sprite -> a Veo 3.1 clip for idle, move, and attack")
    _add_common(anim)
    anim.add_argument("--name", required=True)
    anim.add_argument("--sprite", default=None)
    anim.add_argument("--model", default=None, help="default veo-3.1-lite")
    anim.add_argument("--seconds", type=int, default=None, help="4, 6, or 8. Default 4")
    anim.add_argument("--width", type=int, default=None)
    anim.add_argument("--height", type=int, default=None)
    anim.add_argument("--audio", action="store_true")
    anim.set_defaults(func=cmd_anim)

    anim_all = sub.add_parser("anim-all", help="every cut sprite, idle move and attack, auto-kept")
    _add_common(anim_all)
    anim_all.add_argument("--model", default=None, help="default veo-3.1-lite")
    anim_all.add_argument("--seconds", type=int, default=None, help="4, 6, or 8. Default 4")
    anim_all.add_argument("--width", type=int, default=None)
    anim_all.add_argument("--height", type=int, default=None)
    anim_all.add_argument("--audio", action="store_true")
    anim_all.add_argument("--band", choices=("near", "center"), default="near",
                          help="near is the bottom half. center is the middle 60 percent")
    anim_all.set_defaults(func=cmd_anim_all, name=None, sprite=None, idle=None, move=None, attack=None)

    frames = sub.add_parser("frames", help="black sheets -> monster folders")
    _add_common(frames)
    frames.add_argument("--name", required=True)
    frames.add_argument("--idle", default=None)
    frames.add_argument("--move", default=None)
    frames.add_argument("--attack", default=None)
    frames.add_argument("--band", choices=("near", "center"), default="near",
                        help="near is the bottom half. center is the middle 60 percent")
    frames.set_defaults(func=cmd_frames)

    wire = sub.add_parser("wire", help="print monster_data and add one map object")
    _add_common(wire)
    wire.add_argument("--name", required=True)
    wire.add_argument("--map", required=True)
    wire.add_argument("--template", default="tribey_spear")
    wire.add_argument("--x", type=float, default=None)
    wire.add_argument("--y", type=float, default=None)
    wire.set_defaults(func=cmd_wire)

    fight = sub.add_parser("fight", help="place each cut warrior on two hostile teams")
    _add_common(fight)
    fight.add_argument("--map", required=True)
    fight.add_argument("--each", type=int, default=1, help="copies of each warrior. Default 1")
    fight.add_argument("--template", default="tribey_spear")
    fight.add_argument("--x", type=float, default=None)
    fight.add_argument("--y", type=float, default=None)
    fight.set_defaults(func=cmd_fight)

    brawl = sub.add_parser("brawl", help="show the cut warriors fighting in the game")
    _add_common(brawl)
    brawl.add_argument("--each", type=int, default=1, help="multiplies the label counts. Without stats, copies of each warrior. Default 1")
    brawl.add_argument("--hold", type=float, default=60, help="seconds the fight stays on screen")
    brawl.add_argument("--template", default="tribey_spear")
    brawl.add_argument("--level", default="../levels/benchmark",
                       help="layout directory. Default is the black benchmark room")
    brawl.set_defaults(func=cmd_brawl)

    everything = sub.add_parser("all", help="animate every cut sprite, then show them fighting in the game")
    _add_common(everything)
    everything.add_argument("--each", type=int, default=1, help="copies of each warrior. Default 1")
    everything.add_argument("--hold", type=float, default=60, help="seconds the fight stays on screen")
    everything.add_argument("--template", default="tribey_spear")
    everything.add_argument("--level", default="../levels/benchmark",
                            help="layout directory. Default is the black benchmark room")
    everything.add_argument("--model", default=None, help="default veo-3.1-lite")
    everything.add_argument("--seconds", type=int, default=None, help="4, 6, or 8. Default 4")
    everything.add_argument("--width", type=int, default=None)
    everything.add_argument("--height", type=int, default=None)
    everything.add_argument("--audio", action="store_true")
    everything.add_argument("--band", choices=("near", "center"), default="near",
                            help="near is the bottom half. center is the middle 60 percent")
    everything.set_defaults(func=cmd_all, name=None, sprite=None, idle=None, move=None, attack=None)

    run = sub.add_parser("run", help="scene, sheet, cut, then stop")
    _add_common(run)
    run.add_argument("--image", required=True)
    run.set_defaults(func=cmd_run, sheet=None)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
