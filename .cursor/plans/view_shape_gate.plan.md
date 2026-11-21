---
name: view shape gate
overview: "One gate for character views generated through Leonardo's API (the armoured front, its back view; sides later): each draw is cut out, lined up with its target outline, scored per body band, and shown with its shape error marked; [r1] redraws with that overlay and a standing instruction, as the interiors and level gates do. The overlay, the retry syntax, the console gate and the image client already exist on main and are reused; the pieces that live inside one pipeline are lifted into shared modules, not copied. Branch feat/view-shape-gate in its own worktree."
todos:
  - id: setup
    content: "Before you start: worktree feat/view-shape-gate from main (docs/WORKTREES.md)."
    status: completed
  - id: shape-module
    content: "Step 1: tools/painted_map_pipeline/shape_gate.py (overlay colours, mark_shape_error, shape_note, shape_scores); footprint_overlay calls it with byte-identical output; test import moves; pixel-for-pixel test."
    status: completed
  - id: retry
    content: "Step 2: interiors/cli._parse_gate_retry -> world_levels/retry.parse_gate_retry(raw, overlay, note, directive); interiors calls it; one r1 test."
    status: completed
  - id: cutout
    content: "Step 3: flat_background() in tools/sprite_assets/cut_sheet.py; cut_sprite uses it; figure_cutout() (no hole filling) and score_mask() (holes filled)."
    status: completed
  - id: silhouette
    content: "Step 4: body_silhouette.py into tools/boss_sprite_pipeline/ (from the Boss worktree), docstring updated."
    status: completed
  - id: gate
    content: "Step 5: tools/boss_sprite_pipeline/view_gate.py: front (cover his body, outline as image 2) and back (match the mirrored front), alignment and bands as outline_check, overlay, sheet, the r1 loop, outputs."
    status: completed
  - id: docs
    content: "Step 6: docs point at shape_gate and view_gate; nothing left that the gate replaced."
    status: completed
isProject: false
---

# View shape gate

## Why

Multi-view TRELLIS (`tools/boss_sprite_pipeline/gpu_box/trellis2_multiview.py`, so far only in the Boss worktree)
needs a back view whose outline is the front's mirror. Re-measured with `outline_check.py`'s own alignment and band
rule (`fullplate_tests/BACK3_CHECK.png`):

| back view | IoU with the mirrored front | worst band (% h) |
|---|---|---|
| Nano Banana 2.1, flipped outline as image 2 (`nb21_back3.jpg`) | 0.964 | +0.41 |
| gpt-image 2.5 flare, first (`flare_3_back.jpg`) | 0.919 | shoulder −1.22 |
| gpt-image 2.5 flare, true back (`flare_3_back2.jpg`) | 0.916 | hips −1.72 |

Without a check, a miss goes to the pod. The front needs the same: the armour must cover his body with room to
spare. The front in use (`flare_3_extrahigh.jpg`) leaves 6.67 % of his outline uncovered or too close against his
3D body, and in 3D 32 % of his skin ended up outside it (`explode2/PROCESS_explode2.md`).

The interiors and level pipelines already do this: score the draw against its mask, paint the miss on it and, on
`[r1]`, resend it with a standing instruction. More pipelines like this are coming, so the shared parts go in
shared modules and every pipeline uses the same ones. The images are made through Leonardo's API with Douglas's
key, not by hand.

## What is reused, and where it is (all on `main`)

| Piece | Where | Used for |
|---|---|---|
| `ask`, `show`, `sent`, `prompt_sent`, `with_criticism`, `split_retry` | `tools/painted_map_pipeline/review_gate.py` | the console gate, printing what was sent, numbering attachments |
| `shape_retry` | `tools/painted_map_pipeline/world_levels/retry.py` | the `r1` text |
| `OVERLAY_MISSING / SPILLED / STRENGTH`, `footprint_overlay`, `FOOTPRINT_OVERLAY_NOTE / DIRECTIVE` | `tools/painted_map_pipeline/world_levels/checks.py` | the marked overlay and its wording |
| `_parse_gate_retry`, `_shape_texts` | `tools/painted_map_pipeline/interiors/cli.py` | `r1` / `r <why> @img` at a gate |
| `make_image_client(config)` | `tools/painted_map_pipeline/image_client.py`, `leonardo_api.py` | the draws, with several input images |
| `leonardo.config.example.json` | `tools/painted_map_pipeline/` | a working Leonardo config to copy |
| `sheet_background`, `distance_from` | `tools/sprite_assets/cut_sheet.py` | the plain background colour |
| `cut_sprite`, first stage (border-connected background, big pockets) | `tools/entity_pipeline/figures.py` | the cut-out |
| `bpy_python(here)` | `tools/boss_sprite_pipeline/__init__.py` | the Blender venv's interpreter |

