"""Second batch for the barb: more weapons, defence, reactions, magic, more boxing / kickboxing. Same rules as
mkcells_barb.py: single sentences, return to a ready stance, 3 samples."""
import json
import sys

S = 3
moves = {
    "spear_thrust": (2.0, ["A warrior holding a spear with both hands thrusts it straight forward with a step, then pulls it back to a ready stance."]),
    "spear_sweep": (2.5, ["A warrior holding a long spear with both hands sweeps it in a wide low arc in front of him, then returns to a ready stance."]),
    "dagger_stab": (1.5, ["A man holding a dagger in his right hand stabs quickly forward twice, then returns to a ready stance."]),
    "mace_swing": (2.0, ["A warrior holding a heavy mace in his right hand swings it in a big overhead arc down in front of him, then returns to a ready stance."]),
    "staff_spin": (3.0, ["A fighter holding a long staff with both hands spins it in front of him and strikes forward with one end, then returns to a ready stance."]),
    "dual_slash": (2.5, ["A warrior holding a sword in each hand slashes with the right sword and then the left sword in quick succession, then returns to a ready stance."]),
    "shield_block": (2.0, ["A warrior raises a shield on his left arm in front of his body to block a blow, braces, then lowers it to a ready stance."]),
    "shield_bash": (2.0, ["A warrior steps forward and slams a shield on his left arm into an enemy in front of him, then returns to a ready stance."]),
    "dodge_roll": (2.0, ["A big man dives into a forward roll on the ground and comes back up into a ready stance."]),
    "sidestep": (1.5, ["A fighter quickly sidesteps to his left to dodge an attack, then returns to a ready stance."]),
    "backstep": (1.5, ["A fighter hops quickly backward to dodge an attack, then stands ready."]),
    "hit_react": (1.5, [
        "A big man is hit hard in the chest, staggers back two steps, then recovers to a ready stance.",
        "A warrior is struck on the head from the side, his head and body jerk to the side, then he recovers.",
    ]),
    "knockdown": (3.0, ["A big man is knocked off his feet, falls onto his back on the ground, then gets back up."]),
    "death": (3.0, ["A big warrior is fatally wounded, drops to his knees and falls face down on the ground and lies still."]),
    "cast_push": (2.0, ["A man thrusts both open hands forward to cast a powerful spell, then returns to a ready stance."]),
    "cast_overhead": (2.5, ["A man raises both hands above his head gathering energy, then slams them down to cast a spell at the ground."]),
    "roar": (2.5, ["A huge barbarian spreads his arms wide, leans forward and roars at his enemies, then returns to a ready stance."]),
    "ground_pound": (2.5, ["A huge barbarian raises both fists high and pounds them into the ground in front of him, then stands up."]),
    "grab_throw": (3.0, ["A big man grabs an enemy in front of him with both hands, lifts him and throws him to the side, then returns to a ready stance."]),
    "jab_cross_v2": (2.0, ["A boxer bobs slightly and fires a quick jab and a strong cross, then returns to his guard."]),
    "body_hook": (1.5, ["A boxer dips and throws a left hook to the body, then returns to his guard."]),
    "slip_counter": (2.0, ["A boxer slips his head to the side to dodge a punch and counters with a right hook, then returns to his guard."]),
    "low_kick": (1.5, ["A kickboxer throws a low right roundhouse kick to the thigh, then returns to his guard."]),
    "spinning_kick": (2.5, ["A martial artist spins around and throws a spinning back kick, then returns to his guard."]),
    "flying_knee": (2.0, ["A fighter jumps forward and drives a flying knee up into an enemy, then lands in his guard."]),
    "teep_combo": (2.5, ["A kickboxer pushes forward with a front kick, follows with a right cross and a left hook, then returns to his guard."]),
    "elbow": (1.5, ["A fighter steps in and throws a horizontal right elbow strike, then returns to his guard."]),
    "victory": (3.0, ["A big barbarian raises his fist in the air in victory and beats his chest."]),
}
cells = []
for name, (dur, prompts) in moves.items():
    for i, p in enumerate(prompts):
        cells.append({"name": f"{name}_v{i + 1}", "prompt": p, "duration": str(dur), "samples": S, "seed": 23456})
json.dump(cells, open(sys.argv[1], "w"), indent=1)
print(len(cells), "cells,", len(cells) * S, "clips")
