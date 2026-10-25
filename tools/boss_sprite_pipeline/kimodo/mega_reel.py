"""All fourteen category reels into one, with the experiment named and explained on every frame.

    mega_reel.py <reels_dir> <out.mp4> [fps]

The per-cell labels are already burned into the source frames by cell_reel.py; this adds the
layer above them - which experiment you are watching and what question it asks - because a reel
of 190 cells is unreadable if you have to remember which block you are in.
"""
import os
import sys

import cv2

SRC, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
FPS = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
SCALE, FOOT = 1.5, 118
F = cv2.FONT_HERSHEY_SIMPLEX

# P first: it is the block that answers the question the others were asked to explain.
ORDER = [
    ("P_prompts", "P - your rewritten prompts",
     ["3 single-sentence variants (V1-V3) + 5 chunked (K1-K5), all 5 actions.",
      "Written to NVIDIA's guidelines: \"A person\", one behaviour, idle stated in the prompt."]),
    ("M_models", "M - which checkpoint",
     ["RP-v1 / RP-v1.1 / SEED-v1 / SEED-v1.1, same prompt and seed.",
      "Runs first: no sense tuning a superseded model."]),
    ("M3_model_seeds", "M3 - the same comparison, 3 seeds",
     ["The first pass ranked models on two samples and the ranking flipped.",
      "Three seeds so the spread is visible rather than hidden."]),
    ("Mplus_steps", "M+ - denoising steps",
     ["100 vs 250 steps. Does more compute buy motion, or just time?", ""]),
    ("B0_baseline", "B0 - replication",
     ["The clips Douglas graded, regenerated on their original settings.",
      "If a known-good result will not reproduce, every other cell is noise."]),
    ("B1_duration", "B1 - clip length x anchor",
     ["2/3/4/5/6/8 seconds, each with no anchor and with one fitted to its own frame count.",
      "Six points, so you see where it falls off instead of inferring from two."]),
    ("B1b_bug", "B1b - the suspected bug, on purpose",
     ["An 8-second clip driven by the 150-frame constraint file.",
      "frame_indices are absolute: a file built for 150 frames pins the wrong frames."]),
    ("C_chaining", "C - prompt chaining",
     ["idle -> action -> idle as separate sentences, with different time splits.",
      "C1 balanced, C2 long action, C3 even, C4 combat stance, C5 blended, C7 unchained control."]),
    ("Cplus_depth", "C+ - chain depth",
     ["Five chunks instead of three, naming an explicit wind-up and recovery beat.", ""]),
    ("CW_chain_wording", "CW - chaining x wording",
     ["Drunk-sloppy vs heavy-planted phrasing inside the two best chain splits.",
      "The wording may behave differently once the prompt is chunked."]),
    ("N_constraints", "N - constraint class",
     ["FullBody pins all 77 joints; Root2D, EndEffector and Hands are progressively looser.",
      "We had only ever used FullBody."]),
    ("G_guidance", "G - guidance",
     ["nocfg / regular 3.0 / separated 3.0+2.0 / separated 3.0+6.0.",
      "Measured on a chained prompt, where we would actually use it."]),
    ("W_wording", "W - wording sweep",
     ["Drunk-sloppy vs heavy-planted vs single-clause vs no creature named.",
      "The graded clips came from the drunk wording; the limp batch from a rewrite."]),
    ("O_oneoffs", "O - defaults never questioned",
     ["Post-processing off, and T-pose rest pose on export.", ""]),
]


def band(canvas, w, h, title, lines, idx, n, cells):
    cv2.rectangle(canvas, (0, h), (w, h + FOOT), (26, 26, 32), -1)
    cv2.line(canvas, (0, h), (w, h), (70, 225, 255), 2)
    cv2.putText(canvas, title, (15, h + 34), F, 0.72, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(canvas, title, (14, h + 33), F, 0.72, (70, 225, 255), 2, cv2.LINE_AA)
    tag = "block %d of %d   %d cells" % (idx, n, cells)
    tw = cv2.getTextSize(tag, F, 0.5, 1)[0][0]
    cv2.putText(canvas, tag, (w - tw - 15, h + 32), F, 0.5, (150, 150, 165), 1, cv2.LINE_AA)
    for i, ln in enumerate([x for x in lines if x]):
        cv2.putText(canvas, ln, (15, h + 62 + i * 24), F, 0.46, (215, 215, 225), 1, cv2.LINE_AA)


first = cv2.VideoCapture(os.path.join(SRC, ORDER[0][0] + ".mp4"))
ok, fr = first.read()
first.release()
h0, w0 = fr.shape[:2]
W, H = int(w0 * SCALE), int(h0 * SCALE)
vw = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H + FOOT))

total = 0
for idx, (tag, title, lines) in enumerate(ORDER, 1):
    p = os.path.join(SRC, tag + ".mp4")
    if not os.path.exists(p):
        print("MISSING", p, flush=True)
        continue
    cells = 0
    cap = cv2.VideoCapture(p)
    n = 0
    prev = None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        big = cv2.resize(fr, (W, H), interpolation=cv2.INTER_CUBIC)
        canvas = cv2.copyMakeBorder(big, 0, FOOT, 0, 0, cv2.BORDER_CONSTANT, value=(26, 26, 32))
        # the cell name sits in the source frame's own header; count changes to report cells
        strip = fr[0:18, 0:260].tobytes()
        if strip != prev:
            cells += 1
            prev = strip
        band(canvas, W, H, title, lines, idx, len(ORDER), cells)
        vw.write(canvas)
        n += 1
    cap.release()
    total += n
    print("  %-2d %-20s %4d frames" % (idx, tag, n), flush=True)
vw.release()
print("MEGA_REEL", OUT, total, "frames", "%dx%d" % (W, H + FOOT), flush=True)
