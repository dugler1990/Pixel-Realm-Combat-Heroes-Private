# Animating a non-human rig — what exists, what we can use

Investigated 2026-09-26, while Kimodo was generating. The question: is there something that
takes **our rigged demon** and animates it directly, instead of generating human motion and
retargeting it? Retargeting is what cost this project a full session, and it structurally
cannot animate his wings or tail, because the source skeleton has neither.

## THE FIND — free winged creature rigs with animated wings

`Linzhan/Objaverse-XL-Rigged-Animated` (25 GB, 7,373 rigged GLB, free) contains **51 avian rigs
with >=20 joints and >=60 frames**. Probed six of them locally (`rigfix/probe_rig.py`):

| rig | bones | actions | wing bones | wings actually move |
|---|---|---|---|---|
| `f3e0215859604f7c97cba7367ce27931` | 57 | **42** | 16 | **all 16**, up to 116 deg |
| `ef72384761d943c48e2890f125b13f0c` | 41 | 12 | 6 | all 6, up to 137 deg |
| `669a6c2957bbceb71e634288_fbx` | 27 | 20 | 4 | all 4, up to 64 deg |

The first one is a **winged gargoyle with a complete game animation set**, two creature
variants (Daedalus, Kargoyle):

    Idle, Stand, Run, Sprint, Attack, Skill x6, Damage, Die, Dead,
    Down, Fall, Airborne, Avoid, Spawn, Stun, Taming

Bone naming is 3ds Max Biped - `Bip01-Spine/Spine1/Spine2`, `Bip01-Neck/Neck1/Neck2`,
`Bip01-Head`, `Bip01-L-Clavicle`, `Bip01-L-UpperArm` - **plus `Bone_Jaw` and 16 wing bones**.

**Why this matters more than any of the below.** It has natively the four things the human SOMA
skeleton structurally cannot provide:

- **wings**, animated, which is the single biggest thing making our clips read as stiff
- a **jaw** bone, so the mouth can be driven rather than pinned
- a **neck**, the bone UniRig never gave us
- a **winged bipedal creature body plan** rather than a human one, so the proportion mismatch
  that costs us the armpit and the 10% joint offset largely goes away

And `Airborne` / `Fall` is the soaring that Kimodo cannot generate at all.

It needs no new model: it is a rigged GLB with actions, so it feeds the retargeter we already
built, the same way Kimodo's BVH does. The bone map changes, nothing else.

Licensing per Objaverse asset still needs checking before shipping.

Local copies: `generated/bosses/demon/avian_test/glb/`.

## Verdict first

| Option | Usable today | Animates wings/tail | Cost |
|---|---|---|---|
| **Kimodo + our retargeter** | **yes, working now** | no | already built |
| **Truebones creature mocap** | probably | maybe | hours — it is just another BVH source |
| **Mixamo library** | yes, free | no | hours — another clip source |
| **UniMate** | not drop-in | **yes, in principle** | days, and needs its own pod |
| Meshy Smart Rig | yes, paid | unclear | account + credits |

Keep Kimodo for monster-specific attacks. The wings still need our own procedural overlay
whatever we choose — no generator knows he has them.

## UniMate — the one that would actually solve it

