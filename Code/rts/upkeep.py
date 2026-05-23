from .categories import FOOD


class FoodUpkeep:
    """Passive food drain proportional to population."""

    def __init__(self):
        self.low_food = False
        self._accumulator = 0.0

    def update(self, dt, wallet, population, per_unit_per_min):
        self.low_food = False
        if wallet is None or not wallet.is_active(FOOD):
            return
        pop = max(0, int(population))
        if pop <= 0 or per_unit_per_min <= 0:
            return
        drain_per_sec = (pop * float(per_unit_per_min)) / 60.0
        self._accumulator += drain_per_sec * float(dt or 0)
        while self._accumulator >= 1.0:
            wallet.drain(FOOD, 1)
            self._accumulator -= 1.0
        if wallet.get(FOOD) <= 5:
            self.low_food = True
