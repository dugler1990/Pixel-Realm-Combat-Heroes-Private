"""Where each setup settles and how fast it hurts: the numbers in damage_rules read off a table
(docs/damage/PLAN_temperature.md step 3). Runs the real temperature store on the hero's body card
(barb) wearing nothing, the loincloth or the plate chest, no pygame window.

Columns: steady skin, seconds until the skin passes the wound line, health per second once there,
seconds until a hero with vitality x 50 health is dead. "dashing" adds one slide (20 stamina,
EXERT each) every 2 s.

From a worktree root:
  Code/sprite_venv/Scripts/python.exe tools/temperature_table.py
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Code"))

import temperature  # noqa: E402
from damage_data import body as body_card  # noqa: E402
from damage_rules import COLD_SCALE, COOK, EXERT, HEAT_SCALE, HURT_AT  # noqa: E402
from defence_profile import base_layer, build_profile, natural_profile  # noqa: E402

BASES = json.loads((ROOT / "Graphics" / "Standard_Items" / "item_bases.json").read_text(encoding="utf-8"))
HORIZON_MS = 3_600_000
STEP_MS = 100


class _Resolver:
    """Counts the health temperature sends; nothing else."""

    def __init__(self):
        self.lost = []   # (ms, amount)

    def apply(self, ctx):
        self.lost.append((self.now, ctx.amount))


def _hero(wear, vitality):
    card = body_card("barb")
    defence = natural_profile(card)
    if wear:
        defence = build_profile(card, [(wear, BASES[wear], None)])
    level = SimpleNamespace(air=0.0, interaction_resolver=_Resolver())
    body = SimpleNamespace(id=1, team_id="player", body_def=card, defence=defence, level=level,
                           stats={"vitality": vitality})
    temperature.join(body, level, 0)
    return body, level


def _run(wear, vitality, air, dashing=False):
    body, level = _hero(wear, vitality)
    resolver = level.interaction_resolver
    resolver.now = 0
    temperature.set_air(level, air, 0, [body])
    health = vitality * 50
    crossed = None
    dead = None
    lost = 0
    for now in range(0, HORIZON_MS, STEP_MS):
        resolver.now = now
        if dashing and now % 2000 == 0 and now:
            temperature.bump(body, temperature.SKIN, 20 * EXERT, now)
        temperature.tick(level, now)
        skin = temperature.skin(body, now)
        if crossed is None and (skin > COOK or skin < -HURT_AT):
            crossed = now
        lost = sum(a for _t, a in resolver.lost)
        if dead is None and lost >= health:
            dead = now
            break
        if now > 600_000 and crossed is None and not dashing:
            break
    steady = temperature.skin(body, HORIZON_MS * 10) if not dashing else temperature.skin(body, now)
    rate = HEAT_SCALE * max(0.0, steady - COOK) + COLD_SCALE * max(0.0, -steady - HURT_AT)
    return steady, crossed, rate, dead


def _fmt_s(ms):
    return "never" if ms is None else f"{ms / 1000:.0f}"


def main():
    rows = []
    for air, place in ((-30, "ice"), (-60, "deep ice"), (20, "desert"), (40, "hot desert")):
        for wear in (None, "loincloth", "plate_chest"):
            for vitality in (20, 40, 60):
                rows.append((place, air, wear or "naked", vitality, False, _run(wear, vitality, air)))
        if air > 0:
            for wear in (None, "plate_chest"):
                rows.append((place, air, (wear or "naked"), 20, True, _run(wear, 20, air, dashing=True)))
    print(f"{'place':<11}{'air':>5}  {'wear':<12}{'vit':>4} {'':<8}{'skin':>7}{'past line s':>12}"
          f"{'hp/s':>7}{'dead s':>8}")
    for place, air, wear, vit, dashing, (steady, crossed, rate, dead) in rows:
        print(f"{place:<11}{air:>5}  {wear:<12}{vit:>4} {'dashing' if dashing else '':<8}"
              f"{steady:>7.1f}{_fmt_s(crossed):>12}{rate:>7.2f}{_fmt_s(dead):>8}")


if __name__ == "__main__":
    main()
