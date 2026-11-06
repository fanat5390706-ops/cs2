from datetime import date

from django import template

register = template.Library()

STATUS_LABELS = {
    "draft": "Draft",
    "registration": "Upcoming",
    "ongoing": "Ongoing",
    "finished": "Finished",
    "scheduled": "Scheduled",
    "live": "Live",
    "cancelled": "Cancelled",
}

STATUS_CLASSES = {
    "draft": "text-bg-secondary",
    "registration": "text-bg-info",
    "ongoing": "text-bg-warning",
    "finished": "text-bg-success",
    "scheduled": "text-bg-secondary",
    "live": "text-bg-danger",
    "cancelled": "text-bg-danger",
}


@register.filter
def status_label(value):
    return STATUS_LABELS.get(value, value)


@register.filter
def status_class(value):
    return STATUS_CLASSES.get(value, "text-bg-secondary")


@register.filter
def badge_style(tag):
    """Стабильный цвет бейджа команды, вычисляемый из её тега."""
    hue = sum(ord(ch) * (i + 3) for i, ch in enumerate(tag or "")) % 360
    return f"background:hsl({hue} 55% 36%)"


@register.filter
def initials(tag):
    return (tag or "?")[:3].upper()


@register.filter
def flag_url(code):
    if code and len(code) == 2 and code.isalpha():
        return f"https://flagcdn.com/w20/{code.lower()}.png"
    return ""


@register.filter
def hi_class(value, threshold):
    """Выделяет сильные показатели (выше порога) золотым."""
    try:
        return "hi" if float(value) >= float(threshold) else ""
    except (TypeError, ValueError):
        return ""


@register.filter
def age(birth_date):
    """Возраст в полных годах; пусто, если дата рождения неизвестна."""
    if not birth_date:
        return ""
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


@register.filter
def kd_class(value):
    """Окраска K/D: выше единицы — зелёный, ниже — красный."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return "pos" if number >= 1 else "neg"


@register.filter
def intcomma_space(value):
    """1000000 -> 1,000,000"""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value
