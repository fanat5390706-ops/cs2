from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.urls import reverse

from matches.services import record_map
from matches.tests import MatchTestBase, stat


class ApiTests(MatchTestBase):
    def setUp(self):
        super().setUp()
        self.match = self.new_match()
        stats = [stat(p, 1) for p in self.players_a] + [stat(p, 2) for p in self.players_b]
        record_map(self.match, self.maps[0], 1, {1: 13, 2: 7}, stats)

    def get(self, name, *args, query=""):
        return self.client.get(reverse(f"api:{name}", args=args) + query)

    def test_index_and_lists_ok(self):
        for name in ("index", "teams", "players", "tournaments", "matches", "news", "videos", "streams"):
            with self.subTest(name=name):
                response = self.get(name)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_players_list_has_team_and_pagination(self):
        data = self.get("players", query="?limit=3").json()
        self.assertEqual(len(data["results"]), 3)
        self.assertEqual(data["limit"], 3)
        self.assertGreaterEqual(data["count"], 10)
        self.assertIsNotNone(data["results"][0]["team"])

    def test_bad_pagination_values_fall_back(self):
        data = self.get("players", query="?limit=abc&offset=-5").json()
        self.assertEqual((data["limit"], data["offset"]), (50, 0))
        self.assertEqual(self.get("players", query="?limit=100000").json()["limit"], 100)

    def test_player_detail_has_stats_and_rating(self):
        data = self.get("player_detail", self.players_a[0].pk).json()
        self.assertEqual(data["stats"]["maps_played"], 1)
        self.assertIn("rating", data["stats"])

    def test_match_detail_and_filters(self):
        data = self.get("match_detail", self.match.pk).json()
        self.assertEqual(data["team1"]["maps_won"], 1)
        listed = self.get("matches", query=f"?tournament={self.tournament.pk}").json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(self.get("matches", query="?status=finished").json()["count"], 0)

    def test_unknown_objects_return_404(self):
        for name in ("team_detail", "player_detail", "tournament_detail", "match_detail"):
            self.assertEqual(self.get(name, 999999).status_code, 404)

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(reverse("api:teams")).status_code, 405)


ALL_KEYS = {
    "PANDASCORE_TOKEN": "x", "TWITCH_CLIENT_ID": "x", "TWITCH_CLIENT_SECRET": "x", "NEWSAPI_KEY": "x",
    "YOUTUBE_API_KEY": "x", "STEAM_API_KEY": "x", "FACEIT_API_KEY": "x", "LIQUIPEDIA_CONTACT": "x",
}


class WorkersTests(MatchTestBase):
    def test_once_runs_all_jobs_and_survives_failures(self):
        calls = []

        def fake(name, *args, **kwargs):
            calls.append(name)
            if name == "sync_news":
                raise RuntimeError("no key")

        with patch.dict("os.environ", ALL_KEYS), \
             patch("core.management.commands.run_workers.call_command", side_effect=fake):
            call_command("run_workers", "--once", stdout=StringIO())
        self.assertIn("sync_twitch", calls)
        self.assertIn("sync_liquipedia", calls)  # после сбоя sync_news остальные выполнены

    def test_only_filter(self):
        calls = []
        with patch.dict("os.environ", ALL_KEYS), \
             patch("core.management.commands.run_workers.call_command", side_effect=lambda n, *a, **k: calls.append(n)):
            call_command("run_workers", "--once", "--only", "sync_news", stdout=StringIO())
        self.assertEqual(calls, ["sync_news"])

    def test_jobs_without_keys_are_skipped(self):
        calls = []
        env = {k: "" for k in ALL_KEYS}
        with patch.dict("os.environ", env), \
             patch("core.management.commands.run_workers.call_command", side_effect=lambda n, *a, **k: calls.append(n)):
            call_command("run_workers", "--once", stdout=StringIO())
        self.assertEqual(calls, ["sync_vrs"])  # публичные данные Valve, ключ не нужен
