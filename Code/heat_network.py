"""Warmth of a few layers that pull on each other and on fixed sources, solved exactly.

Pure: no pygame, no entities (docs/damage/PLAN_temperature.md). Between two events every source is
fixed, so the layers follow

    C·x' = −(K + L)·x + s

C: each layer's capacity. K: each layer's total source strength (Σk). s: Σk·T per layer. L: the
links between layers (g per link). The answer is a steady state plus one decaying exponential per
layer: `Curve`. Time is in seconds from the curve's start.

Only `solve` uses numpy (once per event). Reading a curve is plain floats: a few exponentials.
"""
import math

import numpy

_EPS = 1e-12
_TOL_S = 1e-4   # crossings to 0.1 ms: the clock wakes in whole ms


def solve(start, capacity, pull, links=()):
    """The curve from `start` (warmth per layer).

    `capacity`: per layer, > 0. `pull`: per layer, (Σk, Σk·T) of the sources on it. `links`:
    (i, j, g) between two layers. A layer with no source and no link keeps its warmth.
    """
    n = len(start)
    if not (len(capacity) == len(pull) == n) or n == 0:
        raise ValueError("start, capacity and pull need one entry per layer")
    if any(c <= 0 for c in capacity):
        raise ValueError(f"capacity must be > 0, got {capacity}")
    m = numpy.zeros((n, n))
    s = numpy.zeros(n)
    for i, (k, kt) in enumerate(pull):
        if k < 0:
            raise ValueError(f"a source strength must be >= 0, got {k}")
        m[i, i] += k
        s[i] = kt
    for i, j, g in links:
        if g < 0:
            raise ValueError(f"a link must be >= 0, got {g}")
        m[i, i] += g
        m[j, j] += g
        m[i, j] -= g
        m[j, i] -= g
    steady = numpy.linalg.lstsq(m, s, rcond=None)[0]
    root = numpy.sqrt(numpy.asarray(capacity, dtype=float))
    # Symmetric form: real, non-negative rates.
    rates, vectors = numpy.linalg.eigh(m / numpy.outer(root, root))
    rates = numpy.clip(rates, 0.0, None)
    weights = vectors.T @ (root * (numpy.asarray(start, dtype=float) - steady))
    coef = (vectors / root[:, None]) * weights[None, :]
    return Curve(steady.tolist(), coef.tolist(), rates.tolist())


class Curve:
    """Layer i at t seconds: steady[i] + Σ_m coef[i][m]·e^(−rates[m]·t)."""

    __slots__ = ("steady", "coef", "rates")

    def __init__(self, steady, coef, rates):
        self.steady = steady
        self.coef = coef
        self.rates = rates

    def at(self, t):
        """Every layer's warmth at t."""
        return [self.layer_at(i, t) for i in range(len(self.steady))]

    def layer_at(self, i, t):
        value = self.steady[i]
        for c, r in zip(self.coef[i], self.rates):
            value += c * math.exp(-r * t)
        return value

    def _terms(self, i, line):
        """Layer i minus `line` as (constant, [(coef, rate)]), rate-0 terms folded in."""
        const = self.steady[i] - line
        terms = {}
        for c, r in zip(self.coef[i], self.rates):
            if abs(c) < _EPS:
                continue
            if r < _EPS:
                const += c
                continue
            key = round(r, 12)
            terms[key] = terms.get(key, 0.0) + c
        return const, sorted(terms.items(), key=lambda kv: kv[0])

    def crossings(self, i, line, t0, t1):
        """Instants in (t0, t1) where layer i crosses `line`, in order."""
        const, terms = self._terms(i, line)
        return _roots(const, [c for _r, c in terms], [r for r, _c in terms], t0, t1)

    def area_past(self, i, line, t0, t1, above=True):
        """∫ max(0, layer − line) over [t0, t1] (above), or ∫ max(0, line − layer) (below)."""
        if t1 <= t0:
            return 0.0
        const, terms = self._terms(i, line)
        sign = 1.0 if above else -1.0
        cuts = [t0] + _roots(const, [c for _r, c in terms], [r for r, _c in terms], t0, t1) + [t1]
        total = 0.0
        for a, b in zip(cuts, cuts[1:]):
            mid = 0.5 * (a + b)
            if sign * _value(const, terms, mid) > 0.0:
                total += sign * _integral(const, terms, a, b)
        return total


def _value(const, terms, t):
    return const + sum(c * math.exp(-r * t) for r, c in terms)


def _integral(const, terms, a, b):
    total = const * (b - a)
    for r, c in terms:
        total += (c / r) * (math.exp(-r * a) - math.exp(-r * b))
    return total


def _roots(const, coefs, rates, t0, t1):
    """Zeros in (t0, t1) of g(t) = const + Σ coefs[m]·e^(−rates[m]·t), rates > 0 and distinct.

    A sum of n exponentials has at most n zeros. Its derivative, times e^(rates[0]·t), is the
    same form with one term fewer, so the extremes come from one level down; between two extremes
    g is monotone and one bisection finds its zero.
    """
    if not coefs:
        return []

    def g(t):
        return const + sum(c * math.exp(-r * t) for c, r in zip(coefs, rates))

    if len(coefs) == 1:
        c, r = coefs[0], rates[0]
        ratio = -const / c
        if ratio <= 0.0:
            return []
        t = -math.log(ratio) / r
        return [t] if t0 < t < t1 else []
    # g'(t)·e^(r0·t) = −r0·c0 + Σ_{m≥1} −r_m·c_m·e^(−(r_m − r0)·t)
    r0 = rates[0]
    extremes = _roots(-r0 * coefs[0], [-r * c for c, r in zip(coefs[1:], rates[1:])],
                      [r - r0 for r in rates[1:]], t0, t1)
    cuts = [t0] + extremes + [t1]
    found = []
    for a, b in zip(cuts, cuts[1:]):
        ga, gb = g(a), g(b)
        if ga == 0.0 and a > t0:
            if not found or found[-1] != a:
                found.append(a)
            continue
        if ga * gb >= 0.0:
            continue
        lo, hi = a, b
        while hi - lo > _TOL_S:
            mid = 0.5 * (lo + hi)
            if (g(mid) > 0.0) == (ga > 0.0):
                lo = mid
            else:
                hi = mid
        found.append(0.5 * (lo + hi))
    return found
