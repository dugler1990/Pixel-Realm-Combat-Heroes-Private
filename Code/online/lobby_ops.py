"""Lobby op codes: the Python side of deploy/nakama/src/lobby.ts. Change both together.

client -> lobby (JSON bodies)
    SET_CHARACTER {"character": "../Graphics/barb/"}   clears that seat's ready
    SET_READY     {"ready": true}
    CHAT          {"text": "..."}                       1-200 characters
    START         {}                                    host only
lobby -> clients
    STATE   {"name", "map", "map_name", "seats_max", "private", "phase", "host_user_id",
             "seats": [{"user_id", "username", "character", "ready", "host"}],
             "chat": [{"username", "text", "at"}]}       phase: open | starting | started
    TICKET  {"host", "port", "map", "ticket"}           to one player only
    NOTICE  {"text"}
"""

OP_SET_CHARACTER = 1
OP_SET_READY = 2
OP_CHAT = 3
OP_START = 4
OP_STATE = 100
OP_TICKET = 101
OP_NOTICE = 102
