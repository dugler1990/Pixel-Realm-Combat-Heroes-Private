# Plan: elemental (damage chunk 7)

Written 2026-11-17. Revised 2026-11-18 after talk: ice is a body temperature, lightning carries
charge, reach and arcs, colour is three shades split between skin and what is hot. Chunk 6 is
committed on `refactor/conditions`. The build branch is `refactor/elemental`, cut from that branch.
Worktree `..\Pixel-Realm-elemental`.

## Goal

Fire, ice and lightning stop being a flat number. Fire catches a flammable layer, or heats that
layer until the heat falls off. An ice attack keeps its ordinary blow, and also applies cold to
body temperature. Lightning has its own damage, reach and arc count, and a strong bolt jumps
farther and more times than a weak one. The hero and anyone marked full get the curve. Everyone
else gets the same meaning in three shades and at most one jump. Holy, unholy and venom stay out
(chunks 9 and 8).

## The one rule

Every person and every monster already has a body card. Yours says `barb`. The demon's says
`demon`. It is a row in `bodies.json`: what the hide is like (how tough, how flammable, how well
it conducts), and what kind of creature it is. It is not a new part on the sprite, and it is not
a new stat you set in play. The monster list already points each monster at his card. You point
at `barb`.

An arrow, a fireball, a tree and a chest do not have a card. They are not creatures. A hit on one
of those stays the plain number it has today. There is no hide to heat and no skin to tint.

The damage function is one path:

1. The thing that was hit has a body card. Read that card, and the armour on the spot that was hit.
   Price the ordinary blow, then fire, then cold, then lightning. Health loss is those added up.
2. The thing that was hit has no card. Leave the hit's number alone.

You, the demon, the squid and a warrior all take step 1. The cards exist. For monsters the damage
function does not look at the card yet, even though their hide profile is already built from it.
This chunk makes it look. After that, a demon's hide stops an arrow, a spirit takes no fire, and
a squid counts as wet. Same path as you. The co-op server's copy of another player does not know
his card or his armour, so a hit on that copy stays the old flat number until co-op gear exists.

Full and simple are not two kinds of creature. They are how carefully step 1 is worked out.

- **Full.** You, and any monster we later mark `"detail": "full"`. The cold curve, and every jump
  the bolt is allowed.
- **Simple.** Every other monster. The same blow, the same fire, the same first lightning strike.
  Cold is one of three shades. Lightning jumps at most once.

A crowd stays cheap. A boss we care about gets the curve by marking him full. Until we mark any,
only you are full.

## Decisions

1. **Only fire, ice, lightning are priced.** Holy and unholy add nothing. Demon claw stays the
   crush number from chunk 5.
2. **A weakness is written down and not used yet.** Resists may be negative. The number subtracted
   is `max(0, resist)`. Chunk 9 drops the clamp. A parent adds: fire resist is the fire number plus
   the elemental number.
3. **Fire stays on the layer that was hit.** Power is `max(0, power − resist)`. Flammability at or
   above `CATCH` (0.5) starts `burning` and the wound is that power. Below `CATCH`, that layer
   stores heat and, above `COOK`, a `hot_shell` cooks and then ends. The cook wound is solved once,
   when the heat is applied.
4. **Cold is a temperature, not a second copy of the damage.** The attack's `damage`, delivery,
   penetration and force resolve as a normal blow. `cold` is extra. It is added to the body's cold
   (0 is normal). Constitution decides how much of that cold sticks, and how fast it falls off.
   The falloff is solved when the cold is applied. Colder means longer before he is back to normal.
   At or above `HURT_AT` he also takes a cold wound, the area under the curve until he warms past
   that line, solved once. Wet adds `WET_COLD` (8) to the cold that sticks.
5. **Lightning is four named numbers on the attack.** `damage`, `reach` (px at full charge),
   `arcs` (most jumps after the first body), `spark` (charge below this does not jump). A bare
   number in the file means that damage, and reach 0, arcs 0: it hits and does not jump.
   Charge starts at `damage`. A body takes `charge × (1 + conductivity) × (WET_MULT if wet)`.
   What it passes on is `charge × conductivity`, or `charge × 0.4` when it is wet and conducts 0.
   The next hop may reach `reach × (passed / damage)` px. The hop happens only when a bolt has
   just hit, the passed charge is at least `spark`, and arcs remain. One quadtree query for that
   radius, the nearest body not already in this bolt. Full detail may spend every arc. Simple
   detail spends at most one.
6. **Wet is a fact the rule reads.** The `wet` condition, or `starts: ["wet"]` on the body (the
   squid). The scene wets the hero for one beat. Nothing else wets him in this chunk.

