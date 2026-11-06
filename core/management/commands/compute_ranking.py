"""Считает собственный рейтинг команд (Elo) по завершённым матчам и сохраняет снимок в team_ranking.

Это НЕ рейтинг HLTV/Valve: он строится только из результатов серий, которые есть в нашей БД.
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Team, TeamRanking
from web.queries import fetch_all

SOURCE = "khltv"
START, K = 1000.0, 32.0


def elo_ratings(series):
    """series: итерируемое (tag1, tag2, maps1, maps2) в хронологическом порядке -> {tag: рейтинг}."""
    rating = {}
    for tag1, tag2, m1, m2 in series:
        if m1 == m2:  # ничья/нет данных о счёте — не учитываем
            continue
        r1, r2 = rating.get(tag1, START), rating.get(tag2, START)
        expected1 = 1 / (1 + 10 ** ((r2 - r1) / 400))
        score1 = 1.0 if m1 > m2 else 0.0
        rating[tag1] = r1 + K * (score1 - expected1)
        rating[tag2] = r2 + K * ((1 - score1) - (1 - expected1))
    return rating


class Command(BaseCommand):
    help = "Пересчитывает рейтинг команд (Elo) и сохраняет снимок на сегодня."

    def add_arguments(self, parser):
        parser.add_argument("--top", type=int, default=100)

    def handle(self, *args, **options):
        rows = fetch_all(
            "SELECT tag1, tag2, maps_team1, maps_team2 FROM v_match_series_score "
            "WHERE status = 'finished' ORDER BY scheduled_at, match_id"
        )
        ratings = elo_ratings((r["tag1"], r["tag2"], r["maps_team1"], r["maps_team2"]) for r in rows)
        teams = {t.tag: t for t in Team.objects.filter(tag__in=ratings)}
        ordered = sorted(
            ((tag, rt) for tag, rt in ratings.items() if tag in teams), key=lambda x: (-x[1], x[0])
        )[: options["top"]]
        today = date.today()
        with transaction.atomic():
            TeamRanking.objects.filter(source=SOURCE, valid_on=today).delete()
            TeamRanking.objects.bulk_create(
                TeamRanking(team=teams[tag], source=SOURCE, valid_on=today, position=i, points=round(rt))
                for i, (tag, rt) in enumerate(ordered, start=1)
            )
        self.stdout.write(self.style.SUCCESS(f"Рейтинг обновлён: {len(ordered)} команд."))
