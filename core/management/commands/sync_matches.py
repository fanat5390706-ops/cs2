"""Быстрое обновление уже импортированных матчей: статус и счёт серии.

    python manage.py sync_matches

Делает 3 лёгких запроса к PandaScore (идущие, ближайшие, последние завершённые),
поэтому подходит для запуска раз в минуту (лимит бесплатного тарифа — 1000 запросов в час).
Новые матчи и команды добавляет import_pandascore (раз в час в run_workers).
"""
import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.http import get_json
from core.management.commands.import_pandascore import BASE, STATUS_MAP, parse_dt
from matches.models import Match, MatchStatus


class Command(BaseCommand):
    help = "Обновляет статус и счёт матчей из PandaScore."

    def handle(self, *args, **options):
        token = os.environ.get("PANDASCORE_TOKEN", "").strip()
        if not token or token == "change-me":
            raise CommandError("Не задан PANDASCORE_TOKEN в файле .env.")
        headers = {"Authorization": f"Bearer {token}"}

        api_matches = []
        for path, params in (
            ("/csgo/matches/running", {"per_page": 50}),
            ("/csgo/matches/upcoming", {"per_page": 50}),
            ("/csgo/matches/past", {"per_page": 50, "sort": "-begin_at"}),
        ):
            api_matches += get_json(BASE + path, params, headers, pause=0.2) or []

        updated = self.apply(api_matches)

        # «Зависшие» матчи (идут/ожидаются, но время давно прошло) не попадают в списки running/upcoming/past:
        # запрашиваем их по id, иначе они навсегда остаются live.
        now = timezone.now()
        seen = {a["id"] for a in api_matches}
        stale = list(Match.objects.filter(
            status__in=[MatchStatus.LIVE, MatchStatus.SCHEDULED], external_id__isnull=False,
            scheduled_at__lt=now - timedelta(minutes=30),
        ).exclude(external_id__in=seen).values_list("external_id", flat=True))
        refreshed = []
        for i in range(0, len(stale), 50):
            chunk = stale[i:i + 50]
            refreshed += get_json(BASE + "/csgo/matches", {"per_page": 50, "filter[id]": ",".join(map(str, chunk))}, headers, pause=0.2) or []
        updated += self.apply(refreshed)

        # Всё, что источник так и не обновил и что старше суток, считаем отменённым — иначе оно висит в Live/Upcoming.
        dropped = Match.objects.filter(
            status__in=[MatchStatus.LIVE, MatchStatus.SCHEDULED], scheduled_at__lt=now - timedelta(hours=24),
        ).exclude(external_id__in=[a["id"] for a in refreshed + api_matches
                                   if STATUS_MAP.get(a.get("status")) in (MatchStatus.LIVE, MatchStatus.SCHEDULED)]).update(status=MatchStatus.CANCELLED)
        self.stdout.write(self.style.SUCCESS(f"Матчи: обновлено {updated}, догружено зависших {len(refreshed)}, закрыто устаревших {dropped}."))

    def apply(self, api_matches):
        local = {m.external_id: m for m in Match.objects.filter(external_id__in=[a["id"] for a in api_matches]).prefetch_related("participants__entry__team")}
        updated = 0
        for item in api_matches:
            match = local.get(item["id"])
            if match is None:
                continue  # новый матч появится при следующем import_pandascore
            participants = {p.slot: p for p in match.participants.all()}
            # Счёт по командам: сопоставляем по названию, слоты у нас фиксированы
            by_name = {}
            for o in item.get("opponents") or []:
                if o.get("opponent"):
                    by_name[o["opponent"]["id"]] = (o["opponent"].get("name") or "").strip()
            scores = {}
            for r in item.get("results") or []:
                scores[by_name.get(r.get("team_id"))] = r.get("score")
            s1 = scores.get(participants[1].entry.team.name) if 1 in participants else None
            s2 = scores.get(participants[2].entry.team.name) if 2 in participants else None
            status = STATUS_MAP.get(item.get("status"), MatchStatus.SCHEDULED)
            when = parse_dt(item.get("scheduled_at") or item.get("begin_at"))
            new = {"status": status, "score_team1": s1, "score_team2": s2}
            if when:
                new["scheduled_at"] = when
            changed = [k for k, v in new.items() if getattr(match, k) != v]
            if changed:
                for k in changed:
                    setattr(match, k, new[k])
                match.save(update_fields=changed)
                updated += 1
        return updated
