from dialogue.events import SpeechEvent

_MAX_HOPS = 32


class DialogueRunner:
    """Walks one graph. No drawing, no audio.

    Space/Enter calls `interact`: a line that is still revealing finishes, a finished
    line advances, a choice list selects the highlighted row. Esc calls `end`.
    """

    def __init__(self, dispatcher, chars_per_sec=48):
        self.dispatcher = dispatcher
        self.chars_per_sec = chars_per_sec
        self.graph = None
        self.anchor = None
        self.node_id = None
        self.kind = None
        self.speaker_id = ""
        self.speaker_name = ""
        self.text = ""
        self.audio_key = None
        self.visible_chars = 0
        self.choices = []
        self.choice_index = 0
        self.last_event = None

    @property
    def active(self):
        return self.kind in ("line", "choice")

    @property
    def revealed(self):
        return self.kind != "line" or self.visible_chars >= len(self.text)

    def visible_text(self):
        if self.kind != "line":
            return self.text
        return self.text[: int(self.visible_chars)]

    def start(self, graph, anchor=None):
        self.graph = graph
        self.anchor = anchor
        self.kind = None
        self.node_id = None
        self.choices = []
        self.text = ""
        self.last_event = None
        self._enter(graph["start"])

    def tick(self, dt):
        if self.kind != "line" or self.revealed:
            return
        self.visible_chars += self.chars_per_sec * dt
        if self.visible_chars > len(self.text):
            self.visible_chars = float(len(self.text))

    def interact(self):
        if self.kind == "choice":
            if not self.choices:
                self.end()
                return
            self._select(self.choice_index)
            return
        if self.kind != "line":
            return
        if not self.revealed:
            self.visible_chars = float(len(self.text))
            return
        self._follow(self.node_id)

    def move_choice(self, delta):
        if self.kind != "choice" or not self.choices:
            return
        self.choice_index = (self.choice_index + delta) % len(self.choices)

    def end(self):
        was_active = self.active
        self.kind = None
        self.node_id = None
        self.choices = []
        self.text = ""
        if was_active:
            self.last_event = SpeechEvent(
                kind="end",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                text="",
                anchor=self.anchor,
            )

    def snapshot(self):
        if not self.active:
            return None
        return {
            "kind": self.kind,
            "speaker": self.speaker_name,
            "visible": self.visible_text(),
            "text": self.text,
            "revealed": self.revealed,
            "choices": [
                {"text": choice["text"], "selected": index == self.choice_index}
                for index, choice in enumerate(self.choices)
            ],
        }

    def _enter(self, node_id, hops=0):
        if hops > _MAX_HOPS:
            raise ValueError(f"dialogue cycle in {self.graph.get('id')!r}")
        if node_id is None:
            self.end()
            return
        node = self.graph["nodes"][node_id]
        if node.get("end") is True:
            self.end()
            return
        if not self.dispatcher.flags.matches(node.get("require")):
            self._enter(node.get("next"), hops + 1)
            return
        if "choices" in node:
            self._enter_choices(node_id, node, hops)
            return
        self._enter_line(node_id, node)

    def _enter_choices(self, node_id, node, hops):
        flags = self.dispatcher.flags
        visible = [choice for choice in node["choices"] if flags.matches(choice.get("require"))]
        if not visible:
            self._enter(node.get("next"), hops + 1)
            return
        self.node_id = node_id
        self.kind = "choice"
        self.choices = visible
        self.choice_index = 0
        self.text = node.get("text") or ""
        self.visible_chars = float(len(self.text))
        self._apply_speaker(node)
        self.audio_key = node.get("audio")
        self._emit("choice")
        if node.get("command"):
            self.dispatcher.dispatch(node["command"])

    def _enter_line(self, node_id, node):
        self.node_id = node_id
        self.kind = "line"
        self.choices = []
        self.text = node.get("text") or ""
        self.visible_chars = 0
        self._apply_speaker(node)
        self.audio_key = node.get("audio")
        self._emit("line")
        if node.get("command"):
            self.dispatcher.dispatch(node["command"])

    def _apply_speaker(self, node):
        if node.get("speaker"):
            self.speaker_name = node["speaker"]
            self.speaker_id = node.get("speaker_id") or node["speaker"]

    def _follow(self, node_id):
        nxt = self.graph["nodes"][node_id].get("next")
        if not nxt:
            self.end()
            return
        self._enter(nxt)

    def _select(self, index):
        choice = self.choices[index]
        if choice.get("command"):
            self.dispatcher.dispatch(choice["command"])
        nxt = choice.get("next")
        if not nxt:
            self.end()
            return
        self._enter(nxt)

    def _emit(self, kind):
        self.last_event = SpeechEvent(
            kind=kind,
            speaker_id=self.speaker_id,
            speaker_name=self.speaker_name,
            text=self.text,
            audio_key=self.audio_key,
            anchor=self.anchor,
            node_id=self.node_id or "",
        )
