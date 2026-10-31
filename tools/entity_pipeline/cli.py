"""Entity generation pipeline.

    python -m tools.entity_pipeline.cli run --session necron --image path/to/map.png
    python -m tools.entity_pipeline.cli cut --session necron --sheet path/to/sheet.png
    python -m tools.entity_pipeline.cli anim --session necron --name beastman_warrior --sprite cells/beastman_warrior.png --seconds 4
    python -m tools.entity_pipeline.cli frames --session necron --name beastman_warrior
    python -m tools.entity_pipeline.cli wire --session necron --name beastman_warrior --map levels/.../map.tmx --template tribey_spear

Each paid step (scene, sheet, each anim clip) prints the prompt and images it sent, opens the
result, and asks before going on. --yes keeps every result without asking.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.entity_pipeline.figures import cut_sheet  # noqa: E402
from tools.entity_pipeline.frames import ACTIONS, fit_actions, load_action, pack_monster  # noqa: E402
from tools.entity_pipeline.session import load_session, record_call, save_session, session_dir  # noqa: E402
from tools.entity_pipeline.wire import (  # noqa: E402
    DEFAULT_X,
    DEFAULT_Y,
    add_placed_entity,
    format_entry,
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
    "idle": "Standing idle, a short breathing loop",
    "move": "Walking in place, a walk cycle",
    "attack": "One melee attack",
}
ANIM_PROMPT = (
    "2D sprite animation of this exact warrior, facing right, on a solid black background. "
    "{action}. Same character, same scale, feet on the ground. "
    "No scenery, no text, no other characters."
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


def _sprite_path(args: argparse.Namespace) -> Path:
    if args.sprite:
        return Path(args.sprite)
    return session_dir(args.session) / "cells" / f"{args.name}.png"


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
                f"{settings['model']}  cost_usd={result.get('cost_usd')}"
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
    fitted = fit_actions(loaded)
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

    frames = sub.add_parser("frames", help="black sheets -> monster folders")
    _add_common(frames)
    frames.add_argument("--name", required=True)
    frames.add_argument("--idle", default=None)
    frames.add_argument("--move", default=None)
    frames.add_argument("--attack", default=None)
    frames.set_defaults(func=cmd_frames)

    wire = sub.add_parser("wire", help="print monster_data and add one map object")
    _add_common(wire)
    wire.add_argument("--name", required=True)
    wire.add_argument("--map", required=True)
    wire.add_argument("--template", default="tribey_spear")
    wire.add_argument("--x", type=float, default=None)
    wire.add_argument("--y", type=float, default=None)
    wire.set_defaults(func=cmd_wire)

    run = sub.add_parser("run", help="scene, sheet, cut, then stop")
    _add_common(run)
    run.add_argument("--image", required=True)
    run.set_defaults(func=cmd_run, sheet=None)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
