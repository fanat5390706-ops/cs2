from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Player, Team, TeamMembership
from core.services import is_member_on, transfer_player
from core.testing import make_team


class TransferPlayerTests(TestCase):
    def setUp(self):
        self.team_a, self.players = make_team("Alpha", "AAA")
        self.team_b = Team.objects.create(name="Beta", tag="BBB")
        self.player = self.players[0]

    def test_transfer_closes_old_and_opens_new_membership(self):
        transfer_player(self.player, self.team_b, date(2026, 3, 1))

        old = TeamMembership.objects.get(player=self.player, team=self.team_a)
        new = TeamMembership.objects.get(player=self.player, team=self.team_b)
        self.assertEqual(old.left_on, date(2026, 3, 1))
        self.assertIsNone(new.left_on)
        self.assertEqual(TeamMembership.objects.filter(player=self.player).count(), 2)

    def test_history_is_preserved(self):
        transfer_player(self.player, self.team_b, date(2026, 3, 1))

        self.assertTrue(is_member_on(self.player, self.team_a, date(2026, 2, 1)))
        self.assertFalse(is_member_on(self.player, self.team_a, date(2026, 4, 1)))
        self.assertTrue(is_member_on(self.player, self.team_b, date(2026, 4, 1)))

    def test_transfer_to_same_team_rejected(self):
        with self.assertRaises(ValidationError):
            transfer_player(self.player, self.team_a, date(2026, 3, 1))

    def test_transfer_before_joining_rejected(self):
        with self.assertRaises(ValidationError):
            transfer_player(self.player, self.team_b, date(2025, 12, 1))


class MembershipConstraintTests(TestCase):
    """Проверка ограничений уровня БД (CHECK / UNIQUE на генерируемом столбце)."""

    def setUp(self):
        self.team_a, self.players = make_team("Alpha", "AAA")
        self.team_b = Team.objects.create(name="Beta", tag="BBB")

    def test_only_one_open_membership_per_player(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMembership.objects.create(
                player=self.players[0], team=self.team_b, joined_on=date(2026, 2, 1)
            )

    def test_left_on_before_joined_on_rejected(self):
        player = Player.objects.create(nickname="newbie")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMembership.objects.create(
                player=player,
                team=self.team_a,
                joined_on=date(2026, 5, 1),
                left_on=date(2026, 4, 1),
            )

    def test_duplicate_nickname_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Player.objects.create(nickname=self.players[0].nickname)
