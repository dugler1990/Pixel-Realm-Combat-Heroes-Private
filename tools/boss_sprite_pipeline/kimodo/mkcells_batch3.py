"""Batch 3: the barb's martial arts, jumps, rolls, evades and particular weapon strikes; the ice wizard's spells,
gestures, hits and deaths (a thin robed man). Single sentences, back to a ready stance, 3 samples."""
import json
import sys

S = 3
B = "A big strong man"
WZ = "A thin man in long robes"
moves = {
    # barb: martial arts
    "ma_backfist": f"{B} in a fighting stance spins and throws a spinning backfist, then returns to his guard.",
    "ma_side_kick": f"{B} in a fighting stance throws a powerful side kick to the front, then returns to his guard.",
    "ma_axe_kick": f"{B} raises his right leg high and brings his heel straight down in an axe kick, then returns to his guard.",
    "ma_palm_strike": f"{B} steps forward and drives an open palm strike forward with his right hand, then returns to his guard.",
    "ma_shoulder_throw": f"{B} grabs an enemy in front of him, turns and throws him over his shoulder, then stands ready.",
    "ma_headbutt": f"{B} grabs an enemy by the shoulders and slams a headbutt forward, then steps back to a ready stance.",
    "ma_combo": f"{B} throws a jab, a cross, a hook, then a spinning heel kick, and returns to his guard.",
    # barb: jumps, rolls, evades
    "jump_up": f"{B} crouches and jumps straight up as high as he can, then lands and stands ready.",
    "jump_long": f"{B} runs two steps and makes a long jump forward, landing on both feet, then stands ready.",
    "jump_attack": f"{B} jumps high and comes down swinging both fists into the ground in front of him.",
    "roll_back": f"{B} rolls backward on the ground and comes back up into a ready stance.",
    "roll_side": f"{B} dives and rolls to his left side and comes back up into a ready stance.",
    "evade_duck": f"{B} ducks low under a swing and comes back up into a ready stance.",
    "evade_lean": f"{B} leans back quickly to dodge a blow at his head, then returns to a ready stance.",
    "evade_dive": f"{B} dives sideways to the ground to avoid an attack, then gets up quickly.",
    "climb_vault": f"{B} runs forward and vaults over a low obstacle with one hand, then keeps running.",
    # barb: particular weapon strikes
    "w_axe_sweep": f"{B} holding a heavy axe in both hands swings it in a wide low sweep at knee height, then returns to a ready stance.",
    "w_hammer_spin": f"{B} holding a war hammer spins around once with the hammer out and strikes, then returns to a ready stance.",
    "w_flail": f"{B} swings a flail in a circle above his head and whips it down in front of him, then returns to a ready stance.",
    "w_spear_throw": f"{B} pulls a spear back over his right shoulder and throws it forward with force, then stands ready.",
    "w_twin_daggers": f"{B} holding a dagger in each hand stabs forward with both in quick alternation, then returns to a ready stance.",
    "w_sword_uppercut": f"{B} holding a sword low in his right hand slashes it upward in a rising cut, then returns to a ready stance.",
    "w_sword_spin": f"{B} holding a sword spins all the way around with a horizontal slash, then returns to a ready stance.",
    "w_shield_charge": f"{B} with a shield on his left arm charges forward three steps shield first, then stops in a ready stance.",
    # wizard: base moves
    "wz_idle": f"{WZ} stands still with his hands loosely clasped in front of him, breathing calmly.",
    "wz_walk": f"{WZ} walks forward at a calm steady pace.",
    "wz_run": f"{WZ} runs forward, his arms close to his body.",
    # wizard: spells and hand movements
    "wz_cast_throw": f"{WZ} draws his right hand back and throws a ball of magic forward from his palm, then returns to standing.",
    "wz_cast_beam": f"{WZ} pushes both hands forward and holds them there, channeling a beam of magic, then lowers them.",
    "wz_cast_summon": f"{WZ} raises both arms slowly above his head, then sweeps them down toward the ground to summon something.",
    "wz_cast_shield": f"{WZ} crosses his arms in front of his chest and spreads them outward to raise a magic shield.",
    "wz_cast_point": f"{WZ} points his right index finger forward sharply to cast a quick spell, then lowers his hand.",
    "wz_gesture": f"{WZ} weaves his hands in front of his chest in slow circular gestures, gathering magic.",
    "wz_staff_slam": f"{WZ} holding a staff in both hands raises it and slams its end into the ground, then stands.",
    "wz_wand_flick": f"{WZ} flicks a wand in his right hand forward twice, then lowers it.",
    # both: damage and dying
    "wz_hit": f"{WZ} is hit in the chest by a blast, staggers backward, then recovers.",
    "wz_knockdown": f"{WZ} is blown off his feet, falls onto his back, then gets back up.",
    "wz_death": f"{WZ} is fatally struck, clutches his chest, falls to his knees and collapses face down.",
    "barb_death_back": f"{B} is fatally wounded, staggers back and falls flat on his back and lies still.",
    "barb_hit_heavy": f"{B} takes a heavy blow to the side, stumbles sideways, then recovers to a ready stance.",
}
dur = {"idle": 4.0, "walk": 3.0, "run": 2.5, "death": 3.5, "knockdown": 3.0, "combo": 3.0, "gesture": 3.0}
cells = []
for name, p in moves.items():
    d = next((v for k, v in dur.items() if k in name), 2.0)
    cells.append({"name": name, "prompt": p, "duration": str(d), "samples": S, "seed": 34567})
json.dump(cells, open(sys.argv[1], "w"), indent=1)
print(len(cells), "cells,", len(cells) * S, "clips")
