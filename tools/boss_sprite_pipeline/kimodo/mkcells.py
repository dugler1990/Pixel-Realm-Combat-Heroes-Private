"""Emit every remaining test cell as JSON for driver.py.

One place, so the plan and the run cannot drift apart the way the bash scripts did.
"""
import json

ORIG = {
 "haymaker": "A huge fat drunk brute throws a wild haymaker punch, swinging his whole heavy body around and stumbling off balance.",
 "groundsmash": "A huge drunken brute raises both arms high and slams them down into the ground, its whole body lurching after the blow.",
 "jump": "A massive clumsy creature crouches then launches itself upward off both legs, flailing, and crashes back down off balance.",
 "damage": "A huge fat drunk brute takes a hard hit to the chest, staggering backwards and nearly falling over.",
 "slap": "A massive obese ogre swings a giant open hand in a sloppy violent sideways slap, his whole bulk lurching after it.",
}
HEAVY = {
 "haymaker": "A giant gorilla loads all its weight onto its right side, then swings one massive arm in a single wide bear swipe across to the left, following through with its whole body.",
 "groundsmash": "A giant gorilla raises both fists high above its head and smashes them straight down into the ground with enormous force, staying planted and heavy.",
 "jump": "A huge heavy monster crouches deep then explodes upward off both legs as high as it can, hangs at the top, and crashes back down.",
 "damage": "A massive heavy creature is struck in the chest and steps back, absorbing the impact.",
 "slap": "A huge heavy creature swings one open hand across in a single clear sideways slap, arm fully extended away from its body.",
}
SINGLE = {
 "haymaker": "A huge brute throws a haymaker punch.",
 "groundsmash": "A huge brute slams both arms into the ground.",
 "jump": "A huge brute jumps as high as it can.",
 "damage": "A huge brute is hit and staggers back.",
 "slap": "A huge brute slaps sideways with an open hand.",
}
NOCRE = {
 "haymaker": "A big heavy man throws a wild haymaker punch, swinging his whole body around and stumbling off balance.",
 "groundsmash": "A big heavy man raises both arms high and slams them down into the ground, lurching after the blow.",
 "jump": "A big heavy man crouches then launches himself upward off both legs, flailing, and crashes back down.",
 "damage": "A big heavy man takes a hard hit to the chest, staggering backwards and nearly falling over.",
 "slap": "A big heavy man swings an open hand in a violent sideways slap, his bulk lurching after it.",
}
V1 = {
 "haymaker": "A person throws a heavy punch with their right arm, then stands idle.",
 "groundsmash": "A person slams both fists down onto the ground, then stands idle.",
 "jump": "A person jumps straight up as high as they can, then lands and stands idle.",
 "damage": "A person is struck in the chest and staggers backward, then stands idle.",
 "slap": "A person swings their open right hand sideways in a wide slap, then stands idle.",
}
V2 = {
 "haymaker": "An angry person throws a heavy punch with their right arm, then stands idle.",
 "groundsmash": "An angry person slams both fists down onto the ground, then stands idle.",
 "jump": "An angry person jumps straight up as high as they can, then lands and stands idle.",
 "damage": "An injured person is struck in the chest and staggers backward, then stands idle.",
 "slap": "An angry person swings their open right hand sideways in a wide slap, then stands idle.",
}
V3 = {
 "haymaker": "A person swings their right arm forcefully across their body at chest height, then stands idle.",
 "groundsmash": "A person raises both arms overhead and strikes downward heavily onto the ground, then stands idle.",
 "jump": "A person crouches deeply and jumps powerfully straight upward, then lands and stands idle.",
 "damage": "A person recoils sharply backward from a heavy impact to their chest, catching themselves on their right leg, then stands idle.",
 "slap": "A person sweeps their open right hand horizontally across their body at shoulder height, then stands idle.",
}
WIND = {
 "haymaker": "A person winds up, shifting their weight onto their right leg.",
 "groundsmash": "A person raises both arms high above their head.",
 "jump": "A person crouches deeply with both knees bent.",
 "damage": "A person braces themselves in a combat stance.",
 "slap": "A person twists their torso to the right, drawing their arm back.",
}
STRIKE = {
 "haymaker": "A person throws a heavy punch with their right arm.",
 "groundsmash": "A person slams both fists down onto the ground.",
 "jump": "A person jumps straight up as high as they can.",
 "damage": "A person is struck in the chest and staggers backward.",
 "slap": "A person swings their open right hand sideways in a wide slap.",
}
STANCE = "A person stands still in a combat stance."
RECOVER = "A person recovers their balance."
RECIDLE = "A person recovers their balance and stands idle."
C = "/workspace/cons"
cells = []


