# Plan: attack definitions (damage chunk 2)

Written 2026-11-14. Chunk 2 of `docs/damage/NOTES_damage_and_armour.md`. Branch
`refactor/attack-defs`, worktree `..\Pixel-Realm-attack-defs`, started from
`refactor/knockback-mass` (chunk 1, not merged yet).

## Goal

Every attack in the game names an **attack def**: one data row saying what kind of blow it is
(delivery, penetration, force, magic, venom, whether it stops at the first body). Every attack sprite
and every strike carries it into the `InteractionContext`. **Nothing plays differently**: damage is
still today's flat amount. Chunk 5 starts reading the defs.

## Decisions (and what changed from the master doc)

- **Attack defs only.** Body defs wait for chunk 4/5: chunk 1 already put `mass` on monsters, and
  nothing else in a body is read before then.
- **Properties are not repeated.** The item card branch (merged in `main`) keeps the property rows in
  `Code/item_properties.py`; armour layers will use those. No `config/damage/properties.json`.
- **Damage: the def is the kind, the hookup can tune it.** A def holds the default `damage`; an
  attack in `Settings.py` may keep its own `damage` (20 tribe warriors share `tribal_club` at 6, 8, 9
  or 10). Chunk 2 reads damage exactly where it does today.
- **`stops` moves into the def.** Today `fire_projectile` decides it from the name
  (`stops = projectile_type != "demon_dog_projectile"`, `Level4_tmxdev.py:1802`). The def says it.
  Same values as today, so the same behaviour.
- **`attack_type` is not split here.** Its three jobs (combat strategy, hit particle, weapon vs magic
  damage) stay. The third goes away in chunk 5, when the resolver computes damage from the def; the
  strategy rename is its own small change later. Splitting it now is churn with no gain.
- **Server relay** (`Level4_tmxdev.py:2142`, client-computed amount): unchanged; carries no def yet.

## What is there today (read 2026-11-14)

Where attacks are made and where their damage comes from:

| attack | made in | damage from |
|---|---|---|
| player weapon swing | `Weapon.__init__` (`Weapon.py`), `Level4_tmxdev.py:1512` | receiver: `stats["attack"] + weapon_data[w]["damage"]` |
| player flame, ice ball | `Magic.flame`, `Magic.ice_ball2` → `AnimationPlayer.create_particles` | receiver: `stats["magic"] + magic_data[m]["strength"]` |
| enemy melee | `CombatStrategy.py:140` `resolver.strike` | `melee_attacks[i]["damage"]` |
| enemy projectile | `CombatStrategy.py:285, 421` → `Level4.fire_projectile` (`:1759`) → `create_particles` | `ranged_attacks[i]["damage"]` via `_resolve_projectile_damage_payload` |
| multishot iceball | `SpecialAttacks.py:173` → `fire_projectile(amount=None)` | the owner's ranged attack of that type |
| meteor | `SpecialAttacks.py:333` → `meteor_strike._apply_damage` | `burst_damage`, `dot_damage` |
| dash hit (player slide, raccoon Dash) | `abilities/dash.py:151` | dash config `damage` |
| leap slam | `abilities/leap_slam.py:358` | `base_damage` × charge × falloff |
| ice clone burst | `IceClone.py:42` | `amount` or 50 |
| heat floor | `Entity.apply_environmental_damage` | effect `heat` (stays out: chunk 7) |

All but heat reach a target through `InteractionResolver.apply` / `strike` with an
`InteractionContext`; attack sprites through `Level4._strike_with_attack_sprites` (`:1555`).

## Data: `Code/config/damage/`

`categories.json`:
```json
{"schema_version": 1,
 "deliveries": ["pierce", "crush", "blast"],
 "categories": {"elemental": null, "fire": "elemental", "ice": "elemental", "lightning": "elemental",
                "holy": null, "unholy": null}}
```
(name → parent; `null` = top level.)

`attacks.json`: `{"schema_version": 1, "attacks": {name: row}}`. Row fields, all optional but one of
`delivery` / `magic` / `venom`:

