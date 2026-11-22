---
name: perf targeting and projectiles
overview: "Four speed-ups. Parry returns at once when the projectile-parry chance is 0. The aggro timer expires on each fighter's own beat, so it lasts the full 60 frames. The target search grows a box until the nearest hostile is certain, instead of reading the whole sight range. Projectile and swing hits match bodies by rect with one C call each (Rect.collidelistall), after a viability check. Measured before and after on the ice-200 benchmark, now with three hostile teams and the grid that play uses, and logged in Code/NOTES_performance.md. Branch perf/targeting in its own worktree."
todos:
  - id: setup
    content: "Worktree per docs/WORKTREES.md (task targeting, branch perf/targeting), venv and levels linked. First commit: this plan and perf_status.md."
    status: pending
  - id: baseline
    content: "Step 0: the benchmark team option (PRCH_BENCHMARK_TEAMS). Baselines tgt-base-qt (quadtree) and tgt-base (grid 450), both with teams. Commit, log."
    status: pending
  - id: parry
    content: "Step 1: CombatStrategy.parry returns first thing when projectile_parry_chance <= 0. Measure, log, commit."
    status: pending
  - id: timer
    content: "Step 2: one line: the aggro cache expires on the fighter's own beat. Run the targeting test, measure, log, commit."
    status: pending
  - id: nearest
    content: "Step 3: _nearest_hostile grows the box from a start radius, checks each candidate once, with a 32 px margin; replaces _pick_best_hostile and the visible_sprites fallback; dead CombatDriver goes. Tests updated. Stop rule: revert if not cheaper per search."
    status: pending
  - id: c-scan-check
    content: "Step 4a: viability check for collidelistall: same bodies in the same order, at least 3x faster at 80 and 300 bodies. Stop and report if either fails."
    status: pending
  - id: c-scan
    content: "Step 4b: _strike_with_attack_sprites gathers body rects once per call and passes find_hits only the collidelistall matches. Run test_hit_core, measure, log, commit."
    status: pending
  - id: notes
    content: "Step 5: NOTES_performance.md rules, dangers, How to measure. perf_status.md (hits-and-atlas to Done)."
    status: pending
isProject: false
---

# Speed: parry, targeting, hit tests

## Why

