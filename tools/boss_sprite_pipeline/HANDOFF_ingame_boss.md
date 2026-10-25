# Handoff — getting the demon boss drawn in the running game

Written 2026-09-26 for an agent starting cold. The demon is modelled, textured, rigged and
animated. **Nothing has ever been drawn in the game** — that is the whole job.

Two things to take on board before anything else:

* Asset packs for both methods exist on disk, but **both are stale** — baked before today's rig
  and animation work. Section 1b rebuilds them. Do not evaluate anything until you have.
* `PLAN_ingame_both_methods.md` is the original plan and its *mechanics* are still right, but it
  was written before the animation churn and frames the A/B choice as neutral. It is no longer
  neutral — see section 6.

---

## 1. What exists, verified on disk

| Piece | Path | State |
|---|---|---|
| Sprites (method A) | `Graphics/Monsters/demon/` | **383 MB**, 5 actions x 8 directions, per-frame trim, per-frame anchors |
| Mesh pack (method B) | `Graphics/Meshes/demon/mesh.npz` | **210 MB**, 120k tris, 177 baked frames |
| Sprite loader | `Code/combat_unit.py::import_graphics_8dir` (line ~413) | works; lazy per-direction (`_LazyDirFrames`), reads `manifest.get("frames")` for anchors |
| Per-frame anchor | `Code/Entity.py::_frame_anchor_px` | works |
| Mesh runtime | `Code/mesh_boss.py` | `MeshBossPack` / `MeshBoss` with `set_action`, `advance`, `frame_index`, `draw` |
| GL draw call | `Code/render_backend.py::draw_mesh_boss` (line ~669) | **verified rendering a posed, lit, textured frame** standalone |
| CPU fallback | same file, line ~108 | returns `False` — method B silently does nothing without GL |
| Stats | `Code/Settings.py` line ~393 `monster_data["demon"]` | health 2500, melee radius 260, notice 1600 |

**The two gaps:**

1. `Code/YsortCameraGroup.py::custom_draw` (line 271) only ever calls `self.backend.blit(...)`.
   It has no idea `draw_mesh_boss` exists. Method B cannot appear until it does.
2. Nothing spawns a `demon`. No map object, no debug key.

So **method A is one spawn away from being visible**; method B needs a draw hook first.

---

## 1b. START HERE — the assets on disk are stale, rebuild first

**Do not evaluate anything before doing this.** Both packs were baked from the *procedural*
animations, before today's rig and animation work. Judging method A or B on them is judging
work that has been superseded.

**Current rig:** `generated/bosses/demon/rig/jaw/rigged_jaw_hinge.glb`
This is the end of a five-step fix chain (wing parenting, clavicle parenting, head weights,
chest weights, weight blur, jaw hinge). Do not use any earlier `rigged_jaw_*.glb`.

**Current animations**, all already retargeted onto that rig:

| blend | clips | what |
|---|---|---|
| `generated/bosses/demon/animate_idle4/animated.blend` | `settle_01/02/03` | idles. **`settle_01` is the approved one** |
| `generated/bosses/demon/animate_gargoyle/animated.blend` | 8 | **wings, jaw and neck all animate** — Airborne, Attack, Damage, Die, Fall... |
| `generated/bosses/demon/animate_cast/cast/animated.blend` | 15 | attacks and reactions (hitchest, hithead, startled, leapattack, kneel...) |
| `generated/bosses/demon/animate_final/final/animated.blend` | 11 | earlier attack set, tamer |
| `generated/bosses/demon/animate_stance/stance/animated.blend` | 3 | combat-stance candidates, not yet chosen |

**Rebuild the method-B pack from one of those (~40 s):**

```
tools/boss_sprite_pipeline/.venv-bpy/Scripts/python.exe \
  tools/boss_sprite_pipeline/export_mesh_runtime.py \
  generated/bosses/demon/animate_idle4/animated.blend \
  Graphics/Meshes/demon 120000 2048
```

Writes `mesh.npz` (positions per frame, normals, uv, indices, per-action ranges, fps, pivot),
`albedo.png` and `pack.json`. 120000 is the triangle budget — **do not drop to 20k, it tears the
texture** (measured). The mesh is decimated in the *rest* pose before posing, so vertex counts
stay fixed across frames.

**Use `settle_01` (idle) and `walk` for the first test** — these are the two clips Douglas has
reviewed and accepted, so if something looks wrong in game it is the integration, not the
animation. `settle_01` is in `animate_idle4/animated.blend` (240 frames, 30 fps source; it reads
best played back at about half speed). `walk` is in `animate_final/final/animated.blend`.

Everything else in the list is still under review and should not be used to judge the renderer.

**What they should look like.** Rendered previews sit beside each blend, e.g.
`generated/bosses/demon/animate_idle4/video720/settle_01_720_halfspeed.mp4` (720 px, every
frame) and `generated/bosses/demon/animate_final/final/video/walk.mp4`. Watch those first so
you can tell a broken integration from an animation you simply have not seen before.

The gargoyle set is worth a second look once idle and walk are working, because it is the only
set where the **wings, jaw and neck** animate — useful for confirming the whole rig is being
driven rather than just the body. `gar_F_Daedalus_Attack_F_01_F` (96 frames) is the clearest.

