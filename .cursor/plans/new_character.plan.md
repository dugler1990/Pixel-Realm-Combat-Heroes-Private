# Plan: a new character from the outfit page

Goal: an original character made on the outfit page, start to end: concept (text or your image) → views →
TRELLIS → rig → roles → paint → game rig → clips → export → install. What it makes is written into its
character file, so its armour sets, body variants and pieces from a mesh then run on it as on the barb.
Builds on `feat/outfit-config` (character file, field table, images per view, page). Takes over step 2
("first-rig route") of `character_pipeline.plan.md` (branch `docs/characters`); that plan's step 3 (armour
fits only its body) stays there.
Proof throughout: the barb's outputs do not change (`_checks/barb_unchanged.py`, main vs branch).

## Status 2026-11-14
Branch `feat/new-character` (worktree `Pixel-Realm-new-character`), from `feat/outfit-config`.
- 0 built: `view_prompts/barb_plate_armour.json`, `view_checks/default.json`; 16 barb dry-run cases identical.
- 1 concept / front / back / sides built (kind `character`, `concept_gate.py`, `view_prompts/character.json` +
  `a_pose.png`, page panel). The A-pose: the barb's arms measure 28 degrees from straight down
  (`pose_heights.py --arms`); candidates pass at 18-40. Not run with a paid call yet. trellis: the existing step.
- rig (pod: `pod.py unirig`, `gpu_box/unirig_pod.sh` from NOTES_rig_jaw_sam3 section 1), reweight, roles (gate:
  `pose_render.py` sheet), paint (its own reweighted mesh and roles; writes `rig_fit`), game_rig (writes
  `rig_game`, shared `greedy_dirs`, views 32) built. Checked on the barb's own UniRig output through the driver:
  reweight = `rigfix/barb_heat0.5.glb`, roles = `gear_test/barb_roles.json`, game_rig (on `barb_final.glb`) =
  `barb_final_nb.glb`, all exact (`_checks/rig_compare.py`: 29 bones, weight difference 0). The pod install
  is not run yet.
- Correction: `rig_fit` is the painted, reweighted body (as `barb_final.glb`), written by paint, not by reweight.
- Next: clips, sprites, export, install (they stop with "not built yet").

## What exists and is reused
| Step | Tool | State |
|---|---|---|
| views | `view_gate.py` front / back / side, `images` per view (`--use`) | in the driver |
| 3D model | `pod.py trellis`, 4 models (front only ... eight_views) | in the driver |
| rig | `gpu_box/unirig_cli.py` (skeleton → skin → merge) | never run by the driver; ran by hand on the pod (demon, anunaki, barb: `NOTES_rig_jaw_sam3.md` §1: py 3.11 venv, torch 2.7 cu126, flash_attn wheel, libegl1, `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`, ~15 min install, ~3 min run) |
| reweight | `rigfix/rig_reweight.py ... heat 0.5`, linear skinning | barb best (PROCESS_rigfix) |
| roles | `rigfix/anun_roles.py <rigged.glb> <out.json>` (geometric) | anunaki, barb |
| paint | `repaint/paint_outfit.py` (driver `paint` step), look file | in the driver |
| game rig | `explode2/fix_neutral_bone.py` → `*_nb.glb` | barb |
| clips | `retarget_bvh.py --source anunaki --target <c>` (character file row), `player_clips.py --character` | barb |
| export / install | `export_outfit.py` body, `install_outfit.py` hero entry | in the driver; copies `clips_from`'s clips.json |
| concept | `painted_map_pipeline/image_client.py` `generate(prompt, [], out)` | text-to-image not wired anywhere here |

## 0. Defaults out of view_gate.py (small, first)
- `PROMPTS` (plate armour, "the man ... beard"), `BIGGER` ("his large chest") → prompt files
  `tools/boss_sprite_pipeline/view_prompts/<name>.json` (`plate_armour.json` = today's text, `body.json`,
  `character.json`). Outfit field `view_prompts` names one; an outfit's own `front` / `back` / `side` / `quarter`
  / `retry_bigger` still win. No file and no own prompt for a view that is drawn: the step stops naming it.
