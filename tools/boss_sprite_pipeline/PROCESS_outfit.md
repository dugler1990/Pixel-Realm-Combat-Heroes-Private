# Outfit pipeline: process

One command per character + outfit: drawings → 3D → skeleton → paint → cut into slots → game packs.
Plan: `.cursor/plans/outfit_pipeline.plan.md`. Armour method and its history: `explode2/PROCESS_explode2.md`.

## Method that works

Setup (PowerShell, from the repo root; the data lives in the Boss folder):
```
$env:OUTFIT_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
$PY = "Code\sprite_venv\Scripts\python.exe"
$env:OPENAI_API_KEY = (Get-Clipboard).Trim()      # copy each key first; never typed or printed
$env:LEONARDO_API_KEY = (Get-Clipboard).Trim()
$env:HF_TOKEN = (Get-Clipboard).Trim()            # pod steps: TRELLIS weights, SAM3
```
A worktree needs junctions to `Code\sprite_venv`, `tools\boss_sprite_pipeline\.venv-bpy` (Boss folder) and
`tools\boss_sprite_pipeline\.venv-pose` (main folder); see docs/WORKTREES.md.

Run, and rerun the same command after each stop:
```
& $PY -m tools.boss_sprite_pipeline.outfit barb naked                 # runs until the first gate / pod step
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --status
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only front --accept 2
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only front --retry r1      # r | r1 | rb | "r <why> @img"
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --host <ip> --port <port>    # pod steps (trellis, sam3, holopart)
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only trellis --pick front_back
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only paint --accept 1      # or --redo <view> ...
```
After every pod step's pull the driver prints **stop the pod**. You start and stop pods.

Steps (`outfit.py` header): body `front back trellis skeleton paint export`; armour adds `views sam3 cut
holopart merge worn slots sheet` before `export`; cut (a piece from an existing mesh) is those alone.

Files:
| What | Where |
|---|---|
| outfit settings and prompts | `outfits/<character>/<outfit>.json` (paths relative to the data root) |
| run state | `<data>/generated/bosses/<character>/outfits/<outfit>/run.json` |
| drawings + gates | `<run>/gate/` (`gate_front.json`, `gate_back.json`, sheets, cut-outs) |
| TRELLIS models | `<run>/trellis/front_only_from_front.glb`, `front_back_from_front.glb` |
| body pack | `Graphics/Meshes/<pack>/` (+ the printed `PlayerSelectionDict.json` entry, pasted by hand) |
| slot packs | `<run>/packs/<slot>/` (not in Graphics: the game cannot draw them yet) |

Settings that matter:
- fullplate front: `margin` **0.03** (v9; checked against v9's outline image pixel for pixel, 2026-11-13).
- naked front: `front_check` `match` (IoU + bands against his outline, margin 0), as a back is scored.
- TRELLIS: both models each run; pick by eye at the gate (no measure yet). Picks are logged in run.json.

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| export: `RuntimeError: Please select a file` in slot_packs | slots path taken from the run folder, not run.json (backfilled runs live elsewhere) | fixed: `ctx.out("slots", "slots")` |
| `--display-joints needs the pose venv` | worktree without `.venv-pose` | junction to the main folder's `tools\boss_sprite_pipeline\.venv-pose` |

## Log

- 2026-11-13: driver, outfit files, view_gate --outfit / --dry-run / --no-ask / --retry / --accept, pod.py,
  trellis_outfit.sh, slot_packs.py, export_outfit.py. `view_gate front --outfit barb/fullplate --dry-run
  --retry rb`: prompt identical to v9 `front_attempt_02_prompt.txt`, back identical to `back_attempt_01`, all 6
  images sent identical (diff / pixel compare). `--backfill` on fullplate: 13 steps found from v9's paths.
- 2026-11-13: `outfit.py barb fullplate` after the backfill ran `export` only: 10 slot packs (v9 slots) in
  `<run>/packs/`, 3,000-11,000 tris each by share of 40k, each loads as a PlayerMesh with the 3 clips (305 frames).
  For drawing in game later: each pack's own pivot and size differ from the body's (PlayerMesh sized each slot
  alone to 56 px: 53-161 px); a worn slot must be drawn at the body's pivot and scale, not its own.

## Tried and dropped

(none yet)
