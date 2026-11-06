"""Ручной импорт рейтинга команд из CSV (например, списка, который вы сверили с рейтингом HLTV).

    python manage.py import_ranking ranking.csv [--date 2026-11-02]

Колонки: position, team, points (points можно не заполнять).
Рейтинг сохраняется с источником «manual» и имеет приоритет над рейтингом Valve на сайте.
Команда ищется по названию или тегу без учёта регистра; не найденная остаётся с текстовым названием.
"""
import csv
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from core.models import Team, TeamRanking


class Command(BaseCommand):
    help = "Загрузить рейтинг команд из CSV (position, team, points)."

    def add_arguments(self, parser):
        parser.add_argument("csv_file")
        parser.add_argument("--date", help="Дата рейтинга YYYY-MM-DD (по умолчанию сегодня).")

    def handle(self, *args, **opts):
        try:
            valid_on = date.fromisoformat(opts["date"]) if opts["date"] else date.today()
        except ValueError:
            raise CommandError("Дата должна быть в формате YYYY-MM-DD.")
        try:
            handle = open(opts["csv_file"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"Не удалось открыть файл: {exc}")
        with handle:
            reader = csv.DictReader(handle)
            if not {"position", "team"} <= set(reader.fieldnames or []):
                raise CommandError("Нужны колонки position и team (points — по желанию).")
            rows = list(reader)
        created, unmatched, seen_pos, seen_team = [], [], set(), set()
        for line, row in enumerate(rows, start=2):
            try:
                position = int(row["position"])
            except (TypeError, ValueError):
                raise CommandError(f"Строка {line}: position должен быть числом.")
            name = (row["team"] or "").strip()
            if not name or position in seen_pos or name.lower() in seen_team:
                raise CommandError(f"Строка {line}: пустая или повторяющаяся команда/позиция.")
            seen_pos.add(position)
            seen_team.add(name.lower())
            team = Team.objects.filter(Q(name__iexact=name) | Q(tag__iexact=name)).first()
            if team is None:
                unmatched.append(name)
            points = (row.get("points") or "").strip()
            created.append(TeamRanking(team=team, team_name=name, source="manual", valid_on=valid_on,
                                       position=position, points=int(points) if points.isdigit() else 0))
        with transaction.atomic():
            TeamRanking.objects.filter(source="manual", valid_on=valid_on).delete()
            TeamRanking.objects.bulk_create(created)
        self.stdout.write(self.style.SUCCESS(f"Рейтинг загружен: {len(created)} команд на {valid_on}."))
        if unmatched:
            self.stdout.write(self.style.WARNING("Нет в базе (будут без логотипа/ссылки): " + ", ".join(unmatched)))
