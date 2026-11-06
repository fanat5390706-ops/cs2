"""Новости о CS2 из NewsAPI.

    python manage.py sync_news

Нужен NEWSAPI_KEY (.env). Бесплатный тариф NewsAPI рассчитан на разработку:
до 100 запросов в сутки, новости с задержкой, на публичном сайте использовать
нельзя — для учебного проекта на localhost этого достаточно.
"""
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from core.http import get_json
from content.models import NewsArticle


CS_TERMS = ("counter-strike", "counter strike", "cs2", "cs:go", "csgo", "hltv", "iem ", "blast premier",
            "blast.tv", "pgl major", "esl pro league", "cct ", "faceit major")


def is_cs_news(title, description=""):
    """NewsAPI ищет по всему тексту и отдаёт чужие новости: оставляем только то, где CS названа в заголовке/описании."""
    text = f"{title or ''} {description or ''}".lower()
    return any(term in text for term in CS_TERMS)


class Command(BaseCommand):
    help = "Загружает новости про Counter-Strike 2."

    def add_arguments(self, parser):
        parser.add_argument("--purge", action="store_true", help="Удалить из БД уже сохранённые новости не про CS.")

    def handle(self, *args, **options):
        if options["purge"]:
            removed = 0
            for article in NewsArticle.objects.all():
                if not is_cs_news(article.title, article.summary):
                    article.delete()
                    removed += 1
            self.stdout.write(f"Удалено новостей не про CS: {removed}.")
        key = os.environ.get("NEWSAPI_KEY", "").strip()
        if not key or key == "change-me":
            raise CommandError("Не задан NEWSAPI_KEY в .env (https://newsapi.org).")

        data = get_json(
            "https://newsapi.org/v2/everything",
            {"q": '"Counter-Strike" OR "CS2"', "searchIn": "title,description", "language": "en",
             "sortBy": "publishedAt", "pageSize": 100},
            {"X-Api-Key": key},
        ) or {}
        if data.get("status") == "error":
            raise CommandError(f"NewsAPI: {data.get('message', 'ошибка')}")
        self.stdout.write(f"NewsAPI нашёл статей: {data.get('totalResults', 0)}")
        saved = 0
        for a in data.get("articles", []):
            if not a.get("url") or not a.get("title") or not a.get("publishedAt"):
                continue
            if not is_cs_news(a["title"], a.get("description")):
                continue
            _, created = NewsArticle.objects.get_or_create(
                url=a["url"][:500],
                defaults={
                    "title": a["title"][:400],
                    "source": ((a.get("source") or {}).get("name") or "")[:150],
                    "summary": a.get("description") or "",
                    "image_url": (a.get("urlToImage") or "")[:500],
                    "published_at": datetime.fromisoformat(a["publishedAt"].replace("Z", "+00:00")),
                },
            )
            saved += int(created)
        self.stdout.write(self.style.SUCCESS(f"Новости: новых {saved}."))
