# Plan: physical resolve (damage chunk 5)

Written 2026-11-17. Chunk 5 of `docs/damage/NOTES_damage_and_armour.md`. Branch
`refactor/physical-resolve`, worktree `..\Pixel-Realm-physical`, from `refactor/visual-hits`
(chunks 1–4b, not merged).

## Goal

The first hit that plays differently because of armour. A pierce stops when its `penetration` cannot
beat the layer's `stopping_power` (an arrow pings off plate and deals 0). The same arrow in skin
deals its damage. Crush and blast still hurt through plate, cushioned by `absorb`. Magic, venom,
wear and partial penetration stay out (chunks 7, 8, 10, and later).

## Decisions (Douglas, 2026-11-17)

1. **Points is the default hit body. Capsules stay.** `Settings.MESH_HERO_HIT_BODY` stays `"points"`.
   `"capsules"` still works. Confirmed by watching `points_vs_capsules` (12 arrows on each half,
   17.6 s). Chunk 5 does not branch on the switch: `body_regions.hit_layers` already returns the
   layers for whichever body is on.
2. **Under the front piece, the region's other pieces.** A points hit uses the worn piece drawn at
   that pixel as the outer layer. A skin pixel is the hide only: a gap is a gap, a gambeson does not
   cover it. A plate pixel then takes the other pieces `defence_profile` lists on that same region
   (a gambeson under the breastplate), harder first among those, hide last. No second outline.
   Capsules and a sprite hero have no per-pixel piece, so they keep the profile's whole region stack.
3. **A ping is not a wound.** Resolved amount 0 still counts: the arrow stops, the repeat rule
   records it. The player does not get i-frames or a hurt flash from it.
4. **Partial penetration waits.** Through means the full damage. A point that barely clears plate
   hits as hard as one into a gap.

## What is there today (read 2026-11-17)

- Every strike already carries `attack_def` and, when the hit test found a pixel, `contact`.
  Nothing reads them. `InteractionResolver.apply` hands the context to `receive_interaction` as it
  arrived.
- Player weapons (`Weapon.init_attack`) set `amount` to None. `Player.receive_interaction` and
  `RemotePlayer` (server) then use `get_full_weapon_damage` / `get_full_magic_damage`
  (`stats["attack"] + weapon_data damage`, `stats["magic"] + magic_data strength`).
- `Enemy`, `CombatUnit` and `friendly` ignore `ctx.amount` whenever the source has those two
  methods, and call `get_damage(source, attack_type)` instead. A resolved amount on a player swing
  would never land.
- Enemy blows already pass their own `damage` from `monster_data` (often not the def's: `fire_spit`
  def damage 0, config 15). Leap slam and the meteor pass a per-target amount (falloff already in
  it) plus the def.
- `hit_layers` → `HitSpot(slot, layers, piece, point)`. Points: `(front piece's layer, hide)` or
  `(hide,)`. Capsules / sprite: `defence.layers_at(slot)`, the whole region. `toward` None means
  the torso is chest.
- Plate bases: stopping_power 40, absorb 0.15. Barb hide: 0 / 0.05. Arrow: pierce, damage 6,
  penetration 30, force 4. Blowgun dart: 4 / 12 / 2 (no enemy fires it yet). Demon hide stops 30.
- Health is subtracted as the amount given. `tribe_member` already does `int(amount)`.

## The rule (`Code/damage_rules.py`, no pygame)

`BRUISE_SCALE = 0.05`. First value, tuned in play. A force of 2 is a speck; 120 still shows.

`Physical(amount, bruise, reached_flesh, stopped_at)` from `physical(delivery, damage, penetration, force, layers)`.
`layers` is outer first, the hide last. Do not mutate the shared `AttackDef` or `LayerDef`.

`cushion = Π (1 − absorb)` over the layers the blow passed or stopped on.

- **pierce.** Walk outer → inner. `excess = penetration − stopping_power`. `≤ 0`: stop on this
  layer. `> 0`: next layer with `penetration = excess`. Stopped: `amount = 0`,
  `bruise = force × cushion × BRUISE_SCALE`, `reached_flesh` false. Through the hide:
  `amount = damage`, `bruise` from every layer, `reached_flesh` true.
- **crush, blast.** No walk. `amount = damage × cushion`, `bruise` from every layer,
  `reached_flesh` false.
- No delivery: `physical` is not called.

`landed = int(round(amount + bruise))`.

Worked with plate then hide (`cushion` 0.85 if it stops on the plate, 0.8075 if it reaches the hide)
and the naked hide (0.95):

| blow | plate | naked hide |
|---|---|---|
| blowgun dart (4 / pen 12 / force 2) | stops, 0 | 4, flesh |
| arrow (6 / 30 / 4) | stops, 0 | 6, flesh |
| spear (6 / 25 / 10) | stops, 0 | 6, flesh |
| sword (15 / 20 / 15) | stops, 1 | 16 |
| crossbow bolt (30 / 55 / 25) | through, 31 | 31 |
| demon claw (40 / crush / 120) | 37 | 44 (plate is 84% of naked) |

Demon hide (stop 30, absorb 0.3): an arrow stops and deals 0. A lance (pen 50) goes through. That is
the roster, and it will show in play.

## Who builds the layer tuple (`hit_resolve.py`, no pygame)

`resolve(ctx) -> Physical | None`. None: leave `ctx.amount` alone.

Called from `InteractionResolver.apply` after the team gate and `can_receive_interaction`, before
`receive_interaction`, only when `kind == "damage"` and `attack_def` is not None and
`attack_def.delivery` is not None. Sets `ctx.amount` to `landed`.