Two profiles, both in `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\logs\perf\`. Times are with the profiler on.

| ms per frame | `ice_200_atlas.prof`: play, grid, ~39 fighters | `hits.prof`: benchmark, quadtree, ~230 fighters |
|---|---|---|
| Whole frame (`Level4_tmxdev.run`) | | 1,144 |
| Targeting (`select_hostile_target`) | 6.3 | 106 |
| Parry (`CombatStrategy.parry`) | 1.4 | 108 |
| Hit tests (`_strike_with_attack_sprites`) | 3.1 | 75 |
| Every broadphase lookup (`hit`) | | 306 |

**Targeting.** In play, 2.7 ms of it is the grid lookups of the 3.7 full searches a frame, 2.9 ms is `_pick_best_hostile`, and 0.38 ms is rechecking saved targets. The table in `dumb_fighters_share_target.plan.md` labels that 3.3 ms of lookups as rechecks; that is wrong.

- **Too many searches.** The cache stores `frame - (id % 60)` on every write, so a target lasts `60 - (id % 60)` frames, not 60. Fighter #59 searches every frame. Timer searches came to 2.9 a frame; the formula `39 × H(60) / 60` predicts 3.0.
- **Each search reads the whole sight range.** The box is 2000 px wide for sight 1000 and 20000 px for the ice mage (sight 10000). In play that box held about 125 things.
- **The benchmark is the wrong scene for it.** All 200 benchmark enemies spawn on team `enemy` (`Spawner._team_id_for_spawn_config`), so they are allies, and the player is the only hostile. Each search checked faction on about 370 allies (8,474 `can_aggro` a frame over 23 searches). In play the map spawns `enemy_1/2/3`, `ally_4` and the neutral teams, which fight each other. Step 0 gives the benchmark teams.

**Parry.** It asks the broadphase for projectiles every frame for every fighter off cooldown. In the ice mix only `ice_mage` has a projectile-parry chance above 0 (0.5), so for everyone else the result can never be used. At 200 on the quadtree, 101 ms of the 108 is that lookup: 0.47 ms each. On the play grid a lookup that size was about 43 µs, so the gain there is likely much smaller. Step 0 measures it.

**Hit tests.** `_strike_with_attack_sprites` passes the whole `attackable_sprites` group to `find_hits` once per attack sprite. In play that is about 42 sprites × 80 bodies, each a Python `getattr` and `colliderect`: 3.7 million rect tests in the session, about 90% of the 3.1 ms. The pixel tests on the overlapping bodies are about 0.25 ms. The grid would not fix this at today's size, because a lookup costs about the same as the scan.

**The benchmark has been measuring the quadtree.** Play uses `ENTITY_BROADPHASE_BACKEND = "grid"` with 450 px cells (`Settings.py`). Benchmark mode uses `BENCHMARK_BROADPHASE_BACKEND = "quadtree"`, and every logged `perf_ice200.csv` row says `quadtree`. The quadtree lookups alone are 306 ms of the 1,144. Step 0 runs one baseline on each so the gap is on record. From then on everything is measured on the grid.

## Before you start

- Follow `docs/WORKTREES.md` for task `targeting`, from the main folder:
  - Step 1 with branch `perf/targeting`: `git worktree add -b perf/targeting ..\Pixel-Realm-targeting main`.
  - Step 2: the venv junction, and the `levels` hard links (the ice map needs them).
  - Step 3: start the agent in `C:\Users\Douglas\Pixel-Realm-targeting`.
  - Every path and command below is in that folder.
- Copy this plan and `.cursor\plans\perf_status.md` from the main folder into the worktree's `.cursor\plans\`. Both are uncommitted there; `perf_status.md` is `main`'s copy plus the "Next" and "Small tweak" notes. Commit them as the branch's first commit.
- Find functions by name, not line number. Re-read a file right before editing it.
- Before each commit, `git status` in the worktree must show only the step's files.
- One commit per step. Each step adds its row to the log table in `Code/NOTES_performance.md` and commits it with the step's files. Step 5 adds the rules and dangers.
- Do not merge to `main` until Douglas says so (`docs/WORKTREES.md` steps 5–6).

## Do not

1. Do not change `_AGGRO_CACHE_TTL` (60). Changing it is a separate decision.
2. Do not add a `nearest` method to the grid or quadtree classes. Step 3 uses only `hit`, so both backends keep working, and the benchmark matrix compares them.
3. Do not change `find_hits`, `shape_of` or the melee path (`bodies_near`).
4. Do not build target sharing. It is noted in `perf_status.md` for later.
5. Do not change how parry works for a fighter with a chance above 0, nor its box or radius check.

## How each step is measured

Run from `Code\` in one PowerShell call; env vars don't carry between calls. It runs the game twice, about a minute each, with no input needed, then clears the variables. If the game fails to start or shows no enemies, stop and report.

```powershell
$label = "tgt-base"
$backend = "grid"
New-Item -ItemType Directory -Force ..\logs\perf | Out-Null
$env:PRCH_BENCHMARK_ENABLED = "1"
$env:PRCH_BENCHMARK_LAYOUT_DIR = "../levels/tmx"
$env:PRCH_BENCHMARK_ENTITY_COUNT = "200"
$env:PRCH_BENCHMARK_ENEMY_MIX = "ice_ghost:60,raccoon:30,spirit:30,ice_mage:25,demon_dog:20,venom_plant:20,tribey_snake:15"
$env:PRCH_BENCHMARK_TEAMS = "enemy_1,enemy_3,ally_4"
$env:PRCH_BENCHMARK_BROADPHASE_BACKEND = $backend
$env:PRCH_BENCHMARK_GRID_CELL_SIZE = "450"
$env:PRCH_BENCHMARK_WARMUP_SECONDS = "10"
$env:PRCH_BENCHMARK_AUTO_RUN_SECONDS = "30"
$env:PRCH_BENCHMARK_METRICS_CSV_PATH = "../logs/perf_ice200.csv"
$env:PRCH_BENCHMARK_RUN_LABEL = $label
.\sprite_venv\Scripts\python.exe Main2.py
$env:PRCH_BENCHMARK_RUN_LABEL = "$label-prof"
.\sprite_venv\Scripts\python.exe -m cProfile -o "..\logs\perf\$label.prof" Main2.py
Get-ChildItem Env:PRCH_BENCHMARK_* | Remove-Item
```

The three teams are mutually hostile in `Code/config/faction_policy.json`: `enemy_1`↔`enemy_3`, and `ally_4` against both. All of them are `hostile_only`.

Then print the per-frame numbers from the profile:

```powershell
@'
import pstats, sys
st = pstats.Stats(sys.argv[1]).stats
def row(file, name):
    n = ct = 0
    for (f, _, fn), (_, nc, _, c, _) in st.items():
        if fn == name and f.endswith(file):
            n += nc
            ct += c
    return n, ct
