---
name: Entity web page
overview: "The entity pipeline (tools/entity_pipeline/cli.py) in the browser: a stdlib server on 127.0.0.1:8768 and one HTML page. Every button runs one CLI command. Three parts, in order: CLI flags, server, page."
todos:
  - id: cli
    content: "Part 1: cli.py build_parser, --why/--attach, --action, band in session.json, session prefix on names, cut sets the last cut aside, stats recorded"
    status: pending
  - id: server
    content: "Part 2: tools/review_web.py (shared pieces) + tools/entity_pipeline/web.py + tests/test_entity_web.py"
    status: pending
  - id: page
    content: "Part 3: tools/entity_pipeline/web/index.html + PROCESS_entity_web.md"
    status: pending
isProject: false
---

# Entity web page

Replaces `C:\Users\Douglas\.cursor\plans\entity_review_web_930cb16e.plan.md` (reviewed 2026-11-14: page could
not redraw with criticism, status from "file exists" was wrong after a redraw, names collided across sessions).

## Read this first
- Work on branch `feat/entity-web` in its own worktree, from `main` ([docs/WORKTREES.md](../../docs/WORKTREES.md),
  steps 1-2, link the venv). Never edit `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private`.
- Do the parts in order. One commit per part. A part is done when its check passes; do not start the next before.
- Find code **by function name**, not line number. Re-read a file right before editing it.
- Where this plan gives code, copy it as written. Do not rename, "improve", or add features.
- Python for everything: `Code\sprite_venv\Scripts\python.exe` (PowerShell, from the worktree root).
- **Do not:** make a paid call (Leonardo, OpenAI); run `brawl`, `fight` or `wire` for real (they edit
  `Code/Settings.py` and maps); touch `tools/boss_sprite_pipeline/outfit_web.py`, `rts_validation.py`,
  `ANIM_PROMPT`, `cut_sprite`, or `generated/entity_pipeline/pyramid3/attack_tests/`.
- If something in this plan is wrong (a test fails for a reason the plan did not expect, a name does not exist),
  stop and tell the user. Do not work around it.

## Part 1: CLI (`tools/entity_pipeline/cli.py`, `figures.py`, `stats.py`)

Before editing, run the tests and write down the count:
`Code\sprite_venv\Scripts\python.exe -m pytest -q tests/test_entity_gates.py tests/test_entity_pipeline.py`

### 1.1 `build_parser()`
In `main`, move everything from `parser = argparse.ArgumentParser(...)` through the last `set_defaults` into a
new `def build_parser() -> argparse.ArgumentParser:` that ends with `return parser`. `main` becomes:
```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
```

### 1.2 `--why` / `--attach` (redraw with criticism, without the keyboard)
Add above `build_parser`:
```python
def _add_why(parser: argparse.ArgumentParser, attach: bool) -> None:
    parser.add_argument("--why", default=None,
                        help="redraw now, with this criticism added to the prompt")
    if attach:
        parser.add_argument("--attach", default=None,
                            help="redraw now, with this image sent as image 2")
    else:
        parser.set_defaults(attach=None)
```
Call it: `_add_why(scene, attach=True)`, `_add_why(sheet, attach=True)`, `_add_why(anim, attach=False)`.
Every other parser whose command reaches `_gate` gets the defaults, so `_gate` never needs `getattr`:
- `run.set_defaults(func=cmd_run, sheet=None, why=None, attach=None)`
- `anim_all.set_defaults(..., action=None, why=None, attach=None)` (keep the existing keys)
- `everything.set_defaults(..., action=None, why=None, attach=None)` (keep the existing keys)

In `_gate`, replace
```python
    images = [(label, source)]
    if dest.exists() and not args.force:
        print(f"{step}: already have {dest}")
    else:
        _draw(dest, base_prompt, images, draw)
```
with
```python
    images = [(label, source)]
    attach = [Path(args.attach)] if args.attach else []
    if args.why or attach:
        if attach and not attach[0].is_file():
            print(f"no such image: {attach[0]}", file=sys.stderr)
            return False
        images += [("attached", path) for path in attach]
        _draw(dest, with_criticism(base_prompt, args.why or "", attach), images, draw)
    elif dest.exists() and not args.force:
        print(f"{step}: already have {dest}")
    else:
        _draw(dest, base_prompt, images, draw)
```

