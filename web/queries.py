"""Чтение из SQL-представлений (v_match_series_score, v_player_totals, v_tournament_standings)."""
from datetime import datetime, timezone as dt_timezone

from django.db import connection
from django.utils import timezone


def fetch_all(sql, params=None):
    """Выполняет SELECT и возвращает список словарей.

    Даты из «сырых» запросов приходят наивными (в UTC), поэтому делаем их aware,
    чтобы шаблоны показывали время в часовом поясе проекта.
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        rows = []
        for raw in cursor.fetchall():
            row = {}
            for column, value in zip(columns, raw):
                if isinstance(value, datetime) and timezone.is_naive(value):
                    value = timezone.make_aware(value, dt_timezone.utc)
                row[column] = value
            rows.append(row)
        return rows
