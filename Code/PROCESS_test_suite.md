# Test suite

What the user means by "the test suite". The default in-game test. Empty black floor, magenta walls, benchmark arena, mesh hero. Not `rts_validation.py` (real level, tmx map, RTS and terrain scenes only). Formerly `combat_validation.py`.

## Method

From `Code`:

```
python test_suite.py
python test_suite.py --scenario arrows_stop
python test_suite.py --list
python test_suite.py --headless
```

Visible hold after a scene is decided: 4s. Headless hold: 0. Results: `logs/test_suite_latest.json`. Exit 0 when every decided scene passed.

Scenes live in `test_suite_driver.py`. A full run is `SCENARIOS`: knockback_mass, arrows_stop, plate_shove, arrows_where_drawn, points_vs_capsules. A scene a full run must not include goes in `EXTRA_SCENARIOS` and is named with `--scenario`.

A new scene is a `Scene` subclass. Fields: `NAME`, `WATCH`, `SECONDS`, `FAST_SECONDS`. Optional: `GRASS = False` clears tiles and leaves benchmark grass off; `HOUR = 14` pins the clock (noon, light-map is a no-op). `None` leaves that condition alone. The driver calls `apply_scene_conditions` once before `setup`. `setup` builds the thing under test. It does not touch the clock, the grass, or the camera draw.

Layout: `levels/benchmark`. `layout_general_config.txt` is `False` (not a daytime map). A scene `HOUR` turns the daytime path on for that scene and restores it after.

## Known errors

- Closing the window before the scene writes results: `Main2 exited with code N and wrote no results`. The scene has to finish, or be `--headless`.

## Log

- 2026-11-19: this file. The default in-game suite.
- 2026-11-22: renamed combat_validation -> test_suite (files, `PRCH_TEST_SUITE_*` env vars, `logs/test_suite_latest.json`). Branch refactor/test-suite-name.

## Tried and dropped
