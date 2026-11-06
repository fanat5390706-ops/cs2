from django.contrib import admin

from .models import LiveStream, NewsArticle, Video


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "source", "published_at"]
    search_fields = ["title", "source"]


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ["title", "channel", "kind", "published_at", "tournament"]
    list_filter = ["kind"]
    search_fields = ["title", "channel"]


@admin.register(LiveStream)
class LiveStreamAdmin(admin.ModelAdmin):
    list_display = ["channel", "viewers", "language", "tournament", "fetched_at"]