- `HEAD`, `SOLES`, `MARGIN`, `FRONT_MAX_MISSING` and the other pass limits → `view_checks/default.json` (today's
  values, measured on barb fronts); outfit field `view_checks` may name another.
- Barb outfits get `view_prompts` set to the file holding their current default.
**Check:** `view_gate --dry-run` for every barb view, main vs branch: same prompt text and images (diff);
`barb_unchanged.py`: same; tests pass.

## 1. Kind `character` ("New character" on the page)
Steps: `concept front back sides trellis rig reweight roles paint game_rig clips sprites export install`.
Phases on the page: Views (concept front back sides) · 3D model (trellis rig reweight roles paint game_rig) ·
Animation (clips) · Game (sprites export install). Needs nothing in the character file to start; each step
writes what it makes into it (field table, page writes JSON). New outfit fields: `concept_prompt`,
`concept_config`, `concept_refs`, `concept_count`.

### concept
- `images.front` given: that is the concept, no call.
- Else a text prompt with context images → `image_client.generate`, N candidates (`concept_count`, 4) into
  `<run>/concept/`. Gate: pick one, or regenerate with a reason (`r <why>`, as the view gates).
- The model is a setting (`concept_config`: any image config, gpt-image-2.5 flare / gpt-image-2 / Leonardo).
  Each passes context its own way and `image_client` already does it per provider (gpt-image: the images in the
  request, named "Image 1, 2..." in the prompt; Leonardo: a reference strength per image). Context sent:
  1. the pose image: the barb's A-pose (his front outline with the shoulder / hip / knee / ankle lines,
     `body_silhouette.py` + `with_joint_lines`, as the view gates send), so every character stands like him;
  2. `concept_refs`: your style / look images (optional, uploaded on the page).
  The prompt says which image is which, as `view_gate` does.
- Pose: A-pose, the barb's (what UniRig, the retarget and the armour route were all proven on). Check on each
  candidate: one person found (`pose_heights.py`), whole body in frame, white background, joint heights and
  the shoulder–wrist angle within a set tolerance of the barb's (measured once on his front, kept in
  `view_checks/default.json`). PASS / FAIL on the sheet like the view gates.

### front
The picked concept is the front, accepted without a redraw (as a given front with no concept today). Back and
sides are drawn from it with `view_prompts/character.json` (generic: "the character in Image 1", no beard, no
armour), or given.

### rig (pod)
- `pod.py unirig`: push the picked TRELLIS mesh, run `unirig_cli.py`, pull `rigged.glb`. `RIG_OK`.
- Setup: `gpu_box/setup.sh unirig` today differs from what worked (cu124, the full requirements with
  flash_attn): rewrite it to NOTES_rig_jaw_sam3 §1 (torch 2.7 cu126, requirements minus flash_attn, the
  prebuilt flash_attn wheel fetched with curl, spconv-cu126, pyg wheels, numpy 1.26.4, libegl1 / libgl1,
  `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`). Installed once per pod, skipped when there. No xformers.
- Gate: the skeleton drawn over front and side renders, bone count, and the posed body in a few poses
  (as `rigfix/pose_final/POSE_body_tex.png`); `rig_check.py` weight heatmaps beside it.

### reweight, roles, game_rig (local)
- `rig_reweight.py <rigged> <out> heat 0.5` → `rig_fit`.
- `anun_roles.py` → `roles`. Gate: the skeleton drawn with role labels (one image); wrong roles are fixed in
  the form (JSON) and the step rerun.
- `fix_neutral_bone.py` → `rig_game`.
- Written to the character file: `rig_fit`, `roles`, `rig_game`; `greedy_dirs` / `views`: the barb's
  `greedy_dirs_f75.json` (data root, `barb/explode2/fullplate/`) copied once to a shared file, 32 views, so
  armour sets work.

### paint
The existing `paint` step on the reweighted mesh (`paint_look` required; a look file per character, `extends`
a generic one).

