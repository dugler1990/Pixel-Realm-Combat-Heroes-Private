---
name: ""
overview: ""
todos: []
isProject: false
---

# Plan: temperature (after damage chunk 7)

Written 2026-11-18. Chunk 7 is committed on `refactor/elemental`. The fire, ice, lightning and lava
watches are uncommitted on that same branch. This plan does not change those scenes until its own
build. Worktree `..\Pixel-Realm-elemental`. Stamina is `feat/stamina` in `..\Pixel-Realm-stamina`
and is not on this branch.

## Goal

Hot and cold are one warmth. The air, a blow, a hold and exertion all write it. You are red or
blue from that number. A long swing from one side to the other hurts. A level can sit past the
line where warmth starts wounding, and an ordinary body left there dies. Weather can move the
level's number later. It does not in this plan.

## The one rule

A full body (you, and anyone later marked `"detail": "full"`) keeps two warmths. Each is a value
and the moment it was set. The current value is the curve already used for heat and cold, read
when something asks. Nothing in this system walks a crowd.

- **Piece.** The layer a blow or a hot place heated. It fades toward the air. A faint red shows
under `COOK` and does not wound. The three reds above `COOK` stay as they are.
- **Skin.** Fades toward the piece while that piece is warmer than the skin, and toward the air
otherwise. The three blues stay on the skin. A warm plate and a fading blue can share you for
a moment, while the plate's heat arrives. You do not sit at searing and severe together.

A simple body has no store. A fire spit and a ghost chill on a warrior stay the one-shot from
chunk 7.

Comfortable is 0. Heat is positive, cold is negative. `COOK` (5), `SLOW_AT` (10), `HURT_AT` (12),
`HEAT_K` (0.25) and `COLD_K` (0.02) stay the lines they are. New knobs below are the first test
numbers, tuned in play.

## Decisions

1. **The level has one air.** Default 0. A scene or, later, the map sets it. No weather, no

   per-tile temperature. The pull toward that air is mild: `AIR_K` 0.01, far below `HEAT_K`.
    The destination can sit past a wound line. A mild map (air between `-SLOW_AT` and `COOK`)
    never wounds by itself. An ice field and a desert do.
2. **Past a line, the wound is a rate.** A blow that spikes and fades still pays its area once,

   the cook or the cold sum from chunk 7. A source that holds you past the line does not fade, so
    that same sum is a rate for as long as you are held there. The integral is solved when the
    source changes or the clock wakes, not subtracted every frame. Held forever, an ordinary body
    dies.
3. **What the air does to the skin is one product.** Hot or cold, the same three factors, in

   this order, and nowhere else:

    `reached = direction × max(0, |air| − resist) × (1 − insulation) × (20 / vitality)`
   - **Resist.** Hot air subtracts fire resist. Cold air subtracts ice resist. Both go through
   `resist_of`, which a blow already uses. Ice resist is implemented on body cards (the ice
   ghost is 100, the ice mage is 80, the squid is 20). The hero's card, `barb`, has neither
   fire nor ice resist, so the weather reaches him whole. A resist at least as big as the air
   makes that air 0. He can be immune to the ice field by ice resist, and immune to the desert
   by fire resist. The clamp stays `max(0, resist)` until chunk 9, so a negative resist does
   not make the weather worse yet.
   - **Insulation.** How much of what remains reaches the skin. This is the chest's outer layer,
   the same layer `chest_layer` and the lava rate already read. Naked is the hide, insulation 0,
   so the whole remainder arrives. The plate chest is 0.2 and the loincloth is 0.1, already
   written on those item bases. Clothes cut the ice and the sun by that fraction. Plate at 0.2
   does not save an ordinary body in the ice field: −30 becomes −24, still past the hurt line.
   It buys time and a milder settle. Do not add the boots to the belt to the chest. One layer.
   - **Vitality, for now.** There is no constitution stat. The cold blow still uses constitution
   10 inside `elemental`. The air does not. It reads `stats["vitality"]`, and a missing stat is
   20, the ordinary barb from the stamina notes. 20 naked in the ice field settles at −30 and
   loses health. Immunity while naked needs vitality past 50 (the settle falls under
   `HURT_AT` at 50 and is clear of it above that). Health only decides how long the rate takes.
