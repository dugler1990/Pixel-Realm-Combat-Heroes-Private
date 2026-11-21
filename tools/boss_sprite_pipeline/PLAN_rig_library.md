# Plan: rig library (rig a character, map motion onto it)

Written 2026-11-21. Replaces the "transfer" part of `~/.cursor/plans/animation_suite.plan.md` and
`retarget_paths_knobs_d4334792.plan.md`; keeps what they got right.

Goal: every technique that made a character usable is one named function with its settings exposed,
used from the anim page, recorded per character, and checked by a number. No character-specific code,
no bone numbers in code, no hidden defaults.

## State today

| Part | Where | State |
|---|---|---|
| roles, labellers, `match` | `rigmap/label.py`, `match.py` | built, tested, used by the page's match readout |
| `fit`, `edits` | `rigmap/fit.py` | built, tested, **not used by any bake** |
| bake settings | `rigmap/recipe.py` | stopgap: human / creature recipe, sent as env |
| motion transfer | `retarget_bvh.py` | one 900-line script; takes only the bone table from `rigmap` |
| pose check | `retarget_bvh.py` | built 2026-11-21, every bone vs the stick, 40° limit |
| rig fixes | `rigfix/*.py`, `face_parts.py`, `explode2/*.py` | one-off scripts, demon paths and bone numbers typed in |
| lost scripts | scratch | `add_wing_bones.py`, `sam_face.py`, head render, `jaw_check.py` gone; swordsman bind only in `%TEMP%\bind_barb_rig.py` |

## What each character's rig went through (from the notes and the files)

- **demon**: UniRig → hand roles (arms off by one) → wing bones (`add_wing_bones.py`) → jaw from SAM3
  (`face_parts.py`, `rigged_jaw.glb`) → `fix_wing_parent` → `fix_shoulder_parent` → wing weights →
  `fix_head_weights` → `fix_chest_weights` → `fix_smooth_weights` → `fix_jaw_hinge` →
  `rig/jaw/rigged_jaw_hinge.glb`. Exact order between 09-24 and 09-26 is not recorded; file times above.
- **barb**: UniRig (`gear_test/barb_base_rigged.glb`) → `anun_roles.py` (`barb_roles.json`) →
  `rig_reweight.py heat 0.5` + repaint → `rigfix/barb_final.glb` → `fix_neutral_bone.py` →
  `rigfix/barb_final_nb.glb`.
- **anunaki ×4, icewiz**: UniRig → `anun_roles.py`. No fixes.
- **swordsmen**: no rig. Barb armature bound by nearest vertex (scratch). Rough.
- **barb armour**: `outfit_skeleton.py` (bone heat on a voxel proxy of body + armour).

## The contract

1. **Roles.** One anatomical list (`rigmap` already has it): root, spine, spine2, chest, neck, head,
   clavicle/upper_arm/forearm/hand, thigh/shin/ankle/foot per side, eye.L/R, jaw; optional fingers,
   wings, tail. The off-by-one names (`elbow` = upper arm, `wrist` = forearm) are translated once in
   the labeller and nowhere else.
2. **Character file** `anim_library/characters/<id>.json`, the only config:
   - `recipe` (human / creature), current `rig` version, `roles` file
   - `rig_chain`: the rig steps applied, in order, each with its settings and output version
   - `map`: the mapping settings, including the per-bone table (below)
3. **Versions.** Every rig step writes `bosses/<id>/rig/v<N>.glb` + `v<N>.json` (step, settings, input
   version, check results). Nothing is overwritten.
4. **Every function** takes rig + roles + settings, returns a new version and a record. Pure Python
   where it can be (tested without Blender); Blender only to apply.

## Part 1: rig functions

| Function | From | Proven on | Settings exposed | Check |
|---|---|---|---|---|
| `unirig` | `gpu_box/unirig_cli.py`, PROCESS.md §6b | demon, anunaki, barb, icewiz | pod | bone count, `SKELETON_OK` |
| `roles` | `rigfix/anun_roles.py` | anunaki, barb, icewiz | manual override per role | labelled role set = human set |
| `reweight` | `rigfix/rig_reweight.py` | barb (heat 0.5 picked over smooth 150) | method heat / smooth, voxel %, iterations | `rig_check` weight jumps, pose sheet |
| `reparent` | `fix_wing_parent`, `fix_shoulder_parent` | demon | bone role → new parent role | owner map |
| `fix_weights` | `fix_head_weights`, `fix_chest_weights`, `fix_smooth_weights` | demon | region (role, inner/outer radius), blur passes | owner map, stretch map |
| `add_bone_geometry` | `add_wing_bones.py` (lost; rewrite from NOTES_rig_jaw_sam3 §2) | demon wings | vertex selection rule, parent role, segments | pose sheet |
| `add_bone_sam` | `face_parts.py` + lost SAM3 driver, head render, check sheet | demon jaw | prompts, views (front 15° elev + side yaw 90), falloff near/far, rear/top fades | check sheet rest / closed / open |
| `move_pivot` | `fix_jaw_hinge.py` | demon jaw | bone role, target (geometry top, sole) | check sheet |
| `rehome_orphans` | `explode2/fix_neutral_bone.py` | barb loincloth | none | 0 verts on `neutral_bone` |
| `copy_skeleton` | `explode2/outfit_skeleton.py`, swordsman scratch | barb armour; swordsmen (rough) | voxel %, scaling, method proxy-heat / nearest | 0 unweighted, pose sheet |
| `diagnose` | `owner_map`, `stretch_map`, `rig_check`, `neck_profile`, `dir_check` | demon, barb | which render | the images the steps above are judged by |

