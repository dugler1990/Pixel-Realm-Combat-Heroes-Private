from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class SpeechEvent:
    """One spoken moment, whether it came from a bark or a conversation line.

    Presentation and voice listen to this. They do not walk the graph themselves.
    """

    kind: str
    speaker_id: str
    speaker_name: str
    text: str
    audio_key: Optional[str] = None
    anchor: Any = None
    skippable: bool = True
    node_id: str = ""
