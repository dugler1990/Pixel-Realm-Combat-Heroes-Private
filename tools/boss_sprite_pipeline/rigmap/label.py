"""Name tables. A labeller returns bone-or-joint name → anatomical role. Nothing else."""
from __future__ import annotations

# SOMA joint → role. Neck2 is recorded so a match can list it as missing and not grow a bone.
SOMA = {
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

# Gargoyle joint → role. Head joint drives the bone the demon file calls neck.
GARGOYLE = {
    "Bip01-Pelvis_03": "root",
    "Bip01-Spine_00": "spine",
    "Bip01-Spine2_05": "chest",
    "Bip01-Head_09": "head",
    "Bip01-L-Clavicle_011": "clavicle.L",
    "Bip01-L-UpperArm_012": "upper_arm.L",
    "Bip01-L-Forearm_013": "forearm.L",
    "Bip01-R-Clavicle_019": "clavicle.R",
    "Bip01-R-UpperArm_020": "upper_arm.R",
    "Bip01-R-Forearm_021": "forearm.R",
    "Bip01-L-Thigh_045": "thigh.L",
    "Bip01-L-Calf_046": "shin.L",
    "Bip01-L-Foot_047": "ankle.L",
    "Bip01-R-Thigh_049": "thigh.R",
    "Bip01-R-Calf_050": "shin.R",
    "Bip01-R-Foot_051": "ankle.R",
    "Bone_Lwing001_028": "wing.L",
    "Bone_Lwing002_029": "wing.L.tip",
    "Bone_Rwing001_036": "wing.R",
    "Bone_Rwing002_037": "wing.R.tip",
}

# G1 last link of each chain → role. No head, no neck, no clavicles.
G1 = {
    "pelvis_skel": "root",
    "waist_yaw_skel": "spine",
    "waist_pitch_skel": "chest",
    "left_shoulder_yaw_skel": "upper_arm.L",
    "left_elbow_skel": "forearm.L",
    "left_wrist_roll_skel": "hand.L",
    "right_shoulder_yaw_skel": "upper_arm.R",
    "right_elbow_skel": "forearm.R",
    "right_wrist_roll_skel": "hand.R",
    "left_hip_yaw_skel": "thigh.L",
    "left_knee_skel": "shin.L",
    "left_ankle_roll_skel": "ankle.L",
    "left_toe_base": "foot.L",
    "right_hip_yaw_skel": "thigh.R",
    "right_knee_skel": "shin.R",
    "right_ankle_roll_skel": "ankle.R",
    "right_toe_base": "foot.R",
}

_SOURCES = {"soma": SOMA, "anunaki": SOMA, "gargoyle": GARGOYLE, "g1": G1}

# anun_roles.py keys. elbow is the upper arm. On a human rig, neck is a neck.
_ARM = {"shoulder": "clavicle", "elbow": "upper_arm", "wrist": "forearm", "hand": "hand"}
_LEG = {"hip": "thigh", "knee": "shin", "ankle": "ankle", "foot": "foot"}


def label_bvh(names: list[str], source: str = "soma") -> dict[str, str]:
    table = _SOURCES[source if source != "anunaki" else "soma"]
    # anunaki is a target style, not a different BVH. Source clips are SOMA either way.
    if source == "anunaki":
        table = SOMA
    return {n: table[n] for n in names if n in table}


def bone_names(roles: dict) -> list[str]:
    found: list[str] = []

    def walk(node):
        if isinstance(node, str) and node.startswith("bone_"):
            found.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(roles)
    return found


def label_roles(roles: dict, recipe: str) -> dict[str, str]:
    """recipe 'human' (literal neck/head) or 'creature' (the key neck is the skull, head is the snout)."""
    if recipe not in ("human", "creature"):
        raise ValueError(recipe)
    out: dict[str, str] = {}
    for key in ("root", "spine", "spine2", "chest"):
        if isinstance(roles.get(key), str):
            out[roles[key]] = key
    if recipe == "human":
        if isinstance(roles.get("neck"), str):
            out[roles["neck"]] = "neck"
        if isinstance(roles.get("head"), str):
            out[roles["head"]] = "head"
    else:
        # The skull is stored under the key "neck". The key "head" is a snout and is not driven.
        if isinstance(roles.get("neck"), str):
            out[roles["neck"]] = "head"
    for side_key, suffix in (("arm_l", ".L"), ("arm_r", ".R")):
        block = roles.get(side_key)
        if isinstance(block, dict):
            for part, role in _ARM.items():
                bone = block.get(part)
                if isinstance(bone, str):
                    out[bone] = role + suffix
    for side_key, suffix in (("leg_l", ".L"), ("leg_r", ".R")):
        block = roles.get(side_key)
        if isinstance(block, dict):
            for part, role in _LEG.items():
                bone = block.get(part)
                if isinstance(bone, str):
                    out[bone] = role + suffix
    return out
