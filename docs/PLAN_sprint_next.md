# Plan: next sprint (from 2026-11-21)

After the cleanup of Cursor's uncommitted work (`docs/PLAN_cursor_cleanup.md`, items 1-6 merged and
pushed, `main` at `77e82f6d`). Five items, in order. Each item that builds something gets its own
plan first, checked by Douglas before any code.

## 1. Finish the cleanup (item 7)
- Remove old worktree folders whose branch is merged into `main` and whose files are all on `main`:
  the damage chunks (knockback, attack-defs, contact, layers, visual-hits, physical, conditions,
  damage-path), item-card, mesh-equipment, mesh-player, outfit-pipeline, pose-check, view-gate,
  dialogue, legion-ingame, damage (docs), stamina-wired, water-wired; and Cursor's copies (stamina,
  water-combat, water-hole, level-studio, level-review-page). Branches stay in git.
- Before removing: big files git ignores (generated level data, e.g. `sunspine_7x6_play/export`,
  `generated_bootstrap`, `bitter_floe_07`) exist in some of them. Each is compared with the main
  folder; one missing there is moved there first. Nothing that exists only once is deleted.
- Not touched: folders of other live chats (chinampa, mesh-wounds, anim-suite, test-suite, Boss,
  ideas), unmerged doc branches, the `refactor/elemental` archive.
- Done when: `git worktree list` shows only live folders; every ignored big file has one copy, in
  the main folder.

## 2. Damage 8/9: venom, holy and unholy, weakness
- Next on the damage roadmap (`docs/damage/NOTES_damage_and_armour.md`, "Status and next steps").
- First: its own plan (`docs/damage/PLAN_venom_holy.md`): what each does, where its numbers live
  (the attack defs, as the rest), how it uses the conditions clock and the body card, what scene
  shows it. Douglas checks the plan.
- Then build, one commit per step, only the tests of the files touched, one scene per effect for
  Douglas to watch.

## 3. Wire ice fog into the game
- On `main`, not connected to Level4 (`Code/ice_fog/`, `Code/ice_lost_fog.py`,
  `Code/NOTES_ice_fog_test_plan.md`).
- First: a short plan: which level and region gets it, how it starts and ends, what is shown.
  Douglas checks it. Then wire, and Douglas plays it.

## 4. Merge `perf/targeting`
- Cursor's targeting and projectile speed-up (`..\Pixel-Realm-targeting`), not merged. Plans in
  `.cursor/plans/perf_targeting_and_projectiles.plan.md`, `dumb_fighters_share_target.plan.md`,
  status in `perf_status.md`.
- Review the code (simple, contained, correct), say what it changes, merge on Douglas's go.

## 5. Repo size: options note
- History is 5 GB; every new worktree checks out all tracked art. `.gitignore` only keeps new big
  files out.
- A short note (`docs/NOTES_repo_size.md`): what takes the space (by folder), Git LFS vs a history
  rewrite vs leaving it, the cost and risk of each. Douglas decides. Nothing changes before that.

## Working rules for the sprint
- Only the asked thing; side issues are one line in the report, not chased.
- Tests: only the test files of the code touched, once.
- A visible change is checked in a window before it is called done.
- Every new plan is checked by Douglas before building.

## Log
- 2026-11-21: plan written. Item 1 done: 23 old folders removed (big level data checked present in the main folder first); 16 left, all live or unmerged.
