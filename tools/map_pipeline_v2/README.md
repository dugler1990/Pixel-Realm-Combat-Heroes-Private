# map_pipeline_v2

Clean-room rewrite of the irregular world-level map-art pipeline. See
[DESIGN.md](DESIGN.md) for the architecture and rationale. v1 lives at
`tools/painted_map_pipeline/world_levels/` and is untouched.

## Quick start (Phase 0 — no API key needed)

```bash
# from repo root
python -m tools.map_pipeline_v2.cli backends            # list registered backends
python -m tools.map_pipeline_v2.cli demo /tmp/mpv2_demo # run toy world end-to-end
python -m tools.map_pipeline_v2.cli demo /tmp/mpv2_demo --backend overflow_demo
```

The `demo` command builds a small synthetic two-level world and drives it through
the full loop (compose → prompt → generate → conform → qa → decide → accept) using
a key-free backend. With `--backend overflow_demo` the backend deliberately paints
the whole frame, exercising the **crop-not-warp** conform path and the QA gate —
i.e. the exact v1 melt, caught and fixed.

## Status

- [x] **Phase 0** — spine: contracts, registry, copy/dryrun/overflow backends,
      conform (identity/crop), QA gate, state store, CLI demo.
- [ ] **Phase 1** — port real geometry (world/assets/continuity) from v1.
- [ ] **Phase 2** — conform hardening + QA thresholds + land_fit warp strategy.
- [ ] **Phase 3** — real backends (leonardo_image_reference, gpt_image_edit, gemini_edit).
- [ ] **Phase 4** — 04→07 run + HTML compare.
- [ ] **Phase 5** — acceptance/propagation/reset polish.

## Layout

```
map_pipeline_v2/
  DESIGN.md          # architecture + rationale (source of truth)
  models.py          # domain dataclasses, LevelState + transitions
  config.py          # layered config schema + loader/resolver
  backends/
    base.py          # GenerationRequest/Result/Capabilities + GenerationBackend
    __init__.py      # registry + make_backend
    copy.py          # CopyBackend, DryRunBackend, SyntheticOverflowBackend
  service.py         # GenerationService (retry/log/artifact wrapper)
  prompts.py         # versioned prompt templates + render
  conform.py         # conform strategies (identity/crop; warp = Phase 2)
  qa.py              # QA metrics + gate
  store.py           # run.json state + events.jsonl
  pipeline.py        # stage orchestration + toy world (real geometry = Phase 1)
  cli.py             # argparse entrypoint
  config.example.json
```
