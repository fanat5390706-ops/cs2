"""Показывает, сколько данных реально лежит в БД — чтобы понять, почему страницы пустые.

    python manage.py data_status
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from content.models import NewsArticle, Video
from core.models import Player, Team, TeamRanking
from matches.models import Match, PlayerMapStat
from tournaments.models import Tournament


class Command(BaseCommand):
    help = "Сводка по данным в БД."

    def handle(self, *args, **options):
        p = Player.objects.aggregate(
            total=Count("id"),
            photo=Count("id", filter=~Q(photo_url="")),
            role=Count("id", filter=~Q(role="")),
            steam=Count("id", filter=Q(steam_id64__isnull=False)),
            faceit=Count("id", filter=Q(faceit_elo__isnull=False)),
            kd=Count("id", filter=Q(faceit_kd__isnull=False)),
        )
        m = {s: Match.objects.filter(status=s).count() for s in ("scheduled", "live", "finished", "cancelled")}
        lines = [
            f"Команды: {Team.objects.count()} (с логотипом: {Team.objects.exclude(logo_url='').count()})",
            f"Игроки: {p['total']}; с фото {p['photo']}; с ролью {p['role']}; SteamID {p['steam']}; FACEIT ELO {p['faceit']}; FACEIT K/D {p['kd']}",
            f"Турниры: {Tournament.objects.count()}",
            f"Матчи: {m}",
            f"Статистика игроков по картам (PlayerMapStat): {PlayerMapStat.objects.count()}",
            f"Рейтинг команд (строк): {TeamRanking.objects.count()}",
            f"Новости: {NewsArticle.objects.count()}; видео: {Video.objects.count()}",
        ]
        self.stdout.write("\n".join(lines))
        if p["steam"] == 0:
            self.stdout.write(self.style.WARNING("Нет SteamID -> FACEIT не найдёт игроков: выполните link_steam_via_faceit --apply."))
        if p["faceit"] and not p["kd"]:
            self.stdout.write(self.style.WARNING("FACEIT ELO есть, а K/D нет: выполните sync_faceit ещё раз."))
        if not TeamRanking.objects.exists():
            self.stdout.write(self.style.WARNING("Рейтинга нет: выполните compute_ranking."))
