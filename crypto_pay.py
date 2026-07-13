"""
Обёртка над Crypto Pay API (@CryptoBot) для приёма платежей криптой.

Как получить токен:
1. Открой в Telegram @CryptoBot (или @CryptoTestnetBot для тестовой сети)
2. Crypto Pay → Create App
3. Скопируй API-токен приложения

Документация: https://help.crypt.bot/crypto-pay-api
"""

import os
import aiohttp

CRYPTO_PAY_TOKEN = os.environ.get("CRYPTO_PAY_TOKEN", "")

# Основная сеть — реальные деньги. Для тестов можно переключить на testnet
# (тогда нужен токен от @CryptoTestnetBot и testnet-адрес ниже).
BASE_URL = os.environ.get("CRYPTO_PAY_BASE_URL", "https://pay.crypt.bot/api")


async def _call(method: str, params: dict) -> dict:
    if not CRYPTO_PAY_TOKEN:
        raise RuntimeError("Задай переменную окружения CRYPTO_PAY_TOKEN")

    url = f"{BASE_URL}/{method}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=params, headers=headers) as resp:
            data = await resp.json()

    if not data.get("ok"):
        raise RuntimeError(f"Crypto Pay API error: {data}")

    return data["result"]


async def create_invoice(amount: float, asset: str, description: str, payload: str) -> dict:
    """
    Создаёт счёт на оплату.
    asset: например "USDT", "TON", "BTC" — см. список поддерживаемых в доке.
    payload: произвольная строка, вернётся при проверке статуса (кладём сюда user_id).
    Возвращает dict с полями invoice_id, pay_url (и другими).
    """
    return await _call("createInvoice", {
        "amount": str(amount),
        "asset": asset,
        "description": description,
        "payload": payload,
    })


async def get_invoice(invoice_id: int) -> dict | None:
    """Возвращает данные счёта (включая статус: active/paid/expired) или None если не найден."""
    result = await _call("getInvoices", {"invoice_ids": str(invoice_id)})
    items = result.get("items", [])
    return items[0] if items else None
