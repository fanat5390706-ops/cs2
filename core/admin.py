from django.contrib import admin

from .models import Player, Team, TeamMembership, TeamRanking


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    readonly_fields = ["open_player_key"]


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ["nickname", "first_name", "last_name", "role", "country", "steam_id64", "vac_banned"]
    search_fields = ["nickname", "first_name", "last_name", "steam_id64"]
    readonly_fields = [
        "avatar_url", "steam_profile_url", "vac_banned", "steam_synced_at",
        "liquipedia_page", "liquipedia_synced_at",
        "faceit_player_id", "faceit_elo", "faceit_level", "faceit_matches", "faceit_win_rate", "faceit_kd", "faceit_hs", "faceit_maps", "faceit_synced_at",
    ]
    inlines = [TeamMembershipInline]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "tag", "country", "founded_year"]
    search_fields = ["name", "tag"]


@admin.register(TeamRanking)
class TeamRankingAdmin(admin.ModelAdmin):
    list_display = ["source", "valid_on", "position", "team_name", "team", "points"]
    list_filter = ["source", "valid_on"]
    autocomplete_fields = ["team"]


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ["player", "team", "role", "joined_on", "left_on"]
    list_filter = ["team", "role"]
    search_fields = ["player__nickname", "team__name"]
    readonly_fields = ["open_player_key"]
