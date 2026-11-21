# Combat validation

The default in-game test. Black floor, magenta walls, benchmark arena, mesh hero. Not `rts_validation.py` (that one is the tmx map, for RTS and terrain scenes only).

## Method

From `Code`:

```
python combat_validation.py
python combat_validation.py --scenario arrows_stop
python combat_validation.py --list
python combat_validation.py --headless
```

Visible hold after a scene is decided: 4s. Headless hold: 0. Results: `logs/combat_validation_latest.json`. Exit 0 when every decided scene passed.

Scenes live in `combat_validation_driver.py`. A full run is `SCENARIOS`: knockback_mass, arrows_stop, plate_shove, arrows_where_drawn, points_vs_capsules. A scene a full run must not include goes in `EXTRA_SCENARIOS` and is named with `--scenario`.

A new scene is a `Scene` subclass. Fields: `NAME`, `WATCH`, `SECONDS`, `FAST_SECONDS`. Optional: `GRASS = False` clears tiles and leaves benchmark grass off; `HOUR = 14` pins the clock (noon, light-map is a no-op). `None` leaves that condition alone. The driver calls `apply_scene_conditions` once before `setup`. `setup` builds the thing under test. It does not touch the clock, the grass, or the camera draw.

Layout: `levels/benchmark`. `layout_general_config.txt` is `False` (not a daytime map). A scene `HOUR` turns the daytime path on for that scene and restores it after.

## Known errors

- Closing the window before the scene writes results: `Main2 exited with code N and wrote no results`. The scene has to finish, or be `--headless`.

## Log

- 2026-11-19: this file. Combat validation is the default in-game suite.

## Tried and dropped
