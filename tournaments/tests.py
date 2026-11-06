from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Team
from core.services import transfer_player
from core.testing import make_team, make_tournament, register
from tournaments.models import TournamentEntry, TournamentRosterPlayer, TournamentStatus
from tournaments.services import register_team


class RegisterTeamTests(TestCase):
    def setUp(self):
        self.tournament = make_tournament()
        self.team, self.players = make_team("Alpha", "AAA")

    def test_register_saves_entry_and_roster_snapshot(self):
        entry = register(self.tournament, self.team, self.players)

        self.assertEqual(TournamentEntry.objects.filter(tournament=self.tournament).count(), 1)
        self.assertEqual(entry.roster.count(), 5)

    def test_roster_snapshot_survives_transfer(self):
        entry = register(self.tournament, self.team, self.players)
        other = Team.objects.create(name="Beta", tag="BBB")

        transfer_player(self.players[0], other, date(2026, 3, 5))

        self.assertTrue(
            TournamentRosterPlayer.objects.filter(entry=entry, player=self.players[0]).exists()
        )

    def test_too_few_players_rejected(self):
        with self.assertRaises(ValidationError):
            register(self.tournament, self.team, self.players[:4])

    def test_registration_closed_rejected(self):
        self.tournament.status = TournamentStatus.ONGOING
        self.tournament.save()
        with self.assertRaises(ValidationError):
            register(self.tournament, self.team, self.players)

    def test_duplicate_team_rejected(self):
        register(self.tournament, self.team, self.players)
        with self.assertRaises(ValidationError):
            register(self.tournament, self.team, self.players)

    def test_player_not_in_team_rejected(self):
        other_team, other_players = make_team("Beta", "BBB")
        mixed = self.players[:4] + [other_players[0]]
        with self.assertRaises(ValidationError):
            register(self.tournament, self.team, mixed)

    def test_player_cannot_play_for_two_teams_in_one_tournament(self):
        mover = self.players[0]
        register(self.tournament, self.team, self.players, on_date=date(2026, 2, 1))

        team_b, players_b = make_team("Beta", "BBB")
        transfer_player(mover, team_b, date(2026, 3, 1))

        with self.assertRaises(ValidationError):
            register_team(
                self.tournament,
                team_b,
                [(p, "player") for p in players_b[:4] + [mover]],
                on_date=date(2026, 4, 1),
            )
