# Stamina

Pool on the player, gold bar under health and energy. Slide (C) and leap slam spend it. Ice clone (magic) spends energy.

## Method

- Cap `max(40, vitality * 8)`. Wizard vitality 10 → 80 (4 slides). Barbarian vitality 20 → 160 (8 slides). Slide cost is 20, the `cost` field on a `dash` ability.
- Regen `0.04 * vitality` once per player update, same shape as energy. Starts 450 ms after the last spend, and not while a dash is running. Chained dashes do not refill between presses.
- `stamina.pay`: spend what is there; each unpaid point is 2 health, through the resolver; every point spent is heat; the action still starts. An empty slide is 40 health.
- Enemy dashes keep `cost` 0, so they pay nothing.
- A heartbeat view would draw `1 - stamina / cap` (pinned full while a pay has a shortfall). Same pool.

## Log

- 2026-11-18: pool, gold bar, slide spends stamina, overdraw takes health. Leap and ice clone left on energy.
- 2026-11-21: rebuilt on main as `feat/stamina-wired` (Cursor's copy in `..\Pixel-Realm-stamina` untouched).
  `pay` heats the body (`temperature.exert`, the full cost) and the unpaid health goes through the
  resolver (`source_kind="stamina"`). Slide cost only in `cost` (`stamina_cost` dropped). Leap slam
  spends stamina; ice clone stays on energy (magic). Tests: stamina + abilities + damage + rts:
  474 passed, 5 failed (enemy_dash, charge_controller, gather: known; temperature ghost test fails
  only after the ability tests, also on main; leap charge-ratio timing flake, passes alone 3/3).
