from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.management.commands.sync_liquipedia import parse_infobox
from core.models import Player

WIKI = """{{Infobox player
|id=Alpha
|name=Ivan Petrov
|birth_date=1999-05-17
|team=Red Foxes
}}
'''Alpha''' is a player."""


class LiquipediaTests(TestCase):
    def test_parse_infobox(self):
        info = parse_infobox(WIKI)
        self.assertEqual(info["id"], "Alpha")
        self.assertEqual(info["birth_date"], "1999-05-17")
        self.assertIsNone(parse_infobox("no infobox here"))

    @patch.dict("os.environ", {"LIQUIPEDIA_CONTACT": "test@example.org"})
    def test_sync_fills_empty_fields_only(self):
        player = Player.objects.create(nickname="alpha")
        reply = {"query": {"pages": [{"title": "Alpha", "revisions": [{"slots": {"main": {"content": WIKI}}}]}]}}
        with patch("core.management.commands.sync_liquipedia.get_json", return_value=reply):
            call_command("sync_liquipedia", stdout=StringIO())
        player.refresh_from_db()
        self.assertEqual(player.first_name, "Ivan")
        self.assertEqual(str(player.birth_date), "1999-05-17")
        self.assertEqual(player.liquipedia_page, "Alpha")

    @patch.dict("os.environ", {"LIQUIPEDIA_CONTACT": "test@example.org"})
    def test_mismatching_birth_date_is_skipped(self):
        from datetime import date
        player = Player.objects.create(nickname="alpha", birth_date=date(2001, 1, 1))
        reply = {"query": {"pages": [{"title": "Alpha", "revisions": [{"slots": {"main": {"content": WIKI}}}]}]}}
        with patch("core.management.commands.sync_liquipedia.get_json", return_value=reply):
            call_command("sync_liquipedia", stdout=StringIO())
        player.refresh_from_db()
        self.assertEqual(player.liquipedia_page, "")

    @patch.dict("os.environ", {"LIQUIPEDIA_CONTACT": ""})
    def test_requires_contact(self):
        with self.assertRaises(CommandError):
            call_command("sync_liquipedia", stdout=StringIO())


class FaceitTests(TestCase):
    def fake(self, url, params=None, headers=None, **kwargs):
        if url.endswith("/stats/cs2"):
            return {"lifetime": {"Matches": "1,234", "Win Rate %": "55"}}
        return {"player_id": "abc-123", "nickname": "alpha_f", "games": {"cs2": {"faceit_elo": 2750, "skill_level": 10}}}

    @patch.dict("os.environ", {"FACEIT_API_KEY": "test"})
    def test_sync_saves_elo_level_and_winrate(self):
        player = Player.objects.create(nickname="alpha", steam_id64="76561198000000001")
        with patch("core.management.commands.sync_faceit.get_json", side_effect=self.fake):
            call_command("sync_faceit", stdout=StringIO())
        player.refresh_from_db()
        self.assertEqual((player.faceit_elo, player.faceit_level), (2750, 10))
        self.assertEqual((player.faceit_matches, player.faceit_win_rate), (1234, 55))

    @patch.dict("os.environ", {"FACEIT_API_KEY": ""})
    def test_requires_key(self):
        with self.assertRaises(CommandError):
            call_command("sync_faceit", stdout=StringIO())


class LinkSteamViaFaceitTests(TestCase):
    def profile(self, **over):
        data = {"nickname": "Alpha", "country": "ua", "steam_id_64": "76561198000000009",
                "games": {"cs2": {"faceit_elo": 3000, "skill_level": 10}}}
        data.update(over)
        return data

    def run_cmd(self, profile, *args):
        with patch.dict("os.environ", {"FACEIT_API_KEY": "k"}), \
             patch("core.management.commands.link_steam_via_faceit.get_json", return_value=profile):
            call_command("link_steam_via_faceit", *args, stdout=StringIO())

    def test_dry_run_changes_nothing(self):
        player = Player.objects.create(nickname="alpha", country="UA")
        self.run_cmd(self.profile())
        player.refresh_from_db()
        self.assertIsNone(player.steam_id64)

    def test_apply_links_when_checks_pass(self):
        player = Player.objects.create(nickname="alpha", country="UA")
        self.run_cmd(self.profile(), "--apply")
        player.refresh_from_db()
        self.assertEqual(player.steam_id64, "76561198000000009")

    def test_rejects_wrong_country_low_elo_and_other_nick(self):
        player = Player.objects.create(nickname="alpha", country="UA")
        for bad in (self.profile(country="ru"), self.profile(nickname="Other"),
                    self.profile(games={"cs2": {"faceit_elo": 800}}), None):
            self.run_cmd(bad, "--apply")
        player.refresh_from_db()
        self.assertIsNone(player.steam_id64)
