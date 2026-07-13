"""
Telegram-бот: подбор экспресса под заданный суммарный коэффициент
и заданное временное окно событий.

Стек: aiogram 3.x + The Odds API (https://the-odds-api.com/)

Запуск:
    pip install -r requirements.txt
    export BOT_TOKEN=...      # токен от @BotFather
    export ODDS_API_KEY=...   # ключ с the-odds-api.com
    python bot.py
"""

import asyncio
import logging
import os
import datetime as dt

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from odds_api import fetch_odds
from combo_builder import build_combo
from express_image import render_express_image
import stats
import crypto_pay
import api_server

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("Задай переменную окружения BOT_TOKEN")

# Твой Telegram ID (числовой) — только этому пользователю будет доступна команда /stats.
# Узнать свой ID можно у бота @userinfobot в Telegram.
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Настройки подписки
SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_PRICE = 5      # сумма
SUBSCRIPTION_ASSET = "USDT"  # валюта: USDT, TON, BTC и т.д. — см. доку Crypto Pay
FREE_TRIAL_EXPRESSES = 1     # сколько экспрессов доступно без подписки
REFERRAL_BONUS_DAYS = 7      # сколько дней подписки получает пригласивший, когда приглашённый впервые оплатит

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Состояния диалога ---

class ExpressFlow(StatesGroup):
    choosing_odds = State()

class BroadcastFlow(StatesGroup):
    waiting_text = State()
    confirming = State()

DEFAULT_HOURS_WINDOW = 24

# --- Клавиатуры ---

ODDS_OPTIONS = [1.5, 2.0, 3.0, 5.0, 10.0]

def odds_keyboard():
    kb = InlineKeyboardBuilder()
    for val in ODDS_OPTIONS:
        kb.button(text=f"x{val}", callback_data=f"odds:{val}")
    kb.button(text="Свой коэффициент", callback_data="odds:custom")
    kb.adjust(3)
    return kb.as_markup()

# --- Хендлеры ---

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    stats.track_user(message.from_user.id, message.from_user.username)

    # Реферальная ссылка выглядит как /start ref_123456789
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1].removeprefix("ref_"))
            stats.record_referral(message.from_user.id, referrer_id)
        except ValueError:
            pass

    await state.clear()
    await message.answer(
        "Привет! Я подбираю экспресс под нужный тебе суммарный коэффициент.\n\n"
        "Выбери целевой коэффициент:",
        reply_markup=odds_keyboard(),
    )
    await state.set_state(ExpressFlow.choosing_odds)

@dp.message(F.text.startswith("/grant"))
async def grant_subscription(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "Использование: /grant <user_id> [дней]\n"
            "Например: /grant 123456789 30\n"
            "Если дни не указать — выдаётся стандартный срок подписки "
            f"({SUBSCRIPTION_DAYS} дней)."
        )
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("user_id должен быть числом.")
        return

    days = SUBSCRIPTION_DAYS
    if len(parts) >= 3:
        try:
            days = int(parts[2])
        except ValueError:
            await message.answer("Количество дней должно быть числом.")
            return

    new_expiry = stats.extend_subscription(target_id, days)

    await message.answer(
        f"✅ Выдал подписку на {days} дней пользователю {target_id}.\n"
        f"Действует до {new_expiry.strftime('%d.%m.%Y %H:%M')} UTC."
    )

    try:
        await bot.send_message(
            target_id,
            "🎁 Вы получили подписку от владельца проекта. Наслаждайтесь сервисом!\n\n"
            f"Подписка активна до {new_expiry.strftime('%d.%m.%Y %H:%M')} UTC."
        )
    except Exception:
        await message.answer(
            "⚠️ Не удалось отправить уведомление пользователю "
            "(возможно, он ещё не писал боту /start)."
        )


_bot_username_cache = None

async def _get_bot_username() -> str:
    global _bot_username_cache
    if _bot_username_cache is None:
        me = await bot.get_me()
        _bot_username_cache = me.username
    return _bot_username_cache


