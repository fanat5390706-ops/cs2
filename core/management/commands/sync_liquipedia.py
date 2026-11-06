"""Биография игроков из Liquipedia (MediaWiki API, CC-BY-SA 3.0).

    python manage.py sync_liquipedia [--limit 100] [--dry-run]

Правила API Liquipedia, которые соблюдает команда: свой User-Agent с контактом
(LIQUIPEDIA_CONTACT в .env), не чаще 1 запроса в 2 секунды, запрос по 50 страниц
сразу, без action=parse, повторно уже обработанных игроков не запрашивает.

Из инфобокса {{Infobox player}} берутся: настоящее имя и дата рождения —
только если они ещё не заполнены. Страница засчитывается, лишь если её id
совпадает с ником, а дата рождения (если известна) не противоречит.
Ограничение: история трансферов в MediaWiki-разметке не хранится
(она строится из LiquipediaDB, доступ к которой выдаётся по заявке),
поэтому здесь не импортируется.
"""
import os
import re

from django.core.management.base import BaseCommand, CommandError
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core.http import get_json
from core.models import Player

API = "https://liquipedia.net/counterstrike/api.php"
PAUSE = 2.2  # правило API: не чаще 1 запроса в 2 секунды
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def parse_infobox(wikitext):
    """Возвращает словарь параметров {{Infobox player}} или None."""
    start = re.search(r"\{\{\s*Infobox player", wikitext, re.I)
    if not start:
        return None
    params = {}
    for line in wikitext[start.end():].splitlines():
        if line.startswith("}}"):
            break
        m = re.match(r"\|\s*([\w_]+)\s*=\s*(.*)$", line)
        if m:
            params[m.group(1).lower()] = m.group(2).strip()
    return params


class Command(BaseCommand):
    help = "Дополняет игроков данными из Liquipedia."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=300, help="Сколько игроков обработать за запуск.")
        parser.add_argument("--dry-run", action="store_true", help="Только показать, что найдено.")

    def handle(self, *args, **options):
        contact = os.environ.get("LIQUIPEDIA_CONTACT", "").strip()
        if not contact or contact == "change-me":
            raise CommandError("Задайте LIQUIPEDIA_CONTACT в .env: Liquipedia требует контакт в User-Agent.")
        headers = {"User-Agent": f"XLTV2-student-project/1.0 ({contact})", "Accept-Encoding": "gzip"}

        stale = timezone.now() - timedelta(days=30)
        players = list(
            Player.objects.filter(Q(liquipedia_synced_at__isnull=True) | Q(liquipedia_synced_at__lt=stale)).order_by("id")[: options["limit"]]
        )
        by_title = {p.nickname.lower(): p for p in players}
        found = 0
        for i in range(0, len(players), 50):
            chunk = players[i : i + 50]
            data = get_json(
                API,
                {
                    "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
                    "prop": "revisions", "rvprop": "content", "rvslots": "main",
                    "titles": "|".join(p.nickname for p in chunk),
                },
                headers,
                pause=PAUSE,
            ) or {}
            for page in (data.get("query") or {}).get("pages", []):
                if page.get("missing") or not page.get("revisions"):
                    continue
                text = page["revisions"][0]["slots"]["main"]["content"]
                info = parse_infobox(text)
                player = by_title.get((info or {}).get("id", "").lower()) if info else None
                if player is None:
                    continue  # страница не про игрока или id не совпал с ником
                born = DATE.search(info.get("birth_date", ""))
                born = born and __import__("datetime").date(*map(int, born.groups()))
                if born and player.birth_date and born != player.birth_date:
                    self.stdout.write(self.style.WARNING(f"{player.nickname}: дата рождения не совпала, пропуск."))
                    continue
                changed = {"liquipedia_page": page["title"][:100], "liquipedia_synced_at": timezone.now()}
                if born and not player.birth_date:
                    changed["birth_date"] = born
                real = re.sub(r"\[\[|\]\]|\{\{.*?\}\}", "", info.get("name", "")).strip()
                if real and not (player.first_name or player.last_name):
                    first, _, last = real.partition(" ")
                    changed["first_name"], changed["last_name"] = first[:100], last[:100]
                found += 1
                self.stdout.write(f"{player.nickname}: {page['title']}" + (" (пробный запуск)" if options["dry_run"] else ""))
                if not options["dry_run"]:
                    for field, value in changed.items():
                        setattr(player, field, value)
                    player.save(update_fields=list(changed))
        if not options["dry_run"]:  # ненайденных тоже отмечаем, иначе команда будет снова брать одних и тех же
            Player.objects.filter(pk__in=[p.pk for p in players], liquipedia_synced_at__isnull=True).update(
                liquipedia_synced_at=timezone.now()
            )
        self.stdout.write(self.style.SUCCESS(f"Liquipedia: найдено {found} из {len(players)}."))
