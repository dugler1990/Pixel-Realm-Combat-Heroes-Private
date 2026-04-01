# Debug logging (`debug_logging.json`)

Edit [`debug_logging.json`](debug_logging.json) next to this file. Paths under `file` are relative to the `Code/` directory.

## Channels

| Key | Logger | Purpose |
|-----|--------|---------|
| `collision_mask` | `game.collision.mask` | Obstacle and effect mask collision traces ([`Entity.py`](Entity.py)). |
| `tmx_effect_placement` | `game.tmx.effect_placement` | TMX effect layer creation and per-object placement / mask stats ([`tmx_layout_manager.py`](tmx_layout_manager.py)). |
| `tmx_layout` | `game.tmx.layout` | TMX grass profiles, spawner config, env spawn warnings, and other layout load messages ([`tmx_layout_manager.py`](tmx_layout_manager.py)). |
| `animated_environment` | `game.animated.environment` | Animated environment sprites (frame timing) ([`AnimatedEnvironmentSprite.py`](AnimatedEnvironmentSprite.py)). |
| `game_flow` | `game.flow` | Main state machine, menus, level selection, dev reload ([`Main2.py`](Main2.py), [`StartMenu.py`](StartMenu.py), [`LevelSelection.py`](LevelSelection.py), [`PlayerSelection.py`](PlayerSelection.py)). |
| `combat` | `game.combat` | Attack traces, special attacks, traps, legacy combat strategy ([`Level4.py`](Level4.py), [`SpecialAttacks.py`](SpecialAttacks.py), [`Trap.py`](Trap.py), [`CombatStrategy1.py`](CombatStrategy1.py)). |
| `player_item` | `game.player.item` | Pickup and inventory assign ([`Player.py`](Player.py), [`Inventory.py`](Inventory.py)). |
| `spawner` | `game.spawner` | Neutral / spawn diagnostics ([`Spawner.py`](Spawner.py)). |
| `input` | `game.input` | Input manager reset ([`inputManager.py`](inputManager.py)). |
| `mask_ascii` | `game.debug.mask_ascii` | ASCII mask row dump ([`Support.py`](Support.py) `print_mask`). |
| `quadtree` | `game.quadtree` | Quadtree `print_all` traversal ([`QuadTree.py`](QuadTree.py)). |
| `effect_environmental` | `game.effect.environmental` | Environmental damage effects (e.g. heat) ([`Effect.py`](Effect.py)). |

## Fields per channel

- **`enabled`**: `true` to attach handlers; `false` keeps the logger silent (no file opens).
- **`level`**: e.g. `DEBUG`, `INFO` (standard `logging` names).
- **`file`**: relative path for a `FileHandler` (e.g. `logs/tmx_layout.log`). Log files are gitignored under `Code/logs/*.log`.
- **`console`**: `true` to also log to stderr.

Keep **`enabled` false** unless you are diagnosing something; per-frame or high-volume channels can hurt performance when enabled.

## Bootstrap

[`game_logging.setup_debug_logging()`](game_logging.py) runs when [`Main2.py`](Main2.py) is imported. In-game overlay toggles ([`GameSettings.debug_mode`](game_settings.py)) are separate from this file logging.

### Helpers

- `get_debug_logger("channel_key")` — generic lookup by JSON key.
- Named getters: `get_collision_mask_logger()`, `get_tmx_effect_placement_logger()`, `get_tmx_layout_logger()`, etc.
