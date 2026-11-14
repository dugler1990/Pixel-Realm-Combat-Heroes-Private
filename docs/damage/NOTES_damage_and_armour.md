# Damage, armour, magic and conditions: the master plan

Started 2026-11-14. Source talks: `docs/ideas/raw/2026-11-14-armor-and-damage-types.txt` (in the main
folder, untracked) and the Claude Code chat of the same day.

This doc holds the whole system. Each chunk in **Chunks** becomes its own `.cursor/plans/*.plan.md`;
when one is written or finished, check it against this doc and fix whichever is wrong.

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
- Simple bodies stay simple: a body with one flesh layer and no conditions takes today's fast path.
  Layers, wear and stuck arrows are opt-in (player, key bosses).

## Terms

| term | meaning |
|---|---|
| attack def | data row for one attack: damage, penetration, force, delivery, natures/magic, flags |
| delivery | how force arrives: `pierce`, `crush`, `blast`. Physical. Armour answers it |
| magic category | what a spell is: `fire`, `ice`, `lightning` (elemental), `holy`, `unholy`, more later |
| nature | a magic category or `venom` carried by a blow (poisoned dart, holy hammer, fireball) |
| layer | one worn piece over one body region; up to 3 deep (under, mid, outer) |
| body | the creature's own constants: mass, attributes, natural layer, kind |
| contact point | the exact pixel where the attack first met the body |
| condition | something with a clock on a body: venom, hot shell, frozen joints, wet, buff |
| resistance | a stat per magic category; buffs, gear and attributes add to it |

## Data

All loaded once and **compiled**: names become int ids, rule tables become flat lists indexed by id.
The hot path never looks up a string.

### Attack def
```
tribe_dart:   delivery pierce, damage 4,  penetration 10,  force 2,   natures [venom frog_venom dose 1]
iron_mace:    delivery crush,  damage 30, penetration 0,   force 60
ballista:     delivery pierce, damage 80, penetration 120, force 400
fireball:     delivery blast,  damage 10, force 80, magic [fire 40]
holy_hammer:  delivery crush,  damage 25, force 50, magic [holy 20]
lightning:    no delivery,     magic [lightning 50]
venom_gas:    no delivery,     natures [venom marsh_venom dose_per_s 1]   (an effect area, not a sprite)
```
A sprite carries only `attack_def` (an id). Everything else is looked up. Attacker stats and buffs
are applied at hit time, not stored on the sprite.

### Layer properties (per piece)
| property | does |
|---|---|
| `stopping_power` | penetration a point must exceed to get through |
| `absorb` | 0..1, how much force it cushions (padding, fur high; plate low) |
| `conductivity` | lightning conducts into the wearer and can jump |
| `insulation` | how slowly heat gets in and out |
| `flammability` | catches and keeps burning |
| `sealed` | stops gas (head slot) |
| `coverage` | which regions, and which parts of them (holes are exact, see Contact) |
| `weight` | adds to mass, slows movement |
| `durability` | goes down per hit; thresholds lower `stopping_power` / break the piece |

### Body constants
`mass`, `strength`, `constitution`, `magic`, `charisma` (existing attributes), `kind`
(`living`, `undead`, `demon`, ...), a natural layer (hide, scales: same properties as a piece),
resistances per magic category. Attribute list grows as needed.

### Magic categories and resistances
- Registry of categories with a parent: `elemental` → `fire`, `ice`, `lightning`; `holy`; `unholy`;
  room for more (e.g. `mind`) as rows.
- A spell names its category and power. Resistance for a category = own + parent's
  (`fire` resist + `elemental` resist).
- Resolve as a threshold, like `HeatEffect` already does (`Effect.py:115`):
  `max(0, power − resistance)`. High enough resistance = immune.
- No wards. Protection from magic is **buffs**: timed modifiers to any stat (a resistance, `absorb`,
  `stopping_power`, speed). A buff is a condition with an end time.

