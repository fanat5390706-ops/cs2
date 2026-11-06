from django.contrib import admin

from .models import GameMap, Match, MatchMap, MatchMapScore, MatchParticipant, PlayerMapStat


class MatchParticipantInline(admin.TabularInline):
    model = MatchParticipant
    extra = 2
    max_num = 2


class MatchMapInline(admin.TabularInline):
    model = MatchMap
    extra = 0
    max_num = 5


class MatchMapScoreInline(admin.TabularInline):
    model = MatchMapScore
    extra = 2
    max_num = 2


class PlayerMapStatInline(admin.TabularInline):
    model = PlayerMapStat
    extra = 0


@admin.register(GameMap)
class GameMapAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ["tournament", "stage", "scheduled_at", "best_of", "status"]
    list_filter = ["tournament", "status", "best_of"]
    inlines = [MatchParticipantInline, MatchMapInline]


@admin.register(MatchMap)
class MatchMapAdmin(admin.ModelAdmin):
    list_display = ["match", "map_number", "game_map"]
    list_filter = ["game_map"]
    inlines = [MatchMapScoreInline, PlayerMapStatInline]
