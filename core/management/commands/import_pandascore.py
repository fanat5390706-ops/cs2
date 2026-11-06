"""Импорт реальных команд, игроков, турниров и расписания из PandaScore.

    python manage.py import_pandascore [--reset] [--past-pages 1] [--match-pages 2] [--team-pages 10]

Токен берётся из переменной PANDASCORE_TOKEN (файл .env).

Что импортируется (бесплатный тариф PandaScore): команды, игроки, турниры,
заявки команд на турниры и расписание матчей (запланированные и идущие).
Результаты по картам и статистика игроков на бесплатном тарифе недоступны,
поэтому завершённые матчи не импортируются: счёт серии у нас вычисляется
из карт, а карт без статистики нет.

Даты вступления игроков в команды API не отдаёт: joined_on = дата импорта.
Данные вносятся напрямую через ORM (минуя сервисы), но все ограничения БД
(CHECK/UNIQUE) продолжают действовать.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import MembershipRole, Player, Team, TeamMembership
from matches.models import (
    BestOf,
    Match,
    MatchMap,
    MatchMapScore,
    MatchParticipant,
    MatchStatus,
    PlayerMapStat,
)
from tournaments.models import (
    Tournament,
    TournamentEntry,
    TournamentRosterPlayer,
    TournamentStatus,
)

BASE = "https://api.pandascore.co"
STATUS_MAP = {
    "running": MatchStatus.LIVE,
    "finished": MatchStatus.FINISHED,
    "canceled": MatchStatus.CANCELLED,
}  # остальные (not_started, postponed) — запланирован
PAUSE = 0.4  # пауза между запросами: лимит бесплатного тарифа — 1000 запросов в час


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_date(value):
    dt = parse_dt(value)
    return dt.date() if dt else None


def parse_prize(value):
    """'$1,000,000 United States Dollar' -> 1000000. Другие валюты не пересчитываем: возвращаем None."""
    if not value or ("$" not in value and "United States Dollar" not in value):
        return None
    digits = "".join(ch for ch in value.split("United")[0] if ch.isdigit())
    return int(digits) if digits else None


def unique_value(model, field, value, max_len):
    """Подбирает значение, которого ещё нет в UNIQUE-поле."""
    value = (value or "").strip()[:max_len] or "unknown"
    candidate, n = value, 1
    while model.objects.filter(**{field: candidate}).exists():
        n += 1
        suffix = f"_{n}"
        candidate = value[: max_len - len(suffix)] + suffix
    return candidate


class Command(BaseCommand):
    help = "Импортирует команды, игроков, турниры и расписание CS2 из PandaScore."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Сначала удалить все данные проекта.")
        parser.add_argument("--past-pages", type=int, default=1, help="Страниц завершённых турниров (по 100).")
        parser.add_argument("--team-pages", type=int, default=10, help="Страниц общего списка команд (по 100) сверх участников турниров.")
        parser.add_argument("--tiers", default="s,a,b", help="Тиры турниров, матчи которых грузить в первую очередь.")
        parser.add_argument("--match-pages", type=int, default=2, help="Страниц матчей каждого типа (по 100).")

    # --- HTTP -----------------------------------------------------------
    def get(self, path, **params):
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                time.sleep(PAUSE)
                return data
            except urllib.error.HTTPError as error:
                if error.code == 401:
                    raise CommandError("PandaScore отклонил токен (401). Проверьте PANDASCORE_TOKEN.")
                if error.code == 404:
                    return []  # у турнира нет матчей/страницы — не повод падать
                if error.code == 403:
                    self.stdout.write(self.style.WARNING(f"{path}: нет доступа на вашем тарифе (403), пропускаю."))
                    return []
                if error.code == 429:
                    self.stdout.write("Лимит запросов, жду 60 секунд...")
                    time.sleep(60)
                    continue
                raise CommandError(f"{path}: HTTP {error.code}")
            except urllib.error.URLError as error:
                raise CommandError(f"Нет связи с PandaScore: {error.reason}")
        raise CommandError(f"{path}: превышен лимит запросов, повторите позже.")

    def pages(self, path, pages, **params):
        for page in range(1, pages + 1):
            chunk = self.get(path, page=page, per_page=100, **params)
            yield from chunk
            if len(chunk) < 100:
                break

    # --- main -----------------------------------------------------------
    def handle(self, *args, **options):
        self.token = os.environ.get("PANDASCORE_TOKEN", "").strip()
        if not self.token or self.token == "change-me":
            raise CommandError("Не задан PANDASCORE_TOKEN в файле .env.")
        organizer = get_user_model().objects.filter(is_superuser=True).first()
        if organizer is None:
            raise CommandError("Сначала создайте администратора: python manage.py createsuperuser")

        # Всё загружаем ДО изменения базы: если API недоступен, старые данные не пострадают.
        tournaments = {}
        for kind, pages in (("running", 1), ("upcoming", 1), ("past", options["past_pages"])):
            for t in self.pages(f"/csgo/tournaments/{kind}", pages):
                tournaments[t["id"]] = t
        # Общий поток матчей забит низшими лигами, поэтому сначала берём турниры высших тиров (S/A/B)
        # и тянем их матчи по отдельности. Если API не отдаёт фильтр/эндпоинт — просто идём дальше.
        top_matches = {}
        top_tournaments = list(self.pages("/csgo/tournaments", 1, sort="-begin_at", **{"filter[tier]": options["tiers"]}))
        for t in top_tournaments[:40]:
            tournaments[t["id"]] = t
            for m in self.get(f"/csgo/tournaments/{t['id']}/matches", per_page=100) or []:
                top_matches[m["id"]] = {**m, "tournament": m.get("tournament") or t,
                                        "serie": m.get("serie") or t.get("serie"), "league": m.get("league") or t.get("league")}
        matches = list(top_matches.values())
        for kind in ("running", "upcoming"):
            matches += list(self.pages(f"/csgo/matches/{kind}", options["match_pages"]))
        # Завершённые матчи с итоговым счётом серии (самые свежие)
        # только завершённые: среди «past» много отменённых матчей, они вытесняли настоящие результаты
        matches += list(self.pages("/csgo/matches/past", max(options["match_pages"], 3), sort="-begin_at", **{"filter[status]": "finished"}))
        seen = set()
        matches = [m for m in matches if not (m["id"] in seen or seen.add(m["id"]))]
        self.stdout.write(f"Получено: {len(tournaments)} турниров ({len(top_tournaments)} высших тиров), {len(matches)} матчей.")

        team_ids = set()
        for t in tournaments.values():
            team_ids |= {x["id"] for x in t.get("teams") or []}
        for m in matches:
            for o in m.get("opponents") or []:
                if o.get("opponent"):
                    team_ids.add(o["opponent"]["id"])
        teams_full = {}
        ids = sorted(team_ids)
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            for t in self.get("/csgo/teams", per_page=50, **{"filter[id]": ",".join(map(str, chunk))}):
                teams_full[t["id"]] = t
        # Дополнительно: общий каталог команд с составами (бесплатный тариф: 1000 запросов/час).
        for t in self.pages("/csgo/teams", options["team_pages"]):
            teams_full.setdefault(t["id"], t)
        self.stdout.write(f"Получено: {len(teams_full)} команд.")

        with transaction.atomic():
            if options["reset"]:
                self.reset()
            self.save_all(organizer, tournaments, matches, teams_full)

    def reset(self):
        for model in (
            PlayerMapStat, MatchMapScore, MatchMap, MatchParticipant, Match,
            TournamentRosterPlayer, TournamentEntry, Tournament,
            TeamMembership, Player, Team,
        ):
            model.objects.all().delete()

    # --- saving ---------------------------------------------------------
    def save_all(self, organizer, tournaments, matches, teams_full):
        today = date.today()
        self.team_by_ps = {}
        self.players_by_team = {}
        used_players = {}

        for ps_id, data in teams_full.items():
            name = (data.get("name") or "").strip()
            if not name:
                continue
            team = Team.objects.filter(name=name).first()
            if team is None:
                team = Team.objects.create(
                    name=name,
                    tag=unique_value(Team, "tag", data.get("acronym") or name, 10),
                    country=(data.get("location") or "").upper()[:2],
                    logo_url=(data.get("image_url") or "")[:500],
                )
            elif not team.logo_url and data.get("image_url"):
                team.logo_url = data["image_url"][:500]
                team.save(update_fields=["logo_url"])
            self.team_by_ps[ps_id] = team

            members = []
            for p in data.get("players") or []:
                nick = (p.get("name") or "").strip()
                ps_pid = p.get("id")
                if not nick or ps_pid is None or ps_pid in used_players:
                    continue  # без ника или уже закреплён за другой командой в этом запуске
                info = {
                    "first_name": (p.get("first_name") or "")[:100],
                    "last_name": (p.get("last_name") or "")[:100],
                    "country": (p.get("nationality") or "").upper()[:2],
                    "birth_date": parse_date(p.get("birthday")),
                    "photo_url": (p.get("image_url") or "")[:500],
                    "role": (p.get("role") or "")[:30],
                }
                # Игрока ищем по ID PandaScore (так повторный импорт не создаёт дублей);
                # запись, импортированную раньше без ID, находим по нику.
                player = (
                    Player.objects.filter(pandascore_id=ps_pid).first()
                    or Player.objects.filter(nickname=nick, pandascore_id__isnull=True).first()
                )
                if player is None:
                    # у двух разных игроков может быть один ник — второй получит суффикс
                    player = Player.objects.create(
                        nickname=unique_value(Player, "nickname", nick, 50), pandascore_id=ps_pid, **info
                    )
                else:
                    changed = []
                    if player.pandascore_id is None:
                        player.pandascore_id = ps_pid
                        changed.append("pandascore_id")
                    for field in ("birth_date", "photo_url", "country", "role"):
                        if not getattr(player, field) and info[field]:
                            setattr(player, field, info[field])
                            changed.append(field)
                    if changed:
                        player.save(update_fields=changed)
                used_players[ps_pid] = player
                if not TeamMembership.objects.filter(player=player, team=team, left_on__isnull=True).exists():
                    # переход: закрываем прежнее членство (в БД не более одной открытой записи на игрока)
                    TeamMembership.objects.filter(player=player, left_on__isnull=True).update(left_on=today)
                    TeamMembership.objects.create(
                        player=player,
                        team=team,
                        role=MembershipRole.PLAYER if len(members) < 5 else MembershipRole.SUBSTITUTE,
                        joined_on=today,
                    )
                members.append(player)
            if members:  # игроки, пропавшие из состава, считаются ушедшими
                TeamMembership.objects.filter(team=team, left_on__isnull=True).exclude(
                    player__in=members
                ).update(left_on=today)
            self.players_by_team[ps_id] = members

        self.entries = {}  # (id турнира в PandaScore, id команды) -> TournamentEntry
        self.local_tournaments = {}
        for t in tournaments.values():
            self.save_tournament(organizer, t, [x["id"] for x in t.get("teams") or []])

        created = 0
        for m in matches:
            created += self.save_match(organizer, m)

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: команд {Team.objects.count()}, игроков {Player.objects.count()}, "
                f"турниров {Tournament.objects.count()}, матчей {Match.objects.count()} "
                f"(новых матчей: {created})."
            )
        )

    def tournament_status(self, start, end, running):
        today = date.today()
        if running or (start <= today <= end):
            return TournamentStatus.ONGOING
        return TournamentStatus.FINISHED if end < today else TournamentStatus.REGISTRATION

    def save_tournament(self, organizer, t, team_ps_ids):
        key = t["id"]
        if key in self.local_tournaments:
            return self.local_tournaments[key]
        serie = (t.get("serie") or {}).get("full_name") or (t.get("league") or {}).get("name") or ""
        name = f"{serie} — {t.get('name')}".strip(" —") if serie else (t.get("name") or f"Турнир {key}")
        start = parse_date(t.get("begin_at")) or date.today()
        end = parse_date(t.get("end_at")) or start
        end = max(end, start)
        local, _ = Tournament.objects.get_or_create(
            name=name[:150],
            start_date=start,
            defaults={
                "end_date": end,
                "image_url": ((t.get("league") or {}).get("image_url") or "")[:500],
                "organizer_name": ((t.get("league") or {}).get("name") or "")[:100],
                "prize_pool_usd": parse_prize(t.get("prizepool")),
                "location": (t.get("country") or t.get("region") or "")[:150],
                "tier": (t.get("tier") or "")[:1].lower() if (t.get("tier") or "")[:1].lower() in "sabcd" else "",
                "organizer": organizer,
                "status": self.tournament_status(start, end, t.get("status") == "running"),
            },
        )
        self.local_tournaments[key] = local
        for ps_team in team_ps_ids:
            self.ensure_entry(local, key, ps_team)
        return local

    def ensure_entry(self, local_tournament, ps_tournament, ps_team):
        team = self.team_by_ps.get(ps_team)
        if team is None:
            return None
        key = (ps_tournament, ps_team)
        if key not in self.entries:
            entry, created = TournamentEntry.objects.get_or_create(tournament=local_tournament, team=team)
            if created:
                for i, player in enumerate(self.players_by_team.get(ps_team, [])):
                    TournamentRosterPlayer.objects.get_or_create(
                        entry=entry,
                        player=player,
                        defaults={"role": MembershipRole.PLAYER if i < 5 else MembershipRole.SUBSTITUTE},
                    )
            self.entries[key] = entry
        return self.entries[key]

    def save_match(self, organizer, m):
        opponents = [o["opponent"]["id"] for o in (m.get("opponents") or []) if o.get("opponent")]
        if len(opponents) != 2 or opponents[0] == opponents[1]:
            return 0  # соперник ещё не определён (TBD)
        when = parse_dt(m.get("scheduled_at") or m.get("begin_at"))
        best_of = m.get("number_of_games")
        if when is None or best_of not in BestOf.values:
            return 0
        tournament_info = m.get("tournament") or {"id": m.get("tournament_id")}
        if not tournament_info.get("id"):
            return 0
        local = self.local_tournaments.get(tournament_info["id"])
        if local is None:
            local = self.save_tournament(organizer, {**tournament_info, "serie": m.get("serie"), "league": m.get("league")}, [])
        entries = [self.ensure_entry(local, tournament_info["id"], ps) for ps in opponents]
        if None in entries:
            return 0
        stage = (m.get("tournament") or {}).get("name") or "Матч"
        scores = {r.get("team_id"): r.get("score") for r in (m.get("results") or [])}
        fields = {
            "status": STATUS_MAP.get(m.get("status"), MatchStatus.SCHEDULED),
            "score_team1": scores.get(opponents[0]),
            "score_team2": scores.get(opponents[1]),
            "scheduled_at": when.astimezone(timezone.utc),
        }
        match = Match.objects.filter(external_id=m.get("id")).first() if m.get("id") else None
        if match is None:  # матч, импортированный раньше без внешнего ID
            match = Match.objects.filter(
                tournament=local, scheduled_at=fields["scheduled_at"], participants__entry=entries[0]
            ).first()
        created = match is None
        if created:
            match = Match.objects.create(
                tournament=local, stage=stage[:100], best_of=best_of, external_id=m.get("id"), **fields
            )
            for slot, entry in enumerate(entries, start=1):
                MatchParticipant.objects.create(match=match, entry=entry, slot=slot)
        else:
            for name, value in {**fields, "external_id": m.get("id")}.items():
                setattr(match, name, value)
            match.save()
        return int(created)
