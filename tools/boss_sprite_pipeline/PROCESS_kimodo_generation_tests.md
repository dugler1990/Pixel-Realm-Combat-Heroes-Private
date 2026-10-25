# Testing Kimodo generation settings

How to find out which generation settings produce motion worth using, by measuring raw BVH
before anything is retargeted or rendered. Written 2026-09-27; the current run is the first.

## Why this exists

Our attack clips went from usable to limp and nobody could say why. Every theory — constraint
weight, clip duration, prompt wording — was argued from aggregate numbers and each one turned
out wrong or partly wrong. Retargeting and rendering sit between generation and the eye, so a
bad clip and a bad bake look the same. This tests **generation alone**.

## Rules

1. **Raw BVH only.** No retarget, no demon, no render. Those are separate failures.
2. **One variable per cell.** Fixed `--seed` throughout, so cells are comparable and nothing
   carries seed noise.
3. **Anchor every metric to a clip Douglas has graded.** "Bad" means worse than something he
   called good, not worse than my expectation.
4. **Generate one clip and score it before launching a batch.** Every wasted hour so far came
   from skipping this.
5. **No dots in output paths.** See `NOTES_kimodo_api.md` — `--output` silently overwrites a
   different cell.

## Actions

Five, each with a known reference so a bad score means "we broke it" rather than "it was always
like that". Prompts are the originals that produced the graded clips, recovered from the session
transcript — not rewrites.

| tag | reference |
|---|---|
| `haymaker` | Douglas: "ok actually awesome" — our best-rated output |
| `groundsmash` | the largest measured regression, 76.1 → 27.9 energy between batches |
| `jump` | cleanest metric: hip range 0.383 real vs 0.019 collapsed |
| `damage` | kept — "could be a taking damage animation" |
| `slap` | never worked — "little weird movements with the hand". No baseline; needs several phrasings |

## Metrics, straight off the BVH

- **hip range** — height the hips travel. A jump prompt that does not leave the ground reads
  ~0.02 against ~0.38 for a real one. The clearest single discriminator.
- **peak** — most total degrees moved in one frame. An attack needs one. Limp clips sit near 90;
  the clips Douglas rated sit at 180–410.
- **active %** — fraction of frames above a quarter of peak. Separates "brief action in a long
  clip" from "moves throughout".
- **hand excursion** — how far the wrists travel from the hips. *Not yet working*: BVH stores
  position channels for the root only, so this needs forward kinematics through Blender.

## Blocks

| block | varies | why |
|---|---|---|
| **M** models | RP-v1 / RP-v1.1 / SEED-v1 / SEED-v1.1 | runs first — no sense tuning a superseded checkpoint |
| **B0** replication | graded clips on their original settings | if a known-good result will not reproduce, every other cell is noise |
| **B1** duration × anchor | 2/3/4/5/6/8s × {none, anchor fitted to that frame count} | six points, so you see where it falls off instead of inferring from two |
| **B1b** the bug | 8s clip driven by a 150-frame constraint | reproduces the suspected failure deliberately |
| **C** chaining | chunk counts and splits, stance vs idle bookends, transition frames, unchained control | Kimodo's native idle → action → idle |
| **N** constraint class | FullBody / Root2D / EndEffector | we had only ever used FullBody, which pins all 77 joints |
| **G** guidance | nocfg / regular / separated 2.0 / separated 6.0 | never tested beyond one setting |
| **W** wording | drunk-sloppy vs heavy-planted vs single-clause vs no-creature | the graded clips came from the drunk wording; the limp batch from the rewrite |
| **O** one-offs | `--no-postprocess`, transition frames, `--bvh_standard_tpose`, `--diffusion_steps` | defaults we had never questioned |

Two samples per cell, fixed seed. ~220 clips, ~35 s each.

## Running it

Every script lives in `kimodo/`, in this repo, not on the pod — the pod is destroyed after a
run and the tooling used to go with it. `kimodo/README.md` is the how-to for using this on any
animation set, not just these tests.

