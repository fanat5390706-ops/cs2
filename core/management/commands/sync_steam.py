"""Обновление профилей игроков из Steam Web API.

    python manage.py sync_steam

Для игроков с заполненным steam_id64 загружает аватар, ссылку на профиль и
статус VAC-бана (ISteamUser/GetPlayerSummaries и GetPlayerBans).
Ключ берётся из переменной STEAM_API_KEY (файл .env).
SteamID привязывается вручную (админка) или командой import_steam_ids:
по нику игрока Steam найти нельзя, а угадывание привело бы к чужим аккаунтам.
"""
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.http import get_json
from core.models import Player

API = "https://api.steampowered.com"
BATCH = 100  # лимит Steam: до 100 SteamID за запрос


class Command(BaseCommand):
    help = "Загружает аватары и VAC-статус игроков из Steam Web API."

    def handle(self, *args, **options):
        key = os.environ.get("STEAM_API_KEY", "").strip()
        if not key or key == "change-me":
            raise CommandError("Не задан STEAM_API_KEY в файле .env (https://steamcommunity.com/dev/apikey).")

        players = list(Player.objects.exclude(steam_id64__isnull=True).exclude(steam_id64=""))
        if not players:
            self.stdout.write("Нет игроков с заполненным SteamID64. Используйте import_steam_ids или админку.")
            return

        updated = 0
        for i in range(0, len(players), BATCH):
            chunk = players[i : i + BATCH]
            ids = ",".join(p.steam_id64 for p in chunk)
            summaries = {
                s["steamid"]: s
                for s in get_json(f"{API}/ISteamUser/GetPlayerSummaries/v0002/", {"key": key, "steamids": ids})
                .get("response", {})
                .get("players", [])
            }
            bans = {
                b["SteamId"]: b
                for b in get_json(f"{API}/ISteamUser/GetPlayerBans/v1/", {"key": key, "steamids": ids}).get("players", [])
            }
            for player in chunk:
                summary, ban = summaries.get(player.steam_id64), bans.get(player.steam_id64)
                if summary is None and ban is None:
                    self.stdout.write(self.style.WARNING(f"{player.nickname}: SteamID {player.steam_id64} не найден."))
                    continue
                if summary:
                    player.avatar_url = summary.get("avatarfull", "")[:500]
                    player.steam_profile_url = summary.get("profileurl", "")[:300]
                if ban:
                    player.vac_banned = bool(ban.get("VACBanned"))
                player.steam_synced_at = timezone.now()
                player.save(update_fields=["avatar_url", "steam_profile_url", "vac_banned", "steam_synced_at"])
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"Обновлено игроков: {updated} из {len(players)}."))
