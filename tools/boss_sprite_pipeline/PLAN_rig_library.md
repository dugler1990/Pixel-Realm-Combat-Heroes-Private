# Plan: rigging library (rig a character, map motion onto it)

Written 2026-11-21, rewritten the same day after two reviews. Replaces the transfer part of
`~/.cursor/plans/animation_suite.plan.md` and `retarget_paths_knobs_d4334792.plan.md`.

Goal: every technique that made a character usable is a named step with declared settings, run from the
anim page, recorded per rig version, and checked by numbers. No character code, no bone numbers in code,
no hidden defaults.

## State today (feat/anim-suite)

| Part | Where | State |
|---|---|---|
| role list, labellers, `match` | `rigmap/label.py`, `match.py` | built, tested, used by the page's match readout |
| `fit`, `edits` | `rigmap/fit.py` | built, tested, not used by any bake |
| bake settings | `rigmap/recipe.py` | stopgap human / creature recipes, all 9 knobs sent as env |
| motion transfer | `retarget_bvh.py` | 900-line script; takes only the bone table from `rigmap.legacy` |
| pose check | `retarget_bvh.py` | every driven bone vs the stick, worst per bone in `run.json` |
| rig fixes | `rigfix/*.py`, `face_parts.py`, `explode2/fix_neutral_bone.py` | one-off scripts, demon paths and bone numbers typed in |
| lost | scratch | `add_wing_bones.py`, `sam_face.py`, head render, `jaw_check.py`; swordsman bind only in `%TEMP%\bind_barb_rig.py` |

Measured 2026-11-21, first 40 of the 312 Kimodo clips: `Jaw` rotates at most 1.1° (median 0.4), eyes
3.7° (0.5), `Head` 46° (20). Kimodo does not move the jaw or eyes. An added jaw or eye bone is posed
(held, e.g. jaw closed) or procedural, never driven by the clip.

## Rig histories (become the v1 records)

- **demon**: UniRig → hand roles (arms off by one) → wing bones (`add_wing_bones.py`) → jaw from SAM3
  (`face_parts.py` → `rig/jaw/rigged_jaw.glb`) → `fix_wing_parent` → `fix_shoulder_parent` → wing
  weights → `fix_head_weights` → `fix_chest_weights` → `fix_smooth_weights` → `fix_jaw_hinge` →
  `rig/jaw/rigged_jaw_hinge.glb`. Order between 09-24 and 09-26 not recorded; only file times.
- **barb**: UniRig (`gear_test/barb_base_rigged.glb`) → `anun_roles.py` (`barb_roles.json`) →
  `rig_reweight.py heat 0.5` + repaint (manual) → `rigfix/barb_final.glb` → `fix_neutral_bone.py` →
  `rigfix/barb_final_nb.glb`.
- **anunaki ×4, icewiz**: UniRig → `anun_roles.py`.
- **swordsmen**: no rig of their own; barb armature by nearest vertex (scratch, one bound at 180°).
- **barb armour**: `explode2/outfit_skeleton.py`. Owned by the outfit pipeline, not this library.

## Library layout

```
tools/boss_sprite_pipeline/rigging/      (was rigmap/)
  roles.py          the role list + chains (arm = upper_arm-forearm-hand, leg = thigh-shin-ankle, wing, tail, fingers)
  sources/          one file per motion source: labeller, converter, rest convention
    soma.py           Kimodo/SOMA (rest along +X; jaw and eyes static)
    g1.py             uses g1_to_bvh.py
    gargoyle.py       uses gargoyle_to_bvh.py
  settings.py       Setting(name, type, default, range, doc); resolve() records each value's source
  rig/              rigging a character: slow, once per character
    version.py        rig version = glb + roles + bone list + record; the only code that numbers versions; import_v1
    steps/            one file per step; each declares its settings and its checks
      unirig.py  roles_walk.py  reweight.py  transfer_weights.py  blur_weights.py
      reparent.py  move_pivot.py  add_bone.py  rehome_orphans.py  copy_skeleton.py  manual.py
    checks/           numbers + optional image, each marked gate or info
      weight_jumps.py  owner_map.py  stretch.py  pose_sheet.py
  map/              mapping motion: pure maths, no Blender
    skeleton.py       (was bvh.py)
    match.py
    proportions.py    (was fit.py) measured at the one reference pose
    bind.py  transfer.py  pose_check.py
    templates.py      (was recipe.py) human, demon
    pairs.py          source x character exceptions (demon + G1: skip the feet)
    character.py      the character file: load, validate, migrate
  blender/          the only folder that imports bpy
    runner.py         blender_run <step> <in.glb> <settings.json> -> out.glb + record.json, fresh process
    pose_io.py        read bone matrices, write poses
```