### 1.3 `anim --action`
Parser: `anim.add_argument("--action", choices=ACTIONS, default=None, help="only this clip. Default: all three")`.
In `cmd_anim`, first lines of the body (after the import):
```python
    if args.why and not args.action:
        print("--why redraws one clip: add --action idle, move or attack", file=sys.stderr)
        return 1
```
and the loop becomes `for action in (args.action,) if args.action else ACTIONS:`.

### 1.4 Band kept in `session.json`
Add above `_default_action_path`:
```python
def _band(args: argparse.Namespace) -> str:
    """The scene band frames sizes against. A --band given is kept in session.json, so the
    next frames run (or the web page) uses it without being told."""
    data = load_session(args.session)
    if args.band:
        if data.get("band") != args.band:
            data["band"] = args.band
            save_session(args.session, data)
        return args.band
    return data.get("band") or "near"
```
In `cmd_frames` replace `getattr(args, "band", "near")` with `_band(args)`.
In the three `--band` arguments (`anim_all`, `frames`, `everything`): `default=None`, and add to the help
`" Default: the band in session.json, else near"`.

### 1.5 Session prefix on every name
A cell name is also the `Graphics/Monsters/<name>` folder and the `monster_data` key, shared by all sessions.
Today pyramid, pyramid2 and pyramid3 all cut `warrior_00..`. New cuts are named `<session>_...`.
Existing folders (`warrior_00..19`, tracked) are left as they are: no rename, no migration.
- `figures.py`: `from dataclasses import dataclass, replace`.
  `def cut_sheet(image: Image.Image, out_dir: Path, *, prefix: str) -> list[Figure]:`; add to its docstring:
  `Every name starts with prefix (the session): a name is also the Graphics/Monsters folder and the
  monster_data key, shared by every session.`
  Light sheet: `figures = [replace(fig, name=f"{prefix}_{fig.name}") for fig in find_light_figures(image)]`.
  Grid: `name = f"{prefix}_warrior_{i:02d}"`.
- `stats.py`: `def parse_scores(text, names, *, prefix):` and pass `prefix` to
  `_unique_folder(raw, cell, scores, prefix)`; in `_unique_folder`, right after `used = ...`:
  `token = f"{prefix}_{token}"`.
- `cli.py` `cmd_cut`: `figures = cut_sheet(image, work, prefix=args.session)`.
  `cmd_stats`: `scores = parse_scores(text, names, prefix=args.session)`.

### 1.6 A re-cut sets the last cut aside
Today a re-cut leaves the last cut's cells beside the new ones, and brawl then wants frames for both.
- `_set_aside`: `found = [path for path in paths if path.exists()]` (was `is_file()`), docstring
  "files or folders", print `moved the last one to {folder}`.
- `cmd_cut`, right before `with Image.open(sheet) as image:`:
  `_set_aside([work / "cells", work / "layout.json", work / "contact.png"])`.

### 1.7 Stats call recorded
`cmd_stats`, after `out = save_scores(...)`:
`record_call(args.session, "stats", {"cost_usd": None, "output_path": str(out)})`.

### 1.8 Tests
Update (they break on purpose):
- `tests/test_entity_gates.py`: every `lambda image, out_dir: []` → `lambda image, out_dir, prefix: []`.
- `tests/test_entity_pipeline.py`: `cut_sheet(sheet, tmp_path, prefix="t")`; every `parse_scores(...)` gets
  `prefix="s"`; in `test_folder_name_comes_back_in_the_score_and_renames_the_cell` every expected folder
  name gets `s_` in front (`s_egyptian_spearman`, `s_camel_archer`), in every assert of that test.

Add to `tests/test_entity_gates.py` (use the `run` fixture and `_scene` / `_anim` helpers already there):
1. `--yes --why "too dark"` on a session that already has `scene.png`: 2 calls in total, the second prompt
   starts with `SCENE_PROMPT` and ends with `too dark`, one `old/*/scene.png`.
