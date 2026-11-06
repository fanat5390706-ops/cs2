"""Планирование матчей и ввод результатов карт."""
from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count

from core.models import Player
from tournaments.models import Tournament, TournamentEntry

from .models import (
    GameMap,
    Match,
    MatchMap,
    MatchMapScore,
    MatchParticipant,
    MatchStatus,
    PlayerMapStat,
)


@dataclass
class PlayerStatInput:
    player: Player
    slot: int  # за какую сторону (1 или 2) играл игрок
    kills: int
    deaths: int
    assists: int
    headshot_kills: int
    damage: int
    rounds_played: int


@transaction.atomic
def schedule_match(
    tournament: Tournament,
    stage: str,
    scheduled_at: datetime,
    best_of: int,
    entry1: TournamentEntry,
    entry2: TournamentEntry,
) -> Match:
    """Создаёт матч и две его стороны одной транзакцией."""
    if entry1.pk == entry2.pk:
        raise ValidationError("Команда не может играть сама с собой.")
    if entry1.tournament_id != tournament.pk or entry2.tournament_id != tournament.pk:
        raise ValidationError("Обе команды должны быть заявлены на турнир матча.")

    match = Match.objects.create(
        tournament=tournament, stage=stage, scheduled_at=scheduled_at, best_of=best_of
    )
    MatchParticipant.objects.create(match=match, entry=entry1, slot=1)
    MatchParticipant.objects.create(match=match, entry=entry2, slot=2)
    return match


def maps_won(match: Match) -> dict[int, int]:
    """Сколько карт выиграла каждая сторона (ключ — слот). Считается, а не хранится."""
    wins = {1: 0, 2: 0}
    for match_map in match.maps.prefetch_related("scores__participant"):
        scores = {s.participant.slot: s.rounds_won for s in match_map.scores.all()}
        if len(scores) == 2 and scores[1] != scores[2]:
            wins[1 if scores[1] > scores[2] else 2] += 1
    return wins


@transaction.atomic
def record_map(
    match: Match,
    game_map: GameMap,
    map_number: int,
    rounds_by_slot: dict[int, int],
    stats: list[PlayerStatInput],
    allow_finished: bool = False,
) -> MatchMap:
    """Вносит результат карты: счёт обеих сторон и статистику игроков одной транзакцией.

    Если любая проверка не пройдена, не сохраняется ничего.
    """
    # Блокируем матч: два организатора не внесут одну карту одновременно.
    match = Match.objects.select_for_update().get(pk=match.pk)

    # allow_finished — только для импорта статистики уже сыгранных матчей (CSV): статус матча не меняется.
    if match.status == MatchStatus.CANCELLED or (match.status == MatchStatus.FINISHED and not allow_finished):
        raise ValidationError("Матч отменён или уже завершён, менять карты нельзя.")
    if not 1 <= map_number <= match.best_of:
        raise ValidationError(f"Номер карты должен быть от 1 до {match.best_of} (BO{match.best_of}).")
    if set(rounds_by_slot) != {1, 2}:
        raise ValidationError("Нужно указать счёт обеих сторон (слоты 1 и 2).")
    if any(r < 0 for r in rounds_by_slot.values()):
        raise ValidationError("Число раундов не может быть отрицательным.")
    if rounds_by_slot[1] == rounds_by_slot[2]:
        raise ValidationError("Ничья на карте невозможна: у карты должен быть победитель.")

    wins = maps_won(match)
    need = match.best_of // 2 + 1
    if max(wins.values()) >= need and not allow_finished:
        raise ValidationError("Серия уже решена: одна из сторон набрала нужное число карт.")

    participants = {p.slot: p for p in match.participants.select_related("entry")}
    if set(participants) != {1, 2}:
        raise ValidationError("У матча должно быть две стороны.")

    total_rounds = sum(rounds_by_slot.values())
    seen_players = set()
    for s in stats:
        if s.slot not in participants:
            raise ValidationError("Слот игрока должен быть 1 или 2.")
        if s.player.pk in seen_players:
            raise ValidationError(f"Статистика игрока {s.player} указана дважды.")
        seen_players.add(s.player.pk)
        if not participants[s.slot].entry.roster.filter(player=s.player).exists():
            raise ValidationError(f"{s.player} не входит в состав команды на этот турнир.")
        if not 0 < s.rounds_played <= total_rounds:
            raise ValidationError(f"{s.player}: сыграно раундов должно быть от 1 до {total_rounds}.")
        if s.headshot_kills > s.kills:
            raise ValidationError(f"{s.player}: убийств в голову больше, чем убийств.")

    match_map = MatchMap.objects.create(match=match, game_map=game_map, map_number=map_number)
    for slot, rounds in rounds_by_slot.items():
        MatchMapScore.objects.create(
            match_map=match_map, participant=participants[slot], rounds_won=rounds
        )
    PlayerMapStat.objects.bulk_create(
        [
            PlayerMapStat(
                match_map=match_map,
                participant=participants[s.slot],
                player=s.player,
                kills=s.kills,
                deaths=s.deaths,
                assists=s.assists,
                headshot_kills=s.headshot_kills,
                damage=s.damage,
                rounds_played=s.rounds_played,
            )
            for s in stats
        ]
    )

    # Серия закончилась? Тогда помечаем матч завершённым.
    wins = maps_won(match)
    if allow_finished:
        pass
    elif max(wins.values()) >= need:
        match.status = MatchStatus.FINISHED
        match.save(update_fields=["status"])
    elif match.status == MatchStatus.SCHEDULED:
        match.status = MatchStatus.LIVE
        match.save(update_fields=["status"])

    return match_map
