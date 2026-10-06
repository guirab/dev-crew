"""Regenerate the web manifest icons (frontend/public/icon-*.png) from crew.desktop.icons.

Usage: uv run python scripts/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from crew.desktop.icons import write_pngs

PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public"

if __name__ == "__main__":
    for path in write_pngs(PUBLIC):
        print(path)