Rules carried from the notes: SAM3 wants a lit render and two views; never weight by a box, weight by
distance; verify every rig change with a fresh-process render; do not hand-map UniRig bones.

## Part 2: map functions

| Function | State | Change |
|---|---|---|
| `label`, `match` | built | none |
| `fit` | built, unused | measure at the **reference pose**, not the BVH rest (Kimodo rest lies along +X: every bone reads ~90°). Output per bone. |
| `bind` | inside `retarget_bvh.py` | own function. Per bone on/off from the table. Hard-coded neck skip removed. |
| `transfer` | inside `retarget_bvh.py` | own function: rotation delta, IK chains from roles (not typed `LeftArm`…), arm cap and clavicle damping per bone |
| `check` | pose check built | per bone, in the record and on the page; add the plan's knee, foot-floor, shoulder-width, added-bone checks |

`retarget_bvh.py` becomes a thin driver: load, `match`, `fit`, `bind`, `transfer`, `check`, save.
`TARGETS`, `PAIRS`, the profile layer and the demon fallback defaults are deleted; the command line
takes a character file like the page.

### Per-bone table (in the character file, edited on the page)

One row per paired role: `bind` on/off, `arm_cap` (upper arms), `clavicle_damp` (clavicles), the last
bake's pose-check angle, and for `fit` fields `measured` beside `override`. Whole-body fields stay:
`mode` (ik / rot), `ik_body`, `bind_ref`, `root_loc`, `source`.

Starting values come from the recipe: human = barb 2026-11-15 (`retarget_ik2`): ik, IK body 0.35,
bind on except root and neck, arm cap 90, clavicle 1, root on, frame 1. Creature = demon: rot, bind
off, arm cap 35.

## Locked references (tests; a refactor may not change them)

- barb `barb_hit_heavy_01` with the human recipe: same env as `retarget_ik2`
  (`tests/test_rigmap_recipe.py`), pose check ≤ 40° (29.4 on 2026-11-21).
- barb, bind on hips: pose check flags hips (149.3). Bind off: flags forearms (153.3).
- demon: creature recipe resolves to what the page sent before. One demon clip's pose-check numbers
  recorded before the refactor and equal after it.

## Experiments, not defaults (each measured with the pose check against the locked values)

1. Bind by joint-to-joint direction instead of bone +Y axes (should fix hips and head without a skip).
2. One idle pose as bind reference instead of frame 1.
3. Measured `limb_reach` instead of IK body 0.35.

## Page

- **Map panel** (exists): the per-bone table replaces barrel / arm cap / bind; whole-body fields
  editable; pose-check angle per bone after each bake.
- **Rig tab** (new): the character's `rig_chain` as a list; each step a button with its settings;
  a step's check images shown under it; a new version becomes current only when accepted.

## Order

1. Character file + per-bone table + page panel. `retarget_bvh.py` reads it; `recipe.py` becomes the
   starting values. Locked references pass.
2. Split `retarget_bvh.py` into `bind`, `transfer`, `check` in `rigmap`; delete `TARGETS` / fallbacks.
   Locked references pass with the same numbers.
3. `fit` at the reference pose, per bone, shown as measured beside override.
4. Rig functions, barb's chain first so it is reproducible: `roles`, `reweight`, `rehome_orphans`.
   Rig tab with those three.
5. `add_bone_sam` + `move_pivot` (rewrite the lost SAM3 driver, head render, check sheet), first on
   the barb jaw.
6. `reparent`, `fix_weights`, `add_bone_geometry`, `copy_skeleton`, `diagnose` generalised from the
   demon scripts.
7. Experiments 1–3.

Done when: barb and demon rigs are reproducible from their `rig_chain` in the app; a new UniRig
character goes chain → map → checks from the page with no code edit; locked references unchanged.

## Open

- Whether Kimodo clips move the `Jaw` / eye joints (decides if an added jaw is driven or only posed).
- The demon's rig-step order between 09-24 and 09-26 (only file times survive).
