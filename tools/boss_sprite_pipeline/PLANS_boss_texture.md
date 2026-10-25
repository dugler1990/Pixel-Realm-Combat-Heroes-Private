# Boss texturing — three plans

> **READ THIS FIRST — briefing for a fresh session.**
> You are continuing work in `Pixel-Realm-Combat-Heroes-Boss` (worktree, branch `dev_3d_boss`).
> A previous session spent a week and real money on this. Most of that money was wasted
> repeating solved problems. Before running *any* pod command, read:
> **[`CHECKLIST.md`](CHECKLIST.md)** then **[`PROCESS.md`](PROCESS.md)**.
>
> **DO NOT REDO — all verified on disk:**
> - `generated/bosses/demon/variants/<stem>/mesh.glb` — six finished meshes, 640k–724k verts,
>   watertight (0 boundary edges when welded), **already textured** by TRELLIS
>   (2048² basecolor + 2048² metallic-roughness). These are the best assets in the repo.
>   **Do not regenerate them. Do not rent a mesh pod.**
> - `generated/bosses/demon/painted/` and `painted_v2/` — MV-Painter attempts. **Both are
>   WORSE than the variants.** Do not use them as a baseline or try to improve them.
> - `generated/bosses/demon/concept/round2/*.jpg` — source concepts (black background).
>   `concept/round2_rgba/*.png` — background removed to real alpha.
>
> **Traps that cost money last time (full list in PROCESS.md §8):**
> - Judging quality from a **front view**. It hid every defect twice. The verdict gate is
>   always an **8-direction turntable**.
> - Reference images with a **black background** — MV-Painter/TRELLIS composite onto white,
>   and an opaque black background produces washed-out output. Use real alpha.
> - Uploading into `/opt/MV-Painter` while an installer that does `rm -rf` is still running.
> - `pkill -f <pattern>` killing your own SSH session when the pattern is in its command line.
> - Never trust "it ran" — check the artifact (`test -s` the actual output file).
>
> **Local tooling:** `tools/boss_sprite_pipeline/.venv-bpy/Scripts/python.exe` has **bpy +
> numpy + PIL** (no scipy/cv2/torch). Enough for all segmentation, material and render work
> in these plans. This PC's GPU (GTX 1050, 4 GB) cannot run any of the generators.
>
> **Which plan am I on?** Plan 3. Plan 1 is its prerequisite. Plans 1 and most of 3 are
> **free and local — no pod**. Only Plan 2 needs a rental.


Written 2026-09-21. Target: **giant boss**, ~60% of screen height (~650 px at 1080p),
so the **head lands at ~100–130 px on screen**. That is the number every decision below serves.

## Where we actually are

- **Geometry is production quality and done.** `variants/<stem>/mesh.glb` — watertight
  (0 boundary edges welded), sharp face with horns/brow/eye-sockets/individual teeth.
- **Best texture we have is TRELLIS's own** (2048² basecolor + 2048² metallic-roughness,
  baked from a 1024³ attribute volume → no projection bleed, no seams). It is *soft but clean*.
- **MV-Painter is abandoned.** UV-projection based; produced white bleed and mottle on this mesh.
- **The bottleneck:** the head is ~15% of the model's height, so it gets only ~150 voxels of
  that 1024³ volume — roughly 1:1 with a 100 px on-screen face. No headroom. That is exactly
  why the face reads soft.

## The central tradeoff (read before choosing)

Splitting the model **buys resolution and costs continuity.**
Each separately-generated part gets its own colour cast → visible drift and seams at every join.
This is the failure mode that has burned every genAI art pipeline tried so far.
**More splits = more detail = more joins to go wrong.**

Corollary that shapes Plan 3: for **eyes, teeth, claws** do **not** generate texture —
*assign a material*. A tooth is a convex bone-white shape. Assignment is instant, perfect,
and has zero continuity risk. Generation there is strictly worse.

---

# PLAN 1 — The split (prerequisite, free, local)

**Goal:** cleanly separate the mesh into parts that can be textured independently and
recombined without visible joins. Shared prerequisite for Plans 2 and 3.

**Steps**
1. Load `variants/<stem>/mesh.glb` in Blender (bpy, local).
2. Segment. Two options:
   - **Spatial (start here):** head = top ~15% of bbox, centre column. Crude, 10 minutes, adequate for head/body.
   - **Semantic:** `SAMPart3D` / `PartField` / `SAMesh` for head / wings / limbs / horns. More setup, proper parts.
3. Cut along a **low-visibility seam** (under the jaw / behind the neck ridge), never across
   a flat visible surface.
4. Export each part as its own GLB, **preserving the original UVs and world transform**
   so parts snap back together exactly.
5. Keep a `parts.json` recording each part's origin + bbox for reassembly.

**Gate G1:** re-import all parts together, render front/45/side — silhouette must be
pixel-identical to the unsplit mesh. If it isn't, the cut or the transform is wrong.

