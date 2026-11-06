"""Создаёт группы ролей и назначает им права: python manage.py setup_roles"""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from core.roles import ADMIN_GROUP, ORGANIZER_GROUP, VIEWER_GROUP

PROJECT_APPS = ["core", "tournaments", "matches"]

# Модели, которые организатор может создавать и изменять (удаление — только администратор).
ORGANIZER_EDITABLE = {
    "tournaments": ["tournament", "tournamententry", "tournamentrosterplayer"],
    "matches": ["match", "matchparticipant", "matchmap", "matchmapscore", "playermapstat"],
}


def perms(app_label, models, actions):
    codenames = [f"{a}_{m}" for m in models for a in actions]
    return list(
        Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames)
    )


class Command(BaseCommand):
    help = "Создаёт группы Администратор, Организатор, Зритель и назначает права."

    def handle(self, *args, **options):
        # Администратор: всё в проекте + управление пользователями.
        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
        admin_group.permissions.set(
            Permission.objects.filter(
                content_type__app_label__in=PROJECT_APPS + ["auth"]
            )
        )

        # Организатор: добавление/изменение/просмотр своих данных + просмотр справочников.
        organizer, _ = Group.objects.get_or_create(name=ORGANIZER_GROUP)
        organizer_perms = list(
            Permission.objects.filter(
                content_type__app_label__in=PROJECT_APPS, codename__startswith="view_"
            )
        )
        for app_label, models in ORGANIZER_EDITABLE.items():
            organizer_perms += perms(app_label, models, ["add", "change"])
        organizer.permissions.set(organizer_perms)

        # Зритель: только просмотр.
        viewer, _ = Group.objects.get_or_create(name=VIEWER_GROUP)
        viewer.permissions.set(
            Permission.objects.filter(
                content_type__app_label__in=PROJECT_APPS, codename__startswith="view_"
            )
        )

        self.stdout.write(self.style.SUCCESS("Группы ролей созданы и права назначены."))
