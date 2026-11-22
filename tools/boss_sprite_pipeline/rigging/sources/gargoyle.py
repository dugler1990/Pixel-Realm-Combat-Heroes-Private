"""Objaverse winged gargoyle (3ds Max Biped names). Converted by rigfix/gargoyle_to_bvh.py.

Drives wings and jaw, which SOMA cannot. Its pelvis hangs on a large offset: bake with root_loc off.
"""
NAME = "gargoyle"
CONVERTER = "rigfix/gargoyle_to_bvh.py"
REST = "Biped"
STATIC = set()

JOINTS = {
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
