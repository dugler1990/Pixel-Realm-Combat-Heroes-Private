# What 374 clips actually showed, and what to do next

Run of 2026-09-27: 190 cells, 380 BVH clips, 14 blocks, all generated on `Kimodo-SOMA-RP-v1`
except the model blocks, which are the comparison itself. Raw BVH only — no retarget, no demon,
no render, so nothing here is contaminated by the bake.

Reels and sheets: `generated/bosses/demon/kimodo_tests/FINAL_20260927/`.
Numbers: `analyze.py` in `kimodo/`, which averages both samples per cell rather than reading the
first one.

---

## 0. The finding that reframes every other finding

**The noise is bigger than most of the effects we were arguing about.**

| source of variation | measured |
|---|---|
| two samples of the *same* cell | median peak gap **79** (mean peak across the run: 204) |
| three seeds, same model, same prompt | spread up to **208** (`SEEDv11_jump`: 111 / 305 / 319) |

A single draw's peak carries roughly ±79, and changing the seed alone moves it by up to 208.
**Any comparison of two variants at one sample each, with a gap under ~80, measured nothing.**

That is how the first model comparison produced a ranking that flipped depending on which sample
was scored, and it is the correct explanation for a good part of the last two weeks: we changed
a setting, saw a different number, and believed the setting caused it.

Everything below is reported against that floor. Where a difference does not clear it, it says
so, because "no effect" is a result worth having.

---

## 1. Prompt wording is the only large effect in the run

| prompt style | mean peak | hip range (m) |
|---|---|---|
| **rewritten, single sentence (V1/V2/V3)** | **314–349** | **0.22–0.26** |
| rewritten, chunked (K1–K5) | 246–287 | 0.16–0.29 |
| old "single clause" | 220 | 0.18 |
| old "heavy / planted" | 199 | 0.13 |
| old "no creature named" | 155 | 0.10 |
| old "drunk / sloppy" — what the graded clips came from | 146 | 0.08 |

The gap between the rewritten singles and the old drunk wording is **~170–200 on peak and 3× on
hip range**. That clears the noise floor, the seed spread, and every other effect measured.

The jumps make it concrete. A real jump reads ~0.383 of hip travel and the collapsed `jumpup2`
read 0.019:

- `P_V2_jump` **0.52** · `P_V3_jump` **0.72** · `P_K5_jump` **0.83** · `P_K1_jump` **0.72**

**Shorter is better.** Single-sentence beats chunked in **55 of 75** head-to-head pairs across
all five actions (73%). The winning form is what NVIDIA's own guidance says: start with
"A person", name one behaviour, and state the return to idle *in the prompt* rather than
enforcing it with machinery.

The one chunked variant that holds up is **K5** (`wind-up. strike. recovers and stands idle`) —
best hip range of any P variant at 0.29 and the highest active fraction at 31%. It is also the
only chunked form that does *not* open with a stance bookend.

## 2. Constraints are why the bodies stopped moving

The fitted anchor suppresses hip travel **at every duration tested, without exception**:

| clip length | no anchor | fitted anchor |
|---|---|---|
| 2s | 0.032 | 0.017 |
| 3s | 0.127 | 0.029 |
| 4s | 0.075 | 0.045 |
| 5s | 0.090 | 0.032 |
| 6s | 0.063 | 0.030 |
| 8s | 0.044 | 0.029 |

Six of six in the same direction, typically halving it. Individually each gap is small; as a
monotone six-point trend it is the second-clearest result in the run.

Peak tells a muddier story — fitted wins at 3s and 4s, loses at 5s, 6s and 8s, all within noise —
so the honest statement is: **anchoring does not reliably change how hard the motion strikes, and
does reliably cost body travel.**

**On the stale-constraint bug (`B1b`):** an 8s clip driven by the 150-frame file scores 210 on
haymaker against 333 unanchored, but 112 against 113 on groundsmash. One clear hit, one nothing.
The *specific* stale-file theory is not confirmed by this block. What is supported is the more
general version — any full-body anchor costs travel — which covers the observed symptom without
needing the file to be the wrong length.

## 3. Chaining does not beat not chaining

| chain form | peak | hip |
|---|---|---|
| C2 long action `.5/4/.5` | 223 | 0.09 |
| **C7 UNCHAINED control** | **177** | **0.09** |
| C4 combat-stance bookends | 165 | 0.10 |
| C+ five chunks | 153 | 0.07 |
| C1 balanced `1/2.5/1` | 137 | 0.07 |
| C5 transition 15 frames | 113 | 0.07 |
| C6 chain + fitted constraint | 106 | 0.05 |
| C3 even `2/2/2` | 99 | 0.04 |

