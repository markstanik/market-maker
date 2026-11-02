from __future__ import annotations

import logging
import time

from . import devig
from .config import Config
from .kalshi import Kalshi
from .models import Market
from .odds import OddsApi
from .polymarket import Polymarket
from .store import Store
from .teams import TeamMatcher

log = logging.getLogger(__name__)
TRADE_LOOKBACK_S = 3 * 86400  # how far back to backfill trades on first run


class Recorder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.matcher = TeamMatcher(cfg.league, cfg.team_aliases)
        self.store = Store(cfg.db_path)
        self.kalshi = Kalshi(self.matcher)
        self.poly = Polymarket(self.matcher)
        self.odds = OddsApi(cfg.odds_api_key, self.matcher) if cfg.odds_api_key else None
        if not self.odds:
            log.warning("ODDS_API_KEY not set: recording order books and trades only, no fair value")
        self.k_markets: list[Market] = []
        self.p_markets: list[Market] = []

    # -- individual jobs -------------------------------------------------------------
    def refresh_markets(self):
        now = time.time()
        for venue, fetch in (("kalshi", lambda: self.kalshi.markets(self.cfg.kalshi_series)),
                             ("polymarket", lambda: self.poly.markets(self.cfg.polymarket_event_slug))):
            try:
                ms = fetch()
            except Exception:
                log.exception("market refresh failed for %s", venue)
                continue
            self.store.upsert_markets(ms, now)
            unmatched = [m.raw_name for m in ms if m.team is None]
            if unmatched:
                log.warning("%s: %d markets with no team match (add [team_aliases]): %s",
                            venue, len(unmatched), unmatched)
            ms = [m for m in ms if m.team]
            if venue == "kalshi":
                self.k_markets = ms
            else:
                self.p_markets = ms
            log.info("%s: tracking %d markets", venue, len(ms))

    def snapshot_books(self):
        cycle_ts = time.time()
        books = []
        for m in self.k_markets:
            try:
                books.append(self.kalshi.book(m, self.cfg.book_depth))
            except Exception as e:
                log.warning("kalshi book %s failed: %s", m.market_id, e)
        try:
            books += self.poly.books(self.p_markets)
        except Exception as e:
            log.warning("polymarket books failed: %s", e)
        for b in books:
            b.ts = cycle_ts  # one timestamp per cycle so venues can be compared row by row
            for lvls in (b.bids, b.asks):
                del lvls[self.cfg.book_depth:]
        self.store.add_books(books)
        log.info("books: stored %d snapshots", len(books))

    def poll_trades(self):
        floor = time.time() - TRADE_LOOKBACK_S
        n = 0
        for m in self.k_markets:
            since = self.store.last_trade_ts("kalshi", m.market_id) or floor
            try:
                n += self.store.add_trades(self.kalshi.trades(m, since))
            except Exception as e:
                log.warning("kalshi trades %s failed: %s", m.market_id, e)
        since_p = min((self.store.last_trade_ts("polymarket", m.market_id) or floor)
                      for m in self.p_markets) if self.p_markets else floor
        try:
            n += self.store.add_trades(self.poly.trades(self.p_markets, since_p))
        except Exception as e:
            log.warning("polymarket trades failed: %s", e)
        log.info("trades: %d new", n)

    def poll_odds(self):
        if not self.odds:
            return
        try:
            books, unmatched = self.odds.outrights(self.cfg.odds_sport_key, self.cfg.odds_regions)
        except Exception:
            log.exception("odds fetch failed")
            return
        if unmatched:
            log.warning("odds: unmatched names %s", unmatched)
        now = time.time()
        self.store.add_odds(now, books)
        for method in devig.METHODS:
            per_book = {bm: devig.devig(o, method) for bm, o in books.items() if len(o) >= 4}
            probs, counts = devig.blend(per_book, self.cfg.book_weights, self.cfg.default_book_weight)
            self.store.add_fair(now, method, probs, counts)
        log.info("odds: %d bookmakers, %d teams (quota remaining: %s)",
                 len(books), len({t for o in books.values() for t in o}), self.odds.remaining)

    # -- scheduling ------------------------------------------------------------------
    def run_once(self):
        self.refresh_markets()
        self.poll_odds()
        self.snapshot_books()
        self.poll_trades()

    def run_forever(self):
        jobs = [
            (self.cfg.market_refresh_s, self.refresh_markets),
            (self.cfg.odds_interval_s, self.poll_odds),
            (self.cfg.book_interval_s, self.snapshot_books),
            (self.cfg.trade_interval_s, self.poll_trades),
        ]
        due = [0.0] * len(jobs)
        while True:
            for i, (every, job) in enumerate(jobs):
                if time.time() >= due[i]:
                    due[i] = time.time() + every
                    try:
                        job()
                    except Exception:
                        log.exception("%s crashed; continuing", job.__name__)
            time.sleep(max(0.5, min(due) - time.time()))
