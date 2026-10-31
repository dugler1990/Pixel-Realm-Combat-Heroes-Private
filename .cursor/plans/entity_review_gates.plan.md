---
name: entity review gates
overview: "Every paid entity step (scene, sheet, each anim clip) prints the prompt and images it sent, opens the result, and asks keep / redraw / stop before the next paid call. The printer lives in one stdlib-only module that the interior walkthrough also uses."
todos:
  - id: shared-module
    content: "Step 1-4: create tools/painted_map_pipeline/review_gate.py and point interiors/cli.py, interiors/prompt.py and world_levels/retry.py at it."
    status: pending
  - id: entity-gates
    content: "Step 5-15: gate scene, sheet and each anim clip; wire asks before writing the map; cut and frames open their contact sheet without a menu; add --yes; stop run crashing at cut."
    status: pending
  - id: tests
    content: "Step 16-17: add tests/test_entity_gates.py and run the three checks."
    status: pending
isProject: false
---

# Entity review gates

## Read this first

- Do the steps in order. Each step names the file and the function to change.
- Find functions **by name** (`def cmd_scene(`), not by line number. Other sessions edit this checkout, so line numbers move. Re-read a file right before you edit it.
- Code in this plan is complete. Copy it as written. Do not rename anything, do not "improve" it, do not add features.
- When a step says "verbatim", copy the existing text exactly, docstring included.

## What the person sees when this is done

```
scene: generated/entity_pipeline/necron/scene.png  cost_usd=0.04

  ---- prompt sent ----
  | A battle scene in this place, ...
  ---- images sent ----
  | map        levels/.../map.png
  ---------------------
  result: generated/entity_pipeline/necron/scene.png

  [enter] keep   [r] redraw (one paid call)   [r <why> @img] redraw with criticism
  [s] show again   [q] stop
>
```

- `enter` keeps the result and goes on.
- `r` redraws with the original prompt. One paid call. The old file moves to `old/<date_time>/`.
- `r too dark` redraws with "too dark" added to the end of the original prompt.
- `r too dark @C:\path\ref.png` also sends `ref.png` as a second image. Scene and sheet only. Anim refuses `@` because a clip takes one start image.
- `s` prints the block again and opens the file again.
- `q` stops. The command exits with code 1 and nothing after it runs.
- `--yes` prints the block, opens nothing, asks nothing, and keeps the result.
- End of input (no console) counts as `enter`. Keeping never spends money, so that is safe.

`cut` and `frames` make no paid call and are the last step of their command. They print the contact sheet path and open it. **They get no menu**: by the time the menu would appear, `frames` has already written `Graphics/Monsters/<name>/`, so `[q]` would stop nothing.

`wire` prints the `monster_data` entry, then asks before it adds the map object: `enter` writes it, `q` leaves the map alone.

## Do not

1. Do not import anything from `tools.painted_map_pipeline.interiors` or `tools.painted_map_pipeline.world_levels` inside `tools/entity_pipeline/`. Those packages load cv2 (`interiors/trace.py`, `world_levels/geometry.py`) and the interior walkthrough. The entity pipeline imports only `tools.painted_map_pipeline.review_gate`.
2. Do not put any import in `review_gate.py` except `__future__`, `os` and `pathlib`.
3. Do not rename the `_ask`, `_show`, `_prompt_sent`, `_sent` call sites in `interiors/cli.py`. The alias import in step 2 keeps those names. Do not write `review_gate.show(...)` there: tests patch `cli_mod._show` and `cli_mod._ask`, and that only works while the names live in the `interiors.cli` module.
4. Do not change any interior menu, prompt wording, or the interior `_set_aside`.
5. Do not add a menu to `cut` or `frames`.
6. Do not let `@img` through on anim.
7. Do not change `cmd_run`, `SCENE_PROMPT`, `SHEET_PROMPT`, `ANIM_PROMPT`, `ANIM_ACTIONS`, `Code/Settings.py`, or `.cursor/plans/entity_pipeline_2d.plan.md`.

---

## Part 1: the shared module

### Step 1. Create `tools/painted_map_pipeline/review_gate.py`

New file. Exactly this:

