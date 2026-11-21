# Damage, armour, magic and conditions: the master plan

Started 2026-11-14. Source talks: `docs/ideas/raw/2026-11-14-armor-and-damage-types.txt` (in the main
folder, untracked) and the Claude Code chat of the same day.

This doc holds the whole system: the design (first half) and how it is built (second half: code
layout, data files, the attack and body roster, changes per file, tests per chunk). **Where we are and
what is next: the section "Status and next steps" before Open.** Each chunk
becomes its own `.cursor/plans/*.plan.md`; when one is written or finished, check it against this doc
and fix whichever is wrong.

## Goal

Armour that is a fact, not a percentage: full plate walks through a dart tribe, a mace still hurts
through it, lightning loves it. Magic, venom, heat and cold work on the same hit. Hundreds of
fighters on screen: near-zero cost per frame, a few µs per hit.

**What you see is what you hit** (Douglas, from the start): an arrow that visibly hits armour pings
off; one that visibly hits skin can stick in him, where it hit. So a hit is tested against the body as
drawn, and armour is where each piece is drawn, not a whole body region.

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
- **One damage path.** Every hit, lava tick and co-op relay goes through `InteractionResolver`
  (`apply` = the one team rule `team_allows`, then `land`; `strike` checks the team once per target,
  then `land`). `land` **decides**: the body's gate (`Entity.can_receive_interaction`: health left;
  shoves need `takes_impulse`), the `invulnerable` condition (blocks all damage, heat and cold too;
  nothing grants it by default), the price (`_price`: a hit has an attack def or an already-priced
  amount, never both, never neither; the def's damage + the attacker's `scales_with` stat, times
  `ctx.scale`; a card prices it in `hit_resolve.resolve`, else `hit_resolve.flat`), the elements.
  Damage numbers live only in `attacks.json`; a monster's strength is `monster_data` `stats`. Returns `LANDED`, `SPENT` (invulnerable) or
  `REFUSED`. `Entity.take_damage` is the one place health goes down; a class reacts in `on_hurt`;
  at 0 `die()` runs once (`is_dead`, condition notice) and calls `on_death` (leave the tree, kill;
  classes add particles, sound, XP; the player stays on screen). The resolver records the attacker
  (`remember_attacker` → `last_attacker_team` / `last_attacker_until_ms`), read by two rules:
  permission (`FactionPolicy.should_aggro`, retaliate_only) and preference (`CombatUnit`).
  Ground effects (slippery) are not hits: `Entity._set_effect_state`. Sounds: `sounds.get`.
  Guarded by `tests/damage/test_one_path_guard.py`. Plan: `PLAN_damage_foundation.md`.
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
1. **Amount from attacker**: the attack def's `damage` plus the attacker's stat (`scales_with`),
   player and monster alike, times the hit's share (`scale`: falloff, charge, meteor size).
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
   arrow entered. From that pixel, step back along the flight over the body mask with `get_at` until
   outside: at most this frame's travel + the shot's length in reads, capped at 64
   (`hit_core.entry_point`). ~20 µs a walk, so it runs only for hits that land (`EntryPoints`).
