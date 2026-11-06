"""Текущие трансляции Counter-Strike на Twitch.

    python manage.py sync_twitch [--limit 20]

Нужны TWITCH_CLIENT_ID и TWITCH_CLIENT_SECRET (.env). Токен приложения
запрашивается автоматически (client credentials). Таблица live_stream
каждый раз заменяется текущим списком; трансляция привязывается к идущему
турниру, если название турнира встречается в заголовке трансляции.
"""
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.http import get_json, post_form
from content.models import LiveStream
from tournaments.models import Tournament, TournamentStatus

HELIX = "https://api.twitch.tv/helix"


class Command(BaseCommand):
    help = "Загружает активные трансляции CS на Twitch и число зрителей."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        client_id = os.environ.get("TWITCH_CLIENT_ID", "").strip()
        secret = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
        if not client_id or not secret or "change-me" in (client_id, secret):
            raise CommandError("Задайте TWITCH_CLIENT_ID и TWITCH_CLIENT_SECRET в .env (https://dev.twitch.tv/console).")

        token = post_form(
            "https://id.twitch.tv/oauth2/token",
            {"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"},
        ).get("access_token")
        if not token:
            raise CommandError("Twitch не выдал токен.")
        headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}

        games = (get_json(f"{HELIX}/games", {"name": "Counter-Strike"}, headers) or {}).get("data", [])
        if not games:
            raise CommandError("Категория Counter-Strike не найдена на Twitch.")
        streams = (
            get_json(f"{HELIX}/streams", {"game_id": games[0]["id"], "first": options["limit"]}, headers) or {}
        ).get("data", [])

        tournaments = list(Tournament.objects.filter(status=TournamentStatus.ONGOING))
        with transaction.atomic():
            LiveStream.objects.all().delete()
            for s in streams:
                title = s.get("title", "")
                LiveStream.objects.create(
                    twitch_id=s["id"],
                    channel=s.get("user_name", s.get("user_login", ""))[:60],
                    title=title[:300],
                    viewers=s.get("viewer_count", 0),
                    thumbnail_url=s.get("thumbnail_url", "").replace("{width}", "440").replace("{height}", "248")[:500],
                    language=s.get("language", "")[:10],
                    started_at=datetime.fromisoformat(s["started_at"].replace("Z", "+00:00")) if s.get("started_at") else None,
                    tournament=next((t for t in tournaments if t.name.lower() in title.lower()), None),
                )
        self.stdout.write(self.style.SUCCESS(f"Twitch: трансляций {len(streams)}."))