```python
"""The screen a paid generation step shows before you pay for the next one.

The interior walkthrough and the entity pipeline both print from here, so the two pipelines
show the same thing. Standard library only: the entity pipeline imports this module, and it
must not load cv2 or the interior walkthrough.
"""
from __future__ import annotations

import os
from pathlib import Path


def ask(question, default=""):
    """Ask on the console. End of input counts as pressing enter."""
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}\n> ").strip()
    except EOFError:
        answer = ""
    return answer or default


def show(path) -> None:
    """Open the file in its default viewer. Off Windows, the printed path is enough."""
    try:
        os.startfile(str(Path(path).resolve()))       # noqa: S606  (Windows)
    except (AttributeError, OSError):
        pass


def prompt_sent(work, name: str, rebuild) -> str:
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


def sent(prompt: str, images) -> None:
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


def with_criticism(prompt: str, criticism: str = "", attach=(), first_index: int = 2) -> str:
    """The prompt, plus what was wrong with the last try and what the extra images are.

    Same construction as ``world_levels.job_builder._with_retry_context``: everything the
    first attempt was given is kept and the criticism goes on the end, because a retry that
    drops the original instructions trades one failure for another.

    `first_index` is what the first attachment is called, and it is not always 2. The plan
    pass sends one image, so an attachment is image 2; the render pass already sends the
    control plan as image 2 and says so in its own prompt, so an attachment there is image 3.
    Numbering them from 2 regardless would have the prompt call two different pictures "image
    2", which is worse than not numbering them at all.

    Non-ASCII is stripped rather than rejected: a smart quote pasted into the review prompt
    would otherwise fail the whole call in `openai_api.edit_image`, after the draw was paid
    for and while the person is looking at a menu.
    """
    criticism = (criticism or "").strip()
    if not criticism and not attach:
        return prompt
    lines = [prompt.rstrip(), ""]
    for position, path in enumerate(attach, start=first_index):
        lines.append(f"IMAGE {position} IS {Path(path).name}.")
    if criticism:
        lines.append(criticism)
    text = "\n".join(lines).rstrip() + "\n"
    return text.encode("ascii", "ignore").decode("ascii")


def split_retry(line: str) -> tuple[str, Path | None, str]:
    """Split `r <why> @<image> <note about it>` into (reason, image, note).

    The path is the one token straight after the `@`; everything after that token is the note
    describing it, with or without an `@@` in front. Taking the whole remainder as the filename
    is how a sentence ends up being stat()ed.
    """
    body = line[1:]
    body, _, tail = body.partition("@@")
    reason, _, token = body.partition("@")
    parts = token.split(None, 1)
    token = parts[0] if parts else ""
    note = " ".join(part.strip() for part in (parts[1] if len(parts) > 1 else "", tail)
                    if part.strip())
    if not token:
        # A note with nothing to attach it to is still criticism; keep it as the reason rather
        # than dropping it silently.
        return " ".join(part for part in (reason.strip(), note) if part), None, ""

    path = Path(token).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"no such image: {path}")
    # A stray non-ASCII character from a paste would make ascii_prompt reject the whole job.
    return reason.strip(), path, note.encode("ascii", "ignore").decode("ascii")
```

### Step 2. `tools/painted_map_pipeline/interiors/cli.py`

1. Delete these four whole functions: `def _ask(`, `def _show(`, `def _prompt_sent(`, `def _sent(`. Delete the body and docstring of each. Do not delete `_mask_sent` or anything else.
2. Directly below the line `from ..building_interiors import BuildingInteriorError, load_building`, add:

   ```python
   from ..review_gate import ask as _ask, prompt_sent as _prompt_sent, sent as _sent, show as _show
   ```

3. Search the file for `os.`. The only use was inside `_show`. If there are no matches left, delete the line `import os`. If any match remains, keep `import os`.

Every existing call (`_show(sheet)`, `_sent(_prompt_sent(...), [...])`, `_ask(...)`) stays exactly as it is.

### Step 3. `tools/painted_map_pipeline/interiors/prompt.py`

1. Delete the whole function `def with_criticism(`.
2. Directly below the line `from .trace import CLASS_NAMES, FLOOR_RGB, SOLID_RGB`, add:

   ```python
   from ..review_gate import with_criticism  # noqa: F401  (kit, plan and render import it from here)
   ```

`kit.py`, `plan.py` and `render.py` keep `from .prompt import ... with_criticism` unchanged.