Renames: `rigmap` → `rigging`; `fit` → `proportions` (bind skips no longer come from it); `recipe` →
`templates` (copied once, never applied live); `creature` → `demon` (his settings, not a general
creature); `edits()` → `add_bone` placement `joint`; `legacy.py` deleted (becomes `sources/soma.py`).

## Data layout

```
generated/characters/<id>/
  character.json      current rig version + mapping decisions
  rig/v<N>/           rig.glb, roles.json, record.json   (v1 = today's rig, imported; points at the old file)
  bakes/<clip>/       run.json (rig version, resolved settings, pose check) + glb
generated/bosses/anim_library/   the clip index, stays
```

Nothing under `generated/bosses/` is moved.

## The rig version (where rigging and mapping meet)

A rig version is `rig.glb` + `roles.json` + bone list + `record.json`. The map side reads only that.

`record.json`: step, resolved settings with sources, input version, check results, who/when, and for
`manual` the reason. Roles live in the version because steps change them (`add_bone` adds `jaw`,
`reparent` changes parents).

A rig step is `vN + settings → vN+1 + record`. The chain is read by following input links back from the
current version; there is no separate chain list. Two steps from the same input are branches (heat and
smooth both from v3; keep one). A version becomes current only when accepted; accept is blocked until
every gate check in its record passes. One writer (`version.py`) assigns N, so the local lane and the
pod lane never take the same number.

Steps are one of two kinds:
- **weights-only**: same bone set. Existing bakes stay valid.
- **bone-set changing** (`add_bone`, `reparent`, `unirig`, `manual` when it changes bones): every bake
  and every outfit built on an older version is flagged stale on the page.

## The character file (decisions only)

`characters/<id>/character.json`:
- `rig`: current version, e.g. `v3`
- `template`: which template it was copied from (record only; editing the template later does not
  change the character)
- `mode` (ik / rot), `ik_body`, `root_loc`, `reference_pose`
- `bind`: per role, on/off, only roles that differ from the template
- `arm_cap`: upper arms (the fused-armpit fact is about that bone)
- `clavicle_damp`: one value for the pair
- `jaw_closed`: degrees, when the rig has a jaw

Not in it: pose-check angles, proportions, axis errors (results: they go in the bake's `run.json`, the
page shows them beside the decision for the open clip); the source skeleton (a property of the clip);
source × character exceptions (`map/pairs.py`).

`reference_pose` is one setting used by both `proportions` and `bind`: `frame1` (today, graded good)
or an idle pose file. Until a shared idle is the reference, the page shows proportions for the open
clip and does not save them.

Templates (`map/templates.py`):
- **human** = barb bake graded good 2026-11-15 (`barb/anim_test/retarget_ik2`): ik, IK body 0.35,
  bind on except root and neck, arm cap 90, clavicle 1, root on, frame1.
- **demon** = what the page sent the demon: rot, bind off, arm cap 35, jaw closed 14.

## Settings and checks

Every step and the map side declare their settings in `settings.py` form: name, type, default, range,
one-line doc. The page builds its forms from the declarations; the command line validates against them;
records store each resolved value with its source (template / character / panel). Calling `transfer`
without a required setting raises.