@dp.callback_query(F.data == "referral:show")
async def show_referral(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()

    username = await _get_bot_username()
    link = f"https://t.me/{username}?start=ref_{user_id}"
    ref_stats = stats.get_referral_stats(user_id)

    text = (
        "🔗 Твоя реферальная ссылка:\n\n"
        f"{link}\n\n"
        f"Приглашено: {ref_stats['total_invited']}\n"
        f"Оформили подписку: {ref_stats['rewarded_count']}\n\n"
        f"За каждого друга, который оформит подписку, тебе начисляется "
        f"+{REFERRAL_BONUS_DAYS} дней подписки."
    )

    await callback.message.answer(text, reply_markup=after_express_keyboard())


@dp.message(F.text == "/referral")
async def referral_command(message: Message):
    user_id = message.from_user.id
    username = await _get_bot_username()
    link = f"https://t.me/{username}?start=ref_{user_id}"
    ref_stats = stats.get_referral_stats(user_id)

    text = (
        "🔗 Твоя реферальная ссылка:\n\n"
        f"{link}\n\n"
        f"Приглашено: {ref_stats['total_invited']}\n"
        f"Оформили подписку: {ref_stats['rewarded_count']}\n\n"
        f"За каждого друга, который оформит подписку, тебе начисляется "
        f"+{REFERRAL_BONUS_DAYS} дней подписки."
    )

    await message.answer(text, reply_markup=after_express_keyboard())


def subscribe_keyboard(pay_url: str, invoice_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url=pay_url)
    kb.button(text="✅ Я оплатил, проверить", callback_data=f"check_payment:{invoice_id}")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(F.text == "/subscribe")
async def subscribe_start(message: Message):
    user_id = message.from_user.id

    if stats.is_subscribed(user_id):
        expiry = stats.get_subscription_expiry(user_id)
        await message.answer(
            f"У тебя уже активна подписка до {expiry.strftime('%d.%m.%Y %H:%M')} UTC."
        )
        return

    try:
        invoice = await crypto_pay.create_invoice(
            amount=SUBSCRIPTION_PRICE,
            asset=SUBSCRIPTION_ASSET,
            description=f"Подписка на {SUBSCRIPTION_DAYS} дней — express bot",
            payload=str(user_id),
        )
    except Exception:
        logging.exception("Ошибка создания счёта Crypto Pay")
        await message.answer(
            "Не удалось создать счёт на оплату. Проверь CRYPTO_PAY_TOKEN и попробуй позже."
        )
        return

    await message.answer(
        f"Подписка на {SUBSCRIPTION_DAYS} дней — {SUBSCRIPTION_PRICE} {SUBSCRIPTION_ASSET}.\n\n"
        "Оплати по кнопке ниже, затем нажми «Я оплатил, проверить».",
        reply_markup=subscribe_keyboard(invoice["pay_url"], invoice["invoice_id"]),
    )


@dp.callback_query(F.data.startswith("check_payment:"))
async def check_payment(callback: CallbackQuery):
    invoice_id = int(callback.data.split(":")[1])

    try:
        invoice = await crypto_pay.get_invoice(invoice_id)
    except Exception:
        logging.exception("Ошибка проверки счёта Crypto Pay")
        await callback.answer("Не удалось проверить оплату, попробуй позже.", show_alert=True)
        return

    if not invoice:
        await callback.answer("Счёт не найден.", show_alert=True)
        return

    if invoice["status"] != "paid":
        await callback.answer("Оплата пока не поступила. Попробуй ещё раз через минуту.", show_alert=True)
        return

    user_id = int(invoice["payload"])
    new_expiry = stats.extend_subscription(user_id, SUBSCRIPTION_DAYS)

    await callback.message.answer(
        f"✅ Оплата получена! Подписка активна до {new_expiry.strftime('%d.%m.%Y %H:%M')} UTC."
    )

    referrer_id = stats.reward_referrer_if_needed(user_id, REFERRAL_BONUS_DAYS)
    if referrer_id:
        try:
            await bot.send_message(
                referrer_id,
                f"🎉 Твой друг оформил подписку! Тебе начислено +{REFERRAL_BONUS_DAYS} дней подписки."
            )
        except Exception:
            pass  # реферер мог заблокировать бота — не критично

    await callback.answer()


def after_express_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Новый экспресс", callback_data="restart:new")
    kb.button(text="📜 История экспрессов", callback_data="history:show")
    kb.button(text="👤 Личный кабинет", callback_data="account:show")
    kb.button(text="🔗 Пригласить друга", callback_data="referral:show")
    kb.button(text="⬅️ В начало", callback_data="restart:start")
    kb.adjust(1)
    return kb.as_markup()


async def build_and_send_express(message: Message, target_odds: float, user_id: int):
    await message.answer("Собираю пресс, пока вам мацают шляпу на яхте...")

    try:
        events = await fetch_odds(hours_window=DEFAULT_HOURS_WINDOW)
    except Exception as e:
        logging.exception("Ошибка получения коэффициентов")
        await message.answer(
            "Не удалось получить данные по коэффициентам. Проверь ODDS_API_KEY "
            "и лимиты запросов на the-odds-api.com.",
            reply_markup=after_express_keyboard(),
        )
        return

    if not events:
        await message.answer(
            "На ближайшие 24 часа не нашлось событий с коэффициентами. "
            "Попробуй позже.",
            reply_markup=after_express_keyboard(),
        )
        return

    combo = build_combo(events, target_odds=target_odds)

    if not combo:
        await message.answer(
            f"Не получилось собрать комбинацию под коэффициент x{target_odds} "
            "из доступных событий за ближайшие 24 часа. Попробуй другой коэффициент.",
            reply_markup=after_express_keyboard(),
        )
        return

    lines = ["📋 Подробности экспресса:\n"]
    total = 1.0
    for i, leg in enumerate(combo, start=1):
        total *= leg["odds"]
        lines.append(
            f"{i}. [{leg['sport']}] {leg['match']}\n"
            f"   Ставка: {leg['outcome']}\n"
            f"   Коэффициент: x{leg['odds']}   Начало: {leg['commence_time']}\n"
        )
    lines.append(f"Итоговый коэффициент: x{round(total, 2)} (цель была x{target_odds})")
    lines.append(
        "\nЭто просто математическая комбинация реальных коэффициентов букмекера "
        "под твой запрос. Это не прогноз и не гарантия исхода — оценивай риски сам."
    )

    stats.track_express(user_id, target_odds, total_odds=total, combo=combo)

    try:
        image_bytes = render_express_image(combo, total_odds=total, target_odds=target_odds)
        photo = BufferedInputFile(image_bytes, filename="express.png")
        await message.answer_photo(
            photo,
            caption=f"🎯 Экспресс из {len(combo)} событий · x{round(total, 2)}",
        )
    except Exception:
        logging.exception("Не удалось отрисовать картинку экспресса, отправляю только текстом")

    await message.answer("\n".join(lines), reply_markup=after_express_keyboard())


@dp.callback_query(ExpressFlow.choosing_odds, F.data.startswith("odds:"))
async def odds_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":")[1]
    if value == "custom":
        await callback.message.answer("Введи коэффициент числом, например 2.4")
        await callback.answer()
        return
    await state.clear()
    await callback.answer()

    if not stats.access_allowed(callback.from_user.id, ADMIN_ID, FREE_TRIAL_EXPRESSES):
        await callback.message.answer(
            "Бесплатная попытка уже использована. Оформи подписку командой /subscribe, "
            "чтобы собирать экспрессы дальше."
        )
        return

    await build_and_send_express(callback.message, float(value), callback.from_user.id)

