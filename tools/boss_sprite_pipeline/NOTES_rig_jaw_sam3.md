# Rigging notes — UniRig, wing bones, SAM3-placed jaw (state at 2026-09-22, in progress)

What was done today, what worked, what didn't, and where each thing lives. Read with
`PLAN_d2_and_animation.md` (the plan) — this is the log of step 1 (rig) and the jaw work.

## Files

| Thing | Path |
|---|---|
| Rigged mesh (UniRig + wing bones) | `generated/bosses/demon/rig/rigged_12345_wings.glb` |
| Rigged mesh + jaw (work in progress) | `generated/bosses/demon/rig/jaw/rigged_jaw.glb` |
| Bone role map (hand-labelled) | `generated/bosses/demon/rig/bone_roles.json` |
| Rig gate renders | `rig/bend/BEND_SHEET.png` (before wing bones), `BEND_SHEET_WINGS.png` (after) |
| Jaw check renders | `rig/jaw/JAW_CHECK.png` (front + side: rest / closed 20° / closed 30° / open 15°) |
| SAM3 masks, front (15° elev) | `generated/bosses/demon/face_sam/lit/` — `<prompt>_<k>_<score>.npy` + overlay PNGs |
| SAM3 masks, side (yaw 90) | `generated/bosses/demon/face_sam/side90/` |
| Animated clips | `generated/bosses/demon/animate/animated.blend` (+ `PREVIEW_SHEET.png`) |
| Scripts | `add_wing_bones.py` (scratch), `face_parts.py`, `animate_procedural.py`, `animate.py` |

## 1. UniRig on the pod — what it took

Pod: RTX 3080 10 GB, CUDA 12.8 devel image, public IP + TCP 22 (use the direct `ssh -p <port>
root@<ip>` line for scp; the `ssh.runpod.io` proxy has no sftp). Install ≈ 15 min:

```
uv venv --python 3.11 .venv                      # UniRig needs 3.11 (bpy==4.2 wheel)
torch==2.7.0 torchvision==0.22.0  --index-url .../whl/cu126
requirements.txt minus flash_attn, then spconv-cu126, torch_scatter/torch_cluster (pyg wheels
for torch-2.7.0+cu126), numpy==1.26.4
flash_attn: prebuilt wheel flash_attn-2.8.3+cu12torch2.7cxx11abiTRUE-cp311 — check
  torch._C._GLIBCXX_USE_CXX11_ABI first. `uv pip install <github url>` crawled at 130 KB/s;
  `curl -L` of the same url on the pod ran at 12 MB/s. Curl it, then install the local file.
uv pip install pip psutil                        # extract.sh calls `pip install psutil`
apt-get install libegl1 libgl1                   # skin stage imports open3d/pyrender -> libEGL.so.1
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1        # skin checkpoint pickles box.Box; torch 2.7 refuses it
```
Run: `generate_skeleton.sh` (~1 min) → `generate_skin.sh` (~2 min) → `merge.sh` → `rigged.glb`
(55 MB, 700k verts, 37 bones, 4 influences/vertex). The 700k mesh is fine: UniRig simplifies
to 50k faces internally. **Do not decimate the painted mesh** — the confetti atlas tears
(`GATE_700k_vs_150k.png`).

Result: a clean biped skeleton (pelvis, spine, chest, neck, head, 2×5-bone legs, 2×4-bone arms
with three finger chains each, a tail). **No wing bones, no jaw.** `inspect_rig.py`'s
position-based role guesser labelled 30/37 bones "spine" — useless here; roles were read off
`rig_front.png` (skeleton drawn over the silhouette) and written by hand into `bone_roles.json`.

## 2. Wing bones — hand-placed, geometric

Gate R1 (`BEND_SHEET.png`) showed legs/spine/head bend cleanly but the wings shred when an arm
moves: the skinner had given the membranes shoulder/elbow/tail weights. Fix
(`add_wing_bones.py`): two bones per wing (root→top joint, top joint→outer tip) parented to the
chest, placed from measured extremes of the wing vertices. Wing vertices are separable
*geometrically* — behind the torso (Blender y > 0.02) and outboard (|x| > 0.14), minus the calves
— then weighted by distance to the two segments, with a blend band at |x| 0.14–0.20 so the root
doesn't tear. `BEND_SHEET_WINGS.png`: arms no longer touch the wings; each wing flaps back / both
forward / fans cleanly.

