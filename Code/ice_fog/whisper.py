"""Wind whisper helpers — SpeechEvent + ConversationPanel snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from dialogue.events import SpeechEvent

DEFAULT_WHISPERS_PATH = (
    Path(__file__).resolve().parent.parent / "dialogue" / "content" / "wind_whispers.json"
)


def load_wind_whispers(path=None) -> Dict:
    path = Path(path) if path is not None else DEFAULT_WHISPERS_PATH
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def whisper_event(line_id: str, table: Optional[Dict] = None) -> Optional[SpeechEvent]:
    table = table if table is not None else load_wind_whispers()
    spec = table.get(line_id)
    if not isinstance(spec, dict):
        return None
    speaker = spec.get("speaker") or "Wind"
    return SpeechEvent(
        kind="whisper",
        speaker_id=spec.get("speaker_id") or "wind",
        speaker_name=speaker,
        text=spec.get("text") or "",
        audio_key=spec.get("audio"),
        skippable=True,
        node_id=line_id,
    )


def whisper_panel_snapshot(event: SpeechEvent) -> Dict:
    """Snapshot shape compatible with ConversationPanel.draw."""
    return {
        "kind": "whisper",
        "speaker": event.speaker_name,
        "visible": event.text,
        "revealed": True,
        "choices": [],
    }
