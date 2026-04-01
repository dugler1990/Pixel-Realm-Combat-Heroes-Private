# TMX spawner objects

## Layer naming

Object layers whose **name contains** `spawner` (case-sensitive substring) are processed as spawner layers. Each rectangle (or tile object) on that layer defines a spawn area.

## Single property: `spawner_config`

Add one custom property on each spawner object:

| Property | Type in Tiled | Content |
|----------|----------------|---------|
| `spawner_config` | **string** | JSON object (same fields as legacy files under `levels/.../Objects/*_spawner.json`) |

Do **not** put `frequency`, `spawn_limit`, `enemy_spawn_weights`, etc. as separate Tiled properties; everything must live inside **`spawner_config`**.

### Required in the JSON

- **`enemy_spawn_weights`**: object mapping **enemy id** (string keys, as in `monster_data` in `Code/Settings.py`) to numeric **weight**.

### Optional keys (same as `Spawner.handle_spawn_areas`)

`spawn_type`, `frequency`, `spawn_limit`, `spawn_number`, `distance`, `time_scaled`, `scale_type`, `scale_max`.

### Defaults (if omitted after parse)

| Key | Default |
|-----|---------|
| `spawn_type` | `random_weights` |
| `frequency` | `10000` |
| `spawn_limit` | `60` |
| `spawn_number` | `1` |

### Minimal example (one line for Tiled string value)

```json
{"enemy_spawn_weights":{"goblin":3,"orc":1},"frequency":8000,"spawn_limit":40}
```

Enemy ids must exist in **`monster_data`** in `Code/Settings.py` or spawning will fail at runtime.

### Invalid input

Missing `spawner_config`, empty string, invalid JSON, or missing/invalid `enemy_spawn_weights` → the object is **skipped** and a `[tmx_layout_manager]` warning is printed (no traceback).

## Migration

Older maps that used `enemy_spawn_weights` plus separate properties must be merged into one **`spawner_config`** string per object.