### Conditions
One definition per condition: tick rate (or none), end rule, stacking, the save (stat and
difficulty), the cure (item id). Instances on a body: `(cond_id, start_ms, end_ms, strength)`.

## A hit, step by step

0. **Team and avoid**: existing team policy, dodge, parry, block.
1. **Contact point**: the pixel where the attack met the body (see Contact).
2. **Physical** (if the attack has a delivery), layers outer → inner at the contact point:
   - point: `excess = penetration − stopping_power`. `≤ 0`: stops here. `> 0`: goes to the next
     layer with `penetration = excess`.
   - force reaching the body = `force × Π(1 − absorb)` over the layers it passed or stopped on.
   - point stopped: body takes **bruise** = that force. Point through: body takes `damage` + force.
   - crush, blast: no penetration test; force through absorb.
   - each layer hit loses durability (see Wear).
3. **Natures**: each nature's rule reads the outermost layer hit, the body's states and `kind`:
   - lightning: `max(0, power − resist) × (1 + conductivity)`; wet multiplies; jumps to near
     conductive or wet bodies.
   - fire: flammable layer catches (burning condition). Else heat goes into the piece; `insulation`
     sets how fast it reaches the body and how long it stays (hot shell condition).
   - ice: slow; high conductivity seizes joints (worse slow); wet ground freezes.
   - holy / unholy: always lands, through armour; size by `kind` (severe on undead and demons).
   - venom: only if a point reached flesh, or gas reached an unsealed face. Then the venom rules.
4. **Impulse**: one path for every push. Displacement = impulse / (body mass + gear weight),
   reduced by strength. Blasts and body checks use it.
5. **Conditions**: start or extend timers (venom, burning, hot shell, frozen, wet).

Partial penetration (optional, later): `excess` left after the last layer scales the wound, so a
point that barely got through mail hurts less than one into bare skin. Also sets how deep a stuck
arrow sits. Without it: through = full damage.

## Contact: precise, mask collision kept

The existing hit test stays as it is (`hit_core.py`): rect, then mask against mask.

1. **The point is already found.** `hit_core.touching` calls `mask.overlap(...)`, which returns the
   first overlapping pixel, and drops it with `is not None` (`hit_core.py:130`). Keep that pixel:
   no extra cost.
2. **Projectiles: the entry pixel.** The overlap's first pixel is first in scan order, not where the
   arrow entered. From the arrow's tip, step back along its direction over the body mask with
   `get_at` until outside: at most its per-frame travel in reads (10–20). That pixel is where it hit.
3. **Which layer is there.** Only bodies with layers do this.
   - Sprite bodies (bosses): one mask per worn slot per animation frame, built when frames load
     (`hit_core.frame_masks` already makes masks per frame). `slot_mask.get_at(point)`, outer first:
     1–3 reads. Holes are transparent pixels, so they are exact.
   - Mesh bodies: the hit mask is the posed capsules (`mesh_boss.build_body_mask`, cached per frame
     and facing). Rasterize each capsule with its index as colour into the same cached image: the
     contact pixel gives the bone. From the capsule's projection, the point's position along the bone
     (u) and around it (angle). Each slot bakes, at export, a small coverage bitmap per bone in
     (u, angle). One read. Holes in the 3D piece are exact.
4. No contact point (rect fallback, ground blasts): ground blasts are `blast` (no point needed);
   rect fallbacks use the centre of the overlap.

## Force, absorb, bruise

- `force` is a property of the attack (mass × speed of the thing), not of how deadly it is. A dart's
  bruise on plate is a speck; a ballista's is a log.
- `absorb` multiplies down per layer; a gambeson under plate is what makes the mace bearable.
- Natural `absorb` (fat, hide) uses the same rule.

## Knockback and mass (today: three paths, mass ignored)

