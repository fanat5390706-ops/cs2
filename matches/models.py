from django.db import models
from django.db.models import F, Q

from core.models import Player
from tournaments.models import Tournament, TournamentEntry


class GameMap(models.Model):
    """Справочник карт (Mirage, Nuke, ...). Не путать с сыгранной картой — MatchMap."""

    name = models.CharField("Название", max_length=50, unique=True)
    is_active = models.BooleanField("В текущем пуле", default=True)

    class Meta:
        db_table = "game_map"
        ordering = ["name"]
        verbose_name = "карта (справочник)"
        verbose_name_plural = "карты (справочник)"

    def __str__(self):
        return self.name


class MatchStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Запланирован"
    LIVE = "live", "Идёт"
    FINISHED = "finished", "Завершён"
    CANCELLED = "cancelled", "Отменён"


class BestOf(models.IntegerChoices):
    BO1 = 1, "BO1"
    BO3 = 3, "BO3"
    BO5 = 5, "BO5"


class Match(models.Model):
    """Матч как серия (BO1/BO3/BO5). Победитель и счёт серии не хранятся — считаются из карт."""

    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="matches", verbose_name="Турнир"
    )
    stage = models.CharField("Этап", max_length=100)
    scheduled_at = models.DateTimeField("Время начала")
    best_of = models.PositiveSmallIntegerField("Формат", choices=BestOf.choices)
    status = models.CharField(
        "Статус", max_length=20, choices=MatchStatus.choices, default=MatchStatus.SCHEDULED
    )

    # Данные импорта из PandaScore. Счёт серии по картам считается из MatchMapScore;
    # score_team1/2 используются только если карты не внесены (бесплатный тариф даёт лишь итог серии).
    external_id = models.BigIntegerField("ID в PandaScore", null=True, blank=True, unique=True)
    score_team1 = models.PositiveSmallIntegerField("Счёт серии, команда 1 (импорт)", null=True, blank=True)
    score_team2 = models.PositiveSmallIntegerField("Счёт серии, команда 2 (импорт)", null=True, blank=True)

    class Meta:
        # Имя "match" зарезервировано в MySQL (MATCH ... AGAINST), поэтому game_match.
        db_table = "game_match"
        ordering = ["scheduled_at"]
        verbose_name = "матч"
        verbose_name_plural = "матчи"
        indexes = [
            models.Index(fields=["tournament", "scheduled_at"], name="ix_match_tournament_time"),
            # главная, «Matches», «Results» и воркер sync_matches всегда фильтруют по статусу и сортируют по времени
            models.Index(fields=["status", "scheduled_at"], name="ix_match_status_time"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(best_of__in=[1, 3, 5]), name="ck_match_best_of"),
        ]

    def __str__(self):
        return f"{self.tournament}: {self.stage} (BO{self.best_of})"


class MatchParticipant(models.Model):
    """Одна из двух сторон матча (слот 1 или 2) — заявка команды на турнир."""

    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="participants", verbose_name="Матч"
    )
    entry = models.ForeignKey(
        TournamentEntry,
        on_delete=models.PROTECT,
        related_name="match_participations",
        verbose_name="Заявка",
    )
    slot = models.PositiveSmallIntegerField("Слот")

    class Meta:
        db_table = "match_participant"
        verbose_name = "участник матча"
        verbose_name_plural = "участники матча"
        constraints = [
            models.CheckConstraint(condition=Q(slot__in=[1, 2]), name="ck_participant_slot"),
            models.UniqueConstraint(fields=["match", "slot"], name="uq_participant_match_slot"),
            models.UniqueConstraint(fields=["match", "entry"], name="uq_participant_match_entry"),
        ]

    def __str__(self):
        return f"{self.entry.team.tag} (слот {self.slot}) — матч {self.match_id}"


class MatchMap(models.Model):
    """Сыгранная карта конкретного матча."""

    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="maps", verbose_name="Матч"
    )
    game_map = models.ForeignKey(
        GameMap, on_delete=models.PROTECT, related_name="played_maps", verbose_name="Карта"
    )
    map_number = models.PositiveSmallIntegerField("Номер карты в серии")

    class Meta:
        db_table = "match_map"
        ordering = ["match", "map_number"]
        verbose_name = "карта матча"
        verbose_name_plural = "карты матчей"
        constraints = [
            models.CheckConstraint(
                condition=Q(map_number__gte=1, map_number__lte=5), name="ck_match_map_number"
            ),
            models.UniqueConstraint(fields=["match", "map_number"], name="uq_match_map_number"),
            models.UniqueConstraint(fields=["match", "game_map"], name="uq_match_map_game_map"),
        ]

    def __str__(self):
        return f"Матч {self.match_id}, карта {self.map_number}: {self.game_map}"


class MatchMapScore(models.Model):
    """Раунды, выигранные стороной на карте. На карту — ровно две строки."""

    match_map = models.ForeignKey(
        MatchMap, on_delete=models.CASCADE, related_name="scores", verbose_name="Карта матча"
    )
    participant = models.ForeignKey(
        MatchParticipant,
        on_delete=models.PROTECT,
        related_name="map_scores",
        verbose_name="Сторона",
    )
    rounds_won = models.PositiveSmallIntegerField("Выиграно раундов")

    class Meta:
        db_table = "match_map_score"
        verbose_name = "счёт карты"
        verbose_name_plural = "счёт карт"
        constraints = [
            models.UniqueConstraint(
                fields=["match_map", "participant"], name="uq_score_map_participant"
            ),
        ]

    def __str__(self):
        return f"{self.participant}: {self.rounds_won}"


class PlayerMapStat(models.Model):
    """Исходная статистика игрока на карте. K/D, HS%, ADR считаются запросами."""

    match_map = models.ForeignKey(
        MatchMap, on_delete=models.CASCADE, related_name="player_stats", verbose_name="Карта матча"
    )
    participant = models.ForeignKey(
        MatchParticipant,
        on_delete=models.PROTECT,
        related_name="player_stats",
        verbose_name="Сторона",
    )
    player = models.ForeignKey(
        Player, on_delete=models.PROTECT, related_name="map_stats", verbose_name="Игрок"
    )
    kills = models.PositiveIntegerField("Убийства", default=0)
    deaths = models.PositiveIntegerField("Смерти", default=0)
    assists = models.PositiveIntegerField("Помощи", default=0)
    headshot_kills = models.PositiveIntegerField("Убийства в голову", default=0)
    damage = models.PositiveIntegerField("Урон", default=0)
    rounds_played = models.PositiveSmallIntegerField("Сыграно раундов")

    class Meta:
        db_table = "player_map_stat"
        verbose_name = "статистика игрока на карте"
        verbose_name_plural = "статистика игроков"
        constraints = [
            models.UniqueConstraint(fields=["match_map", "player"], name="uq_stat_map_player"),
            models.CheckConstraint(
                condition=Q(headshot_kills__lte=F("kills")), name="ck_stat_headshots_le_kills"
            ),
            models.CheckConstraint(condition=Q(rounds_played__gt=0), name="ck_stat_rounds_positive"),
        ]

    def __str__(self):
        return f"{self.player} — {self.match_map}"