A check returns numbers plus an optional image, with its pass threshold in the declaration, and is
**gate** (blocks accept) or **info**. Pose check measures transfer (mesh bone vs stick); `stretch`
measures mesh damage (worst edge stretch over the pose sheet). Both on every bake.

## Rig steps

| Step | Kind | From | Proven on | Settings | Checks |
|---|---|---|---|---|---|
| `unirig` | bone set | `gpu_box/unirig_cli.py`, PROCESS.md §6b | demon, anunaki, barb, icewiz | pod (pod lane) | bone count |
| `roles_walk` | bone set (labels) | `rigfix/anun_roles.py` | anunaki, barb, icewiz | per-role override patch | required roles present, optional recorded, rest unmapped (stay at rest) |
| `reweight` | weights | `rigfix/rig_reweight.py` | barb: heat 0.5 | method heat / smooth, voxel %, iterations | weight jumps (gate), pose sheet |
| `transfer_weights` | weights | `fix_head_weights`, `fix_chest_weights` | demon | from roles, to roles, axis, inner / outer radius, protected role | owner map, stretch |
| `blur_weights` | weights | `fix_smooth_weights` | demon | passes, held-out role | weight jumps, stretch |
| `reparent` | bone set | `fix_wing_parent`, `fix_shoulder_parent` | demon | role → new parent role | owner map |
| `move_pivot` | bone set | `fix_jaw_hinge.py`, pivot part of `fix_head_weights` | demon jaw, skull | role, target (geometry top / sole / point) | pose sheet; independent of any weight cut |
| `add_bone` | bone set | see placements | demon wings, jaw | placement, parent role, falloff near / far, fades | pose sheet, check sheet |
| `rehome_orphans` | weights | `explode2/fix_neutral_bone.py` | barb loincloth | none | 0 verts on `neutral_bone` (gate) |
| `copy_skeleton` | bone set | `outfit_skeleton.py` (proxy heat), swordsman scratch (nearest) | swordsmen (rough) | method, voxel %, scaling, facing | 0 unweighted (gate), pose sheet. Out of every template until a pose sheet is accepted. |
| `manual` | either | — | barb repaint, demon hand roles | glb, reason | all gate checks of the declared kind |

`add_bone` placements; the weight rule is always distance (never a box):
- `joint`: the source joint's rest offset from its parent (eyes, jaw). Was `rigmap.fit.edits`.
- `geometry`: vertex extremes (the demon wings, NOTES_rig_jaw_sam3 §2).
- `sam`: lit render, front 15° elevation + side yaw 90; local SAM3 (`C:\Users\Douglas\sam3local`);
  union of instances filtered by a height band (scores do not rank by extent); pixels → vertices by a
  world-position render (`face_parts.py`), not the UV atlas.

Added bones with no moving source joint (jaw, eyes, wings, tail): held at a setting (`jaw_closed`) or
driven by the procedural layer (`animate_procedural.py`). Never mapped from a static Kimodo joint.

`diagnose` is not a step. Owner map, stretch map, weight jumps and pose sheet are checks inside a step's
record.

What worked and what did not (heat 0.5 over smooth 150, no hand-mapping UniRig bones, no box weighting,
lit two-view SAM, fresh-process verification) goes in `PROCESS_rigging.md`, Method and Tried and dropped,
not repeated here.

## Map functions

| Function | Today | Change |
|---|---|---|
| `skeleton`, `match` | `bvh.py`, `match.py` | renamed / kept |
| `proportions` | `fit.py`, rest pose | at `reference_pose`; shoulder width, chain length ratios. `axis_error` dropped (tried 2026-11-21: Kimodo rest gives ~90° everywhere; blind to the hip fold) |
| `bind` | in `retarget_bvh.py` | pure function; per-role flags from the character file; the hard-coded neck skip removed |
| `transfer` | in `retarget_bvh.py` | pure function: rotation delta, IK chains from `roles.py` (not typed `LeftArm`), arm cap, clavicle damp, jaw closed |
| `pose_check` | in `retarget_bvh.py` | pure function, same numbers |

