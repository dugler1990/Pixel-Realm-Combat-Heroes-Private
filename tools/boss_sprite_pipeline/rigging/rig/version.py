"""Rig versions: where rigging and mapping meet.

A version is generated/bosses/characters/<id>/rig/v<N>/ holding record.json, roles.json (canonical
role -> bone) and, for anything but an imported v1, rig.glb. Nothing is overwritten. This module is
the only code that assigns N: the directory is created with mkdir, which fails if another writer got
there first, so a local and a pod step cannot take the same number.

record.json: version, step, kind (weights | bone_set), settings (resolved, with sources), input
(version or null), glb, bones, bone_hash, checks, accepted, when, note.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .. import paths
from . import glb as _glb

KINDS = ("weights", "bone_set")


def rig_dir(cid: str) -> Path:
    return paths.character_dir(cid) / "rig"


def vdir(cid: str, n: int) -> Path:
    return rig_dir(cid) / f"v{n}"


def versions(cid: str) -> list[int]:
    d = rig_dir(cid)
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit() and (p / "record.json").is_file():
            out.append(int(p.name[1:]))
    return sorted(out)


def begin(cid: str) -> tuple[int, Path]:
    """Reserve the next version number. Returns (n, folder). The step writes rig.glb there."""
    rig_dir(cid).mkdir(parents=True, exist_ok=True)
    n = max([0] + [int(p.name[1:]) for p in rig_dir(cid).iterdir()
                   if p.is_dir() and p.name[1:].isdigit()]) + 1
    while True:
        try:
            vdir(cid, n).mkdir()
            return n, vdir(cid, n)
        except FileExistsError:
            n += 1


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def finish(cid: str, n: int, *, step: str, kind: str, settings: dict, input_n: int | None,
           roles: dict[str, str], glb: Path | None = None, glb_ref: str | None = None,
           checks: dict | None = None, note: str = "", accepted: bool = False) -> dict:
    if kind not in KINDS:
        raise ValueError(kind)
    d = vdir(cid, n)
    glb_path = Path(glb) if glb else paths.resolve(glb_ref) if glb_ref else d / "rig.glb"
    if not glb_path.is_file():
        raise FileNotFoundError(glb_path)
    bones = _glb.skeleton(glb_path)
    missing = sorted(b for b in roles.values() if b not in {x["name"] for x in bones})
    if missing:
        raise ValueError(f"roles name bones the rig does not have: {missing}")
    rec = {
        "version": n,
        "step": step,
        "kind": kind,
        "settings": settings,
        "input": input_n,
        "glb": paths.rel(glb_path),
        "bones": bones,
        "bone_hash": _glb.bone_hash(bones),
        "roles_hash": roles_hash(roles),
        "checks": checks or {},
        "accepted": accepted,
        "when": _now(),
        "note": note,
    }
    (d / "roles.json").write_text(json.dumps(roles, indent=1), encoding="utf-8")
    (d / "record.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def load(cid: str, n: int) -> dict:
    d = vdir(cid, n)
    rec = json.loads((d / "record.json").read_text(encoding="utf-8"))
    rec["roles"] = json.loads((d / "roles.json").read_text(encoding="utf-8"))
    rec["glb_path"] = str(paths.resolve(rec["glb"]))
    rec.setdefault("roles_hash", roles_hash(rec["roles"]))
    return rec


def roles_hash(roles: dict) -> str:
    import hashlib
    return hashlib.sha1(json.dumps(roles, sort_keys=True).encode()).hexdigest()[:12]


def set_current(cid: str, n: int) -> dict:
    """Make an accepted version the character's current rig."""
    from ..map import character as C
    rec = load(cid, n)
    if not rec.get("accepted"):
        rec = {**rec, **accept(cid, n)}
    char = C.load(cid)
    char["rig"] = n
    C.save(char)
    return char


def chain(cid: str, n: int) -> list[dict]:
    """The version and every input it was built from, newest first."""
    out, seen = [], set()
    while n is not None and n not in seen:
        seen.add(n)
        rec = load(cid, n)
        out.append(rec)
        n = rec.get("input")
    return out


def gates_pass(rec: dict) -> tuple[bool, list[str]]:
    bad = [k for k, c in (rec.get("checks") or {}).items() if c.get("gate") and not c.get("pass")]
    return (not bad, bad)


def accept(cid: str, n: int) -> dict:
    rec = load(cid, n)
    ok, bad = gates_pass(rec)
    if not ok:
        raise ValueError(f"v{n}: gate checks fail: {bad}")
    path = vdir(cid, n) / "record.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accepted"] = True
    raw["accepted_at"] = _now()
    path.write_text(json.dumps(raw, indent=1), encoding="utf-8")
    return raw


def import_v1(cid: str, glb_rel: str, roles: dict[str, str], history: str) -> dict:
    """Today's rig as v1, history as text. The glb stays where it is; v1 points at it."""
    if versions(cid):
        raise FileExistsError(f"{cid} already has versions {versions(cid)}")
    n, _ = begin(cid)
    return finish(cid, n, step="import", kind="bone_set", settings={}, input_n=None, roles=roles,
                  glb_ref=glb_rel, note=history, accepted=True)
