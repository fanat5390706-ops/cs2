import os
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.contrib.auth import login
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from datetime import datetime, timedelta, timezone as dt_timezone
import calendar

from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render

from content.models import LiveStream, NewsArticle, Video
from core.models import FavoriteTeam, Player, Team, TeamRanking
from core.roles import VIEWER_GROUP
from matches.models import GameMap, Match, MatchMap, PlayerMapStat
from tournaments.models import FollowedTournament, Tournament, TournamentEntry, TournamentStatus

from .queries import fetch_all

SERIES = "SELECT * FROM v_match_series_score"
PER_PAGE = 50


def _local_day(value):
    """Дата матча по местному времени сайта (в БД время хранится в UTC)."""
    if not value:
        return None
    return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()


def attach_logos(rows):
    """Добавляет логотипы команд (logo1/logo2) к строкам представления v_match_series_score."""
    tags = {r["tag1"] for r in rows} | {r["tag2"] for r in rows}
    team_rows = {t: (logo, pk) for t, logo, pk in Team.objects.filter(tag__in=tags).values_list("tag", "logo_url", "pk")} if tags else {}
    logos = {t: v[0] for t, v in team_rows.items()}
    events = {pk: (name, img) for pk, name, img in Tournament.objects.filter(
        pk__in={r["tournament_id"] for r in rows}).values_list("pk", "name", "image_url")} if rows else {}
    for r in rows:
        r["event"], r["event_image"] = events.get(r["tournament_id"], ("", ""))
        r["logo1"], r["logo2"] = logos.get(r["tag1"], ""), logos.get(r["tag2"], "")
        r["team1_id"], r["team2_id"] = team_rows.get(r["tag1"], ("", None))[1], team_rows.get(r["tag2"], ("", None))[1]
        r["day"] = _local_day(r.get("scheduled_at"))
    return rows


def with_team_logos(rows):
    """Для строк с полем tag (таблицы команд) добавляет logo."""
    found = {t: (logo, pk) for t, logo, pk in Team.objects.filter(
        tag__in={r["tag"] for r in rows}).values_list("tag", "logo_url", "pk")} if rows else {}
    for r in rows:
        r["logo"], r["team_id"] = found.get(r["tag"], ("", None))
    return rows


def page_number(request):
    try:
        return max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return 1


def base_query(request):
    """Параметры запроса без page — для ссылок пагинации."""
    return urlencode({k: v for k, v in request.GET.items() if k != "page" and v})


def add_rating(row):
    """Внутренний Rating: 0.6*K/D + 0.4*(ADR/75). Это НЕ рейтинг HLTV, а наша формула из K/D и ADR."""
    if row is None:
        return None
    if row.get("kd") is not None and row.get("adr") is not None:
        row["rating"] = round(0.6 * float(row["kd"]) + 0.4 * float(row["adr"]) / 75, 2)
    else:
        row["rating"] = None
    return row


def with_derived(stats):
    """Производные показатели считаем на лету; деление на ноль даёт None, а не ошибку."""
    for s in stats:
        s.kd = round(s.kills / s.deaths, 2) if s.deaths else None
        s.hs_pct = round(100 * s.headshot_kills / s.kills, 1) if s.kills else None
        s.adr = round(s.damage / s.rounds_played, 1) if s.rounds_played else None
    return stats


def latest_ranking(limit=None):
    """Мировой рейтинг Valve (VRS) на последнюю загруженную дату: [{'position','team','points','team_id','tag','logo','roster'}]."""
    source = "manual" if TeamRanking.objects.filter(source="manual").exists() else "vrs"
    latest = TeamRanking.objects.filter(source=source).order_by("-valid_on").values_list("valid_on", flat=True).first()
    if not latest:
        return []
    qs = TeamRanking.objects.filter(source=source, valid_on=latest).select_related("team").order_by("position")
    if limit:
        qs = qs[:limit]
    return [{"position": r.position, "team": r.team.name if r.team else r.team_name, "points": r.points,
             "team_id": r.team_id, "tag": r.team.tag if r.team else "", "logo": r.team.logo_url if r.team else "",
             "roster": r.roster, "date": latest} for r in qs]


TIER_LIMITS = [(10, 1), (30, 2), (100, 3)]  # место в VRS -> тир команды; ниже 100 и без рейтинга — тир 4


def team_tier(position):
    for limit, tier in TIER_LIMITS:
        if position and position <= limit:
            return tier
    return 4


def strength_index():
    """Силу команды берём из мирового рейтинга Valve: {id команды: место, нижний регистр имени/тега: место}."""
    by_id, by_name = {}, {}
    for r in latest_ranking():
        if r["team_id"]:
            by_id[r["team_id"]] = r["position"]
        by_name.setdefault(r["team"].lower(), r["position"])
        if r["tag"]:
            by_name.setdefault(r["tag"].lower(), r["position"])
    return by_id, by_name


