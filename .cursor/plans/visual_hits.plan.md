# Plan: visual hits (damage chunk 4b)

Written 2026-11-14. Branch `refactor/visual-hits`, worktree `..\Pixel-Realm-visual-hits`, from
`refactor/defence-layers` (chunks 1-4, not merged).

## Requirement (Douglas, master doc Goal)

What you see is what you hit: an arrow that visibly hits armour pings off; one that visibly hits skin
can stick in him, where it hit. Chunk 4 fails it in two ways (master doc, Tried and dropped): the mesh
hero is hit on his 2D sprite, and armour covers whole regions.

**Done means**: arrows from many directions at the plated barb, in the game's own hit code, each land
on plate or skin as the armour is drawn there; and the place each one hit is a bone + (u along it,
angle around it) a stuck arrow can sit on (chunk 11).

## What is there today (read and measured 2026-11-14)

- Hero: hit on his sprite mask (`hit_core.shape_of`: no `hit_shape`, so `mask` at `rect`). The mesh
  (`player_mesh.PlayerMesh`) is draw-only, sized to the sprite figure, drawn at
  `Support.mesh_feet_world`.
- Demon: hit on its posed capsules: `CombatUnit.hit_shape` → `MeshBoss.body_mask` →
  `mesh_boss.build_body_mask` (rasterized capsules, LRU of 128 masks), and its `rect` is the capsule
  box (`plant_sprite_on_hitbox`), because `find_hits` drops candidates by `rect` first.
- Barb capsule outline, 732 poses (every 5th frame × 12 facings), figure 56 px: build 0.42 ms median,
  27 ms worst (first builds); from the cache 5 µs. The outline's box sticks out of the sprite's 64×63
  rect by up to 2 px left / right, 11 top, 21 bottom (box with padding, not pixels: to check).
- Armour pieces (`Graphics/Meshes/barb_fullplate/<piece>`, `barb_loincloth`) are skinned packs on the
  body's skeleton, in the body's model space (`PlayerMesh.draw` poses them with the body's frame).
- Co-op: the **server** decides enemy hits on players. Its stand-in (`RemotePlayer`, server mode) is
  hit on **one idle sprite frame**, never animated. The client only gets `MSG_HIT_PLAYER` (amount).
  So in co-op, hits on the hero already differ from what anyone sees.

## Design

### (a) The mesh hero is hit on his capsules

- `BasePlayer.hit_shape()`: with a `mesh_skin`, the capsule outline of his current frame, yaw and size
  (`MeshBoss.body_mask` at `PlayerMesh.yaw_deg()`, `height_px`), placed at `mesh_feet_world(self)`:
  the same pose and place the camera draws. Without one: None (sprite heroes as today).
- Hit box: `find_hits` drops a candidate whose `rect` misses the attack. First check the outline's
  real pixels against the sprite rect over every pose; if they stick out, the hero gets the demon's
  rule (his hit rect follows the capsule box). Pick after measuring; no guess.
- Contacts, the projectile entry walk (chunk 3) and `body_regions.mesh_slot` then run on what is drawn.
- Speed-up of the region lookup, held to: same answers as now on thousands of points; ≤ 10 µs per
  hit measured; memory only for poses hit (capped). If it misses, stop and report.
- Cost to watch: an outline is built per hero frame while an attack is near him (~0.4 ms each, cached
  5 µs). Measured in the fight scene below.

### (b) Armour where each piece is drawn

- **Bake** (new `tools/boss_sprite_pipeline/bake_coverage.py`, run per outfit like
  `bake_body_capsules.py`): for each piece pack, every vertex at rest goes to its nearest body capsule
  → (bone, u 0..1 along it, angle around it) → that cell is set in a grid per bone (16 u × 16 angle),
  grown by one cell. Writes `coverage.json` next to the piece's `skin.npz` (with its sha1, like
  `body.json`). A cell no vertex reaches is skin: gaps stay gaps.
- **Hit**: the front-most capsule at the contact (already found) gives the bone; the 3D point on its
  front surface, taken back to rest through the bone's skin matrix, gives (u, angle). Layers at the hit
  = worn pieces whose cell is set there (harder outside), then the hide.
- The region profile (chunk 4) stays for weight, the item card and sprite heroes.
- A piece with no `coverage.json`: falls back to its whole regions, and the game logs it once.

### (c) Co-op (decision 1)

- The client already reports position and health each tick. Add its pose: clip frame and facing (two
  numbers). The server's stand-in poses the same capsules and hits them, so a hit on the server lands
  where that client draws its hero. Without it, co-op stays on the idle sprite frame.

## Checks

- **Fight scene test**: a headless level with the plated barb (mesh) and archers around him at 16
  angles; real `fire_projectile`, real `_strike_with_attack_sprites`. For each hit: did it land on his
  capsules, which bone + (u, angle), plate or skin. Expected from the bake: plate everywhere except the
  bare head (no helmet item) and the baked gaps.
- **Picture for Douglas**: the barb's capsules at 4 facings, each pixel plate (grey) or skin (tan)
  from the bake, next to the armour's own preview render, to compare by eye.
- **Play**: `DEBUG_DRAW_CONTACTS` dots coloured grey (plate) / red (skin).
- Same-answer check and timing for the region speed-up; outline build cost in the fight scene.
- Regression: the targeted set.

## Commits

1. This plan.
2. (a) hero `hit_shape`, hit box rule, tests.
3. Region lookup speed-up, same-answer check, timing.
4. (b) `bake_coverage.py`, baked files for `barb_fullplate` and `barb_loincloth`, lookup at the hit,
   tests, picture.
5. Fight scene test.
6. (c) co-op pose, if decided now.
7. Delete what 4b leaves unused; perf line; docs; log.

## Decisions (Douglas)

1. Co-op now (c) or later? Without it, co-op hits on the hero stay on the idle sprite frame.
2. The hero's hit shape changes from the sprite to his capsules: he is hit where he is drawn, a few
   px fatter or thinner in places. OK?

## Open

- Capsules are fitted to the body; an arrow at the very edge of a limb can hit or miss by a few px.
  Exact outline (the mesh itself) was the other option; capsules chosen (Douglas, 2026-11-14).
- Sprite heroes (no mesh): height bands and whole regions stay; they are not "what you see".
