"""
Ручной импорт коэффициентов — на случай, когда API даёт мало событий
или их вообще нет. Админ присылает текстом список исходов, бот парсит
их в тот же формат, что использует odds_api.py, и combo_builder может
собирать экспрессы из них.

Формат одной строки (разделитель — точка с запятой):
    Вид спорта; Матч; Исход; Коэффициент; Время(необязательно, YYYY-MM-DD HH:MM)

Примеры:
    Футбол; Реал Мадрид - Барселона; П1; 1.85; 2026-07-15 20:00
    Футбол; Реал Мадрид - Барселона; Тотал Меньше 2.5; 1.9; 2026-07-15 20:00
    Баскетбол; Лейкерс - Уорриорз; П1; 1.75

Несколько строк с одинаковым матчем (вид спорта + название) автоматически
объединяются в одно событие с несколькими исходами.
"""

import datetime as dt
from typing import List, Dict, Tuple

_storage = {"events": [], "updated_at": None, "raw_line_count": 0}


def _parse_line(line: str, line_no: int) -> Tuple[Dict, str, None] | Tuple[None, None, str]:
    """Возвращает (данные, ключ_группировки, None) при успехе, либо (None, None, текст_ошибки)."""
    parts = [p.strip() for p in line.split(";")]

    if len(parts) < 4:
        return None, None, f"строка {line_no}: нужно минимум 4 поля через ';' (спорт; матч; исход; коэфф.)"

    sport, match, outcome, odds_raw = parts[:4]
    time_raw = parts[4] if len(parts) >= 5 else ""

    if not sport or not match or not outcome:
        return None, None, f"строка {line_no}: пустое поле спорта/матча/исхода"

    try:
        odds = float(odds_raw.replace(",", "."))
    except ValueError:
        return None, None, f"строка {line_no}: не удалось распознать коэффициент '{odds_raw}'"

    if odds <= 1:
        return None, None, f"строка {line_no}: коэффициент должен быть больше 1"

    commence_time = "скоро"
    if time_raw:
        try:
            parsed = dt.datetime.strptime(time_raw, "%Y-%m-%d %H:%M")
            commence_time = parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return None, None, f"строка {line_no}: не удалось распознать время '{time_raw}' (нужен формат YYYY-MM-DD HH:MM)"

    key = (sport, match)
    data = {
        "sport": sport,
        "match": match,
        "commence_time": commence_time,
        "outcome": outcome,
        "odds": odds,
    }
    return data, key, None


def set_from_text(raw_text: str) -> Dict:
    """
    Парсит текст с исходами и заменяет текущий ручной пул на новый.
    Возвращает {"events_count": N, "outcomes_count": M, "errors": [...]}
    """
    lines = [l for l in raw_text.strip().splitlines() if l.strip()]

    events_map = {}
    errors = []

    for i, line in enumerate(lines, start=1):
        data, key, error = _parse_line(line, i)
        if error:
            errors.append(error)
            continue

        if key not in events_map:
            events_map[key] = {
                "match": data["match"],
                "sport": data["sport"],
                "commence_time": data["commence_time"],
                "outcomes": [],
            }
        events_map[key]["outcomes"].append({
            "name": data["outcome"],
            "odds": data["odds"],
        })

    events = list(events_map.values())
    outcomes_count = sum(len(e["outcomes"]) for e in events)

    _storage["events"] = events
    _storage["updated_at"] = dt.datetime.utcnow()
    _storage["raw_line_count"] = len(lines)

    return {"events_count": len(events), "outcomes_count": outcomes_count, "errors": errors}


def get_events() -> List[Dict]:
    return _storage["events"]


def has_manual_data() -> bool:
    return bool(_storage["events"])


def clear():
    _storage["events"] = []
    _storage["updated_at"] = None
    _storage["raw_line_count"] = 0


def status() -> Dict:
    return {
        "events_count": len(_storage["events"]),
        "outcomes_count": sum(len(e["outcomes"]) for e in _storage["events"]),
        "updated_at": _storage["updated_at"],
    }
