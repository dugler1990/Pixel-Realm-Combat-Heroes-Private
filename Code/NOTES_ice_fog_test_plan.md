# Ice fog — basic test-suite plan (same map only)

Status: **implemented (suite)** on branch `feature/ice-fog-test-core`. Level4 / Frostreach wiring is next.

Related: package `Code/ice_fog/`, shim `Code/ice_lost_fog.py`, wind lines `Code/dialogue/content/wind_whispers.json`.

---

## Goal

Prove two **same-layout** “stuck in fog” behaviors in the test suite before any Frostreach content work:

1. **Wrap mode** — defined circle; while tangled, rim exits teleport to the opposite side; escape is separate.
2. **Sequence / pads** — wrap containment plus Zelda direction sequence or ordered rim pads to escape.

Forget for this pass: dedicated pocket level, `start_map` neighbor swaps, multiplayer, drifting weather fog, ghosts, full VFX.

---

## Exit criteria checklist

- [x] Core math + wrap mode covered by pytest (`tests/test_ice_fog_geometry.py`, `tests/test_ice_fog_ordeal.py`).
- [x] Sequence mode covered by pytest.
- [x] Pad-order escape covered by pytest.
- [x] Whisper stub / panel variant covered by pytest (`tests/test_ice_fog_whisper.py`).
- [x] Optional debug play scene (`tests/test_ice_fog_play.py`, CLI-gated).
- [x] `ice_fog` package live; Level4 still unwired.

## Manual play

```text
pytest tests/test_ice_fog_play.py
```

## Next (not this pass)

- Hook `FogOrdeal` into Level4 on one ice layout.
- Tiled polygon / effect layer as region source.
- Real wind/VFX, cold, ghosts, larger-than-screen region, minimap lie.