2. `--yes --attach <ref>`: the call's sources are `[map, ref]`.
3. `anim --yes --action move`: 1 call, only `move.mp4` exists.
4. `anim --yes --why x` without `--action`: returns 1, 0 calls.
5. `_band`: `cli_mod._band(SimpleNamespace(session="s", band="center"))` returns `center` and `session.json`
   has `"band": "center"`; then `band=None` returns `center`.
6. `cut` with a fake `cut_sheet` on a session that has `cells/old.png`: afterwards `old/*/cells/old.png` exists
   and `cells/` does not hold `old.png`.
7. `cut` passes `prefix="s"` to `cut_sheet` (the fake records it).

**Check 1:** both test files pass; the count is the count before plus 7. Commit
`Entity CLI: --why/--attach/--action, band kept per session, session prefix on names, re-cut sets the last cut aside.`

## Part 2: server

### 2.1 `tools/review_web.py` (new; shared by local review pages; stdlib only)
Only the entity page uses it now. `outfit_web.py` stays as it is (moving it here is a later, separate task).
Contents, in this order:
- `LOG_KEEP = 400`, `NAME = re.compile(r"^[A-Za-z0-9_\-]+$")`.
- `inside(path, roots)`: copy from `outfit_web.inside`.
- `read_clipboard()`: copy from `outfit_web.read_clipboard`.
- `check_key(name, value, keys)`: the check from `outfit_web`'s `/api/key` branch (prefix, other keys'
  prefixes, length >= 20, no whitespace); raises `ValueError(f"the clipboard does not hold a {name} key")`.
- `save_upload(folder, name, data_url) -> Path`: the body of `outfit_web`'s `/api/upload` branch with
  `folder` in place of `ctx.work / "gate" / "uploads"`.
- `class Jobs` (below): like `outfit_web.Jobs`, but a job holds **locks** (a set of names) instead of a lane.
  Two jobs may run at once when their locks do not overlap.
- `class Handler(BaseHTTPRequestHandler)` with `log_message` (quiet), `send`, `json`, `body`: copy those four
  methods from `outfit_web.make_handler`; plus `send_file` (below).

```python
class Jobs:
    """Running commands and the last 20 finished ones. A job holds locks; a second job that wants
    a held lock is refused, so one session runs one command and only one game window opens."""

    def __init__(self, driver: list[str], cwd: Path):
        self.lock = threading.Lock()
        self.driver, self.cwd = driver, cwd
        self.running: list[dict] = []
        self.done: list[dict] = []
        self.n = 0

    def start(self, key: str, args: list[str], locks: set[str]) -> dict:
        with self.lock:
            held = {name for job in self.running for name in job["locks"]}
            if locks & held:
                raise ValueError(f"busy: {', '.join(sorted(locks & held))}")
            self.n += 1
            job = {"id": self.n, "key": key, "args": args, "locks": sorted(locks), "lines": [],
                   "label": " ".join(args), "started": time.time(), "rc": None}
            self.running.append(job)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def snapshot(self) -> dict:
        with self.lock:
            return {"running": [dict(j, lines=j["lines"][-60:]) for j in self.running],
                    "done": [dict(j, lines=j["lines"][-60:]) for j in self.done[-20:]][::-1]}

    def last(self, key: str) -> dict | None:
        """The running job for `key`, else its last finished one."""
        with self.lock:
            for job in self.running + self.done[::-1]:
                if job["key"] == key:
                    return dict(job, lines=list(job["lines"]))
        return None

    def _run(self, job: dict) -> None:
        try:
            p = subprocess.Popen([*self.driver, *job["args"]], cwd=self.cwd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                 env=dict(os.environ, PYTHONUNBUFFERED="1"))
            for line in p.stdout:
                with self.lock:
                    job["lines"].append(line.rstrip("\n"))
                    del job["lines"][:-LOG_KEEP]
            rc = p.wait()
        except Exception as exc:                       # the command could not start at all
            job["lines"].append(f"could not run: {exc}")
            rc = -1
        with self.lock:
            job["rc"], job["ended"] = rc, time.time()
            self.running.remove(job)
            self.done.append(job)
            del self.done[:-20]
```