The best chain (C2) is 46 above the unchained control — inside the noise floor. Four of the seven
chain forms score *below* the control, and C3/C5/C6 are 64–78 below it, right at the edge of
significance. `C_chaining` also holds the only 2 DEAD cells in all 190.

I pushed chaining hardest all week as the mechanism that would fix this. It doesn't. What the
chaining block *did* establish is narrower and still useful: if you chain, give the action most
of the time (C2's `.5/4/.5`), and do not split evenly.

Wording inside the chain (`CW`) is also flat: 223 / 168 / 165 / 170 across the four combinations,
a 58-point band inside the noise.

## 4. Things that turned out not to matter

**Model choice — unmeasurable at this sample size.** One seed ranks them RP-v1 163, SEED-v1 139,
RP-v1.1 208, SEED-v1.1 229. Three seeds inside a *single* model span 122 (RP-v1 haymaker:
70/120/192) and 208 (SEED-v1.1 jump: 111/305/319). The between-model differences sit entirely
inside the within-model seed spread. **Pick one and stay on it** — not because it is better, but
because a matrix split across checkpoints answers nothing.

**Guidance — no mode beat another.** Against the correct control (`P_K1`, which is the identical
prompt and split at the default `separated 3.0/2.0`):

| mode | peak |
|---|---|
| regular 3.0 | 367 |
| nocfg | 319 |
| separated 3.0/1.0 | 308 |
| **separated 3.0/2.0 (default)** | **304** |
| separated 3.0/6.0 | 302 |

A 65-point band, inside the noise floor. *Correction: I told you earlier that guidance produced
the highest number in the run and was the parameter we had never varied. That came from one
sample of one cell compared against a control on a different prompt. With both samples and the
matching control, there is no effect. The default is fine.*

**Denoising steps — keep 100.** 50 steps scores 87 against 161 at 100 (worse, outside noise);
250 scores 142 (no better than 100, inside noise). More compute buys nothing.

**Constraint class** — FullBody 248 / Root2D 191 / EndEffector 189 / Hands 168 on peak, all
within ~80 of each other. The hip column mildly favours the looser classes (Root2D 0.10 vs
FullBody 0.06), consistent with §2, but this block alone does not carry it.

---

## Proposed best practice

**Prompting**
1. One sentence. Start with "A person". Name one behaviour. State the idle: *"…, then stands
   idle."* That form is `P_V1`, and it is the whole of §1.
2. A style token (`An angry person`, `An injured person`) is free and mildly positive — `V2` is
   the top variant on jump and slap. Use it.
3. Describe body mechanics rather than character (`V3`: "sweeps their open right hand
   horizontally across their body at shoulder height"). Top variant on groundsmash and damage.
4. Drop the creature vocabulary — "drunk", "obese ogre", "massive clumsy creature". It is the
   worst-scoring wording in the run and it is where our graded clips came from, which is why
   they were never reproducible.
5. Chain only when you need a specific beat, and then use `K5`'s shape — wind-up / strike /
   recover-to-idle, no opening stance bookend, action gets most of the time.

**Settings**
6. **4 seconds.** 2s is too short to contain a wind-up; past 5s nothing improves.
7. **No constraint file for returning to idle** — say it in the prompt. Reserve anchors for when
   a clip genuinely must start and end on a specific pose, and expect to pay body travel for it.
   If you must anchor, fit it to that clip's frame count and prefer Root2D over FullBody.
8. `--diffusion_steps 100`, `cfg_type separated 3.0 2.0`, `Kimodo-SOMA-RP-v1`. None of these are
   worth tuning further; all three were tested and none of the alternatives won.

**Process — the change that matters most**
9. **Three samples minimum per prompt, and judge by eye, not by peak.** One draw carries ±79 and
   a seed change moves it up to 208. A single-sample comparison between two settings is not
   evidence. This is the rule that would have saved the most time this week.
10. Peak and hip range rank *candidates for viewing*; they do not decide quality. A high peak can
    be a snap or a jitter. The sheet narrows 40 cells to 5; the reel picks the winner; the grade
    goes in `generated/bosses/demon/APPROVED.json` with your verbatim words.
11. Generate one clip and score it before launching a batch.

## What this run did not settle

- **hand excursion** still is not measured — BVH carries position channels for the root only, so
  it needs forward kinematics through Blender. It is the metric most likely to catch "the arm
  never actually goes anywhere", which is the failure mode behind `slap`.
- **`slap` has never worked** in any block, on any wording, at any length. It is the one action
  with no reference clip, and it needs to be treated as an open problem rather than a cell.
- **Nothing here has been retargeted.** Every conclusion is about generation. The demon bake has
  its own failure modes — `BIND_MATCH`, `IDLE_POSE`, `ARM_ELEV_CAP`, `ROOT_LOC` — and those are
  in `NOTES_retarget_kimodo.md`, unaffected by any of this.
