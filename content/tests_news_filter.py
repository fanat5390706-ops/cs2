from django.test import SimpleTestCase

from content.management.commands.sync_news import is_cs_news


class NewsFilterTests(SimpleTestCase):
    def test_cs_news_kept_and_others_dropped(self):
        self.assertTrue(is_cs_news("Vitality win IEM Katowice", "CS2 grand final"))
        self.assertTrue(is_cs_news("HLTV rankings updated"))
        self.assertFalse(is_cs_news("Stock market rallies", "Tech shares up"))
        self.assertFalse(is_cs_news("", None))