| field | meaning | default |
|---|---|---|
| `delivery` | `pierce` / `crush` / `blast` | none |
| `damage` | default damage (a hookup may tune it) | 0 |
| `penetration` | for pierce | 0 |
| `force` | for bruise and shove | 0 |
| `magic` | `{category: power}` | `{}` |
| `venom` | `{"id": name, "dose": n}` (names checked in chunk 8) | none |
| `stops` | stops at the first body it lands on (projectiles) | false |
| `scales_with` | `attack` / `magic`: the player stat added to damage | none |

First rows (the master doc's roster plus what the warriors use):
`unarmed, sword, rapier, sai, axe, lance, flame, ice_ball, leap_slam, dash_hit, ice_clone_burst,
demon_claw, meteor_impact, meteor_embers, squid_slap, snake_bite, raccoon_claw, spirit_touch,
bamboo_whip, ghost_chill, spear_thrust, fire_spit, thorn, staff_strike, ice_shard`, the warriors'
`arrow, stone, tribal_club, scimitar, curse_bolt, sun_bolt, catapult_shot, scorpion_sting`, plus the
card's reference rows `crossbow_bolt, ballista, storm_bolt, holy_smite, blowgun_dart` (no hookup yet).
`stops` as today: `arrow`, `stone`, `catapult_shot` true; `fire_spit`, `thorn`, `ice_shard`,
`curse_bolt`, `sun_bolt` (all fired as `demon_dog_projectile` art) false.

### The warriors (`warrior_00`..`19`, sheet `generated/entity_pipeline/pyramid3/sheet.png`)

Numbered across the rows of the sheet (`layout.json`). Weapon from the sheet's label and picture,
checked against what each one fires today in `monster_data`; 07 and 13 also checked in their attack
frames (`Graphics/Monsters/warrior_NN/_contact.png`).

| warrior | sheet | attack |
|---|---|---|
| 00, 06, 12 | archers (06 on a camel) | `arrow` |
| 01, 02, 05, 08, 14 | spearmen (05 on a camel) | `spear_thrust` |
| 09 | camel standard bearer (spear-tipped pole) | `spear_thrust` |
| 03, 04, 10, 11 | curved blades (jaguar priest, pharaoh's guard, scimitars) | `scimitar` |
| 07 | desert chieftain, curved blade from a camel | `scimitar` |
| 13 | warrior with club/mace (confirmed by Douglas) | `tribal_club` |
| 15 | catapult crewmember, throws a stone | `stone` |
| 16 | magic-user | `curse_bolt` (unholy) |
| 17 | high priest | `sun_bolt` (holy) |
| 18 | catapult machine | `catapult_shot` (blast) |
| 19 | scorpion | `scorpion_sting` (pierce, venom) |

Workers and chiefs (eskimo, jungle): `unarmed` (no weapon in their art known to me; flagged).

## Hookups in `Settings.py`

| table | key added |
|---|---|
| `weapon_data[w]` | `"attack": w` |
| `magic_data` `flame`, `ice_ball` | `"attack": "flame"` / `"ice_ball"` |
| `ability_data` `slide`, `create_ice_clone`, `leap_slam` | `"attack": "dash_hit"` / `"ice_clone_burst"` / `"leap_slam"` |
| `monster_data` `melee_attacks[i]`, `ranged_attacks[i]` | `"attack": ...` (damage kept) |
| `monster_data` specials `MeteorShower` | `"attack": "meteor_impact"`, `"residual_attack": "meteor_embers"` |
| specials `Dash` | `"attack": "dash_hit"`; `MultiShotIceball`: `"attack": "ice_shard"` |

`tools/entity_pipeline/wire.py` writes each new warrior's attacks itself (`adjust_entry`), so it
gets `attack_for(label, reach)`: the same words it already uses for the projectile (caster, priest,
catapult) plus spear, club/mace, scimitar/sword/blade, staff, scorpion; arrow / `unarmed` otherwise.

## Code

| file | change |
|---|---|
| new `Code/damage_data.py` | load + validate the two files once (unknown field, unknown category, delivery or attack name → error naming the file and row); `AttackDef` (`__slots__`: `id`, `name`, `delivery`, `damage`, `penetration`, `force`, `magic` as `((category_id, power), ...)`, `magic_mask`, `venom`, `stops`, `scales_with`); `attack(name)` returns the one shared object; `ATTACKS` list by id. No pygame |
| `attack_sprite.py` `init_attack` | `attack_def=None` keyword → `self.attack_def` |
| `Weapon.py` | `attack_def=attack(weapon_data[w]["attack"])` |
| `Particles.py` `create_particles`, `ParticleEffect` | pass `attack_def` through |
| `Magic.py` `flame`, `ice_ball2` | `attack_def` from `magic_data` |
| `Level4_tmxdev.py` `fire_projectile` | `attack_def` argument; `stops=attack_def.stops` (the name rule goes) |
| `CombatStrategy.py:140, 285, 421`, `SpecialAttacks.py:173` | pass the attack's def |
| `abilities/dash.py`, `abilities/leap_slam.py`, `IceClone.py`, `meteor_strike.py` | pass the def into their contexts |
| `abilities/instant.py`, `Spawner.spawn_trap` | the ice clone's trap config carries `attack`; the trap gets `attack_def` |
| `SpecialAttacks.py` `DashAttack`, `MeteorShower`; `Level4.spawn_meteor` | carry the defs from the special's config |
| `tools/entity_pipeline/wire.py` | `attack_for(label, reach)`; `adjust_entry` writes `"attack"` |
| `Interaction.py` `InteractionContext` | `attack_def: Any = None` |
| `Level4_tmxdev.py:1555` `_strike_with_attack_sprites` | `attack_def=attack_sprite.attack_def` in the fields |

An attack made without a def (an old path, a test stub) still works: `attack_def` is `None` and
nothing reads it yet.

## Tests

New `tests/damage/test_damage_data.py`:
- both files load; ids are 0..n−1; `attack("sword")` is the same object each call;
- every `"attack"` / `"residual_attack"` key in `weapon_data`, `magic_data`, `ability_data` and every
  `monster_data` attack names a def;
- every monster attack that deals damage today has a def (no hookup forgotten);
- bad files fail with the row named: unknown field, unknown category, unknown delivery, a row with
  none of delivery / magic / venom (written to `tmp_path`);
- `stops` matches today's name rule for every ranged hookup.

New `tests/damage/test_attack_def_plumbing.py`:
- `fire_projectile` puts the def on the sprite and takes `stops` from it;
- an enemy melee strike (`CombatStrategy` with a stub resolver) sends `attack_def` in its context;
- `_strike_with_attack_sprites` copies the sprite's `attack_def` into the context;
- a context with no def is applied as before.

Regression: the targeted set from chunk 1 (same 11 known failures, nothing new).
Hot path: one more attribute copied per hit; no perf run.

## Commits

1. This plan.
2. `damage_data.py`, the two JSON files, `test_damage_data.py` (hookups added in the same commit).
3. Plumbing through sprites, strikes and contexts, `test_attack_def_plumbing.py`.
4. Master doc: decisions above, chunk 2 log.

## Open

- Warriors 16, 17: `curse_bolt` (unholy) and `sun_bolt` (holy) are guesses from a purple wizard and
  a sun priest. 05 could be `lance` (mounted). Workers and chiefs: `unarmed` is a guess.
- Raccoon `Dash` and the player's slide never deal damage today (no `damage`, collision mode not
  `damage_on_hit`); `dash_hit` rides along, unused.
- Ice clone `explode` is never chosen (the ability is `freeze`); `ice_clone_burst` rides along, unused.
- Player damage still comes from `stats + weapon_data damage`; the def's `damage` for player weapons
  copies `weapon_data` until chunk 5 makes the def the source.