4. **A blow is not the air.** Insulation on a spit still stops the blow and heats the piece, the

   chunk 7 rule. Heat already stored in the piece fades more slowly by the same chest insulation,
    so a plate that has been heated keeps it. That is the desert backflip: the sun arrives reduced
    by insulation and fire resist, and the slides' heat then stays in the plate.
5. **A blow is an impact.** Its cook wound is `heat_wound` of that blow's own heat, paid at the

   instant, and cold already on you does not shrink it. If the jump crosses 0 by at least
    `HURT_AT`, a shock is added: `heat_wound` of the distance. A step that stays on one side is
    the cook only. The result is written into the piece and fades toward the air at `HEAT_K`, so
    a spit is gone in a few seconds. Cloth at or above `CATCH` still burns: full power, 6 s,
    searing on that cloth. A chill does not turn a caught cloth into a warm plate.
6. **A hold lasts while the touch lasts.** The ghost, inside the melee radius he already has

   (50), pulls a full body's skin toward a mild cold (`-SLOW_AT`). Faint blue, the small slow,
    no wound, and he does not re-apply ice 20. He is stronger than the air and weaker than the
    ice field. When he steps off, the pull stops and the skin fades toward the air. A simple body
    still takes today's one-shot chill. Lava keeps heat 100 and the rate it already has, and that
    rate is added into the piece store while you stand in it. Stepping off stops adding. Lava does
    not keep a second damage number beside the store.
7. **Exertion adds heat to the skin.** `exert(paid)` adds `paid × EXERT` (`EXERT` 0.15). One

   slide is 20 stamina, so one slide is +3 warmth: enough to matter against a mild cold, and a
    string of them pushes a hot body further over `COOK`. The cardio wound stays in stamina: each
    unpaid point is 2 health, already built. The sun's wound is this store crossing `COOK`. Both
    can land on one dash. This branch cannot see `stamina.pay`. The watch calls `exert` directly.
    When the branches meet, `pay`'s `paid` is the caller. This plan does not edit `feat/stamina`.
8. **Colour is the live number.** Faint red on the piece from `FAINT` (2) up to `COOK`. The three

   reds above `COOK` stay. The three blues on the skin stay, from `-SLOW_AT` downward. The player's
    flame is fire 5; on plate that is heat 4, which today does nothing and in this plan is the
    faint red.

## What is there today (read 2026-11-18)

- `damage_rules.elemental` prices fire and cold independently, from zero. A fire spit on plate
(insulation 0.2) is heat 12, hot, wound about 3, shell about 3.5 s. A ghost chill is ice 20,
one melee hit, severe, wound 9, about 3.5 s. They do not read each other. `apply_element`
starts `hot_shell` or `chilled` from that one price.
- The ghost swings that chill about once a second while he is in reach. He does not pour a mild
cold the whole time he is touching you.
- `HeatEffect` ticks a rate while you stand in a patch and, on exit, starts one `hot_shell` when
one second of that rate is above `COOK`. The benchmark has no lava. The `lava` watch places
heat 100 and draws the existing red outline.
- No level has an air temperature. The mesh "ambient" is a light level, not heat. Sunspine is a
desert in the art only.
- Stamina (`feat/stamina`, uncommitted): cap `max(40, vitality × 8)`, a slide spends 20, `pay`
returns `paid` / `shortfall` / `health_lost`, shortfall is 2 health a point, regen
`0.04 × vitality` after 450 ms. `pay` does not add heat.
- Ice and fire resist are implemented for a blow, through `resist_of`. They are on the body card.
`barb` has none. The ice ghost has ice 100. Insulation is on the item base: plate chest 0.2,
loincloth 0.1. `chest_layer` already returns that outer chest layer, and `patch_rate` already
multiplies by `(1 − insulation)`.
- The hero has no constitution stat. A cold blow uses 10. Vitality is the stamina pool. On this
branch the stat may be missing; the air treats missing as 20.
- Watches on this branch, uncommitted, current behaviour only: `fire`, `ice`, `lightning_jump`,
`lava`. Headless: `fire` dropped 3, hot on a plate piece, skin not hot. `ice` dropped 9, cold
severe. `lightning_jump`: one archer lost 100, the other two and the dog lost 0. `lava`:
dropped 221, searing.

## Numbers

