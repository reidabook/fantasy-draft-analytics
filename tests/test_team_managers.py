import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.fetcher import espn_get_team_managers


class FakeTeam:
    def __init__(self, team_name, owners):
        self.team_name = team_name
        self.owners = owners


class FakeLeague:
    def __init__(self, teams):
        self.teams = teams


def owner(first_name, last_name):
    return {"firstName": first_name, "lastName": last_name}


class TestEspnGetTeamManagers(unittest.TestCase):
    def test_uses_owner_first_name(self):
        league = FakeLeague([FakeTeam("L.A. Kimballs", [owner("Greg", "Spear")])])
        self.assertEqual(espn_get_team_managers(league), {"L.A. Kimballs": "Greg"})

    def test_costa_override(self):
        league = FakeLeague([FakeTeam("Daejon Love Bomb", [owner("Alex", "Costa")])])
        self.assertEqual(espn_get_team_managers(league), {"Daejon Love Bomb": "Costa"})

    def test_medvene_override(self):
        league = FakeLeague([FakeTeam("The Hebrew Hammer", [owner("Matt", "Medvene")])])
        self.assertEqual(espn_get_team_managers(league), {"The Hebrew Hammer": "Medvene"})

    def test_carwell_override_is_tex(self):
        league = FakeLeague([FakeTeam("Nice Pitts", [owner("Tyler", "Carwell")])])
        self.assertEqual(espn_get_team_managers(league), {"Nice Pitts": "Tex"})

    def test_overrides_are_case_insensitive(self):
        league = FakeLeague([FakeTeam("Nice Pitts", [owner("tyler", "carwell")])])
        self.assertEqual(espn_get_team_managers(league), {"Nice Pitts": "Tex"})

    def test_lowercase_first_name_is_capitalized(self):
        league = FakeLeague([FakeTeam("Romo is my designated driver", [owner("paul", "hickman")])])
        self.assertEqual(
            espn_get_team_managers(league), {"Romo is my designated driver": "Paul"}
        )

    def test_uses_first_listed_owner_on_co_owned_team(self):
        league = FakeLeague([
            FakeTeam("The Flutes", [owner("Daniel", "Gardiner"), owner("Someone", "Else")])
        ])
        self.assertEqual(espn_get_team_managers(league), {"The Flutes": "Daniel"})

    def test_falls_back_to_team_name_when_no_owners(self):
        league = FakeLeague([FakeTeam("FAKE TEAM", [])])
        self.assertEqual(espn_get_team_managers(league), {"FAKE TEAM": "FAKE TEAM"})

    def test_falls_back_to_team_name_when_owners_missing_attr(self):
        team = FakeTeam("FAKE TEAM", [])
        del team.owners
        league = FakeLeague([team])
        self.assertEqual(espn_get_team_managers(league), {"FAKE TEAM": "FAKE TEAM"})

    def test_multiple_teams_resolved_independently(self):
        league = FakeLeague([
            FakeTeam("The Hebrew Hammer", [owner("Matt", "Medvene")]),
            FakeTeam("Nice Pitts", [owner("Tyler", "Carwell")]),
            FakeTeam("L.A. Kimballs", [owner("Greg", "Spear")]),
        ])
        self.assertEqual(
            espn_get_team_managers(league),
            {
                "The Hebrew Hammer": "Medvene",
                "Nice Pitts": "Tex",
                "L.A. Kimballs": "Greg",
            },
        )

    def test_team_name_change_does_not_affect_manager_label(self):
        # Same owner, renamed team — label follows the owner, not the name.
        league_week1 = FakeLeague([FakeTeam("Old Name", [owner("Greg", "Spear")])])
        league_week2 = FakeLeague([FakeTeam("New Name", [owner("Greg", "Spear")])])
        self.assertEqual(espn_get_team_managers(league_week1), {"Old Name": "Greg"})
        self.assertEqual(espn_get_team_managers(league_week2), {"New Name": "Greg"})


if __name__ == "__main__":
    unittest.main()
