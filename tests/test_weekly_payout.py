import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.weekly.payout import (
    compute_median, find_high_scorer, find_high_scorers, parse_venmo_handles, payout_line,
    real_team_scores, venmo_pay_link,
)

FAKE = "Fake team"


class TestRealTeamScores(unittest.TestCase):
    def test_excludes_fake_team(self):
        scores = {"A": 100.0, "B": 90.0, FAKE: 80.0}
        self.assertEqual(real_team_scores(scores, FAKE), {"A": 100.0, "B": 90.0})

    def test_missing_fake_team_raises(self):
        with self.assertRaises(ValueError):
            real_team_scores({"A": 100.0}, FAKE)


class TestComputeMedian(unittest.TestCase):
    def test_odd_number_of_real_teams(self):
        scores = {"A": 100.0, "B": 90.0, "C": 80.0, FAKE: 999.0}
        self.assertEqual(compute_median(scores, FAKE), 90.0)

    def test_even_number_of_real_teams_raises(self):
        scores = {"A": 100.0, "B": 90.0, "C": 80.0, "D": 70.0, FAKE: 999.0}
        with self.assertRaises(ValueError):
            compute_median(scores, FAKE)


class TestFindHighScorer(unittest.TestCase):
    def test_finds_max_excluding_fake_team(self):
        scores = {"A": 100.0, "B": 130.0, "C": 80.0, FAKE: 999.0}
        self.assertEqual(find_high_scorer(scores, FAKE), ("B", 130.0))



class TestFindHighScorers(unittest.TestCase):
    def test_single_winner(self):
        scores = {"A": 100.0, "B": 130.0, FAKE: 999.0}
        self.assertEqual(find_high_scorers(scores, FAKE), (["B"], 130.0))

    def test_tie_returns_all(self):
        scores = {"B": 130.0, "A": 130.0, "C": 80.0, FAKE: 999.0}
        self.assertEqual(find_high_scorers(scores, FAKE), (["A", "B"], 130.0))


class TestVenmoPayLink(unittest.TestCase):
    def test_strips_at_and_encodes_note(self):
        self.assertEqual(
            venmo_pay_link("@Tyler-Carwell", 5, "Week 3 high score"),
            "https://venmo.com/?txn=pay&audience=private&recipients=Tyler-Carwell"
            "&amount=5.00&note=Week+3+high+score",
        )


class TestParseVenmoHandles(unittest.TestCase):
    def test_parses_pairs(self):
        self.assertEqual(
            parse_venmo_handles("Tex:@Tyler-Carwell, Medvene : Matt-Medvene,,bad"),
            {"tex": "Tyler-Carwell", "medvene": "Matt-Medvene"},
        )

    def test_unset(self):
        self.assertEqual(parse_venmo_handles(None), {})


class TestPayoutLine(unittest.TestCase):
    MANAGERS = {"Nice Pitts": "Tex", "The Flutes": "Daniel"}
    HANDLES = {"tex": "Tyler-Carwell"}

    def _line(self, week=3, winners=("Nice Pitts",)):
        return payout_line(week, 14, list(winners), 130.0, self.MANAGERS, self.HANDLES, 5)

    def test_link_for_known_handle(self):
        line = self._line()
        self.assertIn("Tex with 130.00", line)
        self.assertIn("pay $5 to @Tyler-Carwell", line)
        self.assertIn("recipients=Tyler-Carwell&amount=5.00&note=Week+3+high+score", line)

    def test_last_regular_season_week_still_pays(self):
        self.assertIn("venmo.com", self._line(week=14))

    def test_none_in_playoffs(self):
        self.assertIsNone(self._line(week=15))

    def test_tie_has_no_link(self):
        line = self._line(winners=("Nice Pitts", "The Flutes"))
        self.assertIn("TIE at 130.00 between Tex, Daniel", line)
        self.assertNotIn("venmo.com", line)

    def test_missing_handle_has_no_link(self):
        line = self._line(winners=("The Flutes",))
        self.assertIn("no handle configured for Daniel", line)
        self.assertNotIn("venmo.com", line)


if __name__ == "__main__":
    unittest.main()