frames = row("YsortCameraGroup.py", "custom_draw")[0]
fighters = row("combat_unit.py", "enemy_update")[0] / frames
searches = (row("combat_unit.py", "_pick_best_hostile")[0] + row("combat_unit.py", "_nearest_hostile")[0]) / frames
select_ms = row("combat_unit.py", "select_hostile_target")[1] / frames * 1000
recheck_ms = row("combat_unit.py", "_aggro_cache_valid")[1] / frames * 1000
print(f"fighters {fighters:.0f}, searches {searches:.2f} a frame, {searches / fighters:.4f} per fighter")
print(f"select_hostile_target {select_ms:.2f} ms, rechecks {recheck_ms:.2f} ms, "
      f"{(select_ms - recheck_ms) / max(searches, 1e-9):.3f} ms per search")
for file, name in (("CombatStrategy.py", "parry"), ("Level4_tmxdev.py", "_strike_with_attack_sprites")):
    n, ct = row(file, name)
    print(f"{name}: {n / frames:.2f} calls, {ct / frames * 1000:.2f} ms per frame")
'@ | .\sprite_venv\Scripts\python.exe - "..\logs\perf\$label.prof"
```

Record, for each label:

- From the CSV row labelled `$label` (the run without the profiler): `frames`, `avg_frame_ms`, `p95_frame_ms`, `aggro_checks_total / frames`, `broadphase_queries / frames`.
- The four lines the script prints.

**Read counts per fighter.** With teams, fighters kill each other during a run, so frame times depend on how many are still alive. A step that changes who fights whom can change that too. Counts don't drift with the machine; times do. Each step's run is the next step's "before". The benchmark runs at about 1 frame a second, so a run is about 30 measured frames. Treat the times as rough and the counts as solid.

## Step 0. Teams in the benchmark, and the baselines

`Code/Level4_tmxdev.py`, `_spawn_benchmark_entities`. Right after the `classic_count = ...` line, add:

```python
        # Teams handed out in turn, so neighbours fight as the map's own spawns do in play.
        teams = [t.strip() for t in os.environ.get("PRCH_BENCHMARK_TEAMS", "").split(",") if t.strip()]
```

In the loop, after `cfg = {"type": et, "pos": pos}`:

```python
            if teams:
                cfg["spawn_team_id"] = teams[i % len(teams)]
```

`spawn_enemy` already reads `spawn_team_id` through `_team_id_for_spawn_config`, which rejects a team the faction policy doesn't know. Without the variable, nothing changes.

Run the measurement block twice: `$label = "tgt-base-qt"` with `$backend = "quadtree"`, then `$label = "tgt-base"` with `$backend = "grid"`. In the game window, check that enemies fight each other, not only the player. Log both rows. Commit `Code/Level4_tmxdev.py`.

## Step 1. Parry skips the lookup when it cannot parry

`Code/CombatStrategy.py`, `CombatStrategy.parry`. Make these the first lines of the body:

```python
        if self.parry_effects['projectile_parry_chance'] <= 0:
            return
