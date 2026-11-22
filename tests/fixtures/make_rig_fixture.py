"""Save one clip's source matrices and one rig's rest data for the pure transfer tests. Runs under .venv-bpy.

    .venv-bpy/Scripts/python.exe tests/fixtures/make_rig_fixture.py <rig.glb> <canonical roles.json> <clip.bvh> <out.npz>

Only the joints a soma match drives are kept, so the file stays small.
"""
import json
import os
import sys

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from tools.boss_sprite_pipeline.rigging import sources  # noqa: E402
from tools.boss_sprite_pipeline.rigging.blender import pose_io  # noqa: E402
from tools.boss_sprite_pipeline.rigging.map.match import match  # noqa: E402

rig_glb, roles_path, bvh, out = sys.argv[1:5]
roles = json.load(open(roles_path))
_, _, rig = pose_io.load_target(rig_glb)
clip = pose_io.read_clip(bvh)
m = match(sources.label(clip["names"], "soma"), roles, rig["order"], static=sources.get("soma").STATIC)
keep = sorted({p["source"] for p in m["paired"]})
frames = clip["frames"]
world = np.array([[clip["world"][f][j] for j in keep] for f in frames], dtype=np.float64)
rest = np.array([clip["rest_world"][j] for j in keep])
meta = {
    "joints": keep,
    "frames": frames,
    "src_parent": clip["parent"],
    "height_f0": clip["height_f0"],
    "rig_order": rig["order"],
    "rig_parent": rig["parent"],
    "rig_length": rig["length"],
    "rig_height": rig["height"],
    "roles": roles,
}
np.savez_compressed(out, world=world, rest=rest, tw=rig["tw"],
                    rest_arm=np.array([rig["rest_arm"][b] for b in rig["order"]]),
                    meta=json.dumps(meta))
print("FIXTURE", out, world.shape)
