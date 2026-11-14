# Plan: characters and outfits set up from the web page, no barb in the code

Written 2026-11-14. Branch `feat/outfit-config` (worktree `Pixel-Realm-outfit-config`), from `main` `b581b6e6`.
Builds on the outfit pipeline (`outfit_pipeline.plan.md`, `PROCESS_outfit.md`) and its web page
(`outfit_web.plan.md`, `PROCESS_outfit_web.md`).

## The problem

- Every input of a run (concept image, rigs, roles, clips blend, look, SAM prompts, prompts) is a path in a
  hand-written outfit file `tools/boss_sprite_pipeline/outfits/<character>/<outfit>.json`. The page lists and
  runs those files; it cannot make, edit or check them, or take an image.
- The 3 barb outfit files repeat the same 6 character paths (`rig_fit`, `rig_game`, `roles`, `clips_blend`,
  `greedy_dirs`, `views`).
- Barb left in code:
  - `export_outfit.py` `clips_json`: clips.json copied from `Graphics/Meshes/barb/`.
  - `export_outfit.py` `export_body`: game entry with "Barbarian", `barbarian.png`, `../Graphics/barb/`, the
    barb's roster / base stats / evasion loadout.
  - `repaint/repaint.py` `DEFAULT_LOOK`: with no look file, the paint prompts describe the barb.
  - `player_clips.py`: defaults `settle_01`, `jokesillyrun`, `overheadchop` 45-60,108-138 are the barb's picks.
  - `retarget_bvh.py` `TARGETS["barb"]`: his rig, roles and quirks in the code table (the bosses' rows stay).
  (Found by `character_pipeline.plan.md` in `Pixel-Realm-characters`, whose step 1 defers to this plan.)
- A view (front, back, sides) can only come from a drawing call. An image you already have cannot be used
  (an upload is only sent to the image model as a reference for a redraw).
- After `export`, getting pieces into the game is terminal + hand edits: `equip_install.py`, the stats in
  `Graphics/Standard_Items/item_bases.json`, the hero entry and its `start_equipment` in
  `Graphics/PlayerSelectionDict.json`.

## Goal

A new character's outfit or look set up, run and installed from the page: every input chosen or uploaded, every
view drawn or supplied, every gate clicked, the pieces in the game. The scripts stay the only way anything runs
(the page calls the same commands); the files they read stay plain JSON you can diff and commit.

## 0. Rules (decided before code)

- **Two files.** `outfits/<character>/character.json`: what every outfit of the character shares. Outfit file:
  only what differs. The driver reads them merged: outfit keys override character keys (`Ctx.o`).
- **One field table** (`tools/boss_sprite_pipeline/outfit_fields.py`): per field: name, level (character /
  outfit), kinds that need it (body / armour / cut), type (image / glb / blend / json / text / number / bool /
  list / choice), help line. The page's forms, the checks and the tests come from this table; a new field is a
  row, no new form code. (Same idea as `item_properties.py`.)
- **`rig_fit` is the character's own rig.** The skeleton step (`explode2/outfit_skeleton.py`) fits every new
  mesh onto `rig_fit` by height and head: right for outfits of that body, wrong for another body shape. Its help
  line says so; a new character never borrows another's `rig_fit`.
- **No character default in code.** A missing field is an error naming the field, never the barb's value.
- **Inputs live in the data root.** Uploads go to `<data>/generated/bosses/<character>/inputs/` (kept, named by
  time + original name). The page may write the character / outfit JSON and `item_bases.json` /
  `PlayerSelectionDict.json` (repo files: you review and commit them). It still never writes `run.json`.
- **A supplied view is an attempt.** It goes through the same gate as a drawing: same cut-out, same outline
  checks, same sheet, accepted by the same button. run.json records it as `supplied` with the source path.

## 1. Character file and the field table

- `outfits/barb/character.json`: `rig_fit`, `rig_game`, `roles`, `clips_blend`, `greedy_dirs`, `views`,
  `clips_from` (pack whose clips.json a body export copies, today `barb`), `roster` (the game entry:
  `display_name`, `painting`, `player_info_dir`, `roster_stats`, `base_stats`, `evasion_loadout`), `clips`
  (idle / move / attack source names + attack frames, for `player_clips.py`), `retarget` (`bind_match`,
  `arm_elev_cap`, `digitigrade`, for `retarget_bvh.py`).
- The 3 barb outfit files lose the repeated keys.
- `Ctx`: loads character + outfit, merges, checks against the field table (missing / wrong type / file not
  found: one error listing all).
- Check: the merged dict of each barb outfit equals today's file (compared with `git show main:...`), and
  `--status` / `--dry-run` of each step prints the same commands as before (diffed).

## 2. Barb out of the code

- `export_outfit.py`: clips.json from `clips_from`; the game entry from the character file + the outfit's
  `display_name` / `start_equipment`.
- `repaint.py`: `DEFAULT_LOOK` moves to `repaint/looks/barb_bare.json` (`repaint/look_file.py`); no look = an
  error. A look may `"extends"` another: the barb's outfit looks extend `barb_bare.json`. A run whose cams.json
  has `"look": null` (made before looks were required) stops with what to set; no data file is rewritten.
- `player_clips.py --character <c>`: clip names and frames from the character file; no defaults.
- `retarget_bvh.py --target <c>`: a character file with `retarget` first, else the code table (bosses).
  The barb's row leaves the table.
- Check (proof stays the barb), before / after, diffed: every step's `--dry-run` commands; the `views` prompts
  for naked / fullplate; the `naked` export entry JSON; `retarget_bvh --target barb` profile; `player_clips`
  clip choice. Grep: no `barb` in the pipeline code outside comments and the barb's own files.

## 3. New character / new outfit from the page

- Server: `GET /api/fields` (the table), `POST /api/character` and `POST /api/outfit` (create: from a copy of an
  existing one or empty; save: checked against the table, refused with the field errors), `GET /api/files`
  (files of a type under the data root, to pick), `POST /api/upload` extended to the inputs folder.
- Page: "New character", "New outfit" (kind, copy from); a form per file from the table: file fields as pick /
  upload with a thumbnail for images, text fields as text areas (prompts), lists as tick boxes.
- A character needs its base assets made first (concept render, rig, clips blend, roles): the form picks them,
  it does not make them (see Not in this plan).

## 4. Supplied views ("use this image")

- `view_gate.py --use <image>`: adds attempt N from the image, no API call; cut-out, outline checks and sheet as
  for a drawing; then `--accept N` as now. Front, back and each side view.
- `outfit.py --only <view> --use <image>`; page: "Use an image" on each view panel (pick or upload).
- So: supply front / back / sides, tick the TRELLIS models, run: every model from your images.

## 5. Install step

- New last step `install` (armour, cut): `equip_install.py` (packs, icons, items with `base`). Bases the items
  name that `item_bases.json` lacks: the step stops at a gate; the page shows a form from
  `Code/item_properties.py` rows (one per base, e.g. `leather_chest`) and writes them; then the step finishes.
- Body kind: `export` writes the hero entry into `PlayerSelectionDict.json` (a free `selection_position`)
  instead of printing it; the page shows the entry first, a button writes it.
- Start gear: a field of the hero entry, set on the body outfit's page (`start_equipment`: wear / pack, item ids
  picked from the installed items).