- `Entity.weight` (`Entity.py:84`) only scales input acceleration (`Entity.py:356`).
- `apply_impulse` (`Entity.py:1137`) moves by the force as given, mass not used.
- Enemy `resistance` multiplies knockback on enemies (`Enemy.py:558`, also `combat_unit.py:879`,
  `friendly.py:571`); it is a knockback strength, not a defence.
- `MeleeCombatStrategy.py:63-66` writes `player.rect` directly: skips the wall check.
- Target: one path through `apply_impulse`, dividing by body mass + gear weight.

## Conditions and the scheduler

Today: no timed conditions. Effects belong to areas and are checked every frame (`Entity.check_effects`,
`Entity.py:839`); `should_persist_after_exit` exists but every effect returns False, so all end on
exit (`Effect.py:62`). Timers are scattered `*_until_ms` fields. `apply_environmental_damage` builds
a new `InteractionContext` with a new `tags` set per entity per frame while in fire
(`Entity.py:1069`).

Target:
- One heap per level: `(due_ms, seq, entity_id, generation, cond)`. Checked in the level update next
  to `entity_id_map` (not in draw), so the headless server runs it too.
- Per frame: peek the top; pop only what is due. Push and pop O(log n).
- A cured condition or a dead entity bumps `generation`; stale heap entries are skipped when popped.
- Values that change smoothly are computed when read, not ticked. Piece heat stores `(heat, t)`:
  now = `ambient + (heat − ambient) × e^(−k·Δt)`. The time it falls below the cook threshold is solved
  ahead, so "hot shell" is scheduled with its end already known.
- Areas (fire floor, gas cloud, slippery ice) stay on `check_effects`; what they leave behind
  (burning, venom dose, wet) becomes a condition.
- Network: the server owns conditions and sends `(cond, start, end, strength)` once; the client works
  out symptoms from the clock.

### Venom
- Starts only on flesh (a point through, a bite, gas on an unsealed face).
- Constitution save on first dose: can shrug off a weak dose; otherwise sets the clock length.
- More doses bring `death_at` earlier. Gas adds dose per second in the cloud.
- Symptoms by time since start (blur, slow, stumble, death). Healing does not touch the clock.
- Each venom has its named antidote; that is the only cure. Generic remedies can slow it.

## Armour wear

- Per hit: durability −= force reaching that layer × wear rate (property). Computed only on hit.
- Thresholds: dented (stopping power or coverage down), broken (layer gone). Repair at a smith.
- Change rebuilds that body's defence profile (dirty flag), not every frame.
- NPCs: most have no layers. Key bosses can. Shared profiles: all fighters of a type share one;
  a boss whose piece takes damage copies its own on first hit.

## Stuck arrows

- Stored as the contact data: sprite bodies `(offset from rect centre, flipped with facing, angle,
  depth)`; mesh bodies `(bone, u, angle, direction, depth)`, drawn on the bone each frame.
- Cost: one transform and one sprite per stuck arrow per frame; same atlas texture, so batched into
  one draw call. Cap per body (about 8, oldest drops), pooled sprites.

## Item card

Say the facts and the cost, not a column of numbers:
- Stops: arrows, darts, cuts.
- Through: maces, blasts (cushioned).
- Weak to: lightning, fire (holds heat).
- Heavy: slower, thrown less, sinks.
- Covers: torso, upper arms.
Numbers in a detail view. Character sheet: the body with pieces, weight, speed, resistances.

## Performance rules

- Zero per-frame cost from this system except the heap peek.
- Per hit on a plain body (one flesh layer, no natures): today's path plus one id lookup.
- Fast paths by bitmask: `atk.nature_mask & body.reacts_mask == 0` skips natures; bodies without
  layers skip the layer walk.
- Shared, compiled data (`__slots__`, int ids, flat lists). No dict of strings on the hot path.
- Contact point: reuse the overlap pixel; projectile step-back ≤ 20 `get_at`; layer lookup ≤ 3 reads.
- Measure each chunk on the fixed 200-entity ice scene and log it in `Code/NOTES_performance.md`.