Damage number fed in:

- `ctx.amount` when the hookup set it (monster config, leap-slam falloff, meteor burst). The stat is
  not added again.
- else the def's `damage`, plus `source.stats[attack_def.scales_with]` when the source has that stat.
  A player sword is `15 + stats["attack"]`, the same pair as `get_full_weapon_damage` today.
  Penetration and force always come from the def. The stat does not raise penetration.

Layers, only when the target has `body_def` and `defence`:

- `defence.worn` is false: `(natural,)`. No region lookup. Every unarmoured enemy, and the naked barb.
- worn, and `contact` is a pixel: start from `hit_layers`. Points and a real front piece: that piece,
  then `defence.layers_at(slot)` minus that piece's layer, hide kept at the end. Skin pixel: the hide
  only. Capsules / sprite (no `piece`): the spot's layers unchanged.
- worn, no contact (leap slam, meteor): the chest stack, `defence.layers_at(chest)`. A blast has no
  pixel; the chest is the stand-in.

`toward`: `ctx.toward` if the strike set it (an arrow's `movement`), else the source's centre to the
target's centre, else None (torso counts as chest, which `hit_layers` already does).

`AttackDef` stays shared. The stat and the hookup's damage are locals inside `resolve`.

No `body_def` (a trap, a test stub, heat): None, today's amount.

## Receivers

They already subtract `ctx.amount` when it is set, except the player-source shortcut. That shortcut
is what drops armour on a player swing.

| file | change |
|---|---|
| `Interaction.py` `apply` | call `resolve`; set `ctx.amount` when it returns |
| `InteractionContext` | `toward: Optional[Tuple[float, float]] = None` |
| `Level4_tmxdev.py` `_strike_with_attack_sprites` | `toward` = the shot's `movement` when it is moving |
| `Enemy.py`, `combat_unit.py`, `friendly.py` `receive_interaction` | if `ctx.amount` is not None, subtract it (the block they already use for non-player sources). The `get_full_*` branch runs only when `amount` is None |
| `Player.py` `receive_interaction` | amount 0: return without `get_damage`. The `get_full_*` branch stays for a hit `resolve` left empty (no delivery: flame, ice ball, fire spit) |
| `RemotePlayer.py` (server) | same 0-skip. It records the amount `apply` already resolved. It does not resolve again |

`tribe_member`, `flyer`, `Trap`, `NeutralCharacter`, `EnemyPuppet` subtract or ignore damage without
the shortcut. Left as they are.

Impulse contexts are untouched. `force` feeds the bruise, not a second shove. Knockback stays chunk 1.

## What chunk 5 does not do

- Magic, conductivity, wet, holy, unholy (7, 9). A def with no delivery keeps today's flat amount,
  including `fire_spit` at 15 and the player's flame and ice ball.
- Venom clocks (8). `reached_flesh` is on the result and not stored.
- Durability (10).
- Stuck arrows (11). `HitSpot.point` is already there.
- Item-card verdicts (12). They will call this same `physical`.
- Co-op gear. The server's remote player wears nothing, so a hit resolved on the server uses the
  naked stack. Plate in co-op waits until the server knows the worn set (master doc, co-op drift).
- `MESH_HERO_HIT_BODY`. Both values stay.

## Tests

`tests/damage/test_rules_physical.py` (no display): the table above, row for row; a third layer
(absorb 0.5) under plate cuts the demon claw below plate alone and does not cushion a dart that
stopped on the plate; a skin-pixel layer tuple is the hide only; `BRUISE_SCALE` is the only knob.

`tests/damage/test_hit_resolve.py`: a stub target with a defence profile.

- no def, or no delivery: `ctx.amount` unchanged
- worn false: one natural layer, `hit_layers` not called
- `ctx.amount` set: that number is the damage, the stat is not added
- `ctx.amount` None, source stats attack 10, sword: damage 25 into `physical`
- points-style spot (a piece): plate then the region's other piece then hide
- spot with `piece` None: the spot's own tuple (capsules / sprite)
- no contact, worn: the chest stack

One strike through `InteractionResolver` with a stub receiver: after `apply`, `ctx.amount` is the
landed int, and a player-source shortcut receiver subtracts that int rather than
`get_full_weapon_damage`.

Regression: the targeted set in the master doc's Method. Same 11 known failures, nothing new.
Perf: one line in `Code/NOTES_performance.md`. A plain `(natural,)` resolve and a three-layer
resolve, microseconds, beside the hit. Not the 200-enemy scene (nobody in it wears plate).

## Check in play

Extend `test_suite.py` with `plate_stops` (pass/fail, not a probe): the plated barb, arrows
from `arrows_where_drawn`'s ring. A hit `kind_of` calls plate deals 0 health and does not clear
`vulnerable`. A hit it calls skin deals damage. Then watch it: grey dots, no health loss; red dots
on the bare head, health drops. Demon claw on the plated barb still takes a large bite (about 37,
naked about 44).

## Commits

1. This plan. Master doc: chunk 5 points here; the points decision; log.
2. `damage_rules.py`, `test_rules_physical.py`.
3. `hit_resolve.py`, `apply`, `toward`, the receiver shortcut, `test_hit_resolve.py`.
4. `plate_stops`. Perf line. Master doc: chunk 5 done, log.

## Open

- `BRUISE_SCALE` 0.05. A sword on plate rounding to 1 is the edge; raise or lower it after the
  play check.
- Demon hide stopping arrows and the player's sword is new. The numbers are the roster's.
- No helmet item, so the head stays a real wound in full plate.
- No gambeson item yet. The under-layer rule is tested with a made-up layer.
