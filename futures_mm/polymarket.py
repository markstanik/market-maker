"""Polymarket public market data (no key needed).

Gamma API (market metadata): https://gamma-api.polymarket.com
CLOB API (order books):      https://clob.polymarket.com
Data API (trades):           https://data-api.polymarket.com

Note: this reads the international Polymarket order books. US residents trade
on Polymarket US, which has separate liquidity; treat these prices as a
reference until a Polymarket US client is added.
"""
from __future__ import annotations

import json
import time

from .http import Http
from .models import Book, Market, Trade
from .teams import TeamMatcher

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"


def _jsonish(v):
    return json.loads(v) if isinstance(v, str) else (v or [])


def parse_event_markets(event: dict, matcher: TeamMatcher) -> list[Market]:
    out = []
    for m in event.get("markets", []):
        if m.get("closed") or not m.get("active", True):
            continue
        tokens = _jsonish(m.get("clobTokenIds"))
        outcomes = _jsonish(m.get("outcomes")) or ["Yes", "No"]
        if not tokens:
            continue
        yes_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), 0)
        name = m.get("groupItemTitle") or m.get("question", "")
        team = matcher.match(m.get("groupItemTitle"), m.get("question"))
        out.append(Market("polymarket", tokens[yes_idx], team, m.get("question", ""), name,
                          {"condition_id": m.get("conditionId"),
                           "volume_24h": m.get("volume24hr"),
                           "slug": m.get("slug")}))
    return out


def parse_book(b: dict, team: str | None, ts: float) -> Book:
    bids = sorted(((float(l["price"]), float(l["size"])) for l in b.get("bids", [])),
                  key=lambda l: -l[0])
    asks = sorted(((float(l["price"]), float(l["size"])) for l in b.get("asks", [])),
                  key=lambda l: l[0])
    return Book("polymarket", b.get("asset_id", ""), team, ts, bids, asks)


def parse_trade(t: dict, token_to_team: dict[str, str | None]) -> Trade | None:
    """Data-API trades carry the token traded. Express everything as a YES price."""
    asset = str(t.get("asset", ""))
    price, side = float(t["price"]), str(t.get("side", "")).lower()
    if asset in token_to_team:
        market_id = asset
    else:
        return None  # NO-token trades are handled by the caller via the yes/no token map
    tid = t.get("transactionHash", "") + ":" + asset + ":" + str(t.get("timestamp")) + ":" + str(t.get("size"))
    return Trade("polymarket", tid, float(t["timestamp"]), market_id, token_to_team[asset],
                 price, float(t["size"]), side)


class Polymarket:
    def __init__(self, matcher: TeamMatcher):
        self.gamma = Http(GAMMA, min_gap_s=0.1)
        self.clob = Http(CLOB, min_gap_s=0.1)
        self.data = Http(DATA, min_gap_s=0.2)
        self.matcher = matcher
        self.no_token: dict[str, str] = {}  # NO token -> YES token

    def markets(self, event_slug: str) -> list[Market]:
        events = self.gamma.get("/events", slug=event_slug)
        if not events:
            raise RuntimeError(f"Polymarket event {event_slug!r} not found; run `discover`")
        ms = parse_event_markets(events[0], self.matcher)
        for raw in events[0].get("markets", []):
            toks = _jsonish(raw.get("clobTokenIds"))
            if len(toks) == 2:
                self.no_token[toks[1]] = toks[0]
        return ms

    def books(self, markets: list[Market]) -> list[Book]:
        by_id = {m.market_id: m for m in markets}
        now = time.time()
        out = []
        ids = list(by_id)
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            data = self.clob.post("/books", json=[{"token_id": t} for t in chunk])
            for b in data:
                m = by_id.get(str(b.get("asset_id")))
                if m:
                    out.append(parse_book(b, m.team, now))
        return out

    def trades(self, markets: list[Market], since_ts: float | None) -> list[Trade]:
        token_team = {m.market_id: m.team for m in markets}
        out = []
        for m in markets:
            cid = m.extra.get("condition_id")
            if not cid:
                continue
            for offset in range(0, 3000, 500):
                rows = self.data.get("/trades", market=cid, limit=500, offset=offset)
                if not rows:
                    break
                for t in rows:
                    asset = str(t.get("asset", ""))
                    if asset in self.no_token:  # NO token trade -> mirror into YES terms
                        t = {**t, "asset": self.no_token[asset], "price": 1 - float(t["price"]),
                             "side": {"buy": "sell", "sell": "buy"}.get(str(t.get("side", "")).lower())}
                    tr = parse_trade(t, token_team)
                    if tr:
                        out.append(tr)
                if since_ts and float(rows[-1]["timestamp"]) < since_ts:
                    break
        return [t for t in out if not since_ts or t.ts >= since_ts]

    def search_events(self, query: str) -> list[dict]:
        data = self.gamma.get("/public-search", q=query, events_status="active")
        return data.get("events", []) if isinstance(data, dict) else []
