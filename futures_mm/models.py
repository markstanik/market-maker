from __future__ import annotations

from dataclasses import dataclass, field

Level = tuple[float, float]  # (price as probability 0-1, size in contracts)


@dataclass
class Market:
    venue: str           # "kalshi" | "polymarket"
    market_id: str       # Kalshi ticker, or Polymarket YES token id
    team: str | None     # canonical team name (None = unmatched)
    title: str
    raw_name: str
    extra: dict = field(default_factory=dict)


@dataclass
class Book:
    venue: str
    market_id: str
    team: str | None
    ts: float
    bids: list[Level]    # YES bids, best (highest) first
    asks: list[Level]    # YES asks, best (lowest) first

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2


@dataclass
class Trade:
    venue: str
    trade_id: str
    ts: float
    market_id: str
    team: str | None
    price: float         # YES price, 0-1
    size: float          # contracts
    taker_side: str | None  # "yes"/"no" (Kalshi) or "buy"/"sell" of YES (Polymarket)
