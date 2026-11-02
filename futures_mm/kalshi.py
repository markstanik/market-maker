"""Kalshi public market data (no API key needed for reads).

Docs: https://docs.kalshi.com  Base: https://api.elections.kalshi.com/trade-api/v2
Kalshi has moved some fields from integer cents to "*_dollars" strings and
fixed-point counts ("*_fp"); the parsers below accept either form.
"""
from __future__ import annotations

import time
from datetime import datetime

from .http import Http
from .models import Book, Market, Trade
from .teams import TeamMatcher

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _price(obj: dict, key: str) -> float | None:
    if obj.get(f"{key}_dollars") not in (None, ""):
        return float(obj[f"{key}_dollars"])
    if obj.get(key) is not None:
        return float(obj[key]) / 100.0
    return None


def _count(obj: dict, key: str = "count") -> float:
    for k in (f"{key}_fp", key):
        if obj.get(k) not in (None, ""):
            return float(obj[k])
    return 0.0


def _ts(s: str | int | float | None) -> float:
    if s is None:
        return time.time()
    if isinstance(s, (int, float)):
        return float(s)
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def parse_orderbook(payload: dict, market_id: str, team: str | None, ts: float) -> Book:
    """Kalshi returns resting *bids* for YES and for NO. A NO bid at p is a YES ask at 1-p."""
    ob = payload.get("orderbook_fp") or payload.get("orderbook") or {}

    def side(name: str) -> list[tuple[float, float]]:
        if ob.get(f"{name}_dollars"):
            return [(float(p), float(q)) for p, q in ob[f"{name}_dollars"]]
        if ob.get(name):
            return [(float(p) / 100.0, float(q)) for p, q in ob[name]]
        return []

    yes_bids = sorted(side("yes"), key=lambda l: -l[0])
    yes_asks = sorted(((round(1 - p, 4), q) for p, q in side("no")), key=lambda l: l[0])
    return Book("kalshi", market_id, team, ts, yes_bids, yes_asks)


def parse_trade(t: dict, team: str | None) -> Trade:
    return Trade(
        venue="kalshi",
        trade_id=str(t["trade_id"]),
        ts=_ts(t.get("created_time")),
        market_id=t["ticker"],
        team=team,
        price=_price(t, "yes_price") or 0.0,
        size=_count(t),
        taker_side=t.get("taker_side"),
    )


class Kalshi:
    def __init__(self, matcher: TeamMatcher):
        self.http = Http(BASE, min_gap_s=0.1)
        self.matcher = matcher

    def markets(self, series_ticker: str) -> list[Market]:
        out, cursor = [], None
        while True:
            params = {"series_ticker": series_ticker, "status": "open", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            data = self.http.get("/markets", **params)
            for m in data.get("markets", []):
                suffix = m["ticker"].rsplit("-", 1)[-1]
                name = m.get("yes_sub_title") or m.get("subtitle") or suffix
                team = self.matcher.match(m.get("yes_sub_title"), m.get("subtitle"), suffix,
                                          m.get("title"))
                out.append(Market("kalshi", m["ticker"], team, m.get("title", ""), name,
                                  {"event_ticker": m.get("event_ticker"),
                                   "volume_24h": m.get("volume_24h_fp") or m.get("volume_24h"),
                                   "open_interest": m.get("open_interest_fp") or m.get("open_interest")}))
            cursor = data.get("cursor")
            if not cursor:
                return out

    def book(self, m: Market, depth: int) -> Book:
        data = self.http.get(f"/markets/{m.market_id}/orderbook", depth=depth)
        return parse_orderbook(data, m.market_id, m.team, time.time())

    def trades(self, m: Market, since_ts: float | None) -> list[Trade]:
        out, cursor = [], None
        for _ in range(20):  # cap pages per poll
            params = {"ticker": m.market_id, "limit": 1000}
            if since_ts:
                params["min_ts"] = int(since_ts)
            if cursor:
                params["cursor"] = cursor
            data = self.http.get("/markets/trades", **params)
            out += [parse_trade(t, m.team) for t in data.get("trades", [])]
            cursor = data.get("cursor")
            if not cursor:
                break
        return out

    def search_series(self, keyword: str) -> list[dict]:
        data = self.http.get("/series", category="Sports")
        kw = keyword.lower()
        return [s for s in data.get("series", []) or []
                if kw in (s.get("title", "") + " " + s.get("ticker", "")).lower()]
