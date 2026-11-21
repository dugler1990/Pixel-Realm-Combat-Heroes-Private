# Plan: temperature as a heat network

Item 1a of `docs/PLAN_cursor_cleanup.md`. Branch `refactor/damage-path` (`..\Pixel-Realm-damage-path`),
on the damage foundation (`17fe7c3a`). Replaces Cursor's uncommitted temperature work
(`..\Pixel-Realm-elemental`, `.cursor/plans/temperature.plan.md`): same goal, new model.
One commit per step; targeted set before/after (same 11 known failures).

## Goal
Hot and cold are one warmth on a full body (`detail == "full"`; today the player). Air, sun, lava,
the ice ghost's touch, blows and exertion move it. Red or blue and the slow come from the live
number. Past `COOK` (heat) or `-HURT_AT` (cold) the skin wounds, as a rate while it stays there;
an ordinary body left in an ice field or a desert dies. Clothes keep you warm in the ice and
cook you in the sun, from the same rule. A simple body keeps today's one-shot `elemental`
price, untouched.

## Status
- Step 1 done (`5daf89a2`): `Code/heat_network.py`, `tests/damage/test_heat_network.py`.
- Step 2 done: `Code/temperature.py` (store, settle, wake queue, paint), constants in
  `damage_rules`, `Entity.die` → `temperature.forget`, Level4 frame → `temperature.tick`;
  `tests/damage/test_temperature.py` (11); `tools/temperature_bench.py`.
  - Solver by hand for 1 and 2 layers (numpy for more), a reach bound that skips lines a curve
    cannot meet, turning points found once per layer, false position for the crossing.
    Per call, 2 layers: solve 9 µs, first crossing of 6 lines 29 µs, heat+cold area 31 µs.
  - Bench, real Level4, 100 squids frozen at −30 in air −60, all wounding, 3 runs: frame mean off
    2.85-3.02 ms / on 2.92-3.10 ms (noise), p95 4.81-4.95 / 4.84-4.99; settle 52-66 µs each,
    0.026-0.033 ms per frame. Every monster can have temperature.
  - Deviation: temperature keeps its own wake queue on the level (`level.warmth_wakes`), not a
    second heap in `ConditionClock`: `conditions.py` stays unaware of it.
  - `hot_shell` / `chilled` start only when the shade changes (a settle is not a new clock entry).

## The model, for reasoning (Douglas, 2026-11-21)
- **Layers hold warmth**: the skin, and the worn outer chest piece if there is one (naked: skin
  only). 0 is comfortable, heat positive, cold negative. Each layer has a capacity: skin 1; a
  piece from its weight (heavy plate holds heat longer).
