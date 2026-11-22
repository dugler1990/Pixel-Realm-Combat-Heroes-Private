# Plan: damage 8/9 — holy and unholy, weakness, venom

Written 2026-11-21 (sprint item 2, `docs/PLAN_sprint_next.md`). The design is the damage notes
(`NOTES_damage_and_armour.md`: "Magic" step 4, "Venom", the attack table); this plan is how it is
built on today's code. Douglas checks it before any code.

## Today

| Part | State |
|---|---|
| Attack defs | parse `magic` (`holy`, `unholy` powers) and `venom` (`{"id", "dose"}`). Used by: `demon_claw` unholy 10, `curse_bolt` unholy 9, `sun_bolt` holy 8, `holy_smite` holy 20; venom on `snake_bite`, `thorn`, `scorpion_sting`, `blowgun_dart`. |
| Pricing | `hit_resolve`: holy / unholy add nothing on a body card; alone, `flat` adds the power as plain damage (no armour, no kind). Venom is read and ignored. |
| Kinds | `kinds.json`: living, undead, demon, construct. No multipliers yet. |
| Resist | per body (`bodies.json`), negative allowed (`ice_ghost` fire −30). Fire, cold, lightning use `max(0, power − resist)`, so a negative resist already adds: weakness works there. Holy / unholy read no resist. |
| Conditions | the clock (`ConditionClock`, one heap per level), `buff` and `state` kinds, `refresh` stacking, saves on the level's seeded rng. No venom kind. |

## The model

**Holy and unholy** (step 1)
- Land through armour: no layer reduces them.
- Amount = `max(0, power − resist[category]) × KIND_MULT[category][kind]`. A negative resist is a
  weakness, the same rule as the elements.
- `KIND_MULT` in `kinds.json`. Starting numbers (to tune in the scene):

  | | living | undead | demon | construct |
  |---|---|---|---|---|
  | holy | 0.5 | 2 | 2 | 0 |
  | unholy | 1 | 0 | 0 | 0 |

- Priced with the blow on a body card (added to the physical result), and in `flat` without one.

**Weakness** (step 1)
- Nothing new: a negative number in a body's `resist`. Holy / unholy join fire, cold and lightning
  in reading it. One rule, one place (`damage_rules`).

**Venom** (steps 2-4)
- Starts only on flesh: a pierce that got through every layer (physical resolve already knows), or
  a hit on a body that wears nothing there. Stopped by plate: no venom.
- Venom is damage over time with debuffs, configured per venom. Each venom is one row in
  `venoms.json` (new, next to `conditions.json`); no venom has its own code.
- A venom row:
  - `class`: the family it belongs to (`snake`, `plant`, `insect`, `frog`, ...), for class cures.
  - `phases`: what it does over time, in order, each `{"ms", "damage_per_s", "debuffs"}`.
    `debuffs` are stat changes while that phase runs (`{"speed": -2, "attack": -1}`), through the
    same `bonus` the buffs use. This one shape covers them all:
    - mild and long: `[{"ms": 60000, "damage_per_s": 0.5}]`;
    - a short burst: `[{"ms": 3000, "damage_per_s": 15}]`;
    - creeping, then worse: `[{"ms": 20000, "damage_per_s": 0.5, "debuffs": {"speed": -1}},
      {"ms": 20000, "damage_per_s": 3, "debuffs": {"speed": -3}}]`.
  - `floor`: health it never takes you below (a mild venom weakens, a terrible one has none and kills).
  - `save`: difficulty of the vitality save on the first dose (no constitution stat yet; vitality is
    the body stat, as for the thermostat). Pass: shrugged off.
  - `class_cure`: how much a class cure works on it, 0 to 1 (a terrible venom: 0, only its own cure).
- Dose: each hit adds its `dose`. Strength = dose (capped by `max_dose`); damage and debuffs scale
  with strength. The phases do not restart; a new dose only raises the strength.
- Several venoms at once: each its own clock; their damage and debuffs add.
- Damage goes through the resolver (`source_kind="venom"`), paid on the clock's wakes (one wake per
  phase change, and a tick while it does damage), not per frame. Healing does not stop it.
- Cures: an item effect `{"cure": [{"venom": "snake_venom", "strength": 1}, {"class": "snake",
  "strength": 0.5}]}`. A cure lowers the venom's strength by its share: 1 ends it, 0.5 halves the
  damage and the debuffs. A class cure's share is times the venom's `class_cure`. Several cures stack.
- Immune: `resist: {"venom": 100}` on a body (snake, venom plant) never starts any venom; a resist
  per class (`resist: {"snake": 50}`) cuts that class's strength.

- No fixed types: every venom has its own numbers anywhere along these ranges. The four today
  (snake, plant, scorpion, frog) get different starting rows, tuned in the scene.

## Steps (one commit each, tests of the touched files only)

1. Holy / unholy and weakness: `KIND_MULT` in `kinds.json`, read once; the rule in `damage_rules`;
   `hit_resolve` adds it on a card and in `flat`. Tests: `test_rules_magic.py` (holy on undead
   ×2, on living ×0.5, through plate; negative resist adds).
2. Venom data and start: `venoms.json` and its loader (checked like the other data); physical
   resolve says "through to flesh"; `hit_resolve` starts it (save, dose). Tests: `test_venom.py`
   (dart on plate: no venom; naked: started; immune: not; a bad row is refused).
3. Venom clock: phases, damage on wakes, debuffs through `bonus`, doses raise the strength, the
   floor. Tests: a burst venom and a creeping one give their damage and debuffs at the right times.
4. Cures: the item effect, by venom and by class, partial strengths. One item now: a class antidote
   potion ("antivenom", snake class), drunk from the belt like the other potions
   (`Inventory.use_belt_slot` → the item's `effect`; `cure` is one more key there). Tests: it cuts a
   snake venom by its share, does nothing to a venom with `class_cure` 0; a health potion cures
   nothing.
5. Scenes (`combat_validation_driver.py`, probes for Douglas):
   - `holy`: a priest's `sun_bolt` on a demon and on the barb in plate: the demon loses far more.
   - `venom`: dart tribe and a snake on the barb, plate then naked: no venom, then it runs; the lines
     show each venom's phase, strength, debuffs and health. He wears a belt with the antivenom; the
     belt key drinks it.
6. Notes, guard rule (holy / unholy only through `KIND_MULT`; no venom-specific code), log.

## Decided (Douglas, 2026-11-22)
- Venom is broad: damage over time with debuffs, configured per venom; no fixed types, each venom
  anywhere along the ranges. Cures by venom and by class, to different degrees.
- One cure item now: a class antidote potion, drunk from the belt.
- Symptoms on screen (blur, stumble) beyond stat debuffs: later.
- `KIND_MULT` starting numbers as above.
- Gas (`venom_cloud`, dose per second in a cloud): later, with the venom plant's special.

## Log
- 2026-11-22: built, steps 1-6 (`feat/venom-holy`): 00ff5d78 holy and weakness, f4657ed3 venom and
  cures, b092e872 scenes, then notes and guard. Found on the way: `resist_of` clamped negatives to
  0, so no weakness worked; now signed, through `past_resist`.

## Tried and dropped
- (none yet)
