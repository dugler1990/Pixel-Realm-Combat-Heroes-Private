# Dialogue

## Method

- Graphs are JSON in `Code/dialogue/content/`. One file per conversation. `id` matches `speakers.json` `graph`.
- A speaker entry's key is `sprite_type`, then `name`. `Eskimo` is the shipped example.
- Barks are `content/barks.json`. Optional `audio` is a file path. A missing file plays nothing.
- Commands: `set_flag:name=value`, `open_shop:id`, `offer_quest:id`, `give_item:id`. `open_shop` opens `content/shops.json` in the trade window. The other two are stubs. `DialogueSession.commands.take_pending()` still lists every command.
- Space on a line finishes the typewriter, then advances. On a choice it selects. Esc ends.
- Settings: `speech_bubbles`, `conversation_text`, `voice_enabled`. Bubbles off hides world lines only. Conversation text off keeps the choice list.

## Known errors

- A graph `next` that names a missing node raises `ValueError` at load.
- More than 32 skipped nodes in a row raises `ValueError` (a require-cycle).

## Log

- 2026-11-08: play test opens the benchmark room (black, wall ring) with one Eskimo. `pytest tests/test_dialogue_play.py` from the worktree. Close the window to finish. The normal suite skips that file.
- 2026-11-08: Trade on the Eskimo's choice list opens a Legion trade window (same panel and bars as Settings). Esc closes the shop and returns to the choices. The play scene starts with 40 gold.
- 2026-11-08: Trade draws the real inventory window on the right. The left is the same slot grid without the body, one icon per ware, tabs All / Goods / Gear / Other. Tab moves between the two. E changes his tab. Space buys or sells. Keys and gold are refused.

## Tried and dropped

- Putting talk on `NeutralCharacter.perform_action`. That path is the NPC acting on a tile (fishing), not the player starting a conversation.
- Reusing combat `InteractionContext` for talk.
