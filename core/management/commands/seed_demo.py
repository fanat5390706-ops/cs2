"""Заполнение базы вымышленными демо-данными: python manage.py seed_demo [--reset]

Все команды, игроки и результаты вымышлены; совпадения с реальными людьми случайны.
Данные создаются теми же сервисами, что и ручной ввод, поэтому проходят все проверки.
"""
import random
from datetime import date, datetime, timedelta, timezone
from itertools import combinations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import MembershipRole, Player, Team, TeamMembership
from core.services import transfer_player
from matches.models import GameMap, Match, MatchMap, MatchMapScore, PlayerMapStat
from matches.services import PlayerStatInput, record_map, schedule_match
from tournaments.models import (
    Tournament,
    TournamentEntry,
    TournamentRosterPlayer,
    TournamentStatus,
)
from tournaments.services import register_team

MAPS = ["Mirage", "Nuke", "Inferno", "Ancient", "Anubis", "Dust2", "Overpass"]

# (название, тег, страна, [пять основных + один запасной])
TEAMS = [
    ("Northern Lights", "NL", "FI", ["frostbyte", "vexel", "korvin", "talyn", "brisk", "lumio"]),
    ("Red Foxes", "RF", "PL", ["emberfox", "quillon", "sable", "torvic", "nyxo", "ravi"]),
    ("Iron Wolves", "IW", "DE", ["grimlock", "dravik", "steelhand", "ironpaw", "havok7", "brann"]),
    ("Blue Comets", "BC", "SE", ["nebulon", "zyra", "cometa", "orbitz", "lyrr", "solis"]),
    ("Steel Ravens", "SR", "UA", ["ravenzo", "korax", "vulkan", "mirra", "blackwing", "zorya"]),
    ("Golden Bears", "GB", "LT", ["kodiak", "honeyb", "grizz", "tundra", "bruin", "taiga"]),
    ("Night Owls", "NO", "DK", ["hootie", "nightjar", "mothra", "ulric", "vesper", "dusky"]),
    ("Storm Riders", "ST", "BY", ["tempest", "galeon", "squall", "nimbus", "rafale", "gale"]),
]

OTHER_COUNTRIES = ["NO", "CZ", "LV", "EE", "KZ", "ES"]


def utc(y, m, d, h=12):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


