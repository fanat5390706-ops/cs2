"""Автоматическая привязка SteamID через FACEIT (по нику игрока).

    python manage.py link_steam_via_faceit            # пробный запуск: только показывает, что нашла
    python manage.py link_steam_via_faceit --apply    # записать найденные SteamID
    python manage.py link_steam_via_faceit --limit 300 --min-elo 2000

FACEIT Data API отдаёт steam_id_64 профиля. Чтобы не привязать чужой аккаунт,
профиль принимается только если одновременно:
  * ник на FACEIT совпал с ником игрока (без учёта регистра);
  * у профиля есть CS2 и ELO не ниже --min-elo (профессионалы играют на высоком ELO);
  * страна совпала, если она известна и там и там;
  * SteamID ещё не занят другим игроком.
Это эвристика, а не гарантия: после --apply просмотрите список на сайте.
Дальше запустите sync_steam и sync_faceit.
"""
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from core.http import get_json
from core.models import Player

API = "https://open.faceit.com/data/v4/players"
ID64 = re.compile(r"^7656119\d{10}$")


class Command(BaseCommand):
    help = "Находит SteamID игроков через FACEIT по нику (с проверками)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Записать найденные SteamID (иначе пробный запуск).")
        parser.add_argument("--limit", type=int, default=200, help="Сколько игроков проверить за запуск.")
        parser.add_argument("--min-elo", type=int, default=1500, help="Минимальное CS2 ELO профиля.")

    def verify_profile(self, player, profile, min_elo):
        """Возвращает (SteamID, None) или (None, причина отказа)."""
        if not profile:
            return None, "нет профиля FACEIT"
        if (profile.get("nickname") or "").lower() != player.nickname.lower():
            return None, "ник не совпал"
        cs2 = (profile.get("games") or {}).get("cs2")
        if not cs2:
            return None, "нет CS2"
        if int(cs2.get("faceit_elo") or 0) < min_elo:
            return None, f"ELO ниже {min_elo}"
        country = (profile.get("country") or "").upper()
        if player.country and country and player.country.upper() != country:
            return None, f"страна {country} ≠ {player.country}"
        steam = profile.get("steam_id_64") or cs2.get("game_player_id") or ""
        if not ID64.match(str(steam)):
            return None, "SteamID не отдан"
        if Player.objects.filter(steam_id64=steam).exclude(pk=player.pk).exists():
            return None, "SteamID уже у другого игрока"
        return steam, None

    def handle(self, *args, **options):
        key = os.environ.get("FACEIT_API_KEY", "").strip()
        if not key or key == "change-me":
            raise CommandError("Не задан FACEIT_API_KEY в файле .env.")
        headers = {"Authorization": f"Bearer {key}"}

        players = Player.objects.filter(steam_id64__isnull=True).order_by("id")[: options["limit"]]
        found = 0
        for player in players:
            profile = get_json(API, {"nickname": player.nickname}, headers)
            steam, reason = self.verify_profile(player, profile, options["min_elo"])
            if steam is None:
                continue  # молча пропускаем: большинство ников на FACEIT не принадлежат этому игроку
            found += 1
            self.stdout.write(f"{player.nickname}: {steam}" + ("" if options["apply"] else " (пробный запуск)"))
            if options["apply"]:
                player.steam_id64 = steam
                player.faceit_nickname = profile["nickname"][:50]
                try:
                    player.save(update_fields=["steam_id64", "faceit_nickname"])
                except IntegrityError:
                    self.stdout.write(self.style.WARNING(f"{player.nickname}: конфликт уникальности, пропуск."))
        self.stdout.write(self.style.SUCCESS(
            f"Проверено {len(players)}, подходящих {found}." + ("" if options["apply"] else " Для записи добавьте --apply.")
        ))
