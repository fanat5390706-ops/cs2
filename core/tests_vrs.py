from datetime import date

from django.test import SimpleTestCase

from core.management.commands.sync_vrs import latest_file, normalize, parse_standings

SAMPLE = """### Standings as of 2026_11_02<br />

| Standing | Points | Team Name            | Roster                                               |      |
| :- | -: | :- | :- | :- |
| 1        |   1960 | MOUZ                 | PR, Spinx, torzsi, xelex, xertioN                    | [details](details/x.md) |
| 13       |   1589 | Natus Vincere        | Aleksib, b1t, iM, makazze, w0nderful                 | [details](details/y.md) |
"""


class VrsParseTests(SimpleTestCase):
    def test_parse_table(self):
        rows = parse_standings(SAMPLE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"position": 1, "points": 1960, "team": "MOUZ", "roster": "PR, Spinx, torzsi, xelex, xertioN"})
        self.assertEqual(rows[1]["team"], "Natus Vincere")

    def test_latest_file_and_normalize(self):
        files = [{"name": "standings_global_2026_10_05.md"}, {"name": "standings_global_2026_11_02.md"},
                 {"name": "standings_europe_2026_11_02.md"}, {"name": "readme.md"}]
        self.assertEqual(latest_file(files), ("standings_global_2026_11_02.md", date(2026, 11, 2)))
        self.assertEqual(normalize("Natus Vincere"), normalize("natus-vincere"))