### Step 4. `tools/painted_map_pipeline/world_levels/retry.py`

1. Delete the whole function `def split_retry(`. Keep `def shape_retry(` and keep `from pathlib import Path` (shape_retry uses it).
2. Directly below `from pathlib import Path`, add:

   ```python
   from ..review_gate import split_retry  # noqa: F401  (review_run and interiors/cli import it from here)
   ```

---

## Part 2: the entity pipeline

All of Part 2 is in `tools/entity_pipeline/cli.py`.

### Step 5. Module docstring

At the end of the module docstring (after the `wire` example line, before the closing `"""`), add a blank line and:

```
Each paid step (scene, sheet, each anim clip) prints the prompt and images it sent, opens the
result, and asks before going on. --yes keeps every result without asking.
```

### Step 6. Imports

1. Add `import shutil` after `import json`.
2. Add `from datetime import datetime` after `import sys`.
3. After the `from tools.entity_pipeline.wire import ( ... )` block, add:

   ```python
   from tools.painted_map_pipeline.review_gate import (  # noqa: E402
       ask,
       prompt_sent,
       sent,
       show,
       split_retry,
       with_criticism,
   )
   ```

### Step 7. Menu text

Directly below the `ANIM_PROMPT = (...)` constant, add:

```python
MENU = (
    "\n  [enter] keep   [r] redraw (one paid call)   [r <why> @img] redraw with criticism"
    "\n  [s] show again   [q] stop"
)
CLIP_MENU = (
    "\n  [enter] keep   [r] redraw (one paid call)   [r <why>] redraw with criticism"
    "\n  [s] show again   [q] stop   (a clip takes one start image, so no @img here)"
)
```

### Step 8. Replace `_generate`

Replace the whole function `def _generate(` with:

```python
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
```

### Step 9. Replace `_paid` with the gate helpers

Delete the whole function `def _paid(`. In its place, add these five functions, in this order:

```python
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
```

Notes for this step:
- A plain `r` sends `base_prompt` unchanged. Criticism from an earlier `r <why>` is not carried over to the next draw. This matches the interior gates.
- If a redraw's API call fails, `_paid_call` exits. The previous draw is already safe in `old/`.

### Step 10. Replace `cmd_scene` and `cmd_sheet`

Replace the whole function `def cmd_scene(` with:

```python
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
```

Replace the whole function `def cmd_sheet(` with:

```python
def cmd_sheet(args: argparse.Namespace) -> int:
    work = session_dir(args.session)
    source = work / "scene.png"
    if not source.exists():
        print(f"no battle picture at {source}; run scene first", file=sys.stderr)
        return 1
    kept = _gate(args, "sheet", work / "sheet.png", SHEET_PROMPT, source, "scene",
                 _image_draw(args, "sheet"))
    return 0 if kept else 1
```

### Step 11. `cmd_cut`: open the contact sheet

In `def cmd_cut(`, replace the last line `return 0` with:

```python
    contact = work / "contact.png"
    print(f"  contact: {contact}")
    if not args.yes and contact.exists():
        show(contact)
    return 0
```

No menu.

### Step 12. Replace `cmd_anim`

Replace the whole function `def cmd_anim(` with:

```python
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
```

Keep `video_draw(action)` as a function that returns `draw`. Do not replace it with a lambda inside the loop: a lambda would see the last `action` of the loop, not the current one.

### Step 13. `cmd_frames`: open the contact sheet

In `def cmd_frames(`, replace the last line `return 0` with:

```python
    contact = monster / "_contact.png"
    print(f"  contact: {contact}")
    if not args.yes and contact.exists():
        show(contact)
    return 0
```

No menu.

### Step 14. Replace `cmd_wire`, and add `--yes`

Replace the whole function `def cmd_wire(` with:

```python
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
```

In `def _add_common(`, add this as the last line:

```python
    parser.add_argument("--yes", action="store_true",
                        help="show each prompt and keep each result without asking")
```

Every subcommand calls `_add_common`, so every command now has `args.yes`.

### Step 15. Stop `run` crashing at cut

In `def main(`, find this line in the `run` parser:

```python
    run.set_defaults(func=cmd_run)
```

Replace it with:

```python
    run.set_defaults(func=cmd_run, sheet=None)
```