```

`parry_effects` always has that key (`combat_unit.py` builds it, default 0). This is the only live `parry`. The two-argument ones in `MeleeCombatStrategy.py` and the other strategy files are unused copies; the classes `combat_unit` imports are in `CombatStrategy.py`. Behaviour is unchanged: with a chance of 0, `random.random() < 0.0` never passes. The only difference is fewer `random.random()` calls, so later random numbers come in a different order. No outcome depends on that.

Measure with `$label = "tgt-parry"`. **Expect** `parry` ms to fall to the ice mages that are off cooldown, and `broadphase_queries / frames` to fall by about one per non-parrying fighter, since these never parry and so are never on cooldown. Log and commit `Code/CombatStrategy.py`.

## Step 2. The timer expires on the fighter's own beat

`Code/combat_unit.py`, `select_hostile_target`, where the cache is written. Replace

```python
        self._aggro_cache_frame = frame_number - (self.id % CombatUnit._AGGRO_CACHE_TTL)
```

with

```python
        # Expire on this fighter's own beat, the frames where (frame + id) % TTL == 0:
        # fighters stay spread across frames and never wait longer than TTL.
        self._aggro_cache_frame = frame_number - ((frame_number + self.id) % CombatUnit._AGGRO_CACHE_TTL)
```

`_aggro_cache_valid` does not change. Example: id 7, search at frame 100. `(100 + 7) % 60 = 47`, so the stored frame is 53 and the cache expires at frame 113, where `(113 + 7) % 60 == 0`. The search at 113 stores 113 and lasts the full 60 frames.

The three requirements from `aggro_spatial_query_e9ac96e1.plan.md`, Change 5:
- Searches are spread across frames: ids land on different beats.
- No wait is longer than 60 frames.
- The spread holds after spawn and after event searches (target died, out of sight, got hit): the next timed search returns to the fighter's beat.

**Gameplay change, known and accepted:** a fighter keeps its target for up to 60 frames before switching to a closer enemy. That is 2 s at the 30 fps cap and longer when the game slows. An idle fighter can notice an arriving enemy up to that late. Getting hit, the target dying, or the target leaving sight still forces a new search immediately. One small waste: an event search just before a fighter's beat is followed soon after by its timed search.

Run, from the worktree root:

```powershell
.\Code\sprite_venv\Scripts\python.exe -m pytest tests/rts/test_notice_radius_targeting.py -q
```

Measure with `$label = "tgt-timer"`. **Judge it on searches per fighter.** Timer searches should fall from about `H(60)/60 = 0.078` to `1/60 = 0.017` per fighter per frame, plus event searches. `select_hostile_target` ms falls by less, because every fighter still runs its recheck every frame. Log and commit `Code/combat_unit.py`.

## Step 3. The search grows a box until the nearest is certain

The grid answers only "what is inside this rectangle".

- **How it finds the nearest.** Ask for a box that reaches `r` past this fighter's rect. Anything the grid does not return has its centre outside that box, so it is further than `r` away. A hostile found at distance `≤ r` is therefore the nearest, and the search stops there. Otherwise `r` doubles, up to the sight range.
- **Where it starts.** This only changes the cost, never the answer.
  - If the saved target is still alive, start at its distance: the nearest can be no further, so one box usually settles it.
  - If the last search found nothing, start at the full sight range, the same single box as today.
  - Otherwise (first search, or the cache was cleared by a hit) start at one grid cell.
- **Each candidate is checked once per search.** Validity and faction don't change during a search, and the best distance only shrinks. So a candidate an earlier box rejected or found too far stays rejected.
- **Distance is checked first,** because it is cheap. Faction checks run only on a candidate closer than the best so far.
- **The box gets a 32 px margin, the same as `bodies_near`.** Grid entries can be smaller than the sprite, and distance is measured from the sprite's rect centre. On the server, players store their hitbox (`RemotePlayer.update`). A player's hitbox normally contains its rect centre, so this rarely matters, but it keeps "never changes the answer" true for entries up to 32 px off.

`Code/combat_unit.py`:

1. Next to `_AGGRO_CACHE_TTL`:

```python
    # Grid entries can be smaller than the sprite (server-side players store their hitbox).
    _AGGRO_BOX_MARGIN = 32
