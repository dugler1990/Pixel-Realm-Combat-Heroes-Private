"""Unitree G1 robot motion. Converted to BVH by rigfix/g1_to_bvh.py. No head, neck or clavicles."""
NAME = "g1"
CONVERTER = "rigfix/g1_to_bvh.py"
REST = "see g1_skel.json"
STATIC = set()

JOINTS = {
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
