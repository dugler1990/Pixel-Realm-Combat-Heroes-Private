"""Local SAM3, called out of process.

``from_sam3`` used to import ``..collision.sam3.roboflow_workflow``, which posts the image to
``serverless.roboflow.com``. The model actually being used is the local one at ``sam3local/``,
and it cannot be imported here: it lives in its own venv (Python 3.12, torch cu118), so
pulling it into this interpreter would mean torch in the game's environment.

So it runs out of process, and the contract between the two projects is a file. By default
the call goes to sam3local's local server (`scripts/serve.py`), started here on first use, which
keeps the model loaded between calls -- loading it is most of a run's time on the GTX 1050. With
``SAM3LOCAL_SERVER=0``, or a sam3local without a server, each call is one `run_chunk.py` process
instead. Either way the run writes the same ``polygons.json``, and that contract already exists
and already matches: ``polygons.json`` entries are
``{class, prompt, confidence, points}`` -- the same shape ``extract_polygons`` returned, so
the class filtering in ``identify`` is untouched by the swap.

Tiling lives over there too (``--tile`` covers 5056x3392 through ``tile_runner.py``), which
is why there is no chunk sweep in this file. The collision pass had to write one because the
Roboflow endpoint takes one modest image at a time; the local runner does not.
"""

from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

# Set here rather than relying on `building_interiors` having been imported first: whether this
# module can open a level image at all should not depend on import order.
Image.MAX_IMAGE_PIXELS = None

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO.parent / "sam3local"

# PIL's own default warning threshold. `sam3local` never sets `MAX_IMAGE_PIXELS`, so its PIL
# warns above this and raises DecompressionBombError at twice it -- on `Image.open`, before a
# single inference pass. Staying under the warning line keeps both processes quiet.
MAX_DISCOVERY_PIXELS = 89_478_485

# Fallbacks for the tile estimate, used only when sam3local's config cannot be read. The
# estimate is advisory: it turns "too big" into "this many passes", which is the number that
# decides whether a run is worth starting.
DEFAULT_TILE_SIZE = 560
DEFAULT_TILE_OVERLAP = 0.15


class SamLocalError(RuntimeError):
    pass


def sam3local_root() -> Path:
    """Where the local SAM3 project lives. Overridable, because it is outside this repo."""
    return Path(os.environ.get("SAM3LOCAL_ROOT", DEFAULT_ROOT))


