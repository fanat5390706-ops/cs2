from django.db import models

from core.models import Player, Team
from tournaments.models import Tournament


class LiveStream(models.Model):
    """Текущая трансляция Counter-Strike на Twitch. Таблица перезаписывается при каждой синхронизации."""

    twitch_id = models.CharField("ID трансляции", max_length=40, unique=True)
    channel = models.CharField("Канал", max_length=60)
    title = models.CharField("Название", max_length=300)
    viewers = models.PositiveIntegerField("Зрителей", default=0)
    thumbnail_url = models.URLField("Превью", max_length=500, blank=True)
    language = models.CharField("Язык", max_length=10, blank=True)
    started_at = models.DateTimeField("Начало", null=True, blank=True)
    tournament = models.ForeignKey(
        Tournament, null=True, blank=True, on_delete=models.SET_NULL, related_name="streams", verbose_name="Турнир"
    )
    fetched_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "live_stream"
        ordering = ["-viewers"]
        verbose_name = "трансляция"
        verbose_name_plural = "трансляции"

    def __str__(self):
        return f"{self.channel} ({self.viewers})"


class Video(models.Model):
    """Видео YouTube: хайлайты, VOD, интервью."""

    class Kind(models.TextChoices):
        HIGHLIGHT = "highlight", "Хайлайты"
        VOD = "vod", "Запись матча"
        INTERVIEW = "interview", "Интервью"

    youtube_id = models.CharField("ID видео", max_length=20, unique=True)
    title = models.CharField("Название", max_length=300)
    channel = models.CharField("Канал", max_length=150)
    kind = models.CharField("Тип", max_length=20, choices=Kind.choices, default=Kind.HIGHLIGHT)
    thumbnail_url = models.URLField("Превью", max_length=500, blank=True)
    published_at = models.DateTimeField("Опубликовано")
    tournament = models.ForeignKey(Tournament, null=True, blank=True, on_delete=models.SET_NULL, related_name="videos")
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="videos")
    player = models.ForeignKey(Player, null=True, blank=True, on_delete=models.SET_NULL, related_name="videos")

    class Meta:
        db_table = "video"
        ordering = ["-published_at"]
        verbose_name = "видео"
        verbose_name_plural = "видео"

    def __str__(self):
        return self.title


class NewsArticle(models.Model):
    title = models.CharField("Заголовок", max_length=400)
    url = models.URLField("Ссылка", max_length=500, unique=True)
    source = models.CharField("Источник", max_length=150)
    summary = models.TextField("Описание", blank=True)
    image_url = models.URLField("Картинка", max_length=500, blank=True)
    published_at = models.DateTimeField("Опубликовано")

    class Meta:
        db_table = "news_article"
        ordering = ["-published_at"]
        verbose_name = "новость"
        verbose_name_plural = "новости"
        indexes = [models.Index(fields=["published_at"], name="ix_news_published")]

    def __str__(self):
        return self.title
