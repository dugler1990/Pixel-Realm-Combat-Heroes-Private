# Wearable pieces in game: process

Armour slots and the loincloth (outfit pipeline slot packs, `PROCESS_outfit.md`) as inventory items that a mesh
player puts on and takes off. Branch `feat/mesh-equipment`. Plan: `.cursor/plans/inventory_equipment.plan.md`.

## Method that works

Pipeline, after an outfit's export (`outfit.py ... export` made `<run>/packs/<slot>/`):
```
$env:OUTFIT_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
Code\sprite_venv\Scripts\python.exe -m tools.boss_sprite_pipeline.equip_install barb fullplate
Code\sprite_venv\Scripts\python.exe -m tools.boss_sprite_pipeline.equip_install barb loincloth
```
- packs → `Graphics/Meshes/<pack>/<slot>/`; icons (`explode2/piece_icons.py`, 3/4 front, rest pose, 256 px)
  → `Graphics/Standard_Items/outfits/<pack>_<slot>.png`; items → `Graphics/Standard_Items/outfit_items.json`.
  `--items-only`: only the items, from the packs already installed (no run folder, no Blender).
- Piece → item: one table, `Code/equipment.py` `PIECES` (+ `BELT_POCKETS`). Armour: `armour_equip`
  `{slot, side, mesh_piece}`; belt / loincloth: `waist_equip` `{belt_slots, mesh_piece}` (loincloth 1 pocket,
  armour belt 2, simple belt 1). `belt_equip` = old name of `waist_equip`, read the same.
- Each item gets `"base"` (its stats in `Graphics/Standard_Items/item_bases.json`): the outfit json's
  `"material"` + the piece, left and right sharing one (`plate_boot`); no material: the piece (`loincloth`).
  A new outfit needs its bases written there (`docs/damage/NOTES_damage_and_armour.md`).
- Sides are the hero's: `_l` = his left (+X in model space) = screen right on the doll (it faces you).
- Start gear: the hero's `Graphics/PlayerSelectionDict.json` entry, `"start_equipment": {"wear": [...],
  "pack": [...]}` (`equipment.start_equipment`, matched by `mesh_pack`; none: the simple belt). Seeded by
  `Level4._seed_start_equipment` into an empty body only. `export_outfit.py` prints it in the entry to paste.

Game code:
- `Code/equipment.py`: rules only, no pygame. `BODY` (13 body slots: id, kind, side, place on the doll),
  `wearable`, `fits(kind, side, item)` (the one rule), `belt_pockets`, `worn_pieces`, start gear.
- `Code/Inventory.py`: the model. Slots (`id`, `kind`, `side`), the hand; changes: `lift`, `place`,
  `put_on` (pack → its body slot, swaps), `wear`, `use`, `add_item`, `return_hand_to_backpack`. Every change
  ends in `_changed()`: pockets from the waist item (pockets that close empty into the pack), then
  `Player.refresh_equipment` → `PlayerMesh.set_pieces(inventory.worn_pieces())`.
- `Code/inventory_view.py`: layout, drawing, keys. One cursor; arrows go to the nearest slot that way
  (`neighbour`: ahead within ~63°, sideways distance counted double) over doll, pack and open belt pockets.
  Enter lifts / places; on armour in the pack, puts it on. U uses. Tab: next area. Held item: the body / belt
  slots it fits glow (`kit.fit_glow`), others fade (`kit.faded`).
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
| inventory: only Tab reached the body, Left / Right stepped the body in list order, a wrong slot did nothing silently | three cursors joined by Tab; no fit shown | fixed: one cursor by direction, fit glow (inventory_view.py) |

## Log

- 2026-11-14: built. GPU check (GTX 1050): barb + all 10 v9 plate pieces line up with the body in idle, move and
  attack at 4 facings (`draw_equipment.py`); chest + boots + one pauldron mixes. Skin pokes through in places;
  dark specks in the plate paint (v9 paint, not the draw). 11 icons checked by eye. Tests: `tests/test_equipment.py`
  5 pass; the 19 test files touching mesh / render / inventory / level: the same 12 failures as on
  `feat/outfit-pipeline` before this branch (names diffed), none new.
- 2026-11-14: inventory restructured (plan above): equipment.py / Inventory.py / inventory_view.py, one cursor,
  glow, sides, waist_equip, start gear in PlayerSelectionDict.json. Tests: test_equipment 13, test_inventory_nav
  7 (expected moves at 800×600, 1280×720, 1920×1080; every open slot reachable with 0 / 1 / 4 pockets). Window
  rendered (CPU) holding a boot and a pauldron, looked at: its slot glows, the rest fade. GPU draw check same as
  before.
- Not yet done: playing it by hand, the naked body pack (paint pending), hiding skin under pieces, gamepad.

## Tried and dropped

- Glow at wash 46 / edge 200 alpha, fade 120: the fitting slot hard to tell from faded ones in the render; now
  70 / 255 (3 px), fade 150.
