# Animation suite

## Method that works

Worktree `feat/anim-suite` (`C:\Users\Douglas\Pixel-Realm-anim-suite`), off `main`. Do not run this from the ice-fog checkout.

```
cd C:\Users\Douglas\Pixel-Realm-anim-suite
$env:ANIM_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\Code\sprite_venv\Scripts\python.exe -m tools.boss_sprite_pipeline.anim_web
```

`http://127.0.0.1:8768/`. `--port`, `--no-browser`. Blender is the Boss `.venv-bpy` unless `ANIM_BPY` is set.

First launch writes `generated/bosses/anim_library/index.json` from `kimodo_new_blender/*.bvh` and `characters.json` (barb, demon, icewiz) when those roles files exist.

Map one clip: the button copies the BVH to `anim_library/stage/<id>`, runs `retarget_bvh.py --character <id> --version <rig> --source <clip source>` into `characters/<id>/bakes/<clip>/`, then `export_split.py` into `characters/<id>/view/v<rig>/` (base.glb once per rig version, then `--clips-only`). The index stores `maps.<id> = {glb, rig, bone_hash, bake}`; a bare string is a pre-2026-11-21 map.

Characters: `generated/characters/<id>/character.json` (decisions only: template, rig version, `map` block). Rig versions: `characters/<id>/rig/v<N>/` (record.json, canonical roles.json, rig.glb or a pointer for v1). Library: `tools/boss_sprite_pipeline/rigging/` (PLAN_rig_library.md). Migration once: `python -m tools.boss_sprite_pipeline.rigging.migrate` (barb, demon, icewiz, anun0-3 as v1).

Map settings: declared in `rigging/map/character.py` `MAP_SETTINGS`; the panel form is built from them; `/api/character` patches the map block (unknown key or out of range = 400). Per-role bind table; a role not listed follows `bind_default`. Templates `rigging/map/templates.py`: human = barb retarget_ik2 (ik, IK body 0.35, bind on except root+neck, arm cap 90, clavicle 1, root on, frame1); demon = rot, bind off (head listed off), arm cap 35, jaw closed 14. Pair exceptions `rigging/map/pairs.py` (g1 x demon: feet unbound).

Bake = `rigging/map/transfer.py` (pure numpy port of the old loop) on matrices read by `rigging/blender/pose_io.py`. `run.json`: rig version + bone hash, resolved settings with sources, bind flags, pairs, per clip pose check (`by_role`) and proportions (shoulder / arm / leg ratio over height, target vs source, at frame 1). Page shows them for the open clip; a bake whose rig bone hash differs from the current rig is STALE, a different version with the same bones is "older rig".

Pose check (`rigging/map/pose_check.py`): segment = driven bone -> its driven child along the chain (chest -> neck/head, clavicle -> upper arm), positions, every 5th frame + last, limit 40.

Locks (`tests/test_rigging_locks.py`, fixtures `tests/fixtures/rig_*.npz`, `rig_locks/*.json`), ±0.1°:

| barb_hit_heavy_01 | worst | note |
|---|---|---|
| human template | 29.4 neck | |
| rot, bind on hips | 149.3 hips | known failure |
| rot, bind off | 153.3 right forearm | known failure |
| human, neck bound | neck 1.3 (worst 22.0 right shin) | proves flags reach the bake |
| demon walk_v1_00, demon template | 60.9 left forearm | demon bakes already over 40 |

Old (pre-split) code vs new on the same inputs: every bone equal within 0.1 on all four; only the chest row differs because the old check measured chest -> first child in its table (barb: clavicle 25.8, now neck 9.7).

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| empty library | ANIM_DATA_ROOT points at a tree with no `kimodo_new_blender` | set it to the Boss worktree and delete a bad empty `index.json` so the next launch rebuilds it |
| map says no .venv-bpy | the worktree has no Blender venv | `ANIM_BPY` = Boss `tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe` |
| the local lane is busy | one Blender at a time | wait; the log is the running bake |
| prompt: set the pod | no host/port | paste the pod's direct IP and TCP 22, not the outfit pod |
| stick is a point | BVH is centimetres | the page scales 0.01, same as the clip viewer |

## Log

- 2026-11-21: rigging library phases 1-4: `rigmap` -> `rigging` (roles, sources, settings, rig/version, map/{match,bind,transfer,pose_check,proportions,templates,pairs,character}, blender/pose_io). `retarget_bvh.py` is a driver; TARGETS/PAIRS/profile/env knobs/legacy.py/recipe.py/fits/DEFAULT_CHARACTERS gone. 7 rigs imported as v1. Page bake of barb_hit_heavy_01 via `--character barb`: rc 0, 29.4. Proportions shoulder width moved from clavicle heads to upper-arm heads (clavicles read 4.4x on the barb; now 1.14; demon 1.81).

