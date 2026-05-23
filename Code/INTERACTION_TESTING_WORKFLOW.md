# Interaction Testing Workflow

This workflow keeps interaction correctness and performance checks parallel:

- Correctness: `interaction_validation.py`
- Perf/regression: `run_benchmark_matrix.py` + benchmark CSV

## Quick local correctness

From the `Code` directory:

```bash
python interaction_validation.py
```

JSON output variant:

```bash
python interaction_validation.py --json
```

## Quick perf sanity

From the `Code` directory:

```bash
python run_benchmark_matrix.py 2 1 --counts 100 --backends quadtree --collision-modes legacy
```

This writes/extends `logs/benchmark_metrics.csv` and includes interaction counters:

- `interactions_emitted_total`
- `interactions_resolved_total`
- `interactions_rejected_team`
- `interactions_rejected_target`
- `interactions_damage_applied_total`
- `interactions_effect_state_total`
- `interactions_rejected_missing_target`
- `interactions_rejected_team_policy`
- `interactions_rejected_target_gate`
- `interactions_rejected_no_receive`
- `aggro_checks_total`
- `aggro_allowed_total`

## Full regression

Run validation suite:

```bash
python interaction_validation.py --json > ../logs/interaction_validation_latest.json
```

Run broader benchmark matrix:

```bash
python run_benchmark_matrix.py 3 1.5 --counts 100,150 --backends quadtree,grid --collision-modes legacy,simple_swarm --swarm-neighbors 4
```

Then compare summary rows in `logs/benchmark_metrics.csv` and latest generated `logs/benchmark_comparison_*.md`.

For effect-focused and faction-policy correctness, the validation suite also covers:

- `SlipperyLifecycleRoute` (`begin`/`tick`/`end`)
- `MixedEffectRoute` (heat damage + slippery state in the same run)
- `MultiFactionSpawnerRoute` (different spawned factions, allied deny, hostile allow, aggro split)
- `PrefilterRoute` (combat prefilter candidate skip/allow behavior)
- `OwnerInheritanceRoute` (owner team propagation for emitted interaction source_team)

## RTS gather validation (in-game)

Runs the real game (`Main2.py` → `Level4` → `levels/tmx/map.tmx`) with scripted chief/worker/gather scenarios and an on-screen HUD (benchmark-style).

From the `Code` directory — **visible window** (default; watch workers walk and gather):

```bash
python rts_validation.py
```

Headless CI (~15s, no window, fast teleports):

```bash
python rts_validation.py --headless
```

Do **not** prefix with `SDL_VIDEODRIVER=` — an empty value breaks pygame.

Single scenario:

```bash
python rts_validation.py --scenario eskimo_gather_delivers
```

JSON output:

```bash
python rts_validation.py --json
```

Visible defaults: **8s hold** after each pass; per-scenario caps in the driver (gather max **38s**, quick checks **12–16s**). Visible pace shortens gather-at-node to 6s (still walk + deliver). Tune if needed:

```bash
python rts_validation.py --hold-seconds 10
```

Results are written to `logs/rts_validation_latest.json`. Exit code is 0 on full pass, 1 on any failure.

Requires `chiefs`, `resource_nodes`, and `dropoff_buildings` object layers on the TMX map.

### Eskimo build sites (tile properties)

Ice Cutting Post pads are discovered from **tile-layer** custom properties (not object layers):

- `deep_snow=true` or `rts_terrain=deep_snow` on ground tiles
- Optional `build_faction=eskimo` (defaults to eskimo)

Connected deep-snow tiles flood-fill into one `BuildSite` at layout load. Remove pre-placed `ice_shelf` resource nodes on those tiles in `levels/tmx/map.tmx` so players must build first. Building catalog: `levels/tmx/rts_buildings.json`.
