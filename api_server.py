"""
Веб-сервер для Telegram Mini App — отдаёт те же данные, что и бот в чате,
но по HTTP, чтобы фронтенд (статика на GitHub Pages) мог их запрашивать.

Работает в том же процессе, что и bot.py (см. main() в bot.py), слушает
порт из переменной окружения PORT (Railway подставляет её сам).

Проверка подлинности запросов — через initData, которую Telegram Mini App
передаёт автоматически (Telegram.WebApp.initData). Мы проверяем подпись
HMAC-SHA256 согласно официальному алгоритму Telegram, чтобы быть уверены,
что запрос реально пришёл из мини-приложения конкретного пользователя,
а не подделан кем-то извне.
"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web

import stats
from odds_api import fetch_odds
from combo_builder import build_combo

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
FREE_TRIAL_EXPRESSES = 1
REFERRAL_BONUS_DAYS = 7
DEFAULT_HOURS_WINDOW = 24
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")  # без @, например shapitisto_bot

# Разрешаем запросы с любого источника (GitHub Pages), т.к. это публичный
# read-mostly API без чувствительных операций, защищённый подписью Telegram.
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _validate_init_data(init_data: str) -> dict | None:
    """
    Проверяет подпись initData от Telegram Mini App.
    Возвращает распарсенные данные пользователя, либо None если подпись неверна.
    Алгоритм: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data or not BOT_TOKEN:
        return None

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    # initData протухает — не принимаем слишком старые (защита от replay)
    auth_date = int(parsed.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None

    return user


def _cors_response(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers=CORS_HEADERS)


async def handle_options(request: web.Request) -> web.Response:
    return web.Response(headers=CORS_HEADERS)


async def handle_health(request: web.Request) -> web.Response:
    return _cors_response({"ok": True})


async def handle_account(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _cors_response({"ok": False, "error": "bad_request"}, status=400)

    user = _validate_init_data(body.get("initData", ""))
    if not user:
        return _cors_response({"ok": False, "error": "unauthorized"}, status=401)

    user_id = user["id"]
    stats.track_user(user_id, user.get("username"))
    info = stats.get_account_info(user_id)
    ref_stats = stats.get_referral_stats(user_id)

    referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}" if BOT_USERNAME else None

    return _cors_response({
        "ok": True,
        "subscribed": info["subscribed"],
        "expires_at": info["expires_at"].isoformat() if info["expires_at"] else None,
        "express_count": info["express_count"],
        "free_trial_remaining": max(0, FREE_TRIAL_EXPRESSES - info["express_count"]),
        "referral_link": referral_link,
        "referral_bonus_days": REFERRAL_BONUS_DAYS,
        "referral_invited": ref_stats["total_invited"],
        "referral_rewarded": ref_stats["rewarded_count"],
    })


async def handle_express(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _cors_response({"ok": False, "error": "bad_request"}, status=400)

    user = _validate_init_data(body.get("initData", ""))
    if not user:
        return _cors_response({"ok": False, "error": "unauthorized"}, status=401)

    user_id = user["id"]
    stats.track_user(user_id, user.get("username"))

    try:
        target_odds = float(body.get("target_odds"))
    except (TypeError, ValueError):
        return _cors_response({"ok": False, "error": "invalid_target_odds"}, status=400)

    if not stats.access_allowed(user_id, ADMIN_ID, FREE_TRIAL_EXPRESSES):
        return _cors_response({"ok": False, "error": "subscription_required"}, status=402)

    try:
        events = await fetch_odds(hours_window=DEFAULT_HOURS_WINDOW)
    except Exception as e:
        return _cors_response({"ok": False, "error": f"odds_fetch_failed: {e}"}, status=502)

    if not events:
        return _cors_response({"ok": False, "error": "no_events"}, status=404)

    combo = build_combo(events, target_odds=target_odds)
    if not combo:
        return _cors_response({"ok": False, "error": "no_combo_found"}, status=404)

    total = 1.0
    for leg in combo:
        total *= leg["odds"]

    stats.track_express(user_id, target_odds, total_odds=total, combo=combo)

    return _cors_response({
        "ok": True,
        "target_odds": target_odds,
        "total_odds": round(total, 2),
        "combo": combo,
    })


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/account", handle_account)
    app.router.add_post("/api/express", handle_express)
    return app


async def run_webapp_server():
    port = int(os.environ.get("PORT", "8080"))
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[webapp] API сервер слушает порт {port}")
    # держим корутину живой бесконечно
    import asyncio
    while True:
        await asyncio.sleep(3600)
