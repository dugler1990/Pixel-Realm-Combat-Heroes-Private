class InteractFocus:
    def __init__(self, target, kind, prompt):
        self.target = target
        self.kind = kind
        self.prompt = prompt


def nearest_focus(player, candidates):
    """The closest candidate whose inflated rect touches the player.

    One winner, so the on-screen prompt and the Space key name the same object.
    An `opened` candidate is skipped. `can_interact(player)` can refuse too.
    """
    player_rect = getattr(player, "rect", None)
    if player_rect is None:
        return None
    player_center = player_rect.center
    best = None
    best_distance = None
    for candidate in candidates:
        if candidate is None or getattr(candidate, "opened", False):
            continue
        allow = getattr(candidate, "can_interact", None)
        if allow is not None and not allow(player):
            continue
        rect = getattr(candidate, "rect", None)
        if rect is None:
            continue
        margin = int(getattr(candidate, "interaction_margin", 48))
        if not player_rect.colliderect(rect.inflate(margin, margin)):
            continue
        center = rect.center
        distance = (player_center[0] - center[0]) ** 2 + (player_center[1] - center[1]) ** 2
        if best is None or distance < best_distance:
            best = candidate
            best_distance = distance
    if best is None:
        return None
    kind = str(getattr(best, "kind", "interact") or "interact")
    prompt = getattr(best, "prompt_text", None) or _default_prompt(kind)
    return InteractFocus(best, kind, prompt)


def _default_prompt(kind):
    if kind == "talk":
        return "[Space] Talk"
    if kind == "seat":
        return "[Space] Sit"
    if kind == "loot_container":
        return "[Space] Open"
    return "[Space] Interact"
