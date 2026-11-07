"""The online screens: sign in, Find a game, Create a game, Lobby.

Laid out like ui_preview/index.html (its mp / create / lobby screens), drawn plainly with
menu_widgets. Screens are pure UI: `handle(events)` returns an action tuple or None, and
Main2 does the network calls and feeds the results back (set_lobbies, set_state, ...).
"""

import re
import time

import pygame

from menu_widgets import (ACCENT, BORDER, BOX, DIM, ERROR, TEXT, Button, Choice, Form, Label,
                          ListView, TextField, draw_text, fit, panel)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
FIND_REFRESH_SECONDS = 5.0


def _escape(events):
    return any(e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE for e in events)


class SignInScreen:
    def __init__(self):
        self.mode = Choice("Account", [("signin", "Sign in"), ("create", "Create account")])
        self.email = TextField("Email", max_len=120)
        self.password = TextField("Password", masked=True, max_len=128)
        self.username = TextField("Username", max_len=20, placeholder="3-20 letters, digits or _")
        self.go = Button("Continue", "continue")
        self.error = Label(color=ERROR)
        self.form = Form([self.mode, self.email, self.password, self.username, self.go, self.error])
        self._sync()

    def _sync(self):
        self.username.visible = self.mode.value == "create"

    def set_error(self, text):
        self.error.text = text

    def handle(self, events):
        if _escape(events):
            return ("back",)
        for widget, action in self.form.handle(events):
            if widget is self.mode:
                self._sync()
                self.error.text = ""
            elif action in ("continue", "submit"):
                return self._submit()
        return None

    def _submit(self):
        email, password = self.email.text.strip(), self.password.text
        if not email or "@" not in email:
            self.error.text = "Enter your email address."
            return None
        if len(password) < 8:
            self.error.text = "The password must be at least 8 characters."
            return None
        self.error.text = ""
        if self.mode.value == "create":
            name = self.username.text.strip()
            if not USERNAME_RE.match(name):
                self.error.text = "Username must be 3-20 letters, digits or _."
                return None
            return ("register", name, email, password)
        return ("signin", email, password)

    def draw(self, surface):
        x, y, width = panel(surface, "Multiplayer", "Sign in")
        self.form.draw(surface, x, y, width)


class FindScreen:
    def __init__(self):
        self.search = TextField("Search", max_len=32, placeholder="Search name")
        self.games = ListView([("Name", 0.42), ("Map", 0.28), ("Players", 0.15), ("", 0.15)],
                              "No games match.")
        self.password = TextField("Password", masked=True, max_len=32)
        self.join = Button("Join", "join")
        self.create = Button("Create a game", "create")
        self.refresh = Button("Refresh", "refresh")
        self.notice = Label()
        self.form = Form([self.search, self.games, self.password, self.join, self.create,
                          self.refresh, self.notice])
        self._lobbies = {}
        self._next_refresh = 0.0
        self.reset()

    def reset(self, notice=""):
        self.notice.text = notice
        self.notice.color = DIM
        self._hide_password()
        self._next_refresh = time.monotonic() + FIND_REFRESH_SECONDS

    def _hide_password(self):
        self.password.visible = False
        self.join.visible = False
        self.password.text = ""

    def search_text(self):
        return self.search.text.strip()

    def set_notice(self, text, error=True):
        self.notice.text = text
        self.notice.color = ERROR if error else DIM

    def set_lobbies(self, lobbies):
        self._lobbies = {g["match_id"]: g for g in lobbies}
        self.games.set_rows([
            (g["match_id"], [g["name"], g.get("map_name", ""), f'{g["seats_used"]}/{g["seats_max"]}',
                             "Private" if g.get("private") else ""])
            for g in lobbies
        ])
        self._next_refresh = time.monotonic() + FIND_REFRESH_SECONDS

    def handle(self, events):
        if _escape(events):
            if self.password.visible:
                self._hide_password()
                self.form.focus_on(self.games)
                return None
            return ("back",)
        for widget, action in self.form.handle(events):
            if widget is self.search and action == "submit":
                return ("refresh",)
            if widget is self.games and action == "pick":
                game = self._lobbies.get(self.games.selected_key)
                if game is None:
                    return None
                if game.get("private"):
                    self.password.visible = True
                    self.join.visible = True
                    self.form.focus_on(self.password)
                    return None
                return ("join", game["match_id"], "")
            if (widget is self.password and action == "submit") or widget is self.join:
                key = self.games.selected_key
                return ("join", key, self.password.text) if key else None
            if widget is self.create:
                return ("create",)
            if widget is self.refresh:
                return ("refresh",)
        if time.monotonic() >= self._next_refresh:
            self._next_refresh = time.monotonic() + FIND_REFRESH_SECONDS
            return ("refresh",)
        return None

    def draw(self, surface):
        x, y, width = panel(surface, "Multiplayer", "Find a game")
        self.form.draw(surface, x, y, width)


