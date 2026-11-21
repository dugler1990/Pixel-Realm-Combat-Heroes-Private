# Dev servers

Every local web app used to develop the game: port, how to start it, where it lives.
Run details stay in each app's own process doc; this page only points to them.

**Keep it current:** a new web app, a port change, or a branch merged or removed → change its row here.

## Web apps

All bind `127.0.0.1`. `--port N` and `--no-browser` work on all but the boss viewer.
`py` = `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\Code\sprite_venv\Scripts\python.exe`.

| Port | App | Branch / folder | Start (from that folder) | Process doc |
|---|---|---|---|---|
| 8765 | SAM review page | `feat/review-page`, `C:\Users\Douglas\sam3local-review-page` (sam3local repo) | `python scripts/review_page.py --manifest config/sunspine_chunks.json --cache output/review_cache --publish output/chunks` | `README.md` there |
| 8765 | SAM server (model kept loaded) | `main`, `C:\Users\Douglas\sam3local` | `python scripts/serve.py start` (normally started for you; `status`, `stop`). Port in `config/server.json` | `README.md` there, "SAM server" |
| 8766 | Level review page | `feat/level-review-fit`, `..\Pixel-Realm-level-review-page` | `py -m tools.painted_map_pipeline.world_levels.review_page <run_root> [--levels 01-06]` | `tools/painted_map_pipeline/world_levels/PROCESS_level_review_page.md` |
| 8766 | Level studio | `feat/level-studio`, `..\Pixel-Realm-level-studio` | `py -m tools.painted_map_pipeline.world_levels.studio_page` | `tools/painted_map_pipeline/world_levels/PROCESS_level_studio.md` |
| 8767 | Outfit web | `main` | `py -m tools.boss_sprite_pipeline.outfit_web` | [PROCESS_outfit_web.md](../tools/boss_sprite_pipeline/PROCESS_outfit_web.md) |
| 8768 | Anim web | `feat/anim-suite`, `..\Pixel-Realm-anim-suite` | `$env:ANIM_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"` then `py -m tools.boss_sprite_pipeline.anim_web` | `tools/boss_sprite_pipeline/PROCESS_anim_web.md` |
| 8768 | Entity web | `feat/entity-web`, `..\Pixel-Realm-entity-web` | `py -m tools.entity_pipeline.web` | `tools/entity_pipeline/PROCESS_entity_web.md` |
| 8777 | Boss viewer | `dev_3d_boss`, `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss` | `python tools/boss_sprite_pipeline/viewer/serve.py 8777` (must run from the Boss folder) | `tools/boss_sprite_pipeline/viewer/PROCESS_viewer.md` |

Paths in the last column are inside that row's folder, except outfit web (on `main`).

## Port clashes

Two apps on one default port can't run together; start the second with `--port N`.

- **8765:** SAM review page and SAM server.
- **8766:** level review page and level studio.
- **8768:** anim web and entity web.

## Not a web app

- Multiplayer game server: `Server/server.py`, port 12345. See [Server/NOTES_multiplayer.md](../Server/NOTES_multiplayer.md).
