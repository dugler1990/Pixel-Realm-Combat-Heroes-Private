"""Serve the viewer AND run the retarget for it. Replaces `python -m http.server`.

    python tools/boss_sprite_pipeline/viewer/serve.py [port]

`http.server` can only hand out files, so importing new clips meant dropping to a shell and
running wire_picks.sh by hand. This adds two routes on top of the same static serving:

    POST /api/import   {"label": "...", "src": "..."}   -> starts wire_picks.sh, returns a job id
    GET  /api/status                                     -> {running, lines, label, done, rc}

so the viewer gets an Import button and the whole loop - prompt on the pod, save the BVH, press
Import, watch it on the demon - never leaves the browser.

Only one import runs at a time; the log is kept in memory and streamed to the panel as plain
text lines, which is enough to see which clip is being retargeted and to read a failure.
"""
import json
import os
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SCRIPT = os.path.join(ROOT, "tools", "boss_sprite_pipeline", "viewer", "wire_picks.sh")

JOB = {"running": False, "lines": [], "label": None, "rc": None, "done": False}
LOCK = threading.Lock()


def run_import(label, src):
    with LOCK:
        JOB.update(running=True, lines=[], label=label, rc=None, done=False)
    cmd = ["bash", SCRIPT, src, label]
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        for line in p.stdout:
            line = line.rstrip()
            if not line:
                continue
            with LOCK:
                JOB["lines"].append(line)
                # the retarget is chatty; keep the tail bounded so the panel stays readable
                del JOB["lines"][:-400]
        p.wait()
        rc = p.returncode
    except Exception as e:                      # bash missing, script missing, anything
        with LOCK:
            JOB["lines"].append("LAUNCH FAILED: %r" % (e,))
        rc = -1
    with LOCK:
        JOB.update(running=False, rc=rc, done=True)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # the viewer re-fetches clips.json after an import; a cached copy would hide new clips
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if self.path.endswith((".json", ".html", "/")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/status":
            with LOCK:
                return self._json(dict(JOB))
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/import":
            return self._json({"error": "no such route"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            req = {}
        label = str(req.get("label") or "picks")
        label = "".join(c for c in label if c.isalnum() or c in "_-") or "picks"
        src = str(req.get("src") or "/c/Users/Douglas/Downloads")
        with LOCK:
            if JOB["running"]:
                return self._json({"error": "an import is already running"}, 409)
        threading.Thread(target=run_import, args=(label, src), daemon=True).start()
        return self._json({"started": True, "label": label})

    def log_message(self, *a):
        pass                                    # the access log drowns the import output


if __name__ == "__main__":
    print("root   %s" % ROOT)
    print("open   http://localhost:%d/tools/boss_sprite_pipeline/viewer/"
          "?base=/generated/bosses/demon/picks/approved9" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
