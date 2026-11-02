import unittest

from futures_mm.teams import NBA, NFL, TeamMatcher


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.nba, self.nfl = TeamMatcher("nba"), TeamMatcher("nfl")

    def test_counts(self):
        self.assertEqual((len(NBA), len(NFL)), (30, 32))

    def test_variants(self):
        cases = {"Oklahoma City": "Oklahoma City Thunder", "OKC": "Oklahoma City Thunder",
                 "Los Angeles L": "Los Angeles Lakers", "LA Clippers": "Los Angeles Clippers",
                 "Philadelphia 76ers": "Philadelphia 76ers", "Trail Blazers": "Portland Trail Blazers",
                 "Will the Boston Celtics win the 2027 NBA Finals?": "Boston Celtics",
                 "Golden St. Warriors": "Golden State Warriors"}
        for raw, want in cases.items():
            self.assertEqual(self.nba.match(raw), want, raw)

    def test_shared_city_is_ambiguous(self):
        self.assertIsNone(self.nba.match("Los Angeles"))
        self.assertIsNone(self.nfl.match("New York"))
        self.assertEqual(self.nfl.match("New York J"), "New York Jets")

    def test_fallback_order(self):
        self.assertEqual(self.nfl.match(None, "", "KC"), "Kansas City Chiefs")


if __name__ == "__main__":
    unittest.main()
