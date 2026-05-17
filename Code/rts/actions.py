class RtsActionDefinition:
    """Data-first action definition used by panels and future executors."""

    def __init__(self, action_id, label, description="", cost=None, duration_ms=0, action_type="generic", payload=None):
        self.action_id = action_id
        self.label = label
        self.description = description
        self.cost = dict(cost or {})
        self.duration_ms = int(duration_ms or 0)
        self.action_type = action_type
        self.payload = dict(payload or {})

    @classmethod
    def from_dict(cls, action_id, data):
        data = data or {}
        return cls(
            action_id=action_id,
            label=data.get("label") or str(action_id).replace("_", " ").title(),
            description=data.get("description", ""),
            cost=data.get("cost") or {},
            duration_ms=data.get("duration_ms", 0),
            action_type=data.get("type", "generic"),
            payload=data.get("payload") or {},
        )

    def is_available(self, resources):
        if resources is None:
            return True
        return resources.can_afford(self.cost)


class RtsActionQueue:
    """Minimal production/progress queue placeholder for later executors."""

    def __init__(self):
        self.current = None
        self.elapsed_ms = 0

    def start(self, action):
        self.current = action
        self.elapsed_ms = 0

    def update(self, dt):
        if self.current is None:
            return None
        self.elapsed_ms += int(float(dt or 0) * 1000)
        duration = max(0, self.current.duration_ms)
        if duration <= 0 or self.elapsed_ms >= duration:
            finished = self.current
            self.current = None
            self.elapsed_ms = 0
            return finished
        return None

    def progress(self):
        if self.current is None or self.current.duration_ms <= 0:
            return 0.0
        return min(1.0, float(self.elapsed_ms) / float(self.current.duration_ms))
