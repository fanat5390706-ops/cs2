from django.test import SimpleTestCase

from core.management.commands.sync_faceit import map_stats


class FaceitMapsTests(SimpleTestCase):
    def test_segments_to_maps(self):
        segments = [
            {"label": "de_mirage", "type": "Map", "mode": "5v5",
             "stats": {"Matches": "40", "Win Rate %": "55", "Average K/D Ratio": "1.12", "Average Headshots %": "48"}},
            {"label": "de_nuke", "type": "Map", "mode": "5v5", "stats": {"Matches": "100", "Win Rate %": "60"}},
            {"label": "de_inferno", "type": "Map", "mode": "2v2", "stats": {"Matches": "5"}},
            {"label": "x", "type": "Overall", "stats": {"Matches": "9"}},
            {"label": "de_dust2", "type": "Map", "mode": "5v5", "stats": {"Matches": "0"}},
        ]
        result = map_stats(segments)
        self.assertEqual([r["map"] for r in result], ["Nuke", "Mirage"])  # по числу матчей, без чужих режимов и пустых
        self.assertEqual(result[1]["kd"], 1.12)
        self.assertEqual(map_stats(None), [])