## What is there today (read 2026-11-17)

- `hit_resolve.resolve` prices a delivery and returns None when there is none. Flame, ice ball and
  fire spit stay on today's amount.
- Magic is a category and a power. Ice and lightning have no `cold`, `reach` or `arcs` yet. A bare
  number keeps loading: ice uses it as `cold`, lightning uses it as `damage` with no jump.
- The mesh draws the body, then each worn piece, as separate `draw_mesh_boss` calls. Each call
  already takes a tint. Plate and skin can be different colours.
- Monsters already name a body card, and their hide profile is built from it. The damage function
  does not read that card for them yet, so a hit on a demon is still the old flat number.
- There is no constitution stat. Missing constitution is `BASE_CON` (10).
- `HeatEffect` deals `max(0, heat − fire_resistance) × dt` while you stand in a patch.
  `fire_resistance` is 0. Leaving leaves nothing.

## Numbers (first values, tune in play)

Fire, unchanged: `CATCH = 0.5`, `COOK = 5`, `HEAT_K = 0.25`, `HEAT_SCALE = 0.25`.
`H = power × (1 − insulation)`, `t = ln(H / COOK) / HEAT_K` when `H > COOK`,
wound `H − COOK − COOK·ln(H / COOK)`.

Cold: `COLD_K = 0.02`, `BASE_CON = 10`, `SLOW_AT = 10`, `HURT_AT = 12`, `WET_COLD = 8`.

Cold that sticks = `max(0, cold − ice resist) × BASE_CON / constitution`, then `+ WET_COLD` if wet.
It falls as `C·e^(−COLD_K·constitution·t)`. Time to fall from `C` to a line `L` is
`ln(C / L) / (COLD_K·constitution)`. The cold wound, when `C > HURT_AT`, is that same shape as the
cook: `(C − HURT_AT − HURT_AT·ln(C / HURT_AT)) / (COLD_K·constitution)`.

Three cold shades, on the skin draw only: mild at 10, medium at 15, severe at 20.
Speed −1 / −2 / −3 until cold falls under `SLOW_AT`. A colder hit stays slow for longer. A higher
constitution sticks less cold and sheds it faster, so the same spell slows him less and for less time.

Three heat shades, on the thing that got hot: warm above `COOK` (5), hot above 10, searing above 18.
The piece's draw takes the red. The body draw takes it only when the hot layer is the hide itself.

Lightning: `WET_MULT = 1.5`, wet carry `0.4`.

| blow | who | what happens |
|---|---|---|
| fire spit 15 | plate (ins 0.2) | H = 12, hot 3.50 s, wound 3, hot red on the plate, skin unchanged |
| fire spit 15 | barb hide | H = 15, hot 4.39 s, wound 5, hot red on the skin |
| fire spit 15 | loincloth (flamm 0.8) | burning 6 s, wound 15, searing red on the cloth |
| fire spit 15 | demon (fire 50) | 0 |
| spirit touch 9 | spirit (fire 100) | 0 |
| ghost chill, cold 20 | hero, constitution 10 | sticks 20, severe, slow 3.5 s (until cold < 10), cold wound 9, skin severe blue, plate unchanged |
| ghost chill, cold 20 | constitution 20 | sticks 10, on the mild line, duration 0, no cold wound |
| ghost chill, cold 20 | wet, constitution 10 | sticks 28, severe, slow 5.1 s, cold wound 29 |
| ghost chill, cold 20 | ice ghost (ice 100) | sticks 0 |
| storm bolt damage 50, reach 180, arcs 4, spark 12 | plate, then a wet hide 100 px away | plate takes 95 and passes 45; next reach 162, so the wet hide is in range and takes 45 × 1.5; it passes 18, next reach 65 |
| storm bolt, same | dry hide | takes 50, passes 0, the arcs are unused |

A simple body hit by cold 20 uses the shade table instead of the logarithm: severe, 6 s × `10/constitution`, speed −3, cold wound 8. Same shade, same idea, no curve.

Player flame in real play is fire `5 + magic stat`, then the fire rule. Ice ball is its force plus `cold` (10 + the magic stat). The cold is not added again as a flat health hit on top of the temperature wound.

## Rules

`elemental` stays pure. It does not search the world. It returns the wound, the conditions, the
heat shade for the layer that heated, and the lightning passed-on `(charge, reach_px)` when another
hop is allowed.

`apply`, which has the level, spends the hops. Full or simple is read off the body that was just
hit. The pure tests feed it bodies at known distances and check the charges. They do not build a
quadtree.

