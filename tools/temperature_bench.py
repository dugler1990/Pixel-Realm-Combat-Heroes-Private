"""Temperature cost in the real Level4, headless: N monsters in an ice field, each with a store,
all past the cold line (wounding every TICK_MS). Prints frame times with and without temperature
and the time spent in settles. Numbers are noisy: run it 3 times.

From a worktree root:
  Code/sprite_venv/Scripts/python.exe tools/temperature_bench.py on|off [frames=600] [bodies=100] [air=-60]
(one level per process: run "off" then "on")
"""
import os
import random
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = Path.cwd()
for p in (ROOT / "Code", ROOT / "Server"):
    sys.path.insert(0, str(p))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((1280, 720))
from headless_level import build_headless_level  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "on"
FRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 600
BODIES = int(sys.argv[3]) if len(sys.argv) > 3 else 100
AIR = float(sys.argv[4]) if len(sys.argv) > 4 else -60.0


def run(with_temperature):
    random.seed(1234)
    level = build_headless_level(level_number=6)
    os.chdir(ROOT / "Code")
    import temperature
    player = level.player
    player.health = 10 ** 9
    cx, cy = player.hitbox.midbottom
    units = []
    for _ in range(BODIES):
        unit = level.spawner.spawn_enemy({"type": "squid", "pos": (0, 0)})
        if unit is None:
            continue
        unit.team_id = "player"   # no fight: only temperature differs between the runs
        unit.hitbox.midbottom = (int(cx + random.randint(-900, 900)), int(cy + random.randint(-900, 900)))
        unit.plant_sprite_on_hitbox()
        unit.health = 10 ** 9
        units.append(unit)
    settle = temperature.settle
    spent = [0.0, 0]

    def timed(body, now):
        t = time.perf_counter()
        settle(body, now)
        spent[0] += time.perf_counter() - t
        spent[1] += 1

    temperature.settle = timed
    if with_temperature:
        now = pygame.time.get_ticks()
        for unit in units:
            temperature.join(unit, level, now)
        temperature.set_air(level, AIR, now, units)
        for unit in units:   # start them frozen: every body past the cold line from frame 1
            temperature.bump(unit, temperature.SKIN, -30.0, now)
    for _ in range(30):
        level.run(1 / 60)   # warm-up
    spent[:] = [0.0, 0]
    times = []
    start_ms = pygame.time.get_ticks()
    for _ in range(FRAMES):
        t0 = time.perf_counter()
        level.run(1 / 60)
        times.append(time.perf_counter() - t0)
    seconds = (pygame.time.get_ticks() - start_ms) / 1000.0
    temperature.settle = settle
    times.sort()
    n = len(times)
    lost = sum(10 ** 9 - u.health for u in units)
    wounding = sum(1 for u in units if temperature.skin(u, pygame.time.get_ticks()) < -12)
    print(f"temperature={'on ' if with_temperature else 'off'} bodies={len(units)} frames={n} "
          f"mean_ms={sum(times) / n * 1000:.2f} p95_ms={times[int(n * 0.95)] * 1000:.2f} "
          f"settles={spent[1]} settle_ms_per_frame={spent[0] / n * 1000:.3f} "
          f"settle_us_each={(spent[0] / spent[1] * 1e6) if spent[1] else 0:.1f} "
          f"wounding={wounding} health_lost={lost:.0f} sim_s={seconds:.1f}")


run(MODE == "on")
