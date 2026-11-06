from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.urls import reverse

from matches.models import MatchStatus
from matches.tests import MatchTestBase
from web.queries import fetch_all


class ExternalScoreTests(MatchTestBase):
    def test_view_uses_imported_series_score_when_no_maps(self):
        match = self.new_match()
        match.status = MatchStatus.FINISHED
        match.score_team1, match.score_team2 = 2, 0
        match.save()
        row = fetch_all("SELECT * FROM v_match_series_score WHERE match_id = %s", [match.pk])[0]
        self.assertEqual((row["maps_team1"], row["maps_team2"]), (2, 0))
        self.assertEqual(row["winner_entry_id"], self.entry_a.pk)

    def test_standings_count_imported_results(self):
        match = self.new_match()
        match.status, match.score_team1, match.score_team2 = MatchStatus.FINISHED, 0, 2
        match.save()
        rows = {r["tag"]: r for r in fetch_all("SELECT * FROM v_tournament_standings WHERE tournament_id = %s", [self.tournament.pk])}
        self.assertEqual((rows["BBB"]["wins"], rows["AAA"]["losses"]), (1, 1))

    def test_unfinished_match_has_no_winner(self):
        match = self.new_match()
        match.score_team1, match.score_team2 = 1, 0
        match.save()
        row = fetch_all("SELECT * FROM v_match_series_score WHERE match_id = %s", [match.pk])[0]
        self.assertIsNone(row["winner_entry_id"])

    def test_finished_match_shows_score_on_site(self):
        match = self.new_match()
        match.status, match.score_team1, match.score_team2 = MatchStatus.FINISHED, 2, 1
        match.save()
        response = self.client.get(reverse("web:results"))
        self.assertContains(response, '<b class="pos">2</b> – <b class="neg">1</b>', html=False)


class SyncMatchesTests(MatchTestBase):
    @patch.dict("os.environ", {"PANDASCORE_TOKEN": "t"})
    def test_updates_status_and_score_of_known_match(self):
        match = self.new_match()
        match.external_id = 777
        match.save()
        api = {"id": 777, "status": "finished", "scheduled_at": "2026-03-02T15:00:00Z",
               "opponents": [{"opponent": {"id": 1, "name": "Alpha"}}, {"opponent": {"id": 2, "name": "Beta"}}],
               "results": [{"team_id": 1, "score": 2}, {"team_id": 2, "score": 1}]}
        replies = iter([[], [], [api]])
        with patch("core.management.commands.sync_matches.get_json", side_effect=lambda *a, **k: next(replies)):
            call_command("sync_matches", stdout=StringIO())
        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.FINISHED)
        self.assertEqual((match.score_team1, match.score_team2), (2, 1))

    @patch.dict("os.environ", {"PANDASCORE_TOKEN": "t"})
    def test_unknown_match_is_ignored(self):
        with patch("core.management.commands.sync_matches.get_json", return_value=[{"id": 5, "status": "running"}]):
            call_command("sync_matches", stdout=StringIO())


class StaleMatchTests(MatchTestBase):
    @patch.dict("os.environ", {"PANDASCORE_TOKEN": "t"})
    def test_stale_live_match_is_refreshed_by_id(self):
        match = self.new_match()
        match.external_id, match.status = 888, MatchStatus.LIVE
        match.save()
        api = {"id": 888, "status": "finished", "scheduled_at": "2026-03-02T15:00:00Z",
               "opponents": [{"opponent": {"id": 1, "name": "Alpha"}}, {"opponent": {"id": 2, "name": "Beta"}}],
               "results": [{"team_id": 1, "score": 2}, {"team_id": 2, "score": 0}]}
        replies = iter([[], [], [], [api]])  # running, upcoming, past, затем запрос зависших по id
        with patch("core.management.commands.sync_matches.get_json", side_effect=lambda *a, **k: next(replies)):
            call_command("sync_matches", stdout=StringIO())
        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.FINISHED)

    @patch.dict("os.environ", {"PANDASCORE_TOKEN": "t"})
    def test_unreported_old_match_is_closed(self):
        match = self.new_match()
        match.external_id, match.status = 999, MatchStatus.LIVE
        match.save()
        with patch("core.management.commands.sync_matches.get_json", return_value=[]):
            call_command("sync_matches", stdout=StringIO())
        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.CANCELLED)