class CreateScreen:
    def __init__(self):
        self.name = TextField("Name", max_len=32)
        self.map = Choice("Map", [])
        self.players = Choice("Players", [(n, f"{n} players") for n in (2, 3, 4)], index=2)
        self.door = Choice("Door", [(False, "Open"), (True, "Private")])
        self.password = TextField("Password", masked=True, max_len=32)
        self.go = Button("Open lobby", "create")
        self.error = Label(color=ERROR)
        self.form = Form([self.name, self.map, self.players, self.door, self.password, self.go, self.error])

    def reset(self, username, maps):
        self.name.text = f"{username}'s game"[:32]
        self.map.options = [(m["id"], m["name"]) for m in maps]
        self.map.index = 0
        self.door.index = 0
        self.password.text = ""
        self.error.text = ""
        self._sync()
        self.form.focus_on(self.name)

    def _sync(self):
        self.password.visible = self.door.value is True

    def set_error(self, text):
        self.error.text = text

    def handle(self, events):
        if _escape(events):
            return ("back",)
        for widget, action in self.form.handle(events):
            if widget is self.door:
                self._sync()
            elif action in ("create", "submit"):
                return self._submit()
        return None

    def _submit(self):
        name = self.name.text.strip()
        if not name:
            self.error.text = "Give the game a name."
            return None
        if self.door.value and not self.password.text:
            self.error.text = "A private game needs a password."
            return None
        return ("create", {"name": name, "map": self.map.value, "seats": self.players.value,
                           "private": bool(self.door.value),
                           "password": self.password.text if self.door.value else ""})

    def draw(self, surface):
        x, y, width = panel(surface, "Multiplayer", "Create a game")
        self.form.draw(surface, x, y, width)


class LobbyScreen:
    """Seats on the left, the board on the right, the menu underneath (the preview's lobby)."""

    def __init__(self, characters):
        # characters: [(character_dir, display name)]
        self.characters = characters
        self.character = Choice("Character", characters)
        self.ready = Choice("Ready", [(False, "No"), (True, "Yes")])
        self.start = Button("Start", "start", enabled=False)
        self.leave = Button("Leave", "leave")
        self.say = TextField("Say", max_len=200, placeholder="Say something")
        self.notice = Label()
        self.form = Form([self.say, self.character, self.ready, self.start, self.leave, self.notice])
        self.state = None
        self.my_user_id = None

    def reset(self, my_user_id, character):
        self.state = None
        self.my_user_id = my_user_id
        self.character.select(character)
        self.ready.index = 0
        self.say.text = ""
        self.notice.text = "Joining..."
        self.notice.color = DIM
        self.form.focus_on(self.character)

    def my_seat(self):
        for seat in (self.state or {}).get("seats", []):
            if seat["user_id"] == self.my_user_id:
                return seat
        return None

    def set_state(self, state):
        self.state = state
        seat = self.my_seat()
        if seat is not None:
            if seat.get("character"):
                self.character.select(seat["character"])
            self.ready.select(bool(seat.get("ready")))
        is_host = state.get("host_user_id") == self.my_user_id
        self.start.visible = is_host
        others_ready = all(s["ready"] for s in state.get("seats", []) if s["user_id"] != self.my_user_id)
        self.start.enabled = is_host and others_ready and state.get("phase") == "open"
        self.ready.visible = not is_host
        if state.get("phase") == "starting":
            self.set_notice("Starting the match...", error=False)
        elif self.notice.text == "Joining...":
            self.notice.text = ""

    def set_notice(self, text, error=True):
        self.notice.text = text
        self.notice.color = ERROR if error else DIM

    def handle(self, events):
        if _escape(events):
            return ("leave",)
        for widget, action in self.form.handle(events):
            if widget is self.character and action == "changed":
                return ("character", self.character.value)
            if widget is self.ready and action == "changed":
                return ("ready", bool(self.ready.value))
            if widget is self.say and action == "submit":
                text = self.say.text.strip()
                self.say.text = ""
                return ("chat", text) if text else None
            if widget is self.start:
                return ("start",)
            if widget is self.leave:
                return ("leave",)
        return None

    def _character_name(self, character_dir):
        for value, name in self.characters:
            if value == character_dir:
                return name
        return "-"

    def draw(self, surface):
        state = self.state or {}
        seats = state.get("seats", [])
        seats_max = state.get("seats_max", len(seats) or 2)
        x, y, width = panel(surface, state.get("map_name", "Multiplayer"), state.get("name", "Lobby"),
                            f"{len(seats)} / {seats_max}" if state else "")
        seat_w = int(width * 0.42)
        for i in range(seats_max):
            rect = pygame.Rect(x, y + i * 56, seat_w, 48)
            pygame.draw.rect(surface, BOX, rect)
            pygame.draw.rect(surface, BORDER, rect, 2)
            if i < len(seats):
                seat = seats[i]
                you = seat["user_id"] == self.my_user_id
                name = seat["username"] + (" (host)" if seat.get("host") else "") + ("  - you" if you else "")
                draw_text(surface, fit(name, 28, seat_w - 120), (rect.x + 12, rect.centery - 9), 28,
                          ACCENT if you else TEXT, "midleft")
                draw_text(surface, self._character_name(seat.get("character")),
                          (rect.x + 12, rect.centery + 12), 22, DIM, "midleft")
                if seat.get("ready") and not seat.get("host"):
                    draw_text(surface, "Ready", (rect.right - 12, rect.centery), 26, ACCENT, "midright")
            else:
                draw_text(surface, "Open", (rect.x + 12, rect.centery), 28, DIM, "midleft")

        board = pygame.Rect(x + seat_w + 24, y, width - seat_w - 24, max(seats_max * 56 - 8, 220))
        draw_text(surface, "BOARD", (board.x, board.y - 26), 22, DIM)
        pygame.draw.rect(surface, BORDER, board, 2)
        lines = state.get("chat", [])
        room = (board.height - 16) // 26
        for n, line in enumerate(lines[-room:]):
            text = f'{line["username"]}  {line["text"]}'
            draw_text(surface, fit(text, 24, board.width - 20), (board.x + 10, board.y + 8 + n * 26), 24, TEXT)

        menu_y = y + max(seats_max * 56, board.height + 8) + 16
        self.form.draw(surface, x, menu_y, width)
