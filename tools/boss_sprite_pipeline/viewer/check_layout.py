"""Does a split-export viewer directory actually hold a skeleton its clips can drive?

    python check_layout.py <viewer_dir> [--write-clips-json]

The split layout stores the mesh+skeleton once (`base.glb`) and each clip as armature-only
animation (`clips/<name>.glb`). three.js binds an AnimationClip's tracks to scene nodes **by
name**. So the layout is only valid if every node a clip animates exists in the base.

That is not automatic, and getting it wrong is silent. Measured 2026-10-12: the four anunaki
variants are four *different* UniRig outputs - anun0/anun2 have 28 bones, anun1 40, anun3 46,
and each one's roles file points at different indices (anun0's left leg is bone_20, anun3's is
bone_38). A bake script that moved every variant's `base.glb` up to one shared
`<parent>/_base.glb` left a single body for all four; the viewer's documented fallback to
`../_base.glb` then loaded it, and three of the four played hip rotations into finger bones
while the variant that happened to bake LAST looked perfect. Nothing in the retarget was wrong.

This checks the invariant the viewer depends on, resolving the base exactly the way index.html
does, so a bad layout fails here instead of looking like a retarget bug.
"""
import glob
import json
import os
import struct
import sys

DIR = os.path.abspath(sys.argv[1])
WRITE = "--write-clips-json" in sys.argv


def gltf_json(path):
    """The JSON chunk of a .glb, without loading its binary payload."""
    with open(path, "rb") as f:
        magic, ver, _total = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67:
            raise ValueError("%s is not a glb" % path)
        length, _ty = struct.unpack("<II", f.read(8))
        return json.loads(f.read(length).decode("utf-8"))


def node_names(j):
    return [n.get("name", "") for n in j.get("nodes", [])]


def animated_nodes(j):
    """Node names targeted by any animation channel."""
    names = node_names(j)
    out = set()
    for a in j.get("animations", []):
        for ch in a.get("channels", []):
            i = ch.get("target", {}).get("node")
            if i is not None and 0 <= i < len(names):
                out.add(names[i])
    return out


clips = sorted(glob.glob(os.path.join(DIR, "clips", "*.glb")))
if WRITE:
    names = [os.path.basename(p)[:-4] for p in clips]
    json.dump(names, open(os.path.join(DIR, "clips.json"), "w"))
    print("clips.json %d clips" % len(names), flush=True)

# exactly index.html's rule: <dir>/base.glb, else <dir>/../_base.glb
base = os.path.join(DIR, "base.glb")
shared = False
if not os.path.exists(base):
    base = os.path.join(os.path.dirname(DIR), "_base.glb")
    shared = True
if not os.path.exists(base):
    print("LAYOUT BAD  no base.glb and no ../_base.glb for %s" % DIR, flush=True)
    raise SystemExit(1)

have = set(node_names(gltf_json(base)))
nb = len([n for n in have if n.startswith("bone_")])
print("base %s%s  %d nodes (%d bone_*)"
      % (os.path.relpath(base, os.path.dirname(DIR)),
         "   <-- SHARED with sibling dirs" if shared else "", len(have), nb), flush=True)

bad = 0
for p in clips:
    want = animated_nodes(gltf_json(p))
    missing = sorted(want - have)
    tag = "ok" if not missing else "MISSING %d of %d: %s" % (
        len(missing), len(want), ",".join(missing[:6]) + ("..." if len(missing) > 6 else ""))
    if missing:
        bad += 1
    print("  %-26s %3d animated nodes  %s" % (os.path.basename(p)[:-4], len(want), tag), flush=True)

print("LAYOUT %s  %d of %d clips drive a bone the base does not have"
      % ("OK" if not bad else "BAD", bad, len(clips)), flush=True)
raise SystemExit(1 if bad else 0)
