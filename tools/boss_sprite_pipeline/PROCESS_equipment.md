# Wearable pieces in game: process

Armour slots and the loincloth (outfit pipeline slot packs, `PROCESS_outfit.md`) as inventory items that a mesh
player puts on and takes off. Branch `feat/mesh-equipment`.

## Method that works

Pipeline, after an outfit's export (`outfit.py ... export` made `<run>/packs/<slot>/`):
```
$env:OUTFIT_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
Code\sprite_venv\Scripts\python.exe -m tools.boss_sprite_pipeline.equip_install barb fullplate
Code\sprite_venv\Scripts\python.exe -m tools.boss_sprite_pipeline.equip_install barb loincloth
```
- packs → `Graphics/Meshes/<pack>/<slot>/`; icons (`explode2/piece_icons.py`, 3/4 front, rest pose, 256 px)
  → `Graphics/Standard_Items/outfits/<pack>_<slot>.png`; items → `Graphics/Standard_Items/outfit_items.json`
  (`item_id <pack>_<slot>`, `effect_type armour_equip`, `effect {slot, mesh_piece[, belt_slots]}`).
- Slot pack → inventory body slot: chest→armor, shoulder_l/r→shoulder, gauntlet_l/r→arm, pants_l/r→legs,
  boot_l/r→boots, belt / loincloth→waist (`BODY_SLOT` in equip_install.py). Waist pieces open belt pockets:
  loincloth 1, armour belt 2 (simple_belt 1).
- Start equipment: `Graphics/Meshes/<body>/equipment.json` `{"wear": [...], "pack": [...]}` (Level4
  `_seed_mesh_equipment`; without it the simple belt as before). A body outfit's `"start_equipment"` is written
  there by its export (naked: wears the loincloth, the 10 plate pieces in the backpack).

Game:
- Inventory doll: 13 body slots (`Inventory.BODY_SLOTS`): helmet, armor, shoulder ×2, arm ×2 (gauntlets), weapon
  ×2, legs ×2, boots ×2, waist. Armour slots take only armour made for them; the waist a belt or a waist piece.
- Every inventory change → `Player.refresh_equipment` → `PlayerMesh.set_pieces(inventory.worn_pieces())`.
- Draw (`PlayerMesh.draw`): the body clears depth once, 15 % wider than its box (`PIECE_CLEAR_PAD`); each piece
  draws about the BODY's pivot, at the body's scale, on the body's clip and frame, without clearing depth. The
  packs share model space (same skeleton and clips); each pack's own pivot is only its bottom centre.
- Check, no game: `Code\sprite_venv\Scripts\python.exe tools\boss_sprite_pipeline\_checks\draw_equipment.py
  <out.png> [--pieces all|none|a,b] [--body barb]`: idle / move / attack × 4 facings through the GPU backend.

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| a second skinned pack drew the first one's mesh | one shared VBO / EBO for every skinned pack, cached per pack name | fixed: buffers per pack (`_skin_pack_state`) |
| skin shows through the plate (chest in the attack, knees) | the body is drawn whole under the pieces | open: hide the body under worn pieces (as explode_pose `--hide-under`) |

## Log

- 2026-11-14: built. GPU check (GTX 1050): barb + all 10 v9 plate pieces line up with the body in idle, move and
  attack at 4 facings (`draw_equipment.py`); chest + boots + one pauldron mixes. Skin pokes through in places;
  dark specks in the plate paint (v9 paint, not the draw). 11 icons checked by eye. Tests: `tests/test_equipment.py`
  5 pass; the 19 test files touching mesh / render / inventory / level: the same 12 failures as on
  `feat/outfit-pipeline` before this branch (names diffed), none new.
- Not yet done: playing it (inventory by hand), the naked body pack (paint pending), hiding skin under pieces.

## Tried and dropped

(none yet)
