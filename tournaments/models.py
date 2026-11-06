from django.conf import settings
from django.db import models
from django.db.models import F, Q

from core.models import MembershipRole, Player, Team


class TournamentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    REGISTRATION = "registration", "Регистрация"
    ONGOING = "ongoing", "Идёт"
    FINISHED = "finished", "Завершён"


class Tournament(models.Model):
    name = models.CharField("Название", max_length=150)
    start_date = models.DateField("Дата начала")
    end_date = models.DateField("Дата окончания")
    status = models.CharField(
        "Статус", max_length=20, choices=TournamentStatus.choices, default=TournamentStatus.DRAFT
    )
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organized_tournaments",
        verbose_name="Организатор",
    )

    image_url = models.URLField("Логотип/баннер", max_length=500, blank=True)
    # Организатор-компания (ESL, BLAST, PGL) — отдельно от `organizer` (пользователь, внёсший запись).
    organizer_name = models.CharField("Организатор (компания)", max_length=100, blank=True)
    prize_pool_usd = models.PositiveBigIntegerField("Призовой фонд, USD", null=True, blank=True)
    location = models.CharField("Место проведения", max_length=150, blank=True)
    tier = models.CharField("Тир", max_length=1, blank=True, choices=[(c, c.upper()) for c in "sabcd"])

    class Meta:
        db_table = "tournament"
        ordering = ["-start_date"]
        verbose_name = "турнир"
        verbose_name_plural = "турниры"
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")), name="ck_tournament_dates"
            ),
        ]

    def __str__(self):
        return self.name


class TournamentEntry(models.Model):
    """Заявка команды на турнир."""

    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="entries", verbose_name="Турнир"
    )
    team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="entries", verbose_name="Команда"
    )

    class Meta:
        db_table = "tournament_entry"
        verbose_name = "заявка на турнир"
        verbose_name_plural = "заявки на турниры"
        constraints = [
            models.UniqueConstraint(fields=["tournament", "team"], name="uq_entry_tournament_team"),
        ]

    def __str__(self):
        return f"{self.team} @ {self.tournament}"


class TournamentRosterPlayer(models.Model):
    """Состав команды, зафиксированный на конкретный турнир (снимок на момент заявки)."""

    entry = models.ForeignKey(
        TournamentEntry, on_delete=models.CASCADE, related_name="roster", verbose_name="Заявка"
    )
    player = models.ForeignKey(
        Player, on_delete=models.PROTECT, related_name="roster_entries", verbose_name="Игрок"
    )
    role = models.CharField(
        "Роль на турнире",
        max_length=20,
        choices=MembershipRole.choices,
        default=MembershipRole.PLAYER,
    )

    class Meta:
        db_table = "tournament_roster_player"
        verbose_name = "игрок в составе на турнир"
        verbose_name_plural = "составы на турнир"
        constraints = [
            models.UniqueConstraint(fields=["entry", "player"], name="uq_roster_entry_player"),
        ]

    def __str__(self):
        return f"{self.player} ({self.entry})"


class FollowedTournament(models.Model):
    """Событие, на которое подписан пользователь (кнопка Follow)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="followed_tournaments")
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="followers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "followed_tournament"
        verbose_name = "подписка на событие"
        verbose_name_plural = "подписки на события"
        constraints = [models.UniqueConstraint(fields=["user", "tournament"], name="uq_follow_user_tournament")]

    def __str__(self):
        return f"{self.user} → {self.tournament}"
