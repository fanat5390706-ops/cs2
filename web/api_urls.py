from django.urls import path

from . import api

app_name = "api"

urlpatterns = [
    path("", api.index, name="index"),
    path("teams/", api.teams, name="teams"),
    path("teams/<int:pk>/", api.team_detail, name="team_detail"),
    path("players/", api.players, name="players"),
    path("players/<int:pk>/", api.player_detail, name="player_detail"),
    path("tournaments/", api.tournaments, name="tournaments"),
    path("tournaments/<int:pk>/", api.tournament_detail, name="tournament_detail"),
    path("matches/", api.matches, name="matches"),
    path("matches/<int:pk>/", api.match_detail, name="match_detail"),
    path("news/", api.news, name="news"),
    path("videos/", api.videos, name="videos"),
    path("streams/", api.streams, name="streams"),
]
