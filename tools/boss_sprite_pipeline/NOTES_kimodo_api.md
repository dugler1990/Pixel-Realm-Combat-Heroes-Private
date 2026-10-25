# Kimodo CLI and API — what we were not using, and the one trap that fails silently

Reference for `kimodo_gen`, written 2026-09-27 while building the generation test suite.
Covers only things not already in `PROCESS.md` or `NOTES_retarget_kimodo.md`.

## The trap that costs real time

**`--output` is a STEM. Anything after a dot is stripped as a file extension.**

`--output out/Kimodo-SOMA-RP-v1.1__haymaker` writes to `out/Kimodo-SOMA-RP-v1/`. It fails
**silently by overwriting a different cell**, so a matrix run looks like it succeeded while half
its results have been clobbered by the other half. It hit twice in one session: the v1.1 models
overwrote the v1 results, and `B1_none_2.0_haymaker` collapsed to `B1_none_2`, so six durations
overwrote each other. Sanitise anything interpolated into an output path — `${D%%.*}s`, `RPv1_1`.

Related: with `--num_samples 1` it writes **files** (`stem.npz`, `stem.bvh`); with 2+ it writes a
**directory** of `_00`, `_01`. A `find <stem> -name '*.npz'` finds nothing after a single-sample run.

## The second trap: two skeletons, and the API hands you the wrong one

**`model.skeleton` is `somaskel30`. The model's OUTPUT is 77 joints. The BVH export needs
`model.skeleton.somaskel77`.**

Calling the model directly instead of through `kimodo_gen` means reimplementing what
`kimodo/scripts/generate.py` does after generation, and this line is easy to miss:

```python
skeleton = model.skeleton
if isinstance(skeleton, SOMASkeleton30):
    # motion has already been converted to somaskel77 within the model for output
    skeleton = skeleton.somaskel77.to(device)
```

Pass the 30-joint one to `global_rots_to_local_rots` / `save_motion_bvh` and every cell dies with

    einsum(): subscript N has size 77 for operand 1 which does not broadcast with previously seen size 30

`N` is the **joint** axis, not frames — `motion_to_bvh` calls `skeleton.from_standard_tpose`,
which contracts the motion against the skeleton's 77 rotation offsets. 30 and 77 are the two
skeletons, nothing to do with the prompt.

It costs time because of *where* it fails: generation succeeds, the output directory gets
created, and only the write fails. A run therefore looks like "this kind of prompt breaks the
model". Ours failed first on four chained cells in a row and was diagnosed for an afternoon as a
chaining limit, then as a SEED-v1.1 limit; the same chained prompt ran clean on both models
through the CLI, and plain single-prompt cells were failing identically two rows later.

Two rules that would have caught it in a minute:
- when a driver replaces a CLI, diff it against the CLI's source before blaming the model;
- a cell that fails after its output directory exists failed in **export**, not in generation.

Also note `generate.py` passes `multi_prompt=True` for every call, single prompt or chained. A
driver that sets it from `len(texts) > 1` is not generating the same thing the CLI did, and the
two cannot be compared in one matrix.

## Constraint classes — we only ever used the bluntest one

```
FullBodyConstraintSet(skel, frame_indices, gpos, grot)      # pins ALL 77 joints
Root2DConstraintSet(skel, frame_indices, smooth_root_2d, global_root_heading=...)
EndEffectorConstraintSet(skel, frame_indices, gpos, grot, smooth_root_2d, *, joint_names=[...])
LeftHand / RightHand / LeftFoot / RightFootConstraintSet
```

Every idle-anchored clip we have ever generated used `FullBodyConstraintSet`, which pins **every
joint** at the anchor frames. That is the likeliest reason anchored attacks go limp: the model is
told all 77 joints must be exactly here, when we only meant "start and finish standing".

`EndEffectorConstraintSet` takes an explicit `joint_names`, so "feet return home, arms free" is a
first-class option. `Root2DConstraintSet` pins only where he stands. `SOMASkeleton77` has no
`LeftToeBase` — check names against the skeleton before listing them.

## Prompt chaining — the native idle → action → idle

The positional prompt accepts several sentences separated by periods, and `--duration` accepts one
length per sentence:

```
kimodo_gen "A brute stands ready. <action>. It returns to standing." --duration "1.0 2.5 1.0"
```

No constraint file involved. Measured on groundsmash (peak deg/frame):

| | peak |
|---|---|
| unchained control | 131 |
| 3 chunks, 1.0/2.5/1.0 | 73 |
| 3 chunks, 0.5/4.0/0.5 | 78 |
| **5 chunks, explicit wind-up** (`ready. winds up. STRIKE. recovers. ready`) | **157** |

Three-chunk splits roughly halve the strike. A five-chunk chain that names the wind-up beats even
the unchained control — naming the phases appears to let the model load the blow.
`--num_transition_frames` (default 5) controls the blend between chunks.

## Parameters that existed and we never used

- **`--seed`** — reproducible. Every comparison made before this carried seed noise.
- `--cfg_type {nocfg,regular,separated}` — we only ever used `separated`.
- `--no-postprocess` — there is foot-skate post-processing **on by default**.
- `--bvh_standard_tpose` — export with a true T-pose rest pose rather than the BONES-SEED rest pose.
- `--input_folder` — loads settings from a `meta.json`.

## Models — six exist, we used one

```
nvidia/Kimodo-SOMA-RP-v1      <- the only one we had ever used
nvidia/Kimodo-SOMA-RP-v1.1
nvidia/Kimodo-SOMA-SEED-v1    SEED = a different training set, not a version bump
nvidia/Kimodo-SOMA-SEED-v1.1
nvidia/Kimodo-SMPLX-RP-v1     different skeleton, no BVH export
nvidia/Kimodo-G1-RP-v1        robot skeleton
```

The four SOMA models are drop-in — same skeleton, same BVH export.

## npz schema

```
local_rot_mats  (T,77,3,3)   global_rot_mats (T,77,3,3)   posed_joints (T,77,3)
root_positions  (T,3)        smooth_root_pos (T,3)        global_root_heading (T,2)
foot_contacts   (T,6) bool
```

Constraints want `posed_joints` for positions, `global_rot_mats` for rotations, and
`smooth_root_pos[:, [0, 2]]` for `smooth_root_2d`.

## Scoring raw BVH

Parse channel offsets from the `CHANNELS` declarations — the root has 6 (position + rotation),
other joints usually 3, so `joint_index * 6` runs off the end of the array. **Only the root has
position channels**, so joint world positions (a wrist, for hand travel) need forward kinematics;
they cannot be read out of the columns.

Useful measures, all off the raw file: hip-height range (a jump that does not leave the ground
reads ~0.02 against ~0.38 for a real one) and peak total degrees moved in a single frame (an
attack needs one; limp clips sit near 90, the clips Douglas rated sit at 180–410).
