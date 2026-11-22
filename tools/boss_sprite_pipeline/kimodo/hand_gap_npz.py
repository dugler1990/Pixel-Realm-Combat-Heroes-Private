"""Hand gap of Kimodo outputs, on the pod, straight from the npz (no retarget): two-handed / bow clips checked
before anything is pulled.

    python hand_gap_npz.py /workspace/runs/<cell>[...]

Per clip: the distance between the LeftHand and RightHand joints (SOMA 77, posed_joints) as a share of the body's
height (head top joint minus the lowest foot joint, median over the clip): min, median, max; and for a bow clip the
frame with the hands farthest apart (full draw) with that gap. On a two-handed hilt the gap is about 0.05-0.10.
"""
import glob
import json
import os
import sys

import numpy as np

NAMES = None


def joint_names():
    from kimodo.skeleton import SOMASkeleton77
    s = SOMASkeleton77()
    for attr in ("bone_order_names", "joint_names", "bone_names"):
        if hasattr(s, attr):
            return list(getattr(s, attr))
    raise SystemExit("no joint names on SOMASkeleton77")


for root in sys.argv[1:]:
    for f in sorted(glob.glob(os.path.join(root, "**", "*.npz"), recursive=True)) or [root]:
        if not f.endswith(".npz"):
            continue
        NAMES = NAMES or joint_names()
        d = np.load(f, allow_pickle=True)
        P = np.asarray(d["posed_joints"])
        if P.ndim == 4:
            P = P[0]
        L, R, H = NAMES.index("LeftHand"), NAMES.index("RightHand"), NAMES.index("Head")
        feet = [NAMES.index(n) for n in NAMES if "Foot" in n or "Toe" in n]
        up = 1                                                  # y is up in SOMA output
        height = float(np.median(P[:, H, up] - P[:, feet, up].min(1)))
        gap = np.linalg.norm(P[:, L] - P[:, R], axis=1) / max(height, 1e-6)
        print("HAND_GAP_NPZ", os.path.relpath(f, "/workspace/runs"), json.dumps({
            "frames": len(gap), "min": round(float(gap.min()), 3), "median": round(float(np.median(gap)), 3),
            "max": round(float(gap.max()), 3), "widest_frame": int(gap.argmax()), "height_m": round(height, 3)}),
            flush=True)
