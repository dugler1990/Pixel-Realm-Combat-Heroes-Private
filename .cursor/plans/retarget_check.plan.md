# Plan: retarget a character's clips deterministically, with checks that fail loudly

Goal: any Kimodo (SOMA) clip set onto any character (barb, ice wizard, swordsman) the same way every time:
settings from the character file, automatic checks with numbers, the best settings kept, the viewer opened.
No judging by eye first, no per-session knob guessing.

## Why (2026-11-16)
- The barb's row had `bind_match` off and used each clip's frame 1 as "standing": a clip not starting
  standing bent his knees backwards (walk: -33..39 deg vs the source's 17..90).
- `bind_match` on copies the source's angles exactly (dir_check 0.0 deg on every bone) but a thin man's angles
  squeeze his wide body: arms into his torso.
- The demon notes already had the answer (NOTES_retarget_kimodo.md): one standing idle pose as every clip's
  reference (`IDLE_POSE`), the clavicle damp, body-relative IK (`RETARGET_MODE=ik`, `IK_BODY`) for contacts.
  The barb never got them.

## The step: `retarget_check.py <character> <bvh_dir> [--try]`
1. Reference pose, automatic: the quietest frame of the character's idle clip (lowest joint speed over a
   window), written as its `idle_pose.json` (idle_pick.py's format, no eye pick). Path in the character file.
2. Retarget with the character file's `retarget` settings (bind_match, idle_pose, mode, ik_body, clavicle_damp,
   arm_elev_cap) - `retarget_bvh.py` reads them (characters.retarget_target).
3. Checks per clip, each a number with a limit (in `view_checks`-style json, per character):
   - backwards joints: signed knee / elbow bend never past -5 deg;
   - feet: the lower foot within 2 % of height of the floor on standing frames; no sinking below it;
   - hands inside the torso: palm distance to the torso axis above the torso radius;
   - two-handed clips (`th_*`): palm gap under 0.10 of height on the hold frames;
   - directions: per bone vs the source (dir_check, the character's own roles) - reported, not failed,
     since body-relative IK moves away from exact angles on purpose.
   Writes `RETARGET_CHECK.json` + a one-page table; PASS / FAIL per clip and per check.
4. `--try`: a small fixed grid (bind_match on/off x mode rot/ik x ik_body 0.2/0.35/0.5 x clavicle 1.0/0.6) on 4
   reference clips (idle, walk, an attack, a two-handed one); the setting with the fewest failures, then the
   smallest summed error, is written into the character file. Deterministic: same clips, same grid, same pick.
5. Export for the viewer (export_split + clips.json) and print its URL.

## Fixes it needs first
- `rigfix/dir_check.py`: roles path is the demon's, hard-coded -> take the character's roles.
- `retarget_bvh.py`: all settings readable from the character file (today env vars + the code table).
- Clips are tagged by rig in their names (`wz_*` wizard, the rest barb): the step only takes its character's.

## Checks of the step itself
- Barb, 8 key clips: no backwards knees (the bug above caught), two-handed gap reported, feet on the floor.
- Demon: its existing settings reproduce its old result (dir_check 0.0 with bind_match on).
