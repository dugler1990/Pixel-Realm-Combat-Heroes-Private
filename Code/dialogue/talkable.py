class TalkAnchor:
    """A sprite the player can talk to. The sprite keeps its own AI.

    `rect` follows the sprite, so a roaming NPC stays the focus target.
    """

    kind = "talk"

    def __init__(self, sprite, graph_id, name, barks=None, margin=48):
        self.sprite = sprite
        self.graph_id = graph_id
        self.display_name = name
        self.speaker_id = graph_id
        self.barks = list(barks or [])
        self.interaction_margin = int(margin)
        self.prompt_text = "[Space] Talk"

    @property
    def rect(self):
        return self.sprite.rect
