# CS2 Esports Information System ("XLTV 2.0")

Educational, non-commercial information system for the Counter-Strike 2 esports scene:
matches, results, events, teams, players, rankings and statistics.
Built as a university course project. **Not monetized** (no ads, no paid features, no betting).

**Stack:** Django 5.2, MySQL 8, Django Templates, Bootstrap 5, Django Admin.

## Features
- Matches (live / upcoming) and results; teams ordered by strength tier (1–4) from the loaded ranking
- Match page: score, lineups, head-to-head, maps and per-player stats (when map data is loaded)
- Team and player profiles, events with tabs, stats tables (players / teams / maps)
- Background synchronisation of matches, news, videos and streams (`AUTO_WORKERS=1` or `run_workers`)
- Role-based access (viewer / organizer) with the Django Admin for data entry

## Data sources
| Source | Used for |
|---|---|
| [PandaScore](https://www.pandascore.co) (free plan) | teams, players, tournaments, series results and schedule |
| [Valve Regional Standings](https://github.com/ValveSoftware/counter-strike_regional_standings) | world team ranking |
| FACEIT Data API | player matchmaking stats and avatars (labelled as FACEIT, not tournament data) |
| Steam Web API | player profiles |
| [Liquipedia](https://liquipedia.net) (CC-BY-SA 3.0) | player biographies; map data when API access is granted |
| YouTube Data API, NewsAPI, Twitch | videos, news, streams (optional) |

Tournament per-map and per-player statistics are not available from free sources;
they can be loaded from CSV (`import_match_stats`, see `docs/examples/match_stats.csv`).
A ranking can be loaded from CSV too (`import_ranking`, see `docs/examples/ranking.csv`).

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # then fill in your own keys; never commit .env
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py import_pandascore
python manage.py sync_vrs
python manage.py runserver        # with AUTO_WORKERS=1 data updates in the background
python manage.py test
```

## Notes
- The project does not scrape HLTV and does not copy any third-party site's assets or code.
- Liquipedia and other sources are credited on the site; see the footer.
- Architecture and audit notes: `docs/ARCHITECTURE.md`, `docs/AUDIT.md`.

## License
MIT — see `LICENSE`.
