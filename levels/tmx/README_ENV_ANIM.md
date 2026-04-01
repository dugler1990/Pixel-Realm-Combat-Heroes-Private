# Animated environment objects from TMX

On a normal **object** layer (tile objects), add **one** custom property:

| Property         | Type   | Value                          |
|------------------|--------|--------------------------------|
| `env_anim_type`  | string | `tree` or `torch` (any case)   |

The game maps that keyword to the full animation folder config in code (`ENV_ANIM_SPRITE_CONFIG_BY_TYPE` in [`Code/tmx_layout_manager.py`](../../Code/tmx_layout_manager.py)), matching the legacy Map7 `tree1` / `torch1` art paths.

Objects without this property stay ordinary static tiles. If spawn fails, a warning is logged and a static tile is used when the object has a tile image.

To add another animated env kind later: extend `ENV_ANIM_REGISTRY` and `ENV_ANIM_SPRITE_CONFIG_BY_TYPE` together.