| | |
|---|---|
| Comfortable air | 0 |
| Mild cold / mild heat, for a map that only nudges | −4 / +3 |
| Ice field, the deadly watch | −30 before resist, clothes and vitality |
| Desert, the sun watch | +20 before fire resist |
| Ghost hold | −10 (`SLOW_AT`), wound 0 |
| `AIR_K` | 0.01 |
| `FAINT` | 2 |
| `EXERT` | 0.15 per stamina paid |
| Shock | crosses 0 by at least 12, then `heat_wound` of the distance |

The ordinary body is vitality 20, fire resist 0, ice resist 0, naked. He settles at −30 in the
ice field and at +20 in the desert, and both wound him. Vitality 60 naked settles the ice at −10,
under the hurt line. Ice resist 30 naked settles it at 0. Plate insulation 0.2 at vitality 20
settles the ice at −24, still wounding, slower than naked. Fire resist 30 settles the desert at 0.

## Check in play

The `fire` and `ice` watches stay, and their meaning changes with this build.

- `fire`. Full plate, the demon dog's spit. A hot flash on the piece, then it fades. The cook
wound still lands. Skin stays untinted unless the piece's heat reaches it.
- `ice`. Full plate, the ghost walks onto you and stays. Faint blue and a small slow while he is
there, not a severe wound every second. He steps off, the blue fades. A warm plate delays the
blue.

Two new watches. Headless solves the long stay. The window shows the colour and the health
falling, not the whole death.

- `ice_naked`. Air −30, nothing worn, no exertion, vitality 20. Skin goes blue and health falls.
The test, not the window, says vitality 20 crosses the hurt line, vitality 60 does not, and
ice resist 30 does not. The same air in plate at vitality 20 still crosses, later than naked.
- `desert`. Air +20, full plate, repeated `exert(20)`. The plate holds the heat, health falls
from the sun, faster with the slides than standing still. The test says fire resist 30 does not
fall from the sun alone.

`lava` and `lightning_jump` are unchanged in meaning. Lava's damage comes from the store after
this build, so its probe numbers move and the scene stays a probe.

## Tests (`tests/damage/test_rules_magic.py`, no display)

The table, solved, no pygame.

- Air 0, no blow: stays 0.
- Flame on plate (heat 4): faint red, wound 0, and that 4 delays a ghost hold.
- Spit on plate from 0: the chunk 7 cook wound, then fade under `COOK` in the same few seconds.
- Spit onto skin at −10: the cook of the spit, plus a shock, finish warm, not blue.
- Equal hot and cold in one jump: finish near 0, shock is the wound.
- Ghost hold alone for a long time: settles at −10, wound 0, slow on.
- Ice air −30, vitality 20, naked, ice resist 0: settles at −30, crosses `HURT_AT`, the solved
wound reaches the body's health. Vitality 60: settles at −10, wound 0. Ice resist 30, vitality
20, naked: settles at 0, wound 0.
- Same ice, plate insulation 0.2, vitality 20, ice resist 0: settles at −24, crosses later than
naked, still wounds.
- Desert +20, fire resist 0, naked: settles at 20 and wounds. Fire resist 30: settles at 0.
Plate 0.2 and fire resist 0: settles at 16, still wounds.
- Desert, plate, three `exert(20)`: hotter, and a larger wound, than standing still.
- One `exert(20)` from a mild cold (−4): finishes closer to 0.
- Caught cloth still burns for the full power. A ghost hold does not clear it.

Regression: the targeted set. Same 11 known failures. Perf: one solved air interval and one blow
onto a stored warmth, in `Code/NOTES_performance.md`. A handful of multiplies. Not per frame, and
not the 200-enemy scene.

## How it is built

One pure function owns the weather. Everything else either calls it or does not to

uch the air.
The steps below are the order. A step is not started until its tests pass. No entity, no pygame,
and no scene until step 3.

1. `**air_on_skin(air, resist, insulation, vitality)` in `damage_rules.py`.** Returns the signed

   warmth the skin is being pulled toward. The product in decision 3, and nothing more. It calls
    `resist_of` for `"fire"` when `air >= 0` and for `"ice"` when `air < 0`. It does not read an
    entity. Tests are the rows in the table: naked 20, vitality 60, ice resist 30, plate 0.2,
    desert fire resist 0 and 30. `elemental` is not modified in this step. A blow must not start
    calling `air_on_skin`.
