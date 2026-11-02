# Repaint a TRELLIS character with gpt-image-2 (whole body)

Started 2026-11-01 on the barb. The demon's face process (`part_polish.py` + `project_paint.py`,
logged in `PLAN_d2_and_animation.md`) extended to the whole body: render the mesh, let gpt-image-2
repaint each render, project the painted pixels back into the texture atlas. Script: `repaint.py`
(Blender venv, run from the Boss repo root).

## Why

TRELLIS `--skip-texture` meshes only carry the rough shape-stage colour: muddy, blurry, and wrong in
places (the barb's hair and beard came out the armour's green). About 5 % of the atlas texels inside
the charts are never written (rgb 0, alpha 0) — the dark speckle on every render; `repaint.py` fills
them from their neighbours first.

## Steps

```
PY=tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe
%PY% tools\boss_sprite_pipeline\repaint\repaint.py views   generated\bosses\barb\gear_test\barb_base_rigged.glb generated\bosses\barb\paint
%PY% tools\boss_sprite_pipeline\repaint\repaint.py gen     generated\bosses\barb\paint generated\bosses\barb\gear_test\in\barb_base.png
%PY% tools\boss_sprite_pipeline\repaint\repaint.py project generated\bosses\barb\gear_test\barb_base_rigged.glb generated\bosses\barb\paint
```

1. **views** (local, ~2 min): 8 body cameras (yaw 0–315, 25° up, 1024×1536) + 3 head close-ups
   (front, ±55°, 1024²). Per camera a flat render (the texture, unlit) and a clay render (grey shape,
   lit), plus `cams.json`.
2. **gen** (OpenAI, paid, ~11 calls): gpt-image-2 edit, quality high. Images in: flat render, clay
   render, the reference picture, and (for every view after the front) the front result as a colour
   anchor. Prompt: repaint as a texture of the same model, keep the grey background. The key is read
   from `OPENAI_API_KEY` (env, else the HKCU registry); a session-only key means running `gen` in the
   same PowerShell window that set it. Writes `gen/<view>/attempt_N/{input,clay,ref,output}.png`,
   `check.json` (silhouette IoU) and `ACCEPTED.txt`.
3. **project** (local, ~5 min): per camera a UV-id render ties each pixel to a texel; each painted
   pixel is splatted with weight smoothstep(facing) × facing⁴ (the most head-on view wins, edges
   blend), averaged in linear light. The head close-ups override the body views on the head. Texels
   no view saw get the old texture through an old→new colour map fitted on the painted texels.
   Gutters grown 16 texels, metallic 0, exported with the armature:
   `paint/result/barb_painted_rigged.glb`, `BEFORE_AFTER.png`.

## Lessons

- **gpt-image-2 redraws the figure slightly off the mesh** (hands and feet moved, proportions a bit
  different). First projection painted the grey background onto the mesh's hands and feet
  (`paint/result/v1_grey_hands/BEFORE_AFTER.png`). Fix in `project`: drop pixels where the painting
  is background grey (within 12 of 128) plus a 3-pixel rim; those texels fall back to the colour-
  mapped old texture. Hands/feet then have the right colour but the old (softer) detail.
- Better next step (not done): warp each painting onto the mesh render (optical flow between clay
  render and painting) before projecting, so every detail lands where the mesh has it.
- Result (`paint/result/BEFORE_AFTER.png`): brown hair and beard instead of green, real muscle
  shading, a proper loincloth; 43 % of the chart texels painted directly.
- The repaint keeps the mesh's skin weights; for posing use the bone-heat reweight
  (`rigfix/PROCESS_rigfix.md`) on the painted GLB.

## Pass 2 — the maximum: close-ups at 2880², 4096 texture (2026-11-01)

Why: pass 1 squeezed the whole body into 1024×1536 (a hand ≈ 100 px, the face ≈ 120 px; head
close-ups 1024²) — chosen to keep the first pass cheap, which was the wrong call. The demon's face
went in alone at 2048². Pass 2 maxes every knob:

