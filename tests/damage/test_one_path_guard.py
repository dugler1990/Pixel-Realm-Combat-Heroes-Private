"""Keeps the damage foundation (docs/damage/PLAN_damage_foundation.md) true after it lands: each
rule is a search over Code/ that must find nothing outside the one place allowed."""
import functools
import os
import re
from pathlib import Path

import pytest

CODE = Path(__file__).resolve().parents[2] / "Code"
SKIP_DIRS = {"sprite_venv", "__pycache__"}


@functools.lru_cache(maxsize=1)
def _lines():
    """(relative path, line number, line) for every code line under Code/, read once."""
    rows = []
    for root, dirs, files in os.walk(CODE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(root) / name
            rel = path.relative_to(CODE).as_posix()
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if not line.lstrip().startswith("#"):
                    rows.append((rel, number, line))
    return rows


def _hits(pattern):
    rx = re.compile(pattern)
    return [f"{rel}:{number}" for rel, number, line in _lines() if rx.search(line)]


RULES = [
    # (what, pattern, files allowed to match: why)
    ("health goes down only in Entity.take_damage", r"\.health\s*-=",
     {"Entity.py": "take_damage", "interaction_validation.py": "its stub body"}),
    ("death only through Entity.die", r"\bcheck_death\b|\bplayer_death\b", {}),
    ("invulnerability is the 'invulnerable' condition", r"\bvulnerable\b|invulnerability_duration|invincibility_duration|\bover_time\b", {}),
    ("one attacker record", r"recent_attacker_|retaliate_team_id|retaliate_until_ms|register_retaliation", {}),
    ("one team rule", r"can_potentially_affect|can_team_interact", {}),
    ("ground effects are not hits", r"[\"']effect_state[\"']", {}),
    ("damage numbers live in the attack defs",
     r"(^\s*|[{,]\s*)[\"']damage[\"']\s*:|get_full_\w*_damage|_resolve_projectile_damage_payload"
     r"|[\"'](base_damage|burst_damage|dot_damage)[\"']", {}),
    ("sounds load through sounds.get", r"mixer\.Sound\(",
     {"sounds.py": "the cache", "dialogue/voice.py": "its own loader, one file per line"}),
    ("holy and unholy go through KIND_MULT in damage_rules.sacred", r"\bKIND_MULT\b",
     {"damage_rules.py": "sacred", "damage_data.py": "the loader"}),
    ("no venom has code of its own: venoms are rows in venoms.json",
     r"[\"'](snake|plant|scorpion|frog)_venom[\"']", {}),
]


@pytest.mark.parametrize("what, pattern, allowed", RULES, ids=[r[0] for r in RULES])
def test_rule_holds(what, pattern, allowed):
    stray = [hit for hit in _hits(pattern) if hit.rsplit(":", 1)[0] not in allowed]
    assert stray == [], f"{what}: {stray}"
