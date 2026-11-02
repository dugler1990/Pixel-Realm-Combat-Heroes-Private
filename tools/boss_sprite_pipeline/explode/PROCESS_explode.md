# Explode a generated character into whole parts

Started 2026-11-01. A log written as the work happens, for refining into a repeatable (and later
automated) process. Scripts live next to this file.

## Goal

Take one TRELLIS mesh of a character wearing gear (fused: armour and body are one surface) and get
each gear piece as its own **whole** mesh (closed, hidden surfaces present), so pieces can later be
bound to bones and swapped.

Why: cutting pieces out of the fused mesh (gear test v2, 2026-10-31) left torn edges and nothing
underneath. Finding a part is not having it: a pulled-off helmet is a paper-thin shell with a hole,
and the head under it was never modelled.

## Pipeline

| Step | Where | Tool | In | Out |
|---|---|---|---|---|
| 1 render | local | `explode_render.py` (Blender venv) | outfit GLB | lit renders + position images per camera |
| 2 label | local, GTX 1050 | `explode_sam.py` (SAM3 venv) | lit renders, prompt list | 2D masks per prompt |
| 3 map | local | `explode_label.py` (Blender venv) | masks + position images | one part label per mesh face, part-coloured renders, split GLB |
| 4 check | you | | part-coloured renders | go / fix prompts |
| 5 complete | 24 GB pod | HoloPart (VAST, MIT code + weights) | split GLB | each part closed and whole |
| 6 show | local | | completed parts | exploded view, each part alone |

Licences checked 2026-11-01: HoloPart MIT (code + HF weights), built on TripoSG (MIT). Not usable:
PartField / PartPacker / OmniPart (NVIDIA non-commercial code), Tencent part models (banned, §2).

## Inputs used

- Outfit mesh: `generated/bosses/barb/gear_test/barb_fullplate_from_front.glb` (TRELLIS.2,
  `--skip-texture`, 791k verts).
- The full plate leaves only the head bare: there is no visible body to complete under the armour.
  The body comes from the naked barb (`barb_base_from_front.glb`), which aligns to the full plate
  within 0.19 % of height (gear test v1/v2).

## Log

### Step 1 — render (2026-11-01, local, ~2 min)

```
cd C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss
tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_render.py generated\bosses\barb\gear_test\barb_fullplate_from_front.glb generated\bosses\barb\explode
```

- 4 directions x 2 square crops (upper / lower body) = 8 cameras, 1120 px. Crops because SAM3 runs at
  560 px on the 1050: a full-body frame leaves hands and feet a few dozen pixels.
- Before rendering, the atlas's unwritten texels are filled (TRELLIS leaves ~5 % of texels black
  with alpha 0 *inside* the charts — the dark speckle on every barb render; not gutter bleed, padding
  the gutters did not remove it).
- Each camera also writes a world-position EXR (`(P+1)/2` encoded: Eevee clamps negative emission),
  the trick from `face_parts.py`: it ties every pixel to a mesh vertex by 3D position. UV-id images
  do not work for this (confetti atlas, NOTES_rig_jaw_sam3.md).

### Step 2 — SAM3 masks (local GTX 1050, model load ~4.5 min, ~1 s per prompt)

```
$env:HF_HUB_OFFLINE = "1"
C:\Users\Douglas\sam3local\.venv\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_sam.py generated\bosses\barb\explode
C:\Users\Douglas\sam3local\.venv\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_sam.py generated\bosses\barb\explode tools\boss_sprite_pipeline\explode\prompts_extremities.json
```

What SAM3 got right / wrong on the full-plate barb (scores are the top instance):

| Prompt | Score | Result |
|---|---|---|
| head / hair / beard | 0.90–0.96 | exact |
| belt | 0.86–0.92 | exact |
| breastplate | 0.70–0.86 | chest (front) and back plate (back); straps between left out |
| armored skirt (upper crop) | 0.73–0.91 | exact |
| armored skirt (lower crop) | 0.48–0.67 | **wrong**: takes the legs too → ignored in lower crops |
| shoulder armor | 0.75–0.87 | pauldrons; a weaker 2nd-tier instance sits on the elbow |
| upper arm / elbow / forearm armor | 0.68–0.91 | each returns most of the arm → all map to one `arm` part |
| gauntlet | 0.19–0.47 | **weak** → replaced by `hand` (0.87–0.96) and `glove` |
| armored boot / shin / knee / thigh | 0.4–0.88 | each returns the whole lower leg → all map to `leg` |
| foot / shoe | 0.68–0.88 | the sabaton → `boot` |
| neck armor | 0.11–0.38 | nothing useful |

