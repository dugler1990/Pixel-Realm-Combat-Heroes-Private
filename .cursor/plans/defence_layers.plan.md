# Plan: bodies and layers (damage chunk 4)

Written 2026-11-14. Chunk 4 of `docs/damage/NOTES_damage_and_armour.md`. Branch
`refactor/defence-layers`, worktree `..\Pixel-Realm-layers`, from `refactor/contact-point` (chunks
1-3, not merged). Needs `main`'s item card (`fd235ab8`: `item_properties.py`, `item_bases.json`,
`Item.base`): merge `main` into this branch first (Douglas's OK).

## Goal

Every body knows what is between a hit and its flesh, and where. A **body def** (natural hide, kind)
per monster and hero; a **defence profile** (worn pieces + natural layer → layers per region, outer
first, plus worn weight) rebuilt on equip; and **which region** a contact pixel is on the mesh hero.
**No rule reads them yet** (chunk 5 does): nothing plays differently, except worn weight, if Douglas
says so (Decisions).

## What is there today (read 2026-11-14)

- Worn items: `Inventory` body slots (`equipment.BODY`: helmet, armor, shoulder_l/r, arm_l/r,
  legs_l/r, boots_l/r, waist). Every change ends in `Inventory._changed` → `Player.refresh_equipment`
  → `PlayerMesh.set_pieces` (`Inventory.py:229`, `Player.py:340`).
- Item stats (on `main`): `Item.base` → `Graphics/Standard_Items/item_bases.json` via
  `item_properties.base_of(item)`. Plate pieces: stopping_power 40, absorb 0.15, weight 1-12,
  `coverage` = region names (`item_properties.REGIONS`: head, neck, chest, back, upper_arm, forearm,
  hand, waist, thigh, shin, foot). Sides come from the item (`effect.side`, "l" = his left).
- The mesh hero is **draw-only** (`player_mesh.py`): hits land on the sprite mask; the mesh and its
  armour pieces are drawn over it at the feet, sized to the sprite figure. Mesh bosses (demon) hit
  on posed capsules (`combat_unit.hit_shape`).
- Barb pack: 28 body capsules on 28 bones, bones named `bone_0`..`bone_27` (UniRig, no names). From
  the rest geometry (+X = his left): 0 hips; 1-2 spine; 3 neck; 4-5 head; 6 / 13 collarbone; 7 / 14
  upper arm; 8 / 15 forearm; 9-12 / 16-19 hand; 20 / 24 thigh; 21 / 25 shin; 22-23 / 26-27 foot
  (left / right). Probed on a projected frame facing the camera: head on top, his left arm on screen
  right, legs below: as expected.
- Mass is in `monster_data` (chunk 1); `gear_weight` on Entity is 0.
- Sprite enemies wear nothing; their only layer is their hide.

## Design

### Data: `config/damage/bodies.json`, `kinds.json`

- `kinds.json`: `living`, `undead`, `demon`, `construct` (the catapult) (names only; `KIND_MULT` comes in
  chunk 9).
- `bodies.json`: per body def `kind` and `natural` (`stopping_power`, `absorb`, `flammability`,
  `conductivity`: the item property ids). Resistances and starting states come with their chunks
  (7, 8, 9, 6). Mass stays in `monster_data`.
- Rows: the roster's 12 (`barb` ... `ice_mage`) plus, agreed with Douglas from a picture of each:
  `eskimo` (eskimo worker, chief), `tribesman` (jungle worker, chief), `warrior` (00 01 02 04 08 10
  12 13 14 15), `robed` (11 16 17), `beastman` (03), `camel_rider` (05 06 07 09), `siege` (18,
  construct), `scorpion` (19). Masses: camels 500, catapult 800, scorpion 30 (were 70).
- `wire.body_for(label)`: new warriors get a body (and mass) from their label; a body already in the
  entry stays (07 "Desert Chieftain" rides a camel, which the label does not say).
- `monster_data` entries get `"body"`; the hero is `barb` (one hero body for now).

### `damage_data.py`

- `LayerDef` (`__slots__`): `stopping_power`, `absorb`, `flammability`, `conductivity`,
  `insulation`, `sealed`, `weight`, `durability`; from a body's `natural` or an item base (missing
  fields 0 / False).
