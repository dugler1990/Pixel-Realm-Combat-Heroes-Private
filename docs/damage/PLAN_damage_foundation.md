# Plan: damage foundation cleanup

Branch `refactor/damage-path` (`..\Pixel-Realm-damage-path`), on top of `a5e6aa45` (one damage path).
One commit per step. Targeted test set run before and after each step; FAILED names compared to baseline.
Each step updates `NOTES_damage_and_armour.md` (Log, Known errors, deletions with commit hash).
Each step has a "done when" grep; the key ones become one guard test (step 7).
Performance: crowd bench before step 1 and after step 7 (real Level4 headless, 40 units in two
hostile crowds, 600 frames: mean/p95 ms per frame; plus `strike` over the crowd, µs per call).
Script and numbers in the notes' Method and Log.

## Rules agreed
- No legacy folder. Git history is the archive. Each deletion: one line in the notes with the hash
  and the restore command `git show <hash>^:<path>`.
- One damage path: every hit goes through `InteractionResolver`; no fallbacks that subtract health directly.
- One team check: the faction policy in `apply`. Nothing else filters by team.
- No invulnerability by default. It is a condition a source grants (a boss trait, a passive ability),
  never a general post-hit grace. Repeat hits stay with `rehit_ms`.
- Invulnerable blocks all damage, heat and cold included. `over_time` goes.
- Attacker memory: one fact on every body, two distinct rules read it.
- Damage numbers live only in attack defs (`Code/config/damage/attacks.json`).

## Status (2026-11-21)
Steps 1-6 done, one commit each: `202fdcfd`, `d87dc708`, `e429ea58`, `31649c6f`, `faea0307`,
`0849cecb`. Guard test `tests/damage/test_one_path_guard.py` added (covers 1-6). Step 7 waits on
the open question below. Changes from the plan as written:
- Step 4: default hit/death sounds stay in code (CombatUnit, NeutralCharacter); a monster's data may
  override them. Putting the same two paths in ~30 `monster_data` entries would be the duplication.
- Step 3: tribe members leave the entity tree on death always (the worker-only guard flag is gone).
- Step 2: `interaction_validation.py` lost its 2 `effect_state` scenarios; the benchmark's
  `effect_state` column is gone.

## Steps
1. **Deletions**
   - `Code/Enemy.py`, `Code/friendly.py`, `tribey_geom_probe.py` (TEMP probe), and their use in
     `test_walk_animation_phasing.py`.
   - The 30 inert `'damage_player': True` keys in `Settings.py` `combat_context`.
   - The dead multiplier/bonus in `Level4_tmxdev._resolve_projectile_damage_payload`.
     (Level4_tmxdev is the live level; only this part is dead.)
   - Done when: `rg "import Enemy|from Enemy|friendly import|damage_player" Code tests` → 0.
2. **Resolver only, one team check**
   - Remove no-resolver fallbacks: `Entity` lava path, `IceClone`, `leap_slam` x2.
   - `effect_state` (slippery and similar) is not a hit: set it directly on the body; delete the
     `effect_state` kind from the resolver and its Entity fallback.
   - Team: one rule (the faction policy), run once per hit. `apply` = policy, then `land()`.
     `strike` keeps its early skip (crowds) but runs the policy itself and calls `land()` directly,
     so no second check and no throwaway context. Remove leap_slam's own prefilter and the same-team
     check in `Entity.can_receive_interaction` (body gate checks health > 0 only).
     Direct `land()` callers (relay, puppet) carry no team, so nothing is lost.
   - Done when: `rg "\.health -=" Code` → only `Entity.take_damage`; `rg "effect_state" Code` → 0;
     `rg "team_id" Code/Entity.py` shows no check in `can_receive_interaction`.