- **25 close-ups** (`PART_SHOTS` in `repaint.py`), framed from the armature's joints (needs the roles
  JSON): face front/±50°, back of head, each hand ×2, each foot ×2, chest front, upper back, each arm
  ×2, each leg ×2, backs of the legs, hips/loincloth front and back. Each at **2880×2880**, gpt-image-2's
  largest (8,294,400 px).
- **Prompt**: the demon's sprite-reading style (bold readable shapes, punchy colour, strong value
  contrast, no pores or fine noise) + a line per part (eyes/brow/nose/beard locks; fingers, knuckles,
  nails; toes; muscle shapes; loincloth stitching) + "matte, no shiny or oily highlights". Image 4 is
  the approved whole-body painting from the nearest angle, as the colour anchor.
- **Projection**: the atlas is upscaled to **4096²** before painting (UVs unchanged), each close-up is
  **tone-matched** (per-channel gain + offset) to what the body and head views already painted on the
  texels both cover, then blended on top where it looks head-on. Material set matte (metallic 0,
  roughness 1). UV-id EXRs ZIP-compressed.

```
%PY% tools\boss_sprite_pipeline\repaint\repaint.py views   generated\bosses\barb\gear_test\barb_base_rigged.glb generated\bosses\barb\paint generated\bosses\barb\gear_test\barb_roles.json
%PY% tools\boss_sprite_pipeline\repaint\repaint.py gen     generated\bosses\barb\paint generated\bosses\barb\gear_test\in\barb_base.png parts
%PY% tools\boss_sprite_pipeline\repaint\repaint.py project generated\bosses\barb\gear_test\barb_base_rigged.glb generated\bosses\barb\paint
```

`views` only renders views whose renders are missing (the 11 pass-1 views keep the renders their
paintings were made from). `gen ... parts` = only the close-ups; any view names work too, to redo one.
`project` writes `paint/result/<input>_painted.glb` (was `barb_painted_rigged.glb` in pass 1).

### Pass 2, first gen run (2026-11-02)

- 8 of 25 close-ups painted (face front/±50°, back of head, both hands from outside, right foot,
  backs of the legs): demon-level — open readable eyes, bold beard/hair locks, separated fingers and
  toes with nails (`paint/PASS2_FIRST8.png`, left = model render, right = painting). ~100–120 s each.
- 15 failed on **OpenAI credit running out** (429 `credit_balance_exhausted`) — check the balance
  before a 25-call run.
- 2 were **blocked by the output safety filter as "sexual"** (`hand_l_front`, `arm_l_out`: both frame
  his near-naked hip and loincloth). Prompt now says he is a non-sexual, family-friendly game
  character wearing a leather loincloth; if still blocked, reframe away from the hips.
- Bug found and fixed: a failed call left an empty `ACCEPTED.txt` (the file was opened before the
  result raised), which crashed `project`. `gen` now writes it only after success; `project` skips
  markers whose painting is missing.
- Bug found and fixed: the first tone match (per-channel gain + offset by least squares) flattened the
  close-ups to 30–50 % contrast — the close-up and the body paint never line up pixel-exactly, and a
  straight-line fit on misaligned pairs comes out too flat. Now: one gain per channel from the median
  ratio (clamped 0.7–1.4); contrast untouched.
- Never paste the shell session with the `$env:OPENAI_API_KEY=...` line: a pasted key must be revoked.

### Ghost eyes → align each painting, one view per spot (2026-11-02)

- First projection of the close-ups put **ghosted double eyes** on the model (`paint/result/v3_ghost/`):
  gpt-image draws the face a little larger/higher than the mesh, and each view a bit differently, so
  the blended views stacked copies.
- Dense optical flow (OpenCV DIS) between the model's render and the painting smeared the painting
  into blobs — the two images are too different. Not used.
- **What works**: one affine warp per painting (`align()`: ECC on silhouette + shading at 720 px) onto
  the model's own clay+flat renders. face_front: ECC 0.985, scale 0.92 — eyes, nose and mouth land on
  the mesh's own lines. Views that will not align (ECC < 0.95 or scale outside 0.85–1.18) are
  **dropped**: face_left/right (ECC 0.93/0.90, scale 0.74/0.72 — drawn at a different head turn).
