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

# Диапазон коэффициентов для отдельного события зависит от цели:
# для больших целевых коэффициентов (x5+) используем более высокий диапазон
# на ногу — иначе пришлось бы набирать десятки событий подряд.
LOW_TARGET_MIN_ODDS = 1.04
LOW_TARGET_MAX_ODDS = 1.3
HIGH_TARGET_MIN_ODDS = 1.2
HIGH_TARGET_MAX_ODDS = 1.55
HIGH_TARGET_THRESHOLD = 5.0   # с какого целевого коэффициента переключаемся на широкий диапазон

ATTEMPTS = 300                # число случайных попыток сборки
HILL_CLIMB_STEPS = 60         # число шагов локального улучшения на попытку


def _odds_range_for_target(target_odds: float):
    if target_odds >= HIGH_TARGET_THRESHOLD:
        return HIGH_TARGET_MIN_ODDS, HIGH_TARGET_MAX_ODDS
    return LOW_TARGET_MIN_ODDS, LOW_TARGET_MAX_ODDS


def _favorite_outcome(event: Dict, min_odds: float, max_odds: float) -> Optional[Dict]:
    """Исход с наименьшим коэффициентом в допустимом диапазоне = фаворит по мнению букмекера."""
    outcomes = [o for o in event["outcomes"] if min_odds <= o["odds"] <= max_odds]
    if not outcomes:
        return None
    return min(outcomes, key=lambda o: o["odds"])


def _dynamic_max_legs(target_odds: float, min_odds: float) -> int:
    """Сколько событий максимум может понадобиться, чтобы дотянуть до цели."""
    if target_odds <= 1:
        return 1
    needed = math.log(target_odds) / math.log(min_odds)
    return min(int(needed) + 5, 40)  # разумный потолок, чтобы не собирать абсурдно длинные экспрессы


def _total_odds(combo: List[Dict]) -> float:
    total = 1.0
    for c in combo:
        total *= c["odds"]
    return total


def _relative_diff(total: float, target: float) -> float:
    return abs(total - target) / target


def build_combo(events: List[Dict], target_odds: float) -> Optional[List[Dict]]:
    min_odds, max_odds = _odds_range_for_target(target_odds)

    candidates = []
    for event in events:
        fav = _favorite_outcome(event, min_odds, max_odds)
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

    max_legs = _dynamic_max_legs(target_odds, min_odds)
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
