"""Where each setup settles and how fast it hurts, read off the real temperature store
(docs/damage/PLAN_temperature.md, the feel targets). The hero's body card (barb) wearing nothing,
the loincloth, or the full plate set; no pygame window.

Columns: the skin it settles at (dashing: its highest), seconds until it starts hurting, health
per second once settled, seconds until a hero with vitality x 50 health is dead, and the outer
layer's shade. "dashing" spends one slide (20 stamina) every second: stamina is heat.

From a worktree root:
  Code/sprite_venv/Scripts/python.exe tools/temperature_table.py
"""
import heapq
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
from damage_rules import COOK, FAINT, HURT_AT, heat_shade  # noqa: E402
from defence_profile import build_profile, natural_profile  # noqa: E402

BASES = json.loads((ROOT / "Graphics" / "Standard_Items" / "item_bases.json").read_text(encoding="utf-8"))
PLATE = [name for name, base in BASES.items() if not name.startswith("_") and base.get("set") == "fullplate"]
WEAR = {"naked": [], "loincloth": ["loincloth"], "plate": PLATE}
PLACES = {   # air, sun
    "mild": (0.0, 0.0),
    "ice": (-30.0, 0.3),
    "deep ice": (-60.0, 0.3),
    "desert": (10.0, 1.0),
    "hot desert": (20.0, 1.5),
}
HORIZON_MS = 3_600_000
SLIDE = 20


class _Resolver:
    def __init__(self):
        self.lost = 0.0

    def apply(self, ctx):
        self.lost += ctx.amount


def hero(wear, vitality, air, sun):
    card = body_card("barb")
    names = WEAR[wear]
    defence = build_profile(card, [(n, BASES[n], None) for n in names]) if names else natural_profile(card)
    level = SimpleNamespace(air=0.0, sun=0.0, interaction_resolver=_Resolver())
    body = SimpleNamespace(id=1, team_id="player", body_def=card, defence=defence, level=level,
                           stats={"vitality": vitality})
    temperature.join(body, level, 0)
    temperature.set_air(level, air, 0, [body])
    temperature.set_sun(level, sun, 0, [body])
    return body, level


def run(wear, vitality, place, dashing=False):
    """(settled or highest skin, ms until hurting, hp/s settled, ms until dead, outer shade)."""
    air, sun = PLACES[place]
    body, level = hero(wear, vitality, air, sun)
    health = vitality * 50
    hurt_at = dead_at = None
    top = temperature.skin(body, 0)
    now = 0
    next_slide = 1000 if dashing else None
    while now < HORIZON_MS:
        wake = level.warmth_wakes[0][0] if getattr(level, "warmth_wakes", None) else None
        steps = [t for t in (wake, next_slide) if t is not None]
        if not steps:
            break
        now = min(steps)
        if next_slide is not None and now == next_slide:
            temperature.exert(body, SLIDE, now)
            next_slide += 1000
        while level.warmth_wakes and level.warmth_wakes[0][0] <= now:
            temperature.tick(level, level.warmth_wakes[0][0])
        skin = temperature.skin(body, now)
        top = max(top, skin)
        if hurt_at is None and (skin > COOK or skin < -HURT_AT):
            hurt_at = now
        if level.interaction_resolver.lost >= health:
            dead_at = now
            break
        if dashing and now > 120_000:
            break
    settled = top if dashing else temperature.skin(body, HORIZON_MS * 10)
    outer = temperature.outer(body, HORIZON_MS * 10 if not dashing else now)
    shade = heat_shade(outer) or ("faint" if outer > FAINT else "")
    rate = (temperature.HOT_SCALE * max(0.0, settled - COOK)
            + temperature.COLD_SCALE * max(0.0, -settled - HURT_AT))
    return settled, hurt_at, rate, dead_at, shade


def rows():
    out = []
    for place in PLACES:
        for wear in WEAR:
            for vitality in (20, 40, 60):
                out.append((place, wear, vitality, False, run(wear, vitality, place)))
        if PLACES[place][1] >= 1.0:
            for wear in ("naked", "plate"):
                out.append((place, wear, 20, True, run(wear, 20, place, dashing=True)))
    return out


def _s(ms):
    return "never" if ms is None else f"{ms / 1000:.0f}"


def main():
    print(f"{'place':<11}{'wear':<10}{'vit':>4} {'':<8}{'skin':>7}{'hurts s':>9}{'hp/s':>7}"
          f"{'dead s':>8}  outer")
    for place, wear, vit, dashing, (skin, hurt, rate, dead, shade) in rows():
        print(f"{place:<11}{wear:<10}{vit:>4} {'dashing' if dashing else '':<8}{skin:>7.1f}"
              f"{_s(hurt):>9}{rate:>7.2f}{_s(dead):>8}  {shade}")


if __name__ == "__main__":
    main()
