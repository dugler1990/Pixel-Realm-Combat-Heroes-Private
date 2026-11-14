# Plan: the inventory, restructured for wearable pieces

Status 2026-11-14: plan only. Branch `feat/mesh-equipment` (worktree `Pixel-Realm-mesh-equipment`), on top of
`4f8fe279` / `4dffdbfd` (pieces wearable and drawn; PROCESS_equipment.md).

Goal: armour from the inventory onto the mesh hero, easy to use with arrows / d-pad, and code that is easy to
reason about. Now: `Code/Inventory.py` does layout, drawing, input, slot rules, belt and armour in one class;
three cursors (body / pack / belt) joined only by Tab; body cursor only Left / Right in list order; a wrong
slot does nothing silently; the mesh update hides in `sync_belt_from_waist`; left / right slots are the same
string; start gear is read from the mesh folder inside the 1700-line level.

## 0. Rules (decided before code)
- **One cursor.** Arrows / d-pad move to the slot in that direction, across body, pack and belt. Tab stays
  as a shortcut (next area), not needed.
- **Held item shows where it goes.** Slots it fits: glow. Others: dimmed. A full slot it fits glows too
  (Enter swaps).
- **Sides are real.** Slots `shoulder_l`, `shoulder_r`, `arm_l`, `arm_r`, `legs_l`, `legs_r`, `boots_l`,
  `boots_r`, `weapon_l`, `weapon_r`. A piece made for a side (pack slot `shoulder_l` ...) fits only that side.
  Items with no side (old sprite-game boots, weapons) fit either.
- **One waist kind.** Belt, loincloth, armour belt: all `effect_type "waist_equip"` with `belt_slots` (and
  `mesh_piece` if drawn). `simple_belt` in standard_items.json changes from `belt_equip`; old saves / items
  with `belt_equip` read as waist (one alias in `equipment.py`, nowhere else).
- **Enter on armour in the pack** (hand empty) puts it on (into its slot; swaps what is there back to the pack).
- Mirror image: the doll faces you, so his left is on screen right. Slot `_l` = his left = screen right.
  (Check against the pack names: `shoulder_l` must be the piece on his left arm.)

## 1. `Code/equipment.py` (new, no pygame)
- `SLOTS`: one row per body slot: `id`, `kind` (helmet, armor, shoulder, arm, weapon, legs, boots, waist),
  `side` (l / r / None), doll rect (shares of the doll picture, from today's `DOLL_SLOTS`).
- `item_slot(item) -> (kind, side) | None`: the one reader of `effect_type` / `effect.slot`. Accepts
  `armour_equip`, `waist_equip`, `belt_equip` (alias).
- `fits(slot, item) -> bool`: the one rule. Armour slot: same kind and side (or item has no side). Weapon
  slot: weapons and non-armour as today. Waist: waist items. Pack: anything. Belt: `_can_place_on_belt`
  (moves here) and not locked.
- `slot_for(item, slots) -> slot | None`: where "put on" goes (empty fitting slot first, else the fitting one
  to swap).
- `worn_pieces(body_items) -> [mesh pack names]`, `belt_capacity(waist_item) -> int`.
- Tests: `tests/test_equipment.py` rewritten against this module, no pygame.

## 2. Inventory model (`Code/Inventory.py`, slimmed)
- Slots keep a list; each `InventorySlot` gets `id` (`helmet`, `shoulder_l`, ..., `pack_0`..`pack_11`,
  `belt_0`..`belt_3`) and `area` (body / pack / belt). Index constants kept for callers
  (`waist_slot_index`, `backpack_start_index`, `belt_start_index`, `slot("waist")`).
- Changes only through: `lift(slot)`, `place(slot)` (place / stack / swap), `add_item`, `wear(item)`,
  `take_off(slot)`, `return_hand_to_backpack`, `use_*`. Each ends in one `_changed()`: belt capacity from
  the waist (dump locked pockets to the pack), then `player.refresh_equipment()`.
- `sync_belt_from_waist` kept as a one-line alias of `_changed` for Level4 / old callers, marked to remove.
- Callers today: Level4 (seed, close inventory), trade.py (`selected_backpack_index`, `focus_region`,
  `display(placed=...)`), Player (`add_item`, `has_room_for`, `worn_pieces`), belt HUD. Kept working.

## 3. Inventory view and input (`Code/inventory_view.py`, new)
- `layout(kit, placed)`: today's `_layout`, body rects from `equipment.SLOTS`.
- `draw(...)`: today's `display`; plus held-item glow / dim from `equipment.fits`; the held item drawn on the
  cursor slot as now.
- Navigation: `neighbour(slot, direction)`: the nearest slot whose centre is in that direction (within a 45°
  cone, nearest by distance weighted to the straight line), over every visible slot's rect. Computed from the
  laid-out rects, so trade's side-by-side layout works too. Locked belt pockets skipped; belt skipped
  without a waist item.
- One cursor `cursor_id`. `selected_backpack_index` / `focus_region` stay as properties over it (trade.py).
- Keys: arrows move, Enter lift / place (empty hand on armour in pack: put on), U use, Tab next area, Esc /
  I close (held item back to the pack, as now).

## 4. Gamepad (separate step; nothing in the game reads a pad today)
- InputManager: pad d-pad / left stick → the same "just pressed" directions, A → Enter, B → drop held / close,
  Y → use. Only if wanted now; else later.

## 5. Start gear out of the mesh folder
- Hero entry in `Graphics/PlayerSelectionDict.json`: `"start_equipment": {"wear": [...], "pack": [...]}`.
  Level4: one call `equipment_start(player, item_spawner)` (in `equipment.py` or a small helper), not nested in
  the belt seed. Default (no entry): the simple belt as today.
- `export_outfit.py` prints `start_equipment` in the selection entry (it already prints the entry to paste)
  instead of writing `equipment.json`. `Graphics/Meshes/barb/equipment.json` → the barb mesh entry.

## 6. `player_mesh.py` tidy
- `self.pieces = {}`, `self._piece_cache = {}` in `__init__` (no class-level dict, no `__dict__` trick);
  `MeshBoss`, `logging`, `VIEW_ELEVATION_DEG` imported at the top (check no import cycle).

## 7. Pipeline side
- `equip_install.py`: items get the side from the pack slot (`shoulder_l` → slot `shoulder`, side `l`; belt /
  loincloth → `waist_equip`); `BODY_SLOT` map goes to `equipment.py` (one table).
- `outfit_items.json` regenerated; icons unchanged.

## 8. Checks
- `tests/test_equipment.py`: fits (side, kind, waist alias, belt lock), slot_for, worn_pieces, belt capacity.
- New `tests/test_inventory_nav.py`: from every slot each direction lands where expected on the default layout
  (table of expected moves: helmet ↓ chest, chest → shoulder? etc. written down first), no slot unreachable,
  no dead end except edges.
- Existing: `test_inventory_room.py`, trade tests, the 19 mesh / render / inventory / level files: same 12
  failures as base, none new (names diffed).
- By hand: run the game, Barbarian (mesh): pick up each piece, its slot glows; arrows reach every slot without
  Tab; put on all 10, take off, he changes. Screenshot of the held-item glow, looked at.

## Order
0 agreed → 1 → 2 → 3 → 6 → 7 → 5 → 8 by hand. 4 (pad) asked separately. Each step: tests pass, commit.

## Open
- Doll left / right: his left on screen right (mirror) or screen left? Default above: mirror.
- Mesh hero start: naked + loincloth needs the naked pack (paint pending, Leonardo key); until then the barb
  mesh with its own loincloth.
