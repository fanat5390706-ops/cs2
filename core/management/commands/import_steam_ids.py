"""Привязка SteamID к игрокам из CSV-файла.

    python manage.py import_steam_ids steam_ids.csv

Формат (первая строка — заголовок):
    nickname,steam
    s1mple,76561198034202275
    donk,https://steamcommunity.com/profiles/7656119...
    zywoo,https://steamcommunity.com/id/zywoo_vanity

В колонке steam допустимы: SteamID64, ссылка /profiles/<id64> или /id/<vanity>
(для vanity нужен STEAM_API_KEY). Никнеймы, которых нет в базе, пропускаются.
"""
import csv
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from core.http import get_json
from core.models import Player

ID64 = re.compile(r"^7656119\d{10}$")


class Command(BaseCommand):
    help = "Записывает steam_id64 игрокам из CSV (nickname,steam)."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def resolve(self, value):
        value = value.strip().rstrip("/")
        if ID64.match(value):
            return value
        m = re.search(r"/profiles/(\d+)$", value)
        if m and ID64.match(m.group(1)):
            return m.group(1)
        m = re.search(r"/id/([^/]+)$", value) or (re.match(r"^[\w-]{2,32}$", value) and re.match(r"(.+)", value))
        if m:
            key = os.environ.get("STEAM_API_KEY", "").strip()
            if not key or key == "change-me":
                raise CommandError("Для ссылок /id/... нужен STEAM_API_KEY в .env.")
            data = get_json(
                "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/",
                {"key": key, "vanityurl": m.group(1)},
            ).get("response", {})
            if data.get("success") == 1:
                return data["steamid"]
        return None

    def handle(self, *args, **options):
        try:
            handle = open(options["path"], newline="", encoding="utf-8-sig")
        except OSError as error:
            raise CommandError(f"Не удалось открыть файл: {error}")
        saved = skipped = 0
        with handle:
            for row in csv.DictReader(handle):
                nick, raw = (row.get("nickname") or "").strip(), (row.get("steam") or "").strip()
                player = Player.objects.filter(nickname__iexact=nick).first()
                steam_id = self.resolve(raw) if raw else None
                if player is None or steam_id is None:
                    self.stdout.write(self.style.WARNING(f"Пропуск: {nick!r} / {raw!r}"))
                    skipped += 1
                    continue
                player.steam_id64 = steam_id
                try:
                    player.save(update_fields=["steam_id64"])
                    saved += 1
                except IntegrityError:
                    self.stdout.write(self.style.WARNING(f"{nick}: этот SteamID уже у другого игрока."))
                    skipped += 1
        self.stdout.write(self.style.SUCCESS(f"Привязано: {saved}, пропущено: {skipped}."))
