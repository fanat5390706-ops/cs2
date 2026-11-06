"""Мировой рейтинг команд — официальный Valve Regional Standings (VRS).

Данные публикует сама Valve в открытом репозитории
https://github.com/ValveSoftware/counter-strike_regional_standings (файлы live/<год>/standings_global_*.md).
Это настоящий рейтинг, а не наш расчёт. Ключ API не нужен.

    python manage.py sync_vrs
"""
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.http import get_json, get_text
from core.models import Team, TeamRanking

REPO = "ValveSoftware/counter-strike_regional_standings"
API = f"https://api.github.com/repos/{REPO}/contents/live/{{year}}"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/live/{{year}}/{{name}}"
SOURCE = "vrs"
FILE_RE = re.compile(r"standings_global_(\d{4})_(\d{2})_(\d{2})\.md$")


def parse_standings(text):
    """markdown-таблица -> [{'position', 'points', 'team', 'roster'}]."""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0].isdigit() and cells[1].isdigit():
            rows.append({"position": int(cells[0]), "points": int(cells[1]), "team": cells[2], "roster": cells[3]})
    return rows


def normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def latest_file(files):
    """Из списка файлов репозитория выбирает самый свежий standings_global_* -> (имя, дата)."""
    best = None
    for f in files:
        m = FILE_RE.search(f.get("name", ""))
        if m:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if not best or d > best[1]:
                best = (f["name"], d)
    return best


class Command(BaseCommand):
    help = "Загружает мировой рейтинг команд Valve (VRS) в team_ranking."

    def handle(self, *args, **options):
        found = None
        for year in (date.today().year, date.today().year - 1):
            files = get_json(API.format(year=year), None, {"Accept": "application/vnd.github+json", "User-Agent": "khltv-student-project"})
            if isinstance(files, list) and (found := latest_file(files)):
                found = (*found, year)
                break
        if not found:
            raise CommandError("Не удалось найти файл рейтинга в репозитории Valve.")
        name, valid_on, year = found
        text = get_text(RAW.format(year=year, name=name), {"User-Agent": "khltv-student-project"})
        rows = parse_standings(text or "")
        if not rows:
            raise CommandError(f"В файле {name} не найдена таблица рейтинга.")

        by_name = {}
        for team in Team.objects.all():
            by_name.setdefault(normalize(team.name), team)
        with transaction.atomic():
            TeamRanking.objects.filter(source=SOURCE, valid_on=valid_on).delete()
            objs, matched, used = [], 0, set()
            for r in rows:
                team = by_name.get(normalize(r["team"]))
                if team and team.pk in used:  # одна команда — одна строка рейтинга
                    team = None
                if team:
                    used.add(team.pk)
                    matched += 1
                objs.append(TeamRanking(team=team, team_name=r["team"][:100], roster=r["roster"][:200], source=SOURCE,
                                        valid_on=valid_on, position=r["position"], points=r["points"]))
            TeamRanking.objects.bulk_create(objs)
        self.stdout.write(self.style.SUCCESS(
            f"VRS на {valid_on}: {len(rows)} команд, из них найдено в нашей БД: {matched}."))
