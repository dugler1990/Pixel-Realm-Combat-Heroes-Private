"""The barb's move set for Kimodo: several single-sentence wordings per move (wording is the large effect,
FINDINGS_kimodo_generation.md), 3 samples each. Game: a top-down action RPG, a big heavy barbarian; clips loop
or return to a ready stance so they chain."""
import json
import sys

S = 3
moves = {
    # locomotion
    "idle": (4.0, [
        "A big strong man stands relaxed in a ready stance, breathing slowly and shifting his weight slightly.",
        "A heavy muscular warrior stands still in a wide ready stance with his arms loose at his sides, breathing.",
    ]),
    "walk": (3.0, [
        "A big strong man walks forward at a steady pace with a heavy confident stride, arms swinging naturally.",
        "A heavy muscular warrior walks straight forward with powerful steps.",
    ]),
    "run": (2.5, [
        "A big strong man runs forward fast with heavy powerful strides, arms pumping.",
        "A heavy muscular warrior sprints straight forward, leaning into the run.",
    ]),
    "dash": (1.5, [
        "A big strong man bursts forward in a quick explosive dash of three fast steps and stops in a ready stance.",
        "A heavy warrior lunges forward in a short fast dash, then plants his feet and stands ready.",
    ]),
    "slide": (2.0, [
        "A big strong man runs forward and drops into a feet-first sliding tackle along the ground, then gets back up.",
        "A heavy warrior sprints and slides low on the ground feet first like a football slide tackle, then stands up.",
    ]),
    "leap": (3.0, [
        "A big strong man crouches, leaps high and far forward through the air and lands heavily with both feet, slamming the ground, then stands ready.",
        "A heavy barbarian jumps up and forward, falls down hard and lands in a deep crouch with a heavy impact, then rises to a ready stance.",
    ]),
    # one-handed weapon
    "sword_slash": (2.0, [
        "A warrior holding a sword in his right hand slashes it diagonally from his right shoulder down across his body, then returns to a ready stance.",
        "A man swings a one-handed sword horizontally from right to left in front of him, then returns to a ready stance.",
    ]),
    "sword_thrust": (2.0, [
        "A warrior holding a sword in his right hand lunges forward and thrusts the sword straight ahead, then steps back to a ready stance.",
    ]),
    "axe_chop": (2.0, [
        "A warrior raises an axe in his right hand high above his head and chops it straight down in front of him, then returns to a ready stance.",
    ]),
    "sword_combo": (3.0, [
        "A warrior holding a sword in his right hand slashes left to right, then right to left, then thrusts forward, and returns to a ready stance.",
    ]),
    # two-handed weapon
    "greatsword_overhead": (2.5, [
        "A warrior holds a heavy greatsword with both hands, lifts it high over his head and slams it straight down in front of him, then returns to a ready stance.",
        "A big man grips a huge two-handed sword, raises it behind his head and brings it down in a powerful vertical strike.",
    ]),
    "greatsword_sweep": (2.5, [
        "A warrior holds a heavy greatsword with both hands and swings it in a wide horizontal arc from his right side to his left, turning his whole body, then returns to a ready stance.",
    ]),
    "hammer_slam": (2.5, [
        "A big man raises a heavy war hammer with both hands over his shoulder and smashes it down onto the ground in front of him, then lifts it back to a ready stance.",
    ]),
    # parries and blocks
    "parry": (1.5, [
        "A warrior holding a sword in his right hand raises it quickly to block a blow coming at his head, then returns to a ready stance.",
        "A man parries an attack by sweeping his sword sideways across his body, then returns to a ready stance.",
    ]),
    "block_2h": (1.5, [
        "A warrior holds a greatsword horizontally above his head with both hands to block a heavy downward blow, then returns to a ready stance.",
    ]),
    # boxing
    "jab": (1.5, [
        "A boxer in a guard stance throws a quick straight left jab and brings his fist back to his guard.",
    ]),
    "cross": (1.5, [
        "A boxer in a guard stance throws a powerful straight right punch, turning his hips, and returns to his guard.",
    ]),
    "hook": (1.5, [
        "A boxer in a guard stance throws a wide left hook to the head and returns to his guard.",
    ]),
    "uppercut": (1.5, [
        "A boxer in a guard stance drops slightly and throws a rising right uppercut, then returns to his guard.",
    ]),
    "box_combo": (3.0, [
        "A boxer in a guard stance throws a left jab, a right cross and a left hook, then returns to his guard.",
        "A boxer throws a fast one-two punch combination followed by a right uppercut, then returns to his guard.",
    ]),
    "box_guard": (3.0, [
        "A boxer stands in a guard stance with his fists up, bouncing lightly on his feet and moving his head.",
    ]),
    # kickboxing
    "front_kick": (1.5, [
        "A fighter in a guard stance lifts his right knee and pushes his foot straight forward in a front kick, then returns to his guard.",
    ]),
    "roundhouse": (2.0, [
        "A fighter in a guard stance pivots on his left foot and swings his right leg in a roundhouse kick at chest height, then returns to his guard.",
    ]),
    "knee": (1.5, [
        "A fighter grabs forward with both hands and drives his right knee up hard, then returns to his guard.",
    ]),
    "kick_combo": (3.0, [
        "A kickboxer throws a left jab, a right cross and a right roundhouse kick, then returns to his guard.",
    ]),
    # bow (second set)
    "bow_shoot_b": (4.0, [
        "An archer raises a bow in his left hand, pulls an arrow back to his cheek with his right hand, aims and releases, then lowers the bow.",
    ]),
}
cells = []
for name, (dur, prompts) in moves.items():
    for i, p in enumerate(prompts):
        cells.append({"name": f"{name}_v{i + 1}", "prompt": p, "duration": str(dur), "samples": S, "seed": 12345})
json.dump(cells, open(sys.argv[1], "w"), indent=1)
print(len(cells), "cells,", len(cells) * S, "clips")