- `BodyDef` (`__slots__`): `id`, `name`, `kind`, `natural` (LayerDef).
- `load_bodies`, `load_kinds`, `body(name)`, `body_of(entry)` like `attack` / `attack_of`. Unknown
  field, kind or property → `DamageDataError` naming the file and body.
- Region slots: int ids for `head, neck, chest, back, waist` and `upper_arm, forearm, hand, thigh,
  shin, foot` × `l, r` (17). `region_slot(region, side)`.

### `defence_profile.py` (pure, no pygame)

- `DefenceProfile`: `layers` (tuple per region slot of LayerDefs, outer → inner, the natural layer
  last), `weight` (worn), `worn` (False: hide only, the fast path).
- `natural_profile(body_def)`: one shared object per body def (all enemies of a kind share it).
- `build_profile(body_def, worn)`: `worn` = `(base, side)` pairs. A base's `coverage` regions; a
  sided region takes the piece's side, a piece with no side covers both. Two pieces on one region:
  harder outside (`stopping_power` descending; plate over a gambeson). LayerDefs are made once per
  base id.
- `layers_at(profile, slot)`.

### Who holds what

- `Player`: `body_def = body("barb")`; `defence` rebuilt in `refresh_equipment` from the body slots'
  items (`item_properties.base_of`; an item with no base adds nothing). Equip / unequip = rebuild;
  nothing per frame.
- `Enemy`, `CombatUnit`, `friendly`: `defence = natural_profile(body_of(monster_info))` next to
  `mass`.

### Which region (`body_regions.py`)

- `Graphics/Meshes/barb/regions.json`: bone → region (`torso` for 1-2, meaning chest or back;
  sides from the table above). Hand-written from the geometry; a test checks every bone has one and
  its rest position agrees (height band, side by x sign).
- `mesh_slot(skin, feet, contact, toward)`: of the projected capsules under the contact, the one
  whose front is nearest the camera (depth `gy·cos e + gz·sin e`); under none, the nearest edge. At
  the skin's frame and yaw, feet as the camera draws it (`Support.mesh_feet_world`, shared with the
  camera) → bone → region. (Built: the plan's "nearest edge" alone let a side hit land on the arm
  hidden behind him; seen on a region map at 4 facings.) Collarbones 6 / 13 are torso: their capsules
  cover the upper chest. `torso` is
  `chest` when the attack comes at his front (`toward` against his facing), else `back`. `toward`: the
  attack's travel on the ground (chunk 5 passes it: projectile `movement`, else source → target).
- Projection cached on the skin per (frame, yaw): hits in one frame share it.
- Measured before building (nearest edge): 167 µs uncached, 53 µs cached. As built (front-most,
  machine ~40% busy): 329 µs uncached, 61 µs cached. Only for **landed hits on a body with worn
  layers** (the hero), so a few a second.
- Sprite hero (no mesh) wearing items: height bands on his hitbox (the barb's rest heights:
  head > 0.60 ... foot < 0.06), side by x against his centre and facing.
- Enemies: no lookup (one layer everywhere).

## Decisions (Douglas)

1. **Merge `main` into this branch** (item card files). Doc conflicts are small (Method that works,
   Log); I resolve them.
2. **Reversed (2026-11-14).** Was: the hero's hit body stays the sprite mask; the region is read from
   the mesh capsules at the contact. I recommended it as harmless; it is not: the sprite pose is not
   the drawn mesh, so an arrow can visibly hit his arm and miss. Fails Douglas's requirement "what you
   see is what you hit" (master doc Goal). Replaced by `visual_hits.plan.md` (a): hit on his capsules.
3. **Agreed (Douglas): worn weight counts now**: `gear_weight = defence.weight`. The full-plate set
   that exists (10 pieces, no helmet item yet) is 31 → the barb moves 90 / 121 = 74% as far.
