# Damage, armour, magic and conditions: the master plan

Started 2026-11-14. Source talks: `docs/ideas/raw/2026-11-14-armor-and-damage-types.txt` (in the main
folder, untracked) and the Claude Code chat of the same day.

This doc holds the whole system: the design (first half) and how it is built (second half: code
layout, data files, the attack and body roster, changes per file, tests per chunk). Each chunk
becomes its own `.cursor/plans/*.plan.md`; when one is written or finished, check it against this doc
and fix whichever is wrong.

## Goal

Armour that is a fact, not a percentage: full plate walks through a dart tribe, a mace still hurts
through it, lightning loves it. Magic, venom, heat and cold work on the same hit. Hundreds of
fighters on screen: near-zero cost per frame, a few µs per hit.

## Rules the system keeps

- Behaviour comes from **properties** (constants), never from names. "Plate" is a set of numbers;
  no rule says `if material == "plate"`.
- Armour answers the **physical** part of a hit. Resistances answer the **magic** part. Conditions
  answer what **stays** after it (venom, heat, cold, buffs).
- A stopped point does not deal its damage. What reaches you is its **force**, softened by `absorb`.
- Late-game weapons keep their kind: a dart's `penetration` does not scale with level, so plate stays
  plate.
- Hits are events. Nothing in this system runs per frame except one heap peek.
- New types, categories, properties and rules are **rows in data**, not new code paths.
- Simple bodies stay simple: a body with no worn layers and no conditions takes the fast path.
  Layers, wear and stuck arrows are opt-in (player, key bosses).
- **One place computes damage**: the resolver. Receivers subtract `ctx.amount` and nothing else.
- The rules are **pure functions** (no pygame, no entities): the card, the tests and the resolver
  all call the same ones.

## Terms

