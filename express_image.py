"""
Рендер собранного экспресса в виде картинки (для отправки как фото в Telegram).
"""

import io
import datetime as dt
from typing import List, Dict

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1000
PADDING = 48
CARD_PADDING = 24
CARD_GAP = 16

BG_TOP = (14, 19, 23)
BG_BOTTOM = (9, 13, 16)
CARD_COLOR = (23, 31, 29)
CARD_BORDER = (38, 50, 46)
ACCENT = (94, 214, 150)
ACCENT_DIM = (58, 130, 95)
TEXT_PRIMARY = (242, 246, 243)
TEXT_MUTED = (138, 150, 144)
BADGE_BG = (33, 44, 40)
NUMBER_BG = (30, 42, 38)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _vertical_gradient(width: int, height: int, top_color, bottom_color) -> Image.Image:
    base = Image.new("RGB", (width, height), top_color)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return base


def _draw_badge(draw, x, y, text, font, fg, bg, pad_x=12, pad_y=6):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.rounded_rectangle(
        [x, y, x + w + pad_x * 2, y + h + pad_y * 2],
        radius=(h + pad_y * 2) // 2,
        fill=bg,
    )
    draw.text((x + pad_x, y + pad_y - bbox[1]), text, font=font, fill=fg)
    return w + pad_x * 2


def _format_time_label(raw: str) -> str:
    """SharpAPI пока отдаёт 'live'/'скоро' вместо точного времени — показываем аккуратным статусом."""
    if raw == "live":
        return "🔴 Live"
    if raw == "скоро":
        return "⏱ Скоро"
    return raw


def render_express_image(combo: List[Dict], total_odds: float, target_odds: float) -> bytes:
    font_brand = _load_font(20, bold=True)
    font_title = _load_font(38, bold=True)
    font_subtitle = _load_font(16)
    font_number = _load_font(20, bold=True)
    font_sport = _load_font(14, bold=True)
    font_match = _load_font(24, bold=True)
    font_detail = _load_font(17)
    font_odds_value = _load_font(25, bold=True)
    font_total_label = _load_font(17)
    font_total_value = _load_font(40, bold=True)
    font_footer = _load_font(13)

    row_height = 120
    header_height = 118
    total_block_height = 104
    footer_height = 56

    height = (
        header_height
        + len(combo) * (row_height + CARD_GAP)
        + total_block_height
        + footer_height
        + PADDING
    )

    img = _vertical_gradient(WIDTH, height, BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(img)

    y = PADDING

    draw.text((PADDING, y), "EXPRESS BOT", font=font_brand, fill=ACCENT_DIM)
    y += 32

    draw.text((PADDING, y), "🎯 Твой экспресс", font=font_title, fill=TEXT_PRIMARY)
    y += 50

    draw.text(
        (PADDING, y),
        f"{len(combo)} событий · цель x{target_odds} · сформировано {dt.datetime.utcnow().strftime('%d.%m %H:%M')} UTC",
        font=font_subtitle,
        fill=TEXT_MUTED,
    )
    y += 36

    for i, leg in enumerate(combo, start=1):
        card_top = y
        card_bottom = y + row_height

        draw.rounded_rectangle(
            [PADDING, card_top, WIDTH - PADDING, card_bottom],
            radius=18,
            fill=CARD_COLOR,
            outline=CARD_BORDER,
            width=1,
        )

        # номер события — кружок слева
        circle_d = 40
        circle_x = PADDING + CARD_PADDING
        circle_y = card_top + (row_height - circle_d) // 2
        draw.ellipse(
            [circle_x, circle_y, circle_x + circle_d, circle_y + circle_d],
            fill=NUMBER_BG, outline=ACCENT_DIM, width=1,
        )
        num_text = str(i)
        bbox = draw.textbbox((0, 0), num_text, font=font_number)
        nw, nh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (circle_x + (circle_d - nw) / 2, circle_y + (circle_d - nh) / 2 - bbox[1]),
            num_text, font=font_number, fill=ACCENT,
        )

        inner_x = circle_x + circle_d + 20
        inner_y = card_top + CARD_PADDING - 4

        badge_w = _draw_badge(draw, inner_x, inner_y, leg["sport"].upper(), font_sport, ACCENT, BADGE_BG)
        time_label = _format_time_label(leg["commence_time"])
        draw.text((inner_x + badge_w + 10, inner_y + 6), time_label, font=font_detail, fill=TEXT_MUTED)
        inner_y += 34

        draw.text((inner_x, inner_y), leg["match"], font=font_match, fill=TEXT_PRIMARY)
        inner_y += 32

        draw.text((inner_x, inner_y), leg["outcome"], font=font_detail, fill=TEXT_MUTED)

        odds_text = f"x{leg['odds']}"
        bbox = draw.textbbox((0, 0), odds_text, font=font_odds_value)
        odds_w = bbox[2] - bbox[0]
        odds_h = bbox[3] - bbox[1]

        badge_w2 = odds_w + 44
        badge_h2 = odds_h + 26
        badge_x = WIDTH - PADDING - CARD_PADDING - badge_w2
        badge_y = card_top + (row_height - badge_h2) // 2

        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w2, badge_y + badge_h2],
            radius=14, fill=(19, 27, 25), outline=ACCENT_DIM, width=1,
        )
        draw.text(
            (badge_x + (badge_w2 - odds_w) // 2, badge_y + (badge_h2 - odds_h) // 2 - bbox[1]),
            odds_text, font=font_odds_value, fill=ACCENT,
        )

        y = card_bottom + CARD_GAP

    total_top = y
    total_bottom = y + total_block_height
    draw.rounded_rectangle(
        [PADDING, total_top, WIDTH - PADDING, total_bottom],
        radius=20, fill=(17, 29, 25), outline=ACCENT, width=2,
    )
    draw.text(
        (PADDING + CARD_PADDING, total_top + 18),
        "ИТОГОВЫЙ КОЭФФИЦИЕНТ", font=font_total_label, fill=TEXT_MUTED,
    )
    draw.text(
        (PADDING + CARD_PADDING, total_top + 40),
        f"x{round(total_odds, 2)}", font=font_total_value, fill=ACCENT,
    )
    y = total_bottom + 22

    footer = "Математическая комбинация реальных коэффициентов. Не прогноз и не гарантия исхода."
    draw.text((PADDING, y), footer, font=font_footer, fill=TEXT_MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
