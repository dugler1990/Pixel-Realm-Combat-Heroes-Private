"""Nakama backend client: accounts and RPCs over HTTPS, the lobby over one websocket.

Wire details mirror Nakama's own JS client (nakama-js socket.ts / web_socket_adapter.ts):
snake_case keys, op_code sent as a string, match data as base64-encoded JSON, and a `cid`
on requests that expect a reply. REST paths are from Nakama's apigrpc.proto (v3.42.0).
The socket thread only parses and queues; pygame code drains `poll()` on the main thread.
"""
import base64
import json
import os
import queue
import threading
import time
import urllib.parse

import requests
import websocket

SESSION_REFRESH_PATH = "/v2/account/session/refresh"
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


class NakamaError(Exception):
    pass


def _jwt_exp(token):
    try:
        part = token.split(".")[1]
        return int(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["exp"])
    except (AttributeError, IndexError, ValueError, KeyError, TypeError):
        return 0


def from_config():
    """A NakamaClient for the backend named in config.json, or None if it isn't set up."""
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    if not config.get("backend_url") or not config.get("server_key"):
        return None
    return NakamaClient(config["backend_url"], config["server_key"])


class NakamaClient:
    def __init__(self, base_url, server_key, timeout=10.0):
        self.base_url = base_url.rstrip("/")
        self.server_key = server_key
        self.timeout = timeout
        self.token = None
        self.refresh_token = None
        self.user_id = None
        self.username = None

    @property
    def signed_in(self):
        return self.user_id is not None

    def _request(self, method, path, params=None, body=None, basic=False):
        headers = {"Accept": "application/json"}
        if not basic:
            headers["Authorization"] = "Bearer " + self.token
        try:
            resp = requests.request(method, self.base_url + path, params=params, json=body,
                                    headers=headers, timeout=self.timeout,
                                    auth=(self.server_key, "") if basic else None)
        except requests.RequestException as exc:
            raise NakamaError("Cannot reach the game server.") from exc
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message")
            except ValueError:
                message = None
            raise NakamaError(message or f"Server error {resp.status_code}.")
        return resp.json() if resp.content else {}

    def register(self, username, email, password):
        self._authenticate(email, password, create=True, username=username)

    def login(self, email, password):
        self._authenticate(email, password, create=False)

    def _authenticate(self, email, password, create, username=None):
        params = {"create": "true" if create else "false"}
        if username:
            params["username"] = username
        data = self._request("POST", "/v2/account/authenticate/email", params=params,
                             body={"email": email, "password": password}, basic=True)
        self.token = data["token"]
        self.refresh_token = data.get("refresh_token")
        account = self._request("GET", "/v2/account")
        self.user_id = account["user"]["id"]
        self.username = account["user"]["username"]

    def refresh_if_needed(self):
        if self.token and self.refresh_token and _jwt_exp(self.token) - time.time() < 300:
            data = self._request("POST", SESSION_REFRESH_PATH, body={"token": self.refresh_token}, basic=True)
            self.token = data["token"]
            self.refresh_token = data.get("refresh_token", self.refresh_token)

    def rpc(self, rpc_id, payload):
        """Call a server RPC with a dict; returns its reply dict, raises NakamaError on ok=false."""
        self.refresh_if_needed()
        # The HTTP body is the RPC's string payload, so the JSON is sent as a JSON string.
        data = self._request("POST", "/v2/rpc/" + rpc_id, body=json.dumps(payload))
        result = json.loads(data.get("payload") or "{}")
        if result.get("ok") is False:
            raise NakamaError(result.get("error") or "Request refused.")
        return result

    def open_socket(self):
        self.refresh_if_needed()
        return NakamaSocket(self.base_url, self.token)


class NakamaSocket:
    def __init__(self, base_url, token):
        scheme = "wss" if base_url.startswith("https") else "ws"
        host = base_url.split("://", 1)[1]
        url = f"{scheme}://{host}/ws?lang=en&status=false&token={urllib.parse.quote(token)}"
        self._events = queue.Queue()
        self._replies = {}
        self._next_cid = 1
        self._lock = threading.Lock()
        opened = threading.Event()
        self._ws = websocket.WebSocketApp(url, on_open=lambda ws: opened.set(),
                                          on_message=self._on_message, on_error=self._on_error,
                                          on_close=self._on_close)
        threading.Thread(target=self._ws.run_forever, kwargs={"ping_interval": 15, "ping_timeout": 10},
                         daemon=True).start()
        if not opened.wait(10):
            self.close()
            raise NakamaError("Cannot open the lobby connection.")

    def _on_message(self, ws, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        cid = msg.get("cid")
        if cid is not None:
            with self._lock:
                slot = self._replies.pop(cid, None)
            if slot is not None:
                slot["reply"] = msg
                slot["event"].set()
            return
        data = msg.get("match_data")
        if data is not None:
            try:
                raw = base64.b64decode(data.get("data") or "")
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                self._events.put(("match_data", int(data.get("op_code", 0)), payload))
            except ValueError:
                return

    def _on_error(self, ws, error):
        self._events.put(("error", str(error)))

    def _on_close(self, ws, code, reason):
        self._events.put(("closed", reason or ""))

    def _call(self, body, timeout=10.0):
        with self._lock:
            cid = str(self._next_cid)
            self._next_cid += 1
            slot = {"event": threading.Event(), "reply": None}
            self._replies[cid] = slot
        body["cid"] = cid
        try:
            self._ws.send(json.dumps(body))
        except websocket.WebSocketException as exc:
            raise NakamaError("Lost connection to the lobby.") from exc
        if not slot["event"].wait(timeout):
            raise NakamaError("The lobby did not answer.")
        error = slot["reply"].get("error")
        if error:
            raise NakamaError(error.get("message") or "Request refused.")
        return slot["reply"]

    def join_match(self, match_id, metadata):
        self._call({"match_join": {"match_id": match_id,
                                   "metadata": {k: str(v) for k, v in metadata.items()}}})

    def leave_match(self, match_id):
        self._call({"match_leave": {"match_id": match_id}})

    def send(self, match_id, op_code, payload):
        data = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        try:
            self._ws.send(json.dumps({"match_data_send": {"match_id": match_id, "op_code": str(op_code),
                                                          "data": data}}))
        except websocket.WebSocketException:
            self._events.put(("closed", "send failed"))

    def poll(self):
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def close(self):
        try:
            self._ws.close()
        except Exception:  # closing an already-dead socket is fine
            pass
