import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.site.awards import (
    game_of_the_week, injured_starters, injury_spotlight, playoff_picture, playoff_talk_ok,
    season_table, week_median, weekly_awards,
)

FAKE = "99"


def _p(name, pos, pts):
    return {"name": name, "pos": pos, "slot": pos, "pts": pts}


def _side(tid, score, starters=(), bench=()):
    starters = sorted(starters, key=lambda p: p["pts"], reverse=True)
    return {"team_id": tid, "score": score, "projected": 0.0, "top_starter": starters[0] if starters else None,
            "starters": list(starters), "bench": list(bench), "bench_pts": sum(p["pts"] for p in bench)}


def _team(tid, standing, wins=0, losses=0, is_fake=False):
    return {"id": tid, "name": f"T{tid}", "abbrev": f"T{tid}", "logo": None, "manager": f"M{tid}", "wins": wins, "losses": losses,
            "pf": 0.0, "pa": 0.0, "standing": standing, "streak": "", "is_fake": is_fake}


def _data():
    # Week 1: team 1 (120) beats team 2 (80); team 3 (100.4) edges FAKE (100).
    # Real-team median is 100.4.
    return {
        "week": 1,
        "fake_team_id": FAKE,
        "teams": {
            "1": _team("1", 1, 1, 0), "2": _team("2", 3, 0, 1), "3": _team("3", 2, 1, 0),
            FAKE: _team(FAKE, 4, 0, 1, is_fake=True),
        },
        "weeks": {"1": [
            {"home": _side("1", 120.0, [_p("QB1", "QB", 30.0), _p("WR1", "WR", 2.0)], [_p("WR2", "WR", 20.0), _p("QB2", "QB", 25.0)]),
             "away": _side("2", 80.0, [_p("RB1", "RB", 40.0)])},
            {"home": _side("3", 100.4, [_p("TE1", "TE", 10.0)]),
             "away": _side(FAKE, 100.0, [_p("RBX", "RB", 99.0)])},
        ]},
        "upcoming": [],
    }


class TestSiteAwards(unittest.TestCase):
    def setUp(self):
        self.data = _data()
        self.awards = {a["key"]: a for a in weekly_awards(self.data, 1)}

    def test_median_excludes_fake(self):
        self.assertEqual(week_median(self.data, 1), 100.4)

    def test_top_and_bottom_are_real_teams(self):
        self.assertEqual(self.awards["top_dog"]["team_id"], "1")
        self.assertEqual(self.awards["basement"]["team_id"], "2")

    def test_fake_team_never_wins_an_award(self):
        self.assertTrue(all(a["team_id"] != FAKE for a in self.awards.values()))

    def test_blowout_and_nail_biter(self):
        self.assertEqual(self.awards["blowout"]["team_id"], "1")
        self.assertAlmostEqual(self.awards["nail_biter"]["value"], 0.4)
        self.assertEqual(self.awards["nail_biter"]["team_id"], "3")

    def test_mvp_ignores_fake_team_players(self):
        self.assertEqual(self.awards["mvp"]["team_id"], "2")  # RB1 40 beats fake's RBX 99

    def test_bench_blunder_same_position_only(self):
        # QB2 (25) outscores WR1 (2) but isn't a WR; WR2 (20) vs WR1 (2) is the blunder.
        b = self.awards["bench_blunder"]
        self.assertEqual(b["team_id"], "1")
        self.assertAlmostEqual(b["value"], 18.0)

    def test_season_table_all_play_and_median(self):
        rows = {r["id"]: r for r in season_table(self.data)}
        self.assertNotIn(FAKE, rows)
        self.assertEqual((rows["1"]["ap_w"], rows["1"]["ap_l"]), (2, 0))
        self.assertEqual((rows["2"]["ap_w"], rows["2"]["ap_l"]), (0, 2))
        self.assertEqual((rows["1"]["med_w"], rows["2"]["med_l"], rows["3"]["med_w"], rows["3"]["med_l"]), (1, 1, 0, 0))
        self.assertEqual(rows["1"]["power"], 1)
        self.assertEqual([r["id"] for r in season_table(self.data)], ["1", "3", "2"])

    def test_playoff_picture_tiers(self):
        self.data["playoff_teams"] = 1
        tiers = playoff_picture(self.data)
        self.assertEqual([r["id"] for r in tiers["in"]], ["1"])
        self.assertEqual([r["id"] for r in tiers["knocking"]], ["3", "2"])
        self.assertEqual(tiers["miracle"], [])

    def test_game_of_the_week_skips_the_median(self):
        self.data["upcoming"] = [
            {"home": _side("1", 0.0), "away": _side(FAKE, 0.0)},
            {"home": _side("2", 0.0), "away": _side("3", 0.0)},
        ]
        g = game_of_the_week(self.data)
        self.assertEqual({g["home"]["team_id"], g["away"]["team_id"]}, {"2", "3"})

    def test_injured_starters(self):
        side = _side("1", 0.0, [dict(_p("A", "QB", 0.0), injury="OUT"), dict(_p("B", "WR", 0.0), injury=None)])
        self.assertEqual([p["name"] for p in injured_starters(side)], ["A"])


    def test_no_playoff_talk_early_in_season(self):
        self.data.update(reg_season_weeks=14, next_week=4)
        self.assertFalse(playoff_talk_ok(self.data))
        self.data["next_week"] = 10
        self.assertTrue(playoff_talk_ok(self.data))

    def test_injury_spotlight_pinned_then_fallback(self):
        hurt = lambda n, proj: dict(_p(n, "RB", 0.0), proj=proj, injury="OUT")  # noqa: E731
        self.data["upcoming"] = [
            {"home": _side("1", 0.0, [hurt("A", 0.0)], [hurt("B", 5.0)]), "away": _side("2", 0.0)},
            {"home": _side("3", 0.0, [hurt("C", 9.0)]), "away": _side(FAKE, 0.0, [hurt("Z", 0.0)] * 3)},
        ]
        self.assertEqual(injury_spotlight(self.data)["team_id"], "1")  # most injured; fake ignored
        self.assertEqual(injury_spotlight(self.data, "M3")["team_id"], "3")  # pinned by manager
        self.assertEqual(injury_spotlight(self.data, "M2")["team_id"], "1")  # pinned team healthy -> fallback
        self.assertTrue(injury_spotlight(self.data)["players"][0]["dead_slot"])


if __name__ == "__main__":
    unittest.main()