## 6. Tests

- `tests/test_outfit_pipeline.py`: merged barb outfits equal the old files; a missing field names itself; no
  barb fallback (a test character in tmp: export entry, clips source from its own fields).
- `tests/test_outfit_web.py` (fake driver, as now): create character / outfit, refused save lists field errors,
  upload lands in the inputs folder, `--use` button builds the right command, install gate writes bases.
- `view_gate --use` on a stored barb drawing: same cut-out as the gate made from it (pixel compare).
- Page: headless Chrome screenshots of the new forms, the "use an image" panel, the bases form; looked at.

## 7. Proof

From the page only (launch typed, nothing else): a new barb armour outfit with its front supplied as an image,
back and sides drawn, TRELLIS with 2 models, picked, through to `install`, worn in game. Paid calls and a pod:
you start and stop the pod.

## Order

0 agreed → 1 → 2 → 3 → 4 → 5 → 6 alongside each → 7. Each step: tests pass, commit.

## Process doc

`PROCESS_outfit_web.md` (page) and `PROCESS_outfit.md` (driver, files): Method, Known errors, Log, Tried and
dropped, kept as each step lands.

## Not in this plan

- Making a new character's base assets. Not `pipeline.py` / `PLAN.md`: that is the September boss route
  (Hunyuan by default, procedural clips). The barb was made: one gpt-image-2.5 "flare" image → TRELLIS → UniRig →
  `rigfix/rig_reweight.py` heat 0.5, plain skinning not dual quaternion (`PROCESS_rigfix.md`, "Current best
  barb") → `anun_roles.py` → `explode2/fix_neutral_bone.py` (`barb_final_nb.glb`) → `retarget_bvh.py --source
  anunaki` → `player_clips.py`. A new character's first rig is a real gap: UniRig has no `pod.py` step and last
  ran through the September `gpu_box/setup.sh` / `GpuExec` route. Draft: `character_pipeline.plan.md` step 2
  (branch `docs/characters`, worktree `Pixel-Realm-characters`). The page only picks the made files.
- Armour made for one body on another: nothing in `equipment.fits()` stops barb plate going on another mesh
  hero (`character_pipeline.plan.md` step 3).
- Animations from the page (kimodo / retarget).
- A batch queue of outfits.
- Hiding the body under worn pieces; the helmet model.

## Open

- Should the page offer "copy outfit to another character" (same prompts, other rig)?
- Item base names for a new material: typed on the bases form, or picked from a material list?
