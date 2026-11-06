"""Хайлайты и записи матчей с YouTube (YouTube Data API v3).

    python manage.py sync_youtube [--max-queries 8]

Нужен YOUTUBE_API_KEY (.env). Каждый поисковый запрос стоит 100 единиц
дневной квоты (бесплатно 10 000), поэтому за запуск делается не более
--max-queries запросов: по идущим и недавним турнирам («<турнир> highlights»).
Видео сохраняются с привязкой к турниру; повторный запуск дубли не создаёт.
"""
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from core.http import get_json
from content.models import Video
from tournaments.models import Tournament

SEARCH = "https://www.googleapis.com/youtube/v3/search"


class Command(BaseCommand):
    help = "Загружает хайлайты матчей и записи турниров с YouTube."

    def add_arguments(self, parser):
        parser.add_argument("--max-queries", type=int, default=8)

    def handle(self, *args, **options):
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not key or key == "change-me":
            raise CommandError("Не задан YOUTUBE_API_KEY в .env (Google Cloud Console → Credentials).")

        saved = 0
        for tournament in Tournament.objects.order_by("-start_date")[: options["max_queries"]]:
            data = get_json(
                SEARCH,
                {
                    "part": "snippet", "type": "video", "order": "date", "maxResults": 8, "key": key,
                    "q": f"{tournament.name} CS2 highlights",
                },
            ) or {}
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                video_id = (item.get("id") or {}).get("videoId")
                if not video_id:
                    continue
                title = snippet.get("title", "")
                kind = Video.Kind.VOD if "full match" in title.lower() else (
                    Video.Kind.INTERVIEW if "interview" in title.lower() else Video.Kind.HIGHLIGHT
                )
                _, created = Video.objects.get_or_create(
                    youtube_id=video_id,
                    defaults={
                        "title": title[:300],
                        "channel": snippet.get("channelTitle", "")[:150],
                        "kind": kind,
                        "thumbnail_url": ((snippet.get("thumbnails") or {}).get("medium") or {}).get("url", "")[:500],
                        "published_at": datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")),
                        "tournament": tournament,
                    },
                )
                saved += int(created)
        self.stdout.write(self.style.SUCCESS(f"YouTube: новых видео {saved}."))
