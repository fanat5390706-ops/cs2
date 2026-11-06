from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.models import Player

SID = "76561198000000001"


class SteamSyncTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(nickname="alpha", steam_id64=SID)
        Player.objects.create(nickname="nosteam")

    def fake(self, url, params=None, **kwargs):
        if "GetPlayerSummaries" in url:
            return {"response": {"players": [{"steamid": SID, "avatarfull": "https://x/a.jpg", "profileurl": "https://steamcommunity.com/id/alpha/"}]}}
        return {"players": [{"SteamId": SID, "VACBanned": True}]}

    @patch.dict("os.environ", {"STEAM_API_KEY": "test"})
    def test_sync_updates_profile_and_vac(self):
        with patch("core.management.commands.sync_steam.get_json", side_effect=self.fake):
            call_command("sync_steam", stdout=StringIO())
        self.player.refresh_from_db()
        self.assertEqual(self.player.avatar_url, "https://x/a.jpg")
        self.assertTrue(self.player.vac_banned)
        self.assertIsNotNone(self.player.steam_synced_at)
        self.assertIsNone(Player.objects.get(nickname="nosteam").vac_banned)

    @patch.dict("os.environ", {"STEAM_API_KEY": ""})
    def test_sync_without_key_fails(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("sync_steam", stdout=StringIO())