@dp.message(ExpressFlow.choosing_odds)
async def custom_odds_entered(message: Message, state: FSMContext):
    try:
        value = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Не понял число, попробуй ещё раз, например: 2.4")
        return
    await state.clear()

    if not stats.access_allowed(message.from_user.id, ADMIN_ID, FREE_TRIAL_EXPRESSES):
        await message.answer(
            "Бесплатная попытка уже использована. Оформи подписку командой /subscribe, "
            "чтобы собирать экспрессы дальше."
        )
        return

    await build_and_send_express(message, value, message.from_user.id)


@dp.callback_query(F.data == "restart:new")
async def restart_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "Выбери целевой коэффициент:",
        reply_markup=odds_keyboard(),
    )
    await state.set_state(ExpressFlow.choosing_odds)
    await callback.answer()


@dp.callback_query(F.data == "restart:start")
async def restart_to_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "Привет! Я подбираю экспресс под нужный тебе суммарный коэффициент.\n\n"
        "Выбери целевой коэффициент:",
        reply_markup=odds_keyboard(),
    )
    await state.set_state(ExpressFlow.choosing_odds)
    await callback.answer()


@dp.message(F.text == "/stats")
async def show_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return  # молча игнорируем для всех, кроме админа

    data = stats.get_stats()

    lines = [
        "📊 Статистика бота\n",
        f"Всего уникальных пользователей: {data['total_users']}",
        f"Активны сегодня: {data['active_today']}",
        f"Активны за неделю: {data['active_week']}",
        f"Всего собрано экспрессов: {data['total_express']}",
    ]

    if data["top_users"]:
        lines.append("\nТоп по активности:")
        for username, user_id, cnt in data["top_users"]:
            name = f"@{username}" if username else f"id{user_id}"
            lines.append(f"  {name} — {cnt} экспрессов")

    await message.answer("\n".join(lines))