```
kimodo/mkcells.py      every cell as one cells.json - the plan and the run cannot drift apart
kimodo/driver.py       generates all of it with the model loaded ONCE
kimodo/build_cons.py   constraint files per duration, from one generated idle clip
kimodo/score_all.py    scores every cell, grouped by category, no Blender needed
kimodo/final_pass.sh   every category -> its own contact sheet and labelled reel
```

`driver.py` replaced the per-cell `kimodo_gen` shell loops. The CLI reloads an 8B text encoder
on every invocation: **~75 s of loading for ~5 s of generation**, and 65 cells cost 87 minutes
almost entirely in reloads. Loading once took the whole 130-cell matrix to **9 s/cell, 94 cells
in 13 minutes** — the same work the shell loops would have spent six hours on.

Two costs come with calling the model directly instead of through the CLI, both of them the same
mistake in different clothes — `kimodo/scripts/generate.py` does work *after* generation that a
driver has to reproduce:

- the BVH export needs `model.skeleton.somaskel77`, not `model.skeleton` (30 joints);
- `cfg_type="regular"` takes one float where `separated` takes two, and the CLI unwraps the
  single-element list for you.

Both are in `NOTES_kimodo_api.md`. **Diff a new driver against the CLI's source before blaming
the model for what it produces.**

**One model per matrix.** Cells generated on different checkpoints cannot be compared with each
other, and a matrix half on one and half on another answers no question at all. This run is
entirely `Kimodo-SOMA-RP-v1`; four cells made on SEED-v1.1 were deleted and regenerated rather
than left in.

Cells are skipped if they already contain BVH, so an interrupted run resumes by relaunching, and
a fix plus a relaunch sweeps up only what failed. Editing a script does not change the copy
already running — kill and relaunch.

## Outputs

Three views of the same cells, because a table hides motion and a video hides comparison:

| what | where | for |
|---|---|---|
| scores table | `score_raw.py <dir>` | sorting and thresholds |
| contact sheet | `block_report.py` → `SHEET.png` | one numbered row per cell, 8 frames, scores in the margin — scan 20 cells in one image |
| labelled reel | `cell_reel.py` + `block_reel.py` | every cell back to back, name and scores burned into each frame |

Row numbers match between sheet and reel, so feedback can be "4 good, 9 dead" without naming
files. Record verdicts in `generated/bosses/demon/APPROVED.json` as they are given — clip name,
verbatim words, date, and the run that produced it.

## What this run cost, and why

Four chained cells failed in a row with `einsum(): subscript N has size 77 ... size 30`. It was
diagnosed as a limit on chained prompts, then as a limit on SEED-v1.1, and neither was true: the
driver was handing the 77-joint output to the 30-joint skeleton on export. Two things made it
look like a generation problem and both are worth remembering:

- the failure is in **export**, after generation succeeds and after the output directory is
  created. A cell whose directory exists but holds no BVH failed *writing*, not generating.
- the four failures were the first four cells the driver actually reached — everything before
  them was skipped as already done. **Consecutive failures at the start of a run are evidence
  about the runner, not about the cells.**

One CLI call of the same prompt on both models would have settled it in two minutes. Run that
before theorising.

## Current run

130 cells on `Kimodo-SOMA-RP-v1`, two samples each, fixed seed; generation complete.

Block **P** — prompts rewritten to NVIDIA's guidelines — is the strongest result so far: 36 of
40 cells register as real motion, and the jumps clear the graded reference by a wide margin
(`P_K5_jump` 0.83, `P_V3_jump` 0.72, `P_K1_jump` 0.72 hip range, against **0.383** for a real
jump and **0.019** for the collapsed one). The four weak cells are all `damage`, the one action
whose description is genuinely small. Block **W** shows single-clause wording holds up
(`W_single_jump` 0.55) where the slap stays weak on every phrasing, as it always has.

Block M found RP-v1 ahead of SEED-v1 on jump (peak 250 vs 159) and groundsmash (127 vs 122).
Block C shows chaining reproduces idle → action → idle natively, and a five-chunk chain naming an
explicit wind-up beat the unchained control (157 vs 131) while three-chunk splits roughly halved
the strike.