## 3. Jaw from SAM3 — what worked, what didn't

Local SAM3 lives in `C:\Users\Douglas\sam3local` (`segment_prompt(image, prompt)`), runs on
the 1050. Scratch driver `sam_face.py` loads the model once and saves the top-3 masks per prompt.

**Render matters more than the prompt.** On the flat (unlit) texture render "jaw" scored 0.10
(a blob on the chin). On the *lit* render at 15° elevation, 2048²:

| prompt | score | got |
|---|---|---|
| horn | 0.88 / 0.85 / 0.84 | all three horns |
| eye | 0.87 / 0.83 | both eyes |
| open mouth / mouth | 0.79 | mouth interior |
| lower jaw | 0.69 | lower teeth + chin + jaw sides (front-facing part) |
| teeth | 0.62 | tooth rows |

Side view (yaw 90): "jaw" instances 0.65 / 0.50 / 0.42 — the **third** (lowest-scoring) one is
the big jaw side back to the ear; scores don't rank by extent, so take the union of instances
and filter by height band instead of trusting #1.

**Pixels → vertices.** First attempt mapped mask pixels through a UV-id render to atlas texels;
the confetti atlas made a 2-texel dilation jump islands and "jaw" came back with horn vertices.
Second attempt renders **world position** per pixel instead (`face_parts.py::render_pos_id`)
and matches vertices by 3D proximity — but Eevee clamps negative emission, so encode
`(P+1)/2` and decode. That works (eye 1252 verts, jaw 4704, horn 3454, teeth 722).

**Region and weights.** A front view only sees the jaw's front 3 cm, so the hinge landed on the
lips; the side view supplies the depth (hinge now at y −0.11, z 0.17, under the ear). A **box**
region tears — its faces cut straight through cheeks and neck and show as hard edges. What works
is **distance weighting**: weight = smooth falloff of each vertex's distance to the SAM jaw
point cloud (front + side + mirrored side; `NEAR 4 mm → FAR 22 mm`), × a fade at the hinge plane,
× a fade at the top edge so the upper lip stays. Result (`JAW_CHECK.png`): −20° closes the mouth
(teeth meet, lips shut), +15° opens it wider, −30° over-closes. Sign: **negative = close** for
this bone. Still to fix: a crease at the hinge line in the side view (rear fade is only 3 cm —
raise `REAR`), and the chin spike reads oddly when closed. The bake in the same session that
built the bone rendered garbage; **always re-render from the exported GLB in a fresh process**
(scratch `jaw_check.py`).

**Rest pose.** The mesh was generated mouth-open, so every clip currently plays with the mouth
open. Once the jaw is accepted: rest = closed (~−20°), idle breathes it a few degrees ajar,
attack opens it on the hit. That's one line per recipe in `animate_procedural.py` and a
re-bake; `bone_roles.json` needs `"jaw": "jaw"` and the animate stage must point at
`rig/jaw/rigged_jaw.glb`.

## 4. Procedural clips — state

`animate_procedural.py` bakes `idle` (48 f breathe: spine/chest pitch, head sway, wing rock,
tail lag, root bob), `move` (32 f two-beat stomp: hip/knee/foot sines, root dip on contact,
lateral sway, spine lean + counter-twist, arm counter-swing, wing flap) and `attack` (30 f:
anticipation → lunge → recover) onto any rig with the roles in `bone_roles.json`. Every angle is
about a *world* axis with the sign resolved per bone by trial (so bone rolls never matter), and
the root is shifted every frame so the lowest foot tip sits on the rest ground line. Amplitudes
are in `DEFAULT_PARAMS` / `stages.animate.params`. Clips are on NLA tracks with fake users;
open `animated.blend`, Dope Sheet → Action Editor → pick the clip → Space.

`animate.py` mode `procedural` is wired (`stages.animate.rigged` / `.roles` / `.params`), so
`pipeline.py --from animate --to pack` is the next command once the jaw is in.

## 5. Lessons worth keeping

- Position-based role guessing is not a rig reader; draw the skeleton over the mesh and label.
- Parts UniRig doesn't know (wings, jaw) are 20–100 lines of geometry each, not a new model.
- SAM3 wants a *lit* render; give it two views when the part has depth.
- Never define a deforming region as a box; weight by distance to the detected surface.
- Verify every rig change with a fresh-process render, never in the session that edited it.
