class TribeResources:
    """Resource wallet for RTS actions."""

    def __init__(self, initial=None):
        self.values = dict(initial or {})

    def get(self, resource_id):
        return int(self.values.get(resource_id, 0))

    def add(self, resource_id, amount):
        self.values[resource_id] = self.get(resource_id) + int(amount)

    def can_afford(self, cost):
        for resource_id, amount in (cost or {}).items():
            if self.get(resource_id) < int(amount):
                return False
        return True

    def spend(self, cost):
        if not self.can_afford(cost):
            return False
        for resource_id, amount in (cost or {}).items():
            self.values[resource_id] = self.get(resource_id) - int(amount)
        return True