**Risks**
- Cutting through a visible surface → permanent seam.
- Losing the world transform → parts don't reassemble.

**Cost:** free, local, ~30 min. **No pod.**

---

# PLAN 2 — Split + TRELLIS retexture + reconstruct  ← most likely to work

**Goal:** texture the head as its own object so it fills TRELLIS's 1024³ volume
(~1000 voxels instead of ~150 → **~6× facial detail**), keep the body's existing texture.

**Why TRELLIS and not UniTEX/MV-Painter:** volume-baked, so no UV projection, no bleed,
no view seams. It is the only texturer that has produced a clean result on this mesh.
MIT weights — commercially clean. We already have a working install recipe.

**Steps**
1. Plan 1 output: `head.glb` + `body.glb`.
2. **Head reference image** — the main risk. Options, best first:
   a. Generate a new close-up of the *same design* (Leonardo/GPT) — matches framing, may drift in design.
   b. Crop the head from the existing concept art (~300 px) and upscale — design-faithful, low-res.
   Use white/alpha background (black background is the bug that wrecked the MV runs).
3. Run `Trellis2TexturingPipeline` on `head.glb` + head reference. **This pipeline has never
   been successfully used here** — every variant was made with `--skip-texture`, so what we
   have is the *generate*-stage bake, not TRELLIS's dedicated texturing stage.
4. Keep `body.glb` with its existing TRELLIS texture (already clean).
5. Reassemble as **two objects, two materials**. No atlas merge needed.
6. **Colour-match the head to the body** at the neck: sample mean skin tone either side of the
   seam and apply a levels/hue correction to the head texture. This is the step that decides
   whether it looks joined or glued.

**Gates**
- **G2a:** head texture is visibly sharper than the current head at 100–130 px. Judge at
  *on-screen size*, not zoomed.
- **G2b:** full 8-direction turntable — no visible neck seam, no colour drift. **A front view is not a verdict.**

**Kill criteria:** if the neck seam is visible after colour matching, stop and fall back to Plan 3's
material-zone approach on the unsplit mesh.

**Cost:** one 24–40 GB pod session, ~30–45 min, well under $1. Segmentation free.

---

# PLAN 3 — Fine segmentation + per-part treatment + reconstruct  ← ambitious

**Goal:** semantic part decomposition (SAM3D-class), then treat each part with the *right*
tool rather than generating everything.

**The key design decision — do not generate every part:**

| Part | Treatment | Why |
|---|---|---|
| Eyes | **Material** (red, emissive) | ~10 px on screen. Assignment is perfect and instant. |
| Teeth / claws / horn tips | **Material** (bone white, low roughness) | Convex simple shapes. Generation can only make them worse. |
| Wing membrane | **Material or TRELLIS** | Thin double-sided geometry — the worst case for any projection texturer. |
| Head/face | **TRELLIS** (Plan 2) | The one part that genuinely needs generated detail. |
| Body/limbs | **Keep existing TRELLIS texture** | Already clean. Don't regenerate what works. |

**Steps**
1. `SAMPart3D` / `PartField` for semantic parts → per-part vertex groups.
2. Assign materials for eyes/teeth/claws/horns (instant, zero risk, big visual win —
   this alone fixes "the eyes have no colour").
3. TRELLIS-retexture only the head (Plan 2).
4. Leave body/wings on existing texture.
5. Reassemble; one material slot per zone.

**Gates**
- **G3a:** material zones assigned to the *correct* geometry (no red bleeding onto skin).
- **G3b:** 8-direction turntable, no seams, consistent skin tone.

**Risks**
- Part segmentation mislabels regions → red eyes on a cheekbone. Needs visual verification per part.
- Every additional *generated* part multiplies continuity risk. Generated parts should stay ≤ 1 (the head).

**Honest note:** the version of this plan that generates texture per fine part (tooth by tooth)
is **not recommended** — at 10 px per tooth it buys nothing visible and adds a seam lottery.
The value here is the **segmentation + material assignment**, not per-part generation.

**Cost:** segmentation free/local; SAMPart3D setup is the main unknown. Same single pod
session as Plan 2 for the head.

---

# Recommended order

1. **Plan 1** — free, prerequisite, no regret.
2. **Plan 3's material zones** — free, local, instant, biggest visible win per effort
   (red eyes + bone teeth + claws on the mesh you already have). Do this *before* renting anything.
3. **Plan 2** — one pod session, only if the face still lacks detail after 1 + 2.
4. Per-part generation — only if all the above falls short. Probably never.

**Reality check kept from the discussion:** a fully automatic genAI path to a polished giant
boss is unlikely. The realistic route is *good geometry (done) + material zones + shading*,
with generated texture as a **base layer to correct**, not a finished product. For one hero
boss on screen at 650 px, hand-finishing the face is what a studio would do and is a few hours.
