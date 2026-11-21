# Plan: visual hits (damage chunk 4b)

Written 2026-11-14, rewritten as built 2026-11-15. Branch `refactor/visual-hits`, worktree
`..\Pixel-Realm-visual-hits`, from `refactor/defence-layers` (chunks 1-4, not merged).

## Requirement (Douglas, master doc Goal)

What you see is what you hit: an arrow that visibly hits armour pings off; one that visibly hits skin
can stick in him, where it hit. Chunk 4 failed it in two ways: the mesh hero was hit on his 2D sprite,
and armour covered whole regions.

**Done means**: arrows from many directions at the plated barb, in the game's own hit code, each land
on plate or skin as the armour is drawn there; and each hit names the mesh point it landed on (where a
stuck arrow sits, chunk 11).

## As built

### The mesh hero is hit on his mesh, as drawn

- `Settings.MESH_HERO_HIT_BODY`: `"points"` (default) or `"capsules"`. Both stay: capsules are the
  demon's hit body and the body-vs-body collision (`body_contact.py`); points are the hero's.
- **Points** (`Code/mesh_points.py`): ~2.5k of the barb's 107k vertices, one per cell of a grid over
  the rest pose. Posed per animation frame on first use (linear blend skinning, as the GPU; float32,
  last 128 frames kept), projected like the camera, each point spread over 2×2 px, nearest per pixel.
  The outline is the hit mask; per pixel it knows the point in front, its bone, and whether it is skin
  or a worn piece.
- **Worn pieces are in the outline** (`WornCloud`): each piece's points at the body's spacing, posed
  about the body's pivot with the body's clip and step (as `PlayerMesh.piece_frames`, which `draw` uses
  too). Body + pieces pose in one pass.
- `BasePlayer.hit_shape()` / `hit_rect` / `hit_outline()`: where the camera draws him
  (`Support.mesh_feet_world`). `hit_rect` holds his outline (a foot stepping toward the camera is 15 px
  below the sprite); `hit_core.reaches_past_rect` lists him, so other candidates pay nothing for it.
  Undrawn mesh (CPU backend) or sprite hero: hit on the sprite as before.
- **What a hit meets**: `body_regions.hit_layers(hero, contact, toward)` → `HitSpot(slot, layers, piece,
  point)`. Points: the point in front at the hit pixel; a worn piece → its item's layer (on equip:
  `defence_profile.piece_layers`) then the hide; skin → the hide. Torso → chest or back by direction.
  Sprite hero or capsules: the region's layers from the profile (chunk 4).
- **Capsules improved too** (`bake_body_capsules.py`): ends pulled in while 90% of a bone's points
  stay inside; barb re-baked (demon not).

### Numbers (barb, 56 px figure)

| | capsules | points |
|---|---|---|
| covers the drawn body (33 poses vs all 107k vertices) | 98% | 98% |
| hit area where nothing is drawn | 35% (worst 52%) | 11% (worst 12%) |
| same body part as the drawn mesh | 77% | 91% |
| new pose outline, body only | 0.36 ms | 0.47 ms |
| first use of an animation frame, body only | — | +0.75 ms |
| full plate (6.9k points): first use of a frame / new facing / cached | — | 3.7 ms / 1.0-1.2 ms / 3-6 µs |
| what the hit meets (`hit_layers`) | 5-60 µs | 6-9 µs |
| memory | 0 | ≤ 128 posed frames per worn set (float32): ~10 MB full plate |

- **Plate or skin as drawn**: 32 poses × 16 arrows through `Level4._strike_with_attack_sprites`,
  against the full body + armour meshes: full plate 487/506 (96%), loincloth 501/512 (98%) within 1 px;
  the misses sit on plate-skin seams (both within 2 px: the points are ~1.6 px apart).
- `find_hits`, 200 candidates: 73 vs 77 µs medians (within noise) with the reaching-body list.
- One-write depth buffer equal to sort + unique on 637k pixels.

## Checks done

- `tests/damage/test_hero_mesh_hits.py` (every test for both bodies), `test_mesh_points.py`,
  `test_armour_hits.py` (plate / skin / loincloth / sprite fallback; arrows from 16 directions at two
  poses: every hit matches the drawn mesh within 2 px, ≥ 85% within 1 px).
- Pictures (scratch, not kept): the wired code at 4 poses; mesh vs tubes vs points with the air in
  magenta; plate (grey) / skin (tan) with 16 arrows per pose, green = matches the drawn mesh.
- Regression: the targeted set + `test_body_capsules`.
- **Not checked in play.**

## Decisions (Douglas)

1. Co-op later: the server keeps hitting the idle sprite frame (master doc Open: co-op drift).
2. Capsules first (2026-11-14), then points tried and chosen (2026-11-15): capsules looked bad (fat,
   35% air); points cost about the same. Keep both alive.

## Open

- First use of an animation frame in full plate costs 3.7 ms while he is attacked (posing 6.9k points);
  each frame once, then kept (128 of 305). Pre-posing on equip or fewer piece points if it shows.
- Only the piece in front counts: a gambeson under plate is not a layer at the hit yet (chunk 5 decides
  how inner layers are found: each piece's own outline at the pixel, or the profile's region).
- `WornCloud.frames_of` repeats `PlayerMesh.piece_frames`'s rule (same clip, same step); one place
  later.
- No helmet item: the head is skin in full plate.
- Sprite heroes: height bands and whole regions; not "what you see" (no mesh).
- Enemies (demon) stay on capsules; move them to points if they need it.

## Tried and dropped

- **Hero hit on capsules as the default**: one round tube per bone is as deep as it is wide; from the
  side he is ~2× too deep, a wedge of air above the head. Kept as the other choice
  (`MESH_HERO_HIT_BODY = "capsules"`), not the default.
- **Armour coverage baked per bone (u, angle)** (this plan's first design (b)): not built; the pieces'
  own points answer plate or skin exactly where they are drawn, with no bake.
- **Faster capsule region lookup** (prototype: same answers on 63k points, 62 µs first hit, 5 µs after):
  not put in; the points answer in 2-9 µs.
- **Capsule ends pulled in by the full radius**: worst bone kept 66% of its points; replaced by pulling
  in only while 90% stay inside.