- **Sources pull a layer** toward their temperature `T` with a strength `k`, while active:
  - the **body**: on the skin, `T` 0, `k` = `BODY_K × vitality / 20`. Always on: a heater set to
    comfortable, stronger with vitality.
  - **outside sources**, on the outer layer (the piece if worn, else the skin): the level's
    **air** (`AIR_K`), **lava** (per patch), a **hold** (the ice ghost's touch, from its attack def).
    Fire resist shrinks a hot `T` toward 0, ice resist a cold one. Nothing else scales them.
- **A link** joins the piece and the skin, `CONTACT_K × (1 − insulation)`: insulation is how
  much a piece slows heat crossing it, both ways.
- **Bumps** are instant jumps: a blow on the layer it hit, exertion on the skin.
- **Only the skin wounds**: `HEAT_SCALE × (skin − COOK)` per second above `COOK`,
  `(−skin − HURT_AT)` per second below `−HURT_AT`. A hot plate hurts by heating your skin.

What falls out, with no special case:
- Naked in ice: the air beats the heater, the skin passes `−HURT_AT`, health falls, death.
  Higher vitality: stronger heater, settles warmer, maybe safe.
- Plate in ice: the link is weak, the heater wins more: warmer, later or never past the line.
- Plate in the desert, dashing: sun heats the plate, exertion heats the skin, the weak link
  keeps that heat in: overheating.
- Two ghosts chill faster but never colder than a ghost; lava on an ice field lands between.
- A hot plate delays a ghost's blue: the ghost cools the plate first.

## The maths (exact, events only)
Between two events every source is fixed, so the layers follow
`C·x' = −(K + L)·x + K·T`: a linear system with a closed-form answer.
- Solver, pure (`damage_rules` or `heat_network.py`, no pygame, no entities): the steady state,
  plus one decaying exponential per layer (`numpy.linalg.eigh` on the symmetric form; real,
  negative rates). `state_at(t)`: a few exponentials.
- Wound between two instants: the integral of a sum of exponentials past a line: closed form.
  Crossing times of a line: a short bracketed search; the skin curve crosses a line at most once
  per layer of the network, so the search is bounded.
- Runs only on events (a source on/off, a blow, exertion, equip) and on the clock's wakes. Never
  per frame; only full bodies. Microseconds per run.
- **One rule for blows on a full body**: the blow bumps the layer it hit; its heat or cold wounds
  through the skin's time past the line, like any other heat. No instant cook, no `quiet_ms`.
  The shock (a jump that crosses 0 by at least `HURT_AT`) stays in the hit's price.
  Change from chunk 7 on a full body: a fire or ice wound lands over the next seconds, not at
  the hit. Simple bodies unchanged.

## The store: `Code/temperature.py` (new)
- `add_source(body, key, T, k, now)` / `remove_source(body, key, now)`: outside sources land on
  the outer layer.
- `bump(body, layer, amount, now)` → the shock wound (the hit's price adds it).
- `settle(body, now)`: solve to now, send the wound through the resolver as one hit
  (`kind="damage"`, `source_kind="temperature"`, `source_team="environment"`, `attack_type`
  heat/cold; `invulnerable` blocks it; no hit sound, as for lava), re-aim, paint, schedule.
- `set_air(level, air, now)`; `refresh(body, now)` on equip (layers, insulation, capacity) and
  vitality change.
- `release(holder, now)`: removes every source a body placed on others.
- **Wakes**: `ConditionClock`'s second heap (port of Cursor's `schedule_warmth`/`warmth_due`): the
  next line crossing (`FAINT`, `COOK`, `−SLOW_AT`, `−HURT_AT`), or `TICK_MS` later while the skin
  is past a line (the wound arrives in ticks, not one point at a time).
- **Paint** at each settle: heat shade on the outer layer (faint from `FAINT` to `COOK`, then the
  three reds), cold shade and `chilled` slow on the skin. Caught cloth (`burning`) stays a
  condition.

## Who calls it
| Source | Where | Does |
|---|---|---|
| Air | level / scene: `set_air`; equip: `refresh` | default 0, a mild map never wounds |
| Blow (fire, ice) on a full body | `hit_resolve` | `bump`; price = blow + shock; no `hot_shell` / `chilled` start |
| Hold | melee strategy, attack def with `hold` | in reach of a full body: `add_source(("hold", id))`, no strike; out of reach, new target: `remove_source` |
| Lava | `HeatEffect` apply / remove | full body: `("lava", id)` source, no tick; simple body: today's tick |
| Exertion | stamina's `pay` (item 2) | `bump(skin, paid × EXERT)`; no caller in this plan |
| Death | `Entity.on_death` | `release(self)`: a dead ghost lets go |

Data: `ghost_chill` gets `"hold": {"T": -10, "k": …}` in `attacks.json` (the attack holds, not
the ghost's name). Constants in `damage_rules`: `AIR_K`, `BODY_K`, `CONTACT_K`, `PIECE_CAP`
(per weight), `LAVA_K`, `TICK_MS`, `FAINT` 2, `EXERT` 0.15, with the existing `COOK`, `SLOW_AT`,
`HURT_AT`, `HEAT_SCALE`. All test numbers, tuned in play.
`tools/temperature_table.py` prints where each setup settles and how fast it wounds (naked /
loincloth / plate × vitality 20 / 40 / 60 × ice −30 / −60 / desert +20 / +40 × resist 0 / 30),
so tuning is read off a table.

## Kept from Cursor's work
- The goal and the test cases (as behaviour; numbers retuned to the new model).
- The clock's second heap; `HeatEffect` feeding the store; the scenes `fire`, `ice`, `ice_naked`,
  `desert`, `lava`; the faint red; `warmth_shade` (calling `heat_shade`).
- Not kept: `air_on_skin`'s product (the body source and the link replace it), single-sample
  `warmth_at` / `wound_between` / `spike_quiet_ms` (the network solver replaces them), `temper()`
  and its branches, the `_ghost_hold` / `_lava_heat` flags, `entity.health -= wound`, `_ticks()`,
  the `−(SLOW_AT − 0.5)` wake line and the 5 s hold re-arm.

## Steps
(Performance, 2026-11-21: Douglas asked whether 100 bodies could carry it. Step 2 adds the
fast paths and the bench; the numbers decide who gets temperature.)
1. **Solver**, pure. Tests, timestamps only: one layer matches the plain exponential; steady
   state is the weighted average; two layers conserve heat with no sources but the link;
   the wound integral matches a fine numeric sum; crossing times are right.
2. **Store**: `temperature.py`, the clock heap, `settle` through the resolver. Tests with a stub
   body: sources add and remove; two holds; invulnerable spends a tick; refresh on equip.
3. **Table and numbers**: `tools/temperature_table.py`; pick first numbers so naked vitality 20
   dies in the ice field, plate survives longer, vitality 60 is safe, plate in the desert with
   dashes overheats. Numbers into the notes.
4. **Wire the sources**: air, blows in `hit_resolve`, lava, hold from the attack def, `release`
   on death. Tests: ghost dies while holding → skin warms back; two ghosts, one leaves → still
   held; hot plate delays the blue; lava on ice lands between.
5. **Scenes, docs, guard**: port the 5 scenes, run headless; notes (rules, log, method), perf line
   in `NOTES_performance.md`; guard rules: no `temper(`, no `_ghost_hold`.
6. **Douglas watches** `fire`, `ice`, `ice_naked`, `desert`, `lava`. Then item 1e (archive
   Cursor's WIP, merge the stack).

## Open
- More layers (cloth under plate, boots): one more layer in the network, later.
- Constitution as a real stat may replace vitality in `BODY_K` (stamina work).
- Weather moving the air: later; same `set_air`.

## Tried and dropped
- One `temper()` writer taking every source as an argument (Cursor, 2026-11-18): a special case
  per source, and the ghost's hold stuck after he died. Replaced by sources on a network.
- Strongest source wins: dropped for the weighted pull.
- Air pre-shrunk by insulation and vitality (`air × (1 − insulation) × 20/vitality`, Cursor):
  dropped for the body as a source. Clothes then trap heat both ways, which the product could not.
- Plate heat reaching the skin in small steps (refreshed every ~0.5 s): dropped for the exact
  solve; steps lag or overshoot when sources change fast.
