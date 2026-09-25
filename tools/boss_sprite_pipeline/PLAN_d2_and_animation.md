# Plan — the animated D2 sprite boss

Written 2026-09-21. Worktree `Pixel-Realm-Combat-Heroes-Boss`, branch `dev_3d_boss`.
Companion docs: `PROCESS.md` (pod rules), `CHECKLIST.md`, `PLANS_boss_texture.md` (superseded
by the outcome below).

## 0. Where we are (verified on disk)

| Asset | Path | State |
|---|---|---|
| Best mesh | `generated/bosses/demon/variants/gpt2_front_sculpt/mesh.glb` | 700k verts, watertight, TRELLIS texture 2048² |
| **Painted mesh** | `generated/bosses/demon/projected/gpt2_front_sculpt_face/mesh_painted.glb` | atlas gutters padded, metallic 0, face repainted from `face_elev15/attempt_2/output_tonematched.png`, texture packed |
| Face paint loop | `tools/boss_sprite_pipeline/part_polish.py` | gpt-image-2 edit, accept / `r` / `r1` / `e` / `p`, `--continue` |
| Projection | `tools/boss_sprite_pipeline/project_paint.py` | UV-id splat from the paint camera, before/after turntable |
| Sprite pipeline | `pipeline.py` → `rig.py` → `animate.py` → `render_frames.py` → `pack_frames.py` | **proven end-to-end on `_test_fox`** (animated GLB → 8-dir frames → installed → engine loads via `manifest.json`) |
| Engine loader | `Code/combat_unit.py::import_graphics_8dir` | reads `manifest.json`: `directions`, `actions{fps,frames}`, `anchor_px` |
| Statuses the AI drives | `Code/CombatStrategy.py` | `idle`, `move`, `attack` — nothing else is required |
| Rig backend | `backends/unirig.py` + `gpu_box/unirig_cli.py` + `gpu_box/setup.sh unirig` | written, **never run** |
| Animate | `animate.py` | `passthrough` works (fox); `procedural` is a docstring, **not built** |

Two facts that shape everything below:

- **The engine only needs `idle`, `move`, `attack`.** No death, no hurt, no special. Three clips.
- **`render_frames.py` already supports `render.target_height_px`** and renders any GLB whose
  actions are named `idle/move/attack`. Render and pack need no new code; the only build is the
  animation.

---

## The plan

### 0. The central decision: how does he move?

Required minimum (decided 2026-09-21): **idle = breathing, move = walk, attack.** He walks; he does
not hover. That makes the walk cycle the hard part, so the choice is about the walk:

| Route | What it is | Automation | Quality | Verdict |
|---|---|---|---|---|
| **B-Proc: procedural stomp** | UniRig skeleton → role-labelled bones → bpy keyframe recipes; the walk is a heavy two-beat stomp (hip/knee/foot sines with phase offsets, root bob, arm counter-swing, wings half-spread and rocking) | **Fully automatic**, reusable on every boss with a rig | Reads well for a *giant heavy* boss because weight and slowness hide the lack of nuance; would not pass for a human | **Try first** |
| B-Mixamo walk | Upload to Mixamo (free), humanoid auto-rig, download a heavy walk / "zombie walk" / "mutant walk" clip, retarget onto our rig (free Rokoko addon) or use Mixamo's rig + hand-added wing bones | Manual web step per boss (no API); wings unrigged | Real walk cycle | **Fallback if the stomp reads as a puppet** — and the standing route for grounded humanoid bosses |
| B-Hybrid | Procedural idle/attack/wings + Mixamo walk | Half manual | Best of both | Likely end state for hero bosses |

Why procedural first: it costs nothing, it is one script for all twenty factions, and a slow
stomping giant is the one gait procedural animation is actually good at. Judge it at game size on
the 8-direction strip before deciding — a walk that looks wrong at 1024 px close-up can be fine at
650 px total with the wings flapping.

### 1. Decimate + rig (one pod session, same plumbing as TRELLIS)

- Decimate `mesh_painted.glb` → `mesh_painted_150k.glb` (~150k tris, keep UVs; bpy DECIMATE, local, 1 min). **Gate:** a head render next to the 700k one — no visible difference at 650 px. This is the mesh for rigging, animating and rendering; the 700k one is done.
- Pod: `gpu_box/setup.sh unirig` then `gpu_box/unirig_cli.py --mesh raw.glb --out rigged.glb`.
  UniRig is **MIT, code and weights** (checked 2026-09-21), CUDA, fits a 24 GB pod. Follow `PROCESS.md`
  rules: test the artifact (`test -s rigged.glb`), never `pkill -f` your own session.
- Local: `inspect_rig.py rigged.glb bones.json` → bones with role guesses.
- **Gate R1 (visual, mandatory):** a bpy script that rotates each role's bone ±30° and renders — head,
  each wing, each arm, each leg, spine. Weights that bleed (jaw drags the chest, wing pulls the
  shoulder) show up here and nowhere else. Fix roles in `bone_roles` of the boss config; fix bad
  weights with `bpy.ops.object.vertex_group_smooth` or re-run UniRig with another seed.
- Risk: UniRig puts no bones in the wings or merges them with the arms. Mitigation: seed retry;
  failing that, add two wing bones by hand at the wing root/tip and auto-weight only the wing
  vertices (we can select them — they are the thin membrane, |X| > 0.13 at shoulder height).

**Cost: one 24 GB pod, ~30 min, < 1 €.**

### 2. Animate — build `animate.py` `procedural` mode

