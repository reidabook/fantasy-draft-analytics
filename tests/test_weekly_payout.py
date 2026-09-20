import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.weekly.payout import compute_median, find_high_scorer, real_team_scores

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


if __name__ == "__main__":
    unittest.main()