## What exists today

| piece | where |
|---|---|
| hit test, rect then mask | `hit_core.py` (`find_hits`, `touching`) |
| mesh hit mask from posed capsules, cached | `mesh_boss.py:217` `build_body_mask`; `combat_unit.py:911` |
| one damage/impulse entry | `Interaction.py` `InteractionResolver.apply`, `strike` |
| hit context | `Interaction.py:12` `InteractionContext` (`attack_type`, `tags`, impulse) |
| area effects, heat threshold | `Effect.py`, `Entity.check_effects`, `apply_environmental_damage` |
| `fire_resistance` | `Entity.py:102` (0, unused by stats yet) |
| item effects with `frost_resistance` | `items.json` |
| body capsules baked per outfit | outfit plan, `bake_body_capsules.py` |

Flags:
- `attack_type` does three jobs: combat strategy (`melee`/`ranged`/`mixed`, `Settings.py:382`), the
  hit-particle key (`Player.py:179`), weapon vs magic damage (`Player.py:220`). `attack_def` is a new
  field; the old one is split by job.
- Enemy `resistance` is knockback strength (see Knockback).
- Knockback write in `MeleeCombatStrategy.py:63-66` skips walls.

## Chunks

Each becomes its own plan. Order follows the arrows; 1 is independent.

1. **Knockback merge.** One impulse path, mass-based, walls respected. Retire enemy `resistance` into
   mass. Isolated, first.
2. **Attack defs.** Registry and loader; `attack_def` id on every attack sprite; split `attack_type`
   by job. Every def still deals today's flat damage. → 3, 5
3. **Contact point.** `hit_core` returns the overlap pixel; projectile entry step-back. Nothing uses
   it yet but a debug draw. → 4, 11
4. **Bodies and layers.** Piece properties, defence profile built on equip (shared, copy-on-write),
   slot masks per frame for sprite bodies, bone id map and per-bone coverage bitmaps for mesh bodies
   (needs the per-slot draw plan from the outfit pipeline). → 5
5. **Physical resolve.** Penetration, absorb, bruise in the resolver. First real behaviour: plate
   stops the dart. → 10, 12
6. **Conditions and buffs.** Level heap, condition defs, generation skip, server-owned, sent once.
   → 7, 8, 9
7. **Elemental natures.** Fire, ice, lightning rules; wet state; piece heat computed when read; hot
   shell. Fold `fire_resistance` and `HeatEffect` into it.
8. **Venom.** Clock, constitution save, named antidotes (items), gas clouds as effect areas.
9. **Magic categories and resistances.** Category registry with parents, resistance stats, buffs that
   change them, holy/unholy by `kind`.
10. **Armour wear.** Durability, dented/broken, repair.
11. **Stuck arrows.** Attach, draw, cap, pool.
12. **Item card and character sheet.**
13. **Boss with layers.** One key boss using 4, 5, 10 to prove NPC opt-in.

## Open

- Partial penetration (depth scales the wound): in chunk 5 or later?
- Attribute list: which attributes feed which saves and resistances (grow as needed).
- Lightning jump: range and how many bodies.
- Can a body change kind (a cursed player taking holy damage)?

## Method that works

(empty)

## Known errors

(empty)

## Log

- 2026-11-14: design talk; this doc written. No code changed.

## Tried and dropped

- **Armour points subtracted from damage** (D2 style): late-game darts beat plate; replaced by
  penetration vs stopping power plus force.
- **Tiers** (dart < arrow < bolt vs leather < mail < plate): no faster than constants and less
  flexible; replaced by `penetration` / `stopping_power` numbers.
- **Named materials in rules** (`if plate`): replaced by property-driven rules.
- **Wards per spell**: replaced by general buffs on resistance stats.
- **Coverage roll for holes**: not precise enough; replaced by exact lookup at the contact pixel.
- **Magic physical / magic elemental as types**: a spell is a delivery plus a category; no extra type.
