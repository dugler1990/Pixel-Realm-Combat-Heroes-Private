from rts.categories import FOOD, FUEL
from rts.resources import ResourceWallet
from rts.upkeep import FoodUpkeep


def test_wallet_active_categories_and_rates():
    wallet = ResourceWallet({"food", "fuel"})
    assert wallet.is_active(FOOD)
    assert not wallet.is_active(FUEL) or wallet.is_active(FUEL)
    wallet.add(FOOD, 10)
    assert wallet.get(FOOD) == 10
    wallet.add(FUEL, 5)
    assert wallet.get(FUEL) == 5
    wallet.drain(FOOD, 3)
    assert wallet.get(FOOD) == 7


def test_wallet_ignores_inactive_category():
    wallet = ResourceWallet({"food"})
    wallet.add(FUEL, 100)
    assert wallet.get(FUEL) == 0


def test_food_upkeep_drains_over_time():
    wallet = ResourceWallet({"food"})
    wallet.set(FOOD, 20)
    upkeep = FoodUpkeep()
    for _ in range(120):
        upkeep.update(0.5, wallet, population=10, per_unit_per_min=60.0)
    assert wallet.get(FOOD) < 20
