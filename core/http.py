"""Минимальный HTTP-клиент для внешних API (без сторонних библиотек)."""
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.core.management.base import CommandError


def get_json(url, params=None, headers=None, pause=0.3, retries=3):
    """GET-запрос, возвращает разобранный JSON. При 429 ждёт и повторяет."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    for _ in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8"))
            time.sleep(pause)
            return data
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(30)
                continue
            if error.code == 404:
                return None
            if error.code in (401, 403):
                raise CommandError(f"Доступ запрещён (HTTP {error.code}): проверьте ключ API.")
            raise CommandError(f"HTTP {error.code} при обращении к {url.split('?')[0]}")
        except urllib.error.URLError as error:
            raise CommandError(f"Нет связи с {url.split('?')[0]}: {error.reason}")
    raise CommandError("Слишком много запросов, повторите позже.")


def get_text(url, headers=None, pause=0.3):
    """GET, возвращает текст ответа (для markdown-файлов и т. п.). 404 -> None."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
        time.sleep(pause)
        return text
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise CommandError(f"HTTP {error.code} при обращении к {url.split('?')[0]}")
    except urllib.error.URLError as error:
        raise CommandError(f"Нет связи с {url.split('?')[0]}: {error.reason}")


def post_form(url, data, pause=0.3):
    """POST application/x-www-form-urlencoded, возвращает JSON (нужно для OAuth-токена Twitch)."""
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), method="POST",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        time.sleep(pause)
        return result
    except urllib.error.HTTPError as error:
        raise CommandError(f"HTTP {error.code} при обращении к {url.split('?')[0]}: проверьте ключи.")
    except urllib.error.URLError as error:
        raise CommandError(f"Нет связи с {url.split('?')[0]}: {error.reason}")
