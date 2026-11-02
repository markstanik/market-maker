from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Book, Market, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    venue TEXT, market_id TEXT, team TEXT, title TEXT, raw_name TEXT, extra TEXT,
    updated REAL, PRIMARY KEY (venue, market_id));
CREATE TABLE IF NOT EXISTS books (
    ts REAL, venue TEXT, market_id TEXT, team TEXT,
    best_bid REAL, best_ask REAL, bid_size REAL, ask_size REAL, mid REAL, depth TEXT);
CREATE INDEX IF NOT EXISTS books_team_ts ON books (team, venue, ts);
CREATE TABLE IF NOT EXISTS trades (
    venue TEXT, trade_id TEXT, ts REAL, market_id TEXT, team TEXT,
    price REAL, size REAL, taker_side TEXT, PRIMARY KEY (venue, trade_id));
CREATE INDEX IF NOT EXISTS trades_team_ts ON trades (team, venue, ts);
CREATE TABLE IF NOT EXISTS odds (
    ts REAL, bookmaker TEXT, team TEXT, decimal_odds REAL);
CREATE TABLE IF NOT EXISTS fair (
    ts REAL, method TEXT, team TEXT, prob REAL, n_books INTEGER);
CREATE INDEX IF NOT EXISTS fair_ts ON fair (method, ts);
"""


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def upsert_markets(self, ms: list[Market], ts: float):
        self.db.executemany(
            "INSERT OR REPLACE INTO markets VALUES (?,?,?,?,?,?,?)",
            [(m.venue, m.market_id, m.team, m.title, m.raw_name, json.dumps(m.extra), ts) for m in ms])
        self.db.commit()

    def add_books(self, books: list[Book]):
        rows = []
        for b in books:
            rows.append((b.ts, b.venue, b.market_id, b.team, b.best_bid, b.best_ask,
                         b.bids[0][1] if b.bids else None, b.asks[0][1] if b.asks else None,
                         b.mid, json.dumps({"bids": b.bids, "asks": b.asks})))
        self.db.executemany("INSERT INTO books VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        self.db.commit()

    def add_trades(self, trades: list[Trade]) -> int:
        before = self.db.total_changes
        self.db.executemany(
            "INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?)",
            [(t.venue, t.trade_id, t.ts, t.market_id, t.team, t.price, t.size, t.taker_side)
             for t in trades])
        self.db.commit()
        return self.db.total_changes - before

    def last_trade_ts(self, venue: str, market_id: str) -> float | None:
        r = self.db.execute("SELECT MAX(ts) FROM trades WHERE venue=? AND market_id=?",
                            (venue, market_id)).fetchone()
        return r[0]

    def add_odds(self, ts: float, books: dict[str, dict[str, float]]):
        self.db.executemany("INSERT INTO odds VALUES (?,?,?,?)",
                            [(ts, bm, t, o) for bm, teams in books.items() for t, o in teams.items()])
        self.db.commit()

    def add_fair(self, ts: float, method: str, probs: dict[str, float], counts: dict[str, int]):
        self.db.executemany("INSERT INTO fair VALUES (?,?,?,?,?)",
                            [(ts, method, t, p, counts.get(t, 0)) for t, p in probs.items()])
        self.db.commit()
