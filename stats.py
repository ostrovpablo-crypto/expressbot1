"""
Простая статистика использования бота через SQLite.
Файл базы создаётся автоматически рядом с ботом (stats.db).
"""

import sqlite3
import json
import datetime as dt
from pathlib import Path

DB_PATH = Path(__file__).parent / "stats.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS express_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            target_odds REAL,
            total_odds REAL,
            combo_json TEXT,
            created_at TEXT
        )
    """)
    # на случай если таблица уже существовала со старой схемой (без total_odds/combo_json)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(express_events)")}
    if "total_odds" not in existing_cols:
        conn.execute("ALTER TABLE express_events ADD COLUMN total_odds REAL")
    if "combo_json" not in existing_cols:
        conn.execute("ALTER TABLE express_events ADD COLUMN combo_json TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            expires_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referred_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            created_at TEXT,
            rewarded INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def record_referral(referred_id: int, referrer_id: int):
    """Запоминает, кто кого пригласил. Срабатывает только один раз на пользователя
    (первый /start с реферальной ссылкой) и не даёт человеку пригласить самого себя."""
    if referred_id == referrer_id:
        return
    conn = _connect()
    existing = conn.execute(
        "SELECT 1 FROM referrals WHERE referred_id = ?", (referred_id,)
    ).fetchone()
    if not existing:
        now = dt.datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO referrals (referred_id, referrer_id, created_at, rewarded) VALUES (?, ?, ?, 0)",
            (referred_id, referrer_id, now),
        )
        conn.commit()
    conn.close()


def reward_referrer_if_needed(referred_id: int, bonus_days: int) -> int | None:
    """
    Вызывать при первой успешной оплате подписки пользователем.
    Если пользователь пришёл по реферальной ссылке и награда ещё не выдавалась —
    продлевает подписку тому, кто его пригласил, на bonus_days.
    Возвращает referrer_id, если награда выдана, иначе None.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT referrer_id, rewarded FROM referrals WHERE referred_id = ?", (referred_id,)
    ).fetchone()

    if not row or row[1]:
        conn.close()
        return None

    referrer_id = row[0]
    conn.execute("UPDATE referrals SET rewarded = 1 WHERE referred_id = ?", (referred_id,))
    conn.commit()
    conn.close()

    extend_subscription(referrer_id, bonus_days)
    return referrer_id


def get_referral_stats(user_id: int) -> dict:
    conn = _connect()
    total_invited = conn.execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)
    ).fetchone()[0]
    rewarded_count = conn.execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND rewarded = 1", (user_id,)
    ).fetchone()[0]
    conn.close()
    return {"total_invited": total_invited, "rewarded_count": rewarded_count}


def set_subscription(user_id: int, expires_at: dt.datetime):
    conn = _connect()
    conn.execute("""
        INSERT INTO subscriptions (user_id, expires_at)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at
    """, (user_id, expires_at.isoformat()))
    conn.commit()
    conn.close()


def extend_subscription(user_id: int, days: int) -> dt.datetime:
    """Продлевает подписку на N дней от текущей даты окончания (или от сейчас, если истекла/нет)."""
    conn = _connect()
    row = conn.execute(
        "SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()

    now = dt.datetime.utcnow()
    base = now
    if row:
        current_expiry = dt.datetime.fromisoformat(row[0])
        if current_expiry > now:
            base = current_expiry

    new_expiry = base + dt.timedelta(days=days)
    set_subscription(user_id, new_expiry)
    return new_expiry


def is_subscribed(user_id: int) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()

    if not row:
        return False
    return dt.datetime.fromisoformat(row[0]) > dt.datetime.utcnow()


def get_subscription_expiry(user_id: int) -> dt.datetime | None:
    conn = _connect()
    row = conn.execute(
        "SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dt.datetime.fromisoformat(row[0]) if row else None


def track_user(user_id: int, username: str | None):
    """Вызывать при любом взаимодействии пользователя с ботом (например /start)."""
    now = dt.datetime.utcnow().isoformat()
    conn = _connect()
    conn.execute("""
        INSERT INTO users (user_id, username, first_seen, last_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            last_seen = excluded.last_seen
    """, (user_id, username, now, now))
    conn.commit()
    conn.close()


def track_express(user_id: int, target_odds: float, total_odds: float = None, combo: list = None):
    """Вызывать каждый раз, когда бот успешно собрал экспресс."""
    now = dt.datetime.utcnow().isoformat()
    combo_json = None
    if combo is not None:
        # сохраняем компактную выжимку — вид спорта, матч, ставку, коэффициент
        summary = [
            {"sport": leg.get("sport"), "match": leg.get("match"),
             "outcome": leg.get("outcome"), "odds": leg.get("odds")}
            for leg in combo
        ]
        combo_json = json.dumps(summary, ensure_ascii=False)

    conn = _connect()
    conn.execute(
        "INSERT INTO express_events (user_id, target_odds, total_odds, combo_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, target_odds, total_odds, combo_json, now),
    )
    conn.commit()
    conn.close()


def get_user_express_history(user_id: int, limit: int = 10) -> list[dict]:
    conn = _connect()
    rows = conn.execute("""
        SELECT target_odds, total_odds, combo_json, created_at
        FROM express_events
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()

    history = []
    for target_odds, total_odds, combo_json, created_at in rows:
        combo = json.loads(combo_json) if combo_json else []
        history.append({
            "target_odds": target_odds,
            "total_odds": total_odds,
            "combo": combo,
            "created_at": created_at,
        })
    return history


def get_account_info(user_id: int) -> dict:
    expiry = get_subscription_expiry(user_id)
    subscribed = expiry is not None and expiry > dt.datetime.utcnow()
    express_count = count_user_expresses(user_id)

    conn = _connect()
    row = conn.execute(
        "SELECT first_seen FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    first_seen = dt.datetime.fromisoformat(row[0]) if row else None

    return {
        "subscribed": subscribed,
        "expires_at": expiry,
        "express_count": express_count,
        "first_seen": first_seen,
    }


def get_all_user_ids() -> list[int]:
    conn = _connect()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]


def access_allowed(user_id: int, admin_id: int, free_trial_limit: int) -> bool:
    if user_id == admin_id:
        return True
    if is_subscribed(user_id):
        return True
    return count_user_expresses(user_id) < free_trial_limit


def count_user_expresses(user_id: int) -> int:
    conn = _connect()
    count = conn.execute(
        "SELECT COUNT(*) FROM express_events WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return count


def get_stats() -> dict:
    conn = _connect()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    today = dt.datetime.utcnow().date().isoformat()
    active_today = conn.execute(
        "SELECT COUNT(*) FROM users WHERE last_seen LIKE ?", (f"{today}%",)
    ).fetchone()[0]

    week_ago = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
    active_week = conn.execute(
        "SELECT COUNT(*) FROM users WHERE last_seen >= ?", (week_ago,)
    ).fetchone()[0]

    total_express = conn.execute("SELECT COUNT(*) FROM express_events").fetchone()[0]

    top_users = conn.execute("""
        SELECT u.username, u.user_id, COUNT(e.id) as cnt
        FROM users u
        LEFT JOIN express_events e ON e.user_id = u.user_id
        GROUP BY u.user_id
        ORDER BY cnt DESC
        LIMIT 5
    """).fetchall()

    conn.close()

    return {
        "total_users": total_users,
        "active_today": active_today,
        "active_week": active_week,
        "total_express": total_express,
        "top_users": top_users,
    }
