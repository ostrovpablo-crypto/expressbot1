"""
Получение реальных коэффициентов через SharpAPI (sharpapi.io).

Как получить ключ:
1. Зайди на https://sharpapi.io, зарегистрируйся (карта не нужна)
2. В личном кабинете возьми API-ключ
3. Задай переменную окружения SHARPAPI_KEY

БУКМЕКЕРЫ: по умолчанию используются Betway, bwin, Betano, Bet365 US, Unibet
(выбраны вручную в личном кабинете SharpAPI). Можно переопределить через
переменную окружения SHARPAPI_BOOKS (через запятую, без пробелов).

ВАЖНО: часть букмекеров в списке SharpAPI помечена замком ("Sharp"-тир) —
доступна только на платных планах (например Stake, Ladbrokes, SBOBET,
Pinnacle-подобные "sharp" книги). Если в SHARPAPI_BOOKS указать
недоступный на твоём тарифе букмекер, API вернёт 403 для него.

ЛИМИТЫ: бесплатный тариф — 12 запросов/минуту (17280/день), без месячного
потолка.
"""

import os
import asyncio
import datetime as dt
from typing import List, Dict

import aiohttp

SHARPAPI_KEY = os.environ.get("SHARPAPI_KEY", "")
BASE_URL = "https://api.sharpapi.io/api/v1"

# Букмекеры, выбранные вручную в личном кабинете SharpAPI.
# Слаги — лучшее предположение по названиям; если какой-то не совпадёт
# с реальным API, будет видно по ошибке в логах (см. диагностику ниже).
# На платном тарифе доступны все букмекеры — по умолчанию НЕ ограничиваем
# список, чтобы получить максимальный охват событий и лиг. Можно всё же
# сузить через переменную SHARPAPI_BOOKS, если понадобится.
SPORTSBOOKS = os.environ.get("SHARPAPI_BOOKS", "")

PAGE_LIMIT = 100
MAX_PAGES = 60   # больше не ограничиваемся узким набором букмекеров — данных будет намного больше
REQUEST_DELAY_SECONDS = 0.6   # тариф даёт 120 запросов/минуту — держим темп чуть ниже лимита
REQUEST_TIMEOUT = 15

CACHE_TTL_SECONDS = 300
_cache = {"timestamp": None, "events": None}

MARKET_LABELS = {
    "moneyline": "Победа",
    "spread": "Фора",
    "total": "Тотал",
}


async def _get(session: aiohttp.ClientSession, path: str, params: dict):
    url = f"{BASE_URL}/{path}"
    headers = {"X-API-Key": SHARPAPI_KEY}
    try:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(f"[sharpapi] {path}: HTTP {resp.status} - {body[:200]}")
                return None
            return await resp.json()
    except asyncio.TimeoutError:
        print(f"[sharpapi] {path}: таймаут запроса")
        return None
    except Exception as e:
        print(f"[sharpapi] {path}: ошибка {e}")
        return None


async def _fetch_all_odds_rows(session: aiohttp.ClientSession) -> List[Dict]:
    all_rows = []
    offset = 0
    total_available = None

    for page in range(MAX_PAGES):
        params = {
            "live": "false",   # только предматчевые линии
            "limit": PAGE_LIMIT,
            "offset": offset,
        }
        if SPORTSBOOKS:
            params["sportsbook"] = SPORTSBOOKS

        data = await _get(session, "odds", params)
        if not data:
            break

        rows = data.get("data", [])
        all_rows.extend(rows)

        meta = data.get("meta", {})
        pagination = meta.get("pagination", {})
        if page == 0:
            total_available = meta.get("total")
            print(f"[sharpapi] всего строк коэффициентов доступно: {total_available}, "
                  f"букмекеры: {SPORTSBOOKS or 'все доступные на тарифе'}")

        if not pagination.get("has_more"):
            break
        offset = pagination.get("next_offset", offset + PAGE_LIMIT)

        # если знаем общее число строк — не листаем больше, чем нужно
        if total_available is not None and offset >= total_available:
            break

        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    print(f"[sharpapi] загружено строк коэффициентов: {len(all_rows)}")
    return all_rows


def _group_rows_into_events(rows: List[Dict]) -> List[Dict]:
    events_map = {}

    for row in rows:
        if row.get("is_live"):
            continue  # лайв-коэффициенты волатильны — берём только предматчевые

        sport = row.get("sport", "")
        home = row.get("home_team")
        away = row.get("away_team")
        market_type = row.get("market_type", "")
        selection = row.get("selection")
        odds_decimal = row.get("odds_decimal")

        if not home or not away or odds_decimal is None or not selection:
            continue

        key = (sport, home, away)
        if key not in events_map:
            events_map[key] = {
                "match": f"{home} vs {away}",
                "sport": sport,
                "commence_time": "скоро",
                "outcomes": [],
            }

        label = MARKET_LABELS.get(market_type, market_type or "Ставка")
        events_map[key]["outcomes"].append({
            "name": f"{label}: {selection}",
            "odds": odds_decimal,
        })

    return list(events_map.values())


async def fetch_odds(hours_window: int) -> List[Dict]:
    """
    hours_window сохранён в сигнатуре для совместимости с остальным кодом,
    но сейчас не используется для строгой фильтрации — /odds не отдаёт
    точное время начала в ответе, только is_live.
    """
    if not SHARPAPI_KEY:
        raise RuntimeError("Задай переменную окружения SHARPAPI_KEY")

    now_ts = dt.datetime.utcnow()

    if (
        _cache["timestamp"] is not None
        and (now_ts - _cache["timestamp"]).total_seconds() < CACHE_TTL_SECONDS
    ):
        print(f"[sharpapi] отдаю данные из кэша ({len(_cache['events'])} событий)")
        return _cache["events"]

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        rows = await _fetch_all_odds_rows(session)

    events = _group_rows_into_events(rows)
    print(f"[sharpapi] сгруппировано в {len(events)} событий")

    _cache["timestamp"] = now_ts
    _cache["events"] = events

    return events
