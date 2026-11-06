import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command

from matches.models import MatchStatus, PlayerMapStat
from matches.tests import MatchTestBase


class ImportMatchStatsTests(MatchTestBase):
    def write_csv(self, match, rounds=(13, 9)):
        path = Path(tempfile.mkdtemp()) / "s.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["match_id", "map_number", "map", "team1_rounds", "team2_rounds", "slot", "player",
                        "kills", "deaths", "assists", "hs", "damage", "rounds"])
            w.writerow([match.pk, 1, "mirage", rounds[0], rounds[1], 1, self.players_a[0].nickname, 20, 12, 3, 9, 1700, 22])
            w.writerow([match.pk, 1, "mirage", rounds[0], rounds[1], 2, self.players_b[0].nickname, 15, 18, 2, 5, 1300, 22])
        return str(path)

    def test_import_on_finished_match_keeps_status_and_is_repeatable(self):
        match = self.new_match()
        match.status = MatchStatus.FINISHED
        match.save()
        path = self.write_csv(match)
        out = StringIO()
        call_command("import_match_stats", path, stdout=out)
        self.assertEqual(PlayerMapStat.objects.filter(match_map__match=match).count(), 2)
        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.FINISHED)
        call_command("import_match_stats", path, stdout=out, stderr=StringIO())  # без --replace: ошибка, дублей нет
        self.assertEqual(PlayerMapStat.objects.filter(match_map__match=match).count(), 2)
        call_command("import_match_stats", path, "--replace", stdout=out)
        self.assertEqual(PlayerMapStat.objects.filter(match_map__match=match).count(), 2)

    def test_dry_run_saves_nothing(self):
        match = self.new_match()
        call_command("import_match_stats", self.write_csv(match), "--dry-run", stdout=StringIO())
        self.assertEqual(PlayerMapStat.objects.count(), 0)
