# Outfit pipeline: process

One command per character + outfit: drawings → 3D → skeleton → paint → cut into slots → game packs.
Plan: `.cursor/plans/outfit_pipeline.plan.md`. Armour method and its history: `explode2/PROCESS_explode2.md`.
In the browser: `PROCESS_outfit_web.md` (the same commands behind buttons).

## Method that works

Setup (PowerShell, from the repo root; the data lives in the Boss folder):
```
$env:OUTFIT_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
$PY = "Code\sprite_venv\Scripts\python.exe"
$env:OPENAI_API_KEY = (Get-Clipboard).Trim()      # copy each key first; never typed or printed
$env:LEONARDO_API_KEY = (Get-Clipboard).Trim()
$env:HF_TOKEN = (Get-Clipboard).Trim()            # TRELLIS weights; sent to the pod once, reused after
```
A worktree needs junctions to `Code\sprite_venv`, `tools\boss_sprite_pipeline\.venv-bpy` (Boss folder) and
`tools\boss_sprite_pipeline\.venv-pose` (main folder); see docs/WORKTREES.md.

Pod: deploy with Public IP + TCP 22. The Connect tab's `…@ssh.runpod.io` line is a proxy (no scp); get the direct
address: `& $PY tools\boss_sprite_pipeline\gpu_box\pod.py address "<that line>"` → `POD <ip> <port>`.

Run, and rerun the same command after each stop:
```
& $PY -m tools.boss_sprite_pipeline.outfit barb naked                 # runs until the first gate / pod step
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --status
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --models front_back_sides,eight_views   # kept in run.json
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only front --accept 2
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only front --retry r1      # r | r1 | rb | "r <why> @img"
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only sides --view front_left --accept 7
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --host <ip> --port <port>    # pod steps (trellis, sam3, holopart)
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only trellis --pick eight_views
& $PY -m tools.boss_sprite_pipeline.outfit barb naked --only paint --accept 1      # or --redo <view> ...
```
After the outfit's last pod step the driver prints **stop the pod**. You start and stop pods. Each step's output
also goes to `<run>/logs/<step>.log`.

Steps (`outfit.py` header): body `front back sides trellis skeleton paint export`; armour adds `views sam3 cut
holopart merge worn slots sheet` before `export`; cut (a piece from an existing mesh) is those alone.

