"""SQL-представления для отчётов. Производные показатели считаются здесь, а не хранятся в таблицах."""
from django.db import migrations

SERIES_SCORE = """
CREATE OR REPLACE VIEW v_match_series_score AS
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
    CAST(COALESCE(SUM(CASE WHEN w.rounds1 > w.rounds2 THEN 1 ELSE 0 END), 0) AS SIGNED) AS maps_team1,
    CAST(COALESCE(SUM(CASE WHEN w.rounds2 > w.rounds1 THEN 1 ELSE 0 END), 0) AS SIGNED) AS maps_team2,
    CASE
        WHEN m.status = 'finished'
             AND SUM(CASE WHEN w.rounds1 > w.rounds2 THEN 1 ELSE 0 END)
               > SUM(CASE WHEN w.rounds2 > w.rounds1 THEN 1 ELSE 0 END) THEN e1.id
        WHEN m.status = 'finished'
             AND SUM(CASE WHEN w.rounds2 > w.rounds1 THEN 1 ELSE 0 END)
               > SUM(CASE WHEN w.rounds1 > w.rounds2 THEN 1 ELSE 0 END) THEN e2.id
        ELSE NULL
    END AS winner_entry_id
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
           MAX(CASE WHEN p.slot = 1 THEN s.rounds_won END) AS rounds1,
           MAX(CASE WHEN p.slot = 2 THEN s.rounds_won END) AS rounds2
    FROM match_map mm
    JOIN match_map_score s ON s.match_map_id = mm.id
    JOIN match_participant p ON p.id = s.participant_id
    GROUP BY mm.match_id, mm.id
) w ON w.match_id = m.id
GROUP BY m.id, m.tournament_id, m.stage, m.scheduled_at, m.best_of, m.status,
         e1.id, t1.name, t1.tag, e2.id, t2.name, t2.tag
"""

PLAYER_TOTALS = """
CREATE OR REPLACE VIEW v_player_totals AS
SELECT
    p.id AS player_id,
    p.nickname,
    COUNT(*) AS maps_played,
    CAST(SUM(s.kills) AS SIGNED) AS kills,
    CAST(SUM(s.deaths) AS SIGNED) AS deaths,
    CAST(SUM(s.assists) AS SIGNED) AS assists,
    CAST(SUM(s.headshot_kills) AS SIGNED) AS headshot_kills,
    CAST(SUM(s.damage) AS SIGNED) AS damage,
    CAST(SUM(s.rounds_played) AS SIGNED) AS rounds_played,
    ROUND(SUM(s.kills) / NULLIF(SUM(s.deaths), 0), 2) AS kd,
    ROUND(100 * SUM(s.headshot_kills) / NULLIF(SUM(s.kills), 0), 1) AS hs_percent,
    ROUND(SUM(s.damage) / NULLIF(SUM(s.rounds_played), 0), 1) AS adr
FROM player p
JOIN player_map_stat s ON s.player_id = p.id
GROUP BY p.id, p.nickname
"""

STANDINGS = """
CREATE OR REPLACE VIEW v_tournament_standings AS
SELECT
    e.tournament_id,
    e.id AS entry_id,
    t.name AS team,
    t.tag,
    COUNT(r.match_id) AS matches_played,
    CAST(COALESCE(SUM(CASE WHEN r.winner_entry_id = e.id THEN 1 ELSE 0 END), 0) AS SIGNED) AS wins,
    CAST(COALESCE(SUM(CASE WHEN r.winner_entry_id IS NOT NULL
                            AND r.winner_entry_id <> e.id THEN 1 ELSE 0 END), 0) AS SIGNED) AS losses
FROM tournament_entry e
JOIN team t ON t.id = e.team_id
LEFT JOIN v_match_series_score r
       ON r.status = 'finished'
      AND r.tournament_id = e.tournament_id
      AND (r.entry1_id = e.id OR r.entry2_id = e.id)
GROUP BY e.tournament_id, e.id, t.name, t.tag
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("tournaments", "0001_initial"),
        ("matches", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(SERIES_SCORE, reverse_sql="DROP VIEW IF EXISTS v_match_series_score"),
        migrations.RunSQL(PLAYER_TOTALS, reverse_sql="DROP VIEW IF EXISTS v_player_totals"),
        migrations.RunSQL(STANDINGS, reverse_sql="DROP VIEW IF EXISTS v_tournament_standings"),
    ]