3. **Death in one place**
   - `Entity.die()`: does nothing if already dead; sets `is_dead` once, condition-clock notice,
     then `on_death()`.
   - Base `on_death()`: removal from the lookup tree, `kill()`. Overrides add extras (XP, particles,
     death sound, RTS notice). Player overrides it and stays alive with `is_dead` set (co-op and the level read it).
   - `take_damage` calls `die()` when health reaches 0.
   - Replaces: `check_death` in Eskimo, PolarBear, combat_unit, tribe_member; `Player.player_death`;
     the death in `Trap.on_hurt`.
   - Check: health set without a hit (restores, net snapshots, heals) must not need a death check;
     co-op deaths still arrive by host message (`EnemyPuppet`, `RemotePlayer`).
     A body dying mid-`strike` (tree removal during the loop): crowd test.
   - Done when: `rg "check_death|player_death" Code` → 0.
4. **Sounds**
   - Shared cache: each file loaded once (`sounds.get(path)`).
   - Paths in existing entity data: `hit_sound`, `death_sound` next to `attack_sound` in `Settings`
     `monster_data` (Eskimo, PolarBear entries too). No new file.
   - Attribute names stay `hit_sound`, `death_sound`, `attack_sound`, so `on_hurt` is unchanged.
   - Later: player hit/impact sound from the weapon or attack def.
   - Done when: `rg "mixer.Sound\(" Code` → only the cache.
5. **Attacker memory**
   - One record on every body: `last_attacker` (team, until_ms), written by the resolver.
     The writer touches nothing else (no `_aggro_target_cache` reset; the AI notices the change itself).
   - Two named readers, each comparing `until_ms` to now:
     permission in `FactionPolicy.should_aggro` (a `retaliate_only` faction may only attack its attacker);
     preference in `CombatUnit` (target the team that hit me). Both documented in the notes.
   - Fixes the bug: `should_aggro` checks `retaliate_until > 0`, not `> now` (`Interaction.py:336`),
     so retaliation never expires today.
   - Done when: `rg "recent_attacker_|retaliate_team_id|retaliate_until_ms" Code` → 0.
6. **Invulnerability as a condition**
   - `invulnerable` timed condition on the `ConditionClock`; the resolver checks it in `land()`.
   - Granted only by sources that declare it (boss trait, passive ability). No default grace.
   - Blocks all damage; `InteractionContext.over_time` removed.
   - Remove `vulnerable` and `invulnerability_duration` from Player, combat_unit, NeutralCharacter,
     the reset code, the dead flicker, the `land()` check; update `combat_validation_driver.py`.
   - `apply` / `land` return an explicit result: landed / spent (invulnerable) / refused.
   - Done when: `rg "\bvulnerable\b|invulnerability_duration|over_time" Code` → 0.
7. **Damage numbers from defs only** (open question first)
   - Found: of 36 monster attacks with a number in `Settings`, 20 differ from their def's damage on
     purpose (a warrior's spear 8 vs the def's 6; a ghost's chill 20 with a magic-only def). The def
     is how a hit lands; the monster's number is how hard (`hit_resolve._damage` uses it). Removing
     them is a balance change (20 new defs, or 20 new numbers), not a cleanup.
     Player weapons: `weapon_data` damage equals the def for all 6. Magic `strength` sits in
     `magic_data` and in the def's `magic`.
   - Recommendation: keep monster numbers (the attacker's strength); remove only true copies:
     the player's weapon damage comes from the def (+ attack stat), `weapon_data` keeps cooldown and art.
   - Projectile, weapon, magic damage priced from `attacks.json`; copies in `Settings`
     (`ranged_attacks` damage, `weapon_data`) removed.
   - Holy rule: holy or unholy alone (no blow, no fire/cold/lightning) is priced as its power, flat;
     no element starts. Today it falls through to the stated amount.
   - The `get_full_*_damage` tier in `_price` goes. A hit with no def and no amount raises an error
     (not a silent 0).
   - Guard test (built): add a rule for no `get_full_.*_damage` in pricing.
   - Done when: the guard test passes.

## Next (not this plan)
- Temperature rebuild: `temperature.py`, sources table, weighted pull, `settle` through the resolver.
- Eskimo / PolarBear move to CombatUnit + roam driver + tile-job driver (RTS-style nomad).
  Own initiative. Now they only get shared death and sounds.
- Dash invulnerability: a possible later source for step 6's condition.