- View weight facing¹² instead of facing⁴: near winner-takes-all, so leftover differences cannot stack.
- Result (`paint/result/FACE_FIX_COMPARE.png`): one clean set of eyes, brows and beard; the hand
  close-up reads finger by finger on the model.
- opencv-python-headless 4.11 installed into `.venv-bpy` (numpy stays 1.26.4).

### Patch report, `missing`, and the final build (2026-11-02)

- `project` writes `paint/result/patches/<view>.png` per close-up: where the camera looks (zoomed out,
  frame drawn) | the model without the patch | with it | where it painted (pink) + its share of the
  texture, plus `PATCHES_INDEX.png` (biggest first) and `patches.json` (share, align ECC/scale,
  dropped views). Share of the texture ≠ importance: face_front is 0.49 % and the biggest visible change.
- `gen <work> <ref> missing` runs every view with no finished painting; re-run it after a partial
  failure (credit, safety filter) and it picks up only what is left.
- UV-id renders are cached (`uvid_<view>.exr` + `.key`: GLB size/mtime + camera) — reruns skip them.
- Windows: an image open in a viewer cannot be overwritten (`OSError: [Errno 22]`). The report crashed
  on `patches/face_front.png` *before* the model export, so the rig step ran on the previous GLB.
  Now the model is exported first, the report runs after it inside try/except, and BEFORE_AFTER.png
  is skipped (logged) if locked.
- Second gen run: 23 more paintings; still missing arm_l_out/front, arm_r_out/front, leg_l_out.
  Dropped as unalignable: face_left/right, back_upper (scale 0.80), leg_r_out (0.82) — regenerate.

**The shine** in the first pose tests (`paint/result/SHINE_TEST.png`) was the Workbench render's specular
highlight, not the texture: without it the paint is matte. Judge looks with specular off or in Eevee.

### Looks: other characters and outfits; cost per painting (2026-11-02)

- `views ... --look looks/<name>.json`: the prompt wording about the character (design, colours to match,
  how to paint, finish, the safety line), which views to make (`"views"`) and per-close-up wording
  (`"shots"`). Remembered in `cams.json`, so `gen` and `project` need no extra argument. Without a look
  the bare barb's wording is used, word for word as before. First look: `looks/barb_fullplate.json`.
- `gen` writes `usd` into each `check.json` and prints `COST this run $X; all paintings in <work>: $Y`.
  Prices (gpt-image-2 Standard, per 1M tokens): text in $5, image in $8, image out $30. A 2880² close-up
  ≈ 5.6k image tokens in + 23.7k out = **$0.76**; a 1024×1536 body view **$0.21**; a 1024² head view
  **$0.25**. The bare barb's 31 paintings: $17.59.

### 2880 was wasted: the 4096 texture holds far less (2026-11-02)

Measured from the barb's UV-id renders (painted pixels landing on each texel of the 4096 atlas, head-on
parts of each view): face close-ups 120 px per texel, hands/feet/head 55–105, chest/pelvis 20–24, legs
7–10, the 1024×1536 body views 1.1. Size giving 1 px per texel: face ~263 px, hands/feet/head 280–390,
chest/pelvis 590–650, legs 920–1060. So a 2880 close-up is 3–11× wider than what the model keeps; what
made pass 2 better was the **framing** (the subject fills the picture, so gpt-image paints it with care),
not the pixel count. Close-ups at 1024 keep the framing and lose nothing on the model (legs ≈ 1 px per
texel). A sharper face on the model would need more texels for it (bigger atlas or a re-UV), not a
bigger painting.

- Looks take `"part_res"` (close-up size), `"quality"` (gpt-image-2 quality) and `"regions"` (widen/raise a
  close-up frame; the full plate's arm frames cut the pauldron tops: `{"arm": {"scale": 1.3, "shift_up": 0.04}}`).
- `quality_test.py <work> <view> high:1024 medium:1024 low:1024` re-sends an accepted painting's exact inputs
  at other quality/size and shows each next to the original, also shrunk to what the texture holds.
