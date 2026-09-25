# Kimodo motion onto the demon — what works, what it cost, what is still broken

Companion to `NOTES_rig_jaw_sam3.md` (how the rig was built). This covers getting generated
human motion onto it. Written 2026-09-25.

## Run it

```
.venv-bpy/Scripts/python.exe retarget_bvh.py \
    generated/bosses/demon/rig/jaw/rigged_jaw_smoothw.glb \
    generated/bosses/demon/rig/jaw/bone_roles.json \
    generated/bosses/demon/kimodo_keep \
    generated/bosses/demon/animate_km
```

Then videos (two steps because cv2 is not in `.venv-bpy` and bpy is not in the cv2 venv):

```
.venv-bpy/Scripts/python.exe scratchpad/anim_video.py <animated.blend> <out> 400 2
python scratchpad/make_mp4.py <out> 12
```

Bake is ~4 min for 9 clips; the videos are ~18 min, and that is two camera angles per frame —
drop to one and it halves.

## The rig, and why there are five glb files

`rigged_jaw_wingfix.glb` was the starting point. Each step below fixed something the *next*
step's measurement exposed; the chain is kept because each is a separate, checkable change.

| File | Script | What and why |
|---|---|---|
| `rigged_jaw_wingfix.glb` | `fix_wing_parent.py` | wings were parented to bone_13 → chest |
| `rigged_jaw_shoulderfix.glb` | `fix_shoulder_parent.py` | clavicles were parented to bone_13 → chest |
| `rigged_jaw_headfix.glb` | `fix_head_weights.py` | head bone owned mid-chest; 29,462 verts moved to the chest, pivot z 0.179 → 0.205 |
| `rigged_jaw_chestfix.glb` | `fix_chest_weights.py` | arm bones owned both pectorals; 51,349 verts, 14,969 weight units moved to the chest |
| `rigged_jaw_smoothw.glb` | `fix_smooth_weights.py` | weights stepped straight from arm to torso; Laplacian blur 0.7 × 10 |

Use the last one. `bone_roles.json` carries an `_anatomy` block recording what each bone
**actually is**, because the role names in it are wrong — see below.

## The two naming traps

Both cost hours. Both were found by measuring, and both would have been found in minutes by
measuring first.

1. **The SOMA leg chain is `Leg → Shin → Foot`**, not the usual `UpLeg → Leg → Foot`.
   `LeftUpLeg` does not exist in the file, so the obvious map silently dropped the hips and
   fed the *thigh's* rotation into the *knee*. This is what "twisted into pretzels" was.
2. **Our own role names are off by one on the arms, and `head` is not the head.**
   `arm_l.shoulder` (bone_14) is the *clavicle*; `elbow` is the upper arm; `wrist` the forearm.
   And `head` (bone_34) is a 3.6 cm **snout**; the head is the bone labelled `neck` (bone_13),
   which carries 56k of vertex weight over the skull. The names are left alone because
   `animate_procedural.py` uses them; `MAP` in `retarget_bvh.py` maps to the real bones.

## The transfer

**World-space rotation delta against a standing reference.** For each mapped bone:

```
world_rotation(target, t) = Rsrc(t) · Rsrc(ref)⁻¹ · bind_rotation(target)
```

Three things make this the formulation that works:

- **It is a delta, not an absolute.** The BVH's *rest* skeleton lies on its side — its spine
  runs along world +X. Only the motion channels stand the figure up. So a plain WORLD-space
  `COPY_ROTATION`, or `nla.bake` over one, tips him 90°, every time. Posed at frame 1 the
  source measures `side +X, up +Z, forward −Y`, which is the frame his rest pose is in.
- **It is in world space.** The two rigs differ in hierarchy depth, parenting and bone roll.
  A world-space delta is a plain rotation, so all of that cancels. Earlier attempts at
  local-space deltas and rest-pose conjugation failed on exactly this.
- **Bones are written parent-first through `pose_bone.matrix`,** so each bone's orientation is
  set explicitly rather than inherited from whatever its parent just did.

`bind_rotation` is the demon's bone aimed along its source counterpart's frame-1 direction
(`BIND_MATCH=1`, the default) rather than his rest orientation. Without it, the difference
between a human neutral stance and his — his arms hang ~59° below horizontal — is baked into
every frame of every clip.

## Not driven, by design

