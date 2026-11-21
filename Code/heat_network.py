"""Warmth of a few layers that pull on each other and on fixed sources, solved exactly.

Pure: no pygame, no entities (docs/damage/PLAN_temperature.md). Between two events every source is
fixed, so the layers follow

    C·x' = −(K + L)·x + s

C: each layer's capacity. K: each layer's total source strength (Σk). s: Σk·T per layer. L: the
links between layers (g per link). The answer is a steady state plus one decaying exponential per
layer: `Curve`. Time is in seconds from the curve's start.

One and two layers (a naked body, a body in one piece) are solved by hand in plain floats; more
layers go through numpy once per event. Reading a curve is plain floats: a few exponentials.
"""
import math

import numpy

_EPS = 1e-12
_TOL_S = 1e-4   # crossings to 0.1 ms: wakes are whole ms


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
    if any(k < 0 for k, _kt in pull) or any(g < 0 for _i, _j, g in links):
        raise ValueError("source strengths and links must be >= 0")
    joined = [(i, j, g) for i, j, g in links if g > 0]
    if n == 1:
        return _one(start[0], capacity[0], pull[0])
    if n == 2 and not joined:
        a, b = _one(start[0], capacity[0], pull[0]), _one(start[1], capacity[1], pull[1])
        return Curve([a.steady[0], b.steady[0]], [[a.coef[0][0], 0.0], [0.0, b.coef[0][0]]],
                     [a.rates[0], b.rates[0]])
    if n == 2 and len(joined) == 1:
        curve = _two(start, capacity, pull, joined[0][2])
        if curve is not None:
            return curve
    return _many(start, capacity, pull, joined)


def _one(x0, c, pull):
    k, kt = pull
    if k <= 0:
        return Curve([float(x0)], [[0.0]], [0.0])
    steady = kt / k
    return Curve([steady], [[x0 - steady]], [k / c])


def _two(start, capacity, pull, g):
    """Two layers and one link, by hand. None when the system has no single steady state."""
    (k0, s0), (k1, s1) = pull
    c0, c1 = capacity
    m00, m11 = k0 + g, k1 + g
    det = m00 * m11 - g * g
    if det <= _EPS:
        return None   # no source anywhere: numpy's least squares handles the conserved mean
    x0 = (m11 * s0 + g * s1) / det
    x1 = (g * s0 + m00 * s1) / det
    a00, a01, a10, a11 = m00 / c0, -g / c0, -g / c1, m11 / c1
    tr, dt = a00 + a11, a00 * a11 - a01 * a10
    root = math.sqrt(max(0.0, tr * tr * 0.25 - dt))
    rates = [tr * 0.5 - root, tr * 0.5 + root]
    # Eigenvector of A for each rate: (−a01, a00 − rate); a01 != 0 because g > 0.
    v = [(-a01, a00 - r) for r in rates]
    d0, d1 = start[0] - x0, start[1] - x1
    den = v[0][0] * v[1][1] - v[1][0] * v[0][1]
    if abs(den) <= _EPS:
        return None
    w0 = (d0 * v[1][1] - v[1][0] * d1) / den
    w1 = (v[0][0] * d1 - d0 * v[0][1]) / den
    coef = [[w0 * v[0][0], w1 * v[1][0]], [w0 * v[0][1], w1 * v[1][1]]]
    return Curve([x0, x1], coef, rates)


