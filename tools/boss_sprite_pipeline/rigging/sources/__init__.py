"""Motion sources: labeller (joint -> role), converter, rest convention, static joints."""
from __future__ import annotations

from . import g1, gargoyle, soma

SOURCES = {m.NAME: m for m in (soma, g1, gargoyle)}


def get(name: str):
    if name not in SOURCES:
        raise ValueError(f"source {name!r}, have {sorted(SOURCES)}")
    return SOURCES[name]


def label(names, source: str) -> dict[str, str]:
    """Joint names in a clip -> {joint: role} for the joints this source knows."""
    table = get(source).JOINTS
    return {n: table[n] for n in names if n in table}
