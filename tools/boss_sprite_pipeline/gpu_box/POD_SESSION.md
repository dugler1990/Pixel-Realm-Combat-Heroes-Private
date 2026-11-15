# Pod session: one script, nothing lost

Lesson (2026-11-16): 2.5 h of pod and most of a token budget went on hand-run steps, live debugging and
polling. A pod session is one script launched once, plus a sync loop here; checked once at the end.

## Pod to rent
- GPU: A40 / L40S 48 GB (TRELLIS ~20 GB + Kimodo or UniRig ~16 GB at the same time).
- Volume: 150 GB mounted at /workspace (installs persist: no recompiling next session). Container disk 30 GB.
- CPU: 16+ vCPU if offered (renders). Check the real limit: `cat /sys/fs/cgroup/cpu.max` (2026-11-16: 7.6 cores
  on a "96 CPU" pod) and `cat /sys/fs/cgroup/memory.max` (50 GB).

## Run
1. Here (Git Bash): `bash tools/boss_sprite_pipeline/gpu_box/pod_go.sh "<RunPod ssh line>"`
   - finds the direct address (pod.py address), sends the HF token from the clipboard (strips a BOM), uploads the
     tools and inputs, starts `pod_session.sh` detached, then runs the sync loop: every 2 min it pulls finished
     outputs into the Boss data folder (`generated/pod_sync/<date>/`). Ctrl+C stops the sync, not the pod.
2. The pod runs `pod_session.sh`: installs in parallel (each skipped when already on the volume), then the jobs.
   Writes `/workspace/out/DONE_<job>` per job and `/workspace/out/SESSION_DONE` at the end.
3. When `SESSION_DONE` is synced: stop the pod.

## Known errors (from this session and the process docs)
| Symptom | Cause | Fix (in the scripts) |
|---|---|---|
| HF requests fail: `'﻿'` in a header | PowerShell's pipe adds a BOM to the token | token sent through ssh stdin with the BOM and CR/LF stripped |
| TRELLIS install: flash_attn wheel "not supported on this platform" | UniRig's cp311 wheel left in /tmp matched `flash_attn-*.whl` | UniRig and TRELLIS each download into their own folder; /tmp wheels removed |
| disk full mid-run | uv / pip caches (8-9 GB per install) | caches removed after every install |
| renders ~2.5 s/frame | EEVEE on CPU + corrective smooth on 700k verts | ANIM_FAST=1, ANIM_ENGINE=BLENDER_WORKBENCH (~1 s/frame) |
| retarget segfaults at the end | the optional glTF export | the .blend is already saved: ignored |
| a running bash script breaks after an upload | bash reads scripts as it runs | never overwrite a running script; jobs read copies |
| Kimodo hand constraints change nothing | they are stored as rotations, not positions | two-handed: off-hand IK after the retarget |
| OpenAI refuses weapon back / side views ("illicit") | its safety filter | weapon prompts worded as a game prop; `back_from_front` for symmetric items; Leonardo for sides |

## All tasks (2026-11-16), in the order they run
Outputs come back as they finish: pod_go.sh pulls every 2 minutes into `<Boss>/generated/pod_sync/<date>/`.
| # | Task | Where | Status |
|---|---|---|---|
| 1 | Kimodo batch 2 (87: spear, dagger, mace, staff, dual, shield, dodges, hits, deaths, spells, fighting) | pod GPU | this session |
| 2 | Kimodo batch 3 (120: barb martial arts, jumps, rolls, evades, weapon strikes; wizard idle/walk/run, spells, hand gestures, staff/wand; hits and deaths for both) | pod GPU | this session |
| 3 | Retarget + render: weapons, moves 1, batches 2 and 3 on the barb (wizard clips onto the wizard once he has a rig) | pod CPU | this session |
| 4 | TRELLIS ice wizard (4 models), sword (front + back) | pod GPU | this session |
| 5 | UniRig on the ice wizard's eight_views model | pod GPU | this session |
| 6 | Swordsman warrior (new batch): front image -> back / sides / 3/4s (OpenAI here) -> TRELLIS | here, then pod | needs his front image + the OpenAI key |
| 7 | Ice wizard: blue robes, dark cultist outfits (armour sets on his rig); staffs, wands, spell books (weapons) | here, then pod | after 5; fronts via OpenAI |
| 8 | Paint every model with Leonardo (repaint/paint_outfit.py, a look file each) | here | needs the Leonardo key |
| 9 | Barb clips into his game pack + game code for run / dash / slide / jump (pack has idle / move / attack only) | here | after 3 |
| 10 | Off-hand IK for two-handed clips; bow string | here | after 3 |
| 11 | Wizard clips retargeted onto his rig | pod CPU | after 5 |

## Queue for the next sessions
- Barb clips in the game: the pack has only idle / move / attack (player_clips.py: settle_01, jokesillyrun,
  overheadchop). The new idle / walk / run / dash / slide / leap clips (moves batch 1) are generated, not
  retargeted into his pack, not wired. Run, dash, slide and jump also need game code (more actions per pack).
- Ice wizard: after his base model + rig (this session's TRELLIS + UniRig): blue robes, dark cultist ice-wizard
  outfits (armour sets on his rig). Staffs, wands, spell books: weapons (route A), any session, about 3-4 min of
  TRELLIS each once installed: add them to TRELLIS_JOBS when their front / back exist.