Why: `cmd_run` passes its own arguments to `cmd_cut`, and `cmd_cut` reads `args.sheet`. Only the `cut` parser defines `--sheet`, so today `run` crashes at cut with `AttributeError: 'Namespace' object has no attribute 'sheet'`. With `sheet=None`, cut uses the session's `sheet.png`, which is the sheet `run` just drew and you just kept.

Use `set_defaults`, not `run.add_argument("--sheet", ...)`. A `--sheet` flag on `run` would let cut work on a different sheet from the one you accepted at the sheet gate. Change only this line. `cmd_run` and `cmd_cut` stay as they are.

---

## Part 3: tests and checks

### Step 16. Create `tests/test_entity_gates.py`

New file. Exactly this:

```python
"""The entity pipeline's review gates, with every paid call faked."""
from __future__ import annotations

import pytest
from PIL import Image

from tools.entity_pipeline import cli as cli_mod
from tools.entity_pipeline import session as session_mod
from tools.painted_map_pipeline import leonardo_api

TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" nextobjectid="10">
 <objectgroup id="1" name="placed_entities">
  <object id="3" name="flyer_mid" x="10" y="20">
   <properties>
    <property name="entity_spawn_config" value="{&quot;kind&quot;:&quot;enemy&quot;,&quot;type&quot;:&quot;flyer&quot;}"/>
   </properties>
  </object>
 </objectgroup>
</map>
"""


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Fake both paid calls, keep sessions in tmp_path, and never open a viewer."""
    monkeypatch.setattr(session_mod, "WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(cli_mod, "show", lambda path: None)
    calls = []

    def fake_generate(prompt, sources, dest, config_path):
        calls.append({"prompt": prompt, "sources": list(sources)})
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8)).save(dest)
        return {"cost_usd": 0.0, "output_path": str(dest)}

    def fake_video(**kwargs):
        calls.append({"prompt": kwargs["prompt"], "sources": [kwargs["input_image"]]})
        kwargs["output_path"].write_bytes(b"clip")
        return {"cost_usd": 0.0, "output_path": str(kwargs["output_path"])}

    monkeypatch.setattr(cli_mod, "_generate", fake_generate)
    monkeypatch.setattr(leonardo_api, "generate_image_to_video", fake_video)
    image = tmp_path / "map.png"
    Image.new("RGB", (8, 8)).save(image)
    ref = tmp_path / "ref.png"
    Image.new("RGB", (8, 8)).save(ref)
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    return {
        "calls": calls,
        "image": image,
        "ref": ref,
        "common": ["--session", "s", "--config", str(config)],
        "work": tmp_path / "work" / "s",
        "tmp": tmp_path,
    }


def _answers(monkeypatch, *replies):
    queue = iter(replies)
    monkeypatch.setattr(cli_mod, "ask", lambda question, default="": next(queue))


def _never_ask(monkeypatch):
    def fail(question, default=""):
        raise AssertionError(f"asked: {question}")

    monkeypatch.setattr(cli_mod, "ask", fail)


def _scene(run, *extra):
    return cli_mod.main(["scene", *run["common"], "--image", str(run["image"]), *extra])


def _anim(run, *extra):
    return cli_mod.main(["anim", *run["common"], "--name", "w", "--sprite", str(run["image"]), *extra])


def test_scene_enter_keeps_the_first_draw(run, monkeypatch):
    _answers(monkeypatch, "")
    assert _scene(run) == 0
    assert len(run["calls"]) == 1
    assert run["calls"][0]["sources"] == [run["image"]]
    assert (run["work"] / "scene_prompt.txt").read_text(encoding="utf-8") == cli_mod.SCENE_PROMPT


def test_scene_redraw_with_criticism_moves_the_first_draw_aside(run, monkeypatch):
    _answers(monkeypatch, "r too dark", "")
    assert _scene(run) == 0
    assert len(run["calls"]) == 2
    second = run["calls"][1]["prompt"]
    assert second.startswith(cli_mod.SCENE_PROMPT)
    assert second.rstrip().endswith("too dark")
    assert (run["work"] / "scene_prompt.txt").read_text(encoding="utf-8") == second
    assert len(list((run["work"] / "old").glob("*/scene.png"))) == 1
    assert len(list((run["work"] / "old").glob("*/scene_prompt.txt"))) == 1


def test_scene_redraw_can_attach_an_image(run, monkeypatch):
    _answers(monkeypatch, f"r wrong colours @{run['ref']}", "")
    assert _scene(run) == 0
    assert run["calls"][1]["sources"] == [run["image"], run["ref"]]
    assert "IMAGE 2 IS ref.png." in run["calls"][1]["prompt"]


def test_scene_q_stops_with_exit_code_1(run, monkeypatch):
    _answers(monkeypatch, "q")
    assert _scene(run) == 1
    assert len(run["calls"]) == 1


def test_yes_draws_once_and_never_asks(run, monkeypatch):
    _never_ask(monkeypatch)
    assert _scene(run, "--yes") == 0
    assert len(run["calls"]) == 1


def test_anim_refuses_an_attached_image_and_q_stops_before_move(run, monkeypatch):
    _answers(monkeypatch, f"r slower @{run['ref']}", "q")
    assert _anim(run) == 1
    assert len(run["calls"]) == 1
    assert not (run["work"] / "anim" / "w" / "move.mp4").exists()


def test_anim_asks_once_per_clip(run, monkeypatch):
    _answers(monkeypatch, "", "", "")
    assert _anim(run) == 0
    assert len(run["calls"]) == 3
    for action in ("idle", "move", "attack"):
        assert (run["work"] / "anim" / "w" / f"{action}_prompt.txt").exists()


def test_cut_never_asks(run, monkeypatch):
    _never_ask(monkeypatch)
    monkeypatch.setattr(cli_mod, "cut_sheet", lambda image, out_dir: [])
    assert cli_mod.main(["cut", *run["common"], "--sheet", str(run["image"])]) == 0


def test_run_command_gets_through_cut(run, monkeypatch):
    _answers(monkeypatch, "", "")
    monkeypatch.setattr(cli_mod, "cut_sheet", lambda image, out_dir: [])
    assert cli_mod.main(["run", *run["common"], "--image", str(run["image"])]) == 0
    assert len(run["calls"]) == 2


def test_wire_q_leaves_the_map_alone(run, monkeypatch):
    tmx = run["tmp"] / "map.tmx"
    tmx.write_text(TMX, encoding="utf-8")
    _answers(monkeypatch, "q")
    assert cli_mod.main(["wire", *run["common"], "--name", "w", "--map", str(tmx)]) == 0
    assert tmx.read_text(encoding="utf-8") == TMX


def test_wire_yes_writes_the_map(run, monkeypatch):
    tmx = run["tmp"] / "map.tmx"
    tmx.write_text(TMX, encoding="utf-8")
    _never_ask(monkeypatch)
    assert cli_mod.main(["wire", *run["common"], "--name", "w", "--map", str(tmx), "--yes"]) == 0
    assert 'name="w"' in tmx.read_text(encoding="utf-8")
```