def add(name, prompt, duration, **kw):
    c = {"name": name, "prompt": prompt, "duration": duration}
    c.update(kw)
    cells.append(c)


ACTS = ["haymaker", "groundsmash", "jump", "damage", "slap"]
THREE = ["haymaker", "groundsmash", "jump"]
TWO = ["haymaker", "groundsmash"]

# P - the rewritten prompts, single and chunked
for a in ACTS:
    add("P_V1_" + a, V1[a], "4.0")
    add("P_V2_" + a, V2[a], "4.0")
    add("P_V3_" + a, V3[a], "4.0")
    add("P_K1_" + a, "%s %s %s" % (STANCE, STRIKE[a], STANCE), "1.0 2.5 1.0")
    add("P_K2_" + a, "%s %s %s" % (STANCE, STRIKE[a], STANCE), "1.0 4.0 1.0")
    add("P_K3_" + a, "%s %s %s %s %s" % (STANCE, WIND[a], STRIKE[a], RECOVER, STANCE),
        "1.0 1.0 2.0 1.0 1.0")
    add("P_K4_" + a, "%s %s %s %s %s" % (
        STANCE, WIND[a], STRIKE[a].replace("A person", "An angry person", 1), RECOVER, STANCE),
        "1.0 1.0 2.0 1.0 1.0")
    add("P_K5_" + a, "%s %s %s" % (WIND[a], STRIKE[a], RECIDLE), "1.0 2.0 1.5")

# W - wording sweep
for a in ACTS:
    add("W_heavy_" + a, HEAVY[a], "4.0")
    add("W_single_" + a, SINGLE[a], "4.0")
    add("W_nocre_" + a, NOCRE[a], "4.0")

# B1 - duration sweep, unanchored vs anchor fitted to the clip's own frame count
for a in TWO:
    for d in (2, 3, 4, 5, 6, 8):
        add("B1_none_%ds_%s" % (d, a), ORIG[a], "%d.0" % d)
        add("B1_fit_%ds_%s" % (d, a), ORIG[a], "%d.0" % d,
            constraints="%s/full_%d.json" % (C, d * 30))
    add("B1b_stale_8s_" + a, ORIG[a], "8.0", constraints="%s/full_150.json" % C)

# N - constraint class. We only ever used FullBody, which pins all 77 joints.
for a in THREE:
    add("N1_full_" + a, ORIG[a], "4.0", constraints="%s/full_120.json" % C)
    add("N2_root2d_" + a, ORIG[a], "4.0", constraints="%s/root2d_120.json" % C)
    add("N3_endeff_" + a, ORIG[a], "4.0", constraints="%s/endeff_120.json" % C)
    add("N4_hands_" + a, ORIG[a], "4.0", constraints="%s/hands_120.json" % C)

# C - chaining on the old wording, CW - chaining x wording
for a in THREE:
    ready = "A huge heavy brute stands ready. %s It returns to standing." % ORIG[a]
    add("C1_bal_" + a, ready, "1.0 2.5 1.0")
    add("C2_longact_" + a, ready, "1.0 4.0 1.0")
    add("C3_even_" + a, ready, "2.0 2.0 2.0")
    add("C5_trans_" + a, ready, "1.0 2.5 1.0", transition=15)
    add("C7_nochain_" + a, ORIG[a], "4.5")
    add("Cp_5chunk_" + a,
        "A huge heavy brute stands ready. It winds up. %s It recovers. It stands ready again." % ORIG[a],
        "1.0 1.0 2.0 1.0 1.0")
    add("CW_heavy_" + a, "A huge heavy brute stands ready. %s It returns to standing." % HEAVY[a],
        "1.0 2.5 1.0")

# G - guidance mode, measured on a chained prompt
for a in TWO:
    ready = "%s %s %s" % (STANCE, STRIKE[a], STANCE)
    add("G_nocfg_" + a, ready, "1.0 2.5 1.0", cfg_type="nocfg")
    add("G_regular_" + a, ready, "1.0 2.5 1.0", cfg_type="regular", cfg_weight=[3.0])
    add("G_sep6_" + a, ready, "1.0 2.5 1.0", cfg_weight=[3.0, 6.0])
    add("G_sep1_" + a, ready, "1.0 2.5 1.0", cfg_weight=[3.0, 1.0])

# O - one-offs: defaults we had never questioned
for a in TWO:
    add("O_nopost_" + a, ORIG[a], "4.0", no_post=True)
    add("O_tpose_" + a, ORIG[a], "4.0", tpose=True)
    add("O_steps250_" + a, ORIG[a], "4.0", steps=250)
    add("O_steps50_" + a, ORIG[a], "4.0", steps=50)

json.dump(cells, open("/workspace/cells.json", "w"), indent=1)
print("cells:", len(cells), " clips:", len(cells) * 2)
