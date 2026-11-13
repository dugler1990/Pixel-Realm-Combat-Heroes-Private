# Plan: the outfit web page

Status 2026-11-14: steps 0-4 built, 14 tests pass, checked on the real runs (PROCESS_outfit_web.md); 5 (one new outfit
from the page alone) not yet.

Goal: run the outfit pipeline (`outfit.py`, `.cursor/plans/outfit_pipeline.plan.md`) from the browser. Every
gate becomes a panel: look, click accept / retry / pick, the next step runs. No terminal, no Claude in the loop.

Same stack as the level review page (`feat/level-review-page`, `world_levels/review_web.py`, itself copied from
sam3local's review page): stdlib `ThreadingHTTPServer` on 127.0.0.1, one HTML file, polling. Every button runs the
same `outfit.py` command a person would type, with the same arguments, in a background thread, one at a time.
`run.json` stays the only state; the page reads it, never writes it.

## 0. Gaps in the driver first (found in the 2026-11-13 test run)
Each of these was done by hand in that run; the page can only click what the driver can do.
- **TRELLIS models are a choice.** `front_only`, `front_back`, `front_back_sides`, `eight_views` (front, back,
  both sides, the four 3/4 views). Default `eight_views` (`DEFAULT_MODELS` in `outfit.py`); an outfit's
  `"trellis_models"` or `--models a,b` overrides. Only the chosen models are built (`trellis_outfit.sh MODELS`).
  One model chosen: picked by itself; several: the pick gate. (2026-11-13, naked barb: front + back + sides and 8
  views both better than front + back by eye; 8 views no clear gain over 4 yet.)
- **Side views as a step.** `sides`, between `back` and `trellis`: draws the views the chosen models need: `left`,
  then `front_left`, `back_left` (each sent the accepted left side so it matches). The right-hand ones are the left
  ones mirrored (`"mirror_right"`, default true): drawn alone, the right side came out 2.4-3.2 % short twice, a
  right 3/4 came back as four small figures, "back-right" drew a front view. One gate per view
  (`gate_side_<view>.json`): `--only sides --view front_left --accept N | --retry ...`. Image model per outfit
  (`"side_config"`): Leonardo refused the naked side as NSFW twice, gpt-image-2 drew it.
- **TRELLIS sheet.** `gpu_box/trellis_sheet.py`: each model front / side / back, Workbench texture, one PNG
  (the scratchpad script of 2026-11-13, kept). The pick gate shows it.
- **Token once.** `trellis` sends the HF token only if the pod has none (`test -s .../token`); now it needs
  `HF_TOKEN` in the environment every run.
- **Pod from the SSH line.** `pod.py address "<ssh line from RunPod>"`: asks the proxy (`-tt`, commands on stdin)
  for `$RUNPOD_PUBLIC_IP $RUNPOD_TCP_PORT_22`, prints host / port. Done by hand each time so far.
- **Logs.** Each step's output to `<run>/logs/<step>.log` as it runs (now: only the terminal).
- **Cost.** Paint's per-view `$` lines and the drawings' calls summed into run.json `cost`; pod minutes ×
  `--pod-rate`.

## 1. Server: `tools/boss_sprite_pipeline/outfit_web.py`
`python -m tools.boss_sprite_pipeline.outfit_web [--port 8767] [--no-browser]` (8765 SAM, 8766 levels).
- `GET /api/outfits`: every `outfits/<character>/<outfit>.json`, its kind and run.json status per step.
- `GET /api/run/<character>/<outfit>`: run.json + the gate files (`gate_<view>.json` attempts with scores).
- `GET /img?path=`: only files under the data root's `generated/bosses/` and the repo's `Graphics/Meshes/`.
- `POST /api/do`: `{character, outfit, args: [...]}` → `outfit.py <character> <outfit> <args>`; refused while
  one runs. Args are checked against the driver's own flags (no free text reaches a shell; a retry reason and an
  attached image go as one argument each).
- `GET /api/progress`: running, step, the log's last lines, exit code, the driver's STOPPED message.
- Keys: read from the environment at launch; the page shows which are set (OpenAI, Leonardo, HF), never values.
  "Read from clipboard" button per key: the server reads the clipboard once into its own environment
  (PowerShell `Get-Clipboard`), checks the prefix (`sk-` / `hf_`), never echoes it.

## 2. Page: `tools/boss_sprite_pipeline/web/outfit.html`
- Left: outfit list; per outfit its steps with status (done / gate / pending / skipped / failed), time, cost.
- Right: the current step's panel.
  - **models (before front):** tickboxes front only / front + back / front + back + sides / 8 views, preset from
    the outfit (default 8 views); they set which drawings the run asks for.
  - **front / back / sides:** every attempt's sheet, newest first, scores above it; Accept; Retry `r`, `r1`, `rb`,
    reason + image (file picker → saved beside the gate, sent as `@path`). Sides: one row per view.
  - **trellis:** Run (builds the ticked models not built yet); then the TRELLIS sheet and Pick per model.
  - **paint:** the `after_*.png` views; Accept; Redo with view tickboxes.
  - **views / sam3 / cut / holopart / merge:** parts sheet, `split_preview_*.png`; Continue.
  - **worn:** `POSE_COMPARE_tex.png`. **slots / sheet:** `SLOTS_SHEET.png`.
  - **export:** pack path, load result (frames per clip, height), the `PlayerSelectionDict.json` entry with Copy.
  - Log pane under every panel (the step's log, tailed).
- Pod bar (top): paste the RunPod SSH line → host / port (`pod.py address`); what the pod is doing (GPU %,
  memory, the running job, installed: TRELLIS / SAM3 / HoloPart); minutes and $ since the first pod step.
  When no pod step is queued or running: a red **stop the pod** banner. The page never starts or stops a pod.

## 3. Two lanes so the GPU does not wait
Every button runs one step (`--only <step>`). Two lanes: pod steps (trellis, sam3, holopart) and local steps; one
command per lane and per outfit at a time. So one outfit's pod step runs while another waits at a drawing gate
(2026-11-13: the loincloth's SAM3 + HoloPart ran while the naked drawings waited, by hand). One pod job at a time:
a single TRELLIS job held the 3090 at 98 % GPU (2026-11-13), so a second job would not finish sooner.

## 4. Tests: `tests/test_outfit_web.py`
No paid call, no pod, no Blender (a fake `outfit.py` that sleeps and prints STOPPED / STEP_DONE):
`/api/do` refuses a second command while one runs; refuses unknown flags; `/img` refuses a path outside the
roots; progress shows the log and the STOPPED message; the outfit list reads run.json.

## 5. Proof
On the 2026-11-13 runs (`naked`, `loincloth`, `fullplate` backfilled): every panel shows them as they are.
Then one new outfit end to end from the page alone, nothing typed in a terminal but the launch.

## Process doc
`tools/boss_sprite_pipeline/PROCESS_outfit_web.md`: Method, Known errors, Log, Tried and dropped.

## Not in this plan
Drawing slot packs in game; several people at once; anything off 127.0.0.1.
