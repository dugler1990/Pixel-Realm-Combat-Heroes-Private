# Multiplayer notes

Read this before writing or reviewing any multiplayer plan.

## What Douglas wants (agreed 2026-11-06)

- Players on different computers create a real account and sign in from the game. They see the open
  games, then create or join one. The lobby has seats, chat and a ready button. When the host starts,
  everyone lands in the same match.
- It runs on a real internet server, starting on his 3 GB Linode, never just on the laptop.
- It is built the way a commercial game would build it: standard, secure and maintainable. In his words,
  it needs "a clear path to get there without big rewrites".
- The first plan is only the foundation: that whole path working end to end in a thin version, with
  features added on top later.
- The pygame game is the client. `ui_preview/index.html` is only the look of those screens.

## Not wanted

- A laptop-only service, SQLite, or any "local rehearsal" stage.
- The HTML preview as the client.
- A plan that leaves the game server letting in anyone who connects.

## Agreed shape of the first plan

1. **Backend:** Nakama runs in Docker on the Linode, with a Postgres database, behind HTTPS. It covers
   accounts, logins, lobbies, chat and matchmaking, and can add Steam login later. Nakama has no official
   Python library, so the game calls its web API directly. Douglas needs a domain name pointing at the
   Linode.
2. **Sign-in:** a sign-in screen in the pygame game.
3. **Lobby screens:** Find, Create and Lobby screens in the pygame game, laid out like the preview.
4. **Starting a match:** on start, the server launches one game-server process for that match with the
   chosen map, and gives each player a signed ticket. Before this step, measure how much RAM one match
   uses on the Linode, because that number decides how many games it can hold at once.
5. **Game server:** `Server/server.py` gets a one-match mode. Only ticket holders get in, the account is
   the player, and the process exits when the match ends.
6. **Done when:** two computers with two accounts can create, join, ready, start, and both play through
   the Linode.

The full plan for this is `C:\Users\Douglas\.cursor\plans\online_foundation.plan.md` (written 2026-11-07).

## Where things stand

- `Server/server.py` runs one world on port 12345 at 60 Hz, on `MP_LEVEL_NUMBER = 6`. It lets in
  anyone who sends a string `player_id`. That has to change in step 5.
- A localhost-only stdlib + SQLite lobby (branch `feat/lobby-foundation`) and two older lobby plans
  were rejected and deleted on 2026-11-06. No lobby code exists in the repo.
