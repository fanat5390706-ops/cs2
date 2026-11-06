# Архитектура ХЛТВ 2.0

```
PandaScore · Steam · Liquipedia · FACEIT · Twitch · YouTube · NewsAPI
                    │  (HTTP, ключи из .env)
                    ▼
   Воркеры: manage.py sync_* / import_pandascore, расписание — run_workers
                    │
                    ▼
        MySQL (модели Django, CHECK/UNIQUE, SQL-представления)
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
 Сайт (Django Templates)   JSON API /api/...  →  десктоп / мобильные клиенты
```

## Источники и зоны ответственности
| Источник | Что даёт | Команда |
|---|---|---|
| PandaScore (основной) | команды, игроки, турниры, расписание | `import_pandascore` |
| Steam Web API | аватар, профиль, VAC (по SteamID64, который вносится вручную) | `import_steam_ids`, `sync_steam` |
| Liquipedia (CC-BY-SA 3.0) | имя, дата рождения | `sync_liquipedia` |
| FACEIT | ELO, уровень, винрейт | `sync_faceit` |
| Twitch | текущие трансляции CS | `sync_twitch` |
| YouTube | хайлайты по турнирам | `sync_youtube` |
| NewsAPI | новости CS2 | `sync_news` |

HLTV не используется: официального API нет, парсинг запрещён правилами сайта.

## Решения для защиты
- Воркеры — обычные команды Django и цикл `run_workers`, без Celery и Redis: меньше компонентов.
- Внешние данные не заменяют данные пользователя: Liquipedia заполняет только пустые поля, SteamID по нику не угадывается.
- Производные показатели (K/D, ADR, Rating) считаются, а не хранятся; Rating — собственная формула `0.6·K/D + 0.4·ADR/75`, не рейтинг HLTV.
- API только для чтения (POST → 405), пагинация ограничена 100 записями.
- Статистика игроков и результаты на бесплатном PandaScore недоступны, вносятся вручную (демо: `seed_demo`).

## Запуск
`python manage.py run_workers` — постоянно; `python manage.py run_workers --once` — разово; `--only sync_news` — выбранные задачи.
