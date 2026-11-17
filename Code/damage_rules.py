"""How a blow meets layers (damage chunk 5). No pygame: the card and the resolver share this.

`physical` does not mutate the attack def or the layer defs. Magic, venom and wear are not here
(chunks 7, 8, 10). A pierce that stops deals no wound, only a bruise from the force that arrived;
a point that gets through deals its full damage (partial penetration is later).
"""
from __future__ import annotations

BRUISE_SCALE = 0.05  # force that becomes health. 2 is a speck; 120 still shows. Tune in play.


class Physical:
    """amount: the wound before rounding. bruise: health from the force that arrived.
    reached_flesh: a pierce got through the last layer (venom, chunk 8, will read this).
    stopped_at: the layer a pierce stopped on; None if it went through or was not a pierce."""

    __slots__ = ("amount", "bruise", "reached_flesh", "stopped_at")

    def __init__(self, amount, bruise, reached_flesh, stopped_at):
        self.amount = amount
        self.bruise = bruise
        self.reached_flesh = reached_flesh
        self.stopped_at = stopped_at

    def __repr__(self):
        return (f"Physical(amount={self.amount:g}, bruise={self.bruise:g}, "
                f"flesh={self.reached_flesh}, stopped={self.stopped_at!r})")


def landed(result):
    """The int subtracted from health."""
    return int(round(result.amount + result.bruise))


def _cushion(layers):
    product = 1.0
    for layer in layers:
        product *= 1.0 - layer.absorb
    return product


def _bruise(force, layers):
    return force * _cushion(layers) * BRUISE_SCALE


def physical(delivery, damage, penetration, force, layers):
    """One blow against `layers` (outer first, the hide last).

    pierce: stop where penetration cannot beat stopping_power. crush and blast: no stop,
    the wound and the force are both cut by every layer's absorb.
    """
    if delivery == "pierce":
        pen = penetration
        met = []
        for layer in layers:
            met.append(layer)
            if pen - layer.stopping_power <= 0:
                return Physical(0.0, _bruise(force, met), False, layer)
            pen = pen - layer.stopping_power
        return Physical(float(damage), _bruise(force, met), True, None)
    if delivery in ("crush", "blast"):
        return Physical(float(damage) * _cushion(layers), _bruise(force, layers), False, None)
    raise ValueError(f"unknown delivery {delivery!r}")
