"""Собственное JSON API (только чтение). Одна точка доступа к данным для сайта,
десктопного и мобильного приложений: клиентам не нужны ключи внешних сервисов.

Список: GET /api/<ресурс>/?limit=50&offset=0 → {"count", "limit", "offset", "results": [...]}
"""
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from content.models import LiveStream, NewsArticle, Video
from core.models import Player, Team, TeamMembership
from tournaments.models import Tournament

from .queries import fetch_all
from .views import SERIES, add_rating

MAX_LIMIT = 100


def iso(value):
    return value.isoformat() if value else None


def respond(data):
    response = JsonResponse(data, json_dumps_params={"ensure_ascii": False})
    response["Access-Control-Allow-Origin"] = "*"  # данные публичные, только чтение
    return response


def page(request, queryset):
    """Постраничная выдача: limit (1..100) и offset из запроса; неверные значения заменяются умолчаниями."""
    try:
        limit = max(1, min(int(request.GET.get("limit", 50)), MAX_LIMIT))
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        limit, offset = 50, 0
    return limit, offset, queryset.count(), queryset[offset : offset + limit]


def listing(request, queryset, serialize):
    limit, offset, count, rows = page(request, queryset)
    return respond({"count": count, "limit": limit, "offset": offset, "results": [serialize(r) for r in rows]})


# --- сериализаторы -------------------------------------------------------
def team_dict(t):
    return {"id": t.pk, "name": t.name, "tag": t.tag, "country": t.country}


def tournament_dict(t):
    return {"id": t.pk, "name": t.name, "start_date": iso(t.start_date), "end_date": iso(t.end_date), "status": t.status}


def player_dict(p, team=None):
    return {
        "id": p.pk,
        "nickname": p.nickname,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "country": p.country,
        "birth_date": iso(p.birth_date),
        "avatar_url": p.avatar_url,
        "steam_profile_url": p.steam_profile_url,
        "vac_banned": p.vac_banned,
        "liquipedia_page": p.liquipedia_page,
        "faceit": {
            "elo": p.faceit_elo, "level": p.faceit_level,
            "matches": p.faceit_matches, "win_rate": p.faceit_win_rate,
        },
        "team": team_dict(team) if team else None,
    }


def match_dict(row):
    return {
        "id": row["match_id"],
        "tournament_id": row["tournament_id"],
        "stage": row["stage"],
        "scheduled_at": iso(row["scheduled_at"]),
        "best_of": row["best_of"],
        "status": row["status"],
        "team1": {"name": row["team1"], "tag": row["tag1"], "maps_won": row["maps_team1"]},
        "team2": {"name": row["team2"], "tag": row["tag2"], "maps_won": row["maps_team2"]},
        "winner": (
            "team1" if row["winner_entry_id"] == row["entry1_id"]
            else "team2" if row["winner_entry_id"] == row["entry2_id"] else None
        ),
    }


def current_teams(player_ids):
    """Текущая команда каждого игрока одним запросом (без N+1)."""
    memberships = TeamMembership.objects.filter(player_id__in=player_ids, left_on__isnull=True).select_related("team")
    return {m.player_id: m.team for m in memberships}


# --- представления -------------------------------------------------------
@require_GET
def index(request):
    return respond({
        "name": "ХЛТВ 2.0 API",
        "endpoints": [
            "/api/teams/", "/api/teams/<id>/",
            "/api/players/?q=&team=", "/api/players/<id>/",
            "/api/tournaments/", "/api/tournaments/<id>/",
            "/api/matches/?status=&tournament=", "/api/matches/<id>/",
            "/api/news/", "/api/videos/", "/api/streams/",
        ],
        "pagination": "limit (1-100, по умолчанию 50) и offset",
        "sources": "PandaScore, Steam, Liquipedia (CC-BY-SA 3.0), FACEIT, Twitch, YouTube, NewsAPI",
    })


