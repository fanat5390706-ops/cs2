import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from core.models import Team, TeamRanking
from web.views import latest_ranking


class ImportRankingTests(TestCase):
    def test_manual_ranking_has_priority(self):
        Team.objects.create(name="Spirit", tag="SPI")
        path = Path(tempfile.mkdtemp()) / "r.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["position", "team", "points"])
            w.writerow([1, "spirit", 1000])
            w.writerow([2, "Unknown Team", ""])
        call_command("import_ranking", str(path), "--date", "2026-11-02", stdout=StringIO())
        self.assertEqual(TeamRanking.objects.filter(source="manual").count(), 2)
        top = latest_ranking()
        self.assertEqual(top[0]["position"], 1)
        self.assertEqual(top[0]["team"], "Spirit")
        self.assertIsNotNone(top[0]["team_id"])
