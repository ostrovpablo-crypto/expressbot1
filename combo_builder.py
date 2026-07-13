"""
Подбор комбинации исходов под целевой суммарный коэффициент.

Логика простая и честная: перемножаем реальные коэффициенты
доступных исходов, пока не приблизимся к цели в пределах допуска.
Никакой "оценки вероятности" бот не делает — это была бы выдумка.

Для каждого события берём исход с наименьшим коэффициентом
(обычно это фаворит) — единственный объективный критерий,
который есть в данных букмекера.

Алгоритм: множество случайных сборок (greedy со случайным порядком)
+ локальное улучшение (подмена одного события на другое, если это
приближает итог к цели). Точность считается в относительных
процентах от цели, а не в абсолютных единицах — иначе для больших
коэффициентов (x10, x20...) допуск в 0.15 был бы нереалистично мал.
"""

import math
import random
from typing import List, Dict, Optional

RELATIVE_TOLERANCE = 0.08   # допустимое отклонение — 8% от цели
MIN_LEG_ODDS = 1.04          # отсекаем совсем неинтересные исходы
MAX_LEG_ODDS = 1.3           # отсекаем слишком рискованные исходы
ATTEMPTS = 300                # число случайных попыток сборки
HILL_CLIMB_STEPS = 60         # число шагов локального улучшения на попытку


def _favorite_outcome(event: Dict) -> Optional[Dict]:
    """Исход с наименьшим коэффициентом = фаворит по мнению букмекера."""
    outcomes = [o for o in event["outcomes"] if MIN_LEG_ODDS <= o["odds"] <= MAX_LEG_ODDS]
    if not outcomes:
        return None
    return min(outcomes, key=lambda o: o["odds"])


def _dynamic_max_legs(target_odds: float) -> int:
    """Сколько событий максимум может понадобиться, чтобы дотянуть до цели."""
    if target_odds <= 1:
        return 1
    needed = math.log(target_odds) / math.log(MIN_LEG_ODDS)
    return min(int(needed) + 5, 40)  # разумный потолок, чтобы не собирать абсурдно длинные экспрессы


def _total_odds(combo: List[Dict]) -> float:
    total = 1.0
    for c in combo:
        total *= c["odds"]
    return total


def _relative_diff(total: float, target: float) -> float:
    return abs(total - target) / target


def build_combo(events: List[Dict], target_odds: float) -> Optional[List[Dict]]:
    candidates = []
    for event in events:
        fav = _favorite_outcome(event)
        if fav:
            candidates.append({
                "match": event["match"],
                "sport": event.get("sport", ""),
                "commence_time": event["commence_time"],
                "outcome": fav["name"],
                "odds": fav["odds"],
            })

    if not candidates:
        return None

    max_legs = _dynamic_max_legs(target_odds)
    tolerance = max(RELATIVE_TOLERANCE * target_odds, 0.05)

    best_combo = None
    best_diff = float("inf")

    for _ in range(ATTEMPTS):
        pool = candidates[:]
        random.shuffle(pool)

        combo = []
        total = 1.0
        for c in pool:
            if len(combo) >= max_legs:
                break
            if total >= target_odds:
                break
            combo.append(c)
            total *= c["odds"]

        # локальное улучшение: пробуем менять отдельные события на другие из пула,
        # если это приближает итог к цели
        used_ids = {id(c) for c in combo}
        unused = [c for c in candidates if id(c) not in used_ids]

        for _ in range(HILL_CLIMB_STEPS):
            if not combo or not unused:
                break
            current_total = _total_odds(combo)
            current_diff = _relative_diff(current_total, target_odds)
            if current_diff <= tolerance:
                break

            i = random.randrange(len(combo))
            j = random.randrange(len(unused))

            new_total = current_total / combo[i]["odds"] * unused[j]["odds"]
            new_diff = _relative_diff(new_total, target_odds)

            if new_diff < current_diff:
                combo[i], unused[j] = unused[j], combo[i]

        total = _total_odds(combo)
        diff = _relative_diff(total, target_odds)

        if diff < best_diff:
            best_diff = diff
            best_combo = combo[:]

        if best_diff <= tolerance:
            break

    if best_combo and best_diff <= tolerance * 1.5:
        return best_combo

    return None