def _interpreter(root: Path) -> Path:
    """The venv's own python. Not this one -- torch is not installed here and should not be."""
    for candidate in (root / ".venv" / "Scripts" / "python.exe",
                      root / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    raise SamLocalError(
        f"no virtualenv at {root / '.venv'}. SAM3 runs in its own environment; see "
        f"{root / 'README.md'} for the setup, or set SAM3LOCAL_ROOT if it lives elsewhere.")


def required_downscale(size, limit: int = MAX_DISCOVERY_PIXELS) -> int:
    """Smallest integer factor that brings `size` under the limit. 1 when it already is.

    Integer because the polygons come back multiplied by it, and a whole number keeps that
    reversible arithmetic exact.
    """
    width, height = size
    factor = 1
    while (width / factor) * (height / factor) > limit:
        factor += 1
    return factor


def tile_estimate(size, root: Path = None) -> int:
    """How many tiles sam3local will cut this into, per prompt.

    Read from its config rather than assumed, so the number stays true if the tiling is
    retuned over there.
    """
    tile, overlap = DEFAULT_TILE_SIZE, DEFAULT_TILE_OVERLAP
    try:
        config = json.loads(
            ((root or sam3local_root()) / "config" / "inference.json").read_text(
                encoding="utf-8"))
        tile = int(config.get("tile_size", config.get("image_size", tile)))
        overlap = float(config.get("tile_overlap", overlap))
    except (OSError, ValueError, TypeError):
        pass
    step = max(1.0, tile * (1.0 - overlap))
    return math.ceil(size[0] / step) * math.ceil(size[1] / step)


def _too_big(size, downscale: int, prompts) -> str:
    """The message when an image cannot be handed to SAM3 as it stands. Empty when it can.

    This message is the feature: it is the only place that knows both what will break and
    what to pass instead.
    """
    scaled = (size[0] // downscale, size[1] // downscale)
    if scaled[0] * scaled[1] <= MAX_DISCOVERY_PIXELS:
        return ""

    needed = required_downscale(size)
    quick = max(needed, 4)
    lines = [
        f"{size[0]}x{size[1]} is {size[0] * size[1] / 1e6:.1f} MP"
        + (f" (still {scaled[0] * scaled[1] / 1e6:.1f} MP at --downscale {downscale})"
           if downscale > 1 else ""),
        f"and SAM3's PIL refuses anything over {MAX_DISCOVERY_PIXELS / 1e6:.1f} MP -- it fails "
        f"on opening the file, before segmenting anything.",
        "",
        f"  --downscale {needed:<3} {size[0] // needed}x{size[1] // needed}, "
        f"{tile_estimate((size[0] // needed, size[1] // needed)) * max(1, len(prompts))} passes"
        f"   (the smallest that runs)",
    ]
    if quick != needed:
        lines.append(
            f"  --downscale {quick:<3} {size[0] // quick}x{size[1] // quick}, "
            f"{tile_estimate((size[0] // quick, size[1] // quick)) * max(1, len(prompts))} "
            f"passes   (faster; edges land within {quick}px once scaled back)")
    lines += [
        "",
        "Nothing is resized without being asked: pick one and pass it.",
    ]
    return "\n".join(lines)


def _downscaled_copy(image_path: Path, factor: int, work: Path) -> Path:
    """A resized copy for SAM3 to look at. The original is what everything else reads."""
    with Image.open(image_path) as original:
        size = (original.width // factor, original.height // factor)
        out = Path(work) / f"{image_path.stem}_x{factor}.png"
        if out.exists():
            with Image.open(out) as existing:
                if existing.size == size:
                    print(f"  reusing {out.name} ({size[0]}x{size[1]})")
                    return out
        print(f"  downscaling {original.width}x{original.height} -> {size[0]}x{size[1]} "
              f"(1/{factor}) for discovery only", flush=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        original.convert("RGB").resize(size, Image.LANCZOS).save(out)
    return out


def _scaled_back(polygons: list, factor: int) -> list:
    """Discovery coordinates -> full-resolution level coordinates.

    Everything downstream -- the crop, the chamber, the collision quads, the TMX -- is in the
    full-resolution space, so this is the only place the factor exists.
    """
    if factor == 1:
        return polygons
    out = []
    for polygon in polygons:
        scaled = dict(polygon)
        scaled["points"] = [[float(x) * factor, float(y) * factor]
                            for x, y in polygon["points"]]
        out.append(scaled)
    return out


def write_prompts(prompts, path: Path) -> Path:
    """The two typed answers as a prompts file the local runner accepts.

    ``normalize_prompts`` over there takes a bare list of strings and makes each one both the
    prompt and the class name, which is exactly what the class filtering downstream expects.
    """
    kept = [p.strip() for p in prompts if p and p.strip()]
    if not kept:
        raise SamLocalError("no prompts given; SAM3 needs at least the object prompt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"prompts": kept}, indent=2) + "\n", encoding="utf-8")
    return path


def _request(target: Path, size, prompts, tile: bool) -> dict:
    """What this pass is being asked. Two identical requests cannot have different answers.

    Deliberately not a hash of the image bytes: the crops are hundreds of megabytes and are
    written by `_crop`, which already refuses to overwrite one of the right size. Path plus
    dimensions plus the prompt list is the whole of what varies.
    """
    return {"image": str(Path(target).resolve()), "size": list(size),
            "prompts": list(prompts), "tile": bool(tile)}


def _cached(work: Path, chunk_id: str, request: dict):
    """The previous answer to this exact request, or None.

    A SAM pass is the only slow thing in the pipeline -- a fresh subprocess loads the model
    onto the GPU before it segments anything -- and re-running the tool after a code change
    would otherwise redo every one of them to reach the same numbers.
    """
    folder = Path(work) / chunk_id
    sidecar, result = folder / "request.json", folder / "polygons.json"
    if not (sidecar.exists() and result.exists()):
        return None
    try:
        if json.loads(sidecar.read_text(encoding="utf-8")) != request:
            return None
        return json.loads(result.read_text(encoding="utf-8")).get("polygons", [])
    except (OSError, ValueError):
        return None


def _run_subprocess(root: Path, script: Path, target: Path, chunk_id: str, work: Path,
                    prompts_path: Path, tile: bool, timeout: int) -> str:
    """One `run_chunk.py` process for this call: it loads the model, runs, and exits. Only when
    the server is switched off (`SAM3LOCAL_SERVER=0`) or sam3local has none. Returns its output."""
    command = [
        str(_interpreter(root)), str(script),
        "--image", str(target),
        "--chunk-id", chunk_id,
        "--out", str(work),
        "--prompts", str(prompts_path),
    ]
    # Both flags are explicit: left to itself `run_chunk` tiles anything bigger than one tile,
    # so an untiled locate pass has to say so or it silently becomes the sweep it replaces.
    command.append("--tile" if tile else "--no-tile")
    finished = subprocess.run(command, cwd=str(root), timeout=timeout,
                              capture_output=True, text=True)
    if finished.returncode != 0:
        raise SamLocalError(
            f"local SAM3 failed ({finished.returncode}):\n{finished.stdout}\n{finished.stderr}")
    return finished.stdout


# The local SAM3 server (sam3local `scripts/serve.py`, `sam3_local/server.py`) keeps the model
# loaded between calls. These mirror the few facts of its protocol this side needs; the two
# projects share no code, only `config/server.json` and the files a run writes.
SERVER_HOST = "127.0.0.1"
SERVER_SERVICE = "sam3local"
SERVER_PORT_TAKEN = 3            # `serve.py start` exit code: another server has the port
SERVER_START_TIMEOUT = 300       # s: the model load, paid once per server


def _server_config(root: Path) -> dict:
    path = root / "config" / "server.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SamLocalError(f"cannot read {path}: {exc}") from exc


def _server_log(root: Path) -> Path:
    return root / "output" / "server.log"


def _health(port: int, timeout: float = 2.0):
    """The server's `/health`, or None when no sam3local server answers on `port` -- including
    some other program that happens to hold it."""
    try:
        with urllib.request.urlopen(f"http://{SERVER_HOST}:{port}/health",
                                    timeout=timeout) as reply:
            data = json.loads(reply.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("service") == SERVER_SERVICE else None


def _listening(port: int) -> bool:
    try:
        with socket.create_connection((SERVER_HOST, port), timeout=1.0):
            return True
    except OSError:
        return False


def _wait_gone(port: int, timeout: float = 3600.0) -> None:
    """Until a stopping server has closed the port, so a fresh one can bind it."""
    deadline = time.monotonic() + timeout
    while _listening(port):
        if time.monotonic() > deadline:
            raise SamLocalError(f"the SAM3 server on port {port} did not stop")
        time.sleep(0.5)


def _start_server(root: Path, port: int) -> None:
    """Start the server detached -- it outlives this process, which is the point -- and wait
    until it answers. Raises with the log's path when it does not come up."""
    log = _server_log(root)
    idle = float(_server_config(root).get("idle_minutes", 15))
    command = [str(_interpreter(root)), str(root / "scripts" / "serve.py"), "start",
               "--log", str(log)]
    detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    print(f"  starting the SAM3 server (loads the model once, stops after {idle:g} idle "
          f"minutes) ...", flush=True)
    child = subprocess.Popen(command, cwd=str(root), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, **detach)
    deadline = time.monotonic() + SERVER_START_TIMEOUT
    while time.monotonic() < deadline:
        if _health(port) is not None:
            return
        code = child.poll()
        # Port taken: another server is up or loading; keep waiting for that one.
        if code is not None and code != SERVER_PORT_TAKEN:
            raise SamLocalError(f"the SAM3 server stopped while starting (exit {code}); "
                                f"see {log}")
        time.sleep(1.0)
    taken = " -- or another program holds that port" if child.poll() == SERVER_PORT_TAKEN else ""
    raise SamLocalError(f"the SAM3 server did not answer on port {port} within "
                        f"{SERVER_START_TIMEOUT}s{taken}; see {log}")


def _post(port: int, path: str, body: dict, timeout: float) -> tuple:
    request = urllib.request.Request(f"http://{SERVER_HOST}:{port}{path}",
                                     data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except ValueError:
            return error.code, {}


def _run_server(root: Path, target: Path, chunk_id: str, work: Path, prompts_path: Path,
                tile: bool, timeout: int) -> str:
    """This call through the local SAM3 server, started if it is not up. Returns its output.

    A server that refuses because sam3local changed since it started (409), or that is on
    its way out (503), is replaced once. Anything else that goes wrong raises: a server that
    cannot start is a failure to see, not a reason to quietly load the model per call again.
    """
    port = int(_server_config(root)["port"])
    body = {"image": str(target), "chunk_id": chunk_id, "out": str(work),
            "prompts": str(prompts_path), "tile": bool(tile)}
    replaced = False
    while True:
        if _health(port) is None:
            _start_server(root, port)
        try:
            status, reply = _post(port, "/run", body, timeout)
        except OSError as exc:
            raise SamLocalError(f"lost the SAM3 server during {chunk_id} ({exc}); "
                                f"see {_server_log(root)}") from exc
        if status in (409, 503) and not replaced:
            print(f"  the SAM3 server is out of date or stopping "
                  f"({reply.get('stale') or reply.get('error')}); starting a fresh one",
                  flush=True)
            _wait_gone(port)
            replaced = True
            continue
        if status == 200 and reply.get("code") == 0:
            return reply.get("log", "")
        raise SamLocalError(f"local SAM3 failed ({status}, code {reply.get('code')}):\n"
                            f"{reply.get('log', '')}\n{reply.get('error', '')}")


def segment(image_path: Path, prompts, work: Path, *, chunk_id: str = "interiors",
            tile: bool = True, timeout: int = 3600, downscale: int = 1,
            rescan: bool = False) -> list:
    """Run every prompt over one image and return the polygons it found.

    Coordinates come back in the *given image's* pixel space -- full resolution even when
    `downscale` was used, because the factor is undone here. The caller adds the crop origin
    when the image is not the whole level.

    `downscale` is never chosen for you. An image SAM3 cannot open raises instead, with the
    factors to pass; resizing the input silently would mean every coordinate afterwards was
    quietly wrong by a factor nobody wrote down.
    """
    image_path = Path(image_path).resolve()
    if not image_path.exists():
        raise SamLocalError(f"no image at {image_path}")
    if downscale < 1:
        raise SamLocalError(f"--downscale must be 1 or more, got {downscale}")

    root = sam3local_root()
    script = root / "scripts" / "run_chunk.py"
    if not script.exists():
        raise SamLocalError(f"no run_chunk.py under {root}; set SAM3LOCAL_ROOT")

    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as probe:
        size = probe.size
    complaint = _too_big(size, downscale, prompts)
    if complaint:
        raise SamLocalError(complaint)

    target = image_path if downscale == 1 else _downscaled_copy(image_path, downscale, work)
    with Image.open(target) as probe:
        target_size = probe.size
        # Untiled is one pass per prompt whatever the size: SAM resizes the whole image to its
        # own input edge, so there is nothing to count tiles of.
        passes = (tile_estimate(target_size) if tile else 1) * max(1, len(prompts))

    request = _request(target, target_size, prompts, tile)
    cached = _cached(work, chunk_id, request) if not rescan else None
    if cached is not None:
        polygons = _scaled_back(cached, downscale)
        print(f"  {chunk_id}: reusing {len(polygons)} polygon(s) from the last scan "
              f"(same crop, same prompts) -- pass --rescan to redo it")
        return polygons

    prompts_path = write_prompts(prompts, work / "sam3_prompts.json")
    print(f"  local SAM3 on {target.name} ({', '.join(prompts)}), "
          f"~{passes} passes ...", flush=True)
    if os.environ.get("SAM3LOCAL_SERVER") == "0" or not (root / "scripts" / "serve.py").exists():
        output = _run_subprocess(root, script, target, chunk_id, work, prompts_path, tile,
                                 timeout)
    else:
        output = _run_server(root, target, chunk_id, work, prompts_path, tile, timeout)

    result = work / chunk_id / "polygons.json"
    if not result.exists():
        raise SamLocalError(f"local SAM3 wrote no {result}:\n{output}")
    document = json.loads(result.read_text(encoding="utf-8"))
    (result.parent / "request.json").write_text(
        json.dumps(request, indent=2) + "\n", encoding="utf-8")
    polygons = _scaled_back(document.get("polygons", []), downscale)
    scaled = f" (scaled back x{downscale})" if downscale > 1 else ""
    print(f"  {len(polygons)} polygon(s){scaled}; overlay at "
          f"{work / chunk_id / 'overlay_preview.png'}")
    return polygons
