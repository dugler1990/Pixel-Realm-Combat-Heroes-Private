"""Declared settings. One declaration per setting: the page builds its form from it, the command
line validates against it, and every record stores the resolved value with where it came from.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Setting:
    name: str
    type: str                     # "float" | "int" | "bool" | "choice" | "str" | "roles_bool" | "path"
    doc: str
    default: object = None        # None + required: no default, the caller must give it
    min: float | None = None
    max: float | None = None
    choices: tuple = ()
    required: bool = True
    unit: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        d["choices"] = list(self.choices)
        return d


class SettingError(ValueError):
    pass


def _cast(s: Setting, v):
    if v is None:
        if s.required:
            raise SettingError(f"{s.name}: required")
        return None
    t = s.type
    if t == "float":
        v = float(v)
    elif t == "int":
        v = int(v)
    elif t == "bool":
        if isinstance(v, str):
            v = v.strip().lower() in ("1", "true", "yes", "on")
        v = bool(v)
    elif t == "choice":
        if v not in s.choices:
            raise SettingError(f"{s.name}: {v!r} not in {list(s.choices)}")
    elif t == "roles_bool":
        if not isinstance(v, dict) or not all(isinstance(x, bool) for x in v.values()):
            raise SettingError(f"{s.name}: want {{role: true/false}}")
        v = dict(v)
    elif t in ("str", "path"):
        v = str(v)
    else:
        raise SettingError(f"{s.name}: unknown type {t}")
    if t in ("float", "int"):
        if s.min is not None and v < s.min or s.max is not None and v > s.max:
            raise SettingError(f"{s.name}: {v} outside {s.min}..{s.max}")
    return v


def resolve(decls: list[Setting], layers: list[tuple[str, dict]]) -> dict:
    """layers: [(source_name, values)], later wins. Returns {name: {"value", "from"}}.

    A declaration's own default counts only when it has one (default is not None); otherwise a
    missing required value raises. Unknown keys raise, so a typo cannot pass silently.
    """
    known = {s.name for s in decls}
    for src, vals in layers:
        extra = set(vals or {}) - known
        if extra:
            raise SettingError(f"{src}: unknown settings {sorted(extra)}")
    out = {}
    for s in decls:
        val, frm = s.default, "default"
        for src, vals in layers:
            if vals and s.name in vals:
                val, frm = vals[s.name], src
        if frm == "default" and s.default is None and s.required:
            raise SettingError(f"{s.name}: required, not given")
        out[s.name] = {"value": _cast(s, val), "from": frm}
    return out


def values(resolved: dict) -> dict:
    return {k: v["value"] for k, v in resolved.items()}


def schema(decls: list[Setting]) -> list[dict]:
    return [s.to_json() for s in decls]
