"""Match launcher: starts one Server/server.py process per match and mints its tickets.

Private HTTP API v1, reachable only on the compose network (port 8090, never published).
Every request needs the header X-Launcher-Key. Nakama's lobby module is the only caller.

    GET  /v1/health   -> {"running": n, "max": MAX_MATCHES}
    GET  /v1/maps     -> {"maps": [{"id": 6, "name": "Level 6"}]}          (MP_MAPS)
    POST /v1/matches  {"match_id", "map", "players": [{"user_id", "username", "character"}]}
                      -> 200 {"host", "port", "map", "tickets": {user_id: ticket}}
                         400 bad body, 401 bad key, 409 already running, 503 no free slot,
                         504 not ready in time, 500 the match server died on start

One job on purpose: a hosted fleet service can replace this later and nothing else changes.
"""

import hmac
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(_SERVER_DIR)
sys.path.insert(0, os.path.join(_REPO_DIR, "Code"))
sys.path.insert(0, _SERVER_DIR)

import tickets  # noqa: E402
from level_layouts import MP_MAPS  # noqa: E402  (pure module: no game imports)

LISTEN_PORT = 8090
MATCH_ID_RE = re.compile(r"^[A-Za-z0-9.\-]{1,80}$")
MAX_PLAYERS = 4
MAX_BODY_BYTES = 16 * 1024
LOG_DIR = os.path.join(_REPO_DIR, "logs", "matches")


def _characters():
    """The selectable character folders, from the same file the game reads."""
    with open(os.path.join(_REPO_DIR, "Graphics", "PlayerSelectionDict.json"), encoding="utf-8") as f:
        return {p["player_info_dir"] for p in json.load(f)["Players"]}


class Launcher:
    def __init__(self, launcher_key, ticket_secret, public_host, port_first, max_matches,
                 ticket_ttl, ready_timeout):
        self.launcher_key = launcher_key
        self.ticket_secret = ticket_secret
        self.public_host = public_host
        self.ports = list(range(port_first, port_first + max_matches))
        self.max_matches = max_matches
        self.ticket_ttl = ticket_ttl
        self.ready_timeout = ready_timeout
        self.characters = _characters()
        self.lock = threading.Lock()
        self.running = {}  # port -> (match_id, Popen)
        os.makedirs(LOG_DIR, exist_ok=True)
        threading.Thread(target=self._reap_forever, daemon=True).start()

    # -- validation --

    def check_body(self, body):
        """The request's problem as text, or None if it is valid."""
        if not isinstance(body, dict):
            return "body must be a JSON object"
        match_id = body.get("match_id")
        if not isinstance(match_id, str) or not MATCH_ID_RE.match(match_id):
            return "bad match_id"
        if body.get("map") not in MP_MAPS:
            return "unknown map"
        players = body.get("players")
        if not isinstance(players, list) or not 1 <= len(players) <= MAX_PLAYERS:
            return f"players must be a list of 1-{MAX_PLAYERS}"
        for p in players:
            if not isinstance(p, dict):
                return "bad player"
            for key in ("user_id", "username"):
                value = p.get(key)
                if not isinstance(value, str) or not 1 <= len(value) <= 64:
                    return f"bad {key}"
            if p.get("character") not in self.characters:
                return "unknown character"
        return None

    # -- starting a match --

    def start(self, body):
        """(status, reply dict) for a validated POST /v1/matches body."""
        match_id, level = body["match_id"], body["map"]
        with self.lock:
            if any(mid == match_id for mid, _ in self.running.values()):
                return 409, {"error": "match already running"}
            free = [p for p in self.ports if p not in self.running]
            if not free:
                return 503, {"error": "no free match slot"}
            port = free[0]
            env = {k: v for k, v in os.environ.items() if k != "LAUNCHER_KEY"}
            log = open(os.path.join(LOG_DIR, f"{match_id}.log"), "ab")
            proc = subprocess.Popen(
                [sys.executable, os.path.join("Server", "server.py"), "--host", "0.0.0.0",
                 "--port", str(port), "--map", str(level), "--match-id", match_id],
                cwd=_REPO_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
            log.close()  # the child holds its own handle
            self.running[port] = (match_id, proc)
        print(f"[launcher] starting {match_id} (map {level}) on port {port}, pid {proc.pid}", flush=True)

        deadline = time.monotonic() + self.ready_timeout
        while True:
            if proc.poll() is not None:
                return 500, {"error": "match server exited during start"}
            try:
                socket.create_connection(("127.0.0.1", port), 1).close()
                break
            except OSError:
                pass
            if time.monotonic() > deadline:
                proc.kill()
                return 504, {"error": "match server not ready in time"}
            time.sleep(0.5)

        issued = {
            p["user_id"]: tickets.mint(self.ticket_secret, match_id, p["user_id"], p["username"],
                                       p["character"], self.ticket_ttl)
            for p in body["players"]
        }
        print(f"[launcher] {match_id} ready on port {port}; {len(issued)} ticket(s)", flush=True)
        return 200, {"host": self.public_host, "port": port, "map": level, "tickets": issued}

    def _reap_forever(self):
        while True:
            time.sleep(2)
            with self.lock:
                for port, (match_id, proc) in list(self.running.items()):
                    code = proc.poll()
                    if code is not None:
                        del self.running[port]
                        print(f"[launcher] {match_id} exited ({code}); port {port} free", flush=True)

    def health(self):
        with self.lock:
            return {"running": len(self.running), "max": self.max_matches}


def make_handler(launcher):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body):
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            key = self.headers.get("X-Launcher-Key", "")
            if hmac.compare_digest(key.encode("utf-8"), launcher.launcher_key.encode("utf-8")):
                return True
            self._send(401, {"error": "bad launcher key"})
            return False

        def do_GET(self):
            if not self._authorized():
                return
            if self.path == "/v1/health":
                self._send(200, launcher.health())
            elif self.path == "/v1/maps":
                self._send(200, {"maps": [{"id": n, "name": name} for n, name in sorted(MP_MAPS.items())]})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return
            if self.path != "/v1/matches":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY_BYTES:
                self._send(400, {"error": "bad Content-Length"})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                self._send(400, {"error": "body is not JSON"})
                return
            problem = launcher.check_body(body)
            if problem:
                self._send(400, {"error": problem})
                return
            self._send(*launcher.start(body))

        def log_message(self, fmt, *args):
            print(f"[launcher] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"[launcher] {name} is not set")
    return value


def main():
    max_matches = int(_required("MAX_MATCHES"))
    if not 1 <= max_matches <= 20:
        raise SystemExit("[launcher] MAX_MATCHES must be 1-20 (ports 7100-7119 are published)")
    launcher = Launcher(
        launcher_key=_required("LAUNCHER_KEY"),
        ticket_secret=tickets.secret_from_env(_required("GAME_TICKET_SECRET")),
        public_host=_required("PUBLIC_HOST"),
        port_first=int(os.environ.get("MATCH_PORT_FIRST", "7100")),
        max_matches=max_matches,
        ticket_ttl=float(os.environ.get("TICKET_TTL_SECONDS", "120")),
        ready_timeout=float(os.environ.get("READY_TIMEOUT_SECONDS", "90")),
    )
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), make_handler(launcher))
    print(f"[launcher] listening on :{LISTEN_PORT}, up to {max_matches} matches", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