Lesson: SAM3 knows everyday nouns (hand, foot, belt, head) far better than armour terms (gauntlet,
greave). Ask for the body part the armour covers.

### Step 3 — masks → part per face (local, ~4 min)

```
tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_label.py generated\bosses\barb\explode
```

- Vote per vertex = mask fraction × score × part priority, per camera; **a part takes its strongest
  prompt, not the sum** (summed, three arm prompts outvoted the one shoulder prompt on the pauldron).
  Priority makes the small specific part win an overlap (hand 1.6 > arm 1.0, foot 1.6 > leg).
  Instances under 0.5 are ignored (mostly wrong guesses).
- Only ~44 % of welded vertices get a direct vote (8 cameras, sub-pixel triangles); the rest take the
  nearest labelled vertex along the surface.
- Cleanup 1: a fragment smaller than 5 % of its part's main piece that touches another part joins the
  neighbour it touches most (6201 faces / 54 fragments at the wrists and shoulders).
- Cleanup 2: small loose geometry pieces (touch nothing) join the part whose main piece is nearest in
  space (104 pieces, 23,546 faces; e.g. hip flecks had been labelled arm because the hand hangs there).
- Left/right by the sign of x (+x = the character's left).

Result: 14 parts — head, torso, belt, skirt, pauldron/arm/gauntlet/leg/boot × left/right.
`PARTS_SHEET.png` (coloured by part, 4 views), `split_preview.png` (pulled apart: these are still
open shells, not completed), `input_parts.glb` (one object per part = HoloPart's input format),
`labels_face.npy`, `parts.json`.

### Step 5 — HoloPart (pod) — notes before running

- Input: a GLB scene with one mesh per part — `input_parts.glb` is exactly that.
- `python -m scripts.inference_holopart --mesh-input <glb> --output-dir <dir>`; weights auto-download
  from HF `VAST-AI/HoloPart`; fp16; defaults 50 steps, guidance 3.5, `--batch_size 8` parts per call.
- **Its post-process simplifies every part to 10,000 faces** (pymeshlab) — far below the TRELLIS
  detail. Patch that line before running (keep the full marching-cubes output).
- Geometry extraction: flash decoder, octree depth 9 (~512³ per part, each part normalised to fill
  the box), so small parts get full resolution.
- requirements.txt pins `numpy==1.22.3` (no wheel past Python 3.10 → make a 3.10 venv with uv) and
  needs `diso` (compiles CUDA code → the pod image must have `nvcc`, i.e. a *devel* image) and
  `torch-cluster` (PyG prebuilt wheel matching the torch version). The post-process also imports
  `pymeshlab`, which is not in requirements.txt.
- Pod: 24 GB GPU, CUDA 12.x **devel** image, Public IP + TCP 22, ~50 GB disk.

### Step 5 — HoloPart (pod) — what was done

Pod (2026-11-01): RunPod template "PyTorch 2.8.0" (`runpod/pytorch:1.5.0-cu1281-torch280-ubuntu2404`,
Python 3.12, torch 2.8.0+cu128, nvcc 12.8 present), 50 GB disk. Listed as an RTX 4090 at $0.34/hr;
the pod came up as an **RTX PRO 4000 Blackwell** 24 GB (sm_120: needs CUDA ≥ 12.8 / torch ≥ 2.7,
which this template has).

- The Connect tab shows the ssh.runpod.io proxy line (needs `-tt`, no scp). The pod also has a public
  IP: inside it, `echo $RUNPOD_PUBLIC_IP $RUNPOD_TCP_PORT_22` gives the direct address, and plain
  `ssh`/`scp -P <port> root@<ip>` work with the same key — the 83 MB input uploaded in 5 s.
- Install (`hp_install.sh`): a venv with `--system-site-packages` to reuse the template's torch (the
  `numpy==1.22.3` pin is ignored: no wheel for 3.12, and torch 2.8 is needed for Blackwell anyway).
  ```
  cd /workspace && git clone https://github.com/VAST-AI-Research/HoloPart
  python3 -m venv --system-site-packages hp && . hp/bin/activate
  pip install diffusers transformers einops huggingface_hub opencv-python-headless trimesh omegaconf \
      scikit-image peft jaxtyping typeguard pymeshlab
  pip install torch-cluster -f https://data.pyg.org/whl/torch-2.8.0+cu128.html
  TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=32 pip install --no-build-isolation diso
  ```
- Patch: `simplify_mesh(part_mesh, 10000)` → `simplify_mesh(part_mesh, int(os.environ.get("HP_FACES", "150000")))`
  in `scripts/inference_holopart.py`.
- HoloPart only samples 20,480 surface points per part (and 20,480 from the whole), so the input
  mesh's resolution does not matter; each part is normalised to fill the box before generation.
- pymeshlab's plugins (incl. the decimation filter) need `libOpenGL.so.0`: `apt-get install -y
  libopengl0 libgl1 libglu1-mesa libegl1` (the import still succeeds without it — check
  `hasattr(pymeshlab.MeshSet(), "meshing_decimation_quadric_edge_collapse")`).
- Run 1 (upstream extraction, only the face-limit patch): 14 parts in ~9 min (diffusion 2 batches ×
  ~1.6 min, then meshing one part at a time, single CPU core). Output `explode/holopart/output.glb`, 40 MB.
- `nohup … &` over ssh must also redirect stdin (`< /dev/null`) or the ssh call never returns.
  `pgrep -f inference_holopart` matches the ssh command's own shell: use `pgrep -f "^python -m scripts.[i]nference"`.

### Step 6 — look at run 1 (local)

```
tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_show.py generated\bosses\barb\explode generated\bosses\barb\explode\holopart\output.glb generated\bosses\barb\gear_test\barb_base_from_front.glb
```

- HoloPart's export renames the parts `geometry_0..13`; `explode_show.py` matches them to the shells
  by bounding-box centre (all 14 matched, centres 0.2–1.8 % of height apart).
- Writes `EXPLODED.png` (completed parts pulled away from the naked body), `PARTS_ALONE.png` (shell vs
  completed, front-3/4 and back-3/4) and `completed.json` (faces, open edges).
- Result: every part came back closed in shape — the torso's ragged shoulder/side openings and the
  cut neck are filled; open edges fell on most parts (pauldron 1113 → 178, belt 1212 → 152, leg 916 → 152).
- But: surfaces show horizontal stair-steps (voxel steps of the depth-9 grid: the flash decoder
  meshes the raw grid, no smoothing), pinholes, and softer detail than the shell (face, straps).
  Skirt (2058 → 6039), head (428 → 852) and gauntlet_l (227 → 373) got *more* open edges.
- Upstream's non-flash "hierarchical" extractor is not a fix: the script passes it `final_octree_depth`
  / `post_smooth`, which `inference_utils.hierarchical_extract_geometry` does not take (TypeError),
  and it does no smoothing either.
- Fix tried in run 2: `holopart_patch.py` (applied to a clean checkout) — Taubin smoothing 10 steps +
  close holes ≤ 60 edges before decimation, seeded sampling, latents saved for re-meshing.

### Run 2 — smoothing (pod, ~4 min after diffusion)

- **Did not fix it.** Output `holopart/output_s10.glb` (198 MB): the stair-steps show as contour rings
  all over (`holopart/s10/ZOOM_done_s10.png`). The steps are several voxels wide on gently curved
  surfaces, so 10 Taubin passes (which reach a few vertices) barely touch them. The occupancy HoloPart
  decodes is close to on/off at the voxel scale; the fix belongs in the field (blur the logit grid by
  ~1–2 voxels before marching cubes), not the mesh.
- Decimation silently did nothing on 12 of 14 parts after the new filters (408k–1.64M faces left;
  two parts hit 150k). Not chased: the surface is the problem, not the size.
- Run 1's decimated meshes look *less* stepped than run 2's raw ones: decimation averages the steps.

### Step 7 — merge: original shell + HoloPart only where the shell has nothing (local, ~5 min)

```
tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_merge.py generated\bosses\barb\explode generated\bosses\barb\explode\holopart\output.glb
```

- Shells come from the textured original + `labels_face.npy` (separated in Blender by material slot;
  the part id rides on a face attribute because separate drops unused slots and renumbers).
- Infill = completed faces > 0.6 % of height from the shell, or whose nearest shell vertex is on the
  shell's cut edge (so the infill runs past the rim, no crack). Colour: UV of the nearest shell vertex.
- `MERGED.png` (shell vs merged, back-3/4 and from below; backface culling on, holes show red),
  `merged_parts.glb`, `merged.json`. Infill per part 3.8k–46k faces (run 1).
- Seen: the infill adds the missing undersides and flaps (pauldron_r, torso sides); the belt's infill is
  a solid disc across the waist (HoloPart closed the belt as a puck, not a ring).

### Brute-force knobs on HoloPart's surface (pod, re-decoding the saved latents, torso + head)

`holopart_redecode.py <input_parts.glb> <latents.pt> <out.glb> fp16|fp32 <depth> [part idx]` — re-meshes
without re-running diffusion (~8 s per part fp16, ~30 s fp32 at depth 9).

| Setting | Result |
|---|---|
| fp32 decoder instead of fp16 | identical stair-steps (`holopart/redec/ZOOM_fp16_vs_fp32.png`): not a precision problem |
| octree depth 10 (1024³) | CUDA out of memory on 24 GB |
| blur the logit grid, σ 1.0 / 1.5 / 2.5 voxels (`HP_BLUR`) | thin plates vanish: torso 1.14M → 33k → 4k faces → nothing (σ 2.5 crashed: empty mesh) |

The decoded occupancy is on/off at the voxel scale and the armour plates are only a few voxels thick,
so no decoder setting gives a smooth plate. A 48 GB GPU would allow depth 10, which halves the step
size but would not remove the steps.

### Step 8 — pose test: parts worn over the naked rigged barb (local, ~6 min per run)

```
tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_pose.py [--hide-body] generated\bosses\barb\gear_test\barb_base_rigged.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\explode\pose shells=generated\bosses\barb\explode\input_parts.glb merged=generated\bosses\barb\explode\merged_parts.glb
```

- One alignment for all parts (head residual 0.19 % of height), each part vertex copies the 4 nearest
  body vertices' weights; 6 poses × 4 views.
- **Body visible (green)**: the naked barb pokes through the armour almost everywhere, even at rest
  (`POSE_COMPARE.png`) — it is bulkier than the armour. A body cannot simply be worn under the gear; the
  body must be hidden where gear covers it (the usual game approach).
- **Body hidden, backfaces culled, red background** (`POSE_COMPARE_nobody.png`, `JOINTS_nobody.png`): no
  see-through gap in any pose with the plain shells, and the HoloPart infill makes no visible difference.
  What does show: the torso's ragged cut edge at the armpits (arms up, back view) and crumple at the
  knee (step).
- Conclusion for armour over a body: the cut shells are enough; HoloPart is not needed. The next fixes
  are the cut edges (clean seams) and the weights at the knees/shoulders.
- In real paint (`--texture`, `POSE_COMPARE_nobody_tex.png`): shells and shells+HoloPart look identical
  in every pose — the infill only fills holes that neighbouring pieces already hide.
- **The bare rigged body bends badly too** (`explode/pose_body/POSE_body_tex.png`, no parts given):
  shoulders and upper back crinkle with the arms up/forward, inner thighs crumple in the step. Part of
  the armour's crumple is the base rig's (UniRig) skin weights, not the parts.

### Skinning: what others do (searched 2026-11-01)

- Armour: rigid plates weighted 100 % to one bone is the standard game practice. Shoulder pads are the
  known exception (bound to the upper arm they bare the shoulder top): a helper bone between collarbone
  and upper arm, or the pad attached as a separate object.
- Body: re-solve the weights with a method made for imperfect meshes — Robust Biharmonic Skinning
  (ACM TOG 2025, uses our skeleton), SkinTokens/TokenRig (open C++ port), Epic's Robust Skin Weights
  Transfer (Blender add-on exists). Licences and code not yet checked.

### Step 9 — 96 views instead of 8 (the cut edges)

Why: with 8 cameras only 41.1 % of the welded vertices are seen by any camera; the rest (armpits,
inner thighs, shoulder tops) get their part by flooding from neighbours — the ragged borders.

- `explode_render.py <glb> <work> 96`: 12 yaws × 4 elevations (−30, 0, 25, 55) × upper/lower crops,
  ~33 min locally (`generated/bosses/barb/explode96`). EXRs now ZIP-compressed (lossless).
- SAM3 on the pod at its native 1008 px, fp32 (laptop: 560 px fp16). The HF repo is gated: copy the
  local snapshot (`~/.cache/huggingface/hub/models--facebook--sam3/snapshots/<id>/`, 3.4 GB, ~3 min)
  and `sam3local/src` to the pod; the pod's transformers 5.22 has `Sam3Model`.
  ```
  export SAM3_SRC=/workspace/sam3local/src SAM3_MODEL=/workspace/sam3 SAM3_SIZE=1008 SAM3_DTYPE=float32
  python explode_sam.py /workspace/explode96
  python explode_sam.py /workspace/explode96 prompts_extremities.json
  ```
  2 views × 20 prompts = 30 s including model load.
- `explode_label.py` now looks pixels up with scipy's cKDTree (installed into `.venv-bpy`: `python -m
  ensurepip`, `python -m pip install scipy`). Checked on the 8-view set: 100 % the same part per face
  as the old per-pixel loop, 1.4 min instead of ~4. It prints `DIRECT COVERAGE`. Paired parts are now
  added in sorted order (a set's order changed between runs, swapping `leg_r`/`boot_r` indices).
- `explode_merge.py <work>` without a completed GLB exports only `shells_parts.glb` (for the pose test).
- SAM3 on the pod: 96 views × (12 or 8 prompts) + the hands/feet pass ≈ 20 min (~9 s per view;
  the GPU sat at ~14 %, one CPU core at 100 %: mask post-processing/PNG writing, not the model).
  5,217 mask files. Pulled back with everything else in `generated/bosses/barb/pod_pull/` (masks,
  logs, HoloPart latents and test meshes, `pod_pip_freeze.txt`, `holopart_patched.diff`).
  Git-Bash `tar` reads `C:/...` as a remote host: extract from inside the folder (or `--force-local`).
- **Result: not better.** Direct coverage 41.1 % → 57.6 % only: the other ~42 % of the welded
  vertices are hidden surface no outside camera reaches (armour insides, the body under it), so the
  90 % yardstick cannot be met by angles. The arm/pauldron seam got *worse* (the low views see the
  pauldron's underside and SAM calls it "upper arm armor"); torso, belt, hips unchanged
  (`explode96/CUT_8_vs_96.png`, `CUT_ZOOM_8_vs_96.png`; right-side colours differ between the two
  sheets because the part order changed). Keep the 8-view cut.
- The ragged borders are SAM prompts disagreeing where parts meet. Next idea for them (not done):
  snap each border to the nearest geometric crease, where the plates actually meet.

### Step 10 — what can any camera see at all? (ray casts, 2026-11-02)

```
tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe tools\boss_sprite_pipeline\explode\explode_visibility.py generated\bosses\barb\gear_test\barb_fullplate_from_front.glb generated\bosses\barb\explode\labels_face.npy generated\bosses\barb\explode\parts.json
```

20,000 points spread over the surface by area, a ray from each towards every camera direction (no
pixels, so small faces are not missed). 24 s.

| Cameras | Surface area visible |
|---|---|
| 8 views | 39.6 % |
| 96 views | 52.8 % (DIRECT COVERAGE said 57.6 % of vertices: the pixel count was not the problem) |
| 256 directions over the whole sphere | **68.2 % — the ceiling for any outside camera** |

- The other 31.8 % is a **second layer right under the outside**: for 88 % of those points another
  surface lies within 0.5 % of his height along the normal, 98 % within 1 %. Armour inner walls and the
  body under the plates — every part has it (head 46 %, gauntlets 45–50 %, boots 42–44 %, torso 33 %,
  skirt 27 %, pauldrons 6–9 %). No angle and no pose sees it.
- So the coverage target is **100 % of the outside 68 %**: the 96 views reach 52.8 / 68.2 = 77 % of it;
  the missing outside is reachable with more directions (straight below, between the legs, steep
  angles). The inner layer takes the part of the outside surface directly above it — a geometry step,
  not SAM.
