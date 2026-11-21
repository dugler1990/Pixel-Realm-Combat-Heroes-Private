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
- Step 3 done: the thermostat (warming `WARM_K` anywhere, sweating `SWEAT_K × bare`, switch at
  0), resting heat, the sun (`set_sun`, layer number `sun_absorb`: plate 0.8, loincloth 0.4, skin
  and hides 0.5 by default), `exert(body, stamina, now)`, `HOT_SCALE` for the skin's heat wound
  (a blow's cook keeps `HEAT_SCALE`). Link `CONTACT_K / insulation`. Tests 14.
  Numbers (feel targets, `tools/temperature_table.py`, 10 s): `AIR_K` = `WARM_K` = `SWEAT_K` 0.02,
  `REST_HEAT` 0.02, `SUN_K` 0.1, `CONTACT_K` 0.08, `PIECE_CAP` 0.05, `HEAT_PER_STAMINA` 0.02,
  `COLD_SCALE` = `HOT_SCALE` 2. Desert = air +10, sun 1; ice field = air −30.
  | Target | Result |
  |---|---|
  | plate, desert, standing: hurts ~30 s | 34 s, dead 144 s |
  | plate, desert, a slide a second: hurts ~10 s | 12 s, dead 70 s |
  | naked, desert, vitality 20: slowly dangerous | hurts 34 s, 3.5 hp/s, dead 345 s |
  | naked, ice, vitality 20: dead in a few minutes | 308 s (plate 454 s) |
  | vitality 60, ice | safe, any wear |
  | mild, standing, any wear | never hurts, no red (skin 0.2-1.0) |
  In full plate in the heat vitality does not cool you (sweat is trapped): only more health.
  Bench after: settle 80-128 µs, 0.053-0.085 ms per frame (machine noisier: frame off 3.3-4.1 ms).

## The model, for reasoning (Douglas, 2026-11-21; revised the same day after the table)
- **Layers hold warmth**: the skin, and the worn outer chest piece if there is one (naked: skin
  only; the loincloth is on the waist, so it counts as naked). 0 is comfortable, heat positive,
  cold negative. Capacity: skin 1; a piece from its weight (heavy plate holds heat longer).
- **The body makes heat**: a small resting amount (`REST_HEAT` per second on the skin), and every
  point of stamina spent (`HEAT_PER_STAMINA` per point, a jump on the skin). The same for everyone.
- **The body's thermostat** pulls the skin toward 0, with two strengths:
  - warming (shivering, holding blood in), when the skin is below 0: `WARM_K × vitality / 20`,
    anywhere, armour or not;
  - cooling (sweat), when the skin is above 0: `SWEAT_K × vitality / 20 × bare`, where `bare` is
    the share of the body's regions with nothing worn. Armour traps sweat.
  The strength switches when the skin crosses 0 (one more line the wakes watch).
  Vitality is the thermostat (and, through stamina, how much heat a body can make).
- **Outside sources**, on the outer layer (the piece if worn, else the skin):
  - the level's **air** pulls toward its temperature (`AIR_K`); fire resist shrinks a hot air
    toward 0, ice resist a cold one;
  - the level's **sun** adds heat per second, `SUN_K × sun × sun_absorb` of the outer layer
    (metal plate high, cloth and skin lower; black more than shiny, per item later);
  - **lava** (per patch) and a **hold** (the ice ghost's touch, from its attack def) pull like air.
- **A link** joins the piece and the skin, `CONTACT_K / insulation`: insulation is resistance, both
  ways; a piece with none is bare skin.
- **Bumps** are instant jumps: a blow on the layer it hit, stamina spent on the skin.
- **Only the skin wounds**: `HOT_SCALE × (skin − COOK)` per second above `COOK`,
  `COLD_SCALE × (−skin − HURT_AT)` per second below `−HURT_AT`.

What falls out, with no special case:
- Naked in ice: the air beats the warming, the skin passes `−HURT_AT`, death. Higher vitality:
  stronger warming, maybe safe. Metal plate helps a little (cold metal, low insulation); a fur
  with high insulation would help a lot (later).
- Plate in the desert: the sun heats the plate, the plate heats the skin, sweat is trapped:
  overheating, faster when dashing (stamina is heat).
- Naked in the desert: the sun hits skin that soaks up less, and sweat works: hot, survivable.
- Two ghosts chill faster but never colder than a ghost; lava on an ice field lands between.
- A hot plate delays a ghost's blue: the ghost cools the plate first.

## Feel targets (Douglas, 2026-11-21): the numbers are tuned to these
| Setup | Target |
|---|---|
| Plate, desert, standing | starts hurting after ~30 s |
| Plate, desert, dashing hard (a slide a second) | starts hurting after ~10 s |
| Naked, desert, vitality 20 | slowly dangerous: a few minutes |
| Naked, ice field, vitality 20 | dead in a few minutes |
| Vitality 60, ice field | safe |
| Any wear, mild air (0), no sun, standing | never hurts, no red |

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

## The store: `Code/temperature.py`
- `join(body, level, now)`; `forget(body, now)` on death (its store goes, every source it placed
  on others comes off).
- `add_source(body, key, T, k, now, placed_by=None)` / `remove_source(...)`: outside sources on
  the outer layer.
- `bump(body, layer, amount, now)` → the shock wound (the hit's price adds it).
- `settle(body, now)`: pay the wound since the last settle through the resolver (whole points;
  `kind="damage"`, `source_kind="temperature"`, `source_team="environment"`; `invulnerable` blocks
  it; no hit sound), re-solve, paint, schedule.
- `set_air(level, air, now, bodies)`, `set_sun(level, sun, now, bodies)`; `refresh(body, now)` on
  equip and vitality change.
- **Wakes**: the level's own queue (`level.warmth_wakes`, `tick` from the Level4 frame): the next
  line crossing (`FAINT`, `COOK`, the reds, 0, the blues, `−HURT_AT`), or `TICK_MS` later while
  the skin is past a line, or the horizon while still moving. A body at rest has none.
- **Paint** at each settle: heat shade on the outer layer (faint from `FAINT` to `COOK`, then the
  three reds) as `hot_shell`, cold shade and the `chilled` slow on the skin; conditions start only
  when the shade changes. Caught cloth (`burning`) stays a condition.

## Who calls it
| Source | Where | Does |
|---|---|---|
| Air, sun | level / scene: `set_air`, `set_sun`; equip: `refresh` | default air 0, sun 0 |
| Blow (fire, ice) on a full body | `hit_resolve` | `bump`; price = blow + shock; no `hot_shell` / `chilled` start |
| Hold | melee strategy, attack def with `hold` | in reach of a full body: `add_source(("hold", id))`, no strike; out of reach, new target: `remove_source` |
| Lava | `HeatEffect` apply / remove | full body: `("lava", id)` source, no tick; simple body: today's tick |
| Stamina spent | stamina's `pay` (item 2) | `exert(body, paid, now)`: a jump of `paid × HEAT_PER_STAMINA` on the skin; no caller in this plan |
| Death | `Entity.die` | `forget(self)`: a dead ghost lets go |

Data: `ghost_chill` gets `"hold": {"T": -10, "k": …}` in `attacks.json`. A new layer number
`sun_absorb` (0..1) in `item_properties` and `item_bases.json` (plate 0.8, loincloth 0.4) and on
the body cards' natural layer (default 0.5). Constants in `damage_rules`: `AIR_K`, `WARM_K`,
`SWEAT_K`, `REST_HEAT`, `HEAT_PER_STAMINA`, `SUN_K`, `CONTACT_K`, `PIECE_CAP`, `TICK_MS`,
`FAINT`, `HOT_SCALE`, `COLD_SCALE`, with the existing `COOK`, `SLOW_AT`, `HURT_AT`.
`tools/temperature_table.py` reads the feel targets off a table: naked / loincloth / plate ×
vitality 20 / 40 / 60 × mild / ice −30 / deep ice −60 / desert / hot desert, standing and dashing.

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
3. **Model fixes, then numbers**: `tools/temperature_table.py` (built). Add the thermostat's two
   strengths (switch at 0, `bare` share), resting heat, the sun (`set_sun`, `sun_absorb`), and
   stamina as heat (`HEAT_PER_STAMINA`). Tests: sweat trapped by armour; the sun on plate vs skin;
   the switch at 0 is exact. Then tune to the feel targets; numbers into the notes.
4. **Wire the sources**: air and sun (scenes and levels), blows in `hit_resolve`, lava, hold from
   the attack def. Tests: ghost dies while holding → skin warms back; two ghosts, one leaves → still
   held; hot plate delays the blue; lava on ice lands between.
5. **Scenes, docs, guard**: port the 5 scenes, run headless; notes (rules, log, method), perf line
   in `NOTES_performance.md`; guard rules: no `temper(`, no `_ghost_hold`.
6. **Douglas watches** `fire`, `ice`, `ice_naked`, `desert`, `lava`. Then item 1e (archive
   Cursor's WIP, merge the stack).

## Open
- More layers (cloth under plate, boots): one more layer in the network, later.
- Constitution as a real stat may replace vitality in the thermostat (stamina work).
- Sun and fire resist: whether fire resist cuts the sun too (today it cuts hot air only).
- Weather moving the air: later; same `set_air`.

## Tried and dropped
- One `temper()` writer taking every source as an argument (Cursor, 2026-11-18): a special case
  per source, and the ghost's hold stuck after he died. Replaced by sources on a network.
- Strongest source wins: dropped for the weighted pull.
- Air pre-shrunk by insulation and vitality (`air × (1 − insulation) × 20/vitality`, Cursor):
  dropped for the body as a source. Clothes then trap heat both ways, which the product could not.
- Plate heat reaching the skin in small steps (refreshed every ~0.5 s): dropped for the exact
  solve; steps lag or overshoot when sources change fast.
- The body pulling toward comfortable with one strength both ways (step 2, first table,
  2026-11-21): plate came out cooler than naked in the desert, dashing too. Replaced by the
  thermostat (warming anywhere, sweat only through bare skin), the sun as heat on the outer
  layer by `sun_absorb`, and stamina spent as heat.
- Insulation as `CONTACT_K × (1 − insulation)`: a piece with no insulation still slowed heat.
  Replaced by `CONTACT_K / insulation`.