```

2. Delete `_pick_best_hostile`. In its place:

```python
    def _nearest_hostile(self, resolver, entity_quad_tree, entity_id_map, notice_radius, only_team, start_radius):
        """The nearest hostile within notice_radius (of only_team, if given), or None.

        Asks the entity grid for a box reaching r past this fighter's rect, from start_radius,
        doubling r up to notice_radius. Anything the grid does not return has its centre more
        than r away, so a hit at distance <= r is the nearest. The start only changes how fast
        the answer comes, never the answer. Each candidate is checked once per search.
        """
        cx, cy = self.rect.center
        r = min(start_radius, notice_radius)
        best, best_d2 = None, notice_radius * notice_radius
        seen = set()
        while True:
            reach = math.ceil(r) + CombatUnit._AGGRO_BOX_MARGIN
            box = HashableRect(self.rect.inflate(reach * 2, reach * 2), self.id)
            for item in entity_quad_tree.hit(box):
                if item._id in seen:
                    continue
                seen.add(item._id)
                candidate = entity_id_map.get(item._id)
                if candidate is None:
                    continue
                ox, oy = candidate.rect.center
                d2 = (ox - cx) ** 2 + (oy - cy) ** 2
                if d2 > best_d2:
                    continue
                if not self._is_valid_aggro_target(candidate):
                    continue
                if only_team is not None and getattr(candidate, "team_id", None) != only_team:
                    continue
                if not resolver.can_aggro(self, candidate):
                    continue
                best, best_d2 = candidate, d2
            if (best is not None and best_d2 <= r * r) or r >= notice_radius:
                return best
            r = min(r * 2, notice_radius)
```

3. In `select_hostile_target`, replace everything from `prefer_team = self._current_prefer_team(now)` down to, but not including, the three cache writes, with:

```python
        prefer_team = self._current_prefer_team(now)
        # A missing notice_radius is infinite: cap it at the map so the box stops growing.
        notice_radius = min(self._notice_radius(), math.hypot(*entity_quad_tree.world_rect.size))
        old = self._aggro_target_cache
        if old is False:
            start = notice_radius  # nothing was in sight last time: one box, as today
        elif old is not None and self._is_valid_aggro_target(old):
            ox, oy = old.rect.center
            start = max(entity_quad_tree.grid_cell_size,
                        math.hypot(ox - self.rect.centerx, oy - self.rect.centery))
        else:
            start = entity_quad_tree.grid_cell_size
        best_target = None
        if prefer_team is not None:
            best_target = self._nearest_hostile(
                resolver, entity_quad_tree, entity_id_map, notice_radius, prefer_team, start
            )
        if best_target is None:
            best_target = self._nearest_hostile(
                resolver, entity_quad_tree, entity_id_map, notice_radius, None, start
            )