Not on `main` (uncommitted in the Boss worktree `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss`, branch
`dev_3d_boss`, 53 commits behind `main`): `tools/boss_sprite_pipeline/explode2/body_silhouette.py` (his 3D body's
silhouette, views as plain arguments: front / back / left / right) and `explode2/outline_check.py` (silhouette,
alignment, band widths, the cover check). The gate replaces `outline_check.py`; `body_silhouette.py` moves in. The
cut-out used so far, `cutout_white.py`, is a scratchpad script; step 3 replaces it.

## Before you start

- Follow `docs/WORKTREES.md` from the main folder: `git worktree add -b feat/view-shape-gate ..\Pixel-Realm-view-gate main`,
  then link the venvs it needs (`Code\sprite_venv`, and `tools\boss_sprite_pipeline\.venv-bpy` for step 5) as
  junctions. Work only there. Read from the Boss worktree; change nothing in it.
- Find functions by name and re-read a file right before editing it.
- One commit per step. No pushing or merging until Douglas says so (`AGENTS.md`).
- No re-export shims and no second copy of anything moved: every caller, tests included, imports from the new place.

## Step 1. The shared shape module

New `tools/painted_map_pipeline/shape_gate.py` (numpy + PIL only):

- **Moved from `world_levels/checks.py`:** `OVERLAY_MISSING`, `OVERLAY_SPILLED`, `OVERLAY_STRENGTH`.
- `mark_shape_error(image, should, has) -> Image`: `should` and `has` are boolean masks the size of `image`;
  `should & ~has` painted `OVERLAY_MISSING`, `has & ~should` `OVERLAY_SPILLED`, blended at `OVERLAY_STRENGTH`.
- `footprint_overlay` keeps its signature and both thresholds and calls it with
  `should = mask`, `has = (mask & (summed > missing_limit)) | (~mask & (summed > limit))`. That reproduces today's
  pixels exactly, including the interiors' split thresholds.
- `shape_note(background) -> str`: today's note with both background words filled in ("where you left it
  {background}", "it should be {background}"). `world_levels/checks.py` keeps
  `FOOTPRINT_OVERLAY_NOTE = shape_note("black")`, equal to today's text; `review_run.py` and `interiors/cli.py`
  keep importing it from there.
- `shape_scores(should, has, bands=()) -> dict`: `iou`, `missing` (pixels of `should` not in `has`, over
  `should`), `spilled` (pixels of `has` not in `should`, over `has`), and for each `(name, row, columns)` the widths of
  `should` and `has` on that row within those columns, and their difference. All in pixels; the caller scales.
- `tests/painted_map_pipeline/test_checks.py`: its `OVERLAY_MISSING / OVERLAY_SPILLED` import moves to `shape_gate`.
  Add one test: an image and mask with pixels in all four brightness ranges, `footprint_overlay` at the default
  thresholds and at the interiors' split pair, compared pixel for pixel with the old formula written out in the test.
  Run `test_checks.py`.

## Step 2. One retry parser for every gate

