from datetime import datetime, timezone

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.testing import make_team, make_tournament, register
from matches.models import GameMap, MatchMap, MatchMapScore, MatchStatus, PlayerMapStat
from matches.services import PlayerStatInput, maps_won, record_map, schedule_match


def stat(player, slot, kills=20, deaths=10, hs=8, rounds=20):
    return PlayerStatInput(
        player=player,
        slot=slot,
        kills=kills,
        deaths=deaths,
        assists=5,
        headshot_kills=hs,
        damage=kills * 85,
        rounds_played=rounds,
    )


class MatchTestBase(TestCase):
    def setUp(self):
        self.tournament = make_tournament()
        self.team_a, self.players_a = make_team("Alpha", "AAA")
        self.team_b, self.players_b = make_team("Beta", "BBB")
        self.entry_a = register(self.tournament, self.team_a, self.players_a)
        self.entry_b = register(self.tournament, self.team_b, self.players_b)
        self.maps = [GameMap.objects.create(name=n) for n in ("Mirage", "Nuke", "Inferno")]

    def new_match(self, best_of=3):
        return schedule_match(
            self.tournament,
            "Group A",
            datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc),
            best_of,
            self.entry_a,
            self.entry_b,
        )


class ScheduleMatchTests(MatchTestBase):
    def test_creates_match_with_two_participants(self):
        match = self.new_match()
        self.assertEqual(match.participants.count(), 2)
        self.assertEqual(match.status, MatchStatus.SCHEDULED)

    def test_team_cannot_play_itself(self):
        with self.assertRaises(ValidationError):
            schedule_match(
                self.tournament,
                "Group A",
                datetime(2026, 3, 2, tzinfo=timezone.utc),
                3,
                self.entry_a,
                self.entry_a,
            )

    def test_invalid_best_of_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.new_match(best_of=2)


class RecordMapTests(MatchTestBase):
    def test_record_map_saves_scores_and_stats(self):
        match = self.new_match()
        stats = [stat(p, 1) for p in self.players_a] + [stat(p, 2) for p in self.players_b]

        record_map(match, self.maps[0], 1, {1: 13, 2: 7}, stats)

        self.assertEqual(MatchMapScore.objects.count(), 2)
        self.assertEqual(PlayerMapStat.objects.count(), 10)
        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.LIVE)
        self.assertEqual(maps_won(match), {1: 1, 2: 0})

    def test_series_finishes_and_rejects_extra_map(self):
        match = self.new_match(best_of=3)
        record_map(match, self.maps[0], 1, {1: 13, 2: 7}, [])
        record_map(match, self.maps[1], 2, {1: 13, 2: 5}, [])

        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.FINISHED)
        with self.assertRaises(ValidationError):
            record_map(match, self.maps[2], 3, {1: 13, 2: 9}, [])

    def test_map_number_above_best_of_rejected(self):
        match = self.new_match(best_of=1)
        with self.assertRaises(ValidationError):
            record_map(match, self.maps[0], 2, {1: 13, 2: 7}, [])

    def test_draw_rejected(self):
        match = self.new_match()
        with self.assertRaises(ValidationError):
            record_map(match, self.maps[0], 1, {1: 12, 2: 12}, [])

    def test_player_outside_roster_rejected(self):
        match = self.new_match()
        _, outsiders = make_team("Gamma", "GGG")
        with self.assertRaises(ValidationError):
            record_map(match, self.maps[0], 1, {1: 13, 2: 7}, [stat(outsiders[0], 1)])

    def test_failed_validation_saves_nothing(self):
        match = self.new_match()
        bad = [stat(self.players_a[0], 1), stat(self.players_a[1], 1, kills=5, hs=9)]
        with self.assertRaises(ValidationError):
            record_map(match, self.maps[0], 1, {1: 13, 2: 7}, bad)
        self.assertEqual(MatchMap.objects.count(), 0)
        self.assertEqual(PlayerMapStat.objects.count(), 0)


class StatConstraintTests(MatchTestBase):
    def test_headshots_above_kills_rejected_by_database(self):
        match = self.new_match()
        record_map(match, self.maps[0], 1, {1: 13, 2: 7}, [])
        match_map = match.maps.get()
        participant = match.participants.get(slot=1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            PlayerMapStat.objects.create(
                match_map=match_map,
                participant=participant,
                player=self.players_a[0],
                kills=5,
                headshot_kills=6,
                rounds_played=20,
            )

    def test_same_map_twice_in_match_rejected_by_database(self):
        match = self.new_match()
        record_map(match, self.maps[0], 1, {1: 13, 2: 7}, [])
        with self.assertRaises(IntegrityError), transaction.atomic():
            MatchMap.objects.create(match=match, game_map=self.maps[0], map_number=2)
