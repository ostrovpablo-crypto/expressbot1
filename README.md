# Express Bot

Телеграм-бот, который собирает экспресс под заданный суммарный коэффициент,
используя реальные коэффициенты через SharpAPI. Доступ по подписке через Crypto Pay (@CryptoBot).

## Как это устроено

1. `bot.py` — меню, диалог, подписка, история, личный кабинет, рассылка, ручная выдача подписки (aiogram 3.x, FSM)
2. `odds_api.py` — запрос реальных коэффициентов через SharpAPI (с кэшем на 5 мин)
3. `combo_builder.py` — подбор комбинации событий под нужный итоговый коэффициент
4. `express_image.py` — рендер результата в виде картинки
5. `stats.py` — учёт пользователей, статистика, история экспрессов, подписки (SQLite, файл `stats.db`)
6. `crypto_pay.py` — обёртка над Crypto Pay API для приёма оплаты

## Установка

```bash
git clone <твой репозиторий> expressbot
cd expressbot
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Настройка

1. Получи токен бота у [@BotFather](https://t.me/BotFather)
2. Зарегистрируйся на [sharpapi.io](https://sharpapi.io) и получи API-ключ (карта не нужна)
   - В личном кабинете выбери нужные букмекеры (по умолчанию код рассчитан на
     Betway, bwin, Betano, Bet365 US, Unibet — можно поменять через `SHARPAPI_BOOKS`)
3. Узнай свой Telegram ID через **@userinfobot** — понадобится для `ADMIN_ID`
4. Настрой приём платежей через Crypto Pay:
   - Открой в Telegram **@CryptoBot**
   - Раздел **Crypto Pay** → **Create App**
   - Скопируй API-токен приложения
5. Задай переменные окружения:

```bash
export BOT_TOKEN="123456:ABC-DEF..."
export SHARPAPI_KEY="твой_ключ"
export SHARPAPI_BOOKS="betway,bwin,betano,bet365us,unibet"   # опционально, это значение по умолчанию
export ADMIN_ID="твой_telegram_id"
export CRYPTO_PAY_TOKEN="токен_из_CryptoBot"
```

На Windows (PowerShell):
```powershell
$env:BOT_TOKEN="123456:ABC-DEF..."
$env:SHARPAPI_KEY="твой_ключ"
$env:ADMIN_ID="твой_telegram_id"
$env:CRYPTO_PAY_TOKEN="токен_из_CryptoBot"
```

## Запуск

```bash
python bot.py
```

## Команды бота

- `/start` — главное меню
- `/subscribe` — оформить/проверить подписку
- `/grant <user_id> [дней]` — вручную выдать подписку пользователю (только ADMIN_ID)
- `/stats` — статистика по пользователям (только ADMIN_ID)
- `/broadcast` — рассылка всем пользователям (только ADMIN_ID)

После каждого экспресса доступны кнопки: новый экспресс, история экспрессов,
личный кабинет (статус подписки), возврат в начало.

## Настройка подписки

В `bot.py` в начале файла:
```python
SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_PRICE = 5
SUBSCRIPTION_ASSET = "USDT"
FREE_TRIAL_EXPRESSES = 1
```

## Деплой на Railway (24/7)

1. Залей код в приватный репозиторий на GitHub
2. На railway.app: **New Project** → **Deploy from GitHub repo**
3. Во вкладке **Variables** добавь все переменные окружения из раздела "Настройка"
4. Railway подхватит `Procfile` (`worker: python bot.py`) и задеплоит автоматически
5. Логи — во вкладке **Deployments** → открой последний деплой → **Deploy Logs**

## Известные ограничения

- SharpAPI бесплатный тариф — 12 запросов/минуту, без месячного лимита
- Эндпоинт `/odds` не отдаёт точное время начала матча — в интерфейсе бот
  показывает статус "скоро" вместо конкретного времени
- Часть букмекеров у SharpAPI доступна только на платных тарифах (помечены
  замком в личном кабинете)

## Важно

Коэффициенты букмекера — это не прогноз и не гарантия исхода.
Бот механически комбинирует реальные цифры под запрошенный
итоговый коэффициент, ничего не "предсказывая". Ответственность
за решения о ставках и оплату подписки лежит на пользователе.
