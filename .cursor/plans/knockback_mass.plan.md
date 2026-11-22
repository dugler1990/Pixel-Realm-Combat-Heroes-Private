# Plan: knockback by mass (damage chunk 1)

Written 2026-11-14. Chunk 1 of `docs/damage/NOTES_damage_and_armour.md`. Branch
`refactor/knockback-mass`, worktree `..\Pixel-Realm-knockback`, started from `docs/damage-armour`
(so merging it also brings the damage docs).

## What is there today (read 2026-11-14)

- **One live path**: `Entity.apply_impulse` (`Entity.py:1137`). Every shove reaches it through an
  `impulse` InteractionContext: leap slam (`abilities/leap_slam.py:377`), meteor blast
  (`meteor_strike.py:644`). It moves the hitbox by the force as given (against walls when it knows
  them), then adds `force × follow_through` to velocity. **Mass is not used.**
- Meteor alone cuts its shove by target strength (`meteor_strike._target_knockback_factor`:
  `max(0.55, 1 − 0.015 × strength)`, strength 5 when the target has none).
- `Entity.weight` (`Entity.py:84`, always 1.0) only scales walking acceleration. Not touched here.
- **Dead, not paths**: the master doc called these knockback paths; they never run.
  - `hit_reaction` (`Enemy.py:556`, `combat_unit.py:877`, `friendly.py:569`; called from their
    updates and `rts/entities/tribe_member.py:138`): fires only while `vulnerable` is False, and
    no enemy ever sets it False (the line is commented out in every `get_damage`). So enemy
    `resistance` is read into an attribute and never used.
  - Parry knockback writing `player.rect` (`MeleeCombatStrategy.py:63`, `MixedCombatStrategy.py:67`):
    those modules are not imported anywhere; the live strategies are the classes in
    `CombatStrategy.py`.

## Target

- Every body has `mass` (and `gear_weight`, 0 until armour has weights).
- `apply_impulse` scales the shove by `knockback_scale(body)`:
  `clamp(REFERENCE_MASS / (mass + gear_weight), SCALE_MIN, SCALE_MAX) × strength_cut(body)`.
  - `REFERENCE_MASS = 90` (the barb): the player is moved exactly as today by everything except the
    strength cut below.
  - `SCALE_MIN 0.1`, `SCALE_MAX 3.0`: a 5-mass spirit is not thrown 18×.
  - `strength_cut`: meteor's rule moved here, for every shove: `max(0.55, 1 − 0.015 × strength)`,
    strength from `stats["strength"]` or `.strength`; **no strength = no cut** (meteor used 5).
- Meteor loses its own factor (no double cut).
- `resistance` leaves `monster_data`; each entry gets `mass` on the same line. `hit_reaction` and the
  `resistance` attribute go (dead code, no behaviour change).
- Not in this chunk: the dead strategy modules (`MeleeCombatStrategy.py`, `MixedCombatStrategy.py`,
  `RangedCombatStrategy.py`): flagged, left alone. Walking `weight`: left alone.

## Masses (first numbers, from the damage roster)

| monster | mass | today → after (shove vs a 90 barb) |
|---|---|---|
| demon | 400 | 1 → 0.23 |
| squid | 60 | 1 → 1.5 |
| tribey_snake | 20 | 1 → 3.0 (cap) |
| raccoon | 80 | 1 → 1.13 |
| spirit | 5 | 1 → 3.0 (cap) |
| bamboo | 30 | 1 → 3.0 |
| ice_ghost | 20 | 1 → 3.0 (cap) |
| tribey_spear | 70 | 1 → 1.29 |
| demon_dog | 40 | 1 → 2.25 |
| venom_plant | 200 | 1 → 0.45 |
| ice_mage | 70 | 1 → 1.29 |
| eskimo / jungle worker | 70 | |
| eskimo / jungle chief | 80 | |
| warrior_* (entity pipeline) | 70 | |

Meteor on enemies without strength: today 0.925 × force, after: mass scale × force.

## Changes

| file | change |
|---|---|
| `Settings.py` | `REFERENCE_MASS`, `KNOCKBACK_SCALE_MIN/MAX`, `STRENGTH_KNOCKBACK_CUT`, `STRENGTH_KNOCKBACK_FLOOR`; `monster_data`: `resistance` → `mass` |
| `Entity.py` | `self.mass = REFERENCE_MASS`, `self.gear_weight = 0.0`; module function `knockback_scale(body)`; `apply_impulse` scales dx, dy |
| `combat_unit.py`, `Enemy.py`, `friendly.py` | `self.mass = monster_info["mass"]`; `resistance` and `hit_reaction` removed with their calls |
| `rts/entities/tribe_member.py` | `hit_reaction()` call removed |
| `meteor_strike.py` | `_target_knockback_factor` and its constants removed |
| `tools/entity_pipeline/wire.py` | nothing: it copies a template entry, so new entries get `mass` |

Both client and server read `mass` from `monster_data`, so they agree.

## Tests

- New `tests/damage/test_knockback.py`:
  - a body at `REFERENCE_MASS` with no strength moves exactly the force (today's number);
  - mass 360 moves a quarter; `gear_weight` counts as mass;
  - very light bodies stop at `SCALE_MAX`, very heavy at `SCALE_MIN`;
  - strength cuts as meteor did; no strength, no cut;
  - every `monster_data` entry has a positive `mass` and no `resistance`.
- `tests/abilities/test_impulse_interaction.py`: CombatUnit cases use the first monster (demon,
  400): expected displacement follows `knockback_scale`; stub cases unchanged (no mass = reference).
- Whole suite before and after; any new failure explained or fixed.

## Check in play (Douglas)

Ice map: leap slam into the demon (barely moves), into tribey_spear / small things (fly further);
a meteor on the barb (same as before unless strength is set).

## Commits

1. This plan.
2. Mass and `knockback_scale` (Settings, Entity, units, meteor) with tests.
3. Master doc: chunk 1 log line; the "three paths" claim corrected.