- 2026-11-21: Kimodo jaw / eyes static. First 40 of 312 clips, rotation range: `Jaw` max 1.1° (median 0.4), eyes max 3.7° (0.5), `Head` max 46° (20). An added jaw is posed or procedural, not driven.

- 2026-11-21: `barb_hit_heavy_01` → barb with the human recipe from the page, rc 0, 60 frames, 22 bones, `recipe.json` env identical to retarget_ik2, pose check ok (29.4). Not yet graded by eye. Knob keys removed from `characters.json` rows and `DEFAULT_CHARACTERS`. Icewiz moves from rot/no hip skip to the human recipe; not rebaked.

- 2026-11-17: page, `rigmap` (label, match, fit, legacy soma/anunaki paths), `serve_one.py`. No rebake of the 312. Jaw weights stay `face_parts.py`.
- 2026-11-17: `--target` resolved the rig under this worktree, so the bake looked for `generated/` here and missed the Boss files. Map now passes absolute rig and roles, and sets `SOURCE`, `ARM_ELEV_CAP`, `BIND_MATCH` from the character row. `rigmap` uses relative imports so Blender's `from rigmap.legacy` loads.
- 2026-11-17: barb source is `anunaki` (22 paths, Head on `head`). `soma` is the demon table (20 paths, Head on the key `neck`) and the first bake drove 20. Rebake of `walk_v1_00`: `bones_driven` 22, `ARM_ELEV_CAP` 90, `BIND_MATCH` false, `BIND_SKIP` bone_4 (the neck). Clip `bosses/barb/viewer/anim_suite/clips/walk_v1_00.glb`. Stick and mapped both on screen at 127.0.0.1:8768.
- 2026-11-17: ice wizard `walk_v1_00`, positional, `bones_driven` 22, `BIND_SKIP` bone_4. Base written `bosses/icewiz/viewer/anim_suite/base.glb` (59.9 MB). Wizard visible in the mapped pane.
- 2026-11-17: `barb_hit_heavy_01` → barb from the button, rc 0, 60 frames, export 143s. Log was only Blender's "zero length bone" lines until the end, so the click looked dead. Header now says running/done, and a finished map reloads the open clip.
- 2026-11-17: the clip is saved and the mesh was on screen, standing. The hit is mid-clip (hip.R 49 deg, elbow.L 38) and the last frame is nearly the rest pose (root 4 deg). The two panes ran on separate clocks, and the 68 MB base loads after the stick has already moved, so the barb was on the standing part. One `showTime` now drives both, and the bar sets it.
- 2026-11-17: that was not the whole miss. `barb_hit_heavy_01` frame 1 is already the pose (left forearm 85 deg, left leg 147 deg). Bind match was forced off, so the bake threw that pose away and the mesh only played the change. Rebaked with bind match on. Limb directions against the source: 0 deg at frame 1 and frame 30 for both arms and both legs. Head stays 37 deg off (face axis versus crown). Clip replaced in `bosses/barb/viewer/anim_suite/clips/barb_hit_heavy_01.glb`. Humans now bind-match unless the row says otherwise.
- 2026-11-17 17:39: user rebake of `barb_hit_heavy_01`, `ARM_ELEV_CAP` 90, `CLAVICLE_DAMP` 0 (barrel 1), `BIND_MATCH` true. The box was forced back on every 1.5 s by `syncFit`, so the untick never reached the bake. `syncFit` now runs only when the character changes.
- 2026-11-17 12:53 `walk_v1_00` (the standing barb): `BIND_MATCH` false, `ARM_ELEV_CAP` 90, `CLAVICLE_DAMP` 1 (barrel not set), `SOURCE` anunaki, `ROOT_LOC` true, `mode` rot, 22 bones, `BIND_SKIP` bone_4. `run.json` in `barb/anim_suite/walk_v1_00`.
- 2026-11-17 14:01 `hit_bind` and 2026-11-19 20:15 user rebake are the same settings with `BIND_MATCH` true. Arms and legs measured 0 deg from the source. Hips measured 149 deg off, head 37 deg off. That is the squashed pose. The panel has no control to bind-match the limbs and skip the hips.

## Tried and dropped

- `rigmap.fit()` `bind_skip` (axis_error > 45°) as the bake's skip list, 2026-11-21: not wired. It compares rest poses; the Kimodo BVH rest has every bone along +X (hips→spine, arms, legs all (1,0,0)), so every bone reads ~90°. And the hip fold is a bone-axis mismatch, which joint-position directions do not see. The pose check catches it instead.
- Putting the panels on the outfit page (8767). That page is one `outfit.py` step per button, and its pod is TRELLIS / SAM3 / HoloPart.
