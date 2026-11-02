# Explode v2 — log

What happened at each step of `PLAN.md`, for refining into a repeatable (later automated) process.
Run from the Boss repo root with the Blender venv: `PY=tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe`.
Outputs: `generated/bosses/barb/explode2/<outfit>/`.

## Step 0 — the outfit gets the base skeleton (2026-11-02, local, 43 s)

```
%PY% tools\boss_sprite_pipeline\explode2\outfit_skeleton.py generated\bosses\barb\rigfix\barb_final.glb generated\bosses\barb\gear_test\barb_fullplate_from_front.glb generated\bosses\barb\explode2\fullplate\fullplate_rigged.glb
%PY% tools\boss_sprite_pipeline\explode2\pose_render.py generated\bosses\barb\explode2\fullplate\fullplate_rigged.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\STEP0_CHECK.png
```

- Align onto `barb_final`'s body: scale 0.9984, head residual 0.19 % of height.
- First try, `rig_reweight.py heat 0.5` on the outfit alone: **every weight 0** (Blender: "Bone Heat
  Weighting: failed to find solution"), and the glTF export then silently drops the skin. The outfit is
  a hollow shell; the bones sit in its empty inside, so bone heat has nothing to solve on.
- Fix (in `outfit_skeleton.py`): the proxy is the outfit **joined with the base body** (which fills the
  hollow), voxel-remeshed at 0.5 % of h, largest island kept (6 islands → the 5 small ones are closed
  pockets between body and armour). Bone heat: 0 of 55,400 proxy verts unweighted; transferred to all
  791,038 outfit verts (none unweighted). The script asserts both.
- Check (`STEP0_CHECK.png`, `STEP0_ZOOM.png`): rest and cut pose (upper arms +70°, legs spread 20° each),
  5 views. Shoulders, armpits and hips bend cleanly, no tearing.

## Coverage: the cut pose does not help; camera directions do (2026-11-02)

`explode/explode_visibility.py` now takes `--pose roles.json` (measure in the cut pose) and
`--greedy out.json` (best camera directions, picked one at a time by most new surface seen).

| | 96 regular views | ceiling (256 dirs) |
|---|---|---|
| rest | 52.8 % | 68.2 % |
| cut pose | 53.4 % | 68.1 % |

- Posing adds 0.6 points: the outside surface the 96 views miss is not the armpits/inner thighs but
  narrow gaps between plates (lames, straps, plate overlaps), each visible only from a few directions.
- Greedy directions (`fullplate/greedy_dirs.json`, rest pose, 47 s):

| directions | surface seen | share of the visible ceiling |
|---|---|---|
| 16 | 52.1 % | 76 % |
| 32 | 56.0 % | 82 % |
| 64 | 60.5 % | 89 % |
| 96 | 63.4 % | 93 % (the regular 96: 77 %) |
| 128 | 65.4 % | 96 % |

- So step 2 (pose) is dropped and step 3 renders the greedy directions instead of the regular grid.
- Caveat for step 3: a ray that escapes counts as seen even at a grazing angle; a gap seen edge-on is a
  few pixels wide in a render and SAM may not label it. Check the greedy set with a facing limit before
  rendering.

## Diagnostics page (2026-11-02)

Every step leaves its settings and numbers as `diag_<step>.json` in the outfit's folder;
`explode2/diag.py <work>` gathers them (plus the paint costs and patch report) into `<work>/DIAGNOSTICS.md`.
Re-run it after any step.

```
python tools\boss_sprite_pipeline\explode2\diag.py generated\bosses\barb\explode2\fullplate
```

- `outfit_skeleton.py` writes `diag_step0_skeleton.json` (alignment scale and residual, proxy voxel size,
  islands, unweighted vertex counts, time).
- `explode_visibility.py ... --json <file>` writes the coverage run (sample count, direction sets, visible %
  per set, hidden % per part when labels are given, the greedy curve).
- repaint `gen` records `usd` per painting in `check.json` and prints the run total and the folder total.

## Step 1 — paint the full plate (2026-11-02)

Cost of the bare barb's paint (from the token counts in each `check.json`, gpt-image-2 at $5 text in /
$8 image in / $30 image out per 1M tokens): 20 close-ups × $0.76 + 8 body views × $0.21 + 3 head views ×
$0.25 = **$17.59**. Four of the close-ups ($3.04) were dropped as unalignable.

For the armour, 12 close-ups instead of 25 (`repaint/looks/barb_fullplate.json`, reasons in its `_about`):
the second view per hand added 0.13–0.19 % of the texture, the side-face views failed to align, the feet
are small at sprite scale, legs_back already frames the hips from behind. Estimate 8 × $0.21 + 12 × $0.76
≈ **$10.80**.

```
%PY% tools\boss_sprite_pipeline\repaint\repaint.py views generated\bosses\barb\explode2\fullplate\fullplate_rigged.glb generated\bosses\barb\explode2\fullplate\paint generated\bosses\barb\gear_test\barb_roles.json --look tools\boss_sprite_pipeline\repaint\looks\barb_fullplate.json
%PY% tools\boss_sprite_pipeline\repaint\repaint.py gen generated\bosses\barb\explode2\fullplate\paint generated\bosses\barb\gear_test\in\barb_fullplate.png
%PY% tools\boss_sprite_pipeline\repaint\repaint.py project generated\bosses\barb\explode2\fullplate\fullplate_rigged.glb generated\bosses\barb\explode2\fullplate\paint
```

Then (same day): the 2880 close-ups were 3–11× more than the 4096 texture keeps (repaint/PROCESS_repaint.md,
"2880 was wasted"). The full-plate look now paints close-ups at **1024** (`part_res`), and the arm frames were
widened (they cut the pauldron tops; `FRAMING_parts.png`, `FRAMING_arms.png`). At high quality that is
8 × $0.21 + 12 × ~$0.25 ≈ **$4.70** instead of $10.80. Medium vs high is being tested on the bare barb's
face first (`repaint/quality_test.py`, ~$0.40); the look's `quality` is set from the result.

Model test on the bare barb's face_front (same prompt and input images; sheets
`generated/bosses/barb/paint/quality_test/QUALITY_face_front.png` and `ALIGN_face_front.png`):

| model | cost | silhouette match | look |
|---|---|---|---|
| gpt-image-2 high 2880 (the one used) | $0.758 | 0.93 | painterly, the reference style |
| gpt-image-2 medium 1024 | $0.099 | 0.96 | almost the same as high |
| gpt-image-2 medium 816 | $0.093 | 0.95 | same; saves $0.006 (the ~$0.047 of input images is fixed) |
| gpt-image-1-mini medium 1024 | $0.023 | 0.72 | unusable: orange cartoon skin, reframed |
| Leonardo nano-banana-2 1024 | $0.039 (Leonardo's charge) | 1.00 | crisper, more graphic, darker hair; features on the model's lines |
