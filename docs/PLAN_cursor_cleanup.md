# Plan: tie up the uncommitted work (Nov 2026)

Started 2026-11-20. Cursor left work uncommitted across worktrees. Goal: each piece simple, clear,
well contained, committed, then merged when Douglas says.

## Method (every item)
1. Review: read the code (no tests): bugs, duplication, special cases, dead code.
2. Talk it through with Douglas; decisions go in the item's own plan (`PLAN_*.md` in its folder).
3. Build on its own branch and worktree, one commit per step, targeted tests before/after
   (FAILED names compared), guard tests where a rule must stay true.
4. Douglas watches what has a scene. Merge, push, delete: only when he says.
- Cursor's uncommitted copy stays untouched until Douglas decides what happens to it.
- No legacy folder: git history is the archive.
- A number lives in one place in data. A rule lives in one place in code.

## Items, in order

### 1. Elemental + temperature: in progress
- Committed: `refactor/elemental` (damage chunks 1-7, 37 commits on main) → `refactor/damage-path`
  (`..\Pixel-Realm-damage-path`): one damage path `a5e6aa45`, foundation cleanup `202fdcfd`..
  `17fe7c3a` (`docs/damage/PLAN_damage_foundation.md`, done).
- Cursor's WIP: `..\Pixel-Realm-elemental`, 11 files, ~1.2k lines, plus untracked
  `.cursor/plans/temperature.plan.md`.
- Review found (2026-11-20): the ghost's cold hold sticks after he dies or leaves, and two ghosts
  flip it every frame; cold took health directly; one 80-line `temper()` with a special case per
  source; imports inside functions; duplicated thresholds and checks.
- Next:
  - 1a. Temperature rebuild: `docs/damage/PLAN_temperature.md`. A heat network solved exactly:
    layers (skin, worn piece) hold warmth; sources pull them (the body as a heater by vitality, air,
    lava, the ghost's hold, keyed by who placed them, released on death); insulation weakens the
    piece-skin link; only the skin wounds, through the resolver; events and clock wakes only.
  - 1b. Cleanup with it: imports at the top, no functions passed as arguments, `warmth_shade`
    calls `heat_shade`, no `_ticks`; Cursor's single-sample maths replaced by the network solver.
  - 1c. Docs: what is still true from `temperature.plan.md` and the WIP's doc entries moves into
    the new plan and `NOTES_damage_and_armour.md`.
  - 1d. Douglas watches the scenes.
  - 1e. Archive commit of Cursor's WIP on `refactor/elemental`; merge the stack into main (his go).

### 2. Stamina
- `feat/stamina` (`..\Pixel-Realm-stamina`), at main, all uncommitted: `stamina.py`,
  `NOTES_stamina.md`, `test_stamina.py`; edits to Player, UI, Settings, dash.
- Dash spends stamina; an empty dash costs health (must now go through the resolver).
  Leap and ice clone still spend energy.
- Wires its `pay` to temperature: every stamina point spent is heat (`HEAT_PER_STAMINA`).

### 3. Water combat
- `feat/water-combat` (`..\Pixel-Realm-water-combat`), on `visual-hits` (carries 30 damage commits);
  its own work uncommitted: 5 hole shapes in the test_suite arena (keys 1-5),
  `PROCESS_test_suite.md`, a time-of-day pin in Weather.
- `feat/water-hole`: the older copy, superseded.
- Swimming and motion parked.

### 4. Level studio + review page
- `feat/level-studio` (`..\Pixel-Realm-level-studio`): studio page (source → compose → scale →
  snap → grid → prepare → cell review), `test_studio.py`.
- `feat/level-review-fit` (`..\Pixel-Realm-level-review-page`): Upscale tab (RunPod HYPIR; only
  disconnects, the pod is stopped by hand), register-level, `3_4.png`, `bitter_floe_7x6_play/`.
- Both at `253e2240`, 57 behind main: merge main in first. The orphan `bitter_floe_07` in the main
  folder likely comes from the studio.

### 5. Anim web
- `feat/anim-suite` (`..\Pixel-Realm-anim-suite`), at main, uncommitted: `anim_web.py`,
  `web/anim.html`, a rigmap, `PROCESS_anim_web.md`, tests.

### 6. Ice fog
- Main folder, `feature/ice-fog-test-core` at `b581b6e6`, uncommitted: `Code/ice_fog/`, dialogue
  whispers (`session.py`, `wind_whispers.json`), `ice_fog_walk` scenario, tests and fixtures,
  `Code/NOTES_ice_fog_test_plan.md`. Not wired into Level4.
- `ice_lost_fog.py`: alias, nothing imports it.
- Mixed in, not ice fog: `perf_status.md` edit and 3 plan files (older copies of `perf/targeting`'s),
  `notes.txt` ideas, a `docs/ideas` raw file, `bitter_floe_07` level files.
- Its `rts_validation_driver.py` edit touches the same file as water-hole's.

### 7. Housekeeping (each removal asked first)
- Worktrees already merged into main: view-shape-gate, outfit-pipeline, mesh-equipment,
  mesh-player, item-card, pose-check, dialogue, process-docs.
- `feat/water-hole`; `perf/targeting` (done, 84 behind main); `dev_3d_boss` (115 behind, 4 dirty
  files); `feat/entity-web` (3 commits, not merged).

## Decided (Douglas, 2026-11-21)
- Cursor's temperature WIP: after the rebuild, one archive commit on `refactor/elemental`, never
  merged; that worktree ends clean.
- The damage stack (chunks 1-7 + damage-path + temperature) merges into main as one piece when
  item 1 is done and the scenes are watched. Items 2-6 build on main after that.
- Exertion: temperature ships `bump()` with no exertion caller; item 2 wires stamina's `pay` to it.

## Log
- 2026-11-20: queue set; item 1 reviewed.
- 2026-11-20: one damage path, `a5e6aa45`.
- 2026-11-21: damage foundation steps 1-7, to `17fe7c3a`.

## Tried and dropped
- Temperature, air pre-shrunk by clothes and vitality (Cursor): dropped for the body as a
  source. Plate heat to skin in small steps: dropped for the exact solve.
- Temperature, strongest source wins: dropped. Weighted average instead: two ghosts chill faster,
  never colder than a ghost; lava on ice lands between.
- Legacy code folder for deleted classes: dropped. Git history is the archive.
- 20 new per-monster attack defs for monster damage: dropped. A monster's attack stat instead.
- Invulnerability as a default post-hit window: dropped. A condition a source grants.
