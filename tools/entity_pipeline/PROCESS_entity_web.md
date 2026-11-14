# Entity web page: process

The entity pipeline (`python -m tools.entity_pipeline.cli`) in the browser. Plan: `.cursor/plans/entity_web.plan.md`.

## Method that works

Launch (PowerShell, repo root):
```
Code\sprite_venv\Scripts\python.exe -m tools.entity_pipeline.web
```
Opens http://127.0.0.1:8768/ . `--port N`, `--no-browser`. 8765 SAM, 8766 levels, 8767 outfits, 8768 entity.

- Keys: copy a key, press its "from clipboard" (OpenAI, Leonardo). The page shows set / –, never the value. OpenAI must start with `sk-`. Leonardo is a long token with no spaces and must not start with `sk-`.
- Left: each session, step chips (done / stale / partial / missing / running), cost `$x` and `+N unknown` when a call has no cost. New session: name, map path (a png/jpg under `levels/` or a session folder), Start. That runs `scene`.
- One panel per step. Scene and sheet: the picture, the prompt, Redraw (`--force`), or a criticism and an optional image (Redraw with this: `--why`, `--attach`). Cut (once the sheet is done). Stats: Score, or Ask again (`--force`); the table is name, label, reach, size, speed, damage, bulk, copies. Anim: one warrior, idle / move / attack, Redraw or a criticism per clip, Animate all missing (`anim-all`; it pays for every missing clip). Frames: band (`near` or `center`; sending it stores the band on the session), Pack per warrior. Brawl: copies and seconds, Fight.
- A stale step says "made before its input changed". A button for a session that already has a command is disabled.
- The page reads the session folder. It does not write `session.json`. Every button is one CLI command.

Order: scene, sheet, cut, stats, anim, frames, brawl.

Files: `tools/review_web.py`, `tools/entity_pipeline/web.py`, `tools/entity_pipeline/web/index.html`, `tests/test_entity_web.py`.

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| Brawl log ends with `validation finished but output file not found` | `Code/rts_validation.py` prints that when the window closes cleanly. A known bug, not fixed here | Read the log as it is. The fight still ran |
| `busy: session:<name>` | One command per session | Wait until its log shows an exit code |
| `busy: game` | Only one game window | Wait until that brawl exits |

## Log

- 2026-11-14: Part 1 tests, 47 passed (`tests/test_entity_gates.py`, `tests/test_entity_pipeline.py`; 40 before, plus 7).
- 2026-11-14: Part 2 tests, 61 passed (those two, plus `tests/test_entity_web.py` and `tests/test_outfit_web.py`). No paid call, no game.
- 2026-11-14: Check 3 in this worktree. `robocopy` of `pyramid3` (`/E /DCOPY:T`) and a copy of `pyramid/map.jpg` into `generated/` (gitignored). Port 8768 was already the outfit page, so this page was opened on 8778.
  pyramid3: chips done for scene, sheet, cut, stats, anim, frames; brawl stale. Cost `$10.9196`. Keys showed OpenAI – and Leonardo –.
  warrior_00 idle, move, and attack loaded (1280px, 4s). Idle played and seeked to 2.0s. Twenty frame contact sheets loaded from `Graphics/Monsters/warrior_*`.
  webcheck: copied pyramid3 `scene.png`, `sheet.png`, `session.json`. Pressed Cut: cells `webcheck_warrior_00`..`19`, exit 0. Copied `pyramid3/anim/warrior_00/*.mp4` to `webcheck/anim/webcheck_warrior_00/`. Pressed Pack: `Graphics/Monsters/webcheck_warrior_00/_contact.png`, exit 0. Pressed Cut again: the frames chip and `webcheck_warrior_00` showed stale, "made before its input changed". `old/2026-11-14_224948/cells/webcheck_warrior_00.png` held the first cut.
  Fight was not pressed. No paid call. The copies and `Graphics/Monsters/webcheck_warrior_00` were deleted after.

## Tried and dropped

- Lanes per kind of step (old plan): one global gen lane blocked other sessions. Per-session locks instead.
- Step status from "file exists": wrong after a redraw. mtime against inputs instead.
- Hash records per output: a stats rename moves files and would orphan the records. mtimes survive it.
- Map upload copied into the session: maps are under `levels/` or a session folder. The page takes a path.
