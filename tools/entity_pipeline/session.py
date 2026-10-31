"""One pipeline run lives in generated/entity_pipeline/<session>/."""
from __future__ import annotations

import json
from pathlib import Path

WORK_ROOT = Path("generated/entity_pipeline")


def session_dir(name: str) -> Path:
    path = WORK_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(name: str) -> Path:
    return session_dir(name) / "session.json"


def load_session(name: str) -> dict:
    path = session_path(name)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"session": name, "calls": []}


def save_session(name: str, data: dict) -> None:
    session_path(name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def record_call(name: str, step: str, result: dict) -> None:
    """Keep the cost Leonardo returned for this call. It may be null."""
    data = load_session(name)
    calls = data.setdefault("calls", [])
    calls.append({
        "step": step,
        "cost_usd": result.get("cost_usd"),
        "output": result.get("output_path"),
    })
    save_session(name, data)
