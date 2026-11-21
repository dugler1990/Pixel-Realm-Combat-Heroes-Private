"""The one Blender entry point for library code. Always a fresh process (a rig change is verified in a
process that did not make it - NOTES_rig_jaw_sam3.md).

    .venv-bpy/Scripts/python.exe runner.py check <name> <glb> <out.json>

Prints RUNNER_OK <out.json> last. Proven one-off scripts (rig_reweight.py, fix_neutral_bone.py,
anun_roles.py) are still called directly by their steps until they are folded in here.
"""
from __future__ import annotations

import importlib
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def main(argv):
    if len(argv) != 4 or argv[0] != "check":
        raise SystemExit(__doc__)
    _, name, glb, out = argv
    mod = importlib.import_module(f"tools.boss_sprite_pipeline.rigging.rig.checks.{name}")
    result = mod.measure(glb)
    with open(out, "w") as f:
        json.dump(result, f, indent=1)
    print("RUNNER_OK", out, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