@require_GET
def teams(request):
    qs = Team.objects.all()
    if q := request.GET.get("q", "").strip():
        qs = qs.filter(name__icontains=q)
    return listing(request, qs, team_dict)


@require_GET
def team_detail(request, pk):
    team = get_object_or_404(Team, pk=pk)
    members = team.memberships.filter(left_on__isnull=True).select_related("player")
    data = team_dict(team)
    data["players"] = [
        {"id": m.player.pk, "nickname": m.player.nickname, "role": m.role, "joined_on": iso(m.joined_on)}
        for m in members
    ]
    return respond(data)


@require_GET
def players(request):
    qs = Player.objects.all()
    if q := request.GET.get("q", "").strip():
        qs = qs.filter(nickname__icontains=q)
    if tag := request.GET.get("team", "").strip():
        qs = qs.filter(memberships__team__tag=tag, memberships__left_on__isnull=True)
    limit, offset, count, rows = page(request, qs)
    rows = list(rows)
    teams_by_player = current_teams([p.pk for p in rows])
    return respond({
        "count": count, "limit": limit, "offset": offset,
        "results": [player_dict(p, teams_by_player.get(p.pk)) for p in rows],
    })


@require_GET
def player_detail(request, pk):
    player = get_object_or_404(Player, pk=pk)
    data = player_dict(player, current_teams([pk]).get(pk))
    totals = fetch_all("SELECT * FROM v_player_totals WHERE player_id = %s", [pk])
    stats = add_rating(totals[0]) if totals else None
    if stats:
        stats = {k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in stats.items() if k not in ("player_id", "nickname")}
    data["stats"] = stats
    return respond(data)


@require_GET
def tournaments(request):
    qs = Tournament.objects.all()
    if status := request.GET.get("status", "").strip():
        qs = qs.filter(status=status)
    return listing(request, qs, tournament_dict)


@require_GET
def tournament_detail(request, pk):
    return respond(tournament_dict(get_object_or_404(Tournament, pk=pk)))


def match_rows(request, where="", params=()):
    status = request.GET.get("status", "").strip()
    tournament = request.GET.get("tournament", "").strip()
    clauses, args = [], list(params)
    if where:
        clauses.append(where)
    if status:
        clauses.append("status = %s")
        args.append(status)
    if tournament.isdigit():
        clauses.append("tournament_id = %s")
        args.append(int(tournament))
    sql = SERIES + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY scheduled_at DESC"
    return fetch_all(sql, args)


@require_GET
def matches(request):
    rows = match_rows(request)
    try:
        limit = max(1, min(int(request.GET.get("limit", 50)), MAX_LIMIT))
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        limit, offset = 50, 0
    return respond({
        "count": len(rows), "limit": limit, "offset": offset,
        "results": [match_dict(r) for r in rows[offset : offset + limit]],
    })


@require_GET
def match_detail(request, pk):
    rows = fetch_all(f"{SERIES} WHERE match_id = %s", [pk])
    if not rows:
        raise Http404
    return respond(match_dict(rows[0]))


@require_GET
def news(request):
    return listing(request, NewsArticle.objects.all(), lambda n: {
        "id": n.pk, "title": n.title, "url": n.url, "source": n.source,
        "summary": n.summary, "image_url": n.image_url, "published_at": iso(n.published_at),
    })


@require_GET
def videos(request):
    qs = Video.objects.all()
    if kind := request.GET.get("kind", "").strip():
        qs = qs.filter(kind=kind)
    return listing(request, qs, lambda v: {
        "id": v.pk, "youtube_id": v.youtube_id, "title": v.title, "channel": v.channel,
        "kind": v.kind, "published_at": iso(v.published_at), "tournament_id": v.tournament_id,
    })


@require_GET
def streams(request):
    return listing(request, LiveStream.objects.all(), lambda s: {
        "id": s.pk, "channel": s.channel, "title": s.title, "viewers": s.viewers,
        "language": s.language, "started_at": iso(s.started_at), "tournament_id": s.tournament_id,
    })
