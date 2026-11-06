"""Бизнес-операции над игроками и командами (сервисный слой)."""
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import MembershipRole, Player, Team, TeamMembership


def is_member_on(player: Player, team: Team, on_date: date) -> bool:
    """Состоял ли игрок в команде в указанную дату (период [joined_on, left_on))."""
    return (
        TeamMembership.objects.filter(player=player, team=team, joined_on__lte=on_date)
        .exclude(left_on__lte=on_date)
        .exists()
    )


@transaction.atomic
def transfer_player(
    player: Player, new_team: Team, on_date: date, role: str = MembershipRole.PLAYER
) -> TeamMembership:
    """Перевод игрока в другую команду.

    Закрывает текущую запись членства датой on_date и открывает новую.
    Старые записи и результаты матчей не меняются: история сохраняется.
    Всё выполняется в одной транзакции, а записи игрока блокируются
    (SELECT ... FOR UPDATE), чтобы два параллельных перевода не создали пересечение.
    """
    memberships = list(
        TeamMembership.objects.select_for_update().filter(player=player).order_by("joined_on")
    )
    current = next((m for m in memberships if m.left_on is None), None)

    if current is not None:
        if current.team_id == new_team.id:
            raise ValidationError("Игрок уже состоит в этой команде.")
        if on_date < current.joined_on:
            raise ValidationError("Дата перевода раньше даты вступления в текущую команду.")
        current.left_on = on_date
        current.save(update_fields=["left_on"])

    # Период [on_date, ∞) не должен пересекаться с другими записями игрока.
    overlap = (
        TeamMembership.objects.filter(player=player)
        .exclude(pk=current.pk if current else None)
        .filter(left_on__gt=on_date)
        .exists()
    )
    if overlap:
        raise ValidationError("Новый период пересекается с другим периодом игрока в команде.")

    return TeamMembership.objects.create(
        player=player, team=new_team, role=role, joined_on=on_date
    )
