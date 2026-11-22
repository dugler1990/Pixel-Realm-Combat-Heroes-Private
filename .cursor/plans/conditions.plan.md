# Plan: conditions and buffs (damage chunk 6)

Written 2026-11-17. Chunk 6 of `docs/damage/NOTES_damage_and_armour.md`. Written on
`refactor/physical-resolve` (chunk 5 is built there and not committed). The build branch is
`refactor/conditions`, cut from that branch after chunk 5 is committed. Worktree
`..\Pixel-Realm-conditions`.

## Goal

A body can carry a condition with a start and an end, and the level notices the end by peeking one
heap. No fire, no venom, no packet. The one behaviour is a buff that adds to a stat until its time
is up, then is gone. Normal play never starts one. The `haste` validation scene does, so the buff
can be walked.

## What is there today (read 2026-11-17)

- Effects belong to areas. `Entity.check_effects` (`Entity.py`) runs for every entity that is in
  an effect cell, every frame, and drops the effect on exit. `should_persist_after_exit` exists
  and every effect returns False (`Effect.py`).
- `HeatEffect` deals `max(0, heat − fire_resistance) × dt` every frame while you stand in the
  area. That stays. Chunk 7 folds it into the fire rule.
- Timers that are not conditions: `recent_attacker_until_ms`, hurt i-frames, gold popup, camera
  shake. Left where they are.
- `Level4.run` builds `entity_id_map` every frame, including on the headless server (the build is
  outside the `if not self.is_server` draw). That is where the clock peeks.
- The player moves with `self.stats["speed"]` (`Player.py` `update`). Enemies copy `speed` off
  `monster_data` once at spawn.

## Decisions

1. **The clock only.** Venom rules, heat-on-the-piece, wet, and burning are chunks 7 and 8. They
   will call `start`. This chunk's only caller is the `haste` validation scene.
2. **Areas stay areas.** A fire floor still ticks in `check_effects`. A condition is what remains
   after you leave. Nothing remains yet.
3. **A cure is per condition, death is the whole body.** Each instance has its own generation.
   Curing one bumps that instance, so its heap entry is stale and every other condition on the
   body keeps running. Death bumps `condition_gen` on the body and clears the dict, so every entry
   for that life is stale. A body that is already gone from `entity_id_map` is stale too.
4. **Stats are read, not rewritten.** A buff does not add to `stats["speed"]` and then subtract
   later. `speed_of(entity)` is `stats["speed"] + bonus(entity, "speed")`. The player move calls
   it. With no buffs, `bonus` returns 0.
5. **No packet yet.** `records(entity)` and `apply_records(entity, records, now)` are the shape the
   server will send, `(cond_id, start_ms, end_ms, strength)`. The socket waits until a condition
   actually starts in play (chunk 7 or 8). Both sides run the same clock from those numbers.
6. **Stacking this chunk is refresh.** Starting a condition that is already on the body replaces
   its end and strength and bumps the generation (the old entry is stale). `add` (venom doses) is
   chunk 8. An unknown stack value fails the load.

## Data: `Code/config/damage/conditions.json`

```json
{"schema_version": 1,
 "conditions": {
   "haste": {"kind": "buff", "stat": "speed", "amount": 4, "duration_ms": 8000, "stack": "refresh"}
 }}
```

`haste` is the test buff. The validation scene is the only thing that grants it. No item row and no
use path: a potion would be a new kind of item for a buff nothing else grants. Rows for burning,
hot shell, wet, frozen and the venoms are added by the chunks that know their rules, not here.

Fields: `kind` (`buff` only, this chunk), `stat`, `amount` (the strength when the caller does not
pass one), `duration_ms`, `stack`. Unknown field, unknown kind, unknown stat name, or a buff with
no stat: `DamageDataError` naming the row. Loaded once in `conditions.py`. Ids are `0 .. n-1`.

## `Code/conditions.py` (no pygame)

`ConditionDef` (`__slots__`): `id`, `name`, `kind`, `stat`, `amount`, `duration_ms`, `stack`.

`Instance` (`__slots__`): `cond_id`, `gen`, `start_ms`, `end_ms`, `strength`.

`ConditionClock`:

- `heapq` of `(due_ms, seq, entity_id, body_gen, cond_id, inst_gen)`. `seq` is the tie break, so
  the heap never compares instances.