Deterministic bpy, keyed by role, ~150–200 lines. Input `rig/rigged.glb` + `rig/bones.json`;
output `animate/animated.glb` with actions named exactly `idle`, `move`, `attack`, so
`render_frames.py` finds them with no `source` mapping.

| Clip | Length | Recipe (all on pose bones, all loopable except attack) |
|---|---|---|
| `idle` (breathe) | 48 f @ 24, loop | spine: 2° pitch sine (chest rise); head: 3° yaw sine at half rate; wing_l/r: 8° slow rock, phase-locked; root: Z bob 0.5 % of height; arms: 2° counter-sway |
| `move` (walk) | 32 f @ 24, loop = 2 steps | legs: hip pitch ±25° sine, L/R offset 180°; knee bends 0→40° on the swing half only (eased); foot pitch to keep the sole flat on contact; root: Z bob 2 % at 2× step rate, dips on each contact (the stomp); root: lateral sway ±1.5 % at step rate; spine: 5° forward lean + 3° twist counter to the hips; arms: swing ±15° opposite to the same-side leg; wings: half-spread, 10° rock at step rate; head: level (counter-rotate spine twist) |
| `attack` | 30 f @ 24, not looped | 0–10: anticipation (root back 4 %, wings up 30°, head back, weight on rear leg); 10–16: lunge (root forward 12 %, front leg step, arms swing 70°, head down, jaw open if a jaw bone exists); 16–30: recover to the idle pose |

Design rules: every recipe reads bone names from `bones.json` roles, never hard-codes names; a
missing role degrades gracefully (no wings → no flap, still a valid clip); amplitudes live in the
boss config under `animate.params` so the next boss tunes numbers, not code.

- **Gate 2a:** `render_frames.py` logs `actions found: ['attack','idle','move']`.
- **Gate 2b:** a 3-direction preview strip (s / e / n) of each clip; loops don't pop, the attack
  recovers to the idle pose, nothing intersects the ground.

### 3. Render + pack + install (existing code)

Render settings for the boss:

| Decision | Pick | Why |
|---|---|---|
| **Size on screen** | `render.target_height_px: 650` | The brief: ~60 % of 1080p height. Frame ≈ 900–1000 px because the wings and 45° camera widen it. |
| **Camera elevation** | 45° | Every installed monster and the map are at the fox's 45°; another angle looks pasted on. |
| **Material** | `mesh_painted.glb` as is | Already padded + metallic 0 + painted. |
| **Lighting** | fox default (sun 50°/-35°, ambient 0.35) | Consistency with installed monsters. |
| `forward_axis` | `-Y` (as fox); verify the `s` frame shows the face, else `+Y` | |

**Frame budget (decide before rendering).**

At 650 px standing height with wings, a trimmed frame is roughly 900 × 700 px RGBA ≈ 2.5 MB in RAM,
and `import_graphics_8dir` loads every frame of every direction. 8 dirs × (idle 8 + move 8 +
attack 10) = 208 frames ≈ **520 MB** for one boss — too much beside the rest of the game. Options:
- fewer frames: idle 6 / move 6 / attack 8 → 160 frames ≈ 400 MB; still heavy;
- **lazy-load per direction** in `combat_unit.py` (only the current direction's frames in RAM, or
  push them into the `ImageCache` GPU atlas) — the real fix, and a small engine change;
- render at 512 standing height and let the engine scale ×1.27 — visible softness, last resort.
Render the first animated pass at the small budget, measure the trimmed frame size and RAM, then
pick. The pipeline does not care which; only the engine does.


`pipeline.py … --from render --to pack` with `bosses/demon.json` updated to:
```json
"source": "animate/animated.glb",
"actions": {"idle": {"fps_out": 8}, "move": {"fps_out": 10}, "attack": {"fps_out": 12}},
"camera": {"elevation_deg": 45, "margin": 1.1},
"render": {"target_height_px": 650, "shading": "raw", "ground_shadow": true}
```
and the frame budget above. **Gate:** engine loads `manifest.json`, the AI's status
changes switch clips, attack plays through and returns to idle, anchor holds (no foot slide).

### 4. If it looks good — the two upgrades worth doing next

1. **Dynamic lighting sprites ("better than D2").** Add a normal-map + depth pass to
   `render_frames.py` (Eevee AOVs), write `Sprite-NNNN_n.png` beside each frame; engine-side a
   per-pixel light pass (numpy or the GPU atlas shader). Torches and spells then light the boss
   correctly. Same pipeline, one extra output.
2. **±45° face paint passes** through `part_polish.py` + `project_paint.py` with the left45/right45
   cameras, so the `e`/`w`/`ne`/`nw` sprites get the painted face too. The tooling is done; it is a
   run, not a build.

---

## Order and cost

| Step | Where | Time | Money |
|---|---|---|---|
| 1 decimate + UniRig | local + pod | 50 min | < 1 € |
| 1 gate R1 (rig check renders) | local | 30 min | 0 |
| 2 procedural clips (walk is the bulk) | local, new code | 4–6 h | 0 |
| 3 render + install + play | local | 1 h | 0 |
| 4 upgrades | local | later | 0 |

The only rental is UniRig, once.

## Kill criteria

- First animated render blows the RAM budget → lazy-load per direction in the engine before touching frame counts.
- R1 shows UniRig can't rig the wings after a seed retry → hand-place wing bones (30 min), do not
  abandon the route.
- The procedural walk reads as a puppet at 650 px on the 8-direction strip → switch the walk to
  B-Mixamo (keep procedural idle/attack/wings). Do not spend more than one tuning pass on the stomp.
