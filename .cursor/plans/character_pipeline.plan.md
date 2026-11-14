# Plan: the mesh pipeline made per character (not barb-only)

Goal: the outfit pipeline and the mesh player take a character as input. Everything barb-specific moves into a
character file; the barb is the only one filled in. Other characters' values (rig, clips, roster, stats) are
not known yet: the file has the fields, a new character fills them later. No new character is built here.
Proof throughout: the barb's outputs do not change.

## What is barb-only today (read on main 7d42ac5b, 2026-11-14)
| Where | What |
|---|---|
| `explode2/outfit_skeleton.py` (outfit `skeleton` step) | every new mesh is put on `rig_fit`, the barb's rig. No route makes a character's first rig |
| `outfit.py` front step | always redraws a `concept` against an outline; no way to take a hand-made front as is |
| `retarget_bvh.py` `TARGETS["barb"]` | rig and roles paths in code, per target |
| `player_clips.py` defaults | `settle_01`, `jokesillyrun`, `overheadchop` 45-60,108-138: the barb's picks |
| `export_outfit.py` `clips_json` | copies `Graphics/Meshes/barb/clips.json` |
| `export_outfit.py` roster entry | "Barbarian", `barbarian.png`, `../Graphics/barb/`, his stats, `slide` / `leap_slam` |
| outfit files | `rig_fit`, `rig_game`, `roles`, `clips_blend` repeated in each barb outfit |
| `repaint/repaint.py` look default | subject "barbarian hero" (each outfit's `paint_look` already overrides it) |
| `Code/equipment.py` | a worn item names a `mesh_piece`; nothing checks the piece was made for this body |
| `Main2._bootstrap_rts_validation_run` | picks the barb (harmless) |
Already per character: data folder `<Boss>/generated/bosses/<character>/`, outfit prompts, paint looks,
`Graphics/Meshes/<pack>/`, `player_mesh.py` (draws any pack on any sprite body).

## 1. Character file
`tools/boss_sprite_pipeline/characters/<character>.json`; `characters/barb.json` filled from today's values:
- `rig_fit`, `rig_game`, `roles`, `clips_blend` (an outfit may still override)
- `clips`: `idle`, `move`, `attack` source names + attack frames
- `retarget`: `bind_match`, `arm_elev_cap`, `digitigrade`
- `roster`: `display_name`, `painting`, `sprite_body` (`player_info_dir`), `roster_stats`, `base_stats`,
  `evasion_loadout`
- `concept_front`: the hand-made front image (empty for the barb: made before the pipeline)
A field a step needs and the file lacks stops that step with its name ("characters/<c>.json has no clips.attack"),
never a silent barb default.
Readers: `outfit.py` (outfit merged over character), `retarget_bvh.py --target` (character files, then the
code table for the bosses), `player_clips.py` (`--character`), `export_outfit.py` (clips.json and roster entry).
**Check:** barb commands `--dry-run` before / after: same commands and paths (diff). `naked` export entry: same
JSON (diff). `retarget_bvh --target barb`: same profile dict printed. Tests pass.

## 2. First-rig route: outfit `kind: "base"`
Steps: `front back sides trellis rig reweight roles clips paint export`. Makes a character's `rig_fit` /
`rig_game` / `roles`; later outfits use the existing `body` / `armour` / `cut` routes on it.
- `front`: `concept_front` taken as the accepted front (no redraw); its cut-out is the outline for back / sides.
- `rig`: UniRig on the pod (`backends/unirig.py`, `gpu_box/unirig_cli.py`), push / run / pull like trellis,
  `RIG_OK`.
- `reweight`: `rigfix/rig_reweight.py heat 0.5`. `roles`: `rigfix/anun_roles.py`. Neutral-bone fix:
  `explode2/fix_neutral_bone.py`.
- `clips`: `retarget_bvh.py --source anunaki --target <character>`, then `player_clips.py --character`.
- Writes the made paths back into `characters/<character>.json`.
**Check without a new character:** run `reweight roles clips` on the barb's own UniRig output
(`gear_test/barb_base_rigged.glb`) via `--backfill`-style inputs; compare with his existing `rigfix/` results:
`rig_check.py` numbers (PROCESS_rigfix), roles JSON (diff), clip frame counts. `rig` (pod) untested until a
character needs it; dry-run prints the push list.

## 3. Game side
- Roster entry written from `roster` (step 1); pasting stays by hand.
- `equipment.py`: a mesh piece fits only the body it was made on. Slot packs record their body (character or
  `rig_game` sha1) in pack meta; `fits()` compares with the wearer's `mesh_pack`'s. Sprite heroes unchanged.
**Check:** tests with a fake second body: barb plate refused on it, accepted on the barb; existing tests pass;
the barb in game wears plate as before (by eye).

## Order and branches
1 → 2 → 3, each its own branch and worktree from main. 1 is pure refactor and goes first. `feat/outfit-pipeline`,
`feat/armour-slots`, `feat/mesh-equipment` have no commits outside main (2026-11-14); recheck before 1.

## Not in this plan
- Any new character (values, concept, pod runs). Lore: `docs/lore/CHARACTERS.md`.
- Evolution stages (new base per stage, or one base + pieces).
- Clips beyond the anunaki set (a cast attack).