class Command(BaseCommand):
    help = "Создаёт вымышленные команды, игроков, два турнира, матчи и статистику."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Удалить игроков, команды, турниры и матчи и создать демо-данные заново.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self.reset()
        if Player.objects.exists():
            raise CommandError("В базе уже есть игроки. Запустите с флагом --reset, чтобы заменить их.")
        organizer = get_user_model().objects.filter(is_superuser=True).first()
        if organizer is None:
            raise CommandError("Сначала создайте администратора: python manage.py createsuperuser")

        self.rng = random.Random(2026)
        self.maps = [GameMap.objects.get_or_create(name=n)[0] for n in MAPS]
        self.skill = {}
        self.teams = {}
        self.build_teams()

        self.tournament_one(organizer)
        # Перевод игрока между турнирами: в первом турнире он играл за RF, во втором за SR.
        quillon = Player.objects.get(nickname="quillon")
        transfer_player(quillon, self.teams["SR"], date(2026, 4, 1))
        self.tournament_two(organizer)

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: {Team.objects.count()} команд, {Player.objects.count()} игроков, "
                f"{Tournament.objects.count()} турнира, {Match.objects.count()} матчей, "
                f"{MatchMap.objects.count()} карт."
            )
        )

    # ------------------------------------------------------------------
    def reset(self):
        for model in (
            PlayerMapStat, MatchMapScore, MatchMap, Match,
            TournamentRosterPlayer, TournamentEntry, Tournament,
            TeamMembership, Player, Team,
        ):
            model.objects.all().delete()

    def build_teams(self):
        for name, tag, country, nicknames in TEAMS:
            team = Team.objects.create(name=name, tag=tag, country=country)
            self.teams[tag] = team
            for index, nick in enumerate(nicknames):
                player_country = country if self.rng.random() < 0.75 else self.rng.choice(OTHER_COUNTRIES)
                player = Player.objects.create(nickname=nick, country=player_country)
                self.skill[player.pk] = self.rng.uniform(0.85, 1.2)
                TeamMembership.objects.create(
                    player=player,
                    team=team,
                    role=MembershipRole.PLAYER if index < 5 else MembershipRole.SUBSTITUTE,
                    joined_on=date(2026, 1, 1),
                )

    def roster_on(self, team, on_date):
        members = (
            TeamMembership.objects.filter(team=team, joined_on__lte=on_date)
            .exclude(left_on__lte=on_date)
            .select_related("player")
            .order_by("role", "id")
        )
        return [(m.player, "player" if i < 5 else "substitute") for i, m in enumerate(members)]

    def register(self, tournament, tags, on_date):
        entries, fives = {}, {}
        for tag in tags:
            roster = self.roster_on(self.teams[tag], on_date)
            entries[tag] = register_team(tournament, self.teams[tag], roster, on_date=on_date)
            fives[tag] = [p for p, role in roster if role == "player"]
        return entries, fives

    # ------------------------------------------------------------------
    def strength(self, players):
        return sum(self.skill[p.pk] for p in players) / len(players)

    def make_stats(self, players, slot, rounds, won):
        rng, out = self.rng, []
        for p in players:
            s = self.skill[p.pk] * (1.06 if won else 0.94)
            kills = max(0, round(rounds * rng.uniform(0.5, 0.8) * s))
            out.append(
                PlayerStatInput(
                    player=p,
                    slot=slot,
                    kills=kills,
                    deaths=max(1, round(rounds * rng.uniform(0.55, 0.8) / s)),
                    assists=round(rounds * rng.uniform(0.08, 0.25)),
                    headshot_kills=min(kills, round(kills * rng.uniform(0.3, 0.6))),
                    damage=round(rounds * rng.uniform(55, 80) * s),
                    rounds_played=rounds,
                )
            )
        return out

    def play(self, match, five1, five2, best_of, max_maps=None):
        """Разыгрывает серию карта за картой через сервис record_map. Возвращает победы сторон."""
        rng = self.rng
        need = best_of // 2 + 1
        p1 = self.strength(five1) / (self.strength(five1) + self.strength(five2))
        pool = rng.sample(self.maps, best_of)
        wins, number = [0, 0], 0
        while max(wins) < need and (max_maps is None or number < max_maps):
            winner = 0 if rng.random() < p1 else 1
            if rng.random() < 0.12:
                win_rounds, lose_rounds = 16, 14
            else:
                win_rounds, lose_rounds = 13, rng.randint(3, 11)
            r1, r2 = (win_rounds, lose_rounds) if winner == 0 else (lose_rounds, win_rounds)
            total = r1 + r2
            stats = self.make_stats(five1, 1, total, winner == 0) + self.make_stats(
                five2, 2, total, winner == 1
            )
            number += 1
            record_map(match, pool[number - 1], number, {1: r1, 2: r2}, stats)
            wins[winner] += 1
        return wins

    # ------------------------------------------------------------------
    def tournament_one(self, organizer):
        """Завершённый турнир: круговой этап BO3 и финал BO5."""
        tournament = Tournament.objects.create(
            name="Minsk Spring Cup 2026",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 10),
            status=TournamentStatus.REGISTRATION,
            organizer=organizer,
        )
        tags = ["NL", "RF", "IW", "BC"]
        entries, fives = self.register(tournament, tags, date(2026, 1, 20))
        tournament.status = TournamentStatus.ONGOING
        tournament.save(update_fields=["status"])

        points = {t: 0 for t in tags}
        for i, (a, b) in enumerate(combinations(tags, 2)):
            match = schedule_match(
                tournament, "Групповой этап",
                utc(2026, 2, 2 + i // 2, 12 + 3 * (i % 2)), 3, entries[a], entries[b],
            )
            wins = self.play(match, fives[a], fives[b], 3)
            points[a if wins[0] > wins[1] else b] += 1

        ranked = sorted(tags, key=lambda t: (-points[t], -self.strength(fives[t])))
        a, b = ranked[0], ranked[1]
        final = schedule_match(tournament, "Финал", utc(2026, 2, 10, 15), 5, entries[a], entries[b])
        self.play(final, fives[a], fives[b], 5)

        tournament.status = TournamentStatus.FINISHED
        tournament.save(update_fields=["status"])

    def tournament_two(self, organizer):
        """Идущий турнир: сыгранные, текущий и будущие матчи."""
        tournament = Tournament.objects.create(
            name="Winter Masters 2026",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 20),
            status=TournamentStatus.REGISTRATION,
            organizer=organizer,
        )
        tags = ["RF", "NL", "SR", "GB", "NO", "ST"]
        entries, fives = self.register(tournament, tags, date(2026, 10, 20))
        tournament.status = TournamentStatus.ONGOING
        tournament.save(update_fields=["status"])

        def match(a, b, best_of, when, stage="Групповой этап"):
            return schedule_match(tournament, stage, when, best_of, entries[a], entries[b])

        for a, b, when in [
            ("SR", "GB", utc(2026, 11, 1, 12)),
            ("NO", "ST", utc(2026, 11, 1, 15)),
            ("RF", "NL", utc(2026, 11, 2, 12)),
        ]:
            self.play(match(a, b, 3, when), fives[a], fives[b], 3)

        # Матч в процессе: сыграна одна карта из трёх.
        live = match("SR", "NO", 3, utc(2026, 11, 3, 12))
        self.play(live, fives["SR"], fives["NO"], 3, max_maps=1)

        match("GB", "RF", 3, utc(2026, 11, 5, 12))
        match("ST", "NL", 1, utc(2026, 11, 5, 15))
        match("SR", "RF", 3, utc(2026, 11, 6, 12))