```

The `use_spatial` test and the `visible_sprites` fallback go. Pass 1 keeps only the prefer team when one is set, and pass 2 drops that filter if pass 1 found nothing, as today. When retaliation finds nobody, pass 2 runs a second growing search. The nearest valid hostile within sight is chosen. Ties at the same distance may break differently, as today's set order already allows.

`Code/rts/behavior_drivers.py`: delete `CombatDriver` and its `"combat"` entry in `_DRIVERS`. It is the only other caller of `select_hostile_target`, and it passes no grid. No unit uses it: tribe members and workers are `"job"`, the chief is `"roam"`, and `pick_driver` falls back to `"job"`.

`tests/rts/test_notice_radius_targeting.py`:

- Imports: `random`, `from hashRect import HashableRect`, `from benchmark_broadphase import MovingEntityBroadphaseAdapter`.
- In the existing test:
  - Give `near` and `far` an `id` (2 and 3).
  - Build a real grid: `MovingEntityBroadphaseAdapter(pygame.Rect(-3000, -3000, 6000, 6000), backend="grid", grid_cell_size=450)`, then `insert(HashableRect(e.rect, e.id))` for each enemy.
  - Call `CombatUnit.select_hostile_target(unit, entity_id_map={2: near, 3: far}, entity_quad_tree=grid)`.
  - Bind `_nearest_hostile` instead of `_pick_best_hostile`. Drop the `visible_sprites` mock.
  - Set `unit.retaliate_until_ms` to `10**12`, not 5000, so it can't run out while tests run.
- Add `test_nearest_hostile_matches_brute_force`:
  - Same unit setup: retaliating against `enemy_1`, the real `InteractionResolver`, `notice_radius` 2000.
  - 60 layouts from a seeded `random.Random`. Each has 80 enemies at random centres in ±2500, each randomly `enemy_1` or `neutral_passive`, inserted in a real grid as above.
  - Rotate the saved target across layouts: `None`; `False`; a random `enemy_1` (start at its distance); and a random `enemy_1` beyond 2000 px. Set `unit._aggro_cache_frame = 0` and pass `frame_number=1000`, so the timer has expired and a search runs.
  - Expected: the brute-force nearest `enemy_1` within 2000 px, or None. Assert the result is None exactly when the expected answer is, and otherwise that its distance equals the expected distance.
  - This covers the doubling, the three start radii and the once-only check.

Run, from the worktree root:

```powershell
.\Code\sprite_venv\Scripts\python.exe -m pytest tests/rts/test_notice_radius_targeting.py tests/rts/test_combat_resume_default.py -q
```

Measure with `$label = "tgt-nearest"`. **Expect** a lower ms per search (the script's third number) than `tgt-timer`, and fewer `aggro_checks_total / frames`. `broadphase_queries / frames` may rise, because one search can be several boxes; that alone is not a regression.

**Stop rule:** if ms per search is not lower than `tgt-timer`, `git restore` the step's files, do not commit, and report both runs' numbers. Otherwise log and commit `Code/combat_unit.py`, `Code/rts/behavior_drivers.py` and `tests/rts/test_notice_radius_targeting.py`.

## Step 4a. Viability check for the C scan

Two code facts first. Confirm each by reading the code; if either is no longer true, stop and report.

- `interaction_kind` is only ever `"damage"` (`attack_sprite.py`, `Trap.py`), so nothing in a strike moves a body.
- A body killed during a strike stays harmless in a list gathered at the start of the call.
  - `CombatUnit` damage only lowers `health`; it leaves `attackable_sprites` in `check_death`, which runs from `update`.
  - `RtsTribeMember.receive_interaction` calls `check_death()`, and so `kill()`, during the strike. But its `can_receive_interaction` returns `health > 0`, and `InteractionResolver.apply` checks that first. So a later attack sprite in the same call can neither hit it nor be stopped by it.

Then run, from `Code\`:

```powershell
@'
import random, timeit, pygame

class Body:
    def __init__(self, rect):
        self.rect = rect

rng = random.Random(7)
ok = True
for n in (80, 300):
    bodies = [Body(pygame.Rect(rng.randrange(0, 1500), rng.randrange(0, 1500), 64, 64)) for _ in range(n)]
    shots = [pygame.Rect(rng.randrange(0, 1500), rng.randrange(0, 1500), rng.randrange(0, 40), rng.randrange(0, 40))
             for _ in range(42)]
    shots.append(pygame.Rect(bodies[0].rect))  # same rect as a body
    rects = [b.rect for b in bodies]
    for s in shots:
        today = [b for b in bodies if (r := getattr(b, "rect", None)) is not None and s.colliderect(r)]
        in_c = [bodies[i] for i in s.collidelistall(rects)]
        if today != in_c:
            ok = False
            print("MISMATCH", n, s)

    def run_today():
        for s in shots:
            overlaps = s.colliderect
            [b for b in bodies if (r := getattr(b, "rect", None)) is not None and overlaps(r)]

    def run_in_c():
        rs = [b.rect for b in bodies]
        for s in shots:
            [bodies[i] for i in s.collidelistall(rs)]

    t_today = min(timeit.repeat(run_today, number=200, repeat=5)) / 200 * 1000
    t_c = min(timeit.repeat(run_in_c, number=200, repeat=5)) / 200 * 1000
    print(f"{n} bodies, 43 shots: today {t_today:.3f} ms, collidelistall {t_c:.3f} ms, {t_today / t_c:.1f}x")
    ok = ok and t_today / t_c >= 3
