import time

from .categories import ALL_CATEGORIES


class TribeResources:
    """Legacy wallet used by action costs; delegates to string keys."""

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


class ResourceWallet:
    """Five-slot faction resource stockpile with per-minute rate tracking."""

    def __init__(self, active_categories=None):
        self.active_categories = set(active_categories or ALL_CATEGORIES)
        self._amounts = {cat: 0 for cat in ALL_CATEGORIES}
        self._rate_per_min = {cat: 0.0 for cat in ALL_CATEGORIES}
        self._rate_window = []
        self._rate_window_start = time.monotonic()

    def is_active(self, category):
        return category in self.active_categories

    def get(self, category):
        return int(self._amounts.get(category, 0))

    def set(self, category, amount):
        if category in ALL_CATEGORIES:
            self._amounts[category] = max(0, int(amount))

    def add(self, category, amount):
        if not self.is_active(category):
            return
        self._amounts[category] = self.get(category) + int(amount)
        self._record_delta(category, int(amount))

    def drain(self, category, amount):
        if not self.is_active(category):
            return
        taken = min(self.get(category), int(amount))
        self._amounts[category] = self.get(category) - taken
        if taken:
            self._record_delta(category, -taken)

    def get_rate_per_min(self, category):
        self._refresh_rates()
        return self._rate_per_min.get(category, 0.0)

    def reset_rates(self):
        self._rate_window = []
        self._rate_window_start = time.monotonic()
        for cat in ALL_CATEGORIES:
            self._rate_per_min[cat] = 0.0

    def _record_delta(self, category, delta):
        now = time.monotonic()
        self._rate_window.append((now, category, delta))

    def _refresh_rates(self):
        now = time.monotonic()
        cutoff = now - 60.0
        self._rate_window = [
            entry for entry in self._rate_window if entry[0] >= cutoff
        ]
        totals = {cat: 0 for cat in ALL_CATEGORIES}
        for _, cat, delta in self._rate_window:
            totals[cat] = totals.get(cat, 0) + delta
        elapsed = max(0.001, now - cutoff)
        scale = 60.0 / elapsed
        for cat in ALL_CATEGORIES:
            self._rate_per_min[cat] = totals[cat] * scale

    def can_afford(self, cost):
        for resource_id, amount in (cost or {}).items():
            if self.get(resource_id) < int(amount):
                return False
        return True

    def spend(self, cost):
        if not self.can_afford(cost):
            return False
        for resource_id, amount in (cost or {}).items():
            self.drain(resource_id, int(amount))
        return True

    def to_legacy(self):
        """Expose wallet as TribeResources for RtsPanel action costs."""
        return TribeResources(dict(self._amounts))