4. **Reversed (2026-11-14).** Was: a region is covered or not (the item's `coverage`); per-bone
   (u, angle) coverage baked at export deferred. A visible gap in a piece then counts as plate: fails
   the same requirement. Replaced by `visual_hits.plan.md` (b): coverage baked per piece.
5. **Agreed (Douglas)**: the bodies and masses above.

## After the review (2026-11-14): what stays, what changes

- **Stays**: bodies and kinds, masses, `wire.body_for`; `DefenceProfile` and worn weight → knockback;
  the front-most capsule lookup (`body_regions.mesh_slot`: the right rule once hits land on the
  capsules); `regions.json` (bone → region, still the item card's and the profile's regions);
  `Support.mesh_feet_world`; `mesh_boss.projected_capsules`.
- **Changes in `visual_hits.plan.md`**: what the hero is hit on (capsules); which layers a hit meets
  on a covered region (the piece's baked coverage at the contact's bone + (u, angle), not the whole
  region).
- **Open**: `body_regions.sprite_slot` (height bands) serves sprite heroes only; kept while they
  exist. Anything 4b leaves unused is deleted when 4b lands.

## Tests

- `tests/damage/test_bodies.py` (built there, not in test_damage_data): bodies and kinds load; every
  `monster_data` entry has a body that exists; unknown body / kind / field fails loudly; natural
  numbers match the roster; `wire.body_for` agrees with Settings except 07.
- New `tests/damage/test_defence_profile.py`: full plate as it exists (10 pieces, no helmet item) →
  every slot but head and neck plate then hide, weight 31; plate chest alone → chest and back plate, the rest hide; loincloth →
  waist only;
  `shoulder_l` covers `upper_arm l` not `r`; two pieces on one region → harder outside; weight sums;
  enemies of one body share one profile; equip / unequip through `Inventory` rebuilds the hero's.
- New `tests/damage/test_body_regions.py`: `regions.json` covers every capsule bone and agrees with
  the rest geometry; on a posed frame, a point on the head capsule → head, on his left forearm →
  `forearm l`; torso from the front → chest, from behind → back; sprite bands; cache reused in one
  frame.
- Regression: the targeted set (doc's Method that works), same 11 known failures.
- Perf: `region_at` cached / uncached, `build_profile` (on equip only); line in
  `Code/NOTES_performance.md`.

## Commits

1. This plan; master doc updated (below).
2. Merge `main` (if OK).
3. Data: `bodies.json`, `kinds.json`, `damage_data` LayerDef / BodyDef / region slots, `body` keys;
   tests.
4. `defence_profile.py`, hero and enemies hold one, equip rebuilds; tests. (Weight → knockback here if
   decision 3 says now.)
5. `body_regions.py`, `regions.json`; tests.
6. Perf line; master doc: chunk 4 done, log.

## Master doc changes (with this plan)

- Contact §3: sprite bodies wear nothing today, so no per-slot sprite masks; the mesh hero's region
  comes from his capsules (hits still on the sprite); per-bone (u, angle) coverage deferred.
- Chunk 4 line: what this plan builds; bodies keep mass in `monster_data`.
- Code layout: `body_regions.py`; `defence_profile.py` as above.

## Check in play (Douglas)

The plated barb is shoved less by the demon's claw and meteors (74% in full plate).

## Log

- 2026-11-14: built in commits `96936bb5` (data), `dc7053c6` (profiles), `b0430aef` (regions), after
  the plan and the merge of `main` (`5c972b10`). Targeted set + item card: 11 failed (the same names)
  / 450 passed (new files test_bodies, test_defence_profile, test_body_regions; the set now also
  runs test_item_card). The machine was busy
  (other agents' Blender jobs): the set took 4:37, collection alone up to a minute. Region map
  (`scratchpad/region_map.py`, not kept) checked at 4 facings. Not checked in play.

## Open

- Mid-shin can read as thigh, the neck is rarely hit: the capsules are as fat as the body. Plate covers
  both, so nothing changes today.
- No helmet item: the head and neck are bare in full plate.

- Co-op: the server does not know what a remote hero wears; chunk 5 (server-resolved hits) needs it
  sent on equip.
- More hero bodies (`PlayerSelectionDict.json` `"body"` per hero) when a second hero has a mesh.
- A second mesh pack needs its own `regions.json`; a bake tool when there are several.
