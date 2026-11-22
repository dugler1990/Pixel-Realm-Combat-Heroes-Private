"""Read a rigged GLB's skeleton without Blender: only the JSON chunk is read, not the mesh."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


def read_json(path: Path) -> dict:
    with open(path, "rb") as f:
        magic, _ver, _length = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise ValueError(f"{path}: not a GLB")
        clen, ctype = struct.unpack("<I4s", f.read(8))
        if ctype != b"JSON":
            raise ValueError(f"{path}: first chunk is not JSON")
        return json.loads(f.read(clen))


def skeleton(path: Path) -> list[dict]:
    """[{name, parent}] for the first skin's joints, parent None at a root."""
    g = read_json(path)
    skins = g.get("skins") or []
    if not skins:
        return []
    nodes = g["nodes"]
    joints = skins[0]["joints"]
    parent_of = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent_of[c] = i
    js = set(joints)
    out = []
    for j in joints:
        p = parent_of.get(j)
        while p is not None and p not in js:
            p = parent_of.get(p)
        n = nodes[j]
        rest = [round(x, 4) for x in n.get("translation", [0, 0, 0]) + n.get("rotation", [0, 0, 0, 1])]
        out.append({"name": n.get("name", f"node_{j}"),
                    "parent": nodes[p].get("name") if p is not None else None, "rest": rest})
    return out


def bone_hash(bones: list[dict]) -> str:
    """Names, parents and rest transforms: a moved pivot changes it as much as a new bone does."""
    lines = sorted(f"{b['name']}>{b['parent']}>{b.get('rest')}" for b in bones)
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()[:12]