- **wings and tail** — no counterpart in the source; left at rest for a procedural overlay
- **jaw** — pinned shut at `jaw_closed_deg` (−18°, measured in `rig/jaw/JAW_ANGLES.png`; the
  mesh was sculpted mouth-open so 0 is wide open). It rides bone_34, which is why it looked
  loose and flapping for as long as bone_34 was being driven.
- **bone_34, the snout** — rides the head

## Still broken: the armpit

**His arms are fused to the torso in the source mesh.** There is no armpit, no gap — the
owner-map rest render shows arm-owned geometry meeting chest-owned geometry directly. Raising
an arm 150° therefore has to stretch that bridge into a sheet, and no weighting scheme fixes
geometry that is not there.

What helped, measured on `groundsmash1` frame 55 by edge stretch (posed length / rest length):

| | p99 | verts over 3× |
|---|---|---|
| as it was | 6.78 | 51,814 |
| chest weight fix | 5.90 | 46,213 |
| + weight blur | 2.86 | 14,049 |
| + Corrective Smooth (in the bake) | **2.17** | **5,271** |

That takes it from shredded to a smooth membrane, not to nothing. `ARM_ELEV_CAP` (default 35°)
then limits how high the upper arm may point, which is a symptom patch but an effective one;
the correction is passed down to the forearm and hand so the arm rides down as a unit rather
than folding at the elbow.

A real fix means cutting and re-closing the armpit in the mesh, and re-texturing across the
seam. Not attempted.

## Is it correct? One command says so

`rigfix/dir_check.py <animated.blend> <clip.bvh> <action>` checks a hard invariant. With bind
matching, `Rd(ref).y == Rs(ref).y` by construction, so substituting into the transfer gives
`Rd(t).y == Rs(t).y` for every t: **every bone must point exactly where its source counterpart
points, on every frame.** On `haymaker1` all 20 bones read 0.0 deg mean and 0.0 deg max. Any
bone that is not near zero is a bug, except when `ARM_ELEV_CAP` is deliberately pulling an arm
down, which shows as error only while the source arm is above the cap.

So the transfer is exact, and it is worth being clear about what that does *not* buy. Identical
bone directions do not make an identical-looking pose on a different body: `rigfix/pose_compare.py`
puts the two skeletons side by side, normalised to the same height, and the joints still sit
**10% of body height apart** at frame 1. Same angles, different limb lengths and a far wider
chest, so his hands end up somewhere else. That is the ceiling of rotation-copy retargeting.
Past it lies copying end-effector *positions* and solving the chains with IK, which preserves
where the hands and feet go instead of what angle the shoulder is at.

## Versioning

Outputs are gitignored - 8.7 GB under `generated/bosses/demon`. So set `RUN_LABEL` and each run
lands in its own directory with a `run.json` recording the rig file, the knobs and the code
commit. That manifest is the only record of what produced a given set of videos; without it a
folder of mp4s is unattributable a week later.

## Diagnostics worth keeping

All in `rigfix/`, all cheap, all of them found something a guess had got wrong:

- `skel_dump.py` — every bone's parent, head/tail, length, direction and **vertex-weight mass**.
  The weight column is what exposed both naming traps.
- `owner_map.py` — renders the mesh coloured by which bone owns each vertex, rest and posed.
  This is what finally showed the arm bones owning both pectorals. `ZOOM`/`ZUP` env vars.
- `stretch_diag.py` / `stretch_map.py` — edge stretch percentiles, and the torn vertices drawn
  on the render. Distinguishes "deforming badly" from "dragged by the wrong bone".
- `hide_test.py` — re-renders with a group hidden. Ruled the wings out in one pass.
- `neck_profile.py` — horizontal cross-section by height. Answered "should we add a neck bone"
  with **no**: from shoulders to skull the radius runs 0.135 → 0.154 → 0.115, no waist at all.
  He has no neck, which is why UniRig produced none.
- `smooth_test.py` — renders several Corrective Smooth settings side by side with their stretch
  numbers, so the setting is chosen on numbers rather than on a thumbnail.

## Lessons

- Measure the source file before writing a bone map. Both naming traps were a two-minute check.
- A weight *mass* column next to the skeleton dump is worth more than the skeleton dump.
- "Which bone owns this vertex" rendered as colour beats any amount of reasoning about it.
- Re-parenting fixes hierarchy, never weight. Three separate fixes here were weight.
- When a fix does not move the number, the diagnosis was wrong — go back and measure again
  rather than tuning the fix.
