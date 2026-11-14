# Plan: a second mesh hero (the ice wizard), and the pipeline made per character

Goal: the outfit pipeline and the mesh player work for any character, not only the barb. The first new
character is the ice wizard (`docs/lore/CHARACTERS.md`). Order: lift the barb's hard-wired values into a
character file with no change to the barb's output; then add the missing first-rig route; then run the wizard
through it.

## What is barb-only today (read on main 7d42ac5b, 2026-11-14)
| Where | What | Blocks the wizard? |
|---|---|---|
| `explode2/outfit_skeleton.py` (outfit `skeleton` step) | aligns every new mesh onto `rig_fit` (the barb's rig) and gives it his bones | **yes**: a lean body on a giant's joints. He needs his own first rig |
| `outfit.py` front step | always redraws a `concept` against an outline. The barb's concept was his own body | yes: the wizard's front *is* the concept (the hand-made image) |
| `retarget_bvh.py` `TARGETS["barb"]` | rig and roles paths hardcoded per target | yes: a target per character in code |
| `player_clips.py` defaults | `settle_01`, `jokesillyrun`, `overheadchop` 45-60,108-138 picked for the barb | partly: a caster wants a cast, not a chop |
| `export_outfit.py` `clips_json` | copies `Graphics/Meshes/barb/clips.json` | yes |
| `export_outfit.py` roster entry | "Barbarian", `barbarian.png`, `../Graphics/barb/`, barb stats, `slide` / `leap_slam` | yes |
| `repaint/repaint.py` look default | subject "barbarian hero" (the outfit's `paint_look` already overrides it) | no: a wizard look file |
| outfit prompts | "beard, hair bun, loincloth" | no: per outfit already |
| `Code/equipment.py` | a worn item names a `mesh_piece`; nothing checks that the piece was made for this body | yes, once two mesh heroes exist: barb plate drawn on the wizard |
| `Code/player_mesh.py` / `Player` | mesh is draw-only on a sprite body (`player_info_dir`), height from that sprite | no: the wizard rides `Graphics/Orange_Wizard/` |
| `Main2._bootstrap_rts_validation_run` | picks the barb | no |
Data is already per character: `<Boss>/generated/bosses/<character>/`.

## 1. Character file. Barb output unchanged
`tools/boss_sprite_pipeline/characters/<character>.json`:
- `rig_fit`, `rig_game`, `roles`, `clips_blend` (moved out of each outfit; an outfit may still override)
- `clips`: `idle`, `move`, `attack` source names + attack frames (player_clips defaults become the barb's)
- `retarget`: `bind_match`, `arm_elev_cap`, `digitigrade` (the `TARGETS` row)
- `roster`: `display_name`, `painting`, `sprite_body` (`player_info_dir`), `roster_stats`, `base_stats`,
  `evasion_loadout`
- `concept_front`: the hand-made front image
`retarget_bvh.py` also reads `--target` from character files (the code table stays for the bosses).
`export_outfit.py` takes clips.json and the roster entry from the character file.
**Check:** the barb's commands with `--dry-run` print the same commands and paths as before (diff). The
`naked` export entry is the same JSON as before (diff). Tests pass.

## 2. First-rig route: `kind: "base"`
Steps: `front back sides trellis rig reweight roles clips paint export`.
- `front`: the concept is accepted as the front (no redraw); its cut-out is the outline for back and sides.
- `rig`: UniRig on the pod (`backends/unirig.py`, `gpu_box/unirig_cli.py`; the barb's was made this way,
  `gear_test/barb_base_rigged.glb`). A pod step like trellis: push / run / pull, `RIG_OK`.
- `reweight`: `rigfix/rig_reweight.py <rigged> <out> heat 0.5` (the barb's pick, PROCESS_rigfix).
- `roles`: `rigfix/anun_roles.py` (walks the skeleton; no hand numbering).
- `clips`: `retarget_bvh.py --source anunaki --target <character>`, then `player_clips.py` with the character's
  clip names.
- Then the `body` path's `paint` and `export`. The result is the character's `rig_fit` / `rig_game`; his later
  outfits (`naked`, robe, armour) use the existing `body` / `armour` routes on it.
Known from the barb, folded in: `fix_neutral_bone.py` (stray loincloth vertices streak once the root
travels); arms raised 70° stretch the shoulders (joint position, still open).
**Check:** `rig_check.py` numbers (bones, influences, edges jumping > 0.3) next to the barb's in PROCESS_rigfix;
pose sheet `explode_pose.py --texture` 6 poses × 4 views, by eye.

## 3. The wizard's base
- Concept: Leonardo gpt-image-2.5 "flare", "Professional / graphic design 2D illustration", 1024², the barb's
  original jpg as Image 1 (`Downloads\gpt-image-2.5-flare_Professional_graphic_design_2D_illustration_Full-body_3D_character_model_render_-0.jpg`).
  Prompt in the session of 2026-11-14 (to be copied into `outfits/<wizard>/base.json` with the attempt).
  A tight wool wrap, not a flap (the barb's flap left an outline gap). Same pose, framing and height in the image.
- `outfit.py <wizard> base` → pod (trellis, rig) → his pack `Graphics/Meshes/<wizard>/`.
**Check:** loads as a PlayerMesh with 3 clips; walk 8 directions in game next to the barb.

## 4. Game
- Roster entry: `mesh_pack: <wizard>`, `player_info_dir: ../Graphics/Orange_Wizard/` (sprite body for hits,
  collision, abilities; it has the magic attack).
- `equipment.py`: a mesh piece fits only the body it was made on. Pack meta records its body (`rig_game`
  sha1 or character); `fits()` checks it against the wearer's `mesh_pack`. Sprite heroes unchanged.
**Check:** tests: barb plate refused on the wizard, accepted on the barb; existing tests pass.

## 5. Later, not in this plan
- His outfits (robe, cult wraps) via `armour` / `cut` on his rig.
- Evolution stages (Keeper / Hoarfrost): either a new base per stage (new rig, outfits redone per stage) or one
  base with painted / added pieces (crystals, frostbite as texture + slot packs). Decide before stage 2 art.
- Caster clips (Kimodo or a new BVH source); the anunaki set has no cast.

## Order and branches
1 → 2 → 3 → 4. Step 1 is pure refactor and goes first so the barb stays the proof. Step 3's concept image can
be made now, in parallel (no code). Branch per step from main, own worktree. `feat/outfit-pipeline`,
`feat/armour-slots`, `feat/mesh-equipment` have no commits outside main (2026-11-14); recheck before step 1.

## Open
- Wizard name; cult take A / B / C.
- Bare base (the `naked` redraw) or the wrap as his base.
- Evolution: new base per stage or one base with pieces.