Method A's 383 MB sprite pack would need a **~70 minute** re-render (`pipeline.py --from animate
--to pack`). That asymmetry is the point of section 6 — consider rebuilding B first and only
paying for A if B is rejected.

---

## 2. Method A — sprites

No code change needed to see it. The benchmark harness already spawns arbitrary enemy types:

```
PRCH_BENCHMARK_ENABLED=1 PRCH_BENCHMARK_ENEMY_TYPE=demon PRCH_BENCHMARK_ENTITY_COUNT=1
```

(`Code/benchmark_runtime.py` reads these; `_env_bool("PRCH_BENCHMARK_ENABLED", ...)` at line ~702.)
A Tiled object of type `demon` works too.

**Gates, in order — do not skip ahead:**

1. loads without exception (the manifest path and the `monster_data` entry are both new and
   have never been exercised at runtime)
2. he stands on his hitbox — **feet** at the anchor pixel, not knees. This is what the
   per-frame anchors are for; if he bobs, the anchor lookup is wrong, not the art
3. walk a circle around him and confirm all 8 direction folders load
4. `idle -> move -> attack` follow the AI status
5. **FPS with 1 on screen and with 3**

**Known risks, measured or reasoned:**

- first entry into a direction decodes ~36 PNGs — a visible hitch. Mitigation is a prewarm on
  the loading screen.
- `pygame.mask.from_surface` on a 749x428 frame is a few ms; masks are built lazily per direction.
- **the GPU atlas only accepts sprites <= 512 px**, so every boss frame takes the `_large_cache`
  path: one GL texture per frame, uploaded on first draw, never freed. With 5 actions x 8 dirs
  x ~36 frames that is a lot of textures. Watch VRAM.

---

## 3. Method B — mesh

`draw_mesh_boss` is proven in isolation; what is missing is a call site.

1. **Give `CombatUnit` an optional mesh.** At `import_graphics_8dir` time: if
   `MeshBossPack.exists(name)` and settings allow, build a `MeshBoss` and keep the sprite frames
   **as well** — they still drive masks, hitbox size and y-sort. Just skip drawing the sprite.
2. **Hook `custom_draw`.** Where it blits a sprite, first check
   `getattr(sprite, "mesh_boss", None)`; if present call
   `boss.draw(self.backend, screen_pos, facing_deg, height_px)` and skip the blit. Ordering is
   free — it happens at that sprite's y-sort position like anything else.
3. **Facing is an angle, not a bucket.** Sprites snap to 8 directions; the mesh takes the real
   heading. Pass the continuous angle — that alone will look better than method A.
4. **Playback.** `boss.set_action(unit.status)` and `boss.advance(dt)` each frame. The pack's
   per-action ranges already match the sprite action names.

**Gates:** everything in method A's list, plus — does he composite correctly *behind* trees and
*in front of* ground?

**Risks:**

- `draw_mesh_boss` **clears the depth buffer per call**, so two mesh bosses cannot intersect
  each other correctly. Fine for one boss; revisit for many.
- `mesh.npz` is 210 MB loaded as numpy. It should be memory-mapped
  (`np.load(..., mmap_mode="r")`) so only the frames actually played are paged in.
- the CPU backend's `draw_mesh_boss` returns `False` and draws nothing. If the game can run
  without GL, method B needs an explicit fallback to the sprite path or the boss is invisible.

---

## 4. The comparison that decides it

Same scene, same camera, same boss, one flag apart. Fill this in:

| Metric | A (sprites) | B (mesh) |
|---|---|---|
| Disk | 383 MB | 210 MB |
| Resident RAM after all 8 dirs touched | ? | ? |
| First-appearance stall (ms) | ? | ? |
| FPS, 1 boss / 3 bosses | ? | ? |
| Visual at 650 px | ? | ? |
| Angles | 8 | continuous |
| Cost to change an animation | ~70 min re-render | ~40 s re-export |

That last row is the one that matters most while the boss is still being designed — and it is
still being designed, heavily. See section 6.

**After choosing:**
- **A wins:** prewarm directions on load; bake masks to disk; decide 650 vs 390 px.
- **B wins:** mmap the npz; add a shadow (sprites have one baked in, the mesh does not); check
  against the game's day/night light pass.

---

## 5. Things that will bite you

- **`render_backend.py` has two `draw_mesh_boss`** — a real one on `GPUBackend` (~line 669) and
  a stub returning `False` (~line 108). Reading the wrong one will convince you the feature is
  unimplemented.
- **Sprite anchors are per frame, not per action.** `Entity._frame_anchor_px` reads
  `per_frame[status][direction][frame_index]["anchor"]`. Per-action anchors were tried and made
  him bob.
- **The animation set is in flux.** Do not hard-code action names. As of today the sprite pack
  has 5 actions but the animation work has produced ~30 clips under new names, and more are
  generating. Read the manifest.
- **650 px is not decided.** 390 px is the other candidate. It changes the atlas question above.

---

## 6. Context you will not guess

The boss's animations are being actively regenerated. Today alone the rig changed five times
(jaw hinge, jaw angle, head weights, chest weights, weight blur) and the clip list was renamed
and pruned by hand. **The sprite pack on disk predates all of that** — it was baked from the
earlier procedural animations, not from the current Kimodo/gargoyle sets.

Consequence: if the choice lands on method A, the 383 MB pack has to be re-rendered from the
current rig before it means anything (~70 min). Method B's `mesh.npz` has the same problem but
re-exports in ~40 s.

**This is the strongest practical argument for method B** and it is not in the original plan,
which was written before the animation churn started. Do not treat the plan's neutral framing
as the current state of the evidence.

Relevant background documents, in the order worth reading:

- `PLAN_ingame_both_methods.md` — the original plan
- `NOTES_retarget_kimodo.md` — how the animations are produced, and the rig's real anatomy
  (the bone role names in `bone_roles.json` are **wrong**; `_anatomy` in that file is correct)
- `NOTES_nonhuman_animation.md` — where future animation is likely to come from
- `PLAN_d2_and_animation.md` — how the sprite pack was baked
