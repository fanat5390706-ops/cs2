"""Регистрация команд на турнир и фиксация состава."""
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import MembershipRole, Player, Team
from core.services import is_member_on

from .models import Tournament, TournamentEntry, TournamentRosterPlayer, TournamentStatus

# Минимум игроков (не считая запасных и тренера) в заявке. Для CS2 — пять.
MIN_ACTIVE_PLAYERS = 5


@transaction.atomic
def register_team(
    tournament: Tournament,
    team: Team,
    roster: list[tuple[Player, str]],
    on_date: date | None = None,
) -> TournamentEntry:
    """Регистрирует команду на турнир вместе с зафиксированным составом.

    roster — список пар (игрок, роль на турнире). Состав сохраняется как снимок:
    последующие трансферы игроков на него не влияют.
    """
    on_date = on_date or date.today()
    # Блокируем турнир, чтобы статус не изменился посреди регистрации.
    tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)

    if tournament.status != TournamentStatus.REGISTRATION:
        raise ValidationError("Регистрация на этот турнир не открыта.")
    if TournamentEntry.objects.filter(tournament=tournament, team=team).exists():
        raise ValidationError("Команда уже зарегистрирована на этот турнир.")

    players = [p for p, _ in roster]
    if len({p.pk for p in players}) != len(players):
        raise ValidationError("Игрок указан в составе более одного раза.")

    active = sum(1 for _, role in roster if role == MembershipRole.PLAYER)
    if active < MIN_ACTIVE_PLAYERS:
        raise ValidationError(f"В составе должно быть не менее {MIN_ACTIVE_PLAYERS} игроков.")

    for player, _ in roster:
        if not is_member_on(player, team, on_date):
            raise ValidationError(f"{player} не состоит в команде {team} на {on_date}.")

    busy = (
        TournamentRosterPlayer.objects.filter(entry__tournament=tournament, player__in=players)
        .select_related("player")
        .first()
    )
    if busy:
        raise ValidationError(f"{busy.player} уже заявлен на этот турнир другой командой.")

    entry = TournamentEntry.objects.create(tournament=tournament, team=team)
    TournamentRosterPlayer.objects.bulk_create(
        [TournamentRosterPlayer(entry=entry, player=p, role=r) for p, r in roster]
    )
    return entry
