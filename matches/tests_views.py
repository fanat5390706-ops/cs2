from django.db import connection

from matches.services import record_map
from matches.tests import MatchTestBase, stat


def query(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


class ReportingViewTests(MatchTestBase):
    def finish_series(self):
        match = self.new_match(best_of=3)
        stats = [stat(p, 1) for p in self.players_a] + [stat(p, 2) for p in self.players_b]
        record_map(match, self.maps[0], 1, {1: 13, 2: 7}, stats)
        record_map(match, self.maps[1], 2, {1: 13, 2: 5}, [])
        return match

    def test_series_score_and_winner(self):
        match = self.finish_series()
        row = query(
            "SELECT maps_team1, maps_team2, winner_entry_id, status "
            "FROM v_match_series_score WHERE match_id = %s",
            [match.pk],
        )[0]
        self.assertEqual((row["maps_team1"], row["maps_team2"]), (2, 0))
        self.assertEqual(row["winner_entry_id"], self.entry_a.pk)
        self.assertEqual(row["status"], "finished")

    def test_unfinished_series_has_no_winner(self):
        match = self.new_match(best_of=3)
        record_map(match, self.maps[0], 1, {1: 13, 2: 7}, [])
        row = query(
            "SELECT winner_entry_id FROM v_match_series_score WHERE match_id = %s", [match.pk]
        )[0]
        self.assertIsNone(row["winner_entry_id"])

    def test_standings(self):
        self.finish_series()
        rows = {
            r["entry_id"]: r
            for r in query(
                "SELECT * FROM v_tournament_standings WHERE tournament_id = %s",
                [self.tournament.pk],
            )
        }
        self.assertEqual(
            (rows[self.entry_a.pk]["matches_played"], rows[self.entry_a.pk]["wins"]), (1, 1)
        )
        self.assertEqual(
            (rows[self.entry_b.pk]["matches_played"], rows[self.entry_b.pk]["losses"]), (1, 1)
        )

    def test_player_totals_and_division_by_zero(self):
        match = self.new_match(best_of=3)
        normal, no_deaths = self.players_a[0], self.players_a[1]
        record_map(
            match,
            self.maps[0],
            1,
            {1: 13, 2: 7},
            [
                stat(normal, 1, kills=20, deaths=10, hs=8, rounds=20),
                stat(no_deaths, 1, kills=15, deaths=0, hs=5, rounds=20),
            ],
        )
        totals = {r["nickname"]: r for r in query("SELECT * FROM v_player_totals")}

        a = totals[normal.nickname]
        self.assertEqual(float(a["kd"]), 2.0)
        self.assertEqual(float(a["hs_percent"]), 40.0)
        self.assertEqual(float(a["adr"]), 85.0)  # 1700 урона / 20 раундов
        # Деление на ноль даёт NULL, а не ошибку.
        self.assertIsNone(totals[no_deaths.nickname]["kd"])
