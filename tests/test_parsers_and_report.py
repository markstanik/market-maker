"""Parsers are tested against payloads shaped like the documented API responses.
They have not been checked against live responses from this environment."""
import tempfile
import time
import unittest
from pathlib import Path

from futures_mm import devig, kalshi, odds, polymarket, report
from futures_mm.models import Book, Trade
from futures_mm.store import Store
from futures_mm.teams import TeamMatcher

M = TeamMatcher("nba")


class ParserTests(unittest.TestCase):
    def test_kalshi_orderbook_cents(self):
        b = kalshi.parse_orderbook({"orderbook": {"yes": [[20, 100], [22, 50]], "no": [[75, 10], [74, 30]]}},
                                   "KXNBA-27-OKC", "Oklahoma City Thunder", 0)
        self.assertEqual(b.bids[0], (0.22, 50))
        self.assertEqual(b.asks[0], (0.25, 10))
        self.assertAlmostEqual(b.mid, 0.235)

    def test_kalshi_orderbook_dollars(self):
        b = kalshi.parse_orderbook({"orderbook_fp": {"yes_dollars": [["0.2200", "50.00"]],
                                                     "no_dollars": [["0.7500", "10.00"]]}}, "X", None, 0)
        self.assertEqual((b.best_bid, b.best_ask), (0.22, 0.25))

    def test_kalshi_empty_book(self):
        b = kalshi.parse_orderbook({"orderbook": {"yes": None, "no": None}}, "X", None, 0)
        self.assertIsNone(b.mid)

    def test_kalshi_trade(self):
        t = kalshi.parse_trade({"trade_id": "t1", "ticker": "X", "count": 5, "yes_price": 23,
                                "taker_side": "yes", "created_time": "2026-11-01T12:00:00Z"}, "Boston Celtics")
        self.assertEqual((t.price, t.size, t.team), (0.23, 5.0, "Boston Celtics"))

    def test_polymarket_event_and_book(self):
        ev = {"markets": [
            {"question": "Will the Oklahoma City Thunder win the 2027 NBA Finals?",
             "groupItemTitle": "Thunder", "clobTokenIds": '["111", "222"]', "outcomes": '["Yes", "No"]',
             "conditionId": "0xabc", "active": True, "closed": False},
            {"question": "Closed one", "groupItemTitle": "Heat", "clobTokenIds": '["3","4"]', "closed": True}]}
        ms = polymarket.parse_event_markets(ev, M)
        self.assertEqual(len(ms), 1)
        self.assertEqual((ms[0].market_id, ms[0].team), ("111", "Oklahoma City Thunder"))
        b = polymarket.parse_book({"asset_id": "111", "bids": [{"price": "0.20", "size": "10"},
                                                               {"price": "0.21", "size": "5"}],
                                   "asks": [{"price": "0.25", "size": "7"}, {"price": "0.23", "size": "9"}]},
                                  ms[0].team, 0)
        self.assertEqual((b.best_bid, b.best_ask), (0.21, 0.23))

    def test_odds_parse(self):
        books, unmatched = odds.parse_outrights([{"bookmakers": [{"key": "pinnacle", "markets": [
            {"key": "outrights", "outcomes": [{"name": "Boston Celtics", "price": 6.0},
                                              {"name": "Mystery Team", "price": 900}]}]}]}], M)
        self.assertEqual(books, {"pinnacle": {"Boston Celtics": 6.0}})
        self.assertEqual(unmatched, ["Mystery Team"])


class ReportTests(unittest.TestCase):
    def test_end_to_end_report(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "t.sqlite")
            s = Store(db)
            now = time.time()
            book_odds = {"pinnacle": {"Oklahoma City Thunder": 4.0, "Boston Celtics": 6.0,
                                      "Denver Nuggets": 8.0, "Miami Heat": 1.6}}
            s.add_odds(now - 600, book_odds)
            p = devig.devig(book_odds["pinnacle"], "shin")
            s.add_fair(now - 600, "shin", p, {t: 1 for t in p})
            okc = "Oklahoma City Thunder"
            s.add_books([Book("kalshi", "K", okc, now - 60, [(0.24, 100)], [(0.26, 80)]),
                         Book("polymarket", "P", okc, now - 60, [(0.27, 50)], [(0.28, 40)])])
            s.add_trades([Trade("kalshi", "1", now - 30, "K", okc, 0.25, 100, "yes")])
            rep = report.build(db, hours=24, method="shin", kalshi_fee=0.07)
            row = next(r for r in rep["rows"] if r["team"] == okc)
            self.assertAlmostEqual(row["kalshi_avg_spread"], 0.02)
            self.assertEqual(row["kalshi_trades"], 1)
            self.assertEqual(len(rep["crosses"]), 1)
            c = rep["crosses"][0]
            self.assertEqual((c["buy"], c["sell"]), ("kalshi", "polymarket"))
            self.assertAlmostEqual(c["gross"], 0.01)
            self.assertLess(c["net"], c["gross"])
            md, csv_path = report.write(rep, "nba", d)
            self.assertIn("Oklahoma City Thunder", md.read_text())
            self.assertTrue(csv_path.exists())


if __name__ == "__main__":
    unittest.main()
