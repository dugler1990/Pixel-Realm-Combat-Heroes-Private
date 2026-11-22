# Dumb fighters share a target

## As is

Every fighter calls `select_hostile_target` once per world draw, from `enemy_update`. A saved target is supposed to last 60 frames. When it expires, that fighter searches the quadtree inside its notice radius and picks the nearest hostile. It then stores the target and the timestamp `frame_number - (id % 60)`.

In `logs/perf/ice_200_atlas.prof` (1,092 world draws, average 39 fighters):

| Work | Per world draw |
|---|---|
| `enemy_update` | 9.5 ms, 39 calls |
| `select_hostile_target` | 6.3 ms, 39 calls |
| `_pick_best_hostile` (the real search) | 2.9 ms, 3.7 calls |
| The other 35 fighters, rechecking a saved target | 3.3 ms |
| `move` | 8.5 ms, 33 bodies |

Move, bump, attack, and drawing stay per fighter. This plan does not change them.

## Problem

Targeting is 6.3 ms of the 9.5 ms spent deciding for 39 fighters. A swarm near one enemy is 35 separate rechecks plus a few full searches, and almost all of them come back with the same answer.

The timestamp makes it worse. A saved target lasts `60 - (id % 60)` frames, not 60. Fighters with a high remainder search again almost every frame. Across 39 fighters that is about 3 to 4 full searches a draw, which is the 3.7 measured.

At this rate, 200 fighters spend on the order of 30 ms just picking a target. Move is another ~0.27 ms each and is outside this plan.

## Fix

Two kinds of fighter.

- **Smart.** The player, bosses, and scripted units. They keep calling `select_hostile_target` for themselves.
- **Dumb.** Everyone else. Fighters of the same team who stand in the same neighborhood share one target.

Neighborhood is one grid cell. Cell size is a named constant on `CombatUnit`, next to `_AGGRO_CACHE_TTL`. Start at 160 pixels, so a few body-lengths of swarm count as one clump.

Each world draw, before the dumb fighters run:

1. Clear a dict of `(cell, team) -> target`.
2. Walk dumb fighters in the existing sprite order.
3. If that cell and team already has a target, copy it onto this fighter and do not call `select_hostile_target`.
4. If not, this fighter does the normal search and the result is stored for the rest of the cell.

Copying means the same writes the search already does: `_aggro_target_cache`, the cache frame, and the prefer-team. The follower also skips the distance recheck. Next draw, a new fighter in the cell may be the one who searches. That is fine.

A dumb fighter who is retaliating (a prefer-team set) does its own search. It is briefly smart. A boss stays smart.

No change to `move`, collision, animation, attacks, or drawing.

## Expectations

On the profiled scene, targeting should fall from 6.3 ms toward about one search per occupied cell. A swarm of five in one cell costs one search instead of five rechecks. If most of the 39 sit in a handful of cells, expect targeting around 1 to 2 ms, and `enemy_update` to drop by roughly that 4 to 5 ms. Move stays about 8.5 ms. Drawing and projectile tests are untouched.

Gameplay: a dumb clump attacks whoever the first fighter in that cell picked. A fighter at the edge of the cell can be one cell-width late to notice someone the leader has not seen. Smart units are unchanged.

This does not make a 200-fighter battle fit in 33 ms. Decisions get cheaper. Each body still moves.