@dp.message(F.text == "/broadcast")
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "Пришли текст сообщения, которое разослать всем пользователям бота.\n"
        "Или /cancel чтобы отменить."
    )
    await state.set_state(BroadcastFlow.waiting_text)


@dp.message(BroadcastFlow.waiting_text, F.text == "/cancel")
async def broadcast_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Рассылка отменена.")


@dp.message(BroadcastFlow.waiting_text)
async def broadcast_text_received(message: Message, state: FSMContext):
    user_ids = stats.get_all_user_ids()
    await state.update_data(broadcast_text=message.text, user_ids=user_ids)

    kb = InlineKeyboardBuilder()
    kb.button(text=f"✅ Отправить ({len(user_ids)} чел.)", callback_data="broadcast:confirm")
    kb.button(text="❌ Отмена", callback_data="broadcast:cancel")
    kb.adjust(1)

    await message.answer(
        f"Получателей: {len(user_ids)}\n\nТекст сообщения:\n\n{message.text}",
        reply_markup=kb.as_markup(),
    )
    await state.set_state(BroadcastFlow.confirming)


@dp.callback_query(BroadcastFlow.confirming, F.data == "broadcast:cancel")
async def broadcast_confirm_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Рассылка отменена.")
    await callback.answer()


@dp.callback_query(BroadcastFlow.confirming, F.data == "broadcast:confirm")
async def broadcast_confirm_send(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data["broadcast_text"]
    user_ids = data["user_ids"]
    await state.clear()
    await callback.answer()

    await callback.message.answer(f"Начинаю рассылку на {len(user_ids)} чел...")

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # чтобы не упереться в лимиты Telegram на отправку

    await callback.message.answer(f"Готово. Доставлено: {sent}, не доставлено: {failed}.")


@dp.callback_query(F.data == "history:show")
async def show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    history = stats.get_user_express_history(user_id, limit=10)
    await callback.answer()

    if not history:
        await callback.message.answer(
            "У тебя пока нет собранных экспрессов.",
            reply_markup=after_express_keyboard(),
        )
        return

    lines = ["📜 Твои последние экспрессы:\n"]
    for i, item in enumerate(history, start=1):
        try:
            created = dt.datetime.fromisoformat(item["created_at"]).strftime("%d.%m %H:%M")
        except Exception:
            created = item["created_at"]

        total = item["total_odds"]
        total_str = f"x{round(total, 2)}" if total else "?"
        legs_count = len(item["combo"])

        lines.append(
            f"{i}. {created} UTC — цель x{item['target_odds']}, "
            f"собрано {total_str} ({legs_count} событий)"
        )

    await callback.message.answer("\n".join(lines), reply_markup=after_express_keyboard())


@dp.callback_query(F.data == "account:show")
async def show_account(callback: CallbackQuery):
    user_id = callback.from_user.id
    info = stats.get_account_info(user_id)
    await callback.answer()

    lines = ["👤 Личный кабинет\n"]

    if info["subscribed"]:
        lines.append(f"Подписка: ✅ активна до {info['expires_at'].strftime('%d.%m.%Y %H:%M')} UTC")
    else:
        lines.append("Подписка: ❌ не активна")
        lines.append("Оформить: /subscribe")

    lines.append(f"\nВсего собрано экспрессов: {info['express_count']}")

    if info["first_seen"]:
        lines.append(f"С ботом с: {info['first_seen'].strftime('%d.%m.%Y')}")

    await callback.message.answer("\n".join(lines), reply_markup=after_express_keyboard())


async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        api_server.run_webapp_server(),
    )

if __name__ == "__main__":
    asyncio.run(main())