- `rng = random.Random(seed)`. The level owns the clock, so the server owns the rolls.
- `start(entity, name, now, strength=None, duration_ms=None)`. Uses the def's amount and duration
  when the caller passes none. Refresh: bump `gen`, new end, push one entry. The body grows
  `conditions` (a dict by cond id) and `condition_gen` on first use; `Entity.__init__` sets
  `conditions = {}` and `condition_gen = 0` so a dead path can bump the gen without a guard.
- `tick(now, entity_id_map)`. Empty heap: return. Otherwise pop while the head is due. Skip when
  the entity is missing, `condition_gen` differs, or the instance is missing or has another gen.
  A matching pop deletes the instance. That is the end of a buff.
- `cure(entity, name)` pops that instance (its gen dies with it).
- `on_death(entity)` bumps `condition_gen` and clears `conditions`.
- `bonus(entity, stat)` sums `strength` of live buffs on that stat. No conditions: 0, no allocation.
- `speed_of(entity)` is `stats["speed"] + bonus(entity, "speed")`.
- `save_succeeds(rng, stat, difficulty)` is `rng.randrange(1, 21) + stat >= difficulty`. Nothing
  calls it in play. Chunk 8 will, with `clock.rng`.
- `records(entity)` / `apply_records(entity, records, now)`. Apply clears and restarts from the
  records, scheduling each end. Same numbers, same bonus.

## Where it hooks

| file | change |
|---|---|
| `Entity.__init__` | `conditions = {}`, `condition_gen = 0` |
| `Level4.run` | one `ConditionClock` on the level, `tick(now, entity_id_map)` immediately after the map is built. Server included. A render client (`mp_client` set) does not tick; it will apply records when a chunk sends them |
| `Player.update` | `self.move(speed_of(self), ...)` |
| `combat_unit.check_death`, `Player.player_death` | `clock.on_death(self)` before the sprite is removed. A death path that skips this still fails safe: the id leaves the map and the entry is skipped |

`check_effects`, `HeatEffect`, enemy `speed`, and the retaliation timers are not touched.

## Tests (`tests/damage/test_conditions.py`, no display)

- The file loads; an unknown field and an unknown kind name the row and fail.
- Heap: three ends at t=500, 100, 500. At t=100 only the middle pops. At t=499 nothing more. At
  t=500 both remaining pop, in `seq` order.
- Cure, then advance past the old end: the buff is already gone, and a second condition on the
  same body is still there.
- Death bumps the gen and clears. Advancing the clock does not bring the buff back. An entry whose
  entity is absent from the map is skipped.
- Two clocks with seed 7: eight `save_succeeds` calls match, and they differ from seed 8.
- `haste` on a stub: `speed_of` is base + 4. After the end, it is the base. Starting it again
  while it runs refreshes the end (the first end does not remove the new one).
- `records` / `apply_records` on a second stub: same bonus, same end.

Regression: the targeted set in the master doc. Same 11 known failures. Perf: empty `tick` and a
`bonus` on an empty body, in `Code/NOTES_performance.md`. Both are a peek and a dict check. Not the
200-enemy scene.

## Check in play

Scene `haste` on the test suite driver (no enemies). `setup` reads `stats["speed"]` and
calls `clock.start(hero, "haste", now)`. The hero still walks from the keys. Overlay: the speed
(`speed_of`) and the seconds left. `SECONDS` 10, `FAST_SECONDS` 9, so the end (8 s) happens while
it is still running, then the hold shows the slow walk.

`WATCH`: hold a direction. He is faster until the line says the buff ended, then he is back to
normal.

`decide`: during the run, `speed_of` was base + 4 at least once; at the end the haste instance is
gone and `speed_of` is the base. Headless passes on those numbers with the hero standing still.
The window is for the eyes.

`test_suite.py --scenario haste --hold-seconds 6` from `Pixel-Realm-conditions\Code`.

## Commits

1. This plan. Master doc: chunk 6 points here; log.
2. `conditions.json`, `conditions.py`, `test_conditions.py`.
3. Entity fields, the level peek, `speed_of` in the player move, `on_death`, the `haste` scene.
   Perf line. Master doc: chunk 6 done, log.

## Open

- `haste` amount 4 and 8 seconds are the test numbers, not a spell. Only the `haste` scene grants it.
- A buff on an enemy does nothing visible until that enemy's speed is read through `speed_of`.
  Not this chunk.
- The d20 save is the first formula. Chunk 8 can change it when a venom uses it; the replay test
  moves with the formula.