3. **Which layer is there** (only bodies with worn layers):
   - **Built in chunk 4** (`defence_layers.plan.md`), **short of the Goal's "what you see is what
     you hit"**: the mesh hero is hit on his sprite mask (the mesh is draw-only); the region is the
     front-most of his projected body capsules at the contact → bone → `regions.json`; a region is
     covered or not (the item's `coverage`). Torso is chest or back by the attack's direction against
     his facing. 61 µs (cached per frame) / 329 µs, landed hits on armoured bodies only.
   - **Built in 4b** (`visual_hits.plan.md`): the mesh hero is hit on his mesh's own points
     (`mesh_points.py`: ~2.5k vertices posed per frame, projected like the camera, nearest per pixel),
     worn pieces in the same outline. At the hit pixel the point in front says which bone (region) and
     whether it is a worn piece (its item's layer, then the hide) or skin (the hide):
     `body_regions.hit_layers`. Plate or skin matches the drawn mesh on 96% of arrows within 1 px, all
     within 2 px (the seams). The point is also where a stuck arrow sits (chunk 11). Capsules stay
     (`MESH_HERO_HIT_BODY = "capsules"`; the demon; body collision).
   - Sprite hero wearing items: height bands on the hitbox (kept while sprite heroes exist). Sprite
     enemies wear nothing: one layer (their hide) everywhere, no lookup.
   - Dropped before chunk 4: per-slot sprite masks per frame (no sprite body wears pieces).
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

- Sprite bodies `(offset from rect centre, flipped with facing, angle, depth)`; mesh bodies: the mesh
  point the arrow hit (`HitSpot.point`: body or piece, posed with the animation) plus direction and
  depth, drawn on that point.
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
- Contact: reuse the overlap pixel; step-back ≤ 64 `get_at` (only hits that land); what the hit meets
  on the mesh hero: one outline lookup, 6-9 µs (`hit_layers`); his outline is built per new pose while
  he is attacked (0.5-1.2 ms; 3.7 ms the first time a frame is used in full plate).
- Measure each chunk on the fixed 200-entity ice scene; log in `Code/NOTES_performance.md`.

# Part 2: how it is built

## Code layout

New modules, flat in `Code/` like the rest (one job each):

| module | job | imports pygame? |
|---|---|---|
| `damage_data.py` | load + validate + compile the data files; registries (property, category, delivery, kind, condition ids); `AttackDef`, `LayerDef`, `BodyDef` (`__slots__`); `attack(name)`, `body(name)` lookups | no |
| `damage_rules.py` | the pure rules: `physical(attack, layers) -> (amount, bruise, reached_flesh, wear)`, `magic(attack, profile, states) -> amount`, `impulse(force, profile)`, `KIND_MULT`, constants | no |
| `defence_profile.py` | `DefenceProfile`: body def + worn pieces → per-region-slot layer tuples (outer first, hide last), worn weight; built on equip; one shared per body def for the unarmoured; resistances, `reacts_mask` and copy-on-write come with chunks 7-10 | no |
| `hit_resolve.py` | `resolve(ctx, target) -> HitResult(amount, impulse, conditions, wear)`: amount from attacker, contact → layers, rules; called by `InteractionResolver.apply` | no |
| `conditions.py` | condition defs, `ConditionClock` (the level heap), venom / burning / hot shell / wet / buff behaviours | no |
| `hit_core.py` (existing) | `touch_point(a, b)` beside `touching`; `find_contacts`; `entry_point(point, step, body)` (done: chunk 3) | yes (masks) |
| `body_regions.py` | contact pixel → region: mesh hero by nearest posed capsule + `Graphics/Meshes/<pack>/regions.json`; sprite hero by height bands (chunk 4) | no (numpy) |

Pure modules stay importable on the headless server and in tests without a display.

## Data files

`Code/config/damage/` (next to `config/faction_policy.json`), JSON, `schema_version` like
faction_policy, loaded once, fail loudly on an unknown key or missing reference:

| file | holds |
|---|---|
| ~~`properties.json`~~ | dropped in chunk 2: the property rows live in `Code/item_properties.py` (item card, on `main`) |
| `categories.json` | magic categories with parents (`elemental` → fire, ice, lightning; holy; unholy). Done: chunk 2 |
| `kinds.json` | creature kinds and `KIND_MULT` per holy/unholy |
| `attacks.json` | attack defs (roster below). Done: chunk 2 |
| `bodies.json` | body defs (roster below) |
| `conditions.json` | venoms, burning, hot shell, frozen, wet, buffs: clock, save, cure, stacking |

Item bases stay in `Graphics/Standard_Items/item_bases.json` (card plan); a worn piece is a layer
with the same property names.

Hookups in existing data:
- `monster_data` (Settings.py): each entry gets `"body": "<body def>"` (chunk 4/5); each melee /
  ranged / special attack gets `"attack": "<attack def>"` (done: chunk 2; meteor also
  `"residual_attack"`). Its `damage` stays and may differ from the def's default (20 warriors share a
  few defs at their own damage).
- `tools/entity_pipeline/wire.py` writes `"attack"` for new warriors (`attack_for(label, reach)`).
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
| `ice_shard` | ice_mage multishot and ranged | pierce | 8 | 20 | 5 | ice 15 |
| `arrow` | warriors 00, 06, 12 | pierce | 6 | 30 | 4 | stops |
| `stone` | warrior 15 (catapult crew) | crush | 4 | | 15 | stops |
| `tribal_club` | warrior 13 | crush | 9 | | 30 | |
| `scimitar` | warriors 03, 04, 07, 10, 11 | pierce | 8 | 20 | 10 | |
| `spear_thrust` | also warriors 01, 02, 05, 08, 09, 14 | | | | | |
| `curse_bolt` | warrior 16 (magic-user) | none | 0 | | 0 | unholy 9 |
| `sun_bolt` | warrior 17 (high priest) | none | 0 | | 0 | holy 8 |
| `catapult_shot` | warrior 18 (catapult) | blast | 12 | | 200 | stops |
| `scorpion_sting` | warrior 19 | pierce | 10 | 15 | 3 | venom `scorpion_venom` 1 |
| `unarmed` | also eskimo / jungle workers and chiefs | | | | | |
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
- ~~Damage amount for player attacks is computed in receivers~~, ~~`PolarBear.py`, `Eskimo.py` keep
  an older `get_damage`~~, ~~`Melee/Mixed/RangedCombatStrategy.py` not imported~~: fixed by the
  damage path (`refactor/damage-path`, 2026-11-20). Pricing is in the resolver; every `get_damage`
  and the three files are gone.
- demon_dog, venom_plant and ice_mage share `demon_dog_projectile` with the same damage 15.
- Enemies never set `vulnerable = False`, so they have no i-frames; repeat hits are limited only by
  each attack's `rehit_ms`. Kept as it was.

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
2. **Attack defs.** Done: `.cursor/plans/attack_defs.plan.md`, branch `refactor/attack-defs`.
   `damage_data.py`, `config/damage/attacks.json` + `categories.json`, `attack` keys in Settings,
   `attack_def` on every attack sprite and strike; projectiles stop by the def. Still flat damage.
   Bodies (and `kinds.json`) moved to 4/5; `properties.json` dropped (`item_properties.py`). → 3, 5
3. **Contact point.** Done: `.cursor/plans/contact_point.plan.md`, branch `refactor/contact-point`.
   `hit_core.touch_point` / `find_contacts` / `entry_point` / `EntryPoints`, `Shape.solid`,
   `InteractionContext.contact`, `strike(contacts=)`; sprites, enemy swings, dashes carry it; blasts
   None. `DEBUG_DRAW_CONTACTS` dots (`contact_debug.py`). → 4, 11
4. **Bodies and layers.** Done: `.cursor/plans/defence_layers.plan.md`, branch
   `refactor/defence-layers`. `bodies.json` + `kinds.json` (natural layer, kind; mass stays in
   `monster_data`), `defence_profile.py` (layers per region slot, worn weight), hero rebuilt on equip,
   enemies share one per body; `body_regions.py` + `regions.json` (contact → region on the mesh hero).
   Needs `main`'s item card merged. Falls short of "what you see is what you hit": hero hit on his
   sprite, armour per whole region. → 4b
4b. **Visual hits.** Done: `.cursor/plans/visual_hits.plan.md`, branch `refactor/visual-hits`. Mesh
   hero hit on his mesh's points (capsules kept as the other choice); worn pieces in his outline;
   `hit_layers` says plate or skin as drawn (96% / 98% of arrows within 1 px, all within 2). → 5, 11
5. **Physical resolve.** Built: `.cursor/plans/physical_resolve.plan.md`, branch
   `refactor/physical-resolve`. `damage_rules.physical`, `hit_resolve.py`; `apply` sets `ctx.amount`
   before the receiver. A pierce stops when it cannot beat `stopping_power` (an arrow on plate deals
   0 and does not flinch); crush and blast are cushioned by `absorb`. Points stays the default hit
   body, capsules stay the other switch. Magic, venom and wear are not in this. → 10, 12
6. **Conditions and buffs.** Built: `.cursor/plans/conditions.plan.md`, branch `refactor/conditions`.
   One heap per level, peeked next to `entity_id_map`; a buff adds to a stat until its end. The
   `haste` validation scene puts that buff on the hero so it can be walked. Fire, venom and the
   network packet stay in 7 and 8. → 7, 8, 9
7. **Elemental.** Built: `.cursor/plans/elemental.plan.md`, branch `refactor/elemental`. You and
   every monster already have a body card (`bodies.json`). The hit reads that card, then armour,
   fire, cold and lightning. An arrow or a tree has no card, so the hit stays the plain number.
   You get the cold curve and every lightning jump. Other monsters get three shades and at most
   one jump, unless marked `detail: full`. Lightning knobs are `damage`, `reach`, `arcs`, `spark`.
   Cold is separate from the blow. Three blues on skin, three reds on the hot piece. Holy, unholy
   and venom stay in 9 and 8.
8. **Venom.** Venoms, saves, antidote items, `venom_cloud` area, new `tribey_dart` enemy.
9. **Magic categories and resistances.** Negative resist raises damage; holy/unholy by kind.
   Parents are already read in 7.
10. **Armour wear.**
11. **Stuck arrows.**
12. **Item card and character sheet.** `.cursor/plans/item_card.plan.md` (pulled forward; its rule
    function is `damage_rules.physical`, written there first if the card goes before chunk 5).
13. **Boss with layers.** One key boss using 4, 5, 10 to prove NPC opt-in.

## Status and next steps (2026-11-17)

**Built, on branches, not merged**, each on the one before:
`refactor/knockback-mass` (1) → `refactor/attack-defs` (2) → `refactor/contact-point` (3) →
`refactor/defence-layers` (4, with `main` merged in) → `refactor/visual-hits` (4b) →
`refactor/physical-resolve` (5, built, not watched in the window) → `refactor/conditions` (6, built)
→ `refactor/elemental` (7, built, not watched in the window) → `refactor/damage-path` (one damage
path, worktree `..\Pixel-Realm-damage-path`, from 7's last commit; the temperature work still
uncommitted in `..\Pixel-Realm-elemental` does not have it yet).
Tests: the targeted set, same 11 known failures (543 passed after the foundation cleanup). In play, knockback uses
mass and worn weight, the mesh hero is hit on his points, a pierce stops on plate, a haste buff
adds to speed until its end (the `haste` scene is the only thing that grants it), and a fire or ice
hit on a body card uses the elemental rule.

**Hit body (Douglas, 2026-11-17).** Watched `points_vs_capsules`. Points stays the default
(`MESH_HERO_HIT_BODY = "points"`). Capsules stay available. The run landed 12 arrows on each half
(17.6 s).

**Next, in order:**
1. **Watch `plate_stops`** (Douglas), if you still want the window. Headless already passed.
   `combat_validation.py --scenario plate_stops --hold-seconds 12` from `Pixel-Realm-physical\Code`.
2. **Watch `haste`** (Douglas). Headless checks the speed. The window is the walk: hold a direction,
   he is faster until the line says the buff ended.
   `combat_validation.py --scenario haste --hold-seconds 6` from `Pixel-Realm-conditions\Code`.
3. **Watch `elemental`** (Douglas). Headless already passed: plate −3 and hot red, cloth −15 and
   searing red, then a chill −9, severe blue, slower, then back to speed 5.
   `combat_validation.py --scenario elemental --hold-seconds 6` from `Pixel-Realm-elemental\Code`.
4. Then 8 / 9 (venom, holy and the weakness), 10 (wear), 11 (stuck arrows), 12 (item card
   verdicts), 13 (boss with layers). Merge of 1–7 is still Douglas's call. Nothing is pushed.

**Owed cleanups and loose ends** (none blocks 5):
- `WornCloud.frames_of` repeats `PlayerMesh.piece_frames`'s rule: one place.
- `body_regions.mesh_slot` / `sprite_slot` serve only the capsules choice and sprite heroes now.
- The test-order `chdir` problem (Known errors), the co-op drift and inertia (below), no helmet item,
  demon tubes not re-baked, first-use posing cost in full plate (3.7 ms per new frame).

## Open

- Partial penetration: in chunk 5 or later?
- Attribute list: which attributes feed saves and resistances.
- Lightning jump range and count.
- `BRUISE_SCALE`, `WET_MULT`, `KIND_MULT`, `DENT_MULT`: first values in chunk 5 / 7, tuned in play.
- New enemy `tribey_dart`: art from tribey_spear, or new?
- Warriors 16 / 17: `curse_bolt` (unholy) / `sun_bolt` (holy) are guesses; 05 could be `lance`.
  Workers and chiefs: `unarmed` is a guess.
- **Co-op drift** (2026-11-14, not the focus): the server decides enemy hits on players against one
  idle sprite frame (`RemotePlayer` server mode), never animated, so in co-op hits on the hero differ
  from what anyone sees. Fix when wanted: the client sends its pose (frame, facing) with its position;
  the server hits the same capsules (`visual_hits.plan.md` (c)).
- Inertia (asked 2026-11-14): `Entity.weight` slows speeding up and turning, but every body has 1.0;
  coasting friction is the surface's, the same for all. Big bodies sliding longer = tie `weight` to
  mass + gear. Not built; a chunk of its own if wanted.

## Method that works

- Baseline before code: run the tests that touch the change in the chunk's worktree, save the
  FAILED lines, compare after (`diff` of the names). The whole suite is too slow for this.
- The targeted set (~2 min), from the worktree root:
  `Code/sprite_venv/Scripts/python.exe -m pytest tests/damage tests/abilities tests/rts
  tests/test_hit_core.py tests/test_server_enemy_authority.py tests/test_walk_animation_phasing.py
  tests/test_wall_collision.py tests/test_enemy_puppet.py tests/test_entity_gates.py
  tests/test_coop_player_damage.py tests/test_headless_level.py tests/test_mesh_contact.py
  tests/test_mesh_player.py tests/test_equipment.py tests/test_server_players.py
  -q -p no:cacheprovider -rfE`.
  Known failures (11, before chunk 1): test_enemy_dash 1, test_player_charge_controller 1,
  rts/test_gather 1, test_enemy_puppet 2, test_entity_gates 2, test_coop_player_damage 2,
  test_mesh_contact 2.
- Crowd bench (damage path speed): `Code/sprite_venv/Scripts/python.exe tools/damage_crowd_bench.py
  600 20` from the worktree root. Real Level4 headless, 40 units in two hostile crowds; mean/p95 ms
  per frame, then one `strike` over the crowd (µs). Noisy (AI on the clock): 3 runs, compare means.
- Deleted code is restored from git, not a legacy folder: `git show <commit>^:<path>`
  (the commits are in the Log).
- Item stats: `Graphics/Standard_Items/item_bases.json` (hand-written, by base id: `plate_chest`, `loincloth`).
  An item names its base in `base`; outfit items get it from `equip_install.py`
  (`equipment.piece_base`: the outfit json's `"material"` + the piece, left and right share one). Stats never
  go in `outfit_items.json` (rewritten on install).
- Properties: one row each in `Code/item_properties.py` (`PROPERTIES`: id, label, group, format, better,
  card line / detail, template, optional threshold `at`). A new property = a row + a field in the bases.
  Weight class (light / medium / heavy): `WEIGHT_CLASSES` by body slot kind.
- Card text: `Code/item_card.py` `build(item)` (no pygame); drawn by `inventory_view.CardPanel` (rows made
  once per item / durability / detail key / size, TextSlot per row). Shift held: every number.
- Tests: `tests/test_item_card.py`.

## Known errors

- Settings.py has CRLF line endings: a regex edit with `\n` matches nothing. Use `\r?\n`.
- `tests/test_entity_pipeline.py` fails (FileNotFoundError `Code\Settings.py`) when run in one pytest
  call after any test that imports `Settings`: Settings (and 9 other modules) `os.chdir` into `Code/`
  and `wire.SETTINGS` is relative to the repo root. Same cause as the known `test_entity_gates`
  failures. Run it on its own (22 passed). Not fixed (older than this work).
- `Path.read_text()` turns CRLF into LF, so a script that checks for `\r\n` after it finds none
  and writes the file back with LF (git shows no diff, autocrlf, but the working copy changes).
  Read and write bytes (`read_bytes`) and keep the file's own endings.
- Outside the targeted set, `test_remote_player.py` (2: snapshot position and facing, camera kwargs)
  and `test_multiplayer_level_inbox.py::test_state_update_applies_snapshot_to_existing_remote` fail
  on `refactor/elemental` too. Not from the damage work. Not fixed.
- A test stub that borrows `Entity.can_receive_interaction` needs `takes_impulse = True` (the class
  field it reads); one that borrows `Entity.receive_interaction` for damage needs `take_damage`.
- `Code/interaction_validation.py` FactionPolicyRoute fails (`npass_e1=True`): it expects a
  `neutral_passive` hit on `enemy_1` refused, but the policy lets a neutral damage a hostile.
  The script's expectation is stale (older than this work). Not fixed.
- The impulse (shove) team rule still lives in the body gate (`can_receive_interaction`), not in
  `team_allows` (which rules damage only). One place for shoves too: not done.
- `sed -i` in Git Bash rewrites a CRLF working copy as LF (git shows no diff; autocrlf). Edit with
  a script that keeps the file's endings.

## Log

- 2026-11-14: design talk; this doc written. No code changed.
- 2026-11-14: item card plan written (`.cursor/plans/item_card.plan.md`).
- 2026-11-14: card chunks 1 + 3 (no verdicts), plate and loincloth (branch `feat/item-card`). First numbers:
  plate stopping_power 40, absorb 0.15, conductivity 0.9, insulation 0.2; loincloth 0 / 0.05 / 0 / 0.1,
  flammability 0.8. Weight class thresholds per slot kind invented (to tune). Window rendered (CPU) at 800×600,
  1280×720, 1920×1080, card and detail view looked at. Pack cells shrink to make room; rows keep their
  heights so the arrow moves are unchanged (test_inventory_nav passes as before).
- 2026-11-14: Part 2 added: code layout, data files, attack and body roster, changes per file, tests
  per chunk. Read for it: `Settings.py` monster_data, `Interaction.py`, `Player.py:165-255`,
  `combat_unit.py:790-860`, `CombatStrategy.py:130-160`, `Particles.py:243-300`, `Weapon.py`,
  `attack_sprite.py`, `Level4_tmxdev.py:1555-1595, 2130-2150`, `tests/test_hit_core.py`.
- 2026-11-14: chunk 1 (knockback by mass) on `refactor/knockback-mass`. Targeted tests (abilities,
  rts, hit_core, server enemy authority, walk phasing, wall collision, enemy puppet, entity gates,
  co-op damage, headless level, mesh contact, mesh player, equipment): before 11 failed / 241 passed;
  after 11 failed (the same names) / 284 passed (43 new in `tests/damage/`). Not checked in play.
- 2026-11-14: chunk 2 (attack defs) on `refactor/attack-defs`. Warriors mapped from
  `generated/entity_pipeline/pyramid3/sheet.png` (row order = `layout.json`); 13 = club confirmed by
  Douglas; 07 checked in its attack frames (curved blade). Same targeted set + `tests/damage`:
  11 failed (the same names) / 332 passed (48 new). `test_entity_pipeline.py`: 22 passed.
  Not checked in play (nothing should play differently; arrows and stones must still stop).
- 2026-11-14: chunk 3 (contact point) on `refactor/contact-point`. Same targeted set: 11 failed (the
  same names) / 367 passed (35 new in `tests/damage/test_contact.py`). Micro-benchmark in
  `Code/NOTES_performance.md`: `find_contacts` +3-7 % over `find_hits`; `entry_point` ~20 µs, so
  lazy (`EntryPoints`). Debug dots not seen yet (camera draw has no test). Not checked in play.

- 2026-11-14: chunk 4 (bodies and layers) on `refactor/defence-layers` (with `main` merged in for the
  item card). 19 bodies (warriors split by what they are, from a picture with Douglas), camel /
  catapult / scorpion masses, defence profiles (worn weight → knockback: full plate 31 → 74%), region
  lookup (front-most capsule). Targeted set + item card: 11 failed (the same names) / 450 passed.
  Not checked in play.

- 2026-11-15: chunk 4b (visual hits) on `refactor/visual-hits`. Hero hit on capsules first; pictures
  against the full mesh showed them fat (35% air, 2x too deep from the side); mesh points built and
  made the default (11% air, 91% same body part, ~same cost). Worn pieces in the outline; plate or skin
  as drawn on 96% (plate) / 98% (loincloth) of 506 / 512 arrows within 1 px. Capsule bake: ends pulled
  in (barb re-baked). Targeted set: same 11 failures. Not checked in play.
- 2026-11-17: Douglas watched `points_vs_capsules` (12 arrows on points, 12 on capsules). Points stays
  the default; capsules stay. Chunk 5 plan written (`.cursor/plans/physical_resolve.plan.md`, branch
  `refactor/physical-resolve`). Not built.
- 2026-11-17: chunk 5 (physical resolve) built on `refactor/physical-resolve`. `damage_rules.physical`
  + `hit_resolve`; apply sets the landed int. Arrow on plate is 0 and does not flinch; skin takes the
  arrow; demon claw 37 on plate, 44 naked (`BRUISE_SCALE` 0.05). New tests 19 passed. Targeted set:
  11 failed (the same names) / 495 passed. `plate_stops` headless: plate 9 bad 0, skin 4 hurt 2.
  Resolve itself 2.1-2.7 us unarmoured, 2.8-3.8 us for three layers (outline lookup not included).
  Not watched in the window.
- 2026-11-17: chunk 6 plan written (`.cursor/plans/conditions.plan.md`). The clock, a buff, and a
  `haste` validation scene that grants it so the speed change can be walked. Not built. Fire, venom
  and the packet stay in 7 and 8.
- 2026-11-17: chunk 6 (conditions) built on `refactor/conditions`. One heap per level, peeked next to
  `entity_id_map` (a render client does not tick). `speed_of` is the stat plus live buffs; the player
  move is the one read. Death bumps `condition_gen` (`Enemy` and `friendly` copy `check_death`, so the
  call is in those copies too). `haste` is speed +4 for 8 s, granted only by the `haste` scene.
  Empty `tick` 0.155 us, empty `bonus` 0.227 us (200k calls). New tests 10 passed. Targeted set:
  11 failed (the same names) / 505 passed. `haste` headless: base 5, saw the +4, ended back at 5.
  Not watched in the window. Fire, venom and the packet stay in 7 and 8.
- 2026-11-17: chunk 7 plan written (`.cursor/plans/elemental.plan.md`). Fire catches or cooks, ice
  slows, lightning uses conductivity and wet. Not built. Holy, unholy, negative weakness and venom
  stay in 9 and 8.
- 2026-11-18: chunk 7 plan revised after talk. One resolve: no card keeps the flat amount; a card runs
  physical then fire, cold and lightning. Full detail is the curve and every arc; simple is three
  shades and at most one jump. Lightning knobs are damage, reach, arcs, spark. Cold is a
  temperature; constitution cuts how much sticks and how fast it fades. Three blues on skin, three
  reds on the hot layer. Not built.
- 2026-11-18: chunk 7 (elemental) built on `refactor/elemental`. Fire catches or cooks, cold is a
  temperature (wound 9 and 3.5 s slow at constitution 10; constitution 20 sticks half and does not
  slow), lightning jumps by charge (plate 95, passes 45, reach 162). Monsters' hits use the body
  card they already had. `elemental` headless: drops 3, 15, 9; plate red not skin; cloth searing;
  skin severe blue; slow then back to 5. Full cold apply 7.5 µs, simple 4.4 µs, a 4-arc bolt
  against 8 bodies 3.3 µs (20k calls). Not per frame. Targeted set: 11 failed (the same names) /
  517 passed. Not watched in the window. Holy, unholy, a weakness that increases damage, and venom
  stay in 9 and 8.
- 2026-11-20: one damage path (`refactor/damage-path`, from 7's last commit). Before: 8 receivers
  each priced, gated and subtracted (`get_damage` in Player, Enemy, CombatUnit, Friendly, Eskimo,
  PolarBear, Trap; `take_environmental_damage`; `receive_interaction` copies), plus dead
  `Level4.damage_player` and three unimported strategy files. Now: resolver `land` decides,
  `Entity.take_damage` applies, `on_hurt` reacts. Changes in behaviour: a hit in the invulnerable
  window no longer starts elements or retaliation (still spent, as before); enemies, neutrals and
  workers play their hit sound on every non-ground hit (only the old amount-less path did); enemies
  no longer turn to face the player when hit (only that old path did); the attacker memory of
  CombatUnit and Friendly moved into `register_retaliation`; the co-op relay goes through `land`;
  Player `hurt_time` is `hit_time` like everyone else. Targeted set: 11 failed, the same names as
  before; 528 passed (517 before, plus `test_server_players` 5 and the new
  `tests/damage/test_damage_path.py` 6).
- 2026-11-21: foundation cleanup, steps 1-6 of `PLAN_damage_foundation.md` (`refactor/damage-path`).
  1 `202fdcfd` deleted `Code/Enemy.py`, `Code/friendly.py`, `Code/tribey_geom_probe.py` (restore:
  `git show 202fdcfd^:Code/Enemy.py`), 31 inert `damage_player` keys, the unused projectile
  multiplier/bonus. 2 `d87dc708` no resolver fallbacks (Entity lava, IceClone, leap slam); slippery
  set directly (the `effect_state` kind, its benchmark column and 2 validation scenarios gone); one
  team rule `team_allows` (leap slam's, the meteor's and the body gate's checks gone). 3 `e429ea58`
  `die()` / `on_death()`; dies at the killing hit (before: at the victim's next update); Eskimo,
  PolarBear and workers now drop their conditions on death; every tribe member leaves the entity tree
  (before: only workers given a callback); the level loop and camera group skip a body killed earlier
  in the frame. 4 `31649c6f` `sounds.get`; Hit.wav was loaded per instance. 5 `faea0307` one
  attacker record; a passive faction's leave to fight back now expires (before: never, `until > 0`);
  the resolver no longer clears the AI's target cache (`_aggro_cache_valid` already does when the
  preferred team changes). 6 `0849cecb` `invulnerable` condition, `over_time` gone; the player's
  one-frame window after a hit is gone, so two hits in one frame both land; results LANDED / SPENT /
  REFUSED. Targeted set after each step: 11 failed, the same names; 540 passed with the guard (528
  before). Crowd bench, 3 runs each, 600 frames, 40 units: before mean 8.28 / 8.66 / 8.24 ms, p95
  11.7 / 12.9 / 11.4, strike 278 / 223 / 248 µs over 36 / 33 / 33 targets (~7 µs each); after mean
  7.47 / 7.73 / 7.78 ms, p95 10.9 / 11.8 / 11.2, strike 192 / 168 / 163 µs over 38 / 37 / 34 (~4.8
  µs each).
- 2026-11-21: foundation step 7, prices from defs only. Douglas: the number belongs in the def; a
  monster's strength is its stat. A hit has a def or an already-priced amount (relay, hop, lava),
  never both, never neither (ValueError). Removed: `damage` in `weapon_data` (6) and in every monster
  attack (36), flame/ice_ball `strength`, leap_slam `base_damage`, meteor `burst_damage`/`dot_damage`
  (now `scale`), `_resolve_projectile_damage_payload`, trap/ice-clone `amount`,
  `Player.get_full_*_damage`. Monsters whose number was above the def got `stats.attack` = the
  difference (warriors 1-2, workers 1, chiefs 5, venom plant 10); every monster attack def
  `scales_with` attack or magic. Changes in play: ice mage's ice shard blow 15 → 8 (its def; the
  staff keeps 15); meteor fire now scales with size like its blow; a blast or leap on a body with no
  card rounds to a whole number. Holy or unholy alone is its power (`flat`). Checks: targeted set 11
  failed, same names, 543 passed; `interaction_validation.py` same as before (only FactionPolicyRoute,
  stale); headless smoke in the real level: warrior_01 spear on a bare body 8 (was 8), arrows from
  warrior_06 land on the hero, meteor impact and embers land, hero's unarmed hit lands on a squid.
  Crowd bench after: mean 7.73 / 7.83 / 8.37 ms, p95 10.6 / 10.7 / 12.7, strike 181 / 161 / 176 µs.

## Tried and dropped

- **Mesh hero hit on his 2D sprite mask** (chunk 4, decision 2 of `defence_layers.plan.md`, my
  recommendation): the sprite pose is not the drawn mesh's, so an arrow can visibly hit his arm and
  miss, or hit beside him. Fails the Goal's "what you see is what you hit"; replaced in 4b by his
  posed capsules.
- **Armour per whole region** (chunk 4, decision 4: per-bone coverage deferred): a visible gap in a
  piece still counts as plate. Fails the same Goal; replaced in 4b by coverage baked per piece.
- **Mesh hero hit on capsules as the default** (4b): one round tube per bone is as deep as it is
  wide (2x too deep from the side, a wedge of air over the head; 35% air vs the drawn mesh). Kept as
  the other choice; points are the default.
- **Armour coverage baked per bone (u, angle)** (4b's first design): not built; the pieces' own points
  say plate or skin where they are drawn, no bake.
- **Hit region by the nearest capsule edge** (chunk 4, as first planned): from the side, a hit landed
  on the arm hidden behind the body, and big capsules swallowed the neck. Replaced by the front-most
  capsule under the contact (depth toward the camera); region map at 4 facings compared both.

- **Armour points subtracted from damage** (D2 style): late-game darts beat plate; replaced by
  penetration vs stopping power plus force.
- **Tiers** (dart < arrow < bolt vs leather < mail < plate): no faster than constants and less
  flexible; replaced by `penetration` / `stopping_power` numbers.
- **Named materials in rules** (`if plate`): replaced by property-driven rules.
- **Wards per spell**: replaced by general buffs on resistance stats.
- **Coverage roll for holes**: not precise enough; replaced by exact lookup at the contact pixel.
- **Magic physical / magic elemental as types**: a spell is a delivery plus a category; no extra type.
