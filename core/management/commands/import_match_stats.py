"""Импорт статистики карт и игроков из CSV (одна строка = один игрок на одной карте).

Колонки: match_id, map_number, map, team1_rounds, team2_rounds, slot, player,
         kills, deaths, assists, hs, damage, rounds
match_id — номер матча на сайте (в адресе /matches/<id>/), slot — 1 или 2 (сторона в матче),
hs — убийства в голову (число), rounds — сыграно раундов (если пусто — сумма раундов карты).
Пример: docs/examples/match_stats.csv
"""
import csv
from collections import OrderedDict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.models import Player
from matches.models import GameMap, Match, MatchMap
from matches.services import PlayerStatInput, record_map
from tournaments.models import TournamentRosterPlayer

REQUIRED = ["match_id", "map_number", "map", "team1_rounds", "team2_rounds", "slot", "player", "kills", "deaths", "assists", "hs", "damage"]


def to_int(value, default=0):
    value = (value or "").strip()
    return int(value) if value else default


class Command(BaseCommand):
    help = "Загрузить статистику карт и игроков из CSV (см. docstring модуля)."

    def add_arguments(self, parser):
        parser.add_argument("csv_file")
        parser.add_argument("--replace", action="store_true", help="заменить уже внесённую карту (удалить и записать заново)")
        parser.add_argument("--dry-run", action="store_true", help="только проверить файл, ничего не сохранять")

    def handle(self, *args, **opts):
        try:
            handle = open(opts["csv_file"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"Не удалось открыть файл: {exc}")
        with handle:
            reader = csv.DictReader(handle)
            missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise CommandError("В файле нет колонок: " + ", ".join(missing))
            groups = OrderedDict()
            for line, row in enumerate(reader, start=2):
                groups.setdefault((row["match_id"].strip(), row["map_number"].strip()), []).append((line, row))

        done = failed = 0
        for (match_id, map_number), rows in groups.items():
            label = f"матч {match_id}, карта {map_number}"
            try:
                self.load_map(match_id, map_number, rows, opts)
                done += 1
                self.stdout.write(f"OK   {label}: {len(rows)} игроков")
            except (ValidationError, ValueError, Match.DoesNotExist) as exc:
                failed += 1
                text = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
                self.stderr.write(f"FAIL {label}: {text}")
        self.stdout.write(self.style.SUCCESS(f"Загружено карт: {done}, с ошибками: {failed}") + (" (dry-run, ничего не сохранено)" if opts["dry_run"] else ""))

    def load_map(self, match_id, map_number, rows, opts):
        match = Match.objects.get(pk=int(match_id))
        first = rows[0][1]
        rounds = {1: to_int(first["team1_rounds"]), 2: to_int(first["team2_rounds"])}
        game_map, _ = GameMap.objects.get_or_create(name=first["map"].strip().capitalize())
        participants = {p.slot: p for p in match.participants.select_related("entry__team")}
        stats = []
        for line, row in rows:
            slot = to_int(row["slot"])
            if slot not in participants:
                raise ValueError(f"строка {line}: slot должен быть 1 или 2")
            entry = participants[slot].entry
            nick = row["player"].strip()
            player = Player.objects.filter(nickname__iexact=nick).first()
            if player is None:
                raise ValueError(f"строка {line}: игрок «{nick}» не найден (сначала импортируйте составы)")
            TournamentRosterPlayer.objects.get_or_create(entry=entry, player=player)
            stats.append(PlayerStatInput(
                player=player, slot=slot, kills=to_int(row["kills"]), deaths=to_int(row["deaths"]),
                assists=to_int(row["assists"]), headshot_kills=to_int(row["hs"]), damage=to_int(row["damage"]),
                rounds_played=to_int(row.get("rounds"), sum(rounds.values())),
            ))
        from django.db import transaction
        with transaction.atomic():
            existing = MatchMap.objects.filter(match=match, map_number=int(map_number))
            if existing.exists():
                if not opts["replace"]:
                    raise ValidationError("карта уже внесена (используйте --replace)")
                existing.delete()
            record_map(match, game_map, int(map_number), rounds, stats, allow_finished=True)
            if opts["dry_run"]:
                transaction.set_rollback(True)
