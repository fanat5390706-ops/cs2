"""Обновление данных игроков из FACEIT Data API (ELO, уровень, винрейт).

    python manage.py sync_faceit

Кого искать: игроков с SteamID64 (поиск по game_player_id, надёжно) и игроков
с вручную внесённым faceit_nickname. Ключ — переменная FACEIT_API_KEY (.env).
"""
import os

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from core.http import get_json
from core.models import Player

API = "https://open.faceit.com/data/v4"


def to_decimal(value):
    try:
        return round(float(str(value).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def map_stats(segments):
    """Сегменты FACEIT (type=Map) -> компактный список по картам."""
    result = []
    for seg in segments or []:
        if seg.get("type") != "Map" or seg.get("mode") not in (None, "5v5"):
            continue
        st = seg.get("stats") or {}
        matches = to_int(st.get("Matches"))
        if not matches:
            continue
        name = (seg.get("label") or "").replace("de_", "").replace("_", " ").title()
        result.append({
            "map": name, "matches": matches, "win_rate": to_int(st.get("Win Rate %")),
            "kd": to_decimal(st.get("Average K/D Ratio")), "hs": to_int(st.get("Average Headshots %")),
        })
    return sorted(result, key=lambda r: -r["matches"])


def to_int(value):
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = "Загружает FACEIT ELO, уровень и винрейт игроков."

    def handle(self, *args, **options):
        key = os.environ.get("FACEIT_API_KEY", "").strip()
        if not key or key == "change-me":
            raise CommandError("Не задан FACEIT_API_KEY в файле .env (https://developers.faceit.com).")
        headers = {"Authorization": f"Bearer {key}"}

        candidates = Player.objects.filter(
            Q(steam_id64__isnull=False, steam_id64__gt="") | Q(faceit_nickname__gt="")
        )
        updated = missing = 0
        for player in candidates:
            profile = None
            if player.steam_id64:
                profile = get_json(f"{API}/players", {"game": "cs2", "game_player_id": player.steam_id64}, headers)
            if profile is None and player.faceit_nickname:
                profile = get_json(f"{API}/players", {"nickname": player.faceit_nickname}, headers)
            cs2 = ((profile or {}).get("games") or {}).get("cs2")
            if not profile or not cs2:
                missing += 1
                continue

            lifetime, segments = {}, []
            stats = get_json(f"{API}/players/{profile['player_id']}/stats/cs2", None, headers)
            if stats:
                lifetime = stats.get("lifetime") or {}
                segments = stats.get("segments") or []
            if profile.get("avatar") and not (player.avatar_url or player.photo_url):
                player.avatar_url = profile["avatar"][:500]

            player.faceit_player_id = profile["player_id"]
            player.faceit_nickname = profile.get("nickname", player.faceit_nickname)[:50]
            player.faceit_elo = to_int(cs2.get("faceit_elo"))
            player.faceit_level = to_int(cs2.get("skill_level"))
            player.faceit_matches = to_int(lifetime.get("Matches"))
            player.faceit_win_rate = to_int(lifetime.get("Win Rate %"))
            player.faceit_kd = to_decimal(lifetime.get("Average K/D Ratio"))
            player.faceit_hs = to_int(lifetime.get("Average Headshots %"))
            player.faceit_maps = map_stats(segments)
            player.faceit_synced_at = timezone.now()
            player.save(update_fields=[
                "faceit_player_id", "faceit_nickname", "faceit_elo", "faceit_level",
                "faceit_matches", "faceit_win_rate", "faceit_kd", "faceit_hs", "faceit_maps", "avatar_url",
                "faceit_synced_at",
            ])
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"FACEIT: обновлено {updated}, не найдено {missing}."))