def add_strength(rows):
    """Каждой серии: pos1/pos2 (место в VRS), strength (лучшее из двух мест), tier (1–4 по лучшей команде)."""
    by_id, by_name = strength_index()

    def pos(team_id, name, tag):
        return by_id.get(team_id) or by_name.get((name or "").lower()) or by_name.get((tag or "").lower()) or 0

    for r in rows:
        r["pos1"] = pos(r.get("team1_id"), r.get("team1"), r.get("tag1"))
        r["pos2"] = pos(r.get("team2_id"), r.get("team2"), r.get("tag2"))
        known = [p for p in (r["pos1"], r["pos2"]) if p]
        r["strength"] = min(known) if known else 9999
        r["tier"] = team_tier(r["strength"] if known else 0)
    return rows


def sort_by_strength(rows, newest_first=False):
    """Внутри дня: сначала матчи команд тира 1–3 по времени, затем остальные тоже по времени.
    Дни идут по порядку (в Results — от новых к старым); идущие сейчас матчи выше остальных."""
    sign = -1 if newest_first else 1
    return sorted(rows, key=lambda r: (
        sign * (r["day"].toordinal() if r.get("day") else 0),
        0 if r["status"] == "live" else 1,
        0 if r["tier"] <= 3 else 1,
        sign * (r["scheduled_at"].timestamp() if r.get("scheduled_at") else 0),
    ))