`send_file` answers `Range: bytes=a-b` (a `<video>` cannot seek without it):
```python
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp4": "video/mp4"}

    def send_file(self, path: Path, roots: list[Path]) -> None:
        ctype = TYPES.get(path.suffix.lower())
        if not ctype or not path.is_file() or not inside(path, roots):
            return self.send(404, b"not found", "text/plain")
        data = path.read_bytes()
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if not m or not (m.group(1) or m.group(2)):
            return self.send(200, data, ctype)
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)) if m.group(2) else len(data) - 1, len(data) - 1)
        else:                                          # bytes=-N: the last N bytes
            start, end = max(0, len(data) - int(m.group(2))), len(data) - 1
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(data)}")
            self.end_headers()
            return
        self.send_response(206)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data[start:end + 1])
```

### 2.2 `tools/entity_pipeline/web.py` (new)
Launch: `python -m tools.entity_pipeline.web [--port 8768] [--no-browser]`; `main()` like `outfit_web.main`.
Serves `tools/entity_pipeline/web/index.html`. All paths relative to the repo root (`_ROOT` as in cli.py);
the server never calls `session_dir()` (it creates folders).

Constants: `WORK = _ROOT / WORK_ROOT`, `MONSTERS = _ROOT / "Graphics" / "Monsters"`,
`MEDIA_ROOTS = [WORK, MONSTERS]`, `MAP_ROOTS = [WORK, _ROOT / "levels"]`,
`KEYS = {"openai": ("OPENAI_API_KEY", "sk-"), "leonardo": ("LEONARDO_API_KEY", "")}`.

**Status.** One rule for every output:
```python
def status(output: Path, inputs: list[Path]) -> str:
    """missing: no output. stale: an input is missing or newer than the output. done: otherwise.
    A redraw writes a new file (newer); a rename (stats) keeps the time, so it stays done."""
    if not output.exists():
        return "missing"
    made = output.stat().st_mtime
    if any(not p.exists() or p.stat().st_mtime > made for p in inputs):
        return "stale"
    return "done"
```
What each step's output is made from (`w` = session folder, `n` = a warrior = a `cells/*.png` stem):

| step | output | inputs |
|---|---|---|
| scene | `w/scene.png` | the `map_image` in `session.json` (repo-relative) |
| sheet | `w/sheet.png` | `w/scene.png` |
| cut | `w/layout.json` | `w/sheet.png` |
| stats | `w/stats.json` | `w/layout.json` |
| anim n a | `w/anim/n/a.mp4` | `w/cells/n.png` |
| frames n | `MONSTERS/n/_contact.png` | `w/anim/n/{idle,move,attack}.mp4`, `w/layout.json`, `w/stats.json` if it exists |
| brawl | `w/brawl.json` | every `MONSTERS/n/_contact.png`, `w/stats.json` if it exists |

Per session (anim, frames) the warriors' statuses fold into one: all done → `done`; all missing → `missing`;
any stale → `stale`; else `partial`.

`sessions()`: every folder in `WORK` → `{name, steps: {step: status}, cost_usd, calls_unknown}`. Cost: sum of
`session.json` `calls[].cost_usd` that are numbers; `calls_unknown` = how many are null.

`session_detail(name)` (name checked with `NAME`, folder must exist, else 404): `map_image`, `band`
(session.json, else `"near"`), the step statuses, file paths that exist (`scene`, `sheet`, `contact`,
`brawl`), the last prompt text of scene and sheet (`scene_prompt.txt`, `sheet_prompt.txt`), and `warriors`:
one row per cell: `name`, `cell` path, `anim` `{idle, move, attack}` → `{status, path}`, `frames`
`{status, contact}`, `score` (from `stats.json["scores"][name]` read directly, or null), `copies`
(`wire.roster_counts` over the scored warriors). Read `stats.json` with `json.loads`, not `load_scores`
(it prints).