| term | meaning |
|---|---|
| attack def | data row for one attack: damage, penetration, force, delivery, magic, venom, flags |
| delivery | how force arrives: `pierce`, `crush`, `blast`. Physical. Armour answers it |
| magic category | what a spell is: `fire`, `ice`, `lightning` (elemental), `holy`, `unholy`, more later |
| nature | a magic category or `venom` carried by an attack |
| layer | one worn piece (or a body's natural hide) over one region; up to 3 deep |
| body def | a creature's constants: mass, natural layer, kind, resistances, states it starts with |
| defence profile | a body def plus what it wears, compiled for fast lookup; rebuilt on equip |
| contact point | the exact pixel where the attack first met the body |
| condition | something with a clock on a body: venom, burning, hot shell, frozen, wet, buff |
| resistance | a number per magic category; negative = weakness |

# Part 1: design

## A hit, step by step

0. **Team and avoid**: existing team policy (`Interaction.py`), dodge, parry, block. Unchanged.
1. **Amount from attacker**: the attack def's `damage`, plus attacker stats for player attacks
   (today `get_full_weapon_damage` / `get_full_magic_damage`, computed in two receivers; moves into
   the resolver).
2. **Contact point**: the pixel where the attack met the body (see Contact).
3. **Physical** (attack has a delivery), layers outer → inner at the contact point:
   - pierce: `excess = penetration − stopping_power`. `≤ 0`: stops at this layer. `> 0`: next layer
     with `penetration = excess`.
   - force reaching the body = `force × Π(1 − absorb)` over the layers it passed or stopped on.
   - stopped: body takes **bruise** = that force × `BRUISE_SCALE`. Through: `damage` + bruise.
   - crush, blast: no penetration test; `damage × Π(1 − absorb)` + bruise.
   - each layer hit loses durability (Wear).
4. **Magic**: per category on the attack: `max(0, power − resist(category))`, then the category rule:
   - lightning: × (1 + conductivity of the outermost layer); × `WET_MULT` if wet; jumps to bodies
     within `JUMP_PX` that are conductive or wet (later).
   - fire: flammable outer layer catches (burning). Else heat into the piece (hot shell).
   - ice: slow; conductive outer layer seizes joints (stronger slow); wet body freezes.
   - holy / unholy: lands through armour; × `KIND_MULT[category][kind]` (severe on undead, demon).
5. **Venom**: only if a pierce got through to flesh, or gas reached an unsealed face. Then the venom
   rules (Conditions).
6. **Impulse**: one path. Displacement = impulse / (body mass + gear weight), cut by strength.
7. **Conditions**: start or extend timers.

Partial penetration (optional, later): `excess` left after the last layer scales the wound, so a
point that barely got through mail hurts less than one into bare skin.

## Contact: precise, mask collision kept

The existing hit test stays (`hit_core.py`): rect, then mask against mask.

1. **The point is already found.** `hit_core.touching` calls `mask.overlap(...)`, which returns the
   first overlapping pixel, and drops it with `is not None` (`hit_core.py:130`). Keep that pixel.
2. **Projectiles: the entry pixel.** The overlap's first pixel is first in scan order, not where the
   arrow entered. From the tip, step back along the flight over the body mask with `get_at` until
   outside: at most the per-frame travel in reads (10–20).
3. **Which layer is there** (only bodies with worn layers):
   - Sprite bodies: one mask per worn slot per animation frame, built when frames load.
     `slot_mask.get_at(point)`, outer first: 1–3 reads. Holes are transparent pixels.
   - Mesh bodies: the hit mask is the posed capsules (`mesh_boss.build_body_mask`, cached per frame
     and facing). Rasterize each capsule with its index as colour into the same cached image: the
     pixel gives the bone; the capsule's projection gives position along it (u) and around it
     (angle). Each slot bakes, at export, a coverage bitmap per bone in (u, angle). One read.
4. No contact point (rect fallback, ground blasts): blasts need none; rect fallback uses the centre
   of the overlap.

## Knockback and mass (done: chunk 1, `refactor/knockback-mass`)

- One live path: `Entity.apply_impulse`. Leap slam and meteors reach it through `impulse` contexts.
- It scales every shove by `Entity.knockback_scale(body)`: `REFERENCE_MASS` (90, the barb) /
  (`mass` + `gear_weight`), kept in [0.1, 3.0], times the strength cut
  `max(0.55, 1 − 0.015 × strength)` (no strength, no cut). Constants in `Settings.py`.
- `monster_data` has `mass` per monster; `gear_weight` is 0 until armour has weights (item bases).
- Was wrong in the first version of this doc: "three paths". `hit_reaction` + enemy `resistance`
  never ran (no enemy sets `vulnerable` False); the parry `player.rect` write is in
  `MeleeCombatStrategy.py` / `MixedCombatStrategy.py`, which nothing imports. Both were dead code.
- `Entity.weight` (walking acceleration only) is untouched.

## Conditions and the scheduler

Today: no timed conditions. Effects belong to areas, checked every frame (`Entity.check_effects`,
`Entity.py:839`); `should_persist_after_exit` is always False (`Effect.py:62`). Timers are scattered
`*_until_ms` fields. `apply_environmental_damage` builds a new `InteractionContext` with a new `tags`
set per entity per frame in fire (`Entity.py:1069`).

Target:
- One heap per level: `(due_ms, seq, entity_id, generation, cond)`, checked in the level update next
  to `entity_id_map` (not in draw), so the headless server runs it too.
- Per frame: peek; pop only what is due. A cure or death bumps `generation`; stale entries skipped.
- Smooth values computed when read: piece heat `(heat, t)` → `ambient + (heat − ambient)·e^(−k·Δt)`.
  The time it drops below the cook threshold is solved ahead; "hot shell" ends then.
- Areas (fire floor, gas cloud) stay on `check_effects`; what they leave behind becomes a condition.
- Saves use one `random.Random` owned by the level (server), so runs replay.
- Network: the server owns conditions; sends `(cond, start, end, strength)` once.

### Venom
- Starts only on flesh. Constitution save on first dose: shrug off, or set the clock length.
- More doses bring `death_at` earlier. Gas adds dose per second inside the cloud.
- Symptoms by time since start (blur, slow, stumble, death). Healing does not touch the clock.
- Each venom has its named antidote item; the only cure. Generic remedies slow it.

## Armour wear

- Per hit: durability −= force reaching that layer × `wear` (property).
- Thresholds: dented (`stopping_power` × `DENT_MULT`), broken (layer gone). Repair at a smith.
- A change marks the profile dirty; rebuilt once, not per frame.

## Stuck arrows

- Sprite bodies `(offset from rect centre, flipped with facing, angle, depth)`; mesh bodies
  `(bone, u, angle, direction, depth)`, drawn on the bone.
- One transform and one sprite per arrow per frame, batched (same atlas texture). Cap ~8, pooled.

## Item card

See `.cursor/plans/item_card.plan.md`. Verdict lines come from running the rule functions against
reference attacks; numbers in a detail view.

## Performance rules

- Zero per-frame cost except the heap peek.
- Plain hit (no layers, no magic, no venom): today's cost plus one def lookup.
- Fast paths by bitmask: `atk.magic_mask & body.reacts_mask == 0` skips magic; no layers skips the
  layer walk.
- Compiled data: int ids, flat lists, `__slots__`. No string dict on the hot path.
- Contact: reuse the overlap pixel; step-back ≤ 20 `get_at`; layer lookup ≤ 3 reads.
- Measure each chunk on the fixed 200-entity ice scene; log in `Code/NOTES_performance.md`.

# Part 2: how it is built

## Code layout

New modules, flat in `Code/` like the rest (one job each):

| module | job | imports pygame? |
|---|---|---|
| `damage_data.py` | load + validate + compile the data files; registries (property, category, delivery, kind, condition ids); `AttackDef`, `LayerDef`, `BodyDef` (`__slots__`); `attack(name)`, `body(name)` lookups | no |
| `damage_rules.py` | the pure rules: `physical(attack, layers) -> (amount, bruise, reached_flesh, wear)`, `magic(attack, profile, states) -> amount`, `impulse(force, profile)`, `KIND_MULT`, constants | no |
| `defence_profile.py` | `DefenceProfile`: body def + worn pieces → per-region layer lists, total weight, resistances, `reacts_mask`; built on equip; shared per body def; copy-on-write | no |
| `hit_resolve.py` | `resolve(ctx, target) -> HitResult(amount, impulse, conditions, wear)`: amount from attacker, contact → layers, rules; called by `InteractionResolver.apply` | no |
| `conditions.py` | condition defs, `ConditionClock` (the level heap), venom / burning / hot shell / wet / buff behaviours | no |
| `hit_core.py` (existing) | `touch_point(a, b)` beside `touching`; `entry_point(projectile, body)` | yes (masks) |

Pure modules stay importable on the headless server and in tests without a display.

## Data files

`Code/config/damage/` (next to `config/faction_policy.json`), JSON, `schema_version` like
faction_policy, loaded once, fail loudly on an unknown key or missing reference:

| file | holds |
|---|---|
| `properties.json` | every property: id, label, group, format, better, card rule, template (shared with the card) |
| `categories.json` | magic categories with parents (`elemental` → fire, ice, lightning; holy; unholy) |
| `kinds.json` | creature kinds and `KIND_MULT` per holy/unholy |
| `attacks.json` | attack defs (roster below) |
| `bodies.json` | body defs (roster below) |
| `conditions.json` | venoms, burning, hot shell, frozen, wet, buffs: clock, save, cure, stacking |

Item bases stay in `Graphics/Standard_Items/item_bases.json` (card plan); a worn piece is a layer
with the same property names.

Hookups in existing data:
- `monster_data` (Settings.py): each entry gets `"body": "<body def>"`; each melee / ranged / special
  attack gets `"attack": "<attack def>"`. Old `damage` stays until the chunk that reads the def.
- `weapon_data`, `magic_data`, `ability_data` (Settings.py): each gets `"attack": "<attack def>"`.
- Ranged attack `type` today names the projectile **art** (`demon_dog_projectile`); `attack` names
  what it **does**. demon_dog, venom_plant and ice_mage all fire the same art today: same art,
  three different defs.

## Roster: attacks (first numbers; tune in play)

Scale: plate `stopping_power` 40, leather 10, skin 0. Force: 100 ≈ a horse's kick.

| attack def | used by | delivery | dmg | pen | force | magic / venom |
|---|---|---|---|---|---|---|
| `unarmed` | player | crush | 5 | 0 | 8 | |
| `sword` | player | pierce | 15 | 20 | 15 | |
| `rapier` | player | pierce | 8 | 30 | 6 | |
| `sai` | player | pierce | 10 | 25 | 8 | |
| `axe` | player | pierce | 20 | 30 | 35 | |
| `lance` | player | pierce | 30 | 50 | 60 | |
| `flame` | player magic | none | 0 | | 0 | fire 5 (+ magic stat) |
| `ice_ball` | player magic | none | 0 | | 10 | ice 10 (+ magic stat) |
| `leap_slam` | player ability | blast | 25 | | 140 | |
| `dash_hit` | player, raccoon | crush | config | | 80 | |
| `ice_clone_burst` | player ability | blast | config | | 60 | ice 15 |
| `demon_claw` | demon | crush | 40 | | 120 | unholy 10 |
| `meteor_impact` | demon | blast | 75 | | 250 | fire 30 |
| `meteor_embers` | demon (residual) | none | 8 | | 0 | fire 8 |
| `squid_slap` | squid | crush | 8 | | 15 | |
| `snake_bite` | tribey_snake | pierce | 8 | 15 | 3 | venom `snake_venom` 1 |
| `raccoon_claw` | raccoon | pierce | 80 | 15 | 20 | |
| `spirit_touch` | spirit | none | 0 | | 0 | fire 9 |
| `bamboo_whip` | bamboo | crush | 6 | | 8 | |
| `ghost_chill` | ice_ghost | none | 0 | | 0 | ice 20 |
| `spear_thrust` | tribey_spear | pierce | 6 | 25 | 10 | |
| `blowgun_dart` | **new** tribey_dart (the dart tribe) | pierce | 4 | 12 | 2 | venom `frog_venom` 1 |
| `fire_spit` | demon_dog | none | 0 | | 10 | fire 15 |
| `thorn` | venom_plant | pierce | 5 | 12 | 2 | venom `plant_venom` 1 |
| `venom_cloud` | venom_plant (new special) | none, area | 0 | | 0 | venom `plant_venom` 1/s |
| `staff_strike` | ice_mage | crush | 15 | | 20 | |
| `ice_shard` | ice_mage multishot | pierce | 8 | 20 | 5 | ice 15 |
| `crossbow_bolt` | reference (card), later enemy | pierce | 30 | 55 | 25 | |
| `ballista` | reference (card), later siege | pierce | 80 | 120 | 400 | |
| `storm_bolt` | reference, later enemy | none | 0 | | 0 | lightning 50 |
| `holy_smite` | reference, later | crush | 25 | | 50 | holy 20 |

What this gives in play (full plate on the barb):
- tribey_dart, venom_plant thorns, snake bites: stopped. Bruise ≈ 0. No venom. The walk-through.
- spear_thrust (25 vs 40): stopped. ice_shard: stopped, but the ice still lands and plate seizes.
- demon_claw, squid, bamboo: crush, cushioned only by `absorb`. The demon still hurts.
- meteor_impact: thrown less (mass), fire heats the shell.
- crossbow_bolt (55 vs 40): through. ballista: through and thrown.
- Naked barb: every point goes in; darts, thorns and bites start venom clocks.

## Roster: bodies (first numbers)

| body def | used by | mass | natural layer (stop / absorb / flamm / cond) | kind | resistances | starts with |
|---|---|---|---|---|---|---|
| `barb` | player | 90 | 0 / 0.05 / 0.2 / 0 | living | | |
| `demon` | demon | 400 | 30 / 0.3 / 0 / 0.2 | demon | fire 50 | |
| `squid` | squid | 60 | 0 / 0.5 / 0 / 0 | living | ice 20 | wet (always) |
| `snake` | tribey_snake | 20 | 5 / 0.1 / 0.3 / 0 | living | venom immune | |
| `raccoon` | raccoon | 80 | 5 / 0.2 / 0.5 / 0 | living | | |
| `spirit` | spirit | 5 | 0 / 0 / 0 / 0 | undead | fire 100, ice −20 | |
| `bamboo` | bamboo | 30 | 15 / 0.2 / 0.9 / 0 | living | lightning 30 | |
| `ice_ghost` | ice_ghost | 20 | 0 / 0 / 0 / 0 | undead | ice 100, fire −30 | |
| `tribesman` | tribey_spear, tribey_dart | 70 | 10 / 0.1 / 0.5 / 0 (leather) | living | | |
| `demon_dog` | demon_dog | 40 | 5 / 0.1 / 0 / 0 | demon | fire 100 | |
| `venom_plant` | venom_plant | 200 | 10 / 0.3 / 0.9 / 0 | living | fire −50, venom immune | |
| `ice_mage` | ice_mage | 70 | 0 / 0.1 / 0.6 / 0 (cloth) | living | ice 80, fire −20 | |

Worn plate pieces (item bases): stop 40, absorb 0.15, flamm 0, cond 0.9, insulation 0.2. Weights and
coverage in the card plan.

## Changes to existing code, per file

| file | change | chunk |
|---|---|---|
| `Entity.py` `apply_impulse` | scaled by `knockback_scale` (mass, gear weight, strength) — done | 1 |
| `Enemy.py`, `combat_unit.py`, `friendly.py`, `meteor_strike.py`, `Settings.py` | `resistance` → `mass`; dead `hit_reaction` and meteor's own strength factor removed — done | 1 |
| `attack_sprite.py` `init_attack` | new `attack_def` field (compiled def); `attack_type` stays for particles only | 2 |
| `Weapon.py`, `Particles.py` `ParticleEffect` | pass `attack_def` from `weapon_data` / `magic_data` / the ranged attack | 2 |
| `CombatStrategy.py:140` (enemy melee strike) | pass `attack_def` from the melee attack config | 2 |
| `abilities/dash.py:151`, `abilities/leap_slam.py:358`, `IceClone.py:42`, `meteor_strike.py:609` | pass `attack_def` | 2 |
| `Settings.py` `monster_data`, `weapon_data`, `magic_data`, `ability_data` | `body` / `attack` keys | 2 |
| `Interaction.py` `InteractionContext` | fields `attack_def`, `contact` (x, y or None) | 2, 3 |
| `Interaction.py` `InteractionResolver.apply` | for `kind == "damage"` with `attack_def`: `hit_resolve.resolve` sets `ctx.amount`, applies impulse, starts conditions | 5 |
| `Player.py:204-240`, `combat_unit.py:830-850` | stop computing amount from `source.get_full_*`; subtract `ctx.amount` only (the resolver did it) | 5 |
| `Level4_tmxdev.py:1555` `_strike_with_attack_sprites` | pass `attack_def`, `contact` into the fields | 2, 3 |
| `Level4_tmxdev.py:2142` (server, client-relayed amount) | keep for plain bodies; bodies with layers resolved on the server | 5 |
| `hit_core.py` | `touch_point`, `entry_point` | 3 |
| `Player.py`, `CombatUnit` | hold a `DefenceProfile`; `Inventory` equip/unequip marks it dirty | 4 |
| `Effect.py` `HeatEffect`, `Entity.fire_resistance` | fold into fire rule and resistances | 7 |
| level update loop | `ConditionClock.tick(now)` next to `entity_id_map` | 6 |

An attack without `attack_def` keeps today's behaviour exactly (flat `amount`), so chunks land one at
a time and nothing breaks between them.

Flags found while reading:
- `attack_type` does three jobs: combat strategy (`Settings.py:382`), particle key (`Player.py:179`),
  weapon vs magic (`Player.py:220`).
- Damage amount for player attacks is computed in two receivers (`Player.py:222`,
  `combat_unit.py:841`), not in the resolver.
- demon_dog, venom_plant and ice_mage share `demon_dog_projectile` with the same damage 15.
- `PolarBear.py`, `Eskimo.py` keep an older `get_damage(player, attack_type)` path.
- `MeleeCombatStrategy.py`, `MixedCombatStrategy.py`, `RangedCombatStrategy.py` are not imported
  anywhere (the live strategies are classes in `CombatStrategy.py`). Left alone.
- Enemies never set `vulnerable = False` (commented out in every `get_damage`), so they have no
  i-frames; repeat hits are limited only by each attack's `rehit_ms`.

## Tests

New folder `tests/damage/`, pytest, same header as `tests/test_hit_core.py` (Code on `sys.path`,
`SDL_VIDEODRIVER=dummy` only where pygame is needed). Pure modules get plain tests with no display.

**The scenario table** (`tests/damage/test_scenarios.py`) is the spec of the fantasy: one row per
(attack def, wearer, expected). Parametrized; it calls `damage_rules` / `hit_resolve` directly. Rows
are added with each chunk; a row never gets deleted to make a change pass.

| attack | wearer | expect |
|---|---|---|
| `blowgun_dart` | barb in full plate | amount < 1, no venom |
| `blowgun_dart` | naked barb | amount 4, `frog_venom` started |
| `thorn` | barb, plate chest only, hit on the face | goes in, venom started |
| `spear_thrust` | full plate | stopped |
| `crossbow_bolt` | full plate | through |
| `demon_claw` | full plate | ≥ 70% of naked damage (absorb 0.15) |
| `demon_claw` | plate + gambeson (absorb 0.5) | less than plate alone |
| `meteor_impact` | plate vs naked | plate thrown less (mass) |
| `storm_bolt` | plate vs leather | plate takes more |
| `storm_bolt` | squid (wet) | × `WET_MULT` |
| `spirit_touch` | spirit | 0 (fire 100) |
| `fire_spit` | ice_ghost | more than base (fire −30) |
| `holy_smite` | demon vs barb | demon takes far more, through plate |
| `snake_bite` | snake | no venom (immune) |

Per chunk:

| chunk | test file | checks |
|---|---|---|
| 1 knockback | `tests/damage/test_knockback.py` (+ existing `tests/abilities/test_impulse_interaction.py`) | reference body moves the force; heavy moves less; gear weight counts; limits; strength cut; every monster has a mass (done) |
| 2 attack defs | `tests/damage/test_damage_data.py` | every `attack` / `body` key in Settings exists in the data; unknown key fails loudly; ids stable; an attack with no def deals today's amount (regression) |
| 3 contact | `tests/damage/test_contact.py` | `touch_point` returns the overlap pixel; `entry_point` finds the edge pixel along the flight; rect fallback gives the centre |
| 4 layers | `tests/damage/test_defence_profile.py` | worn pieces → layers per region in order; hole pixel → flesh; profile shared until a piece is damaged; equip marks dirty |
| 5 physical | `tests/damage/test_rules_physical.py`, scenario rows | penetration chain across layers; absorb product; bruise ≈ 0 for darts; resolver sets `ctx.amount`; receivers only subtract |
| 6 conditions | `tests/damage/test_conditions.py` | heap pops only due; stale generation skipped; seeded save replays; buff changes a stat and ends on time |
| 7 elemental | `tests/damage/test_rules_magic.py`, scenario rows | resistance threshold, parent category adds, conductivity, wet, heat decay closed form vs stepped |
| 8 venom | `tests/damage/test_venom.py` | starts only on flesh; doses shorten clock; con save; antidote cures; healing does not |
| 9 categories | `tests/damage/test_rules_magic.py` | holy/unholy by kind; negative resistance = weakness |
| 10 wear | `tests/damage/test_wear.py` | durability falls with force; dent lowers stop; broken removes layer |
| 11 arrows | `tests/damage/test_stuck_arrows.py` | stored at contact; cap drops oldest; follows facing |
| 12 card | `tests/test_item_card.py` | lines come from the rules; card for plate chest / loincloth |
| all | `tests/damage/test_perf.py` (like `tests/test_wall_collision_perf.py`) | plain hit resolve under budget; armoured hit under budget; no per-frame work with no conditions |

Plus one end-to-end: `tests/damage/test_headless_hits.py` on the headless level (as
`tests/test_headless_level.py`): a tribey_dart fires at the plated barb, health holds; at the naked
barb, venom starts.

## Chunks

Each becomes its own plan. Order follows the arrows; 1 is independent. Every chunk: its tests above,
its scenario rows, a perf line in `Code/NOTES_performance.md` if it touches the hit path.

1. **Knockback by mass.** Done: `.cursor/plans/knockback_mass.plan.md`, branch
   `refactor/knockback-mass`.
2. **Attack defs and bodies.** `damage_data.py`, `config/damage/*.json` (attacks, bodies, properties,
   categories, kinds), `attack` / `body` keys in Settings, `attack_def` on every attack sprite and
   strike. Still flat damage. → 3, 5
3. **Contact point.** `touch_point`, `entry_point`, `contact` on the context; debug draw. → 4, 11
4. **Bodies and layers.** `defence_profile.py`; profile on Player / CombatUnit; slot masks for sprite
   bodies; bone map + per-bone coverage for mesh bodies (needs the outfit per-slot draw). → 5
5. **Physical resolve.** `damage_rules.physical`, `hit_resolve.py`, resolver calls it, receivers
   simplified. First real behaviour: plate stops the dart. → 10, 12
6. **Conditions and buffs.** `conditions.py`, the level clock, server-owned. → 7, 8, 9
7. **Elemental.** Fire, ice, lightning rules; wet; piece heat; hot shell; fold `HeatEffect`.
8. **Venom.** Venoms, saves, antidote items, `venom_cloud` area, new `tribey_dart` enemy.
9. **Magic categories and resistances.** Parents, negative = weakness, holy/unholy by kind.
10. **Armour wear.**
11. **Stuck arrows.**
12. **Item card and character sheet.** `.cursor/plans/item_card.plan.md` (pulled forward; its rule
    function is `damage_rules.physical`, written there first if the card goes before chunk 5).
13. **Boss with layers.** One key boss using 4, 5, 10 to prove NPC opt-in.

## Open

- Partial penetration: in chunk 5 or later?
- Attribute list: which attributes feed saves and resistances.
- Lightning jump range and count.
- `BRUISE_SCALE`, `WET_MULT`, `KIND_MULT`, `DENT_MULT`: first values in chunk 5 / 7, tuned in play.
- New enemy `tribey_dart`: art from tribey_spear, or new?

## Method that works

- Baseline before code: run the tests that touch the change in the chunk's worktree, save the
  FAILED lines, compare after (`diff` of the names). The whole suite is too slow for this.

## Known errors

(empty)

## Log

- 2026-11-14: design talk; this doc written. No code changed.
- 2026-11-14: item card plan written (`.cursor/plans/item_card.plan.md`).
- 2026-11-14: Part 2 added: code layout, data files, attack and body roster, changes per file, tests
  per chunk. Read for it: `Settings.py` monster_data, `Interaction.py`, `Player.py:165-255`,
  `combat_unit.py:790-860`, `CombatStrategy.py:130-160`, `Particles.py:243-300`, `Weapon.py`,
  `attack_sprite.py`, `Level4_tmxdev.py:1555-1595, 2130-2150`, `tests/test_hit_core.py`.
- 2026-11-14: chunk 1 (knockback by mass) on `refactor/knockback-mass`. Targeted tests (abilities,
  rts, hit_core, server enemy authority, walk phasing, wall collision, enemy puppet, entity gates,
  co-op damage, headless level, mesh contact, mesh player, equipment): before 11 failed / 241 passed;
  after 11 failed (the same names) / 284 passed (43 new in `tests/damage/`). Not checked in play.

## Tried and dropped

- **Armour points subtracted from damage** (D2 style): late-game darts beat plate; replaced by
  penetration vs stopping power plus force.
- **Tiers** (dart < arrow < bolt vs leather < mail < plate): no faster than constants and less
  flexible; replaced by `penetration` / `stopping_power` numbers.
- **Named materials in rules** (`if plate`): replaced by property-driven rules.
- **Wards per spell**: replaced by general buffs on resistance stats.
- **Coverage roll for holes**: not precise enough; replaced by exact lookup at the contact pixel.
- **Magic physical / magic elemental as types**: a spell is a delivery plus a category; no extra type.
