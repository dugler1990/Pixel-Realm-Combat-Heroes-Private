# Explode v2 — log

What happened at each step of `PLAN.md`, for refining into a repeatable (later automated) process.
Run from the Boss repo root with the Blender venv: `PY=tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe`.
Outputs: `generated/bosses/barb/explode2/<outfit>/`.

## Method: explode an armour mesh into swappable pieces (proven 2026-11-12 on v9 front + back)

In: a TRELLIS armour mesh of him wearing it (`<armour>.glb`), the front drawing it came from (`<front>.png`).
Need: Leonardo key (`$env:LEONARDO_API_KEY`), an HF token with SAM3 access, a pod (A40 / PyTorch 2.8 template,
public IP + TCP 22, ~50 GB). PowerShell from the Boss root; `$PY = "tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe"`,
`$W = "generated\bosses\barb\explode2\<outfit>"`, `$G = "generated\bosses\barb"`, pod `root@<ip> -p <port>`, key `ppp`.

1. **Skeleton** (local, 1 min): `& $PY tools\boss_sprite_pipeline\explode2\outfit_skeleton.py $G\rigfix\barb_final.glb <armour>.glb $W\fullplate_rigged.glb`
   → must print `SKELETON_OK` (0 unweighted).
2. **Paint** (local + Leonardo, ~20 min, ~$1): `& $PY tools\boss_sprite_pipeline\repaint\paint_outfit.py $W\fullplate_rigged.glb $W\paint <front>.png $G\gear_test\barb_roles.json tools\boss_sprite_pipeline\repaint\looks\barb_fullplate.json`
   → `PAINT_OUTFIT_DONE`; look at `$W\paint\result\after_0_body_0.png`.
3. **Views** (local, ~5 min): `& $PY tools\boss_sprite_pipeline\explode\explode_render.py $W\paint\result\fullplate_rigged_painted.glb $W\views "greedy:$G\explode2\fullplate\greedy_dirs_f75.json:32" --diag $W\diag_step3_render.json`
4. **SAM3** (pod, ~5 min). Upload (Git Bash `scp -P <port> -i ppp`): the SAM3 snapshot
   (`~/.cache/huggingface/hub/models--facebook--sam3/snapshots/<id>` → `/workspace/sam3`), `C:/Users/Douglas/sam3local/src`
   → `/workspace/sam3local_src`, `explode/explode_sam.py`, `explode/sam3_pod.sh`, `explode2/prompts_v2.json` → `/workspace/`,
   `$W/views` → `/workspace/views`. Run: `bash /workspace/sam3_pod.sh /workspace/views /workspace/prompts_v2.json`
   → `SAM_DONE`, check each `sam_shard*.log` ends in `SAM_OK`. Pull `/workspace/views/masks` → `$W/views/masks`.
5. **Cut** (local, ~5 min): `& $PY tools\boss_sprite_pipeline\explode\explode_label.py $W\views --facing-power 8 --belt-gate --crease-snap --dirs 32 --out $W\cut --diag $W\diag_step5_label.json`
   → `LABEL_OK`; look at `$W\cut\PARTS_SHEET.png`.
6. **HoloPart** (pod, ~10 min; optional: worn it looks the same as the shells). Upload `explode/holopart_pod.sh`,
   `explode/holopart_patch.py`, `$W/cut/input_parts.glb` → `/workspace/`. Run `bash /workspace/holopart_pod.sh install`
   (→ `DECIMATE True`, `HP_READY`), then `bash /workspace/holopart_pod.sh run /workspace/input_parts.glb /workspace/holopart_out`
   → `HP_DONE`. Pull `/workspace/holopart_out/*` → `$W/holopart/`. **Stop the pod.**
