from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.management.commands.import_pandascore import Command
from core.models import Player, Team, TeamMembership


def team_data(team_id, name, players):
    return {"id": team_id, "name": name, "acronym": name[:3].upper(), "location": "PL", "image_url": "https://x/l.png",
            "players": [{"id": pid, "name": nick, "first_name": "F", "last_name": "L", "nationality": "PL",
                         "birthday": "2000-01-01", "image_url": "https://x/p.png"} for pid, nick in players]}


class ImportIdempotencyTests(TestCase):
    def run_import(self, teams):
        organizer, _ = get_user_model().objects.get_or_create(username="admin", defaults={"is_superuser": True})
        command = Command(stdout=StringIO())
        command.save_all(organizer, {}, [], {t["id"]: t for t in teams})

    def test_second_run_does_not_duplicate_players_or_memberships(self):
        teams = [team_data(1, "Alpha", [(10, "ann"), (11, "bob")])]
        self.run_import(teams)
        self.run_import(teams)
        self.assertEqual(Player.objects.count(), 2)
        self.assertEqual(TeamMembership.objects.count(), 2)

    def test_same_nickname_of_different_players_gets_suffix(self):
        self.run_import([team_data(1, "Alpha", [(10, "ann")]), team_data(2, "Beta", [(20, "ann")])])
        self.assertEqual(sorted(Player.objects.values_list("nickname", flat=True)), ["ann", "ann_2"])

    def test_transfer_closes_old_membership(self):
        self.run_import([team_data(1, "Alpha", [(10, "ann")]), team_data(2, "Beta", [(20, "bob")])])
        self.run_import([team_data(1, "Alpha", [(20, "bob")]), team_data(2, "Beta", [(10, "ann")])])
        ann = Player.objects.get(nickname="ann")
        self.assertEqual(Player.objects.count(), 2)
        self.assertEqual(ann.memberships.filter(left_on__isnull=True).get().team, Team.objects.get(name="Beta"))
        self.assertEqual(ann.memberships.filter(left_on__isnull=False).count(), 1)


class ParsePrizeTests(TestCase):
    def test_parse_prize(self):
        from core.management.commands.import_pandascore import parse_prize

        self.assertEqual(parse_prize("$1,000,000 United States Dollar"), 1000000)
        self.assertIsNone(parse_prize("500,000 Euro"))
        self.assertIsNone(parse_prize(None))


class EloTests(TestCase):
    def test_winner_gains_loser_drops_and_order_matters(self):
        from core.management.commands.compute_ranking import START, elo_ratings

        r = elo_ratings([("AAA", "BBB", 2, 0), ("AAA", "CCC", 1, 2), ("BBB", "CCC", 1, 1)])
        self.assertGreater(r["CCC"], r["AAA"])  # CCC обыграла AAA
        self.assertAlmostEqual(r["AAA"] + r["BBB"] + r["CCC"], 3 * START)  # Elo сохраняет сумму очков
        self.assertNotIn("DDD", r)

    def test_draw_is_ignored(self):
        from core.management.commands.compute_ranking import elo_ratings

        self.assertEqual(elo_ratings([("A", "B", 0, 0)]), {})