`retarget_bvh.py` becomes a driver: `pose_io` reads matrices, `map/` computes, `pose_io` writes.
`TARGETS`, the profile layer and the demon fallback defaults are deleted. `PAIRS` moves to
`map/pairs.py`. The command line takes a character file, like the page.

Pure functions get fixtures: source and target matrices for the locked clips, saved once from Blender,
so a refactor is tested without a bake.

## Migration (step 2)

| Today | Becomes |
|---|---|
| `anim_library/characters.json` | `characters/<id>/character.json` |
| `DEFAULT_CHARACTERS` in `anim_web.py` | deleted; new characters copy a template |
| `anim_library/fits/<id>.json` | merged into the character file |
| `rigmap/recipe.py` | `map/templates.py` |
| `rigmap/legacy.py` | deleted; `sources/soma.py` + labellers |
| `TARGETS`, profile, fallbacks in `retarget_bvh.py` | deleted |
| `PAIRS` | `map/pairs.py` |
| `recipe.json` beside each bake | `run.json` holds the resolved settings |

## Locked references (tests)

Each lock is a recorded number within ±0.1°, not a ceiling.
- barb `barb_hit_heavy_01`, human template: env equals `retarget_ik2` (`tests/test_rigmap_recipe.py`);
  pose check 29.4 on the neck.
- the known failures stay failures: bind on the hips 149.3 (hips); bind off 153.3 (right forearm).
- neck bound (not skipped) on the same clip: angle recorded before the split, so the hard-coded neck skip
  cannot survive inside `bind`.
- demon: one named clip, per-bone angles recorded before the split.
- pair sets: demon 20, barb 22 (`tests/test_rigmap.py`).
- `transfer` without a required setting raises.

## Experiments (not defaults; judged by the pose check and stretch against the locks)

1. Bind by joint-to-joint direction instead of bone +Y axes. Judged only by the hip (149.3) and head
   angles with the hips not skipped.
2. A shared idle as `reference_pose` instead of frame1. Makes proportions a character property.
3. IK body set from the measured arm-length / height ratio (target vs source). IK body stays a blend
   (0 = rotation copy, 1 = hip-anchored); record both the ratio and the blend.

## Page

- **Map panel**: per-role bind flags, arm cap, clavicle, jaw closed, mode, IK body, reference pose,
  root; forms built from the declarations; per-bone pose-check angle and stretch from the open bake
  beside each decision; stale bakes flagged.
- **Rig tab**: the current version and its input links back to v1; each registered step a button with
  its declared settings; local lane for Blender steps, pod lane for UniRig and SAM; check results and
  images under each new version; accept blocked until gates pass.

## Order

1. `rig/version.py` + `settings.py`. Import barb, demon, anunaki ×4, icewiz as v1 with their histories.
2. Character file + migration table above. Locked references pass.
3. Record the locks that need a before value (neck bound, one demon clip). Save fixtures. Split `bind`,
   `transfer`, `pose_check` into `map/`; driver deletes `TARGETS` and fallbacks. Locks pass within ±0.1°.
4. `proportions` at the reference pose.
5. `blender/runner.py`; steps `roles_walk`, `reweight`, `rehome_orphans`, `manual`; Rig tab from the
   registry; stale flags.
6. `add_bone` (joint, geometry, sam) and `move_pivot`. The sam path is proved by replaying it on the
   demon head against `rig/jaw/rigged_jaw_hinge.glb` (parents, role labels, weight checks). Then the
   barb jaw.
7. `transfer_weights`, `blur_weights`, `reparent`, `copy_skeleton` generalised from the demon scripts.
8. Experiments 1-3.

Done when: a new UniRig character is a copied template plus `unirig` and `roles_walk`, then map and
checks from the page with no code edit; the barb chain replays (manual steps included) to a rig that
passes its checks; the locks hold. The demon chain is done when a replay matches the hinge-glb oracle,
whatever the historical order was. Reproducing the demon is not required for the rest.

## Open

- The demon's rig-step order between 09-24 and 09-26 (only file times). Does not block anything.
