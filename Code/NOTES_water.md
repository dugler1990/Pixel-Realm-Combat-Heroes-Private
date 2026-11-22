# Water look

Still hole on the test-suite arena floor. Swimming stays parked.

## Method

Suite: `Code/PROCESS_test_suite.md`. Test suite is the default in-game test.

From `Code` in `Pixel-Realm-water-combat`:

```
.\sprite_venv\Scripts\python.exe test_suite.py --scenario water_hole --hold-seconds 8
```

Black floor, magenta walls. 1 flat cut, 2 beach (wade), 3 cliff (jump), 4 sloped isometric box, 5 the same box with vertical walls. Close the window to finish.
A full `test_suite.py` run does not include this scene.

A scene's conditions are fields on the scene class: `GRASS = False` clears the tiles, `HOUR = 14` pins the clock. The driver applies them once in `apply_scene_conditions` before `setup`. `setup` builds the thing under test. It does not touch the clock, the grass, or the camera. `None` leaves that condition alone. A scene a full combat run must not include goes in `EXTRA_SCENARIOS`.

Headless geometry:

```
.\sprite_venv\Scripts\python.exe -m pytest ..\tests\test_water_hole.py -q
```

## Known errors

## Log

- 2026-11-19: moved off rts_validation onto test_suite, scene `water_hole`. Branch feat/water-combat.
- 2026-11-19: pit kept as the beach. Cliff added on key 3. First cliff was a smaller pool in the same hole and read as the beach. Replaced with a face on the hero side and water at its foot. Motion still waiting.
- 2026-11-19: key 3 left as the face. Key 4 first drawn as a flat split rectangle. Replaced with an isometric rectangular pit: diamond mouth, four inner walls, water on the floor.
- 2026-11-19: key 4 left as the sloped box. Key 5 is that box with 90° walls: each floor corner is directly under its rim corner.
- 2026-11-19: water_hole `GRASS = False` and `HOUR = 14`. Driver applies them once. Clock pin lives on Weather. Camera no longer checks for the hole.

## Tried and dropped

- Standalone pygame window.
- `rts_validation.py --scenario water_hole` on the tmx map. Wrong suite. Blue disc, ground not opened.
