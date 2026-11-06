from django.conf import settings
from django.db import models
from django.db.models import Case, F, Q, When


class Player(models.Model):
    """Игрок. Не хранит текущую команду: она определяется историей членства."""

    nickname = models.CharField("Никнейм", max_length=50, unique=True)
    first_name = models.CharField("Имя", max_length=100, blank=True)
    last_name = models.CharField("Фамилия", max_length=100, blank=True)
    country = models.CharField("Страна (ISO-2)", max_length=2, blank=True)
    # NULL допустим: UNIQUE в MySQL разрешает несколько NULL.
    steam_id64 = models.CharField(
        "SteamID64", max_length=17, unique=True, null=True, blank=True
    )

    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    photo_url = models.URLField("Фото", max_length=500, blank=True)
    pandascore_id = models.BigIntegerField("ID в PandaScore", null=True, blank=True, unique=True)
    # Заполняются командой sync_steam (Steam Web API).
    avatar_url = models.URLField("Аватар", max_length=500, blank=True)
    steam_profile_url = models.URLField("Профиль Steam", max_length=300, blank=True)
    vac_banned = models.BooleanField("VAC-бан", null=True, blank=True)  # NULL = неизвестно
    steam_synced_at = models.DateTimeField("Steam обновлён", null=True, blank=True)

    # Заполняются командой sync_liquipedia (Liquipedia, лицензия CC-BY-SA 3.0).
    liquipedia_page = models.CharField("Страница Liquipedia", max_length=100, blank=True)
    liquipedia_synced_at = models.DateTimeField("Liquipedia обновлена", null=True, blank=True)
    # FACEIT: faceit_nickname вносится вручную (иначе поиск по SteamID64); остальное — sync_faceit.
    faceit_nickname = models.CharField("Ник на FACEIT", max_length=50, blank=True)
    faceit_player_id = models.CharField("FACEIT player_id", max_length=40, unique=True, null=True, blank=True)
    faceit_elo = models.PositiveIntegerField("FACEIT ELO", null=True, blank=True)
    faceit_level = models.PositiveSmallIntegerField("FACEIT уровень", null=True, blank=True)
    faceit_matches = models.PositiveIntegerField("FACEIT матчей", null=True, blank=True)
    faceit_win_rate = models.PositiveSmallIntegerField("FACEIT винрейт, %", null=True, blank=True)
    faceit_kd = models.DecimalField("FACEIT средний K/D", max_digits=4, decimal_places=2, null=True, blank=True)
    faceit_hs = models.PositiveSmallIntegerField("FACEIT средний HS%", null=True, blank=True)
    # Статистика по картам из FACEIT: [{"map": "Mirage", "matches": 40, "win_rate": 55, "kd": 1.12, "hs": 48}, ...]
    faceit_maps = models.JSONField("FACEIT по картам", default=list, blank=True)
    faceit_synced_at = models.DateTimeField("FACEIT обновлён", null=True, blank=True)

    # Игровая роль (PandaScore): нужна для фильтров «AWPer / Rifler / IGL ...» на странице игроков.
    role = models.CharField("Роль", max_length=30, blank=True)
    # null=True: у строк, созданных до появления поля, даты неизвестны (так миграция проходит без запроса значения).
    created_at = models.DateTimeField("Создан", auto_now_add=True, null=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True, null=True)

    class Meta:
        db_table = "player"
        ordering = ["nickname"]
        verbose_name = "игрок"
        verbose_name_plural = "игроки"

    def __str__(self):
        return self.nickname


class Team(models.Model):
    name = models.CharField("Название", max_length=100, unique=True)
    tag = models.CharField("Тег", max_length=10, unique=True)
    country = models.CharField("Страна (ISO-2)", max_length=2, blank=True)
    logo_url = models.URLField("Логотип", max_length=500, blank=True)
    # Соцсети и сайт: заполняются вручную в админке (в бесплатных API их нет).
    website = models.URLField("Сайт", max_length=300, blank=True)
    twitter_url = models.URLField("Twitter/X", max_length=300, blank=True)
    youtube_url = models.URLField("YouTube", max_length=300, blank=True)
    twitch_url = models.URLField("Twitch", max_length=300, blank=True)
    founded_year = models.PositiveSmallIntegerField("Год основания", null=True, blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True, null=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True, null=True)

    class Meta:
        db_table = "team"
        ordering = ["name"]
        verbose_name = "команда"
        verbose_name_plural = "команды"

    def __str__(self):
        return f"{self.name} ({self.tag})"


