# Plan — getting the boss on screen, both methods

Written 2026-09-22. Companion to `PLAN_d2_and_animation.md` (which ends at "frames installed")
and `NOTES_rig_jaw_sam3.md` (rig). This covers the part neither document has: **actually
drawing him in the running game**, for the sprite route and the mesh route, and choosing.

## 0. What exists right now

| Piece | Path | State |
|---|---|---|
| Sprites (method A) | `Graphics/Monsters/demon/` | **installed**, 383 MB, 5 actions x 8 dirs, per-frame trim + per-frame anchors |
| Mesh pack (method B) | `Graphics/Meshes/demon/` | **installed**, 210 MB, 120k tris, 177 frames |
| Sprite loader | `Code/combat_unit.py::import_graphics_8dir` | works; eager on `main` — lazy version on `dev_3d_boss`, see HANDOFF_ingame_boss.md "Lazy loading" |
| Per-frame anchor | `Code/Entity.py::_frame_anchor_px` | works |
| Mesh runtime | `Code/mesh_boss.py` + `render_backend.GPUBackend.draw_mesh_boss` | **verified rendering a posed, lit, textured frame** (`MESH_TEST.png`) |
| Stats entry | `Code/Settings.py` `monster_data["demon"]` | added (health 2500, melee radius 260, notice 1600) |
| **Gap** | `Code/YsortCameraGroup.py` | draws `sprite.image` only — **never calls `draw_mesh_boss`** |
| **Gap** | spawn | no map object or debug key spawns `demon` |

So method A is one spawn away from being visible; method B needs a draw hook first.

## PART 1 — Method A in game (sprites)

1. **Spawn him.** Cheapest is the benchmark path that already exists:
   `PRCH_BENCHMARK_ENABLED=1 PRCH_BENCHMARK_ENEMY_TYPE=demon PRCH_BENCHMARK_ENTITY_COUNT=1`,
   or a Tiled object of type `demon`. No code change either way.
2. **Gates, in order:**
   - loads without exception (the manifest path and `monster_data` entry are both new);
   - stands on the hitbox — his feet, not his knees, at the anchor pixel;
   - turning changes direction folder: walk a circle around him and watch all 8;
   - `idle -> move -> attack` follow the AI's status;
   - **FPS before/after** with him on screen, and again with 3 of him.
3. **Numbers to write down** (these decide everything later): first-load stall in ms, resident
   MB after all 8 directions are touched, steady FPS with 1 and with 3 bosses.

Known risks: first entry into a direction decodes ~36 PNGs (visible hitch — mitigation is a
prewarm on the loading screen); `pygame.mask.from_surface` on a 749x428 frame is a few ms each,
built lazily per direction; the GPU atlas only accepts sprites <= 512 px, so every boss frame
takes the `_large_cache` path (one GL texture per frame, uploaded on first draw, never freed).

## PART 2 — Method B in game (mesh)

The renderer works standalone; what is missing is a place in the frame where it is called, and
a way for a unit to say "draw me as a mesh".

1. **`CombatUnit` gets an optional mesh.** In `import_graphics_8dir`-time: if
   `MeshBossPack.exists(name)` and settings allow, build a `MeshBoss`, keep the sprite frames
   **as well** (they still drive masks, hitbox size and y-sort) but skip drawing the sprite.
2. **`YsortCameraGroup.custom_draw` hook.** Where it blits a sprite, first check
   `getattr(sprite, "mesh_boss", None)`; if present call
   `boss.draw(self.backend, screen_pos, facing_deg, height_px)` and skip the blit. Ordering is
   free: it happens at that sprite's y-sort position like any other.
3. **Facing is an angle, not a bucket.** The sprite route snaps to 8 directions; the mesh takes
   the real heading, so pass the continuous angle — that alone will look better than method A.
4. **Playback.** `boss.set_action(unit.status)` and `boss.advance(dt)` each frame; the pack's
   per-action ranges already match the sprite action names.
5. **Gates:** same list as Part 1, plus: does he composite correctly *behind* trees and *in
   front of* ground (depth is cleared per boss, so he is one sorted object); does the turntable
   angle match where he is walking.

Risks: the mesh pass clears the depth buffer each call, so two mesh bosses cannot intersect
each other correctly (fine for one boss, revisit for many); `mesh.npz` is 210 MB loaded as
numpy — it should be memory-mapped (`np.load(..., mmap_mode="r")`) so only the frames actually
played are paged in.

## PART 3 — The comparison that decides it

Same scene, same camera, same boss, one flag apart. Record for each:

| Metric | Method A (sprites) | Method B (mesh) |
|---|---|---|
| Disk | 383 MB | 210 MB |
| Resident RAM after 8 dirs | ? | ? (mmap) |
| First-appearance stall | ? | ? |
| FPS, 1 boss / 3 bosses | ? | ? |
| Visual at 650 px | ? | ? |
| Angles | 8 | continuous |
| Cost to change an animation | ~70 min re-render | ~40 s re-export |

The last row is the one that matters most while the boss is still being designed.

## PART 4 — After the choice

- **If A wins:** prewarm directions on load; bake masks to disk; decide 650 vs 390 px.
- **If B wins:** mmap the npz; add a shadow (the sprites get one baked in, the mesh does not);
  check it against the game's day/night light pass.
- **Either way:** the remaining open item from the other plan — rebuilding the attacks from
  real reference motion (Kimodo, in progress) — feeds both routes unchanged.

## Order

1. Part 1 (no code, minutes) — gets a boss on screen today and produces the numbers.
2. Part 2 (~100 lines across two files).
3. Part 3 (one session, both flags).
