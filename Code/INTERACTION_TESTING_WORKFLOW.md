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
