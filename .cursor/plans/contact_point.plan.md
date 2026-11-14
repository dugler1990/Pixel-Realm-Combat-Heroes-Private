# Plan: contact point (damage chunk 3)

Written 2026-11-14. Chunk 3 of `docs/damage/NOTES_damage_and_armour.md`. Branch
`refactor/contact-point`, worktree `..\Pixel-Realm-contact`, started from `refactor/attack-defs`
(chunks 1 and 2, not merged yet).

## Goal

Every hit that lands by touching pixels carries **where** it landed: one world pixel, `contact`, on
its `InteractionContext`. Projectiles carry the pixel where they **entered** the body, not just any
pixel of the overlap. A debug flag draws a dot at each contact. **Nothing plays differently**:
chunk 4 (layers) and 11 (stuck arrows) read the point.

## What is there today (read 2026-11-14)

- `hit_core.touching(a, b)` (`hit_core.py:126`): rects, then `a.mask.overlap(b.mask, offset)`. The
  overlap returns the first shared pixel pygame's scan finds (left-most bit-column band first; not
  where the attack arrived) and `touching` drops it (`is not None`).
- `hit_core.find_hits(shape, candidates, exclude, body)` returns the touched bodies only.
- Hit sites that touch pixels (these get a contact):
  - `Level4._strike_with_attack_sprites` (`Level4_tmxdev.py:1554`): weapon swings, spells,
    projectiles (`ParticleEffect`, moving by `movement` each frame, 12 px for enemy shots).
  - `CombatStrategy.land_melee_swing` (`CombatStrategy.py:107`): enemy swing frame vs bodies.
  - `DashAbility._apply_damage_on_hit` (`abilities/dash.py:136`): the dasher's body vs bodies.
- Ground blasts test footprints (`body=foot_shape`): leap slam (`leap_slam.py:322`), meteor
  (`meteor_strike.py:597`), ice clone (`IceClone.py:28, 37`). **No contact**: a blast has no point.
- All of them reach targets through `InteractionResolver.strike(targets, hits, rehit_ms, **fields)`
  or `.apply(ctx)`.
- Server relay (`Level4.apply_enemy_hit`, client-computed amount): no contact; unchanged.
- Debug draw: `YsortCameraGroup.custom_draw` ends with runtime debug blocks
  (`runtime_debug_effect_rects`, `runtime_debug_faction_outlines`, `YsortCameraGroup.py:551-583`).

## Design

### `hit_core` (pure, no game imports)

- `touch_point(a, b)` → world `(x, y)` of the first shared pixel, or `None`. `touching(a, b)` becomes
  `touch_point(a, b) is not None` (same cost: the overlap call was already made).