Move `interiors/cli._parse_gate_retry` into `world_levels/retry.py` as
`parse_gate_retry(raw, overlay, note, directive)`, same body, the texts passed in instead of fetched. Both call sites
in `interiors/cli.py` become `parse_gate_retry(raw_answer, shape, *_shape_texts())`; delete the old function. Add a
test of `parse_gate_retry("r1 ...", overlay, note, directive)` next to the existing `r1` tests in `test_checks.py`
(the interiors gate tests don't call it). Run `test_checks.py` and `test_interiors_gates.py`.

## Step 3. One cut-out for a figure on a plain background

- `tools/sprite_assets/cut_sheet.py`: `flat_background(rgb) -> bool mask`, lifted from the first stage of
  `cut_sprite`: `distance_from(rgb, sheet_background(rgb)) < 75`, the components touching the border, plus pockets
  `< 22` of 45 px or more. `cut_sprite` calls it and keeps its crumb peeling (that is for small sprites).
- **Done differently (2026-11-08):** `flat_background(rgb, pockets=True)` takes a switch. With the pocket rule
  on, the first check punched holes in the plate: polished-steel highlights are near-white, so they read as
  sheet (`fullplate_tests/CUTOUT_NEW_VS_OLD.png`). `cut_sprite` keeps `pockets=True` (output identical to
  `main` on 9 images); `figure_cutout` and `score_mask` use `pockets=False`. The arm gaps in these poses open
  onto the border, so they are still cleared. Result: IoU 0.986 against both old cut-outs, 0.99 with the old
  cutter's 1 px trim undone, 96-99 % of the difference within 2 px of the outline, no holes.
- Same file, two masks from it:
  - `figure_cutout(image) -> RGBA`: alpha = `~flat_background`, largest component, **holes not filled**. The gaps
    between arm and torso stay transparent; that is what gave TRELLIS separated arms
    (`tools/boss_sprite_pipeline/PROCESS.md` §6b).
  - `score_mask(image) -> bool mask`: the same with holes filled, for scoring and overlays only (as
    `outline_check.silhouette` did).
- Check once: the alpha of `figure_cutout` on `fullplate_tests/flare_3_extrahigh.jpg` and `nb21_back3.jpg` matches
  the alpha of the current cut-outs (`gear_test/in/barb_fullplate_v2.png`, `barb_fullplate_v2_back3.png`) to IoU
  0.99 or better. If it doesn't, stop and report; don't add a second cutter.
- Run `tests/test_entity_pipeline.py` (it covers `cut_sprite`).

## Step 4. His body's silhouette

Copy `explode2/body_silhouette.py` from the Boss worktree to `tools/boss_sprite_pipeline/body_silhouette.py`. It
already makes its out path absolute (Blender resolves relative render paths elsewhere) and takes the views as
plain arguments. Change only its docstring: it names `outline_check.py`, which goes; name `view_gate.py` instead.

## Step 5. The gate

`tools/boss_sprite_pipeline/view_gate.py`, run with the repo venv as
`python -m tools.boss_sprite_pipeline.view_gate front --input <bare concept> --body <base_rigged.glb> --config <json> --out <dir>`
or `... view_gate back --input <approved front> --config <json> --out <dir> [--body <base_rigged.glb>]`.
`--body` is required for `front`. The body's silhouette comes from running `body_silhouette.py` as a separate
process with `bpy_python(Path(__file__).parent)`, absolute paths, written into `--out`; the gate never imports
`bpy`.

**Two targets**, one scoring path:

| view | images sent | target (`should`) | counts as a miss | overlay |
|---|---|---|---|---|
| `front` (dress) | 1: the bare concept; 2: his body's front outline grown by `MARGIN` 0.5 % h, black on white | that grown outline, top 13 % (head, neck) and bottom 2 % (soles) left out | missing only | magenta only: `mark_shape_error(img, should \| has, has)` |
| `back` | 1: the approved front; 2: the front's outline mirrored left to right, black on white | that mirrored outline | missing and spilled | magenta and cyan |

Image 2 does for the front what it did for the back (back3: 0.964): the model sees the shape it must cover. The
head and soles are left out of the score as `outline_check` left the head out (`HEAD = 0.13`): the head stays bare,
and the soles stand on the floor. With `--body`, the back also prints the front-style cover check against his body
from behind, as a number, not a pass. **Sides are not in this plan, and no side view goes to the pod unchecked:**
a side has no mirror of the front; its target would be `body_silhouette` left / right with the front's cover rule.

**Prompts** are module constants:
- front: the dress prompt that made the front in use ("Dress this exact man in a full suit of steel plate armour
  worn over a thick padded gambeson ... if unsure, make the armour slightly too big rather than too tight"), plus
  one sentence: "Image 2 is the outline his armour must cover: every part of the black shape is inside the armour;
  the armour may reach past it." This sentence is new; the first runs show whether it works.
- back: "Draw the man in Image 1 seen from behind. Image 2 is his exact outline from behind: fill it exactly, with
  the same pose, size and position, nothing outside it and no gaps. Show his back, hair bun, backplate, the backs
  of his arms, legs and heels. Same armour, white background."

**Config** (`--config`): a copy of `tools/painted_map_pipeline/leonardo.config.example.json` with `"model":
"nano-banana-2.1"`, `"prompt_enhance": "OFF"`, no `style_ids`, 1024 × 1024, **`"quantity": 1`**:
`generate_with_image_reference` downloads only the first image, so a second one is paid for and never seen. `[r]`
draws another. The client is used as it is. If Leonardo rejects the model id, its readable error says so; take the
id from Leonardo's model list.

**Each draw** (`attempt_NN.*` in `--out`):
1. `score_mask` of the draw, lined up with the target exactly as `outline_check.normalise` does: scale to the
   target's height with `Image.NEAREST`, head top at row 20, body centre (mean x of the top 30 % of the figure) on
   the target's. The target is lined up the same way.
2. `shape_scores` on the lined-up masks. Bands as `outline_check` measured them, at these heights above the floor:
   shoulder 0.80, chest 0.72, waist 0.60, hips 0.52 (whole row), thigh 0.42, knee 0.30, calf 0.20, ankle 0.08 (one
   leg: the right half of the image). Widths in % of height.
3. **Pass**, constants at the top of the module with the measurements beside them:
   - back: IoU ≥ 0.95 and every band within 1.0 % h (back3 passes at 0.964 / +0.41; the gpt backs fail);
   - front: `missing` ≤ 1 % of the target. The front in use fails this (6.67 %, and 32 % of his skin outside it
     in 3D), which is correct: the gate is there to catch it.
4. The overlay on the **lined-up** draw → `attempt_NN_shape.png`. The sheet `attempt_NN_sheet.png`: target |
   lined-up draw | overlay, with the scores and PASS or the failing bands written on it; `review_gate.show` opens it.

**The gate** (same keys as the interiors gates):
`[enter] accept   [r] draw again   [r1] redraw showing this draw's shape error   [r <why> @img] redraw with criticism   [s] show again   [q] stop`.
`r1` → `parse_gate_retry(raw, shape_png, note, directive)` with each view's own texts, and the prompt sent is
`with_criticism(prompt, criticism, attach, first_index=3)` (both views already send two images):
- back: `shape_note("white")` and `BACK_SHAPE_DIRECTIVE` (match the outline in image 2 exactly);
- front: `FRONT_SHAPE_NOTE` ("magenta is where his body is not covered by the armour; cover it, armour may reach
  past it") and `FRONT_SHAPE_DIRECTIVE`. No cyan clause: the front must never be told to shrink.
Both directives are modelled on `FOOTPRINT_OVERLAY_DIRECTIVE` and keep its last clause ("this is the most important
directive..."). Before each draw, `review_gate.sent` prints the prompt and the images exactly as sent; each attempt's
prompt is saved as `attempt_NN_prompt.txt`.

**Accept** writes `<out>/<view>.png` (`figure_cutout`, ready for TRELLIS) and `<out>/gate.json`: view, inputs,
config, every attempt (prompt file, images sent, scores, pass), the accepted one.

## Step 6. Docs, and nothing left behind

- The comment above the overlay code in `world_levels/checks.py`: the colours and marking live in `shape_gate.py`,
  shared by the level, interiors and view gates.
- `tools/boss_sprite_pipeline/PROCESS.md` §6 / §6b: the cut-out is `figure_cutout` (via `view_gate`), not a
  scratchpad `cutout.py`.
- `tools/boss_sprite_pipeline/README.md`: one paragraph on `view_gate`, its two targets, and that it calls
  `body_silhouette.py` through the Blender venv.

## Do not

1. Do not add a second overlay colour scheme, retry syntax, console gate, image client or cutter.
2. Do not change any level or interiors behaviour: their overlay pixels and texts stay byte-identical (step 1's test).
3. Do not extend the image client in this branch (saving every image of a batch is a separate change).

## Decisions for Douglas

- **Automatic r1:** recommended no, as in the other gates: the check reports, a person decides what goes back to
  the model (`world_levels/checks.py`, module docstring).
- **After the merge:** to use the gate from the Boss worktree, merge `main` into `dev_3d_boss` (53 commits behind;
  his go-ahead). Then delete the untracked `explode2/outline_check.py` and `explode2/body_silhouette.py` there, and
  point `explode2/PROCESS_explode2.md` at the gate.
