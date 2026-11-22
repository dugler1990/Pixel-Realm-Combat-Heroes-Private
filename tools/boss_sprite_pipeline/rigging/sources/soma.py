"""Kimodo / SOMA BVH (somaskel77 export).

Rest skeleton lies along +X (every bone (1,0,0)): never measure proportions or axes at rest; use
the reference pose. Jaw and eyes are static (2026-11-21, 40 clips: Jaw <= 1.1 deg, eyes <= 3.7 deg),
so nothing is driven from them.
"""
NAME = "soma"
CONVERTER = None          # already BVH
REST = "along +X; use the reference pose"
STATIC = {"jaw", "eye.L", "eye.R"}

JOINTS = {
    "Hips": "root",
    "Spine1": "spine",
    "Spine2": "spine2",
    "Chest": "chest",
    "Neck1": "neck",
    "Neck2": "neck2",
    "Head": "head",
    "Jaw": "jaw",
    "LeftEye": "eye.L",
    "RightEye": "eye.R",
    "LeftShoulder": "clavicle.L",
    "LeftArm": "upper_arm.L",
    "LeftForeArm": "forearm.L",
    "LeftHand": "hand.L",
    "RightShoulder": "clavicle.R",
    "RightArm": "upper_arm.R",
    "RightForeArm": "forearm.R",
    "RightHand": "hand.R",
    "LeftLeg": "thigh.L",
    "LeftShin": "shin.L",
    "LeftFoot": "ankle.L",
    "LeftToeBase": "foot.L",
    "RightLeg": "thigh.R",
    "RightShin": "shin.R",
    "RightFoot": "ankle.R",
    "RightToeBase": "foot.R",
}
