# Kimodo generation, end to end

Everything needed to generate a set of animations with Kimodo and see whether they are any
good, without a pod-side state that dies with the pod. Pulled out of the 2026-09-27 run, which
generated 380 clips across 190 cells.

## The speed fact, because it decides the whole design

`kimodo_gen` reloads an 8B text encoder on every invocation: **~75–105 s of loading for ~5 s of
generation.** A shell loop over the CLI therefore costs ~80 s per cell almost entirely in
reloads — 65 cells took 87 minutes that way.

`driver.py` loads the model **once** and iterates a list of cells:

| | CLI loop | `driver.py` |
|---|---|---|
| per cell | ~80 s | **9–12 s** |
| 94 cells | ~2 h 5 m | **13 min** |
| model load | once per cell | once per run, ~105 s |

Use the CLI for a single clip or to isolate a bug. Use the driver for anything with more than
about five cells. **One model per driver run** — it holds one loaded model, and cells generated
on different checkpoints cannot be compared with each other anyway.

## Generating any animation set

1. **Write the cells.** One JSON list, one object per cell. This is the single source of truth —
   keep prompts in one file and derive the list from it (`mkcells.py`), never a second copy in a
   shell script. The plan and the run drifted apart the first time exactly that way.

   ```json
   {"name": "bigpunch_chain", "prompt": "A person stands still in a combat stance. A person
    throws a heavy punch with their right arm. A person stands still in a combat stance.",
    "duration": "1.0 2.5 1.0", "samples": 2, "seed": 12345}
   ```

   Optional keys: `constraints` (path to a constraint file), `cfg_type` (`separated` default /
   `regular` / `nocfg`), `cfg_weight`, `steps` (default 100), `transition` (default 5),
   `no_post`, `tpose`.

   Prompts split on `.` — each sentence is a chunk, and a multi-value `duration` must have one
   value per chunk.

2. **Constraint files, if you want them.** `build_cons.py <idle.npz>` builds one per clip
   length; `build_cons2.py` adds the looser classes. `frame_indices` are absolute, so a file
   built for 150 frames pins the wrong frames in a 240-frame clip — this is a real failure we
   reproduced deliberately as block `B1b`, and it is the likeliest cause of a batch going limp.

3. **Generate.**
   ```
   python driver.py cells.json Kimodo-SOMA-RP-v1
   ```
   Cells that already hold a BVH are skipped, so an interrupted run resumes by relaunching, and
   fixing one broken cell and relaunching sweeps up only that cell.

4. **Pull the BVH** (`tar --exclude='*.npz' -czf runs.tgz runs`) and render locally.

## Seeing whether it worked

Three views of the same cells, because a table hides motion and a video hides comparison:

```
score_all.py  <runs_dir> <out.csv>              scores every cell, grouped, no Blender needed
make_block.sh <tag> <name-regex>                one category -> sheet + labelled reel
final_pass.sh                                   every category in one go
```

`make_block.sh` runs `block_report.py` (contact sheet: one numbered row per cell, 8 frames
across the clip, hip/peak/verdict in the margin) and `cell_reel.py` + `block_reel.py` (reel with
the cell name, its parameters, its prompt and its scores burned into **every** frame). Row
numbers match between sheet and reel, so feedback is "row 4 good, row 9 dead" without naming
files. Labels come from `manifest_from_cells.py`, which builds them from the same cells JSON the
driver ran — a reel of unlabelled stick figures is unreviewable.

Blender needs Pillow, which it does not ship. Install it where Blender actually looks:
`%APPDATA%/Blender Foundation/Blender/<ver>/scripts/addons/modules/`. Under
`blender -b --python x.py -- a b c`, `sys.argv[1]` is Blender's own flag, so read after `--`.

## Metrics

- **hip range**, metres. The BVH is written in **centimetres** — divide by 100 before comparing
  to any threshold. A jump that never leaves the ground reads ~0.02 against ~0.38 for a real one.
- **peak**, most total degrees moved in one frame. Limp clips sit near 90; rated clips 180–410.
- **active %**, fraction of frames above a quarter of peak.
- **hand excursion** — not working. BVH stores position channels for the root only, so this
  needs forward kinematics through Blender.

## The two traps that cost a day

Both are the same mistake: calling the model directly means reproducing what
`kimodo/scripts/generate.py` does *after* generation.

- the BVH export needs `model.skeleton.somaskel77`, **not** `model.skeleton` (30 joints).
  Getting this wrong raises `einsum(): subscript N has size 77 ... size 30` — those are the two
  skeletons, not frames, not chunks;
- `cfg_type="regular"` takes **one** float where `separated` takes two, and the CLI unwraps the
  single-element list for you.

Both fail *after* generation succeeds and after the output directory is created, so they read as
"this prompt breaks the model". **A cell whose directory exists but holds no BVH failed writing,
not generating.** Full account in `../NOTES_kimodo_api.md`.
