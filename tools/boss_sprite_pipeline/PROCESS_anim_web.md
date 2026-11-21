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

Map one clip: the button copies the BVH, runs `retarget_bvh.py` with that character's `--target` or rig+roles, copies an existing `base.glb` when the row has one, then `export_split.py --clips-only`. The glb path is stored on the clip's `maps`. A fit file at `anim_library/fits/<character>.json` is turned into env by `rigmap.fit.knob_env` (`barrel_chest` 1 → `CLAVICLE_DAMP` 0). `limb_reach` is stored and not passed. `IK_BODY` is a different dial.

Prompt: host and port of a Kimodo pod (not the outfit pod). `kimodo/serve_one.py` on the pod, model `Kimodo-SOMA-RP-v1`, one cell, BVH copied back into the library. The page does not start or stop the pod.

Tests, from the worktree, no Blender:

```
C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\Code\sprite_venv\Scripts\python.exe -m pytest tests/test_rigmap.py tests/test_anim_web.py -q
```

Barb recipe = the graded-good 2026-11-15 bake (`barb/anim_test/retarget_ik2/run.json`): `RETARGET_MODE` ik, `IK_BODY` 0.35, `BIND_MATCH` on, `BIND_SKIP` bone_0,bone_4 (hips, neck), arm cap 90, clavicle 1, root on, anunaki, rig `barb_final_nb.glb`. Set per character in `characters.json` (`mode`, `ik_body`, `bind_skip`); `run_map` passes them. Bind on without skipping bone_0 folds the hips (149° off); bind off leaves him upright. The panel's three fields cannot reach these.

`retarget_bvh.py` takes its soma and anunaki bone tables from `rigmap.legacy`. Gargoyle and G1 stay the tables in that file.

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| empty library | ANIM_DATA_ROOT points at a tree with no `kimodo_new_blender` | set it to the Boss worktree and delete a bad empty `index.json` so the next launch rebuilds it |
| map says no .venv-bpy | the worktree has no Blender venv | `ANIM_BPY` = Boss `tools\boss_sprite_pipeline\.venv-bpy\Scripts\python.exe` |
| the local lane is busy | one Blender at a time | wait; the log is the running bake |
| prompt: set the pod | no host/port | paste the pod's direct IP and TCP 22, not the outfit pod |
| stick is a point | BVH is centimetres | the page scales 0.01, same as the clip viewer |

## Log

- 2026-11-21 19:53: `barb_hit_heavy_01` → barb with the IK recipe, rc 0, 60 frames, `bones_driven` 22; run.json settings identical to retarget_ik2. Not yet graded by eye.

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

- Putting the panels on the outfit page (8767). That page is one `outfit.py` step per button, and its pod is TRELLIS / SAM3 / HoloPart.
