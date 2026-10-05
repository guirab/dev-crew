"""App icon drawn with Pillow: a dark rounded square with the favicon's dot, colored by status."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PIL import Image, ImageDraw

BG = "#050807"
LINE = "#22322b"


class Status(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


DOT = {Status.STARTING: "#f4b544", Status.RUNNING: "#2bee86", Status.ERROR: "#ff5d5d"}
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
SUPERSAMPLE = 4


def draw_icon(size: int, status: Status = Status.RUNNING) -> Image.Image:
    """Square RGBA icon of ``size`` px. Drawn 4x larger and downscaled so the edges stay smooth."""
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    border = max(SUPERSAMPLE, big // 32)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=big // 5, fill=BG, outline=LINE, width=border)
    r = big * 0.27
    c = big / 2
    draw.ellipse((c - r, c - r, c + r, c + r), fill=DOT[status])
    return img.resize((size, size), Image.Resampling.LANCZOS)


def write_ico(path: Path) -> Path:
    """Multi-size ``.ico`` for the shortcut (Windows picks the size it needs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    draw_icon(256).save(path, format="ICO", sizes=ICO_SIZES)
    return path


def write_pngs(directory: Path, sizes: tuple[int, ...] = (192, 512)) -> list[Path]:
    """PNG icons for the web manifest (``icon-<size>.png``)."""
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for size in sizes:
        path = directory / f"icon-{size}.png"
        draw_icon(size).save(path, format="PNG", optimize=True)
        out.append(path)
    return out
