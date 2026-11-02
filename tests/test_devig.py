import unittest

from futures_mm import devig

# ~115% overround, like a real futures board
ODDS = {"A": 2.2, "B": 3.5, "C": 5.0, "D": 9.0, "E": 17.0, "F": 34.0, "G": 67.0}


class DevigTests(unittest.TestCase):
    def test_all_methods_sum_to_one(self):
        for m in devig.METHODS:
            p = devig.devig(ODDS, m)
            self.assertAlmostEqual(sum(p.values()), 1.0, places=9, msg=m)
            self.assertEqual(list(p), list(ODDS))

    def test_power_and_shin_shrink_longshots_more(self):
        mult, pw, sh = (devig.devig(ODDS, m) for m in devig.METHODS)
        for p in (pw, sh):
            self.assertGreater(p["A"], mult["A"])
            self.assertLess(p["G"], mult["G"])

    def test_fair_book_unchanged(self):
        fair = {"A": 2.0, "B": 4.0, "C": 4.0}
        for m in devig.METHODS:
            p = devig.devig(fair, m)
            self.assertAlmostEqual(p["A"], 0.5, places=6)

    def test_blend_weights_and_missing_teams(self):
        probs, counts = devig.blend({"sharp": {"A": 0.6, "B": 0.4}, "soft": {"A": 0.4, "B": 0.4, "C": 0.2}},
                                    {"sharp": 3.0})
        self.assertAlmostEqual(sum(probs.values()), 1.0)
        self.assertEqual(counts, {"A": 2, "B": 2, "C": 1})
        self.assertGreater(probs["A"], probs["B"])


if __name__ == "__main__":
    unittest.main()