**Commands.** `build_argv(body) -> (key, args, locks)`. `S` = `body["session"]` (must match `NAME`),
key = `S`, locks = `{"session:" + S}` unless the table says more. Anything not in the table is
`ValueError`. Flags are added only when the body has them.

| step | args | checks |
|---|---|---|
| scene | `scene --session S --image M --yes` [+ `--force`] [+ `--why W`] [+ `--attach A`] | `M` = `body["map"]` or the session's `map_image`; a file under `MAP_ROOTS`, suffix .png/.jpg/.jpeg. A new session = a name with no folder yet + `map` |
| sheet | `sheet --session S --yes` [+ `--force`] [+ `--why W`] [+ `--attach A`] | |
| cut | `cut --session S --yes` | |
| stats | `stats --session S` [+ `--force`] | no `--yes` (stats has none) |
| anim | `anim --session S --name N --yes` [+ `--action X`] [+ `--force`] [+ `--why W`] | `N` is a cell of S; `X` in `ACTIONS`; `--why` needs `X` |
| anim-all | `anim-all --session S --yes` | |
| frames | `frames --session S --name N --yes` [+ `--band B`] | `B` in `near`, `center` |
| brawl | `brawl --session S --each E --hold H --yes` | `E` int >= 1, `H` number > 0; locks `{"session:" + S, "game"}` |

`W`: a string, stripped, at most 500 characters. `A`: a file under `w/uploads/`. The args go to `Popen` as a
list (no shell), so the text is never parsed.

**Routes.**
- `GET /` the page. `GET /api/state` `{sessions, jobs: jobs.snapshot(), keys: {name: bool}}` (never a value).
- `GET /api/session?name=S` `session_detail`. `GET /api/log?name=S` `jobs.last(S)` or `{}`.
- `GET /media?path=P` `send_file(Path(P), MEDIA_ROOTS)`.
- `POST /api/do` `build_argv` then `jobs.start` → `{started: id}`; `ValueError` → 400 `{error}`.
- `POST /api/key {name}`: `check_key(name, read_clipboard(), KEYS)`, then `os.environ[env] = value`.
- `POST /api/upload {session, name, data}`: session folder must exist; `save_upload(w / "uploads", ...)`.
- `Jobs(driver=[sys.executable, "-m", "tools.entity_pipeline.cli"], cwd=_ROOT)`. `make_server(port, jobs)` as
  in `outfit_web`.

### 2.3 `tests/test_entity_web.py`
Shape of `tests/test_outfit_web.py`: a fake driver script (prints its args, sleeps 0.6 s, exits 0), a server on
port 0, `WORK` / `MONSTERS` / `MEDIA_ROOTS` / `MAP_ROOTS` monkeypatched into `tmp_path`. No paid call, no game.
1. Every row of the commands table (all flags on): `build_argv` output parses with `cli.build_parser()`
   (`parse_args(args)` does not raise and `func` is the right `cmd_*`).
2. Unknown step, `"a/b"` as session, `--why` on anim without action, map outside `MAP_ROOTS`,
   `each=0`, `hold=0`: each 400.
3. Two commands for one session: second is 400 "busy". Two sessions at once: both 200. Two brawls for two
   sessions: second 400 (`game`).
4. `/media`: a file outside the roots 404, a `.txt` 404, a `.png` inside 200, `Range: bytes=0-3` on an
   `.mp4` → 206 with 4 bytes and `Content-Range: bytes 0-3/<size>`.
5. `/api/state` keys: env set → true, unset → false; the response text holds no key value.
6. Status: fixture session with `scene.png`, `sheet.png`, `layout.json`, `cells/s_a.png`: cut done; then
   `os.utime` `sheet.png` newer than `layout.json`: cut stale; anim `missing`; one clip of three → `partial`.
7. `/api/log` shows the fake driver's printed args while it runs.
8. `/api/session?name=nope` → 404, and no folder `nope` was made.

**Check 2:** `pytest -q tests/test_entity_web.py tests/test_entity_gates.py tests/test_entity_pipeline.py
tests/test_outfit_web.py` all pass. Commit `Entity web: server and shared review_web pieces.`

## Part 3: page and process doc

