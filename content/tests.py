from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from content.models import LiveStream, NewsArticle, Video
from core.testing import make_tournament


class NewsTests(TestCase):
    reply = {"status": "ok", "articles": [
        {"url": "https://ex.org/a", "title": "CS2 update", "publishedAt": "2026-11-01T10:00:00Z",
         "source": {"name": "Ex"}, "description": "d", "urlToImage": None},
        {"url": None, "title": "broken", "publishedAt": "2026-11-01T10:00:00Z"},
    ]}

    @patch.dict("os.environ", {"NEWSAPI_KEY": "k"})
    def test_sync_is_idempotent_and_skips_broken(self):
        for _ in range(2):
            with patch("content.management.commands.sync_news.get_json", return_value=self.reply):
                call_command("sync_news", stdout=StringIO())
        self.assertEqual(NewsArticle.objects.count(), 1)

    @patch.dict("os.environ", {"NEWSAPI_KEY": ""})
    def test_requires_key(self):
        with self.assertRaises(CommandError):
            call_command("sync_news", stdout=StringIO())


class YoutubeTests(TestCase):
    @patch.dict("os.environ", {"YOUTUBE_API_KEY": "k"})
    def test_sync_saves_video_for_tournament(self):
        tournament = make_tournament()
        reply = {"items": [{"id": {"videoId": "abc123"}, "snippet": {
            "title": "Final highlights", "channelTitle": "Ch", "publishedAt": "2026-11-01T10:00:00Z",
            "thumbnails": {"medium": {"url": "https://i/x.jpg"}}}}]}
        with patch("content.management.commands.sync_youtube.get_json", return_value=reply):
            call_command("sync_youtube", stdout=StringIO())
        video = Video.objects.get(youtube_id="abc123")
        self.assertEqual(video.tournament, tournament)


class TwitchTests(TestCase):
    @patch.dict("os.environ", {"TWITCH_CLIENT_ID": "id", "TWITCH_CLIENT_SECRET": "s"})
    def test_sync_replaces_streams(self):
        LiveStream.objects.create(twitch_id="old", channel="old", title="old", viewers=1)

        def fake_get(url, params=None, headers=None, **kw):
            if url.endswith("/games"):
                return {"data": [{"id": "32399"}]}
            return {"data": [{"id": "1", "user_name": "esl_cs", "title": "Live", "viewer_count": 5000,
                              "thumbnail_url": "https://t/{width}x{height}.jpg", "language": "en",
                              "started_at": "2026-11-03T10:00:00Z"}]}

        with patch("content.management.commands.sync_twitch.post_form", return_value={"access_token": "t"}), \
             patch("content.management.commands.sync_twitch.get_json", side_effect=fake_get):
            call_command("sync_twitch", stdout=StringIO())
        self.assertEqual(list(LiveStream.objects.values_list("channel", flat=True)), ["esl_cs"])


class PagesTests(TestCase):
    def test_pages_render_empty_and_filled(self):
        for url in (reverse("web:news_list"), reverse("web:video_list"), reverse("web:video_list") + "?kind=vod", reverse("web:home")):
            self.assertEqual(self.client.get(url).status_code, 200)
        NewsArticle.objects.create(title="T", url="https://ex.org/t", source="S", published_at="2026-11-01T10:00:00Z")
        self.assertContains(self.client.get(reverse("web:news_list")), "T")