[Paper](https://arxiv.org/abs/2609.05415) · [code](https://github.com/Friedrich-M/UniMate) ·
[project](https://linzhanmou.com/unimate/) · SIGGRAPH Asia 2026 · **code is MIT**.

Synthesises motion for arbitrary skeletons from a rigged asset plus a text prompt, no per-rig
retraining. Trained on **UniML3D** — 13,006 text-paired clips spanning bipedal, quadrupedal,
**avian**, marine, insectoid and serpentine rigs. Avian is the interesting word: winged
creatures are in the training distribution, so wings could be driven directly.

**All three pieces exist:**

- code — cloned fine, MIT
- weights — **not officially released** ("[TODO] Pretrained checkpoints ... will be released
  soon"). A third-party checkpoint exists at
  [`tarn59/UniMate-Weights`](https://huggingface.co/tarn59/UniMate-Weights): unofficial, not
  endorsed by the authors, provenance unverified.
- dataset — **published**: [`Linzhan/UniML3D`](https://huggingface.co/datasets/Linzhan/UniML3D),
  with `run_download.sh` as stage 0 of the data pipeline.

**The catch, and it is the important part.** README line 159:

> *Sampling starts from the output directory of a training run (`config.json`,
> `dataset_stats.npy`, `checkpoints/`). The target skeleton — T-pose and topology conditioning —
> is taken from the dataset, so the `dataset/features/<dataset>/` directory the model was
> trained on must be present.*

So it does **not** accept an arbitrary rigged GLB at inference. "Arbitrary skeletons" means
arbitrary skeletons *that have been through their four-stage data pipeline* and exist as an
`object_type` inside `dataset/features/`. To animate our demon we would have to run his rig
through stages 1–4 (canonicalise, annotate joints, clean names, extract features) to add him as
a new object type. That is documented in `data_process/README.md`, but it is a project, not an
afternoon — and it wants a T-pose, which we do not currently have for him.

**Disk.** UniML3D plus weights will not fit alongside Kimodo on a 55 GB container (31 GB free
with Kimodo's venv and its 17 GB Llama cache in place). This needs its own pod.

## Tried it — what actually happened

Ran on the pod 2026-09-26. Findings, in order of usefulness:

**UniML3D's published `export/` is previews only.** 1,097 mp4 and 76 png — no motion data.
Breakdown: `export/objaverse` 51.8 GB, `export/mixamo` 1.36 GB, `export/truebones` **0.19 GB**.
So the 53 GB headline is almost entirely Objaverse renders, and Truebones is trivially small -
but none of it is motion.

**`skeletons.csv` is worth having on its own.** It indexes every rig with joint count, clip
count, category and facing axis. The winged entries:

| rig | joints | clips | frames |
|---|---|---|---|
| truebones Dragon | **140** | 9 | 2017 (67 s) |
| truebones Bird | 61 | 18 | 1666 |
| truebones Bat | 47 | 10 | 798 |

and the Dragon's clips are named `Fly`, `Slow_Fly`, `Idle`, `Idle_2`, `Idle_3`, `Attack`,
`Attack_2`, `Attack_3`, `Die`. That is precisely the set we want, on a winged creature.

**But Truebones motion is not free.** Their `run_download.sh` says so outright: *"Truebones ZOO
is a commercial asset pack and is not redistributed; this downloads annotations only... To
obtain the motion data, purchase it from https://truebones.com"*. The free download is prompts,
metadata, renders and build scripts.

**Two free sources fell out of the same script**, and these are the actionable finds:

- `Linzhan/Mixamo-Animations-Characters` — Mixamo animations as a HF dataset. **No browser and
  no Adobe account needed**, which removes the only awkward part of the Mixamo route.
- `Linzhan/Objaverse-XL-Rigged-Animated` — free rigged+animated assets, and `skeletons.csv`
  lists many as **avian with real wing joints** (`Wing1.R`/`Wing1.L`, `RightWingEnd`,
  `back_right_wing`). The only free source of genuine **wing motion** found.

## Truebones — the lead worth following first

UniMate's own training data is built from **Truebones FBX, Mixamo FBX and Objaverse GLB**.
Truebones is a creature/animal mocap library — dragons, quadrupeds, winged things. That is
ordinary mocap in an ordinary format, so it needs **no new model at all**: it feeds our
existing retargeter exactly like Kimodo's BVH does, and unlike Kimodo it may contain rigs that
actually have wings and tails to copy from.

Cheapest high-value experiment on this list. Worth pricing and checking licensing before
anything else.

## Mixamo — free, and already compatible

~2,400 animations, free with an Adobe account. The useful framing is **not** "Mixamo rigs the
demon" — its auto-rigger is humanoid-only and would ignore his wings and tail. It is a **source
of clips**: professionally captured, far cleaner than anything generated, and our retargeter is
source-agnostic.

Gives us the generic set cheaply — walk, run, turn, stagger, hit reactions, death. Will not
give monster-specific moves, and carries the same human-proportion mismatch we already handle
(`NOTES_retarget_kimodo.md`, "Still broken: the armpit").

Needs a browser and Douglas's own account; cannot be driven from a pod.

## What none of them solve

**The wings.** Kimodo's skeleton has none. Mixamo's has none. UniMate could in principle, but
only after the data-pipeline work. Right now his wings and tail sit dead at rest in every
generated clip, which is the single biggest thing making them read as stiff — more than any
retargeting error. `animate_procedural.py` already has wing-flap code from the earlier pass;
layering that over the generated clips is the cheapest visual win available and does not depend
on any of the above.