### 3.1 `tools/entity_pipeline/web/index.html`
One file, no build, no library. Look and helpers copied from `tools/boss_sprite_pipeline/web/outfit.html`
(`esc`, `api`, `toast`, lightbox, chips, colours). Poll `/api/state` every 2 s; reload `/api/session` when the
session's job ends or the selection changes.
- **Header:** OpenAI / Leonardo set or –, each with "from clipboard".
- **Left:** sessions, each with step chips coloured by status (done / stale / partial / missing / running) and
  its cost (`$x`, plus `+N unknown` when calls_unknown > 0). Below: **New session** (name, map path, Start →
  `scene` with `map`).
- **Right, one panel per step chip:**
  - Scene / Sheet: the picture (click to zoom), the prompt text that went. Buttons: Redraw (`force`), and a
    criticism box + optional image (upload → `attach`) + "Redraw with this" (`why`, `attach`).
  - Cut: Cut (if sheet done), `contact.png`, grid of cells with names.
  - Stats: Score / Ask again (`force`), a table: name, label, reach, size, speed, damage, bulk, copies.
  - Anim: a warrior picker (cells), three `<video controls loop>` (idle, move, attack) with each clip's status,
    per clip Redraw (`action`, `force`) and criticism box (`action`, `why`). "Animate all missing"
    (`anim-all`), with a confirm that says it pays for every missing clip.
  - Frames: band select (shows the session's band; sending it changes it), per warrior Pack + `_contact.png`.
  - Brawl: copies (`each`, default 1), seconds (`hold`, default 60), Fight. A note: it opens the game window
    and adds the warriors to `Code/Settings.py` `monster_data`.
- **Log** under the panel: `/api/log?name=S`, grows while the job runs, its exit code when it ends.
- A button whose session is busy is disabled. A stale step shows "made before its input changed".
- The brawl log ends with `validation finished but output file not found` on a clean close
  (`Code/rts_validation.py:106`, a known bug, not fixed here). Show it as is.

### 3.2 `tools/entity_pipeline/PROCESS_entity_web.md`
Sections as in `AGENTS.md`: Method that works (launch command, keys, the step order), Known errors (the brawl
line above; "busy"), Log (dated, what was checked and how), Tried and dropped:
- Lanes per kind of step (old plan): one global gen lane blocked other sessions. Per-session locks instead.
- Step status from "file exists": wrong after a redraw. mtime against inputs instead.
- Hash records per output: dropped, a stats rename moves files and would orphan the records; mtimes survive it.
- Map upload copied into the session: maps are under `levels/` or a session folder; the page takes a path.

**Check 3** (in the worktree, nothing paid, nothing tracked changed):
1. Copy one session, timestamps kept:
   `robocopy C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\generated\entity_pipeline\pyramid3 generated\entity_pipeline\pyramid3 /E /DCOPY:T`
   and `generated\entity_pipeline\pyramid\map.jpg` (pyramid3's map). `generated/` is git-ignored.
2. Start the page, open it. pyramid3: chips show done for scene, sheet, cut, stats; the anim videos play and
   seek; frames contact sheets show (`Graphics/Monsters/warrior_*`, tracked).
3. New session `webcheck`, free steps only: copy pyramid3's `scene.png`, `sheet.png`, `session.json` into
   `generated\entity_pipeline\webcheck\` (no paid step needed), press Cut: cells named `webcheck_warrior_00..`.
   Copy `pyramid3\anim\warrior_00\*.mp4` into `webcheck\anim\webcheck_warrior_00\`, press Pack for that warrior:
   `Graphics\Monsters\webcheck_warrior_00\` appears. Press Cut again: frames for `webcheck_warrior_00` show stale,
   `old\<time>\cells\` holds the first cut.
4. Clean up: delete `generated\entity_pipeline\webcheck`, `generated\entity_pipeline\pyramid3`,
   `generated\entity_pipeline\pyramid`, `Graphics\Monsters\webcheck_warrior_00`. `git status` shows only your
   committed work (nothing).
Write in the Log what was checked and how (which buttons, what was seen). Commit
`Entity web: page and process doc.` Then report to the user: branch, commits, pushed or not. Do not merge.
