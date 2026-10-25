# Plan — skin the mesh boss on the GPU

Written 2026-09-26. Follows `PLAN_ingame_both_methods.md`. Method B is in the running
game (`Graphics/Meshes/demon`, `Code/mesh_boss.py`, `GPUBackend.draw_mesh_boss`). It is
too expensive to keep: one demon is already under the 30 fps cap, three are not playable.
This plan is the fix.

The cap is 30 fps (`GameSettings.fps_cap_index` 0, `clock.tick`). A frame under that ran
long. Measured on this machine, debug overlay on, camera on the boss:

| | Frame time | About | RAM |
|---|---|---|---|
| 1 sprite demon | 34 ms | on the cap | 880 MB |
| 1 mesh demon | 79 ms | ~13 fps | 1300 MB |
| 3 mesh demons | 259 ms | ~4 fps | 1308 MB |

Target after this plan: **20 mesh demons at 30 fps**, one shared pack, RAM near the size
of one mesh plus its texture. That number is a target, not a measurement. The current
stall is the per-frame Python upload, and that is what this removes.

## Why it is slow

`export_mesh_runtime.py` bakes every posed vertex, and `draw_mesh_boss` rebuilds that
buffer every frame:

- 154,439 vertices, 120,000 triangles
- each new frame: `float16 → float32`, concat normals and UVs, `glBufferSubData` of about **4.9 MB**
- the pack is **443 MB** because it stores all 390 frames (`settle_01` + `walk`)
- sprite sheets are still loaded, because masks and the hitbox still come from method A
- one VBO is shared and rewritten, keyed by pack name, so two demons on different frames upload twice

A game engine leaves one mesh in GPU memory and uploads bone matrices, a few kilobytes.
The vertex shader poses the mesh. Twenty demons then share that mesh.

120k triangles is not the thing that made three demons take 259 ms. That cost is the
Python rebuild. Triangle count is a later pass, after skinning matches the current look.

## What stays

- `MeshBoss.set_action`, `advance`, `draw(backend, screen_pos, facing_deg, height_px)`.
  Callers in `combat_unit.py` and `YsortCameraGroup._draw_sorted_sprite` do not change.
- Clips stay `settle_01` (idle, half of 24 fps) and `walk`. Same blends as the current pack.
- Triangle budget stays **120000** for the first skinned export, so a difference is skinning,
  not a new decimate.
- CPU backend `draw_mesh_boss` still returns `False`. A mesh demon with no GL falls back
  to the sprite blit.
- Classic sprite demons keep the current blit. A unit with no `mesh_boss` is unchanged.

## Pack format

Replace the `[frames, V, 3]` position stack. After the same rest-pose decimate, write:

| Array | Shape | Notes |
|---|---|---|
| `rest_pos` | `[V, 3]` float16 | rest pose, same space as today's pivot |
| `rest_nrm` | `[V, 3]` int8 | rest normals |
| `uv` | `[V, 2]` float16 | unchanged |
| `indices` | `[T, 3]` uint32 | unchanged, uploaded once |
| `joints` | `[V, 4]` uint16 | top 4 vertex-group influences, after decimate |
| `weights` | `[V, 4]` float16 | renormalized to sum to 1 |
| `skin_mats` | `[frames, B, 4, 4]` float32 | skin matrix per bone per frame |
| `ranges`, `fps`, `pivot`, `bbox` | as now | playback unchanged |

`pack.json` gains `bones` (count) and `influences: 4`. No `positions` / `normals` frame stacks.

Skin matrix for pose bone `pb`, in the same space as `rest_pos`:

```
pb.matrix @ pb.bone.matrix_local.inverted()
```

then the mesh object's rest `matrix_world`, matching what `to_mesh()` * `matrix_world` does
today. Normals use the upper 3×3.

Size, for this demon, order of magnitude: one mesh is under 10 MB, 390 frames of ~150
bone matrices is a few MB. Shared by every instance. Confirm `B` with the probe below
before locking the uniform path.

Weights must be read **after** the decimate. The current exporter already deforms that
decimated mesh with the armature, so the vertex groups survive collapse. If a probe shows
they do not, stop and fix the export before writing a shader.

## Phase 0 — probe

One bpy run on `animate_idle4/animated.blend` after the same 120k decimate:

- bone count that actually influences the mesh
- max influences per vertex, and how many vertices need more than 4
- a dumped rest-pose AABB to compare with `pack.json` `bbox`

Top-4 is the shader format. If a large share of vertices carry a 5th weight above ~0.05,
the jaw / wing / chest work can shift. Gate: do not proceed on a guess. Either accept
top-4 after the Phase 1 image compare, or raise the shader to 8.