class MembershipRole(models.TextChoices):
    PLAYER = "player", "Игрок"
    SUBSTITUTE = "substitute", "Запасной"
    COACH = "coach", "Тренер"


class TeamMembership(models.Model):
    """История составов: один период пребывания игрока в команде.

    left_on = NULL означает, что игрок состоит в команде сейчас.
    """

    player = models.ForeignKey(
        Player, on_delete=models.PROTECT, related_name="memberships", verbose_name="Игрок"
    )
    team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="memberships", verbose_name="Команда"
    )
    role = models.CharField(
        "Роль", max_length=20, choices=MembershipRole.choices, default=MembershipRole.PLAYER
    )
    joined_on = models.DateField("Вступил")
    left_on = models.DateField("Покинул", null=True, blank=True)

    # MySQL не поддерживает частичные уникальные индексы, поэтому "не более одной
    # открытой записи у игрока" моделируем генерируемым столбцом:
    # player_id, пока left_on IS NULL, иначе NULL (а UNIQUE допускает много NULL).
    open_player_key = models.GeneratedField(
        expression=Case(
            When(left_on__isnull=True, then=F("player_id")),
            default=None,
            output_field=models.BigIntegerField(null=True),
        ),
        output_field=models.BigIntegerField(null=True),
        db_persist=True,
    )

    class Meta:
        db_table = "team_membership"
        ordering = ["-joined_on"]
        verbose_name = "членство в команде"
        verbose_name_plural = "история составов"
        indexes = [
            models.Index(fields=["player", "joined_on"], name="ix_membership_player_joined"),
            models.Index(fields=["team", "joined_on"], name="ix_membership_team_joined"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(left_on__isnull=True) | Q(left_on__gte=F("joined_on")),
                name="ck_membership_period",
            ),
            models.UniqueConstraint(
                fields=["open_player_key"], name="uq_membership_one_open_per_player"
            ),
        ]

    def __str__(self):
        end = self.left_on or "н.в."
        return f"{self.player} → {self.team}: {self.joined_on} — {end}"


class TeamRanking(models.Model):
    """Позиция команды в рейтинге на дату. Рейтинг — история, а не поле Team.ranking:
    так видно динамику, и одна команда может иметь места в разных рейтингах (source)."""

    # team пустой, если команды из рейтинга нет у нас в БД: тогда название хранится в team_name
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.CASCADE, related_name="rankings", verbose_name="Команда")
    team_name = models.CharField("Название в рейтинге", max_length=100, blank=True)
    roster = models.CharField("Состав в рейтинге", max_length=200, blank=True)
    source = models.CharField("Рейтинг", max_length=30, default="vrs")  # vrs — Valve Regional Standings
    valid_on = models.DateField("На дату")
    position = models.PositiveSmallIntegerField("Место")
    points = models.PositiveIntegerField("Очки", default=0)

    class Meta:
        db_table = "team_ranking"
        ordering = ["source", "valid_on", "position"]
        verbose_name = "место в рейтинге"
        verbose_name_plural = "рейтинг команд"
        constraints = [
            models.UniqueConstraint(fields=["team", "source", "valid_on"], name="uq_ranking_team_source_date"),
            models.UniqueConstraint(fields=["source", "valid_on", "position"], name="uq_ranking_source_date_pos"),
        ]
        indexes = [models.Index(fields=["source", "valid_on", "position"], name="ix_ranking_lookup")]

    def __str__(self):
        return f"#{self.position} {self.team or self.team_name} ({self.source}, {self.valid_on})"


class FavoriteTeam(models.Model):
    """Избранная команда пользователя («Add to favorites»)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_teams")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "favorite_team"
        verbose_name = "избранная команда"
        verbose_name_plural = "избранные команды"
        constraints = [models.UniqueConstraint(fields=["user", "team"], name="uq_favorite_user_team")]

    def __str__(self):
        return f"{self.user} ♥ {self.team}"
