# Plan: the outfit pipeline, scripted end to end

Goal: one command per character + outfit runs the whole chain (drawings → 3D → skeleton → paint → cut
into slots → game packs), stopping only at the review gates and the pod steps, and you can run it
yourself. Afterwards a web page sits on top (separate plan), like the SAM3 tool and the world-level
review page.

An outfit is the same process with different prompts: `barb_fullplate` (armour), `barb_naked` (the barb
without the loincloth), later others. Every TRELLIS run makes both models, front-only and front + back,
until we know which one works best.

## Where things are (checked 2026-11-13)
- main: older copies of the explode / repaint tools, `pose_heights.py`, the mesh player.
- `feat/view-shape-gate` (worktree `Pixel-Realm-view-gate`): `view_gate.py`, 25 commits not on main.
- `dev_3d_boss` (Boss folder): 3 commits not on main, 70 behind. **Uncommitted there:** 14 modified tool
  files (explode_*, repaint.py, retarget_bvh.py, ...), 22 untracked tools the method depends on
  (`repaint/paint_outfit.py`, `explode2/fit_set.py`, `fix_neutral_bone.py`, `prompts_v2.json`,
  `gpu_box/trellis2_multiview.py`, `trellis2_mv_run.py`, ...). Uncommitted = one lost folder away from gone.
- `feat/armour-slots` (worktree `Pixel-Realm-mesh-player`): `armour_slots.py`, `pieces_sheet.py`.
- Scratchpad only: `v9_chain.sh`, `mv2_chain.sh` (the TRELLIS pod chains).

## Steps

### 0. One branch with every script  (needs your go-ahead: commits and merges in shared folders)
1. Commit the Boss folder's tool changes and untracked tools on `dev_3d_boss`. Who owns them: you say
   (they look like the explode2 sessions' work).
2. New branch `feat/outfit-pipeline` from main, in its own worktree. Merge into it: `dev_3d_boss`,
   `feat/view-shape-gate`, `feat/armour-slots`. Conflicts expected in `tools/boss_sprite_pipeline/` (main's
   older copies): the newer file wins, checked file by file.
3. Commit `v9_chain.sh` / `mv2_chain.sh` as `gpu_box/trellis_outfit.sh` (step 3 below finishes it).
Check: the explode2 Method commands (PROCESS_explode2.md) all resolve to files on the branch.

### 1. Outfit files
`tools/boss_sprite_pipeline/outfits/<character>/<outfit>.json`, read by every step:
- `kind`: `body` (a new body: drawings → 3D → skeleton → paint → body pack) or `armour` (also cut into
  slots) or `cut` (cut pieces out of an existing mesh: the loincloth from the current barb).
- `base`: the concept / mesh it starts from; `skeleton`: the rig it goes onto (`barb_final_nb.glb`).
- `front` / `back`: prompt text; `front_check`: `cover` (armour covers his outline) or `match` (outline
  and hip / knee joints match his).
- `paint_look`: the paint prompts (today `repaint/looks/barb_fullplate.json`).
- `sam_prompts` + `prompt_to_piece`: today `prompts_v2.json` and the table built into `explode_label.py`.
- `slots`: slot rules for `armour_slots.py` (today built in; add `loincloth`: hips, up to 50 % thighs).
Changes: `view_gate.py --outfit`, `explode_label.py --map`, `armour_slots.py --outfit`, `paint_outfit.py`
reads the look from it. Files: `barb_fullplate.json` (the v9 settings, moved), `barb_naked.json`,
`barb_loincloth.json`.
Check: re-running the fullplate front from its file sends the same prompt as v9 did.

### 2. Gates without the terminal
`view_gate.py ... --no-ask` draws, scores, writes the attempt and `gate_<view>.json` (status `pending`),
exits. `view_gate accept <dir> <view> <n>`, `view_gate redraw <dir> <view> [--note "..."] [--marked]`.
Same for the paint check. The terminal prompt stays as the default.
Check: one front drawn with `--no-ask`, accepted by command, `front.png` written as before.

### 3. Pod steps: push / run / pull
`tools/boss_sprite_pipeline/gpu_box/pod.py <step> push|run|pull --host <ip> --port <port>`, key `ppp`,
steps:
- `trellis`: front (+ back) → `front_only.glb` and `front_back.glb` in one run.
- `sam3`: SAM3 snapshot, sam3local src, views, prompts → masks.
- `holopart`: input parts → output.glb.
Each step's file list lives in the script (today in comments at the top of each pod script). `pull` checks the
end marker (`TRELLIS_OK`, `SAM_OK` per shard, `HP_DONE`), then prints **stop the pod** on its own line.
You start and stop the pod; Claude never does.
Check: one SAM3 run on the existing v9 views gives the same masks count (3,299).

### 4. Run state
`generated/bosses/<character>/outfits/<outfit>/run.json`: per step: status, inputs, outputs, accepted
attempt, time, cost. Each script writes its entry; the next step reads its inputs from it (no paths
typed). Glue folded in: `cams.json` copied into the cut folder by the cut step.
Check: `outfit.py barb_fullplate --status` lists the v9 outputs that exist.

### 5. Game export
`export_outfit.py <character> <outfit>`: `swap_body.py` onto the clips blend → `export_mesh_runtime.py`
→ `bake_body_capsules.py` → `clips.json`; for armour / cut outfits one pack per slot. Prints the
character-select entry to add (not written by itself).
Drawing the body + the worn slot packs in game is its own plan (needs per-slot draw, hide-under, the
loincloth hidden under the belt).

### 6. Driver
`outfit.py <character> <outfit> [--from <step>] [--only <step>] [--status]`. Steps by kind:
- body: `front, back, trellis, skeleton, paint, export`
- armour: body steps + `views, sam3, cut, holopart, merge, slots, sheet`
- cut: `views, sam3, cut, holopart, merge, slots, sheet`
Stops at a gate (prints the accept / redraw commands) and at a pod step (asks for host and port),
resumes from `run.json`.

### 7. Proof
- `barb_naked` end to end with the driver: front, back, both TRELLIS models, skeleton, paint, body pack,
  as "Barbarian (naked, mesh)" next to the others.
- `barb_loincloth` (kind `cut`) on the current barb → loincloth slot on the sheet.
- `barb_fullplate` `--status` from the v9 outputs, no paid calls.
Paid: drawings (Leonardo / gpt-image) and one pod session for trellis + sam3 + holopart.

## Not in this plan
The web page (next plan, on top of steps 2, 4 and 6); per-slot drawing in game; SAM prompt tests
("gauntlet", "sabaton", "helmet"); the helmet model.