Palette storage is a uniform buffer object (`#version 330 core` already). A `mat4`
uniform array is the wrong default: a few hundred bones can exceed
`GL_MAX_VERTEX_UNIFORM_COMPONENTS`.

## Phase 1 — exporter

Extend `tools/boss_sprite_pipeline/export_mesh_runtime.py`. Same CLI, same
`--only settle_01,walk` and the extra walk blend.

For each frame, record bone matrices only. Do not call `to_mesh()` in the loop.

Also write **one** baked frame (frame 0 of `settle_01`, and one mid-walk frame) to a
side file `skin_check.npz`: the current `to_mesh()` positions. The runtime does not
load it. It exists so Phase 2 can diff shader output against the method that is on
screen today.

Re-export to `Graphics/Meshes/demon`. Keep the old `mesh.npz` until Phase 2 draws.

## Phase 2 — shader and upload

`GPUBackend.draw_mesh_boss`:

- Static VBO once per pack: `rest_pos`, `rest_nrm`, `uv`, `joints`, `weights`. EBO once, as now.
- Per draw: bind that VBO, upload `skin_mats[frame]` into the UBO, set the existing
  uniforms (`origin`, `pivot`, `scale`, `yaw`, `elev`, light).
- Vertex shader: `pos = sum(weight[i] * skin_mats[joint[i]] * rest_pos)`, same for
  the normal, then the current yaw / elevation / pixel projection. Fragment shader unchanged.
- Two demons on different frames no longer rebuild a shared vertex buffer. They bind
  the same mesh and upload their own palette.

`MeshBossPack` loads the new arrays. `frame_index` still selects the pose.
`MeshBoss.draw` signature stays.

Gate, in order:

1. Max position error against `skin_check.npz` under a few millimetres of the mesh height
   (~0.83 units). If it is larger, the matrix space is wrong. Fix that before judging pictures.
2. Smoke shot, same camera as `logs/mesh_boss_ingame_smoke.png`. He should match the
   current posed demon.
3. In-game shot, one demon, `PRCH_BENCHMARK_ENEMY_TYPE=demon`. Feet on the hitbox, idle
   playing at half speed.

## Phase 3 — stop paying for sprites on a mesh demon

When `mesh_boss` is set, do not walk the 8-direction folders. Masks and y-sort use a
fixed hitbox from the pack bbox (width from XY, feet at the pivot, height from
`height_units`). One sprite frame may still be loaded if something in `Entity` requires
`self.image` for the rect. It must not be the 383 MB pack.

`PRCH_MESH_BOSS=0` still loads sprites and blits them. That is the classic demon.

Per-spawn choice, so both can stand in one level: a spawn field `mesh: false` skips
`MeshBoss` for that unit even when the pack exists and the global flag is on. Default
stays "mesh if the pack exists".

## Phase 4 — measure

Same arena, camera on the first demon, overlay off this time. Counts: 1, 3, 20.
Record frame time, fps against the 30 cap, and RSS after spawn.

Done when:

- 20 mesh demons hold 30 fps (frame time ≤ 33 ms)
- RSS stays in the range of one pack, not 20 × 443 MB
- idle and walk still follow `status`
- a classic demon (`mesh: false`) still blits in the same scene

If 20 misses 30 fps and a profile shows the rasterizer rather than Python, Phase 5.
If the miss is still Python, the palette upload or the sprite load is still on the
hot path. Do not cut triangles to hide that.

## Phase 5 — triangles, only if Phase 4 says so

Re-export a short series (60k, 40k, 30k) and compare at 650 px against the 120k shot.
20k tore the texture before; do not jump there. Pick the lowest count that does not
tear, then rerun the 20-demon bench.

Instancing twenty demons into one draw call is not part of this plan. Twenty skinned
draws of a resident mesh is enough for the target. Add instancing only if the Phase 4
profile shows draw-call overhead, which 20 calls will not.

## Out of scope

- A contact shadow. Sprites have one baked in. The mesh still does not.
- Depth between two mesh bodies. `glClear(GL_DEPTH_BUFFER_BIT)` per draw stays, so
  overlapping demons still intersect wrong. Y-sort against the world is unchanged.
- New clips. Wings, jaw, and attacks stay out until idle and walk match. Adding a clip
  is another export, not a shader change.
- Re-rendering method A.

## Order

1. Phase 0 probe.
2. Phase 1 export and the baked check frames.
3. Phase 2 shader, until the smoke shot matches.
4. Phase 3 sprite skip and the per-spawn `mesh` flag.
5. Phase 4 bench. Phase 5 only if the bench asks for it.
