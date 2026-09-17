#!/usr/bin/env python3
"""Render the brand icon and logo HACS looks for.

HACS wants either the integration's domain registered in the Home Assistant
brands repository, or brand assets committed alongside the component. This
draws both from the same original mark used in the README, so the repository
carries no Polestar trademark artwork.

    python3 scripts/generate_brand_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
BRAND = REPO / "custom_components" / "polestar_data_portal" / "brand"

BACKGROUND = (22, 24, 29, 255)
FOREGROUND = (237, 239, 242, 255)
# A dimmer tone for the two side chevrons, matching the README artwork.
FOREGROUND_DIM = (237, 239, 242, 150)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# The mark, in the same coordinate space as resources/logo.svg. Each entry is
# a polygon and the colour it is filled with.
MARK: tuple[tuple[list[tuple[int, int]], tuple[int, int, int, int]], ...] = (
    ([(48, 8), (64, 48), (48, 88), (32, 48)], FOREGROUND),
    ([(16, 28), (48, 48), (16, 68), (28, 48)], FOREGROUND_DIM),
    ([(80, 28), (48, 48), (80, 68), (68, 48)], FOREGROUND_DIM),
)
MARK_BOX = (16, 8, 80, 88)  # left, top, right, bottom in mark coordinates


def draw_mark(
    draw: ImageDraw.ImageDraw, centre: tuple[float, float], height: float
) -> None:
    """Draw the mark centred on ``centre``, scaled to ``height`` pixels."""
    left, top, right, bottom = MARK_BOX
    scale = height / (bottom - top)
    origin_x = centre[0] - (right - left) * scale / 2
    origin_y = centre[1] - height / 2

    for polygon, colour in MARK:
        draw.polygon(
            [
                (origin_x + (x - left) * scale, origin_y + (y - top) * scale)
                for x, y in polygon
            ],
            fill=colour,
        )


def build_icon(size: int) -> Image.Image:
    """Return the square app icon."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=BACKGROUND
    )
    draw_mark(draw, (size / 2, size / 2), size * 0.58)
    return image


def build_logo(width: int, height: int) -> Image.Image:
    """Return the wide logo: the mark next to the integration name."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=int(height * 0.16), fill=BACKGROUND
    )

    draw_mark(draw, (height * 0.62, height / 2), height * 0.52)

    title = ImageFont.truetype(FONT_PATH, int(height * 0.22))
    subtitle = ImageFont.truetype(FONT_PATH, int(height * 0.13))
    text_x = height * 1.15
    draw.text(
        (text_x, height * 0.30), "POLESTAR", font=title, fill=FOREGROUND, anchor="lm"
    )
    draw.text(
        (text_x, height * 0.62),
        "DATA PORTAL",
        font=subtitle,
        fill=FOREGROUND_DIM,
        anchor="lm",
    )
    return image


def main() -> int:
    """Write every brand asset."""
    BRAND.mkdir(parents=True, exist_ok=True)

    assets = {
        "icon.png": build_icon(256),
        "icon@2x.png": build_icon(512),
        "logo.png": build_logo(512, 160),
        "logo@2x.png": build_logo(1024, 320),
    }
    for name, image in assets.items():
        image.save(BRAND / name, "PNG", optimize=True)
        print(f"wrote {(BRAND / name).relative_to(REPO)} {image.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
