from dialogue.events import SpeechEvent


class BarkDirector:
    """One-line speech that does not take input.

    Each bark has its own cooldown. A global cap stops a crowd from starting
    several lines in the same short window.
    """

    def __init__(self, table, cooldown_ms=8000, max_active=2, active_ms=4000):
        self.table = table or {}
        self.cooldown_ms = cooldown_ms
        self.max_active = max_active
        self.active_ms = active_ms
        self._last = {}
        self._starts = []

    def try_play(self, bark_id, now_ms, anchor=None):
        spec = self.table.get(bark_id)
        if not isinstance(spec, dict):
            return None
        cooldown = int(spec.get("cooldown_ms", self.cooldown_ms))
        last = self._last.get(bark_id)
        if last is not None and now_ms - last < cooldown:
            return None
        window = int(spec.get("active_ms", self.active_ms))
        self._starts = [started for started in self._starts if now_ms - started < window]
        if len(self._starts) >= self.max_active:
            return None
        self._last[bark_id] = now_ms
        self._starts.append(now_ms)
        speaker = spec.get("speaker") or ""
        return SpeechEvent(
            kind="bark",
            speaker_id=spec.get("speaker_id") or speaker,
            speaker_name=speaker,
            text=spec.get("text") or "",
            audio_key=spec.get("audio"),
            anchor=anchor,
            node_id=bark_id,
        )