TRELLIS models (a choice; default `eight_views`, an outfit's `"trellis_models"` or `--models` overrides):
| model | drawings |
|---|---|
| `front_only` | front |
| `front_back` | front, back |
| `front_back_sides` | + left, right |
| `eight_views` | + front_left, back_left, front_right, back_right (3/4 views) |
The `sides` step draws only what the chosen models need: left, then the left 3/4s (each sent the accepted left
side); the right-hand views are the left ones mirrored (`"mirror_right"`, default true). Several models: pick at
the gate from `trellis/TRELLIS_SHEET.png` (front, his left side, back per model); one model: picked by itself.

Files:
| What | Where |
|---|---|
| outfit settings and prompts | `outfits/<character>/<outfit>.json` (paths relative to the data root) |
| run state | `<data>/generated/bosses/<character>/outfits/<outfit>/run.json` |
| drawings + gates | `<run>/gate/` (`gate_front.json`, `gate_back.json`, `gate_side_<view>.json`, sheets, cut-outs) |
| TRELLIS models + sheet | `<run>/trellis/<model>_from_front.glb`, `TRELLIS_SHEET.png` |
| logs | `<run>/logs/<step>.log` |
| body pack | `Graphics/Meshes/<pack>/` (+ the printed `PlayerSelectionDict.json` entry, pasted by hand) |
| slot packs | `<run>/packs/<slot>/` (not in Graphics: the game cannot draw them yet) |

Settings that matter:
- fullplate front: `margin` **0.03** (v9; checked against v9's outline image pixel for pixel, 2026-11-13).
- naked front: `front_check` `match` (IoU + bands against his outline, margin 0), as a back is scored.
- naked sides: `side_config` gpt-image-2 (Leonardo refused them as NSFW).
- naked paint look: `shots` re-word the pelvis close-ups (the default ones ask for "leather loincloth and belt").
- A 3/4 or side draw that comes back as several figures: redraw with "r draw ONE single figure only, not two".

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| export: `RuntimeError: Please select a file` in slot_packs | slots path taken from the run folder, not run.json (backfilled runs live elsewhere) | fixed: `ctx.out("slots", "slots")` |
| `--display-joints needs the pose venv` | worktree without `.venv-pose` | junction to the main folder's `tools\boss_sprite_pipeline\.venv-pose` |
| pod: `$'{\r': command not found`, `set: pipefail: invalid option` | Windows checkout has CRLF; scp copied it as is | fixed: `pod.put` strips `\r` from pushed `.sh` |
| pod `run` kept polling after the script died | waited only for the success marker | fixed: `run_detached` appends `RUN_EXIT $?`; a run ending without its marker stops |
| worn: `TypeError: 'NoneType' object is not subscriptable` in piece_weights | a cut keeps the rest of the mesh as "body", which has no plate rule | fixed: worn passes `--only <pieces>` (the prompt_to_part values but body) |
| worn shown "skipped" though it never ran | "skipped" was recorded before the test, then it crashed | fixed: the note is recorded with "done" after the test |
| TRELLIS reinstalled on every run (~2.5 min when cached) | install check `import trellis2` fails outside the TRELLIS.2 folder | fixed: installed = `setup.log` holds INSTALL_OK |
| Leonardo: generation FAILED, `moderationClassification: ['NSFW']` | naked side view / pelvis_back close-up | sides: `side_config` gpt-image-2; paint: reworded pelvis shots (to check) |
| OpenAI 429 `credit_balance_exhausted` | no credit on the key's organisation | add credit (billing of the organisation that owns the key) |

## Log

- 2026-11-13: driver, outfit files, view_gate --outfit / --dry-run / --no-ask / --retry / --accept, pod.py,
  trellis_outfit.sh, slot_packs.py, export_outfit.py. `view_gate front --outfit barb/fullplate --dry-run
  --retry rb`: prompt identical to v9 `front_attempt_02_prompt.txt`, back identical to `back_attempt_01`, all 6
  images sent identical (diff / pixel compare). `--backfill` on fullplate: 13 steps found from v9's paths.
- 2026-11-13: `outfit.py barb fullplate` after the backfill ran `export` only: 10 slot packs (v9 slots) in
  `<run>/packs/`, 3,000-11,000 tris each by share of 40k, each loads as a PlayerMesh with the 3 clips (305 frames).
  For drawing in game later: each pack's own pivot and size differ from the body's (PlayerMesh sized each slot
  alone to 56 px: 53-161 px); a worn slot must be drawn at the body's pivot and scale, not its own.
- 2026-11-13, pod RTX 3090 24 GB (81.27.69.180): loincloth cut end to end. SAM3 install + 111 views ~4 min, 3
  shards SAM_OK; cut: loincloth 126,610 faces, body 843,218 (`cut/parts_000.png`, `parts_180.png`: clean);
  HoloPart install ~30 min (diso compile), run ~2 min; worn test passed 6 poses; slot pack 40,000 tris loads,
  305 frames. Sheet: holes at the hip sides, 35 loose bits (9.3 % of faces).
- 2026-11-13: naked barb. Front gpt-image-2 attempt 1 (IoU 0.989; "FAIL thigh -1.13" = the loincloth flap gap in
  his outline). Back Leonardo attempt 1 PASS (IoU 0.978). TRELLIS install 15-20 min first time; front_only 4.5 min,
  front_back 6.5 min, front_back_sides 4.5 min, eight_views 7.5 min, GPU 98 % throughout (one job fills it).
  By eye: front_back better than front_only (bun, back); front_back_sides and eight_views best profile and back,
  slimmer arms / arms closer to the body than the front drawing. Pick pending (front_back_sides or eight_views).
- 2026-11-13: naked paint (on front_back) put a belt and pouch on his hips: the default pelvis close-ups ask for the
  loincloth. Look reworded (`shots`); repaint of pelvis_front / pelvis_back pending, after the pick.
- 2026-11-14: models choice, sides step, TRELLIS sheet, token reuse, pod address / status, step logs, $ per step.
  `--only sides` on naked: 6 views found done; `--only trellis --models front_back_sides,eight_views`: sheet, gate.

## Tried and dropped

- Right side and right 3/4 views drawn on their own (gpt-image-2, 2026-11-13): right side 2.4 % then 3.2 % short;
  front_right as four small figures; back_right drew a front view. Now the left ones mirrored.
- Leonardo (nano-banana-2) for the naked side view: NSFW refusal twice (with and without "no clothing").
