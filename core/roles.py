"""Роли системы: реализованы группами Django Auth."""

ADMIN_GROUP = "Администратор"
ORGANIZER_GROUP = "Организатор"
VIEWER_GROUP = "Зритель"


def is_admin(user) -> bool:
    return user.is_superuser or user.groups.filter(name=ADMIN_GROUP).exists()
