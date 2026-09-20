import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.weekly.imessage import build_group_text

FAKE = "Fake team"

MANAGERS = {
    "The Hebrew Hammer": "Medvene",
    "Nice Pitts": "Tex",
    "L.A. Kimballs": "Greg",
}


class TestBuildGroupTextManagerLabels(unittest.TestCase):
    def test_high_scorer_shown_as_manager_label(self):
        text = build_group_text(
            week=1,
            median=100.0,
            fake_team_name=FAKE,
            override_ok=True,
            high_scorer="The Hebrew Hammer",
            high_score=150.0,
            scores={"The Hebrew Hammer": 150.0, "Nice Pitts": 90.0, FAKE: 80.0},
            team_to_manager=MANAGERS,
        )
        self.assertIn("Medvene", text)
        self.assertNotIn("The Hebrew Hammer", text)

    def test_fake_opponent_shown_as_manager_label(self):
        text = build_group_text(
            week=1,
            median=100.0,
            fake_team_name=FAKE,
            override_ok=True,
            high_scorer="L.A. Kimballs",
            high_score=150.0,
            scores={"L.A. Kimballs": 150.0, "Nice Pitts": 90.0, FAKE: 80.0},
            fake_opponent="Nice Pitts",
            fake_opponent_score=90.0,
            team_to_manager=MANAGERS,
        )
        self.assertIn("Tex", text)
        self.assertNotIn("Nice Pitts", text)

    def test_fake_team_name_is_never_relabeled(self):
        # Even if the map happened to contain an entry for the fake team's
        # name, only real teams get swapped for a manager label. Use a
        # distinctive sentinel that can't collide with template wording.
        text = build_group_text(
            week=1,
            median=100.0,
            fake_team_name=FAKE,
            override_ok=True,
            high_scorer="L.A. Kimballs",
            high_score=100.0,
            scores={"L.A. Kimballs": 100.0, "Nice Pitts": 90.0, FAKE: 80.0},
            fake_opponent="Nice Pitts",
            fake_opponent_score=90.0,
            team_to_manager={**MANAGERS, FAKE: "ZZZ_SENTINEL"},
        )
        self.assertIn(FAKE, text)
        self.assertNotIn("ZZZ_SENTINEL", text)

    def test_same_team_branch_uses_manager_label(self):
        # High scorer and Fake team's opponent are the same team -> the
        # combined-paragraph branch should also relabel.
        text = build_group_text(
            week=1,
            median=100.0,
            fake_team_name=FAKE,
            override_ok=True,
            high_scorer="The Hebrew Hammer",
            high_score=150.0,
            scores={"The Hebrew Hammer": 150.0, FAKE: 80.0},
            fake_opponent="The Hebrew Hammer",
            fake_opponent_score=150.0,
            team_to_manager=MANAGERS,
        )
        self.assertIn("Medvene", text)
        self.assertNotIn("The Hebrew Hammer", text)

    def test_unmapped_team_falls_back_to_team_name(self):
        text = build_group_text(
            week=1,
            median=100.0,
            fake_team_name=FAKE,
            override_ok=True,
            high_scorer="Some Unmapped Team",
            high_score=150.0,
            scores={"Some Unmapped Team": 150.0, FAKE: 80.0},
            team_to_manager=MANAGERS,
        )
        self.assertIn("Some Unmapped Team", text)

    def test_omitting_team_to_manager_keeps_team_names(self):
        # Backward compatibility: no map passed -> team names unchanged.
        text = build_group_text(
            week=1,
            median=100.0,
            fake_team_name=FAKE,
            override_ok=True,
            high_scorer="The Hebrew Hammer",
            high_score=150.0,
            scores={"The Hebrew Hammer": 150.0, FAKE: 80.0},
        )
        self.assertIn("The Hebrew Hammer", text)


if __name__ == "__main__":
    unittest.main()