def today_matches():
    """Матчи сегодняшнего дня (по местному времени) и идущие сейчас."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    rows = fetch_all(
        f"{SERIES} WHERE (status = 'live' AND scheduled_at >= NOW() - INTERVAL 1 DAY) OR (status = 'scheduled' AND scheduled_at >= %s AND scheduled_at < %s) "
        "ORDER BY scheduled_at LIMIT 200",
        [start.astimezone(dt_timezone.utc), end.astimezone(dt_timezone.utc)],
    )
    rows = add_strength(attach_logos(rows))
    rows.sort(key=lambda r: (0 if r["status"] == "live" else 1, 0 if r["tier"] <= 3 else 1, r["scheduled_at"]))
    return rows[:14]


def group_by_event(rows):
    """Строки серий -> [{'event', 'image', 'tournament_id', 'matches': [...]}] в порядке появления."""
    groups, index = [], {}
    for r in rows:
        key = r["tournament_id"]
        if key not in index:
            index[key] = {"event": r["event"], "image": r.get("event_image", ""), "tournament_id": key, "matches": []}
            groups.append(index[key])
        index[key]["matches"].append(r)
    return groups


def events_sidebar():
    """Блок Events: идущие и ближайшие события с числом дней до начала."""
    today = timezone.localdate()
    items = list(Tournament.objects.filter(status=TournamentStatus.ONGOING).order_by("-start_date")[:4])
    items += list(Tournament.objects.filter(start_date__gt=today).order_by("start_date")[:4])
    for t in items:
        t.is_live = t.start_date <= today <= t.end_date
        t.days = (t.start_date - today).days
    return items


def home(request):
    ongoing = (
        Tournament.objects.filter(status=TournamentStatus.ONGOING).order_by("-start_date").first()
        or Tournament.objects.order_by("-start_date").first()
    )
    standings = []
    if ongoing:
        standings = fetch_all(
            "SELECT * FROM v_tournament_standings WHERE tournament_id = %s "
            "ORDER BY wins DESC, losses ASC, team LIMIT 8",
            [ongoing.pk],
        )
    featured = list(Tournament.objects.filter(status=TournamentStatus.ONGOING).order_by("-start_date")[:3]) or list(
        Tournament.objects.order_by("-start_date")[:3]
    )
    ranking = latest_ranking(10)
    context = {
        "featured": featured,
        "live": attach_logos(fetch_all(f"{SERIES} WHERE status = 'live' AND scheduled_at >= NOW() - INTERVAL 1 DAY ORDER BY scheduled_at LIMIT 8")),
        "upcoming": attach_logos(fetch_all(f"{SERIES} WHERE status = 'scheduled' ORDER BY scheduled_at LIMIT 10")),
        "recent": attach_logos(fetch_all(f"{SERIES} WHERE status = 'finished' ORDER BY scheduled_at DESC LIMIT 10")),
        "top_teams": with_team_logos(fetch_all(
            "SELECT team, tag, CAST(SUM(wins) AS SIGNED) AS wins, CAST(SUM(losses) AS SIGNED) AS losses "
            "FROM v_tournament_standings GROUP BY team, tag HAVING SUM(wins) + SUM(losses) > 0 "
            "ORDER BY wins DESC, losses ASC LIMIT 10"
        )),
        "ongoing": ongoing,
        "ranking": ranking,
        "today_matches": today_matches(),
        "events_side": events_sidebar(),
        "streams": LiveStream.objects.all()[:48],
        "twitch_parent": request.get_host().split(":")[0],
        # без ключей Twitch API показываем встроенные плееры известных каналов (список меняется в .env)
        "fallback_channels": [c.strip() for c in os.environ.get("TWITCH_FALLBACK_CHANNELS", "esl_csgo,blastpremier").split(",") if c.strip()],
        "news": NewsArticle.objects.all()[:9],
        "videos": Video.objects.all()[:4],
        "standings": standings,
        "top_players": fetch_all(
            "SELECT v.*, p.country FROM v_player_totals v JOIN player p ON p.id = v.player_id "
            "ORDER BY v.adr DESC LIMIT 6"
        ),
        "counts": {
            "teams": Team.objects.count(),
            "players": Player.objects.count(),
            "matches": Match.objects.count(),
            "maps": MatchMap.objects.count(),
        },
    }
    return render(request, "web/home.html", context)


def tournament_list(request):
    status = request.GET.get("status", "")
    tournaments = Tournament.objects.select_related("organizer")
    if status in {value for value, _ in TournamentStatus.choices}:
        tournaments = tournaments.filter(status=status)
    else:
        status = ""
    followed = set()
    if request.user.is_authenticated:
        followed = set(request.user.followed_tournaments.values_list("tournament_id", flat=True))
    return render(
        request,
        "web/tournament_list.html",
        {"tournaments": tournaments, "status": status, "followed": followed,
         "tabs": [("", "All"), ("ongoing", "Ongoing"), ("registration", "Upcoming"), ("finished", "Past")]},
    )


def tournament_detail(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    standings = fetch_all(
        "SELECT * FROM v_tournament_standings WHERE tournament_id = %s "
        "ORDER BY wins DESC, losses ASC, team",
        [pk],
    )
    matches = attach_logos(fetch_all(f"{SERIES} WHERE tournament_id = %s ORDER BY scheduled_at", [pk]))
    groups = []  # этапы в порядке появления
    for m in matches:
        if not groups or groups[-1]["stage"] != m["stage"]:
            groups.append({"stage": m["stage"], "matches": []})
        groups[-1]["matches"].append(m)

    top_players = fetch_all(
        "SELECT p.id AS player_id, p.nickname, p.country, t.tag, "
        "COUNT(*) AS maps_played, "
        "ROUND(SUM(s.kills) / NULLIF(SUM(s.deaths), 0), 2) AS kd, "
        "ROUND(SUM(s.damage) / NULLIF(SUM(s.rounds_played), 0), 1) AS adr "
        "FROM player_map_stat s "
        "JOIN match_map mm ON mm.id = s.match_map_id "
        "JOIN game_match m ON m.id = mm.match_id "
        "JOIN match_participant mp ON mp.id = s.participant_id "
        "JOIN tournament_entry e ON e.id = mp.entry_id "
        "JOIN team t ON t.id = e.team_id "
        "JOIN player p ON p.id = s.player_id "
        "WHERE m.tournament_id = %s "
        "GROUP BY p.id, p.nickname, p.country, t.tag "
        "ORDER BY adr DESC LIMIT 10",
        [pk],
    )
    tab = request.GET.get("tab", "overview")
    if tab not in ("overview", "matches", "results", "stats"):
        tab = "overview"
    results = [m for m in matches if m["status"] == "finished"][::-1]
    teams = list(tournament.entries.select_related("team").order_by("team__name"))
    return render(
        request,
        "web/tournament_detail.html",
        {
            "tournament": tournament,
            "standings": standings,
            "groups": groups,
            "top_players": top_players,
            "tab": tab,
            "tabs": [("overview", "Overview"), ("matches", "Matches"), ("results", "Results"), ("stats", "Stats")],
            "results": results,
            "teams": teams,
            "teams_count": len(teams),
            "upcoming": [m for m in matches if m["status"] != "finished"],
        },
    )


MATCH_TABS = [("overview", "Overview"), ("scoreboard", "Scoreboard"), ("stats", "Stats"),
              ("lineups", "Lineups"), ("h2h", "H2H")]


def team_form(team):
    """Результаты команды по всем её заявкам: (серии от новых к старым, id заявок)."""
    entry_ids = list(team.entries.values_list("pk", flat=True))
    if not entry_ids:
        return [], []
    marks = ",".join(["%s"] * len(entry_ids))
    rows = fetch_all(
        f"{SERIES} WHERE status = 'finished' AND (entry1_id IN ({marks}) OR entry2_id IN ({marks})) "
        "ORDER BY scheduled_at DESC LIMIT 300",
        entry_ids + entry_ids,
    )
    return rows, entry_ids


def match_detail(request, pk):
    match = get_object_or_404(Match.objects.select_related("tournament"), pk=pk)
    tab = request.GET.get("tab", "overview")
    if tab not in {k for k, _ in MATCH_TABS}:
        tab = "overview"
    rows = fetch_all(f"{SERIES} WHERE match_id = %s", [pk])
    series = attach_logos(rows)[0] if rows else None
    maps = []
    for match_map in match.maps.select_related("game_map").order_by("map_number"):
        scores = {
            s.participant.slot: s.rounds_won
            for s in match_map.scores.select_related("participant")
        }
        r1, r2 = scores.get(1), scores.get(2)
        stats = with_derived(
            list(match_map.player_stats.select_related("player", "participant").order_by("-kills"))
        )
        maps.append(
            {
                "map": match_map,
                "r1": r1,
                "r2": r2,
                "p1": round(100 * r1 / (r1 + r2)) if r1 is not None and (r1 + r2) else 50,
                "stats1": [s for s in stats if s.participant.slot == 1],
                "stats2": [s for s in stats if s.participant.slot == 2],
            }
        )

    lineups, h2h, h2h_wins, forms = [], [], (0, 0), []
    if series:
        entries = {e.pk: e for e in TournamentEntry.objects.filter(
            pk__in=[series["entry1_id"], series["entry2_id"]]).select_related("team")}
        if True:
            for key in ("entry1_id", "entry2_id"):
                entry = entries.get(series[key])
                if entry:
                    roster = list(entry.roster.select_related("player").order_by("role", "player__nickname"))
                    lineups.append({"team": entry.team, "players": roster})
        if True:
            h2h = attach_logos(fetch_all(
                f"{SERIES} WHERE status = 'finished' AND ((tag1 = %s AND tag2 = %s) OR (tag1 = %s AND tag2 = %s)) "
                "ORDER BY scheduled_at DESC LIMIT 20",
                [series["tag1"], series["tag2"], series["tag2"], series["tag1"]],
            ))
            w1 = sum(1 for r in h2h if (r["tag1"] == series["tag1"]) == (r["maps_team1"] > r["maps_team2"]) and r["maps_team1"] != r["maps_team2"])
            w2 = sum(1 for r in h2h if r["maps_team1"] != r["maps_team2"]) - w1
            h2h_wins = (w1, w2)
        if True:
            for key in ("entry1_id", "entry2_id"):
                entry = entries.get(series[key])
                if entry:
                    rows_, ids = team_form(entry.team)
                    forms.append({"team": entry.team, "record": team_record(rows_, ids)})
    return render(
        request,
        "web/match_detail.html",
        {
            "match": match,
            "series": series,
            "tab": tab,
            "tabs": MATCH_TABS,
            "maps": maps,
            "lineups": lineups,
            "h2h": h2h,
            "h2h_wins": h2h_wins,
            "forms": forms,
            "streams": match.tournament.streams.all()[:3],
            "videos": match.tournament.videos.all()[:3],
            "teams_count": match.tournament.entries.count(),
            "other_upcoming": [m for m in today_matches() if m["match_id"] != match.pk][:8],
        },
    )


def team_list(request):
    q = request.GET.get("q", "").strip()
    teams = Team.objects.annotate(
        active_players=Count("memberships", filter=Q(memberships__left_on__isnull=True))
    )
    if q:
        teams = teams.filter(Q(name__icontains=q) | Q(tag__icontains=q))
    paginator = Paginator(teams.order_by("name"), 48)
    page = paginator.get_page(page_number(request))
    return render(
        request,
        "web/team_list.html",
        {"teams": page, "q": q, "page": page.number, "pages": paginator.num_pages,
         "total": paginator.count, "base_query": base_query(request)},
    )


def team_record(rows, entry_ids):
    """Победы/поражения, процент, серия и форма команды по завершённым сериям (rows — от новых к старым)."""
    entry_ids = set(entry_ids)
    wins = losses = maps_won = maps_lost = 0
    form, streak = [], ""
    for r in rows:
        if r["status"] != "finished" or r["maps_team1"] == r["maps_team2"]:
            continue
        is_first = r["entry1_id"] in entry_ids
        mine, theirs = (r["maps_team1"], r["maps_team2"]) if is_first else (r["maps_team2"], r["maps_team1"])
        won = mine > theirs
        wins += won
        losses += not won
        maps_won += mine
        maps_lost += theirs
        form.append("W" if won else "L")
    if form:
        n = 1
        while n < len(form) and form[n] == form[0]:
            n += 1
        streak = f"{n}{form[0]}"
    total = wins + losses
    return {
        "wins": wins, "losses": losses, "total": total,
        "win_rate": round(100 * wins / total) if total else None,
        "maps_won": maps_won, "maps_lost": maps_lost,
        "streak": streak, "form": form[:5],
    }


TEAM_TABS = ["overview", "players", "matches", "results", "stats", "news"]


def team_detail(request, pk):
    team = get_object_or_404(Team, pk=pk)
    tab = request.GET.get("tab", "overview")
    if tab not in TEAM_TABS:
        tab = "overview"
    current = list(team.memberships.filter(left_on__isnull=True).select_related("player"))
    totals = {
        r["player_id"]: r
        for r in fetch_all(
            "SELECT * FROM v_player_totals WHERE player_id IN ("
            + ",".join(["%s"] * len(current))
            + ")",
            [m.player_id for m in current],
        )
    } if current else {}
    for m in current:
        m.totals = totals.get(m.player_id)

    entry_ids = list(team.entries.values_list("pk", flat=True))
    series = []
    if entry_ids:
        marks = ",".join(["%s"] * len(entry_ids))
        series = attach_logos(fetch_all(
            f"{SERIES} WHERE entry1_id IN ({marks}) OR entry2_id IN ({marks}) "
            "ORDER BY scheduled_at DESC LIMIT 300",
            entry_ids + entry_ids,
        ))
    finished = [r for r in series if r["status"] == "finished"]
    upcoming = sorted((r for r in series if r["status"] != "finished"), key=lambda r: r["scheduled_at"])
    rank = TeamRanking.objects.filter(team=team, source="vrs").order_by("-valid_on").first()
    news = list(NewsArticle.objects.filter(title__icontains=team.name)[:10]) if tab == "news" else []
    context = {
        "team": team,
        "tab": tab,
        "tabs": [("overview", "Overview"), ("players", "Players"), ("matches", "Matches"),
                 ("results", "Results"), ("stats", "Stats"), ("news", "News")],
        "current": current,
        "history": team.memberships.filter(left_on__isnull=False).select_related("player").order_by("-left_on"),
        "entries": team.entries.select_related("tournament"),
        "recent": finished[:5],
        "results": finished,
        "upcoming": upcoming[:5],
        "all_upcoming": upcoming,
        "record": team_record(finished, entry_ids),
        "rank": rank,
        "news": news,
        "is_favorite": request.user.is_authenticated and team.favorited_by.filter(user=request.user).exists(),
    }
    return render(request, "web/team_detail.html", context)


@login_required
@require_POST
def tournament_follow(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    follow, created = FollowedTournament.objects.get_or_create(user=request.user, tournament=tournament)
    if not created:
        follow.delete()
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "web:tournament_list"
    return redirect(target)


@login_required
@require_POST
def team_favorite(request, pk):
    team = get_object_or_404(Team, pk=pk)
    fav, created = FavoriteTeam.objects.get_or_create(user=request.user, team=team)
    if not created:
        fav.delete()
    return redirect("web:team_detail", pk=pk)


# kd/hs: сначала статистика из внесённых карт, если её нет — средние значения FACEIT
KD = "COALESCE(v.kd, p.faceit_kd)"
HS = "COALESCE(v.hs_percent, p.faceit_hs)"
SORTS = {
    "elo": "p.faceit_elo IS NULL, p.faceit_elo DESC",
    "rating": "(0.6 * v.kd + 0.4 * v.adr / 75) IS NULL, (0.6 * v.kd + 0.4 * v.adr / 75) DESC",
    "adr": "v.adr IS NULL, v.adr DESC",
    "kd": f"{KD} IS NULL, {KD} DESC",
    "hs": f"{HS} IS NULL, {HS} DESC",
    "winrate": "p.faceit_win_rate IS NULL, p.faceit_win_rate DESC",
    "kills": "v.kills IS NULL, v.kills DESC",
    "maps": "COALESCE(v.maps_played, p.faceit_matches) IS NULL, COALESCE(v.maps_played, p.faceit_matches) DESC",
}


def player_list(request):
    q = request.GET.get("q", "").strip()
    team_tag = request.GET.get("team", "").strip()
    role = request.GET.get("role", "").strip()
    sort = request.GET.get("sort", "elo")
    if sort not in SORTS:
        sort = "elo"

    sql = [
        "SELECT p.id AS player_id, p.nickname, p.country, p.role, p.photo_url, p.avatar_url,",
        "COALESCE(v.maps_played, p.faceit_matches) AS maps_played, v.kills, v.deaths, v.assists,",
        f"{KD} AS kd, {HS} AS hs_percent, v.adr, p.faceit_elo, p.faceit_win_rate,",
        "ct.tag AS team_tag, ct.name AS team_name",
        "FROM player p LEFT JOIN v_player_totals v ON v.player_id = p.id",
        "LEFT JOIN team_membership cm ON cm.player_id = p.id AND cm.left_on IS NULL",
        "LEFT JOIN team ct ON ct.id = cm.team_id WHERE 1 = 1",
    ]
    params = []
    if q:
        sql.append("AND p.nickname LIKE %s")
        params.append(f"%{q}%")
    if team_tag:
        sql.append("AND ct.tag = %s")
        params.append(team_tag)
    if role:
        sql.append("AND p.role = %s")
        params.append(role)
    total = fetch_all("SELECT COUNT(*) AS c FROM (" + " ".join(sql) + ") x", params)[0]["c"]
    pages = max(1, -(-total // PER_PAGE))
    page = min(page_number(request), pages)
    sql.append(f"ORDER BY {SORTS[sort]}, p.nickname")  # SORTS — белый список, не ввод пользователя
    sql.append("LIMIT %s OFFSET %s")
    params += [PER_PAGE, (page - 1) * PER_PAGE]

    return render(
        request,
        "web/player_list.html",
        {
            "players": [add_rating(r) for r in fetch_all(" ".join(sql), params)],
            "teams": Team.objects.all(),
            "roles": list(Player.objects.exclude(role="").values_list("role", flat=True).distinct().order_by("role")),
            "q": q,
            "team_tag": team_tag,
            "role": role,
            "sort": sort,
            "page": page,
            "pages": pages,
            "total": total,
            "first_rank": (page - 1) * PER_PAGE,
            "base_query": base_query(request),
        },
    )


def player_detail(request, pk):
    player = get_object_or_404(Player, pk=pk)
    totals = fetch_all("SELECT * FROM v_player_totals WHERE player_id = %s", [pk])
    stats = with_derived(
        list(
            PlayerMapStat.objects.filter(player=player)
            .select_related(
                "match_map__match__tournament",
                "match_map__game_map",
                "participant__entry__team",
            )
            .order_by("-match_map__match__scheduled_at", "match_map__map_number")
        )
    )
    max_adr = max((s.adr or 0 for s in stats), default=0)
    for s in stats:
        s.bar = round(100 * (s.adr or 0) / max_adr) if max_adr else 0
    team_now = getattr(player.memberships.filter(left_on__isnull=True).select_related("team").first(), "team", None)
    team_rows, team_entries = team_form(team_now) if team_now else ([], [])
    tab = request.GET.get("tab", "info")
    if tab not in ("info", "teams", "matches", "faceit"):
        tab = "info"
    totals_row = add_rating(totals[0]) if totals else None

    def pct(value, top):
        return min(100, round(100 * float(value) / top)) if value is not None else 0

    if totals_row:
        bars = [("Rating", totals_row["rating"], f'{totals_row["rating"]}', pct(totals_row["rating"], 1.8)),
                ("K/D", totals_row["kd"], f'{totals_row["kd"]}', pct(totals_row["kd"], 2.0)),
                ("ADR", totals_row["adr"], f'{totals_row["adr"]}', pct(totals_row["adr"], 100)),
                ("HS%", totals_row["hs_percent"], f'{totals_row["hs_percent"]}', pct(totals_row["hs_percent"], 100))]
        bars_source = f"{totals_row['maps_played']} maps in tournament matches"
    else:
        bars = [("FACEIT ELO", player.faceit_elo, str(player.faceit_elo), pct(player.faceit_elo, 5000)),
                ("K/D", player.faceit_kd, str(player.faceit_kd), pct(player.faceit_kd, 2.0)),
                ("HS%", player.faceit_hs, f"{player.faceit_hs}%", pct(player.faceit_hs, 100)),
                ("Win rate", player.faceit_win_rate, f"{player.faceit_win_rate}%", pct(player.faceit_win_rate, 100))]
        bars = [b for b in bars if b[1] is not None]
        bars_source = f"FACEIT matchmaking · {player.faceit_matches} matches" if player.faceit_matches else "no statistics yet"
    all_rows = attach_logos(team_rows[:40])
    context = {
        "tab": tab,
        "tabs": [("info", "Info"), ("teams", "Teams"), ("matches", "Matches"), ("faceit", "FACEIT")],
        "bars": bars,
        "bars_source": bars_source,
        "upcoming_team": attach_logos(fetch_all(
            f"{SERIES} WHERE status != 'finished' AND (entry1_id IN ({','.join(['%s'] * len(team_entries))}) "
            f"OR entry2_id IN ({','.join(['%s'] * len(team_entries))})) ORDER BY scheduled_at LIMIT 5",
            team_entries + team_entries)) if team_entries else [],
        "player": player,
        "all_rows": all_rows,
        "team_matches": attach_logos(team_rows[:10]),
        "team_record": team_record(team_rows, team_entries) if team_now else None,
        "totals": add_rating(totals[0]) if totals else None,
        "team_now": team_now,
        "memberships": player.memberships.select_related("team").order_by("-joined_on"),
        "stats": stats,
    }
    return render(request, "web/player_detail.html", context)


def matches(request, tab=None):
    tab = tab or request.GET.get("tab", "upcoming")
    where, order = {
        "live": ("status = 'live' AND scheduled_at >= NOW() - INTERVAL 1 DAY", "scheduled_at"),
        "upcoming": ("status = 'scheduled'", "scheduled_at"),
        "results": ("status = 'finished'", "scheduled_at DESC"),
    }.get(tab, ("status = 'scheduled'", "scheduled_at"))
    if tab not in ("live", "upcoming", "results"):
        tab = "upcoming"
    params, tournament = [], request.GET.get("tournament", "")
    if tab == "upcoming":
        # запланированные, но давно прошедшие матчи (не обновлённые источником) в ближайших не показываем
        where += " AND scheduled_at >= %s"
        params.append(timezone.now() - timedelta(minutes=45))
    if tournament.isdigit():
        where += " AND tournament_id = %s"
        params.append(int(tournament))
    day_raw = request.GET.get("date", "")
    try:
        day = datetime.strptime(day_raw, "%Y-%m-%d").date()
    except ValueError:
        day = None
    if day:
        where += " AND DATE(scheduled_at) = %s"
        params.append(day)
    tier = request.GET.get("tier", "")
    tier = int(tier) if tier in ("1", "2", "3", "4") else ""
    q = request.GET.get("q", "").strip()
    if q:
        where += " AND (team1 LIKE %s OR team2 LIKE %s OR tag1 LIKE %s OR tag2 LIKE %s)"
        params += [f"%{q}%"] * 4
    rows = add_strength(attach_logos(fetch_all(f"{SERIES} WHERE {where} ORDER BY {order} LIMIT 800", params)))
    if tier:
        rows = [r for r in rows if r["tier"] == tier]
    rows = sort_by_strength(rows, newest_first=(tab == "results"))[:300]
    counts = {r["status"]: r["c"] for r in fetch_all(
        "SELECT status, COUNT(*) AS c FROM game_match WHERE status <> 'live' OR scheduled_at >= NOW() - INTERVAL 1 DAY GROUP BY status")}
    counts["scheduled"] = fetch_all("SELECT COUNT(*) AS c FROM game_match WHERE status = 'scheduled' AND scheduled_at >= %s",
                                    [timezone.now() - timedelta(minutes=45)])[0]["c"]
    return render(
        request,
        "web/matches.html",
        {
            "tab": tab,
            "rows": rows,
            "counts": {"live": counts.get("live", 0), "upcoming": counts.get("scheduled", 0), "results": counts.get("finished", 0)},
            "tournaments": Tournament.objects.order_by("-start_date")[:60],
            "tournament": int(tournament) if tournament.isdigit() else "",
            "q": q,
            "tier": tier,
            "groups": [],
            "day": day,
            "calendar": month_calendar(day or timezone.localdate()),
            "events_side": events_sidebar(),
        },
    )


def month_calendar(anchor):
    """Недели месяца для мини-календаря слева: [[(дата|None, из_этого_месяца), ...], ...]."""
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month)
    return {
        "title": anchor.strftime("%B %Y").upper(),
        "weeks": [[(d, d.month == anchor.month) for d in week] for week in weeks],
        "today": timezone.localdate(),
        "prev": (anchor.replace(day=1) - timedelta(days=1)).replace(day=1),
        "next": (anchor.replace(day=28) + timedelta(days=4)).replace(day=1),
    }


def signup(request):
    """Регистрация зрителя: обычный пользователь без доступа к админке, в группе «Зритель»."""
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        group, _ = Group.objects.get_or_create(name=VIEWER_GROUP)
        user.groups.add(group)
        login(request, user)
        return redirect("web:home")
    return render(request, "registration/signup.html", {"form": form})


def results(request):
    return matches(request, "results")


MAP_THEMES = {n: n for n in ("ancient", "anubis", "dust2", "inferno", "mirage", "nuke", "overpass", "vertigo", "train", "cache")}

STATS_SECTIONS = [("players", "Player stats"), ("teams", "Team stats"), ("maps", "Map stats")]


def faceit_map_table():
    """Сводка по картам из FACEIT-статистики отслеживаемых игроков: матчи, винрейт и K/D (взвешенно по матчам)."""
    agg = {}
    for maps in Player.objects.exclude(faceit_maps=[]).values_list("faceit_maps", flat=True):
        for m in maps or []:
            row = agg.setdefault(m["map"], {"map": m["map"], "players": 0, "matches": 0, "wr": 0.0, "kd": 0.0, "kd_n": 0})
            n = m.get("matches") or 0
            row["players"] += 1
            row["matches"] += n
            row["wr"] += (m.get("win_rate") or 0) * n
            if m.get("kd") is not None:
                row["kd"] += float(m["kd"]) * n
                row["kd_n"] += n
    rows = []
    for r in agg.values():
        rows.append({"map": r["map"], "players": r["players"], "matches": r["matches"],
                     "win_rate": round(r["wr"] / r["matches"]) if r["matches"] else None,
                     "kd": round(r["kd"] / r["kd_n"], 2) if r["kd_n"] else None})
    return sorted(rows, key=lambda r: -r["matches"])


def stats(request):
    """Три раздела как на HLTV: игроки, команды, карты. Игроки — по картам матчей, иначе по FACEIT."""
    section = request.GET.get("section", "players")
    if section not in {k for k, _ in STATS_SECTIONS}:
        section = "players"
    boards, map_rows, map_tiles = [], [], []

    def bar(value, peak):
        return round(100 * float(value) / float(peak)) if peak else 0

    table_rows = []
    tournament_mode = False
    if section == "players":
        table_rows = fetch_all(
            "SELECT p.id AS player_id, p.nickname, p.country, COUNT(*) AS maps, CAST(SUM(s.rounds_played) AS SIGNED) AS rounds, "
            "CAST(SUM(s.kills) AS SIGNED) AS kills, CAST(SUM(s.deaths) AS SIGNED) AS deaths, "
            "CAST(SUM(s.kills) - SUM(s.deaths) AS SIGNED) AS diff, ROUND(SUM(s.kills) / NULLIF(SUM(s.deaths), 0), 2) AS kd, "
            "ROUND(SUM(s.damage) / NULLIF(SUM(s.rounds_played), 0), 1) AS adr, "
            "ROUND(100 * SUM(s.headshot_kills) / NULLIF(SUM(s.kills), 0), 1) AS hs, "
            "(SELECT ct.id FROM team_membership cm JOIN team ct ON ct.id = cm.team_id "
            " WHERE cm.player_id = p.id AND cm.left_on IS NULL LIMIT 1) AS team_id "
            "FROM player_map_stat s JOIN player p ON p.id = s.player_id GROUP BY p.id, p.nickname, p.country "
            "ORDER BY kd DESC LIMIT 100"
        )
        tournament_mode = bool(table_rows)
        if tournament_mode:
            teams = {t.pk: t for t in Team.objects.filter(pk__in={r["team_id"] for r in table_rows if r["team_id"]})}
            for r in table_rows:
                team = teams.get(r["team_id"])
                r["team_tag"], r["logo"] = (team.tag, team.logo_url) if team else ("", "")
        else:
            table_rows = fetch_all(
                "SELECT p.id AS player_id, p.nickname, p.country, p.faceit_elo, p.faceit_kd, p.faceit_hs, "
                "p.faceit_win_rate, p.faceit_matches, ct.tag AS team_tag, ct.name AS team_name, ct.id AS team_id "
                "FROM player p LEFT JOIN team_membership cm ON cm.player_id = p.id AND cm.left_on IS NULL "
                "LEFT JOIN team ct ON ct.id = cm.team_id "
                "WHERE p.faceit_elo IS NOT NULL ORDER BY p.faceit_elo DESC LIMIT 100"
            )
            # логотипы команд: один дополнительный запрос на всю страницу
            logos = dict(Team.objects.filter(pk__in={r["team_id"] for r in table_rows if r["team_id"]}).values_list("pk", "logo_url"))
            for r in table_rows:
                r["logo"] = logos.get(r["team_id"], "")
    elif section == "teams":
        wl = {r["tag"]: r for r in fetch_all(
            "SELECT tag, CAST(SUM(wins) AS SIGNED) AS wins, CAST(SUM(losses) AS SIGNED) AS losses "
            "FROM v_tournament_standings GROUP BY tag"
        )}
        agg = {r["tag"]: r for r in fetch_all(
            "SELECT t.tag, COUNT(DISTINCT s.match_map_id) AS maps, CAST(SUM(s.kills) AS SIGNED) AS kills, "
            "CAST(SUM(s.deaths) AS SIGNED) AS deaths, ROUND(SUM(s.damage) / NULLIF(SUM(s.rounds_played), 0), 1) AS adr "
            "FROM player_map_stat s JOIN match_participant mp ON mp.id = s.participant_id "
            "JOIN tournament_entry te ON te.id = mp.entry_id JOIN team t ON t.id = te.team_id GROUP BY t.tag"
        )}
        for r in latest_ranking(100):
            rec = wl.get(r["tag"]) if r["tag"] else None
            r["wins"], r["losses"] = (rec["wins"], rec["losses"]) if rec else (None, None)
            a = agg.get(r["tag"]) if r["tag"] else None
            r["maps"] = a["maps"] if a else None
            r["diff"] = a["kills"] - a["deaths"] if a else None
            r["kd"] = round(a["kills"] / a["deaths"], 2) if a and a["deaths"] else None
            r["adr"] = a["adr"] if a else None
            table_rows.append(r)
    else:
        map_rows = faceit_map_table()
        played = dict(MatchMap.objects.values_list("game_map__name").annotate(c=Count("id")).values_list("game_map__name", "c"))
        peak = max(played.values(), default=0)
        names = [m.name for m in GameMap.objects.filter(is_active=True)] or list(MAP_THEMES)
        map_tiles = [{"name": n, "theme": MAP_THEMES.get(n.lower(), "ancient"), "played": played.get(n, 0),
                      "bar": round(100 * played.get(n, 0) / peak) if peak else 0} for n in names]
        map_tiles.sort(key=lambda t: -t["played"])
    return render(request, "web/stats.html", {
        "table_rows": table_rows, "boards": boards, "map_rows": map_rows, "map_tiles": map_tiles, "tournament_mode": tournament_mode, "section": section, "sections": STATS_SECTIONS,
        "pool": list(GameMap.objects.filter(is_active=True)),
    })


def map_list(request):
    return redirect(f"{reverse('web:stats')}?section=maps")


def news_list(request):
    return render(request, "web/news_list.html", {"articles": NewsArticle.objects.all()[:60]})


def video_list(request):
    kind = request.GET.get("kind", "")
    videos = Video.objects.select_related("tournament")
    if kind in {value for value, _ in Video.Kind.choices}:
        videos = videos.filter(kind=kind)
    else:
        kind = ""
    return render(request, "web/video_list.html", {"videos": videos[:48], "kind": kind, "kinds": Video.Kind.choices})


def search(request):
    q = request.GET.get("q", "").strip()
    context = {"q": q, "players": [], "teams": [], "tournaments": []}
    if q:
        context["players"] = Player.objects.filter(nickname__icontains=q)[:20]
        context["teams"] = Team.objects.filter(Q(name__icontains=q) | Q(tag__icontains=q))[:20]
        context["tournaments"] = Tournament.objects.filter(name__icontains=q)[:20]
    return render(request, "web/search.html", context)
