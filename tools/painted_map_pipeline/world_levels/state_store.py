from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def atomic_write_json(path: str | Path, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def append_event(root: str | Path, event: str, **fields: Any) -> None:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": utc_now(), "event": event, **fields}
    with (root_path / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def update_level_state(
    root: str | Path,
    level_id: str,
    state: str,
    **fields: Any,
) -> dict[str, Any]:
    root_path = Path(root)
    run_path = root_path / "run.json"
    run = read_json(run_path)
    level = run.setdefault("levels", {}).setdefault(level_id, {})
    level.update({"state": state, "updated_at": utc_now(), **fields})
    atomic_write_json(run_path, run)
    append_event(root_path, "state_changed", level_id=level_id, state=state, **fields)
    return run
