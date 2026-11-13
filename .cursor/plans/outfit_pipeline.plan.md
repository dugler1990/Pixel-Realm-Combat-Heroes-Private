# Plan: the outfit pipeline, scripted end to end

Goal: one command per character + outfit runs the whole chain (drawings → 3D → skeleton → paint → cut
into slots → game packs). It stops only at review gates and pod steps, and you can run it yourself.
A web page goes on top later (separate plan), like the SAM3 tool and the world-level review page.

An outfit is the same process with different prompts: `fullplate` (armour), `naked` (the barb without
the loincloth: a full redraw of the front like the armour, then back, TRELLIS...), `loincloth` (cut
from the current barb, like the armour pieces). Every TRELLIS run makes both models, front-only and
front + back; you pick one by eye at the gate (we don't know yet which works best; the choice is logged).

Decisions (2026-11-13): merge route below OK; TRELLIS choice by eye for now; keep a process doc
(`tools/boss_sprite_pipeline/PROCESS_outfit.md`); the Boss folder's uncommitted tools committed in
groups, `explode2/` sorted into method / `options/` / `measure/`, dropped tools removed and logged.
Reviews (junior + senior, 2026-11-13) folded in below.

## 0. One branch with every script — done 2026-11-13
- `dev_3d_boss`: `7c3de314` armour pipeline, `a4980e2a` leonardo_api error text, `135b5ab7` kimodo
  host_demo, `1e6a5d02` pod chains (from the scratchpad), `e0f48f9e` explode2 sorted + README +
  removals logged in Tried and dropped.
- `feat/outfit-pipeline` (worktree `Pixel-Realm-outfit-pipeline`) from main + `dev_3d_boss` +
  `feat/view-shape-gate` (brings its level-pipeline code: shape_gate, image_client, retry, cut_sheet,
  figures — accepted) + `feat/armour-slots`. Conflicts: `leonardo_api.py` (both sides kept: view-gate's
  checks + Boss's `error` fallback and 400-char message), `world_levels/checks.py` (main's colour_gap
  + view-gate's shape_note). Painted-map tests: the same 7 fail as on main.
- Check: every script the explode2 Method names exists on the branch (12 of 12).

## 1. Outfit files
`tools/boss_sprite_pipeline/outfits/<character>/<outfit>.json`, read by every step:
- `kind`: `body` | `armour` | `cut`.
- `concept`: the image the front is drawn on (fullplate: `gear_test/body_sil/body_front_textured.png`).
- `rig_fit`: the rig the outfit is fitted and worn-tested on (`rigfix/barb_final.glb`, as v9);
  `rig_game`: the clips' rig (`rigfix/barb_final_nb.glb`; `swap_body.py` checks rest poses against it).
- `roles`, `greedy_dirs`, `sam_prompts`, `prompt_to_piece`, `paint_look`.
- `front` / `back`: prompt text; `front_check`: `cover` | `match`; `margin`; `display_joints`;
  `retry_bigger` (the [rb] line).
- `existing`: paths of outputs made before run.json (v9), for `--backfill`.
Changes: `view_gate.py --outfit`, `explode_label.py --prompt-map`, the loincloth rule in
`explode_common` (as the skirt: hips, up to 50 % thighs at the hem) and `armour_slots.py`.
Check: `view_gate front --outfit fullplate --dry-run --retry rb` prints v9's `front_attempt_02_prompt.txt`
exactly (diff), with no paid call.

## 2. Gates without the terminal
`view_gate ... --no-ask` draws once, scores, appends to `gate_<view>.json` (status `pending`), exits.
`--retry r|r1|rb|"r <why> @img"`: the next draw with the same choices as the terminal.
`--accept N`: writes the cut-outs as the terminal accept does (a back accept also writes `front.png`).
Paint: no accept loop; the driver stops after paint, shows `paint/result/after_0_body_0.png`, and you
continue or rerun with `--redo <view>`. TRELLIS: stops with both models; `--pick front_only|front_back`.

## 3. Pod steps: push / run / pull
`gpu_box/pod.py <step> push|run|pull --host <ip> --port <port>` (or `POD_HOST` / `POD_PORT`), key `ppp`.
- `trellis`: `gpu_box/trellis_outfit.sh` (from `pod_chains/v9_chain.sh`): install, then
  `trellis2_mv_run.py` twice → `front_only_from_front.glb`, `front_back_from_front.glb`; `TRELLIS_OK`.
- `sam3`: snapshot path and sam3local src resolved at push (HF cache, `C:/Users/Douglas/sam3local/src`),
  views, prompts, `explode_sam.py`, `sam3_pod.sh`; pull checks `SAM_OK` ending every `sam_shard*.log`
  and `SAM_DONE`.
- `holopart`: `holopart_pod.sh`, `holopart_patch.py`, `input_parts.glb`; `HP_READY`, `HP_DONE`.
`pull` ends with **stop the pod** on its own line. You start and stop pods; Claude never does.

## 4. Run state
`generated/bosses/<character>/outfits/<outfit>/run.json`: per step status, inputs, outputs, picked /
accepted attempt, time, cost. The driver records each step; the next step reads its inputs from it.
Cost: the image calls' own usage where the response gives it, else per-call list price; pod: minutes ×
the rate you pass (`--pod-rate`). `--backfill` writes run.json from the outfit's `existing` (v9).
Glue folded in: `cams.json` copied into the cut folder by the merge step.

## 5. Game export (last step)
`export_outfit.py`: body → `swap_body.py` onto the clips blend → `export_mesh_runtime.py` →
`bake_body_capsules.py` → `clips.json`, prints the `PlayerSelectionDict.json` entry (pasting it is
part of the proof). Armour / cut → one pack per slot (`slot_packs.py`: rigid weights per slot on the
clips rig). The game can't draw slot packs yet: check = each pack loads (`PlayerMesh`) + the sheet.

## 6. Driver
`outfit.py <character> <outfit> [--from S] [--only S] [--status] [--backfill] [--host --port]`:
- body: `front, back, trellis, skeleton, paint, export`
- armour: `front, back, trellis, skeleton, paint, views, sam3, cut, holopart, merge, worn, slots, sheet, export`
- cut: `views, sam3, cut, holopart, merge, slots, sheet, export`
Stops at a gate (prints accept / retry commands) and before a pod step without host / port.

## 7. Proof
Free first: the `--dry-run` diff (step 1), `--backfill` + `--status` for fullplate, slot packs from the
v9 slots (load test). Then one paid session: `naked` front + back (drawings), one pod for TRELLIS
(both models) + SAM3 + HoloPart (the SAM3 check: the v9 views again, masks compared pixel by pixel),
`naked` skeleton + paint + body pack ("Barbarian (naked, mesh)"), `loincloth` as a first prompt trial
(the sheet is the bar only once a mask labels the cloth), worn on the naked body.

## Process doc
`tools/boss_sprite_pipeline/PROCESS_outfit.md`: Method (commands), Known errors, Log, Tried and dropped.

## Not in this plan
The web page; drawing slot packs in game (hide-under, loincloth under the belt); SAM prompt tests
beyond the loincloth ("gauntlet", "sabaton", "helmet"); the helmet model.