### Step 17. Run the checks

From the repo root, in PowerShell, as three separate commands. Do not combine them into one pytest call.

```
python -m pytest tests/test_entity_pipeline.py tests/test_entity_gates.py -q
```

Expect everything to pass. (The Necron cut test may show as skipped; that is normal.)

```
python -m pytest tests/painted_map_pipeline -q
```

This takes about 3 minutes. Expect the same result as before your change. If an interior test fails, the most likely cause is step 2: check that the alias import is there and that no call site was renamed.

```
python -c "import sys; import tools.entity_pipeline.cli; print('cv2 loaded:', 'cv2' in sys.modules)"
```

Expect `cv2 loaded: False`. If it prints `True`, something in `tools/entity_pipeline/` imports from `interiors` or `world_levels`. Remove that import and use `review_gate` instead.

## Done when

- The three checks above pass.
- You edited only these files: `tools/painted_map_pipeline/review_gate.py` (new), `tools/painted_map_pipeline/interiors/cli.py`, `tools/painted_map_pipeline/interiors/prompt.py`, `tools/painted_map_pipeline/world_levels/retry.py`, `tools/entity_pipeline/cli.py`, `tests/test_entity_gates.py` (new). Do not use `git diff` to check this: the working tree already has other people's uncommitted changes in many files, and `tools/entity_pipeline/` is not tracked yet.
