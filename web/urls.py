from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("maps/", views.map_list, name="maps"),
    path("signup/", views.signup, name="signup"),
    path("matches/", views.matches, name="matches"),
    path("results/", views.results, name="results"),
    path("stats/", views.stats, name="stats"),
    path("news/", views.news_list, name="news_list"),
    path("videos/", views.video_list, name="video_list"),
    path("search/", views.search, name="search"),
    path("tournaments/", views.tournament_list, name="tournament_list"),
    path("tournaments/<int:pk>/", views.tournament_detail, name="tournament_detail"),
    path("matches/<int:pk>/", views.match_detail, name="match_detail"),
    path("teams/", views.team_list, name="team_list"),
    path("teams/<int:pk>/", views.team_detail, name="team_detail"),
    path("tournaments/<int:pk>/follow/", views.tournament_follow, name="tournament_follow"),
    path("teams/<int:pk>/favorite/", views.team_favorite, name="team_favorite"),
    path("players/", views.player_list, name="player_list"),
    path("players/<int:pk>/", views.player_detail, name="player_detail"),
]