- **Rect bodies** (`rect_shape`, no mask): the first shared pixel of two solid shapes is the top-left
  corner of their overlap, which says nothing. `Shape` gets a `solid` slot (True from `rect_shape`);
  when **both** shapes are solid, the point is the centre of the rect overlap (the master doc's rule).
- `find_contacts(shape, candidates, exclude=(), body=shape_of)` → `[(sprite, point, body_shape), ...]`,
  same filter and order as `find_hits` (body_shape so `entry_point` doesn't build the target's shape
  twice; mesh bosses pose a mask for it). `find_hits` stays (blasts, freeze) and is unchanged.
- `entry_point(point, step, body_shape, max_steps)` → the last body pixel walking back from `point`
  along `-step` (the projectile's travel this frame). `step` is a unit vector; at most `max_steps`
  `get_at` reads (`max_steps` = this frame's travel + the shot's own length, capped at 64). Point
  outside the body mask (shouldn't happen) → returned as is.

Why walking back from the overlap pixel works: that pixel is in the body; the shot came along
`step`, so the line back through it leaves the body where the shot crossed the outline. The point is
on the shot's line through the overlap, within a pixel of where it entered. Cost: one tuple per hit,
plus ≤ 64 mask reads per **projectile hit** (not per frame, not per candidate).

Built: a walk measured ~20 µs, and pass-through shots overlap a body for several frames, so the walk
is lazy: `hit_core.EntryPoints(found, step, reach)` has `.get(id)`, and `strike` asks only after its
repeat and team checks. `step` needn't be a unit vector (`entry_point` normalises it).

### Context and resolver

- `InteractionContext.contact: Optional[Tuple[int, int]] = None` (world pixels).
- `InteractionResolver.strike(..., contacts=None, **fields)`: `contacts` maps `id(target)` → point;
  each context gets its target's point. `None` keeps today's calls working.

### Hit sites

| site | change |
|---|---|
| `Level4._strike_with_attack_sprites` | `find_contacts`; a sprite moving this frame (`is_moving` and a `movement`) gets `entry_point` with `step = movement`; pass `contacts` |
| `CombatStrategy.land_melee_swing` | `find_contacts`; pass `contacts` (swing: the overlap pixel) |
| `abilities/dash.py` `_apply_damage_on_hit` | `find_contacts`; pass `contacts` |
| blasts (leap slam, meteor, ice clone) | unchanged: `contact` stays `None` |

Melee and dash keep the first overlap pixel pygame finds (some pixel of the overlap, biased left).
Good enough to say which region was hit; refine only if chunk 4 shows a problem.

### Debug draw

- `Settings.DEBUG_DRAW_CONTACTS = False`.
- New `contact_debug.py` (no pygame drawing in `hit_core`): `record(point, now_ms)` into a
  `deque(maxlen=64)`, `recent(now_ms, keep_ms=600)`. `InteractionResolver.apply` records
  `ctx.contact` when the flag is on and the hit landed (one `if` per landed hit when off).
- `YsortCameraGroup.custom_draw`: when `runtime_debug_contacts`, a 3 px red dot per recent contact
  (`backend.draw_circle`, batches like the other debug shapes).

## Tests

New `tests/damage/test_contact.py`:
- `touch_point`: two masks with a known overlap → the expected world pixel; no overlap → `None`;
  `touching` agrees with it on the same pairs.
- Rect bodies: two solid shapes → centre of their overlap; solid vs masked → a pixel of the mask.
- `find_contacts`: same bodies and order as `find_hits` on the existing `test_hit_core` scene; each
  point lies in both shapes.
- `entry_point`: a 40×40 body; a shot moving right 12 px/frame whose overlap pixel is 9 px inside →
  entry on the body's left column; moving down → top row; diagonal → on the outline, within 1 px of
  the line; body with a hole (a ring) → the outer edge, not the hole; `max_steps` respected.
- `strike` with `contacts` → each context's `contact` is its target's point; without → `None`.
- `_strike_with_attack_sprites` (stub level, as in `test_attack_def_plumbing.py`): an arrow moving
  right into a body → contact on the body's left edge; a weapon (not moving) → the overlap pixel.
- `land_melee_swing`, dash: contact reaches the strike.
- Blasts: leap slam and meteor contexts have `contact is None`.
- Debug: flag off → nothing recorded; on → recorded, and dropped after `keep_ms`.

Regression: the chunk 1/2 targeted set + `tests/damage` (11 known failures, nothing new).

Perf (`Code/NOTES_performance.md`, the hit path): micro-benchmark of `find_hits` vs `find_contacts`
on 200 candidates, 20 touching, and `entry_point` on 1000 projectile hits; numbers in the log. The
200-enemy benchmark moves ~100 ms between runs of the same code, so it can't resolve this.

## Commits

1. This plan.
2. `hit_core`: `touch_point`, `solid`, `find_contacts`, `entry_point`; tests.
3. `contact` on the context, `strike(contacts=)`, the three hit sites; tests.
4. Debug dots (`contact_debug.py`, Settings flag, camera); tests.
5. Perf line; master doc: chunk 3 done, log.

## Check in play (Douglas)

`DEBUG_DRAW_CONTACTS = True`: arrows into the barb leave a dot on the side they came from; a sword
swing leaves one where the blade met the body; meteors leave none.

## Open

- Melee contact is the first overlap pixel pygame finds, not the blade's leading edge. Chunk 4 decides if
  that's precise enough for regions.
- Mesh bodies: the contact is a screen pixel on the posed-capsule mask; turning it into bone + (u,
  angle) is chunk 4.
- Server-owned enemies hitting players: the server computes the contact; the relay to clients
  carries no contact yet (needed only when the client draws stuck arrows, chunk 11).

## Log

- 2026-11-14: built in 4 commits after the plan. Targeted set: 11 failed (the same names) / 367
  passed (35 new). Micro-benchmark: `find_hits` 85-99 µs, `find_contacts` 88-106 µs (200
  candidates, 20 touching); `entry_point` ~20 µs a walk. Debug dots and play not checked.