def _many(start, capacity, pull, links):
    n = len(start)
    m = numpy.zeros((n, n))
    s = numpy.zeros(n)
    for i, (k, kt) in enumerate(pull):
        m[i, i] += k
        s[i] = kt
    for i, j, g in links:
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
            if c:
                value += c * math.exp(-r * t)
        return value

    def reach(self, i, t):
        """How far layer i can still be from its steady state from t on: Σ|coef|·e^(−rate·t).
        A line further away than this is never crossed."""
        return sum(abs(c) * math.exp(-r * t) for c, r in zip(self.coef[i], self.rates) if c)

    def _terms(self, i, line):
        """Layer i minus `line` as (constant, [(rate, coef)]), rate-0 terms folded in."""
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
        return const, sorted(terms.items())

    def crossings(self, i, line, t0, t1):
        """Instants in (t0, t1) where layer i crosses `line`, in order."""
        if abs(self.steady[i] - line) > self.reach(i, t0):
            return []
        const, terms = self._terms(i, line)
        return _roots(const, [c for _r, c in terms], [r for r, _c in terms], t0, t1)

    def first_crossing(self, i, lines, t0, t1):
        """The earliest instant in (t0, t1) layer i crosses any of `lines`, or None.

        The turning points are found once; the curve is monotone between them, so the first
        piece whose ends straddle a line holds the answer, and that line is the one nearest the
        piece's start.
        """
        reach = self.reach(i, t0)
        near = [line for line in lines if abs(self.steady[i] - line) <= reach]
        if not near:
            return None
        const, terms = self._terms(i, 0.0)
        cuts = [t0] + _turns(terms, t0, t1) + [t1]
        fa = _value(const, terms, t0)
        for a, b in zip(cuts, cuts[1:]):
            fb = _value(const, terms, b)
            hit = [line for line in near if (fa - line) * (fb - line) < 0.0]
            if hit:
                line = min(hit, key=lambda x: abs(x - fa))
                return _solve_between(const - line, terms, a, b, fa - line, fb - line)
            fa = fb
        return None

    def area_past(self, i, line, t0, t1, above=True):
        """∫ max(0, layer − line) over [t0, t1] (above), or ∫ max(0, line − layer) (below)."""
        if t1 <= t0:
            return 0.0
        sign = 1.0 if above else -1.0
        gap = sign * (self.steady[i] - line)
        reach = self.reach(i, t0)
        if gap <= -reach:
            return 0.0   # never past the line from t0 on
        const, terms = self._terms(i, line)
        if gap >= reach:
            return sign * _integral(const, terms, t0, t1)   # past it the whole time
        cuts = [t0] + _roots(const, [c for _r, c in terms], [r for r, _c in terms], t0, t1) + [t1]
        total = 0.0
        for a, b in zip(cuts, cuts[1:]):
            if sign * _value(const, terms, 0.5 * (a + b)) > 0.0:
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
    """Zeros in (t0, t1) of g(t) = const + Σ coefs[m]·e^(−rates[m]·t), rates > 0, distinct, rising.

    A sum of n exponentials has at most n zeros. Its derivative, times e^(rates[0]·t), is the
    same form with one term fewer, so the turning points come from one level down; between two
    of them g is monotone and `_solve_between` finds its zero.
    """
    if not coefs:
        return []
    if len(coefs) == 1:
        ratio = -const / coefs[0]
        if ratio <= 0.0:
            return []
        t = -math.log(ratio) / rates[0]
        return [t] if t0 < t < t1 else []

    terms = list(zip(rates, coefs))

    def g(t):
        return _value(const, terms, t)

    cuts = [t0] + _turns(terms, t0, t1) + [t1]
    found = []
    for a, b in zip(cuts, cuts[1:]):
        ga, gb = g(a), g(b)
        if ga * gb < 0.0:
            found.append(_solve_between(const, terms, a, b, ga, gb))
    return found


def _turns(terms, t0, t1):
    """Where const + Σ c·e^(−r·t) turns, in (t0, t1). terms: [(rate, coef)], rates rising.
    g'(t)·e^(r0·t) = −r0·c0 + Σ_{m≥1} −r_m·c_m·e^(−(r_m − r0)·t): one term fewer."""
    if len(terms) < 2:
        return []
    r0, c0 = terms[0]
    return _roots(-r0 * c0, [-r * c for r, c in terms[1:]], [r - r0 for r, _c in terms[1:]], t0, t1)


def _solve_between(const, terms, a, b, ga, gb):
    """The zero of a monotone const + Σ c·e^(−r·t) on [a, b] with ga, gb of opposite signs:
    false position with the Illinois step, to 0.1 ms."""
    side = 0
    while b - a > _TOL_S:
        t = b - gb * (b - a) / (gb - ga)
        if not a < t < b:
            t = 0.5 * (a + b)
        gt = _value(const, terms, t)
        if gt == 0.0:
            return t
        if (gt > 0.0) == (ga > 0.0):
            a, ga = t, gt
            if side == -1:
                gb *= 0.5
            side = -1
        else:
            b, gb = t, gt
            if side == 1:
                ga *= 0.5
            side = 1
        if abs(gt) < 1e-9:
            return t
    return 0.5 * (a + b)