7. **Merge + pieces sheet** (local): `copy $W\views\cams.json $W\cut\`, then
   `& $PY tools\boss_sprite_pipeline\explode\explode_merge.py $W\cut $W\holopart\output.glb` (→ `MERGE_OK`, `shells_parts.glb`,
   `merged_parts.glb`) and `& $PY tools\boss_sprite_pipeline\explode\explode_show.py $W\cut $W\holopart\output.glb`
   (→ `PARTS_ALONE.png`, `EXPLODED.png`). Without HoloPart: `explode_merge.py $W\cut` alone gives `shells_parts.glb`.
8. **Worn test** (local, ~3 min each): `& $PY tools\boss_sprite_pipeline\explode\explode_pose.py --texture --aligned --rigid --hide-under $G\rigfix\barb_final.glb $G\gear_test\barb_roles.json $W\worn_shells outfit=$W\cut\shells_parts.glb`
   (and `worn_merged` with `merged_parts.glb`) → `POSE_COMPARE_tex.png`, 6 poses.

Known errors (all hit 2026-11-12, all fixed or worked around above):
| Symptom | Cause | Fix |
|---|---|---|
| step 1 `bone heat failed on the proxy`, ~1,000 proxy islands | `VOXEL` 0.5 % h too fine: bulky armour does not fuse with the body, kept piece is a hollow shell | `VOXEL = 2.0` (committed) |
| step 2 `no cams.json yet` | roles + look not given | pass `barb_roles.json` and `looks\barb_fullplate.json` |
| step 4 `KeyError: 'full'` in every shard | default prompts have no `full` crop (steep views) | pass `prompts_v2.json` |
| step 6 `cannot import name 'LayerNorm'` | newest diffusers | pins in `holopart_pod.sh` |
| step 6 `DECIMATE False` / `libOpenGL.so.0` | apt install without update | `apt-get update` first (in the script) |
| step 7 `cams.json` not found | merge reads it from the cut folder | copy it from `views` |
Open: his head is cut as a piece (drop it); stray bits; limb misalignment (see the 2026-11-12 entries below).

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

Chosen: Nano Banana 2. repaint `gen` now takes `"provider": "leonardo", "model": "nano-banana-2"` from the look
(set in `barb_fullplate.json`). If Leonardo refuses a view's size (body views are 1024x1536) it paints at
Gemini's nearest 1K size (848x1264) and projection rescales it. Checked with a stubbed Leonardo (no paid
calls): refusal, retry size, anchor image, IoU and cost records, the diagnostics table. Estimate for the
20 armour views: 20 × ~$0.039 ≈ **$0.80**.

First run: 3 of 20 painted ($0.12); 17 failed with `'str' object has no attribute 'get'`. Leonardo refused
those requests (4 at once; likely a concurrency or rate limit) with a plain-text reason, and
`leonardo_api._readable_api_error` crashed reading it, hiding the reason. Refused requests make no image and
cost nothing. Fixed: the reader handles text reasons and prints them; repaint retries refusals and 429/5xx
after 20/40/80/160 s (never after a generation exists, so nothing is paid twice) and writes `error.txt` in a
failed attempt. Then `gen ... missing` paints only the views without a finished painting.

Second run: all 8 body views and 3 close-ups came back; the armour face was reframed (head drawn ~75 %
size with armour round it: IoU 0.77), which projection would drop. Deciding that was by eye, so it is
now a rule:

- **Paint step = one command**, `repaint/paint_outfit.py <rigged.glb> <work> <ref.png> [<roles.json> <look.json>]`:
  views (only if `cams.json` is missing) → `gen missing` → `project` → `diag.py`. Re-running it repaints
  only what is missing or unusable, then projects again.
- `gen` checks every painting as it arrives with project's own alignment rule (`aligns()`: ECC ≥ 0.95,
  scale 0.85–1.18; one shared function now, `align_painting`) and repaints a failure up to 2 more times,
  keeping the first that lines up (else the best). `missing` = no painting, or one that does not line up.
  check.json records ecc / scale / aligns; the diagnostics table shows them and which attempt is used.
- Checked with a stubbed Leonardo returning a face drawn at 75 % twice: repainted twice, third kept.

```
%PY% tools\boss_sprite_pipeline\repaint\paint_outfit.py generated\bosses\barb\explode2\fullplate\fullplate_rigged.glb generated\bosses\barb\explode2\fullplate\paint generated\bosses\barb\gear_test\in\barb_fullplate.png
```

Projection of all 20 (888 s): body views ecc 0.98–0.99; 6 close-ups dropped (face_front scale 0.76;
arm_r_out 0.89; pelvis_front 0.87; hand_r_out, chest_front, back_upper 0.93–0.94); hand_l_out lines up
but painted skin-coloured gaps between thin steel fingers → orange hand on the model (no rule catches
it: `paint_outfit.py ... --redo hand_l_out`). These 7 repaints are not done yet; they change only the
texture, not the cut (SAM labels end up on mesh faces), so they can come after the explode.

## Step 3 — camera views for SAM (2026-11-02)

The greedy set did not care about grazing angles. `explode_visibility.py --facing 75`: a point counts as
seen from a direction only if its surface faces it within 75° (either side; TRELLIS normals are not
reliably outward). Ceiling 68.2 % → **64.1 %** head-on enough; greedy (`greedy_dirs_f75.json`):
16 dirs 49.6 %, 64 → 56.3 %, 96 → 59.1 %, **128 → 61.0 % (95.2 % of that ceiling)**.

`explode_render.py <glb> <work> greedy:<dirs.json>:<count> --diag <file>`: the first 128 directions of the
painted GLB (`paint/result/fullplate_rigged_painted.glb`), upper/lower crops at 1120 px; views steeper
than 60° get one full-body crop (ortho 1.05 h). Test: 1 direction = 2 renders, 148 s with the scene load.

```
%PY% tools\boss_sprite_pipeline\explode\explode_render.py generated\bosses\barb\explode2\fullplate\paint\result\fullplate_rigged_painted.glb generated\bosses\barb\explode2\fullplate\views "greedy:generated\bosses\barb\explode2\fullplate\greedy_dirs_f75.json:128" --diag generated\bosses\barb\explode2\fullplate\diag_step3_render.json
```

Rendered: 128 directions → 226 renders (30 steep views as one full crop) in ~21 min, **~5.5 s per render**
(the 148 s test was mostly the scene load).

## Step 4 — SAM3 on the pod (2026-11-02)

Pod: RunPod "PyTorch 2.8.0", RTX PRO 4000 Blackwell 24 GB, 48 cores. Ubuntu 24.04 refuses system pip
(PEP 668): venv `--system-site-packages` (`/workspace/sv`, transformers 5.22.1 has `Sam3Model`). SAM3 weights
copied from the local HF snapshot (3.3 GB, ~5 min with `sam3local/src`; tar ownership errors are harmless).
One-view test: 12 prompts in 21 s with the model load.

- `explode_sam.py` now takes `SAM3_SHARD=i/k`: 3 processes side by side → GPU at 100 %, 16 GB used.
  226 views × 11–19 prompts = 2,922 prompt runs in **~29 min**, 12,383 masks (≥ 0.2 kept).
- Lost ~10 min: the pod waited until all renders were done before anything was uploaded. Next time feed
  it in batches as renders finish.
- On the painted armour, front: "armored skirt" 0.44 (v1 unpainted: 0.73–0.91); tried "skirt", "kilt",
  "tassets", "metal skirt" (all < 0.15), "waist armor" 0.53. **"waist armor" is unusable**: from behind it
  takes the whole back plate with the skirt (0.63) → first label had the back plate and a leg as skirt.
  Dropped from `PROMPT_PART`; "armored skirt" scores 0.70 from behind (exact), so the skirt still gets votes.

## Step 5 — label: part per face (2026-11-02, local, ~5 min for 226 views)

```
%PY% tools\boss_sprite_pipeline\explode\explode_label.py generated\bosses\barb\explode2\fullplate\views --facing-power 8 --out generated\bosses\barb\explode2\fullplate\cut_d128 --diag generated\bosses\barb\explode2\fullplate\diag_step5_label_d128.json
```

Direct coverage 65.5 % of welded verts (v1: 41 % at 8 views, 58 % at 96). 14 parts; torso = breastplate +
back plate, skirt from the belt down, legs separate. The fauld's pointed front plate went to the belt.

**How many views are worth it** (`--dirs N` = first N greedy directions on the same masks;
`explode2/compare_cuts.py` → `CUTS_BY_VIEWS.png`, `diag_step5_cut_vs_views.json`):

| step | faces that change part | biggest changes |
|---|---|---|
| 16 → 32 dirs | 6.3 % | belt 58 % (the fauld plate joins it), leg_r 14 %, pauldron_r 12 % |
| 32 → 64 | 4.2 % | pauldron_r 10 %, skirt 8 %, head 7.5 % |
| 64 → 128 | 5.6 % | pauldron_r 40 %, skirt 12 %, belt 11 % |

The cut does not settle as views are added: every doubling moves 4–6 % of faces, all at part borders,
and the four sheets look the same piece for piece (torso 8.8 % different between 16 and 128 dirs).
More views buy no better cut past 16–32 directions: the borders wobble because the prompts disagree
where parts meet (as v1 found), which is step 7's job (snap to creases), not more cameras.
**Default for the next outfit: 32 directions (55 renders, ~5 min render, ~4 min SAM with 3 shards).**

## Step 8 — HoloPart (pod, same session)

Installed while SAM ran (`/workspace/hp_install.sh`: v1's recipe at HoloPart 48dd632 + `holopart_patch.py`;
`decimation True`). Weights pre-fetched while labelling. 14 parts: diffusion 50 steps × 2 batches at
2.6 s/it (9 GB VRAM), meshing ~2 min → `holopart_d128/output.glb` (165 MB), latents, logs, pip freeze.
Pod work end to end ≈ 55 min.

Then locally: `explode_show.py` (EXPLODED.png, PARTS_ALONE.png) and `explode_merge.py` (merged_parts.glb:
14 painted pieces = original shell + HoloPart only where the shell has nothing; MERGED.png). As in v1,
HoloPart's own surfaces are noisy/stair-stepped and thin plates (pauldron_r) break into lace; the shells
are clean. Left: a plate hanging off the torso's back bottom, the fauld front plate in the belt, open
ends where parts join (boot soles, torso bottom).

## Step 13 (first look) — the breastplate alone on the naked barb (2026-11-02, local, ~10 min)

`explode_pose.py` gained `--aligned` (parts already in the base's frame), `--only <parts>` and
`--hide-under` (delete body faces a worn part covers or that poke out through it: ray along the face
normal hits the part within 6 % h, or against it within 3 % h, for faces on the bones the part sits on).
`explode2/swap_sheet.py` puts the same poses side by side.

```
%PY% tools\boss_sprite_pipeline\explode\explode_pose.py --texture generated\bosses\barb\rigfix\barb_final.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\swap_test\bare
%PY% tools\boss_sprite_pipeline\explode\explode_pose.py --texture --aligned --rigid --hide-under --only torso generated\bosses\barb\rigfix\barb_final.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\swap_test\torso breastplate=generated\bosses\barb\explode2\fullplate\cut_d128\merged_parts.glb
```

Result (`swap_test/SWAP_breastplate.png`, `SWAP_zoom.png`): the painted breastplate + back plate sits on
`barb_final`, rigid on the chest bone, and moves with him (arms up, twist, bend, step); 154k body faces
hidden under it. Problems:
- **Too narrow**: the barb's pecs and lats bulge past the plate's sides (the plate comes from the slimmer
  armoured model) → step 12 (fit to the widest chest) is needed.
- **Skin patch on the back plate** (heart-shaped, between the shoulder blades): not a hole — the cut's back
  view is all torso and the piece alone is whole there. The barb's upper back pokes out through the plate
  by more than the 3 % h `--hide-under` reaches, so those faces stay. Same cause as the sides: the plate is
  smaller than this body → the fit (step 12), not the labels.

- **Lats gone with the arms up / forward** (empty space between arm and plate): `--hide-under` also deletes
  skin up to 3 % h *outside* the plate (meant for skin poking through), but this plate does not reach that
  far, so nothing covers those faces. Same root: the plate is smaller than the body.

## Is SAM the weak link? (2026-11-02)

`explode2/sam_check.py <views> <out.png>`: per view, each pixel takes the part SAM's masks give it under the
labeller's own rules (read from explode_label.py), before any combining (`SAM_CHECK.png`: front, side,
back, 3/4, upper and lower crops). SAM's masks are clean for head, hands, arms, pauldrons, belt, lower legs
and boots from every side. What went wrong was mine:
1. "armored skirt" from the side/back also covers the torso's sides, and skirt priority (1.0) beat torso (0.8);
2. from the front the (exact) skirt mask scored 0.44 < MIN_INSTANCE 0.5 → tassets unlabelled;
3. the breastplate mask takes the pointed plate below the belt; nothing kept the torso above the belt.
The thighs under the skirt are dark padding no armour prompt catches. The painting does not hurt SAM (the
skin-coloured left hand is still labelled gauntlet).

Fix without re-running SAM (masks are kept): `explode_label.py --belt-gate`. The belt line = median world
height of SAM's belt masks (58.8 % of height); skirt votes only below it, torso votes only above it (pixel
heights from the position EXRs), also enforced while flooding unseen surface; "armored skirt" counts from
0.4. On 32 dirs: 3.8 % of faces change, all into the skirt (the fauld front plate leaves the belt; the belt is
only the belt; the torso ends at the belt) → `cut_d32_gate/`.

```
%PY% tools\boss_sprite_pipeline\explode\explode_label.py generated\bosses\barb\explode2\fullplate\views --facing-power 8 --belt-gate --dirs 32 --out generated\bosses\barb\explode2\fullplate\cut_d32_gate --diag generated\bosses\barb\explode2\fullplate\diag_step5_label_d32_gate.json
```

HoloPart re-run on `cut_d32_gate` (same pod, ~5 min) → `holopart_d32_gate/output.glb`.

## What does HoloPart buy? (2026-11-02)

`explode2/holo_value.py`: each piece alone from 6 directions, front faces white, back faces red; see-through %
= red / piece pixels (the inside seen through a hole or open end: an inventory item, a piece worn without
its neighbours). Previous cut (`cut_d128`): **7.9 % → 5.7 %** mean with HoloPart's infill; belt 24.9 → 12.4,
pauldron_r 16.3 → 10.1, pauldron_l 7.4 → 4.4, arms −1.6/−1.8, torso only 9.4 → 8.9 (its open ends are the
neck, arm holes and waist, which HoloPart does not close as they are real openings).

### Previous vs new version (2026-11-02)

previous = `cut_d128` (128 dirs, no gate) · new = `cut_d32_gate` (32 dirs, `--belt-gate`). Sheets:
`CUT_prev_vs_new.png`, `holo_value/HOLO_VALUE.png` + `HOLO_VALUE.md`, `swap_test/SWAP_zoom_prev_vs_new.png`,
`swap_test/SWAP_breastplate_prev_vs_new.png`.

- Cut: 5.4 % of faces differ (pauldron_r 15 %, skirt 11.6 %, belt 8.3 %, torso 2.5 %).
- See-through % of each piece alone (mean over parts): previous 7.9 → 5.7 with HoloPart; new 7.5 → 5.4.
  Torso shell 9.4 → **4.6** (the hanging plate is gone); belt worse 24.9 → 29.3 (it is now a bare ring, open
  inside — HoloPart 16.6). HoloPart's gain is the same in both: about −2.2 points (−28 %), mostly belt and
  pauldrons (single-sided plates whose undersides it thickens).
- Breastplate alone on the naked barb: the new torso ends cleanly at the belt (the pointed plate over the
  loincloth is gone). Unchanged in both: skin through the back plate and the missing lats with the arms
  up/forward — the fit (step 12).

### HoloPart's own output vs what the merge keeps (2026-11-02)

`holo_value.py` with HoloPart's raw `output.glb` as a third column (parts matched by centre): **0.0 %
see-through on every part** (pauldron_r 0.3) — HoloPart does close every piece. `merge_explain.py`
(`MERGE_EXPLAIN_pauldron_r.png`): the merge kept 19 % of HoloPart's pauldron_r; the dropped faces sit a
median 0.16 % h from the cut shell — in the slice the shell already has the plate's top and underside and
HoloPart's surface runs inside the plate, a duplicate. So the merge is not discarding needed surface there:
the cut pieces were mostly whole already, which is why HoloPart changes little in the merged pieces and
nothing in the breastplate-on-barb test (torso 4.6 → 4.0 %).
Open: why the cut shells still show 7.5 % red. Tried `--recalc` (Blender's recalc_face_normals before
rendering) to tell inward-facing faces from holes: it made every shell ~35–48 % red (it flips the open,
layered TRELLIS shells inconsistently), so it cannot answer this. Not blocking the fit.

## Step 12 — breastplate fit (2026-11-02, local, ~3 min + pose test ~5 min)

`explode2/fit_piece.py <base_rigged.glb> <roles.json> <parts.glb> <part> <out_parts.glb> [--bone chest]
[--gap 0.005] [--thick 0.004]`: the plate rides the chest bone rigidly, so the body is looked at from that
bone — in each of the 6 test poses (now shared: `explode_common.test_poses` / `set_pose`) the torso skin
(root, spine, spine2, chest, neck, shoulder bones; not the arms) is moved into the chest bone's rest frame.
Around a vertical axis through the plate, bins of 1 % h × 5°: body's largest radius over all poses vs the
plate's outer radius. Where body + gap (0.5 % h) + thickness (0.4 % h) reaches past the plate, the plate is
pushed outward by the shortfall (smoothed over ±1.5 bins, at least 80 % of the raw need); every layer in a
bin moves the same, so the plate keeps its thickness. Only outward.

```
%PY% tools\boss_sprite_pipeline\explode2\fit_piece.py generated\bosses\barb\rigfix\barb_final.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\cut_d32_gate\merged_parts.glb torso generated\bosses\barb\explode2\fullplate\fit\merged_parts_fit.glb --diag generated\bosses\barb\explode2\fullplate\diag_step12_fit_torso.json
```

- The plate was too tight in 1,690 of its 1,832 bins: push median 2.5 % h (~4.4 cm), max 5.4 % h (~10 cm).
  After: 990 bins still inside gap + thickness (the 80 % floor and smoothing), but the slices
  (`fit/FIT_torso.png`: body over all poses grey, plate before red / after green) show the plate outside the
  body at 63–86 % height.
- Pose test (`swap_test/SWAP_zoom_fit.png`, `SWAP_breastplate_fit.png`): **the skin patch on the back is
  gone, the lats no longer vanish with the arms up / forward, the sides are covered**; it reads as a
  breastplate worn by this barb. Left: ragged cut edges at the arm holes, the back slightly boxy in side view
  (the twist and bend poses widen it there).

## Moving: sweeps and real clips (2026-11-02)

- `explode_pose.py --sweep`: each motion swept smoothly past the still poses' angles (twist ±45°, bend
  −15…+40°, side bend ±25°, arms swing +40…−90°, arms raise to 90°), front-3/4 + side:
  `swap_test/sweep_fit/SWEEP_<motion>.gif`, `SWEEP_SHEET.png`. The fitted plate follows every sweep; no break
  seen at sheet scale.
- Real clips: `retarget_bvh.py` gained a `barb` target (UniRig literal roles like the anunaki → `--source
  anunaki`; bind_match off, arm cap open). Walk, two-hand swing, overhead chop (Kimodo/SOMA clips from
  `anunaki/bvh_all`), 150 frames each, 22 bones, 4 min → `barb/anim_test/retarget/animated.blend`.
  `explode_pose.py --clips a,b` plays them (base = the animated.blend; camera follows his root; every 3rd
  frame) and `explode2/anim_compare.py` stacks without / with.

```
%PY% tools\boss_sprite_pipeline\retarget_bvh.py --source anunaki --target barb generated\bosses\barb\anim_test\bvh generated\bosses\barb\anim_test\retarget
%PY% tools\boss_sprite_pipeline\explode\explode_pose.py --texture --clips walk,twohandswing,overheadchop generated\bosses\barb\anim_test\retarget\animated.blend generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\anim_test\bare
%PY% tools\boss_sprite_pipeline\explode\explode_pose.py --texture --aligned --rigid --hide-under --only torso --clips walk,twohandswing,overheadchop generated\bosses\barb\anim_test\retarget\animated.blend generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\anim_test\breastplate breastplate=generated\bosses\barb\explode2\fullplate\fit\merged_parts_fit.glb
```

## Holes: find them, fill the small ones (2026-11-02)

`explode2/hole_check.py <parts.glb> <out> [--parts ...] [--hole-max 0.06] [--fix <out.glb>]`: boundary edges
after welding UV seams; each connected run is an opening; perimeter < 6 % h = a hole, longer = a real
opening (neck, arm holes, waist). `--fix` fills the holes (bmesh holes_fill, new corners take the
surrounding UV). `holes/HOLES_<part>.png`: before (holes red, openings blue) / after.

On the fitted pieces (113 s): torso 1,033 holes (perimeter 8.4 h in total) + 69 openings; belt 823; pauldron_l
261; pauldron_r 426. Filled: torso 526 faces (629 holes left), belt 633 (375 left), pauldron_l 237 (103
left), pauldron_r 280 (305 left) → `fit/merged_parts_fit_holes.glb`. The torso's holes sit on the arm-hole
rims and down the sides under the arms — the side-view holes; the ones left are on ragged, tangled rims
(where HoloPart's infill patches meet the shell and along the cut) that holes_fill cannot close. Clean rims
need step 7 (snap the cut to creases) and step 9 (tidy edges), not more filling.

## Step 7 — snap borders to the creases (2026-11-02, local, in the label run)

`explode_label.py ... --crease-snap`: after the face labels, faces within SNAP_BAND × h of a border are
relabelled by a multi-source shortest-path flood (scipy `dijkstra`, `min_only`) from the faces outside the
band, which keep their part. A step between two faces costs their centre distance × (1 + 50 × crease),
crease = 1 − |n₁·n₂| scaled so a 30° fold or sharper is 1 (normals compared either way up). Each side fills
up to the fold, so the border lands where the plates meet. Runs before the fragment cleanup.
`explode2/border_zoom.py <out.png> <label>=<cut> ...`: close-ups where two parts meet (camera found from
the last cut's border), each cut in the same part colours → `BORDERS_gate_vs_snap.png`.

| band | changed | result |
|---|---|---|
| 2 % h | 31,052 faces | belt edges, wrist cuff clean; **pauldrons flooded by the arm** (most of a small plate lay in the band, too little left to regrow it) |
| **0.8 % h** (kept) | 17,168 faces | every border cleaner than before: belt top and bottom along the belt's edges, gauntlet cuff, pauldron rims; no flood |

A quarter of all edges count as creases (the TRELLIS surface is bumpy), so the band must stay narrow:
within ~1.4 cm the strongest fold is the plate seam.

```
%PY% tools\boss_sprite_pipeline\explode\explode_label.py generated\bosses\barb\explode2\fullplate\views --facing-power 8 --belt-gate --crease-snap --dirs 32 --out generated\bosses\barb\explode2\fullplate\cut_d32_snap --diag generated\bosses\barb\explode2\fullplate\diag_step7_label_snap.json
```

Rebuilt from it with the same commands (HoloPart output of `cut_d32_gate` reused: the borders moved by
1.4 cm at most and the merge matches HoloPart's parts by centre): merge → fit → holes → pose test, into
`cut_d32_snap/`, `fit_snap/`, `holes_snap/`, `swap_test/torso_snap/`.

## The holes come from the merge, not the cut (2026-11-02)

Back views of the fitted plate in every pose: the plate is solid but every edge is ragged with small
holes (sides by the lats, bottom, strap tops). The snap did not change the hole count (torso 1,033 → 1,001),
so `hole_check.py` was run on the plain cut torso (`shells_parts.glb`, no HoloPart):

| torso (snapped cut) | small holes | ragged edge (sum of hole perimeters) | openings |
|---|---|---|---|
| plain cut piece | 343 | 0.7 h | 11 |
| merged with HoloPart infill | 1,001 | 8.3 h | 70 |

The merge's infill patches are loose surface whose own ragged rims never join the plate: 3× the holes, 12×
the ragged edge. HoloPart's gain on the torso was ~0.6 points of see-through; the merge costs far more.
**So the torso is built from the plain cut piece**, cleaned: `hole_check.py --clean --fix` deletes islands
under 1 % of the piece (2,976 faces), strips rim spikes (556 faces in 3 passes), smooths the rim (4 passes),
then fills: **132 holes left** (merged + fill: 596). Front and back look clean (`holes_shell_clean/HOLES_torso.png`);
left: a stray lump on top of the gorget and the ragged inner rim inside the arm holes (hidden by body/arm
when worn). HoloPart stays for the plates whose undersides it thickens (belt, pauldrons) — to be checked
the same way.

All movement checks now render front, 3/4, side and back (`explode_pose.py` MOVE_VIEWS).
`final_check/`: cleaned + fitted torso — stills, sweeps, the 3 clips bare and with, `COMPARE_<clip>.gif`.

```
%PY% tools\boss_sprite_pipeline\explode2\hole_check.py generated\bosses\barb\explode2\fullplate\cut_d32_snap\shells_parts.glb generated\bosses\barb\explode2\fullplate\holes_shell_clean --parts torso --clean --fix generated\bosses\barb\explode2\fullplate\cut_d32_snap\shells_clean_torso.glb
%PY% tools\boss_sprite_pipeline\explode2\fit_piece.py generated\bosses\barb\rigfix\barb_final.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\cut_d32_snap\shells_clean_torso.glb torso generated\bosses\barb\explode2\fullplate\fit_clean\parts_fit.glb
```

### Torn armpits (2026-11-02)

First four-side stills of the cleaned plate: rest/twist/bend/step good from every side, but with the arms
up or forward the armpits were torn (see-through from the side). `--hide-under` took its bones from the
piece's copied skin, which on the cleaned torso included the upper arms (bone_7, bone_14), so it deleted the
inner-arm skin by the arm hole — the skin that fills the armpit when the arm lifts. Now `skin_bones(part)`
lists per piece the bones whose skin it may hide (torso: root, spine, spine2, chest, neck, both clavicles;
pauldron: clavicle + upper arm; arm: upper arm + forearm; …). Re-run: armpits are skin again; a small light
sliver is left in side views where the arm-hole edge stands off his side.

### Full check from four sides (2026-11-02, ~55 min of renders)

Cleaned + fitted torso (`fit_clean/parts_fit.glb`), armpit fix in. Review sheets (upper body, front / 3/4 /
side / back): `final_check/stills/STILLS_ZOOM.png`, `final_check/sweep/REVIEW_sweeps.png` (each sweep at its
two ends and middle), `final_check/REVIEW_<clip>.png` (5 key frames, without above with), GIFs
`final_check/COMPARE_<clip>.gif`, `final_check/sweep/SWEEP_<motion>.gif`.

- **Holds:** front and back of the plate solid in every pose, sweep and clip; it rides the chest through twist
  ±45°, bend, side bend ±25°, arms swing and raise to 90°, the two-hand swing and the overhead chop.
- **Left on the plate:** (1) a small light sliver at the armpit in side views whenever an arm is out — the
  arm-hole edge stands off his side; (2) at full forward bend, a light strip at the lower back where the
  plate's bottom edge lifts off; (3) ragged arm-hole rim and the lump on top of the gorget.
- **Not the plate:** the bare barb's own shoulder stretches hard when an arm goes overhead (rig).
- **Walk clip is broken on the retarget side:** his legs never step (the legs barely move in the swing and
  chop either) — the barb's leg chain is not being driven properly by `retarget_bvh.py --target barb`.
  To fix before any walking check.

### The mistake behind the arm-hole see-through (2026-11-03)

Zoomed (`final_check/stills/_gap_zoom.png`): with an arm out, the plate's arm hole is a huge ring from the
shoulder down to the lower ribs, and through it you see background where body skin was deleted.
- **The torso piece has no side panel under the arm.** In every SAM view the arm hangs in front of the
  plate's side, so that surface was voted "upper arm armor" or flooded from the arm. In the cut pose the
  armour's side and armpit are plainly there (`STEP0_ZOOM.png`, arms +70°). Step 2 (pose for the cut) was
  dropped on a global number — +0.6 points of surface visible from *some* direction — but what matters at
  the armpit is that the side is seen *without the arm in front of it*. That decision was wrong.
- **`--hide-under` deletes skin, which leaves holes in the body**; through the plate's openings (the over-big
  arm hole, the bottom rim when he bends) you look into those holes.
- The skin at the lower back in the bend is real skin below the plate: only the breastplate is worn (no belt
  or skirt) and the rigid plate rides up off his back as he bends forward.

Fix: (1) SAM views of the armour in the cut pose too (arms raised, legs apart), the labeller mapping those
pixels through the posed vertex positions; (2) skin under a piece pushed inward behind it instead of
deleted, so the body has no holes to see into.

### Back patch found; poses back in; skin tucked instead of deleted (2026-11-03)

- The patchy skin on one side of his back (bend): `explode_pose.py --hide-body` shows the plate alone whole
  and steel-coloured there (`final_check/BACK_PATCH_CHECK.png`) — it is his lower-back skin poking out
  through the plate when he bends (plate on the chest bone, lower back on the spine; `--hide-under` only
  judged skin at rest).
- `explode_pose.py --tuck` (replaces `--hide-under`): for a rigid piece, in its bone's frame, every covered
  skin vertex (skin_bones) gets the largest shortfall over the 6 test poses against the piece's inner side
  (outer radius − 0.4 % h, margin 0.4 % h, bins 1 % h × 5°) and is pushed in radially at rest by it,
  spread to neighbours (3× max, 6× average) so the patch has no step. Nothing is deleted; where the piece is
  absent (openings) nothing is pushed.
- Step 2 back: `explode_render.py ... ring --pose <roles> cut|arms_fwd --append`: the painted rigged outfit
  posed (cut = arms raised 70° to the sides, legs apart; arms_fwd = arms forward 70°), 12 yaws × (0°, +30°) +
  4 from below = 28 directions × 2 wider crops = 56 renders per pose, into `views/` as `cut_*` / `arms_fwd_*`
  with `posed_<pose>_verts.npy` / `_normals.npy`. `explode_label.py` looks posed cameras up in those posed
  positions (`--no-posed` to leave them out for comparison).

Tuck tested on the current plate (`final_check/stills_tuck/STILLS_ZOOM.png`, 6 poses × 4 sides): 68,701 skin
vertices pushed in (max 2.0 % h, median 0.17 % h). The see-through slivers at the armpits and the patchy
skin on the lower back in the bend are gone. Left: the oversized arm hole (his side skin shows through it
with an arm up) — the posed SAM views are for that.

More poses (2026-11-03): besides cut (sides, armpits, pauldron undersides) and arms_fwd (inner arms),
`step` (inner legs, backs of the knees, the skirt's inner plates) and `head_up` (the gorget's front under the
beard). Rendered the same way; SAM gets each pose's level ring + the 4 from below (32 views per pose).
Pod (2026-11-03): RTX PRO 4000 Blackwell, same recipe as step 4 (setup + upload 6.5 min). First start
uploaded 1 of 64 views: the file list was written by Python on Windows with CRLF endings, so tar looked for
`name.png\r`. Lists for the pod are now written with `newline="\n"` (and read through `tr -d '\r'`).
Batch 1 (cut + arms_fwd, 64 views): 3 shards, GPU 100 %, ~8 min. Batch 2 (step + head_up, 64 views) queued
to start the moment batch 1 finishes; masks downloaded per batch.

### Stretch poses for the fit and the tuck (2026-11-03)

The two-hand swing reaches past the 6 test poses (arms fully out and back while twisting): with the old
skin deletion that showed as holes at the lats and shoulders (f73 back, f109 front/back/side). Two jobs need
poses: SAM needs surface hidden at rest made visible (the 4 posed render sets cover it); the fit and the tuck
need the worst stretch the clips reach. `explode_common.stretch_poses`: arms overhead (150°), arms back 60°,
arms across the chest, swing back (twist −45° with arms out and back), swing forward (twist +45°, arms
forward), back arch, side bends ±25°; `fit_poses` = test + stretch, used by `fit_piece.py`, `--tuck`, and the
still check (14 poses × 4 sides). Trade-off: the plate comes out a little bulkier.

SAM done on both batches (128 posed views, 18,446 mask files in `views/masks`, no errors), 09:52.
Caught before labelling: posed cameras SAM never ran on (the +30° ring, 96 of them) would have counted as
"saw it, voted nothing" and diluted the votes → `explode_label.py` now leaves out every camera without masks.
Render time: a full check was ~55 min (≈900 frames × 4 views of a 1M-face figure on the GTX 1050, 3–6 s a
frame). `explode_pose.py` now renders only what is reviewed: 5 key frames per clip (from the every-3rd-frame grid, so
they match the earlier bare run frame for frame) and each sweep at start / middle / end, no GIFs → ~10 min,
mostly loading. `--gif` renders every 6th clip frame and 8 sweep steps and writes the GIFs (~25 min).
**Result of the posed views, and a correction (10:30).** `cut_d32_posed`: 183 cameras (55 rest + 128 posed),
5.4 % of faces changed vs `cut_d32_snap` — belt 17 %, skirt 11.5 %, leg_l 10.6 %, pauldrons ~9 % (the stride
pose), head 2.4 %, **torso only 1.7 % (and slightly smaller)**. `border_zoom.py --pose views/posed_cut_verts.npy`
(the cut shown on the arms-raised mesh, `BORDERS_armsup_snap_vs_posed.png`): the plate's side under the arm is
torso in BOTH cuts. **The earlier diagnosis "the torso has no side panel under the arm" was wrong.** The big
ring in the breastplate-alone views is the opening where the armoured arm and pauldron were fused to the
plate: it is as big as an armoured shoulder, and the bare barb's arm is far thinner, so a gap shows round it.
That is geometry, not segmentation; more SAM views cannot change it. (Also seen: the armoured mesh itself
tears a little at the armpit when posed — in the outfit, not in the breastplate-on-barb.)
Options for the opening: (1) the tuck fills the see-through with skin (gap reads as space between rim and
skin); (2) wear the pauldrons with the breastplate (they cover that opening in the full plate); (3) build plate
surface into the opening down to the bare arm's size.
Chain results (10:32): torso cleaned (330 holes → 124 left), fitted against the 14 fit poses, tucked
(74,503 skin verts, max 1.9 % h); stills 14 poses × 4 sides, sweeps (start/middle/end), two-hand swing and
overhead chop at 5 key frames. Sheets in `final_check_posed/`: `REVIEW_stills.png`, `stills/RISK_ZOOM.png`
(sides with arms stretched), `REVIEW_twohandswing.png`, `REVIEW_overheadchop.png`, `sweep/SWEEP_SHEET.png`.
**No see-through in any pose or clip frame from any side** — the holes at the lats and shoulders in the swing
(f37, f73, f109) are gone; the patchy lower back is gone. Left: the plate is bulkier (fitted to the stretch
extremes); through the shoulder opening his shoulder skin shows, a little creased where it was tucked; the
lower back below the plate is bare when he bends (no belt or skirt worn). The `anim_compare.py` step failed
on old leftover frames in the folder (not needed: review sheets are built from the 5 key frames).
Post-SAM chain (`scratchpad/chain_posed.ps1`, commands as above): label with posed views → `cut_d32_posed` →
cut and border comparisons → shells → clean/fill torso → fit (14 poses) → stills (14 × 4, tuck) → sweeps →
two-hand swing + overhead chop with tuck → `final_check_posed/`.

## All pieces: first, legs that move (2026-11-03)

- The "walk" clip was never a walk: in the source BVH the hips travel 1.6 cm and the knees bend ~5° over
  150 frames (a standing gesture clip). The retarget was fine (22 bones driven; his arms swing 39°, his legs
  1–2° because the source's do). Ranked all 40 `anunaki/bvh_all` clips by knee range (the thigh's ~359° is
  Euler wrap-around): jumpfar 137°, kneel 126°, leapattack 83°, jumpup 70°, backstep 66°, jokesillyrun 60°
  (a run, 8.8 m of travel). Taken for the leg pieces: **jokesillyrun, kneel, backstep** →
  `anim_test/retarget_legs/animated.blend`. Legs stride, kneel and step back (`final_check_legs/clips_bare/LEGS_CHECK.png`).
- New fault shown by the travelling clips: a long streak from his hips. 752 loincloth vertices of `barb_final`
  sat on glTF's `neutral_bone`, which nothing animates; standing clips hid it. `explode2/fix_neutral_bone.py`
  gives each the weights of its nearest vertex on real bones → `rigfix/barb_final_nb.glb` (the barb retarget
  target now points there; `barb_final.glb` untouched). Re-retargeted the 3 leg clips onto it: the streak is
  gone (`final_check_legs/clips_bare/LEGS_CHECK2.png`). From here the armour tests use `barb_final_nb.glb`.

Plan for the other pieces: (1) a general fit + tuck in world space per pose (any piece shape, rigid or
blended — the cylinder fit only suits upright pieces); (2) fit inner pieces first (leg plates before the
skirt, breastplate before the pauldrons); (3) every piece from the plain cut, cleaned + filled; thin plates
double-sided; (4) the full set and partial sets checked: 14 poses × 4 sides, sweeps, the clips incl. the 3 leg clips.

All 13 pieces of `cut_d32_posed` (head excluded: the barb keeps his own) cleaned + filled with
`hole_check.py --clean --fix` → `cut_d32_posed/shells_clean_all.glb` (`holes_posed_all/`, `diag_step9_holes_all.json`).
Holes left: boots 3 each, pauldrons 5/7, gauntlets 27/45, arms ~60–100, legs 67/63, belt 66, skirt ~150, torso 124.

`explode2/fit_set.py` (steps 11–12 for any piece): world space per fit pose (6 test + 8 stretch); everything as a
height above the posed skin (nearest body vertex and its normal). Fit inner first (legs, boots, arms, gauntlets,
torso, belt, skirt, pauldrons): a piece vertex stands GAP 0.5 % h above the skin and above inner pieces under it
(within 1.2 % h); the worst shortfall is spread over 1.2 % h (voxel max, so plate layers move together), smoothed,
pushed along the skin's rest normal. Tuck: covered skin (skin_bones) stays MARGIN 0.4 % h below the lowest piece
surface over it (piece vertices within 1.2 % h of its normal line) in every pose; pushed in, spread, smoothed.
Writes `parts_fit.glb` (materials double-sided) + `body_tucked.glb` + `fit_set.json`; weights are the shared
`explode_common.piece_weights` (same as `explode_pose --rigid`), skin bones `explode_common.skin_bones`.

Full set fitted (13 pieces, `fit_set_full/`, 436 s): push max — legs 1.1 / 0.7 % h, boots 1.5 / 1.7, arms 3.4 /
4.6, gauntlets 1.5 / 1.7, torso 3.4, belt 2.0, skirt 3.3, pauldrons 3.9 / 6.1 (they clear the breastplate as well
as the body). Tuck with the whole set on: 587,300 of 712,855 skin verts pushed in, max 5.1 % h. A glTF round trip
splits vertices (712,855 → 717,685), so the tuck is saved as `tuck_offsets.npz` (rest position → offset) and
`explode_pose.py --tuck-from` applies it to any copy of the body by position (the animated.blends too).
Check running: `final_check_full/` — 14 stills × 4 sides, sweeps, swing + chop, run + kneel + backstep.

**First full-set result was wrong** (`final_check_full/REVIEW_stills.png`, 1st run): the whole figure skin-orange
with grey patches. Not the texture (parts_fit.glb carries the grey steel atlas, mean rgb 0.31). The body is a
shell: signed volume positive (outward winding) but only 49.8 % of the chest's vertex normals point out — an
inner layer facing the cavity. fit_set took the inner layer as skin: armour heights against it came out
negative (nearly every piece vertex "too close", even at rest) and the tuck's "push inward along the normal"
moved the inner layer OUT through the skin. Fix: `fit_set.py` classes the outer skin as the vertices that can
see out of the body in one of 5 directions round their normal (armpit skin's straight-out ray hits the arm,
a tilted one escapes; the inner layer never escapes); every skin lookup uses the outer skin only, and each
inner-layer vertex moves with its nearest outer vertex (same push, same direction), so the shell moves as one.
Re-fit + re-check running.

**Re-fit (359 s):** outer skin 318,336 verts (44.7 %), inner layer 394,519. Push max: legs 2.5, boots 2.5, arms
5.1 / 6.3, gauntlets 1.7, torso 4.9, belt 3.0, skirt 5.7, pauldrons 5.2 / 4.6 % h. Tuck at rest: 88,455 skin verts
(was 447,308 with the inner layer mistaken for skin); 524,443 moved in total, max 5.3 % h.
**Result** (`final_check_full/`: `REVIEW_stills.png` 14 × 4, `REVIEW_swing_chop.png`, `REVIEW_run_kneel_backstep.png`,
close-ups `stills/PATCH_ZOOM.png`, `LEGS_ZOOM.png`): the whole set reads as a suit of plate in every pose and clip
and follows the run, kneel, backstep, swing and chop. Faults:
1. **Skin between pieces at the joints when they move:** shoulder/deltoid between pauldron and breastplate with
   the arms up, across or swung back; backs of the thighs / seat between skirt and leg plates in the kneel and
   backstep. No piece covers that skin in those poses, so nothing tucks it.
2. **The barb's loincloth shows through the skirt's centre gap** front and back (cloth between the tassets).
3. **A stray dark bar** sticking out at shoulder height in the backstep (one piece's vertices stretched).
Ideas: an under-layer (skin the worn set covers painted as dark padding, so joint gaps read as gambeson, as
games do); pauldrons weighted more to the upper arm so they ride up with it; find the stretched vertices.

**Which faults come from which step (2026-11-04).** `PROOF_paint_and_gaps.png`: the left gauntlet alone (no body)
is skin-orange → its paint (Nano drew thin steel fingers with orange gaps; the painted model had the orange hand
before any SAM; flagged on 2026-11-02 as `--redo hand_l_out`). `ORANGE_SPLIT.png`: the same 14 poses × 4 sides
armour-only (`explode_pose --hide-body`) vs with body; warm orange in the armour-only image = paint (yellow),
orange only with the body = skin showing (red):
| fault | root | step |
|---|---|---|
| orange left gauntlet | paint | 1 |
| orange at the boots / ankles | his feet showing through the sabatons (red, not paint) | 11–12 (tuck/fit at the feet) |
| skin at the shoulders with arms up / across / swung | rigid pieces part at the shoulder | 10 (weights) / coverage |
| skin at the seat / backs of thighs in the kneel | same at the hips | 10 / coverage |
| loincloth in the skirt's centre gap | the barb's own loincloth in a real skirt opening | under-layer / hide |
| stray bar in the backstep | stretched vertices in one piece | 10 (weights) |
| ragged rims, small holes | cut + TRELLIS mesh | 7 / 9 |
| face red in the split | his own bare head — correct | — |
So paint explains the gauntlet only.

Left hand repainted with Nano (`repaint.py gen <paint> <ref> hand_l_out`, $0.039): attempt_3, aligns (ecc 0.959,
scale 1.00), every finger steel with dark gaps, no orange (only the leather strap at the wrist)
(`paint/gen/hand_l_out/_compare.png`). Then, all local: project → shells from `cut_d32_posed` (the cut is on mesh
faces, so no SAM/HoloPart re-run) → clean all → fit_set → stills (`scratchpad/chain_hand.ps1`).

**The gauntlet stayed orange from the front** (`final_check_full/GAUNTLET_FIX.png`). The pieces did carry the new
texture (merge ran, files fresh). The orange came from another painting: the `leg_l_front` close-up frames the
left hand hanging into its top corner, Nano painted that hand bare skin, and close-ups override the body views
(all of which painted steel gauntlets) — `paint/_hand_sources.png`. So repainting hand_l_out could never fix it.
Fix (general, any outfit): `repaint.py project <glb> <work> [roles.json]` — with the roles, each close-up paints
only pixels whose main bone (a per-camera bone-id render from the outfit's step-0 weights) is in its own region:
face/head → head (+children) and neck; hand → forearm + hand (+fingers); arm → clavicle, upper arm, forearm;
leg → thigh, shin, foot bone; foot → foot (+toes); chest → spine, spine2, chest, neck, clavicles; pelvis → root,
spine, thighs; legs → root + both legs. The log line per close-up reports the pixels dropped as outside its region.
Re-projection + rebuild running (`scratchpad/chain_region.ps1`).
Result (592 s projection): 13 regions; e.g. leg_l_front dropped 184,281 px outside the leg (the hand among them),
hand_l_out 393,218 px of hip and skirt in its frame, arm_l_out 127,308, legs_back 45,768. **The left gauntlet is
steel from front, side, 3/4 and arm raised** (`final_check_full/GAUNTLET_FIX_region.png`); a few orange specks left
at one fingertip / the palm edge. `paint_outfit.py` now passes roles.json to project when given.

Final check of this version in `final_check_full2/` (the previous one kept in `final_check_full/`): `OVERVIEW_final.png`,
`REVIEW_stills.png` (14 × 4), `REVIEW_swing_chop.png`, `REVIEW_run_kneel_backstep.png`, `sweep/SWEEP_SHEET.png`. Both
gauntlets steel now. Left exactly as listed before: skin at the shoulders when the arms go overhead / swing / chop,
the seat in the kneel, the loincloth in the skirt's centre gap, his feet at the boots, the bar in the backstep.
Undergarment plan (black gambeson + hose as a body-texture variant first, a garment mesh only if needed): `PLAN.md`.

**Mistake: "under control" was judged by eye** on a few sheets, and the user found the same skin faults still
there (shoulders, seat, feet, loincloth). From here the skin is measured, not eyeballed:
`explode_pose.py --mask --hide-head` renders flat colours with no anti-aliasing (body pure green, every piece grey,
black background) with his head and neck taken out (his bare head is meant to show), and `explode2/skin_metric.py`
counts the green: body showing as a % of the figure per image, the mean, per view, the worst ten, and a sheet
with the body in red (`SKIN.png`, `skin.json`). Measured over the 14 fit poses × 4 sides and the 5 clips' key
frames × 4 sides (`scratchpad/skin_base.ps1 <fit_dir> <name>` → `fullplate/skin_metric/<name>/`).

**Baseline, `fit_set_full` (stills, `skin_metric/base/SKIN_stills.png`): 4.24 % of the figure is his body, mean
over 56 images, every one of them above 0.05 %.** Per view: front 4.89, back 4.85, 3/4 4.13, side 3.09 %. Worst:
arms_overhead side 11.6 (lat/armpit under the raised arm), swing_back back 7.7, swing_fwd front 7.1, swing_fwd 3/4
6.7, arms_across back 6.6, arms_overhead 3/4 6.4. Present in every pose, even at rest (rest front 4.26 %): a large
patch at the crotch front and back (the skirt's centre gap), both shins where the greave meets the boot, the
fingertips, speckles through small holes in the plates. The arm poses add the shoulder / armpit / lat.
(A mistake on the way: I changed the pauldron weights while the baseline clips were about to start, which would
have rendered the old fit with new weights; stopped, put 0.5 back for the baseline, re-ran the clips.)
Clips (5 key frames × 4 sides of swing, chop, run, kneel, backstep; 100 images): 5.31 %; worst kneel 0088 front 12.4,
chop 0073 3/4 11.9, kneel 0118 front 11.4, backstep 0025 front 11.4. **Whole baseline: 4.93 % over 156 images**
(front 5.95, 3/4 5.12, back 4.91, side 3.74) — `skin_metric/base/SKIN.png`, `skin.json`. Render + count 423 s
for the clips, ~2 min for the stills.

Which step uncovers it (`scratchpad/skin_stages.ps1`, `explode2/skin_stages.py`): the same untucked body, head
hidden, under the armour after each step — the whole painted outfit (`fullplate_rigged.glb`), HoloPart's raw
output (`holopart_d32_gate/output.glb`), the cut (`shells_parts.glb`), cleaned (`shells_clean_all.glb`), fitted
(`parts_fit.glb`); per stage the rest pose from 4 sides, yellow = body this step uncovered. Suspect: `hole_check
--clean` strips faces with 2+ open edges (3 passes) and pulls rim vertices inward, so on a seam two pieces share,
both lose a strip — a gap even at rest.
**Result: inconclusive for the early stages** — the untucked bare barb is bulkier than the painted outfit and pokes
through every unfitted stage (orig 54.8 %, HoloPart 73.7 %, cut 58.3 %, clean 58.5 % at rest), so only the fitted
stage compares (2.57 % at rest untucked). It showed something else: **the tuck made the rest pose worse** (tucked 3.27 %
vs untucked 2.57 %, `scratchpad/tuck_vs_untucked.png`): at the crotch the tucked body shows more. The loincloth is
a thin flap, both faces outer skin; each was pushed in along its own normal, so the back face went forward,
through the front face and out past the skirt. At the collar the tuck works (skin there only when untucked).

**Why the body shows — split by depth.** A flat armour-only render cannot tell poke-through from an opening: through
a hole you see the far side of the armour. `explode_pose --mask` now casts each visible body pixel's camera ray on
past the body (`split_mask`): armour within 2 % h behind = poking through (green → red on the sheet), none = an
opening / hole (cyan → blue). (First I read "armour anywhere behind" as poke-through and said 4.07 of the 4.34 %
was the tuck's — wrong for that reason; corrected before acting on it.) Also from now on the render uses the
pauldron split the fit used (`fit_set.json` "pauldron_arm"; older fits: 0.5), so a weight change can no longer
mix into a check of an old fit.
**Baseline stills: 4.24 % = poking through 2.42 % + openings 1.82 %** (`skin_metric/base/SKIN_stills.png`).
Poking through (tuck): the crotch / loincloth in every pose, fingertips, boot fronts and toes, shin spots.
Openings (coverage / cut): shoulders, armpits and lats with the arms moving (arms_overhead side 10.9 % of 11.6),
the collar when he bends, pinholes in the plates.

Tuck fixes (`fit_set.py`): (1) the push after smoothing never drops below a vertex's own need (6 averaging passes
thinned small spots); (2) faces whose normal points at their bone (flap backs) are pushed towards the bone; (3) the
armour over a skin vertex is searched along its whole normal line, 3 % h below to the margin above (samples every
0.6 % h, 8 nearest armour vertices each, within 1.2 % h of the line), not only the 32 armour vertices nearest the
skin point (those sat on the nearest plate edge, so the plate behind was missed); (4) fingers covered; (5) a check
after the tuck: the tucked body posed again, covered skin still in front of armour counted per pose. Pauldron
weights 0.75 upper arm / 0.25 collarbone (`explode_common.PAULDRON_ARM`).

**Full baseline with the split: 4.93 % = poking through 2.51 % + openings 2.42 %** (156 images; kneel 0088 front 12.4
= 5.1 + 7.4, chop 0073 3/4 11.9 = 2.7 + 9.2, arms_overhead side 11.6 = 0.8 + 10.9, backstep 0025 front 11.4 = 4.0 + 7.4).

Re-fit with the tuck fixes → `fit_set_full2/` (562 s): tuck on 27 bones (fingers in), 27,602 flap-back verts pushed
towards their bone, 548,834 skin verts pushed in, max 3.40 % h (was 5.34). The fit's own check still counts ~53k
covered skin verts in front of armour at rest (72k arms overhead) — partly the check's own blind spot (skin pushed
in comes within 3 % h of the far side of the same thin part); the image count decides.

**The breastplate has no side panel** (`skin_metric/torso_alone/`, `skin_metric/HOLO_SIDE_torso.png`, new
`explode2/holo_side.py`): alone with the body hidden it shows a large hole down its side under the raised arm.
The cut torso's armhole is an oval from the shoulder to the lower ribs with a ragged notch at its foot — the
footprint where the arm was fused to the torso in the painted model (at rest no surface existed between them).
HoloPart's completed torso keeps the same armhole, a little smaller, and is a stair-stepped voxel surface: it
treats the armhole as an opening, so HoloPart cannot supply that surface either. Needed: our own step that
covers the torso skin inside the armhole outline with plate (just above the skin, the torso's steel, on the
chest bone) — the main "opening" in the arm poses.

**v2 (`skin_metric/v2/`): 4.90 % = through 2.39 + openings 2.51 — no real gain over 4.93.** Per view the back got
better (poking through −1.63) and the side worse (+1.79): `scratchpad/side_v2.png` — the hands now poke out of
the gauntlets. The 3 % h search along the normal found the gauntlet's back plate behind a finger (a finger is
thinner than that) and pushed the finger skin through the finger and out. Fix: armour counts for a skin vertex
only if the skin it sits over (its nearest outer skin vertex) faces the same way (`lowest_armour`, normals' dot
> 0). Same problem from the other side for thin flaps: the loincloth's front face goes behind the crotch armour but
its back face finds no armour of its own and stays in front — flap backs now take the push of the nearest front
face. v3 running (`fit_set_full3/`, `skin_metric/v3/`).

**v3: 4.19 % = through 1.94 + openings 2.25** (base 4.93 = 2.51 + 2.42). The loincloth patch at the crotch is mostly
gone; the hands got worse than base (red / blue at the gauntlet cuffs); the red spots on both shins did not change.
Probed instead of guessed — `explode2/skin_probe.py <base> <fit_dir> <view> <label>:<x0,y0,x1,y1> ...` casts each
pixel's ray at rest and reports the body vertex hit (main bone, tuck offset, outer skin or not, normal facing) and
the armour next behind it (piece, distance, its triangle's longest edge):
- hands (v3): finger bones 18/19, tuck moved them a median 3.35 % h, **2.77 % h outward along the normal**; 99 px with
  no gauntlet behind at all. The "normal faces the bone → push towards the bone" rule fired on fingers: the finger
  bones do not run inside the fingers, so "towards the bone" was out of the gauntlet.
- crotch (v3): root bone, pushed 3.39 % h = the search depth limit (3 % h + margin), still 0.67 % h in front of the
  skirt / belt: the loincloth hangs more than 3 % h in front of the crotch plates.
- shins (same in base and v3): knee / ankle bones, outer skin, normals correct, leg plate 0.58 % h behind, but the
  tuck moved them 0.07 % h. **The armour triangles behind have longest edges of 4.6 % h** (median; crotch 2.8 %;
  TRELLIS edges are ~0.2–0.3 % h). (Corrected 2026-11-05: not `hole_check`'s caps — triangles over 2 % h before the
  fit: legs 0 / 0, after: 501 / 383; the fit's per-vertex push stretched them.) The tuck looks for armour vertices,
  so a stretched triangle's middle was not seen, and the shin bulged through it.
v4 (`fit_set.py`): (1) refine — every worn piece's edges over 0.6 % h split (UVs interpolated) before anything
else; (2) thin sheets found by thickness (another outer face, facing away, within 0.6 % h straight behind), not by
bone direction: the fit ignores them (cloth to squash, not skin for the armour to clear), the tuck searches them
8 % h deep, a sheet's back counts "out" against its own normal and moves with the front face across from it; the
skin an armour point sits over is looked up without sheets; (3) `--cover` (step 0): plate over the skin a piece
encloses — around its main axis (1 % h × 5° cells) a cell with piece surface above and below in that direction but
none in it; outer skin there on the piece's own bones, not neck / head, not a sheet, with no piece over it that moves
with it (the arm plate over the lat at rest does not count), copied + grown 3 rings under the rim, GAP above the
skin, each face in the colour of the nearest piece vertex; then fitted with the piece.
**v4 result: 13.65 % (through 4.65 + openings 9.00) — three times worse. Its code (refine, sheets, --cover) was
removed and `fit_set.py` is back to v3 (4.19 %, `fit_set_full3/`, `skin_metric/v3/`).** Also removed as one-off
debris: `skin_stages.py`, `holo_side.py`, the v2 / v4 / stages / torso_alone outputs. Overall this round (base 4.93 →
v3 4.19 %) was a poor return for the time spent.

**Causes, checked (2026-11-05, `fullplate/SKIN_CAUSES.png`):** all four left are the fit / tuck / weights, none paint.
Shins: the fit stretches the plates (triangles over 2 % h before → after: legs 0 → 501 / 383, skirt 2 → 11,811,
torso 9 → 4,402, arms 7 / 0 → 2,900 / 2,410). Loincloth: in front of the skirt, the tuck did not reach it. Kneel:
skin through the thigh plate that is there — no kneel among the fit poses. Backstep bar: arm_r, 232 vertices by the
wrist on the upper-arm bone (arm_l: 0). Outside both kinds: the breastplate's armhole (no side panel).
**Decision (his):** `fit_set.py`'s per-vertex push bends the armour — overengineered, not reliable. Kept as an
option only; to be replaced by a fit that never changes a piece's shape.

**State without fit_set (2026-11-07, `fullplate/nofit_check/`, 669 s):** the 13 pieces of
`cut_d32_posed/shells_clean_all.glb` exactly as cut, `--rigid`, no fit, no tuck, on `barb_final_nb.glb`; stills (14 poses
× 4 sides), the 5 clips, the bare barb and the armour alone (`scratchpad/nofit.ps1`, sheets `nofit_sheets.py`):
`NOFIT_1_start.png` (concepts, 3D barb, pieces, worn at rest), `NOFIT_2_poses.png`, `NOFIT_3_clips.png`.
Even at rest his skin covers most of the armour: the pieces sit inside his body (the fit had pushed them out up
to legs 2.5, torso 4.9, skirt 5.7, arms 5.1 / 6.3 % h). The armour mesh is slimmer than the bare barb's body, so a
size fit is needed in any approach; movement is not the first problem.
Measured (rest, `scratchpad/size_cmp.py`): outer widths match within ~1–2 % h (chest W 41.8 armour vs 43.3 body, D 18.5
vs 19.4). **Could one whole-piece scale fix it?** (`scratchpad/scale_need.py`: per piece, about its own axis — vertical
for torso / belt / skirt, else its long axis — in 1 % h × 10° patches, skin radius ÷ armour radius, skin on the
piece's `skin_bones` only): median 0.93–1.07 (same size), but skin out in 39–72 % of patches; p90 1.21–1.37 (pauldrons
2.7), p98 1.44–1.70. One scale that covers him makes each piece 20–60 % too big elsewhere: the mismatch is shape
(his muscles bulge where the plates don't), not size.
**Where it starts: the 2D concepts** (`fullplate/CONCEPT_OUTLINE.png`; grey both, red bare body outside the armour,
blue armour outside the body): `gear_test/in/barb_fullplate.png` traces `barb_base.png`'s outline — same height (985 /
986 px), widths within ~1 % h (chest armour 40.3 vs bare 41.3, hips 57.0 vs 57.2, thigh 27.9 vs 28.0); red at the lats,
forearms, outer thighs. The image model drew the plate on the skin with no thickness; the 3D gen kept that.
Sources (not logged before; found from the 2026-10-31 cutout commands, `cutout_white.py <jpg> <png>`), both his gens
with gpt-image-2.5 "flare", in `C:\Users\Douglas\Downloads\`:
- bare → `gear_test/in/barb_base.png`: `gpt-image-2.5-flare_Professional_graphic_design_2D_illustration_Full-body_3D_character_model_render_-0.jpg`
- full plate → `gear_test/in/barb_fullplate.png`: `gpt-image-2.5-flare_concept_design_sheet_1.4_concept_art_Fitted_steel_plate_armour_that_follows_his_-0.jpg`
  (its prompt began "Fitted steel plate armour that follows his …": it asked for a tight fit)
- breastplate → `gear_test/in/barb_breastplate.png`: `gpt-image-2.5-flare_concept_design_sheet_1.4_concept_art_Polished_steel_breastplate_covering_his_che-0.jpg`

**New concepts (2026-11-07)**, his gens, gpt-image-2.5 flare, edit of the bare jpg, prompt "Dress this exact man in a full
suit of steel plate armour worn over a thick padded gambeson … every plate stands clear of the skin … if unsure, slightly
too big". Three quality settings; the file names do not say which (`-0`, `-0 (1)`, `-0 (2)`, 1024², no metadata), taken
in download order → `gear_test/in/fullplate_tests/flare_1_high.jpg`, `flare_2_higher.jpg`, `flare_3_extrahigh.jpg`.
`outline_check.py` (margin 0.5 % h), sheet `fullplate_tests/CHECK_SHEET.png`:
| image | fail % of bare outline | shoulder / chest / hips width (% h; bare 34.1 / 41.3 / 57.2) |
|---|---|---|
| old fitted (`barb_fullplate.png`) | 7.21 | 35.7 / 40.2 / 56.9 |
| 1 high | 5.74 | 39.2 / 43.5 / 58.3 |
| 2 higher | 3.95 | 38.3 / 43.8 / 55.9 |
| 3 extra high | **2.40** | 38.8 / 42.8 / 57.8 |
Extra high: what is left red — hands (gauntlets ≈ his hands, ~36 % of the red), soles (feet on the floor, not a fault,
~19 %), inner arms by the armpits, a little at the crotch.
4th, "3D render" style added to the prompt (`flare_4_3drender.jpg`, `CHECK_SHEET_2.png`): **3.95 %** (shoulder / chest /
hips 38.8 / 43.7 / 58.3); extra red at the crotch (his loincloth below where the armour's legs part), else as 3.

**3D check before any cut** — `explode2/shell_check.py <base> <roles> <outfit_aligned.glb> --json` (local, 52 s): 1 in 4
outer-skin verts (head / neck out), a ray out along the normal; inside = it leaves an outward outfit face within 3 % h.
Old armour (`fullplate/fullplate_rigged.glb`, `shell_check_v1.json`): **57.0 % of his skin OUT** (torso 66.8, upper
arm 61.5, forearm 48.5, hands 53.2, thigh 55.8, shin 54.5, feet 44.5); where inside, the plate stands off 0.45 % h median.

**TRELLIS.2 for `flare_3_extrahigh`** (cut out → `gear_test/in/barb_fullplate_v2.png`, `cutout_white.py`): pod
A6000 48 GB, 50 GB disk, torch 2.8.0+cu128, direct IP (scp). `trellis2_setup.sh` with MAX_JOBS=4 (64 cores);
`TRELLIS.2-4B` pulled in parallel from the venv (7.1 GB in 20 s).
HF token piped from his clipboard (first try 40 bytes: PowerShell's BOM — `tr -cd 'A-Za-z0-9_'` fixed it, PROCESS.md §7);
whoami 200, `facebook/dinov3-vitl16-pretrain-lvd1689m` 200, pre-downloaded. `run_v2.sh` (scratchpad) waits for the
install, then `trellis2_run.py --image /workspace/in/barb_fullplate_v2.png --name barb_fullplate_v2 --skip-texture`
(same settings as 2026-10-31).
Install 13:07 → INSTALL_OK; TRELLIS 13:09:33 → 13:20:47, exit 0, `barb_fullplate_v2_from_front.glb` 57.4 MB →
`gear_test/`. Pod stopped after the pull. Local (`scratchpad/after_v2.sh`, 245 s): `outfit_skeleton.py` onto
`barb_final` → `explode2/fullplate_v2/fullplate_rigged.glb` (scale 0.9991, head residual 0.27 % h); `shell_check.py`
→ `shell_check_v2.json`: **32.4 % of his skin OUT (v1 57.0)** — torso 30.5, upper arm 22.0, forearm 6.9, hands 44.6,
thigh 37.6, shin 36.0, feet 38.9; stand-off 0.76 % h median (v1 0.45). `WORN_OLD_VS_NEW.png` (body orange, armour grey,
rest, 4 views): the front is nearly all plate (left: the upper pecs above the breastplate, the loincloth in the skirt
gap); the back is poor — lats / upper back, backs of the thighs and calves. The concept shows only the front, so the
2D check could not see the back and TRELLIS made it slim.
Measured why: TRELLIS widens bare and armour alike (chest image → 3D: bare 41.3 → 43.3, old 40.2 → 41.8, new 42.8 →
46.2 % h); aligned by the head, the new armour stands 1.6–4.7 % h in front of him but only 0.4–1.4 % h behind the
torso and 1.5 % h inside at the backs of the thighs / knees (its bulk is in front). TRELLIS.2 is single-image
(multi-image only in unmerged community PR #104).
**Decision (his, 2026-11-07):** fitting a separately generated garment afterwards (placement by measurement, whole-
piece scale, multi-image TRELLIS) is not general — not pursued. A general process must build the garment on his body.
**How far out is the skin that is out?** `shell_check.py` now also gives, for OUT skin, the distance to the nearest
outfit surface, and the OUT share left if the outfit grew by 0.5 / 1 / 2 % h (rest; optimistic at openings, where
growing an edge does not close the gap):
| | OUT % | OUT by p50 / p90 (% h) | left if grown 0.5 / 1 / 2 % h |
|---|---|---|---|
| old armour | 57.0 | 0.51 / 1.27 | 29.1 / 10.9 / 0.1 |
| new armour | 32.4 | 0.51 / 1.66 | 16.4 / 6.7 / 2.6 (thighs 8.6: crotch / loincloth) |
The skin is out by little: ~1–2 % h of growth covers nearly all of it, even on the old armour.

**Buffer test (2026-11-07, his go), old armour's 13 pieces** — `explode2/buffer_set.py <base> <roles> <parts> <out>
[--cover 98 --margin 0.001 --cap 0.02]` (29 s): per piece, at rest, the skin under it (outer skin on its
`skin_bones`, within 3 % h) needs growth = distance to the piece + margin where not covered; buffer = 98th percentile,
capped at 2 % h; every vertex moves by it along its own normal turned away from the skin (both layers out, shape
and thickness kept). `fullplate/buffer_set/parts_buffer.glb` + `buffer.json`. Covered before → buffer → after (estimate):
arms 37–39 % → 2 (cap) → 93–95 %; belt 21 → 2 → 85; boots 48 → 2 / 1.78 → 97–98; gauntlets 36 → 2 → 93–95; legs 30 / 43 → 2
→ 89 / 92; pauldrons 20–21 → 2 → 77–80; skirt 33 → 2 → 96; torso 22 → 2 → 93. All but boot_r hit the cap.
Renders (`scratchpad/buffer_test.ps1`): mask stills + 5 clips → `skin_metric/buffer`, textured stills →
`buffer_set/stills`, then the same mask set unbuffered → `skin_metric/nofit` (both without tuck).
**Result (1,415 s):** visible skin, 156 images — unbuffered 55.45 % (through 39.92 + openings 15.53), **buffer 21.71 %**
(11.70 + 10.01); fit_set + tuck was 4.93. Rest only: 58.5 → 22.7 (fit_set 3.3). `buffer_set/BUFFER_TEST.png`: the
buffered plates are **lumpy blobs** — moving each vertex 2 % h along its own normal on TRELLIS's noisy surfaces
(edges ~0.2–0.3 % h) is not an even growth; the chest still shows (blue: the breastplate sits more than 2 % h inside
his pecs). The estimate in buffer_set (~90 % covered) was far off the render. Not a working method as written.

**Multi-view TRELLIS.2, researched (2026-11-07):** (1) microsoft/TRELLIS.2 PR #104 (open, unmerged): 2–8 unposed views,
each view's prediction averaged over the whole model at all three stages; author + a commenter report shapes "fatter or
thinner than expected"; no measurements. (2) visualbruno/ComfyUI-Trellis2 (MIT) `run_multiview` (front / back / left /
right slots): at every denoising step, each view's prediction is weighted per voxel by a softmax over the voxel's
position along a fixed axis (front = +z half, back = −z half, `front_axis` z or x, `blend_temperature` 2.0) — sparse
structure, shape and texture stages; ~400 lines to port onto stock TRELLIS.2, no new packages. (2) is "make a front
and a back model and merge them" done inside the generation (one shared model, no seams). No user-reported results
for either beyond the fat/thin report. A post-hoc merge of two finished meshes would add seams and alignment — worse.
Code read (visualbruno b0e84c0, cloned to scratchpad/ext/vb; stock microsoft/TRELLIS.2 to ext/t2): **the pack's
front/back axis is wrong for TRELLIS.2.** Stock voxel coords are `argwhere(decoded)[:, [0,2,3,4]]` → (D, H, W) = (x, y,
z), positions `coords/res − 0.5`; `to_glb` writes (x, z, −y) and Blender's import undoes it, so Blender frame =
TRELLIS frame, and our three meshes all face −y. The pack weights views along coords[:,1] / D (x: his left–right,
`front_axis='z'`) or coords[:,3] / W (z: up–down, `'x'`) — never y. Fix: front = −y, back = +y (H / coords[:,2]); his
right = −x. The pack's `trellis2` package is a heavily modified copy that imports ComfyUI (`folder_paths`,
`comfy.utils`) — not usable as-is; porting its multi-view sampler + `run_multiview` (~300–400 lines, no texture) onto
stock TRELLIS.2 with the axis fixed is the clean route.
Also: the pack's blend `softmax(2 · pos[-1, 1])` gives the front image only ~70 % at the chest surface of a body
~0.2 deep (near plain averaging).
**Port written (local, untested — no torch here):** `gpu_box/trellis2_multiview.py` (`MultiViewSampler`: per step,
per view `_inference_model` with that view's cond / neg_cond, blended per voxel by softmax(signed position / BAND),
front = −y, back = +y, right = −x, left = +x, BAND 0.03 object units → ~96 % at the surface; one sampler serves the
512 and 1024 stages via id(front cond); `run_multiview` = stock 1024_cascade with the samplers swapped; texture from
the front view only) + `gpu_box/trellis2_mv_run.py` (same export as trellis2_run.py). Plan on the pod: (1) stock
`trellis2_run.py` on the back image alone — which way does he face? (front-facing −y = TRELLIS works in the object's
frame, the method holds); (2) front + back with the port; 3D check vs 32.4 %.
`explode2/body_silhouette.py <base> <out> [views]`: his real body's silhouette (front / back / left / right) as the bare
reference for `outline_check.py`. Against it, `flare_3_extrahigh` fails **6.67 %** (2.40 % against the 2D bare concept):
TRELLIS made his body ~2 % h wider than its concept, so the 3D body is the reference from now on.
**Pod 2 (multi-view test):** RTX PRO 4000 Blackwell, 24 GB, compute 12.0 (no Ampere / Ada card offered; a 5080 at 16 GB
refused — PROCESS.md §6: 24 GB-class minimum). torch 2.8.0+cu128, 50 GB, 48 cores, direct IP. `trellis2_setup.sh`
with **TORCH_CUDA_ARCH_LIST=12.0** (Blackwell), MAX_JOBS=4; token by clipboard (37 bytes, whoami 200, DINOv3 200).
`scratchpad/mv_chain.sh` on the pod: models in parallel → INSTALL_OK → flash-attn varlen smoke test on the card
(the prebuilt wheel may lack Blackwell kernels) → waits for `in/barb_fullplate_v2_back.png` → back-only stock run
(orientation) → front + back `trellis2_mv_run.py`.
16:43 INSTALL_OK on Blackwell, **flash-attn varlen OK on the RTX PRO 4000 (sm_120)**, models downloaded.
**Port self-test while waiting for the back image:** `trellis2_mv_run.py --front` only → 3,231,385 verts / 7,508,208
faces, 50.9 MB GLB; stock `trellis2_run.py` on the same image and pod → **the same 3,231,385 / 7,508,208**: with one view
the port reproduces the stock generation (sparse-structure 12 steps in 4 s). On pod 1 (A6000) the same image gave a
57.4 MB GLB — GPUs differ. 3D check of the port's mesh (`explode2/mv_test/frontonly/`): **30.8 % OUT** (pod 1: 32.4).
`outfit_skeleton.py` bone heat failed on this mesh (proxy 69 islands, every proxy vert unweighted) — added
`--align-only` (alignment alone, for `shell_check.py`); the rig failure is a separate problem for later.
**Back view** (his gen, gpt-image-2.5 flare, my back-view prompt on `flare_3_extrahigh.jpg` →
`fullplate_tests/flare_3_back.jpg`, cut out → `gear_test/in/barb_fullplate_v2_back.png`): same design and pose;
`outline_check` against his body from behind (`body_sil/body_back.png`) **10.07 %** (front 6.67 %), extra red where the
arms are held at a slightly different angle and at the crotch (`BACK_CHECK.png`).
**Orientation test passed** (`gear_test/mv_test/ORIENTATION.png`): stock TRELLIS.2 on the back image alone (17:11–17:14,
pod 2) builds him facing −y like the front run — the backplate from the image at +y, an invented beardless face at −y.
TRELLIS works in the object's frame, so the front / back blend lines up. (The toe test, `scratchpad/facing.py`, was
borderline on this mesh: −0.19 % h vs −3 … −8 % on the front meshes — the renders settle it.)
**Front + back result (17:14–17:18, 3,159,740 verts, 52.3 MB; pod stopped after the pull) — worse.** `shell_check`
(now also split by which way the skin faces, |n_y| > 0.3):
| mesh | OUT % | front-facing | side-facing | back-facing |
|---|---|---|---|---|
| front image only (`mv_test/frontonly`) | 30.8 | 19.7 | 29.5 | 43.4 |
| front + back (`mv_test/mv`, BAND 0.03) | **38.0** | 25.2 | 35.4 | 53.1 |
| back image only (`mv_test/backonly`) | 46.2 | | | |
`mv_test/WORN_FRONT_VS_FRONTBACK.png`: the backs of the thighs are now covered, but the upper back, the arms and the
sides show more skin. Why (my reading): a back image, like a front one, looks along the front–back axis, so it gives
the back's look, not how deep he is — depth shows only from the side, and the position blend gives a side view a say
only over his outer sides. So this method does not fix depth.
**The back view was bad (his catch):** only the head and upper back were from behind; knee guards, shin ridges,
sabatons and gauntlet fronts all faced the camera — TRELLIS got a front lower body for the back half. The test was not
fair. **Back view 2 (2026-11-08)**, tighter prompt (backs of the knees, calves in rear greaves, heels, toes away) →
`fullplate_tests/flare_3_back2.jpg`: a true back view; `outline_check` vs his back 11.16 % (back 1: 10.07). Cut out →
`gear_test/in/barb_fullplate_v2_back2.png`. `scratchpad/mv2_chain.sh` for a fresh pod: install with
TORCH_CUDA_ARCH_LIST from the GPU's own compute capability, models once the token is there, flash-attn check, then
front + back2 `trellis2_mv_run.py` (BAND 0.03, seed 0).
Back 2's arms were held at a different angle from the front's. **Back view 3**: Leonardo **Nano Banana 2.1**, style
None, prompt enhance off, 1:1, two inputs — Image 1 `flare_3_extrahigh.jpg`, Image 2 `flare_3_back_outline.png` (the
front cut-out flipped left–right as a black silhouette: from straight behind his outline is the front's mirror; the
flipped photo was dropped because it still shows his face) — prompt "Draw the man in Image 1 seen from behind. Image 2
is his exact outline from behind: fill it exactly, with the same pose, size and position, nothing outside it and no
gaps. Show his back, hair bun, backplate, the backs of his arms, legs and heels. Same armour, white background." →
`fullplate_tests/nb21_back3.jpg`. Outline vs the target (front flipped), IoU: **back3 0.968**, back1 0.929, back2
0.919; widths at shoulder / chest / waist / hips / thighs / calves within 0.3 % h of the target; only the heels differ
(`BACK3_CHECK.png`). vs his body from behind: 6.48 % (front 6.67). A true back view. Cut out →
`gear_test/in/barb_fullplate_v2_back3.png`; `mv2_chain.sh` now runs front + back3 (`barb_fullplate_v2_mv3`).
**View gate (2026-11-08)**, branch `feat/view-shape-gate` (worktree `C:\Users\Douglas\Pixel-Realm-view-gate`, plan
`.cursor/plans/view_shape_gate.plan.md`): `python -m tools.boss_sprite_pipeline.view_gate --front <front> --out <dir>`
draws the back through Leonardo's API (`google/nano-banana-2.1`, quantity 1) with the front's mirrored outline as
image 2, scores IoU + bands, `[r1]` redraws with the miss marked; accept writes `front.png` / `back.png` cut out for
TRELLIS. Run on `flare_3_extrahigh.jpg` → `gear_test/view_gate_test/`: 4 attempts (2 via r1), all PASS (IoU 0.966–
0.973); accepted attempt 4: IoU 0.973, every band within 0.3 % h, a true back view. `mv2_chain.sh` now runs front +
back from the gate (`/workspace/in/gate_front.png`, `gate_back.png` → `barb_fullplate_v2_gate_mv`).
**Front + gated back on TRELLIS (pod 3: A40 48 GB, 2026-11-08, install 16:13–16:26, run 16:26–16:32, 52.3 MB):**
aligned (scale 0.9986, head 0.18 % h) → `mv_test/gate_mv/`; `shell_check` **36.3 % OUT** (front only 30.8): torso
39.5, upper arm 26.5, forearm 32.5, hands 45.2, thigh 30.1, shin 56.2, feet 30.3; front-facing 27.9 / side 33.3 /
back-facing 47.1 (front only 19.7 / 29.5 / 43.4). `mv_test/WORN_FRONT_VS_GATED_BACK.png`: the back skirt now covers
the seat, but the forearms and calves come out thinner and the upper back still shows. With a clean, outline-matched
back view, the front / back blend is still worse than the front alone: it does not give the depth.
**view_gate front / side / [rb] (`702155f`, his ask):** `front --input <bare>`: dress prompt + the bare outline grown
0.5 % h as image 2; pass if ≤ 2 % of it is uncovered (head top 13 %, soles 2 % left out). Calibrated on the fronts
so far, against the bare concept: flare_3_extrahigh 1.37 %, flare_2 2.74, flare_4 3.52, flare_1 4.81, the first
fitted front 5.38 — a width check only (extrahigh passes it and still left 30 % of his skin outside in 3D). `side
--front --back`: only head top, feet and height vs the front (≤ 2 %); depth unchecked. `[rb]`: redraw with "Make the
armour realistically big enough to cover his large chest, shoulders and arms ...". Checked with the copy provider.
`explode2/outline_check.py <bare.png> <armoured.png> [...] [--margin 0.005]` (local, seconds, no pod): bare outline
inside the armour's with a margin, head / neck left out. Current concept: **fail 7.21 %** of the bare outline (red all
round: plate within 0.5 % h of the skin or inside it). New concepts (his gens, model in the file name) go through it
before any 3D gen.

Fingers: bones 10–12 / 17–19 hang off the hands with no role, so `skin_bones` never listed them and finger skin
was never tucked under the gauntlets (the red fingertips). `fit_set.py` now adds every bone under a covered hand
or foot (the feet have none: the foot role is the toe bone, already covered).

```
%PY% tools\boss_sprite_pipeline\explode2\fit_set.py generated\bosses\barb\rigfix\barb_final_nb.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode2\fullplate\cut_d32_posed\shells_clean_all.glb generated\bosses\barb\explode2\fullplate\fit_set_full --only arm_l,arm_r,belt,boot_l,boot_r,gauntlet_l,gauntlet_r,leg_l,leg_r,pauldron_l,pauldron_r,skirt,torso
%PY% tools\boss_sprite_pipeline\explode\explode_pose.py --texture --aligned --rigid --tuck-from generated\bosses\barb\explode2\fullplate\fit_set_full\tuck_offsets.npz --only <13 pieces> generated\bosses\barb\rigfix\barb_final_nb.glb generated\bosses\barb\gear_test\barb_roles.json <out> full=generated\bosses\barb\explode2\fullplate\fit_set_full\parts_fit.glb
```

Prepared for steps 4–5: `explode2/prompts_v2.json` (upper / lower / full crops, the hand and foot prompts
in the same pass; "neck armor" dropped: 0.11–0.38 in v1) and `explode_label.py --facing-power K --diag`
(each camera's vote weighted by |normal · view|^K; without the flag v1's plain average is unchanged).

**view_gate `--draw reference|mask` (2026-11-08, `21d59c0`):** front and back take the target outline either as a
reference image, lined up afterwards (default; back = Leonardo nano-banana-2.1, front = gpt-image-2), or as a
gpt-image edit's mask, pasted back inside it (`--draw mask`). `--config` picks the model. Results of the masked
tries: see Tried and dropped.

**Rigid best fit + a chunkier front (2026-11-09):** `scratchpad/best_fit.py` (one-off): runs `shell_check`, then
coordinate descent over a shift (x / y / z) and a uniform scale about the body centre of the whole aligned outfit,
scored by moving the skin sample the inverse way. Front-only mesh (`mv_test/frontonly`): **30.85 → 23.63 % OUT** with
0.75 % h backwards and ×1.020. New front `view_gate_v4/front_attempt_02` (gpt-image-2 + `[rb]`, 1.29 % uncovered in
2D, cut out → `gear_test/in/v4_front_02.png`), TRELLIS front only on pod 4 (A40, install 23:07–23:21, mesh 23:27, 52.5
MB) → `mv_test/v4_front02/` (aligned scale 0.9984, head 0.20 % h): **34.0 % OUT**, best fit 28.47 % (x +0.5, y +0.75,
z +0.25 % h, ×1.015). By region vs the old front: thigh 22.0 (38.1), foot 17.1 (22.8), torso 33.0 (32.8), but upper
arm 52.7 (20.5), forearm 50.4 (5.5), hand 56.9 (43.7). Chunkier legs helped; the arms got much worse.

**v9 set on TRELLIS (2026-11-09, pod 5 A40, install 15:17-15:28, 3 runs to 15:43):** views from `view_gate_v9`
(front attempt 02 drawn on his body render with `--display-joints --margin 0.01`, back 01, left side 01, right = left
flipped), cut out → `mv_test/v9/`. OUT % as aligned → rigid best fit: front only 32.5 → 24.4 (torso 44.9, front-
facing 41.4); front + back 28.8 → 24.8; front + back + both sides 48.1 → 43.5 (forearms 68.7, hands 83.0).
Old concept front for reference: 30.8 → 23.6. Sides made it much worse.

**Limb misalignment (2026-11-12, `mv_test/WORN_V9_BESTFIT.png`):** on v9 front + back the whole armour sits right
(head residual 0.2 % h), but its arms and legs hang at slightly different angles from his: the skin left showing at
the armpits and inner shins comes from that, not from size (the rest is the loincloth). A rigid best fit cannot fix
it (it moves the armour as one block). **Possible next step, not built:** per-limb alignment after step 0, before
the pieces are fitted (steps 10-12): for each limb bone, the main direction of the armour points weighted to it vs
his body's points on that bone; rotate the armour's bone by the difference, apply as rest pose (Blender by hand:
pose mode, rotate the arm / leg bones onto his, Apply Pose as Rest Pose). No such step exists: `outfit_skeleton.py`
aligns the whole armour, `fit_piece.py` widens the torso, `fit_set.py` tucks skin (rejected).

## v9 front + back: full explode run (2026-11-12, pod 6 A40) → `v9_fb/EXPLODE_V9_STEPS.png`

Commands (Boss root, `%PY%` = `tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe`, `W` = `generated\bosses\barb\explode2\v9_fb`):
```
%PY% tools\boss_sprite_pipeline\explode2\outfit_skeleton.py generated\bosses\barb\rigfix\barb_final.glb generated\bosses\barb\explode2\mv_test\v9\v9_fb_from_front.glb W\fullplate_rigged.glb
%PY% tools\boss_sprite_pipeline\repaint\paint_outfit.py W\fullplate_rigged.glb W\paint generated\bosses\barb\gear_test\view_gate_v9\front_attempt_02.png generated\bosses\barb\gear_test\barb_roles.json tools\boss_sprite_pipeline\repaint\looks\barb_fullplate.json
%PY% tools\boss_sprite_pipeline\explode\explode_render.py W\paint\result\fullplate_rigged_painted.glb W\views "greedy:generated\bosses\barb\explode2\fullplate\greedy_dirs_f75.json:32" --diag W\diag_step3_render.json
pod: explode/sam3_pod.sh /workspace/views /workspace/prompts_v2.json   (upload recipe in the script header)
%PY% tools\boss_sprite_pipeline\explode\explode_label.py W\views --facing-power 8 --belt-gate --crease-snap --dirs 32 --out W\cut --diag W\diag_step5_label.json
pod: explode/holopart_pod.sh install ; holopart_pod.sh run /workspace/input_parts.glb /workspace/holopart_out
copy W\views\cams.json W\cut\ ; %PY% tools\boss_sprite_pipeline\explode\explode_merge.py W\cut W\holopart\output.glb ; %PY% ...\explode_show.py W\cut W\holopart\output.glb
%PY% tools\boss_sprite_pipeline\explode\explode_pose.py --texture --aligned --rigid --hide-under generated\bosses\barb\rigfix\barb_final.glb generated\bosses\barb\gear_test\barb_roles.json W\worn_shells outfit=W\cut\shells_parts.glb   (and merged_parts.glb)
```
- Step 0 needed `VOXEL = 2.0` (was 0.5): at 0.5 the bulkier armour and the body did not fuse in the proxy (~1,150
  islands, the kept largest one a hollow armour shell → bone heat all 0, the 2026-11-02 failure again). At 2.0: 1
  island, 0 of 844,247 armour verts unweighted.
- Paint: 859 s projection, some close-ups repainted (did not line up). SAM: default prompts crash on the steep views'
  `full` crop (`KeyError: 'full'`): use `prompts_v2.json` (has upper / lower / full). 55 renders, 3,299 masks.
- HoloPart: pip's newest diffusers (0.43) has no `models.normalization.LayerNorm` → pinned diffusers 0.32.2,
  transformers 4.49.0, peft 0.14.0 (in `holopart_pod.sh`). pymeshlab decimation needs `apt-get update` before the
  libopengl install. Output 250 MB, latents saved.
- `explode_merge.py` needs `cams.json` in the cut folder (copy it from views).
- Result: 13 clean pieces; worn on him in 6 poses with no skin showing. HoloPart surfaces noisy as before; the worn
  shells and merged look the same. Faults: head cut as a piece (drop), stray bit above arm_l (shows in "step side"),
  right boot toe in leg_r, strap hanging off pauldron_r. Limb misalignment still open (above).

## Tried and dropped

- **[r1] as a gpt-image-2 masked edit of the last attempt** (2026-11-08, `c775758`): mask = the shape error +12 px.
  The model redraws the whole picture: a feet-only mask came back with the gap between the thighs opened (thigh
  −11 % h) and the chest +3.5 % h; back IoU 0.976 → 0.951 → 0.943 over attempts 03 → 05 (`view_gate_v3/`). With
  the return pasted back inside the mask (`04a67b9`; attempt 04 replayed: 0.975) the body survives but the feet came
  back unchanged: an edit inside an error mask does not reshape. Dropped: a retry is the same draw with the overlay
  attached, as in the interiors.
- **Back as a gpt-image masked edit** (2026-11-08, `d8980b0`): image 1 the mirrored front outline as a black
  placeholder, the same outline as the mask, image 2 the front, return pasted back inside the mask. Raw return vs
  the mask: gpt-image-2 medium **0.940** (attempt 07: figure 3 px right, 0.952 shifted back; legs drawn apart where
  the outline is filled, thigh −11.2 % h), gpt-image-2.5-flare high **0.941** (attempt 10: every band ~1 % h narrow,
  more cartoon style; `view_gate_flare.json`). The Leonardo reference backs scored 0.964–0.976 lined up. gpt-image
  fills a mask to ~3 px, not exactly (OpenAI: the mask is guidance). Kept as `--draw mask`, not the default.
- **Front as a masked edit** (2026-11-08): mask = bare outline grown 0.5 % h, head left out. Covers him by
  construction but cuts the armour to the mask (pauldrons cut to his shoulders). Not wanted; kept as `--draw mask`.
