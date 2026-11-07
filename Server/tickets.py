"""Signed join tickets: the launcher mints them, the match server checks them.

v1: base64url(payload_json) + "." + base64url(HMAC-SHA256(secret, base64url(payload_json))).
Payload: {"v": 1, "mid": match_id, "uid": user_id, "usn": username, "chr": character, "exp": unix_s}.
"""
import base64
import binascii
import hashlib
import hmac
import json
import time

TICKET_VERSION = 1


class TicketError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: bytes, body: str) -> str:
    return _b64(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())


def mint(secret: bytes, match_id: str, user_id: str, username: str, character: str,
         ttl_seconds: float, now: float = None) -> str:
    payload = {"v": TICKET_VERSION, "mid": match_id, "uid": user_id, "usn": username,
               "chr": character, "exp": int((time.time() if now is None else now) + ttl_seconds)}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return body + "." + _sign(secret, body)


def verify(secret: bytes, ticket, match_id: str, now: float = None) -> dict:
    try:
        body, sig = ticket.split(".")
        if not hmac.compare_digest(sig, _sign(secret, body)):
            raise TicketError("bad signature")
        payload = json.loads(_unb64(body))
    except TicketError:
        raise
    except (AttributeError, TypeError, ValueError, UnicodeError, binascii.Error) as exc:
        raise TicketError("malformed ticket") from exc
    if not isinstance(payload, dict):
        raise TicketError("malformed ticket")
    if payload.get("v") != TICKET_VERSION:
        raise TicketError("unsupported ticket version")
    if payload.get("mid") != match_id:
        raise TicketError("ticket is for another match")
    if payload.get("exp", 0) < (time.time() if now is None else now):
        raise TicketError("ticket expired")
    return payload


def secret_from_env(value: str) -> bytes:
    """GAME_TICKET_SECRET is hex; refuse anything shorter than 32 bytes."""
    secret = bytes.fromhex(value or "")
    if len(secret) < 32:
        raise ValueError("GAME_TICKET_SECRET must be at least 64 hex characters")
    return secret