### clips
- `retarget_bvh.py --source anunaki --target <c>` (its row from the character file: rig, roles, `retarget`
  quirks written with defaults bind_match false, arm_elev_cap 90, digitigrade false, editable) →
  `<run>/clips/animated.blend` + one preview per clip (`make_mp4.py` / frame strip).
- Gate: the page lists the clips with previews; pick idle, move, attack and the attack frames → `clips` in the
  character file. `player_clips.py --character <c>` → `clips_blend`. Source: the anunaki SOMA set only.

### sprites: its own sprite body
In the game a mesh hero is drawn over a sprite hero: `Player` loads `player_info_dir` (`down_idle/0.png` sets
its size and hit body, the frames drive it) and draws the mesh on top (`barb_mesh` and `barb_armour_mesh` both
use `../Graphics/barb/`). A new player gets its own folder `Graphics/<c>/`, rendered from its painted mesh and
clips: `render_frames.py` (one camera, the same framing for every frame) + `pack_frames.py`, adapted to the
player layout (`down up left right`, each `_idle _move _attack`, plus the plain direction folders,
`selection_screen`, `sit_down sit_idle sit_up`, `slide_left slide_right`, as `Graphics/barb/`). Sit and slide:
from the anunaki clips nearest them (picked at the clips gate), else a still pose. Portrait (`painting`): a
render of the painted mesh, or the concept cropped; you pick. Gate: a contact sheet of every folder.

### export, install
- Export: the body pack with its own clips.json from `clips_blend` (today a body copies `clips_from`'s:
  `clips_from` becomes optional, set = copy, not set = own).
- Install: the hero entry from `roster` → `PlayerSelectionDict.json` (exists): `player_info_dir` its own
  `../Graphics/<c>/`, `painting` its portrait, `mesh_pack` its pack; display name, stats, loadout asked for
  at install.

## 2. Page
- "New character" opens the character kind: name, then concept (prompt box or upload), TRELLIS models, image
  slots; Save → its first run. The character page shows its base run on top ("Base model": phases, next step).
- Clip picker panel (previews, three picks, frame range).

## Checks (no new character needed until the last)
- 0: as above.
- reweight / roles / game_rig / clips on the barb's own UniRig output (`gear_test/barb_base_rigged.glb`,
  backfilled as the rig step's output): `rig_check.py` numbers vs `rigfix/barb_heat0.5.glb`; roles JSON vs `gear_test/barb_roles.json` (diff); `_nb` vs
  `barb_final_nb.glb` (bone and weight counts); retarget + player_clips frame counts vs today's `player.blend`.
- concept: dry-run prints prompt and config; one paid run (4 candidates, ~$0.5) when you say so.
- rig (pod): one run on a pod you start, on the barb's TRELLIS mesh; compare bone count / roles with his.
- sprites: render the barb's own mesh + clips into a scratch folder; frame sizes and anchor vs `Graphics/barb/`
  on the contact sheet: same figure height and feet line (not the same pixels).
- End to end: one new character you choose, through install, worn in game. Paid calls and a pod: yours to run.

## Decided (2026-11-14, you)
- Concept: text prompt, the model a setting, context passed the way each model takes it.
- Pose: the A-pose we use (the barb's).
- A new player is its own player: its own sprite folder and portrait, not the barb's.
- Clips: the anunaki set for now.

## Open
- Sit and slide frames when no anunaki clip is close: a still pose, or skip those folders (does the game need
  them for every hero? check `Player` before building `sprites`).

## Order and branches
`feat/new-character` from `feat/outfit-config`, own worktree. 0 → 1 (concept front back sides; then rig;
then reweight roles game_rig; then clips; then sprites; then export install) → 2. One commit per step, barb
check each time.

## Not in this plan
- Armour fits only the body it was made on (`equipment.fits()`): `character_pipeline.plan.md` step 3.
- Non-humanoid bodies (wings, tails: NOTES_rig_jaw_sam3 §2), new slot rules for robes / capes.
- Clip sources beyond the anunaki set; cast attacks; evolution stages.
