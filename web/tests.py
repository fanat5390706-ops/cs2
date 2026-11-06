from django.urls import reverse

from matches.services import record_map
from matches.tests import MatchTestBase, stat


class PageSmokeTests(MatchTestBase):
    """Каждая страница сайта отвечает 200 и показывает данные."""

    def setUp(self):
        super().setUp()
        self.match = self.new_match()
        stats = [stat(p, 1) for p in self.players_a] + [stat(p, 2) for p in self.players_b]
        record_map(self.match, self.maps[0], 1, {1: 13, 2: 7}, stats)

    def test_all_pages_ok(self):
        urls = [
            reverse("web:home"),
            reverse("web:tournament_list"),
            reverse("web:tournament_list") + "?status=ongoing",
            reverse("web:tournament_detail", args=[self.tournament.pk]),
            *[reverse("web:match_detail", args=[self.match.pk]) + f"?tab={t}" for t in
              ("overview", "scoreboard", "stats", "lineups", "h2h", "bogus")],
            reverse("web:match_detail", args=[self.match.pk]),
            reverse("web:tournament_list") + "?status=finished",
            reverse("web:team_list"),
            reverse("web:team_list") + "?q=Alpha",
            reverse("web:team_detail", args=[self.team_a.pk]),
            *[reverse("web:team_detail", args=[self.team_a.pk]) + f"?tab={t}" for t in
              ("overview", "players", "matches", "results", "stats", "news", "bogus")],
            reverse("web:player_list") + "?role=awper&sort=winrate",
            reverse("web:player_list"),
            reverse("web:player_list") + "?q=a&sort=kd&team=AAA",
            reverse("web:player_detail", args=[self.players_a[0].pk]),
            reverse("web:matches"),
            reverse("web:matches") + "?tab=live",
            reverse("web:matches") + "?tab=results&tournament=%d" % self.tournament.pk,
            reverse("web:matches") + "?tab=unknown",
            reverse("web:results"),
            reverse("web:stats"),
            *[reverse("web:stats") + f"?section={s}" for s in ("players", "teams", "maps", "bogus")],
            reverse("web:matches") + "?tab=upcoming&tier=1",
            reverse("web:maps"),
            reverse("web:search"),
            reverse("web:search") + "?q=Alpha",
            reverse("login"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_signup_creates_viewer_user(self):
        response = self.client.post(reverse("web:signup"), {
            "username": "viewer1", "password1": "Str0ng-pass-2026", "password2": "Str0ng-pass-2026"})
        self.assertEqual(response.status_code, 302)
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.get(username="viewer1")
        self.assertFalse(user.is_staff)
        self.assertTrue(user.groups.filter(name="Зритель").exists())
        self.assertEqual(self.client.get(reverse("web:signup")).status_code, 200)

    def test_favorite_team_requires_login_then_toggles(self):
        url = reverse("web:team_favorite", args=[self.team_a.pk])
        self.assertEqual(self.client.post(url).status_code, 302)  # на страницу входа
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user("fan", password="Str0ng-pass-2026")
        self.client.force_login(user)
        self.client.post(url)
        self.assertTrue(user.favorite_teams.filter(team=self.team_a).exists())
        self.client.post(url)
        self.assertFalse(user.favorite_teams.filter(team=self.team_a).exists())
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_follow_tournament_toggles_and_blocks_foreign_redirect(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user("fan2", password="Str0ng-pass-2026")
        self.client.force_login(user)
        url = reverse("web:tournament_follow", args=[self.tournament.pk])
        response = self.client.post(url, {"next": "https://evil.example/"})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example", response["Location"])
        self.assertTrue(user.followed_tournaments.exists())
        self.client.post(url)
        self.assertFalse(user.followed_tournaments.exists())

    def test_matches_team_filter(self):
        url = reverse("web:matches") + "?tab=live&q=Alpha"
        self.assertContains(self.client.get(url), "Alpha")
        self.assertNotContains(self.client.get(reverse("web:matches") + "?tab=live&q=Nobody"), "Alpha")

    def test_match_page_shows_map_and_score(self):
        response = self.client.get(reverse("web:match_detail", args=[self.match.pk]))
        self.assertContains(response, "Mirage")
        self.assertContains(response, "13")

    def test_live_match_is_marked_on_home(self):
        # После первой карты BO3 матч идёт: на главной есть метка LIVE.
        self.assertContains(self.client.get(reverse("web:home")), "LIVE")

    def test_unknown_sort_falls_back_to_default(self):
        response = self.client.get(reverse("web:player_list") + "?sort=; DROP TABLE player")
        self.assertEqual(response.status_code, 200)

    def test_unknown_match_returns_404(self):
        self.assertEqual(self.client.get(reverse("web:match_detail", args=[999999])).status_code, 404)


class StrengthSortTests(TestCase):
    def test_tier_and_order(self):
        from datetime import date, datetime, timezone as tz
        from web import views
        self.assertEqual([views.team_tier(p) for p in (1, 10, 11, 30, 31, 100, 101, 0)], [1, 1, 2, 2, 3, 3, 4, 4])
        d = date(2026, 11, 6)
        mk = lambda tier, h: {"status": "scheduled", "day": d, "tier": tier, "scheduled_at": datetime(2026, 11, 6, h, tzinfo=tz.utc)}
        rows = views.sort_by_strength([mk(4, 8), mk(3, 18), mk(1, 10), mk(4, 9), mk(2, 13)])
        # сначала тир 1–3 по времени, затем остальные тоже по времени
        self.assertEqual([(r["tier"], r["scheduled_at"].hour) for r in rows], [(1, 10), (2, 13), (3, 18), (4, 8), (4, 9)])
