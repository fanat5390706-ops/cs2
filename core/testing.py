"""Фабрики для автотестов: небольшие хелперы, чтобы не повторять создание данных."""
from datetime import date

from django.contrib.auth import get_user_model

from core.models import Player, Team, TeamMembership
from tournaments.models import Tournament, TournamentStatus
from tournaments.services import register_team

JOINED = date(2026, 1, 1)
REG_DATE = date(2026, 2, 1)


def make_team(name: str, tag: str, size: int = 5, joined_on: date = JOINED):
    """Команда с size игроками, все состоят в ней с joined_on."""
    team = Team.objects.create(name=name, tag=tag)
    players = []
    for i in range(1, size + 1):
        player = Player.objects.create(nickname=f"{tag.lower()}_p{i}")
        TeamMembership.objects.create(player=player, team=team, joined_on=joined_on)
        players.append(player)
    return team, players


def make_tournament(status: str = TournamentStatus.REGISTRATION) -> Tournament:
    organizer, _ = get_user_model().objects.get_or_create(username="test_organizer")
    return Tournament.objects.create(
        name="Test Cup",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 10),
        status=status,
        organizer=organizer,
    )


def register(tournament: Tournament, team: Team, players, on_date: date = REG_DATE):
    return register_team(tournament, team, [(p, "player") for p in players], on_date=on_date)