Ice resist uses the same `max(0, own + parent)` clamp as fire. Constitution missing is 10.

## Data

`bodies.json`: `resist`, `starts`, as before. Squid `starts: ["wet"]`.

An ice row may include `cold` (number ≥ 0). `"magic": {"ice": 10}` still loads, as `cold` 10.
`scales_with: magic` adds the caster's magic stat to `cold`.

A lightning value may be a number, or
`{"damage", "reach", "arcs", "spark"}`. Missing reach, arcs and spark are 0. Unknown field fails
the row. `storm_bolt` gets `damage` 50, `reach` 180, `arcs` 4, `spark` 12.

`monster_data`: optional `"detail": "full"`. Absent means simple. The player is full.

`conditions.json`: `burning`, `hot_shell`, `wet`, and `chilled` (buff on speed, amount and duration
set by the shade, refresh). One chill. A new cold hit replaces it with the new shade and the new
end. There is no separate frozen row: wet adds cold, and the shade follows.

## Colour

Chosen when the heat or the cold is applied, stored on the body, passed into the draw. No new
surface, and no walk of the heap at draw time.

- Cold: three blues on the body draw (the skin). Piece draws stay white.
- Heat: three reds on the draws of the layers that are hot. A hot breastplate tints that piece.
  Skin under it stays untinted. A hot hide, or a naked burn, tints the body draw, because the hide
  is what heated.
- Burning uses the searing red on the layer that caught.

`PlayerMesh.draw` already draws the body, then each piece. The body call gets the skin tint. Each
piece call gets that piece's heat tint, or white.

## Heat patch

Unchanged. While you stand in a patch, `max(0, heat − fire resist) × (1 − insulation) × dt`, from
the chest stack's outer layer. Leaving starts `hot_shell` when one second of that heat is above
`COOK`. `fire_resistance` on the entity is not read.

## Check in play

Scene `elemental`. The hero is full detail. Three beats, 6 s (`SECONDS` 18, `FAST_SECONDS` 16).

1. Full plate. Fire spit. The plate goes hot red. The skin does not. Overlay: hot shell, 3.5 s,
   health −3.
2. Loincloth only. Fire spit. The cloth goes searing red. Overlay: burning, health −15.
3. Cloth stays. Ghost chill, cold 20, constitution 10. The skin goes severe blue. The cloth does
   not. Overlay: severe, 3.5 s until the slow ends, health −9. Hold a direction: slower until
   that line clears, then today's speed and colour.

Headless checks the health drops, the shade, and that the slow is gone at the end.
`test_suite.py --scenario elemental --hold-seconds 6` from `Pixel-Realm-elemental\Code`.

A second headless check, no window: one storm bolt with the numbers above, a plate body and a wet
hide 100 px away, and the charges match the table. A simple body beside them is offered a second
hop only.

## Tests (`tests/damage/test_rules_magic.py`, no display)

The table. Parent resist. The ice-ghost clamp. Heat curve and cold curve against a 1 ms step,
within 0.05. Constitution 20 sticks half of constitution 10 and the slow ends sooner. Three shade
boundaries (9, 10, 15, 20). A simple body given cold 20 gets the shade row, not the curve.

One apply through `InteractionResolver` for fire spit on loincloth, as before.

Lightning: plate then wet hide at 100 px and at 200 px (200 is past the 162 reach, so no second
hit). A third hop stops when passed charge drops under `spark`. Simple detail stops after one jump
even when charge remains.

Regression: the targeted set. Same 11 known failures. Perf: one full cold apply, and one lightning
of 4 arcs against 8 nearby bodies, in `Code/NOTES_performance.md`. Not the 200-enemy scene. If
either is more than a few microseconds, the simple path is the one that must stay there; full is
allowed to be the longer of the two and still has to be a handful of multiplies plus at most `arcs`
quadtree asks.

## Commits

1. This plan. Master doc: chunk 7 points here; log.
2. Resists, `cold`, lightning objects, the thermometer and the bolt, tests.
3. Point monster hits at the body card they already have, `resolve` / `apply`, hops, heat patch,
   tints, the scene. Perf line.
   Master doc: chunk 7 done, log.

## Open

- `CATCH`, `COOK`, `COLD_K`, `SLOW_AT`, `HURT_AT`, the shade lines, `reach` 180 and `arcs` 4 are
  the test numbers.
- Holy, unholy, kind multipliers, and a negative resist that increases damage are chunk 9.
- The co-op server's copy of another player does not know his card or his armour, so a hit on that
  copy stays the old flat number.
- Which bosses are `"detail": "full"` is a list we fill when one of them should show the curve.
  Until then only the player is full.
