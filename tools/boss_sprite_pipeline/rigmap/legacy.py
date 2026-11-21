"""The bake still consumes source-joint → roles.json path. These are that table, in one place.

'soma' is the demon-oriented map: Head lands on the key 'neck', and Spine2 / Neck1 are absent
because that rig has nowhere to put them. 'anunaki' is the literal UniRig map, 22 paths.
"""
from __future__ import annotations

SOMA_PATHS = {
    "Hips": ("root",),
    "Spine1": ("spine",),
    "Chest": ("chest",),
    "Head": ("neck",),
    "LeftShoulder": ("arm_l", "shoulder"),
    "LeftArm": ("arm_l", "elbow"),
    "LeftForeArm": ("arm_l", "wrist"),
    "LeftHand": ("arm_l", "hand"),
    "RightShoulder": ("arm_r", "shoulder"),
    "RightArm": ("arm_r", "elbow"),
    "RightForeArm": ("arm_r", "wrist"),
    "RightHand": ("arm_r", "hand"),
    "LeftLeg": ("leg_l", "hip"),
    "LeftShin": ("leg_l", "knee"),
    "LeftFoot": ("leg_l", "ankle"),
    "LeftToeBase": ("leg_l", "foot"),
    "RightLeg": ("leg_r", "hip"),
    "RightShin": ("leg_r", "knee"),
    "RightFoot": ("leg_r", "ankle"),
    "RightToeBase": ("leg_r", "foot"),
}

ANUN_PATHS = {
    **SOMA_PATHS,
    "Spine2": ("spine2",),
    "Neck1": ("neck",),
    "Head": ("head",),
}


def as_legacy_map(source: str):
    if source == "soma":
        return dict(SOMA_PATHS)
    if source == "anunaki":
        return dict(ANUN_PATHS)
    return None