2. **The store, still pure.** Two samples, skin and piece. A sample is `(warmth, at_ms, target, k)`.

   `warmth_at(sample, now)` is the existing exponential. `wound_between(sample, t0, t1)` is the
    cook or the cold sum for the time the value sat past `COOK` or `HURT_AT`, solved, not a loop
    of frames. Changing the target (the air result, a ghost hold, lava starting or stopping)
    samples "now" first, adds any blow, then stores the new target. Tests feed timestamps. They
    do not construct a player.
3. **One writer, `temper`, in `hit_resolve.py`.** A full body only. It reads the two samples,

   calls `air_on_skin` with `chest_layer(entity).insulation` and `resist_of` from the body card
    and `stats.get("vitality", 20)`, asks `wound_between` for the gap since the last sample, adds
    a blow's cook and shock if this call is a blow, and writes the samples back. Health changes
    by that one returned wound. Simple bodies do not call `temper`. They keep `apply_element` and
    `elemental` exactly as they are.
4. **Wire the four sources into that writer, and no second path.**
   - The level air is an argument `temper` already read. Setting `level.air` does not apply damage
    by itself.
   - A fire or ice blow on a full body goes through `temper` once inside `apply`. The cook is
   computed from the blow before it is added to the sample, so a stored chill cannot shrink it.
   - The ghost, in his existing melee radius check: if the target is full, set the skin target to
   −10 and do not strike ice 20. If the target is simple, strike ice 20 as today. Leaving the
   radius clears the hold and the skin target returns to `air_on_skin`.
   - Lava's `get_environmental_damage` stops returning a separate amount for a full body. It sets
   the piece target from the heat it already computes. Exit clears that target. A simple body
   keeps today's lava tick, because it has no store.
5. **The clock wakes the writer.** The next time the solved curve crosses `COOK` or `HURT_AT`, or

   the next point of wound, is one entry on the condition clock that already peeks once a frame.
    That wake calls `temper` with no new blow. There is no per-frame subtract on the player, and
    lava does not also subtract.
6. **Scenes last.** `ice_naked`, `desert`, then the new meaning of `fire` and `ice`.

Do not do these. They are the ways this goes wrong.

- Resist subtracted in `air_on_skin` and again inside `_sticks` for the same air.
- Insulation summed over every worn piece, or a second insulation number invented for weather.
- Vitality and constitution both scaling the air.
- `elemental` growing an air argument, so simple bodies and blows start sharing the weather path.
- The ghost's ice-20 strike left on for a full body, beside the hold.
- Lava's old per-frame health loss left on beside `wound_between`.
- A per-frame loop that moves the warmth by `k * dt` instead of the solved sample. The sample is
the only copy of the number.

## Files

- `Code/damage_rules.py`: the read, the air pull, the shock, the faint line, the held-past-line
integral. `elemental` stays the price of a hit that finds a simple body at zero.
- `Code/hit_resolve.py`: a full body reads the store, applies the blow or the hold, writes the
store, and schedules the wake on the condition clock. Simple bodies keep `apply_element`.
- `Code/Effect.py`: lava's rate feeds the piece store. Exit only stops that feed.
- The ghost's melee: against a full body, in radius sets the hold and out of radius clears it.
No new loop. The ice-20 strike stays for a simple body.
- `exert` lives next to the store. No edit on `feat/stamina`.
- `Code/combat_validation_driver.py`: `fire` and `ice` match the new meaning; add `ice_naked` and
`desert`.
- `docs/damage/NOTES_damage_and_armour.md`: this plan, then the build.

## Commits

1. This plan. Master doc points here. Log.
2. The pure rule and the table.
3. The store on a full body, the ghost hold, lava into the store, the four watches, the perf line.

   Master doc: temperature built, log. Stamina still not wired.

## Open

- `AIR_K`, `FAINT`, `EXERT`, ice −30 and desert +20 are the test numbers.
- Constitution as a real stat replaces the `20 / vitality` factor when it exists, and whether the
stamina pool then reads it too belongs to the stamina work. Until then the air reads vitality.
- `pay` calling `exert` waits until `feat/stamina` and this branch are the same code.
- Weather replaces the level's one number later. Same store.
- Which maps are the ice field and the desert is a number on the map when those levels are played.
Until then only the watches set the air.