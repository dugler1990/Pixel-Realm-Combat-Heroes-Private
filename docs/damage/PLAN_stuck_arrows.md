# Plan: damage 11 — stuck arrows

Written 2026-11-22. The design is in `NOTES_damage_and_armour.md` ("Stuck arrows", chunk 11 in the
order); this plan is how it is built on today's code. Douglas checks it before any code.

## Goal
An arrow that lands on the player stays where it hit, drawn on his mesh, and moves with it (the
animation and facing). Player only for now; certain bosses may get it later. Visual only.

## Today
- A landed hit knows its pixel (`ctx.contact`). On the mesh hero, `body_regions.hit_layers` finds
  the mesh point in front there (`HitSpot.point`, an index into his worn point cloud) and whether
  it is a worn piece or skin. Sprite bodies have only the contact pixel and their rect.
- The arrow sprite is removed when it lands (`ParticleEffect.stop`).
- The point cloud is posed per frame (`PointCloud.posed`, cached) and projected like the camera
  (`mesh_points._build`).

## The model
- **What sticks:** an arrow that landed and went into something: it reached flesh, or it stopped in
  a layer that catches (leather, cloth, wood, hide). An arrow stopped by plate or mail glances off
  and does not stick. A layer property `catches` (true / false) in the item bases and body cards
  says which; plate and mail false, the rest true.
- **Where:**
  - Mesh hero: the point index and the arrow's direction in the body's own frame (its travel turned
    by minus the body's yaw at the hit). Each frame: that point from the posed cloud, projected with
    the current yaw and scale, gives the screen spot and depth; the direction is turned by the
    current yaw.
- **How deep:** the share of the shaft drawn outside the body: less the further it went in
  (through to flesh: half the shaft shows; stuck in an outer layer: most of it).
- **Hidden behind the body:** on the mesh hero an arrow is drawn only when its point is in front at
  its pixel (the outline's labels already say which point is in front); otherwise skipped that
  frame, so arrows in his back vanish when he faces you.
- **How many and how long:** at most `STUCK_MAX` (8) per body, the oldest dropped; each lasts
  `STUCK_MS` (60 s) or until death. Constants in `damage_rules`.
- **Who has them:** the player only (the mesh hero). Monsters none, so a crowd costs nothing.
- **Cost:** one small sprite per stuck arrow per frame, the same atlas texture (batched); the mesh
  hero's posed cloud is already computed for the frame it is drawn.

## Steps (one commit each, tests of the touched files only)
1. `catches` on layers (data and loader); `stuck_arrows.py`: the store per body (add at landing,
   cap, expire, forget on death) and the placement maths (mesh point projected). Tests
   `tests/damage/test_stuck_arrows.py`: stored at the contact; plate does not keep one; the cap
   drops the oldest; the spot follows the yaw.
2. Landing: the resolver keeps an arrow when it landed and something caught it (the arrow's attack
   def, the HitSpot). Hook where the arrow sprite stops.
3. Drawing: in the camera's sprite pass, after the body, its stuck arrows (hidden when behind on
   the mesh hero).
4. Scene `stuck_arrows` (probe for Douglas): archers around the barb, half plate (chest and legs),
   head and arms bare; he walks and turns. Watch: arrows stay in the skin and the leather, none on
   the plate; they move with him; the ones behind vanish.
5. Notes, log, guard (only `stuck_arrows.py` stores them).

## Decided (Douglas, 2026-11-22)
- Plate and mail glance off: no stuck arrow.
- 8 per body, 60 s, to start.
- The player only for now; certain bosses maybe later.
- Later, not now: pulling arrows out, bleeding while they are in, arrows slowing you.

## Log
- 2026-11-22: built, steps 1-5 (`feat/stuck-arrows`). Arrow-like = pierce + `stops` (no new attack
  field). Headless: 12 landed, 8 stuck (cap), 5 drawn in front. Not watched.

## Tried and dropped
- (none yet)
