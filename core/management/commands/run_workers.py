"""Фоновые воркеры: периодически запускают синхронизации с внешними API.

    python manage.py run_workers            # работает, пока не остановите (Ctrl+C)
    python manage.py run_workers --once     # выполнить все задачи один раз и выйти
    python manage.py run_workers --only sync_news sync_twitch

Это обычный цикл на команде Django, без Celery и Redis (в проекте не нужны
дополнительные компоненты). Сбой одной задачи (нет ключа, API недоступен)
не останавливает остальные: ошибка пишется в вывод, задача повторится по расписанию.
Альтернатива — запускать нужные команды из Планировщика заданий Windows.
"""
import os
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

# Переменные окружения, без которых задача бессмысленна (тогда она тихо пропускается)
REQUIRES = {
    "sync_matches": ["PANDASCORE_TOKEN"],
    "import_pandascore": ["PANDASCORE_TOKEN"],
    "sync_twitch": ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"],
    "sync_news": ["NEWSAPI_KEY"],
    "sync_youtube": ["YOUTUBE_API_KEY"],
    "sync_steam": ["STEAM_API_KEY"],
    "sync_faceit": ["FACEIT_API_KEY"],
    "sync_liquipedia": ["LIQUIPEDIA_CONTACT"],
}

# (команда, период в минутах)
JOBS = [
    ("sync_matches", 1),
    ("sync_vrs", 1440),
    ("sync_twitch", 5),
    ("sync_news", 30),
    ("import_pandascore", 60),
    ("sync_youtube", 360),
    ("sync_steam", 1440),
    ("sync_faceit", 1440),
    ("sync_liquipedia", 1440),
]


class Command(BaseCommand):
    help = "Периодически запускает синхронизации с внешними API."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Выполнить все задачи один раз и выйти.")
        parser.add_argument("--only", nargs="+", help="Только указанные команды.")

    def configured(self, name):
        missing = [v for v in REQUIRES.get(name, []) if os.environ.get(v, "").strip() in ("", "change-me")]
        if missing and name not in self.skipped:
            self.skipped.add(name)
            self.stdout.write(self.style.WARNING(f"{name}: пропущено, нет {', '.join(missing)} в .env"))
        return not missing

    def run_job(self, name):
        if not self.configured(name):
            return
        try:
            self.stdout.write(f"[{time.strftime('%H:%M:%S')}] {name}")
            call_command(name, stdout=self.stdout)
        except BaseException as error:  # noqa: BLE001 — воркер не должен падать из-за одной задачи
            if isinstance(error, KeyboardInterrupt):
                raise
            self.stdout.write(self.style.WARNING(f"{name}: {error}"))

    def handle(self, *args, **options):
        self.skipped = set()
        jobs = [(n, p) for n, p in JOBS if not options["only"] or n in options["only"]]
        if options["once"]:
            for name, _ in jobs:
                self.run_job(name)
            return
        next_run = {name: 0.0 for name, _ in jobs}
        self.stdout.write("Воркеры запущены. Остановка: Ctrl+C.")
        try:
            while True:
                now = time.monotonic()
                for name, minutes in jobs:
                    if now >= next_run[name]:
                        self.run_job(name)
                        next_run[name] = time.monotonic() + minutes * 60
                time.sleep(15)
        except KeyboardInterrupt:
            self.stdout.write("Воркеры остановлены.")