print("GO" if ok else "NO-GO")
'@ | .\sprite_venv\Scripts\python.exe -
```

**Go** needs both of these:
- The same bodies in the same order for every shot. This includes zero-size shots: `colliderect` never hits a 0×0 rect, so both lists should be empty for those.
- At least 3× faster at both 80 and 300 bodies.

On NO-GO, stop and report the printed lines, and do not build 4b. Write the two speed lines into the log either way.

## Step 4b. Hit tests match bodies in C

`Code/Level4_tmxdev.py`, `_strike_with_attack_sprites`. This is the function behind both enemy projectiles (`enemy_projectile_logic`) and the player's swings and spells (`player_attack_logic`). Replace the start of the body, down to the `find_hits` call, with:

```python
        if not group:
            return
        # Gathered once per call: nothing in a strike moves a body, and a body killed
        # mid-call is turned away by its own can_receive_interaction.
        bodies = [body for body in self.attackable_sprites if getattr(body, "rect", None) is not None]
        rects = [body.rect for body in bodies]
        # A copy: stop() kills the sprite, which takes it out of the group.
        for attack_sprite in list(group):
            shape = hit_core.shape_of(attack_sprite)
            if shape is None:
                continue
            owner = attack_sprite.owner
            targets = hit_core.find_hits(
                shape,
                [bodies[i] for i in shape.rect.collidelistall(rects)],
                exclude=(owner, attack_sprite) + tuple(also_exclude),
            )
```

Everything after `targets = ...` stays as it is. Add one sentence to the docstring: "Bodies are matched by rect with one `Rect.collidelistall` per sprite over rects gathered once per call; only those reach `find_hits`." `find_hits` still filters its short list by rect, which is cheap and still needed for the melee path.

Run, from the worktree root:

```powershell
.\Code\sprite_venv\Scripts\python.exe -m pytest tests/test_hit_core.py -q
```

Measure with `$label = "tgt-cscan"`. **Expect** `_strike_with_attack_sprites` ms to fall by about the speed-up 4a measured, on the scan part, which is about 90% of it. The pixel tests stay. Then a play check on the ice map, about a minute: player swings and shots, enemy shots, and a projectile an ice mage parried all still hit. Log and commit `Code/Level4_tmxdev.py`.

## Step 5. Notes

`Code/NOTES_performance.md`:

- **Rule 4**, add: "Many shapes against the same bodies: gather the bodies' rects once per pass, then one `Rect.collidelistall` per shape. Python never loops over every body per shape. See `_strike_with_attack_sprites`."
- **New rule:** "A nearest-X search grows its box from the best guess it has (the old target's distance, or one grid cell) and doubles until the best hit lies within the reach. Each candidate is checked once. Never ask for the whole sight range up front unless the last search found nothing. See `CombatUnit._nearest_hostile`."
- **Dangers**, add:
  - "A per-unit offset re-applied on every timer refresh shortens the timer for everyone. The aggro stagger made fighters search 4.7× more often than designed."
  - "Per-frame work for an effect whose chance is 0, such as a parry lookup when nobody can parry."
  - "A benchmark whose fighters are all one team measures the swarm-chases-the-player case, not fights between factions."
- **How to measure**, add:
  - "Set `PRCH_BENCHMARK_TEAMS=enemy_1,enemy_3,ally_4`, `PRCH_BENCHMARK_BROADPHASE_BACKEND=grid` and `PRCH_BENCHMARK_GRID_CELL_SIZE=450`. Rows before 2026-11-07 are one team, on the quadtree, and not comparable."
  - "With teams, read counts per fighter."
- **Log:** check there is a row for each label (`tgt-base-qt`, `tgt-base`, `tgt-parry`, `tgt-timer`, `tgt-nearest`, `tgt-cscan`) with avg ms, p95 ms and the step's own numbers in Notes, plus the step 4a speed lines.

`.cursor/plans/perf_status.md`:
- Move `perf/hits-and-atlas` to Done; it was merged in `e719e2b`.
- Put this plan under "In progress" and tick the steps as they land.
- Add the final parry, targeting and hit-test ms per frame to the profile reference.

Commit `Code/NOTES_performance.md` and `.cursor/plans/perf_status.md`.
