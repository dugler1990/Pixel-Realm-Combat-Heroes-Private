# Plan: weapons through the armour flow

Goal: a weapon made exactly like an armour set: he is drawn holding it, TRELLIS on the whole figure, fit to his
rig, paint, SAM3 finds the weapon by its keywords, cut, HoloPart completes what the fist hides, then it is a piece
on the hand bone. Any held thing (sword, axe, bow, staff, shield) is a new keyword list and prompt, not new code.
The standalone weapon kind (`weapon`, grip step: concept alone + `weapon_grip.py`) stays as a cheap test; dropped if
it gets in the way.
Proof throughout: the barb's armour outputs do not change (`_checks/barb_unchanged.py`, `view_prompts_unchanged.py`).

## Status 2026-11-14
Written, nothing built. Branch `feat/new-character` (worktree `Pixel-Realm-new-character`).

## 1. Prompts: him holding it (config)
- `view_prompts/held_weapon.json`: front / back / side / 3/4 "keep his exact pose (the A-pose); in his right hand
  he holds {weapon}, gripped in his fist, hanging down and held clear of his body". The weapon text comes from the
  outfit (`held` field, e.g. "a short iron sword"); one file for every weapon.
- Front check: `cover` as armour (the weapon may reach outside his outline; his body must stay covered as drawn).
- Pose: the A-pose kept, so the joint lines and the side checks stay valid.

## 2. SAM3: find it (config)
- The outfit's `sam` table names the weapon's keywords per crop ("sword", "blade", "hilt"; a bow: "bow", "string")
  and `prompt_to_part` maps them to the part `weapon`; everything else is `body`, as the loincloth cut does.
- Per weapon type a small prompt table in `explode2/` (sword, axe, bow, staff, shield).

## 3. Code (small)
- `explode/explode_common.piece_weights`: `weapon` (`weapon_l` / `weapon_r`) rigid, 100 % the hand bone.
- `explode2/armour_slots.py`: part `weapon` -> slot `weapon_r` (or `_l` by the side it is on).
- `equipment.PIECES`: `weapon_r` / `weapon_l` (a hand slot), `piece_base` -> base `<material>_<weapon type>`
  for item stats (`item_bases.json`).
- Worn test: the weapon posed with the hand (already: `--rigid`).

## 4. Game (bigger, own step)
- The player draws a worn `weapon_r` piece with the hand (as armour pieces now), equip / unequip from the
  inventory; stats from its base. Checked in game by eye.

## Checks
- 1-2: dry-run prompts for a held sword; barb armour prompts unchanged (16 cases).
- 3: tests for the weapon rule and slot; the barb's fullplate slots unchanged.
- First real run (paid calls + pod, yours): one sword on the barb through the armour flow; look at TRELLIS (thin
  blade merged into the leg?), the SAM masks, the HoloPart grip, the worn sheet.

## Risks
- TRELLIS may join a thin blade to the leg: the prompt holds it clear; look at the first run.
- The fingers around the grip stay in the body mesh; the game's hand stays as the rig has it.
- Paint's close-ups are body regions: a long weapon may be painted less sharply.

## Not in this plan
- Two-handed weapons; fitting the attack clip to a weapon; a closed-hand pose.
