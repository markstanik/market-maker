"""Remove the bookmaker margin ("vig") from a set of outright odds.

Input is a dict of {outcome: decimal_odds}. Output is {outcome: probability}
summing to 1.0. Futures books carry large overrounds (often 110-130%), and the
margin is loaded disproportionately onto longshots, which is why the power and
Shin methods are preferred over simple proportional scaling.
"""
from __future__ import annotations

import math

METHODS = ("multiplicative", "power", "shin")


def implied(odds: dict[str, float]) -> dict[str, float]:
    return {k: 1.0 / v for k, v in odds.items() if v and v > 1.0}


def multiplicative(q: dict[str, float]) -> dict[str, float]:
    s = sum(q.values())
    return {k: v / s for k, v in q.items()}


def _bisect(f, lo: float, hi: float, iters: int = 200) -> float:
    flo = f(lo)
    for _ in range(iters):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def power(q: dict[str, float]) -> dict[str, float]:
    """Find k so that sum(q_i ** k) == 1. k > 1 shrinks longshots more than favourites."""
    s = sum(q.values())
    if abs(s - 1.0) < 1e-12:
        return dict(q)
    lo, hi = (1.0, 50.0) if s > 1 else (0.01, 1.0)
    k = _bisect(lambda k: sum(v**k for v in q.values()) - 1.0, lo, hi)
    p = {name: v**k for name, v in q.items()}
    return multiplicative(p)  # clean up residual rounding


def shin(q: dict[str, float]) -> dict[str, float]:
    """Shin (1993) model: the margin is a defence against a fraction z of insider money."""
    s = sum(q.values())
    if s <= 1.0:
        return multiplicative(q)

    def probs(z: float) -> dict[str, float]:
        return {
            k: (math.sqrt(z * z + 4 * (1 - z) * v * v / s) - z) / (2 * (1 - z))
            for k, v in q.items()
        }

    z = _bisect(lambda z: sum(probs(z).values()) - 1.0, 0.0, 0.999)
    return multiplicative(probs(z))


def devig(odds: dict[str, float], method: str = "shin") -> dict[str, float]:
    q = implied(odds)
    if not q:
        return {}
    if method == "multiplicative":
        return multiplicative(q)
    if method == "power":
        return power(q)
    if method == "shin":
        return shin(q)
    raise ValueError(f"unknown method {method!r}; choose from {METHODS}")


def blend(
    per_book: dict[str, dict[str, float]],
    weights: dict[str, float],
    default_weight: float = 1.0,
) -> tuple[dict[str, float], dict[str, int]]:
    """Weighted average of each book's de-vigged probabilities, renormalised to sum to 1.

    Returns (probabilities, number_of_books_quoting_each_outcome).
    """
    num: dict[str, float] = {}
    den: dict[str, float] = {}
    count: dict[str, int] = {}
    for book, probs in per_book.items():
        w = weights.get(book, default_weight)
        if w <= 0:
            continue
        for team, p in probs.items():
            num[team] = num.get(team, 0.0) + w * p
            den[team] = den.get(team, 0.0) + w
            count[team] = count.get(team, 0) + 1
    raw = {t: num[t] / den[t] for t in num}
    total = sum(raw.values())
    if total <= 0:
        return {}, {}
    return {t: v / total for t, v in raw.items()}, count
