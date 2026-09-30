import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.site.render import render_site
from src.site.writer import templated_copy
from tests.test_site_awards import _data


def _issue(next_week):
    data = _data()
    data.update(league_name="L", season=2026, generated_at="2026-09-29T21:00", next_week=next_week,
                reg_season_weeks=14, playoff_teams=2)
    return data


class TestRenderArchive(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())

    def test_issues_numbered_by_preview_week_and_snapshotted(self):
        render_site(_issue(2), templated_copy(_issue(2)), self.out)
        snap = json.loads((self.out / "weeks" / "week2.json").read_text())
        self.assertEqual(snap["data"]["next_week"], 2)
        self.assertIn("preview_headline", snap["copy"])
        self.assertTrue((self.out / "weeks" / "week2.html").exists())

    def test_old_issues_rerendered_with_full_archive_and_legacy_html_dropped(self):
        (self.out / "weeks").mkdir(parents=True)
        (self.out / "weeks" / "week1.html").write_text("legacy, no snapshot")
        render_site(_issue(2), templated_copy(_issue(2)), self.out)
        render_site(_issue(3), templated_copy(_issue(3)), self.out)

        self.assertFalse((self.out / "weeks" / "week1.html").exists())
        old = (self.out / "weeks" / "week2.html").read_text()
        self.assertIn("weeks/week3.html", old)  # old issue links forward to the newer one
        self.assertIn("Archived issue", old)
        self.assertNotIn("Archived issue", (self.out / "index.html").read_text())
        self.assertIn("<h1>Week 3</h1>", (self.out / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
