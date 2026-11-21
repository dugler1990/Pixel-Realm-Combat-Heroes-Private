"""Crowd fight bench for the damage path: the real Level4 headless, two hostile crowds around the
hero (tribey_spear as ally_4 vs squid as enemy_1), time per frame; then one resolver strike over
the crowd. Numbers are noisy (the AI runs on the clock): run it 3 times and compare means.

From a worktree root:
  Code/sprite_venv/Scripts/python.exe tools/damage_crowd_bench.py [frames=600] [per_side=20]
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

FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 600
PER_SIDE = int(sys.argv[2]) if len(sys.argv) > 2 else 20

random.seed(1234)
level = build_headless_level(level_number=6)
os.chdir(ROOT / "Code")
player = level.player
player.health = 10 ** 9
cx, cy = player.hitbox.midbottom
units = []
for i in range(PER_SIDE * 2):
    side = i % 2
    unit = level.spawner.spawn_enemy({"type": "squid" if side else "tribey_spear", "pos": (0, 0)})
    if unit is None:
        continue
    unit.team_id = "enemy_1" if side else "ally_4"
    dx = (-160 if side else 160) + random.randint(-80, 80)
    unit.hitbox.midbottom = (int(cx + dx), int(cy + random.randint(-200, 200)))
    unit.plant_sprite_on_hitbox()
    units.append(unit)

resolver = level.interaction_resolver
land = resolver.land
lands = [0]


def _counted(ctx):
    lands[0] += 1
    return land(ctx)


resolver.land = _counted
health_start = sum(u.health for u in units)
times = []
for _ in range(FRAMES):
    t0 = time.perf_counter()
    level.run(1 / 60)
    times.append(time.perf_counter() - t0)
resolver.land = land

lost = health_start - sum(max(u.health, 0) for u in units)
dead = [u for u in units if not u.alive()]
times.sort()
n = len(times)
print(f"units={len(units)} frames={n} died={len(dead)} dead_still_in_enemies="
      f"{sum(1 for u in dead if u in level.spawner.enemies)} health_lost={lost} lands={lands[0]} "
      f"mean_ms={sum(times) / n * 1000:.2f} p50_ms={times[n // 2] * 1000:.2f} "
      f"p95_ms={times[int(n * 0.95)] * 1000:.2f}")

live = [u for u in units if u.alive()]
for u in live:
    u.health = 10 ** 9
t0 = time.perf_counter()
for _ in range(2000):
    resolver.strike(live, kind="damage", source_kind="bench", source_team="enemy_1", amount=1)
print(f"strike_us={(time.perf_counter() - t0) / 2000 * 1e6:.1f} targets={len(live)}")
