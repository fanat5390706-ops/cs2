"""Представление счёта серии учитывает итог из импорта, если карты не внесены."""
import importlib

from django.db import migrations

NEW_SERIES_SCORE = """
CREATE OR REPLACE VIEW v_match_series_score AS
SELECT
    s.*,
    CASE
        WHEN s.status = 'finished' AND s.maps_team1 > s.maps_team2 THEN s.entry1_id
        WHEN s.status = 'finished' AND s.maps_team2 > s.maps_team1 THEN s.entry2_id
        ELSE NULL
    END AS winner_entry_id
FROM (
    SELECT
        m.id AS match_id,
        m.tournament_id,
        m.stage,
        m.scheduled_at,
        m.best_of,
        m.status,
        e1.id AS entry1_id,
        t1.name AS team1,
        t1.tag AS tag1,
        e2.id AS entry2_id,
        t2.name AS team2,
        t2.tag AS tag2,
        CASE WHEN COUNT(w.match_map_id) > 0
             THEN CAST(COALESCE(SUM(CASE WHEN w.rounds1 > w.rounds2 THEN 1 ELSE 0 END), 0) AS SIGNED)
             ELSE CAST(COALESCE(m.score_team1, 0) AS SIGNED) END AS maps_team1,
        CASE WHEN COUNT(w.match_map_id) > 0
             THEN CAST(COALESCE(SUM(CASE WHEN w.rounds2 > w.rounds1 THEN 1 ELSE 0 END), 0) AS SIGNED)
             ELSE CAST(COALESCE(m.score_team2, 0) AS SIGNED) END AS maps_team2
    FROM game_match m
    JOIN match_participant mp1 ON mp1.match_id = m.id AND mp1.slot = 1
    JOIN tournament_entry e1 ON e1.id = mp1.entry_id
    JOIN team t1 ON t1.id = e1.team_id
    JOIN match_participant mp2 ON mp2.match_id = m.id AND mp2.slot = 2
    JOIN tournament_entry e2 ON e2.id = mp2.entry_id
    JOIN team t2 ON t2.id = e2.team_id
    LEFT JOIN (
        SELECT mm.match_id,
               mm.id AS match_map_id,
               MAX(CASE WHEN p.slot = 1 THEN sc.rounds_won END) AS rounds1,
               MAX(CASE WHEN p.slot = 2 THEN sc.rounds_won END) AS rounds2
        FROM match_map mm
        JOIN match_map_score sc ON sc.match_map_id = mm.id
        JOIN match_participant p ON p.id = sc.participant_id
        GROUP BY mm.match_id, mm.id
    ) w ON w.match_id = m.id
    GROUP BY m.id, m.tournament_id, m.stage, m.scheduled_at, m.best_of, m.status,
             m.score_team1, m.score_team2, e1.id, t1.name, t1.tag, e2.id, t2.name, t2.tag
) s
"""

OLD_SERIES_SCORE = importlib.import_module("matches.migrations.0002_reporting_views").SERIES_SCORE


class Migration(migrations.Migration):
    dependencies = [("matches", "0003_match_external_scores")]

    operations = [migrations.RunSQL(NEW_SERIES_SCORE, reverse_sql=OLD_SERIES_SCORE)]
