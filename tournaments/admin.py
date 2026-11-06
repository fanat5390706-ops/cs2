from django.contrib import admin

from core.roles import is_admin

from .models import Tournament, TournamentEntry, TournamentRosterPlayer


class RosterInline(admin.TabularInline):
    model = TournamentRosterPlayer
    extra = 0


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ["name", "tier", "prize_pool_usd", "start_date", "end_date", "status", "organizer_name"]
    list_filter = ["status"]
    search_fields = ["name"]

    # Организатор видит и правит только свои турниры; администратор — все.
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if is_admin(request.user) else qs.filter(organizer=request.user)

    def get_readonly_fields(self, request, obj=None):
        return [] if is_admin(request.user) else ["organizer"]

    def save_model(self, request, obj, form, change):
        if not change and not is_admin(request.user):
            obj.organizer = request.user
        super().save_model(request, obj, form, change)


@admin.register(TournamentEntry)
class TournamentEntryAdmin(admin.ModelAdmin):
    list_display = ["tournament", "team"]
    list_filter = ["tournament"]
    inlines = [RosterInline]
