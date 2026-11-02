# Fix the skin weights of a UniRig-rigged TRELLIS character

Started 2026-11-01 on the barb. A log written as the work happens, for refining into a repeatable
(and later automated) step. Scripts live next to this file; run them with the Blender venv
(`tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe`).

## Problem

The bare barb rigged by UniRig (`generated/bosses/barb/gear_test/barb_base_rigged.glb`) crinkles when
posed: shoulders and upper back with the arms up/forward, inner thighs in a step
(`generated/bosses/barb/explode/pose_body/POSE_body_tex.png`). Armour worn over him inherits it, so this
is step 1 before judging any armour.

## Diagnosis — `rig_check.py`

```
rig_check.py generated\bosses\barb\gear_test\barb_base_rigged.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\rig_check
```

- 712,077 vertices, 28 bones, at most 4 influences (mean 2.09). UV-seam copies agree exactly.
- Point-to-point the weights are smooth (median jump between neighbours 0), but every bone's
  influence ends in a ragged edge where the weight drops from ~0.15 straight to 0 (`WEIGHTS.png`):
  UniRig predicts on a sparse point cloud, keeps the top 4 bones and copies the result to the dense
  mesh by nearest point. 1.95 % of edges jump > 0.3. Those cut-offs are the crinkles.
- The shoulder cap belongs mostly to the chest bone, not the upper arm: lifting the arm leaves the
  deltoid behind.
- Role names: `arm_l.shoulder` (bone_6) is the collarbone-like bone; `arm_l.elbow` (bone_7) is the
  upper arm that turns at the shoulder joint.

## Fix — `rig_reweight.py` (same skeleton, new weights)

```
rig_reweight.py <rigged.glb> <out.glb> heat 0.5        # the pick
rig_reweight.py <rigged.glb> <out.glb> smooth 150      # close second
```

- **heat**: voxel-remesh a copy of the body into a watertight proxy (voxel = 0.5 % of height → 53k
  vertices; TRELLIS's own mesh is open/non-manifold and breaks Blender's solver), parent it to the
  armature with Blender's bone-heat automatic weights, transfer the weights onto the real mesh
  (Data Transfer, nearest face interpolated), keep the 4 strongest bones, normalise. 33 s.
- **smooth**: diffuse UniRig's own weights over the position-welded surface N times, keep top 4,
  normalise. 150 iterations ≈ 4.6 min.

Pose test (bare body, real paint, 6 poses × 4 views):

```
explode\explode_pose.py --texture <reweighted.glb> generated\bosses\barb\gear_test\barb_roles.json <out_dir>
```

Result (`generated/bosses/barb/rigfix/RIG_COMPARE.png`, close-ups `RIG_ZOOM.png`): UniRig crinkles
everywhere; smooth 40 leaves a little at the front shoulder; smooth 150 and heat 0.5 are clean. Heat
is the pick: weights from scratch (not a patch on UniRig's), seconds, works the same on any
character or armour piece; the shoulders lift with the arm.

Still there in every version: the chest/shoulders stretch wide with the arms raised 70° — weights
only decide which bone moves which skin; this is likely the shoulder joint's position. Next to check.

## Preserve Volume (dual quaternion) — tried, not better

`explode_pose.py --texture --dqs <heat0.5.glb> ...` (`rigfix/BODY_DQS_COMPARE.png`): the shoulders
balloon with the arms up/forward and the back widens. Plain (linear) skinning on the bone-heat
weights looks best, and it is what the in-game GPU skinning does anyway.

## Armour on the fixed rig: rigid plates — `explode_pose.py --rigid`

```
explode_pose.py --hide-body --texture [--rigid] generated\bosses\barb\rigfix\barb_heat0.5.glb generated\bosses\barb\gear_test\barb_roles.json generated\bosses\barb\rigfix\armour_heat shells=generated\bosses\barb\explode\shells_parts.glb
```

`--rigid` weights by piece (`rigid_weights` in explode_pose.py): head / breastplate / belt 100 % on
head / chest / root; arm, leg, gauntlet, boot plates each 100 % on the one bone they sit on (upper
arm or forearm, thigh or shin, ...), so they articulate at elbow and knee; pauldron 50 % collarbone +
50 % upper arm (the helper-bone trick); skirt root at the waist blending to 50 % thigh at the hem.

Result (`rigfix/ARMOUR_RIGID_COMPARE.png`: UniRig skin copy / bone-heat skin copy / rigid):
rigid wins — the breastplate keeps its shape with the arms up instead of stretching with the
chest; the pauldrons ride up with the arms. Left over: loose bits at the armpit where the cut edge
is ragged (the cut, not the weights).

## Current best barb (2026-11-02)

`generated/bosses/barb/rigfix/barb_final.glb` = repaint pass 2 (27 paintings incl. 16 close-ups at 2880�, 4096
texture, aligned, matte � `repaint/PROCESS_repaint.md`) + bone-heat weights. Poses:
`rigfix/pose_final/POSE_body_tex.png`. Still to paint: the 4 arm close-ups and leg_l_out; to regenerate
(would not align): face_left/right, back_upper, leg_r_out.

### Earlier best (2026-11-01)

`generated/bosses/barb/rigfix/barb_painted_heat0.5.glb` = the gpt-image-2 repaint
(`repaint/PROCESS_repaint.md`) + bone-heat weights (`rig_reweight.py ... heat 0.5`, 43 s). Poses:
`rigfix/pose_painted_heat/POSE_body_tex.png` — clean in all 6 poses; the chest/shoulder stretch with
the arms raised is the one thing left (joint position).

## Notes for the in-game mesh route

`PLAN_mesh_skinning.md` skins in a GPU shader with the top-4 joints/weights (linear blend). Anything
done here as weights (heat, smooth) carries over. Blender's "Preserve Volume" (dual quaternion)
option only helps renders made in Blender (the sprite route) unless the shader implements it too.
