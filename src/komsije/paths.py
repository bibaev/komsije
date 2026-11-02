"""Все пути проекта в одном месте: остальной код не знает, как разложены папки."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONFIG = ROOT / "config.json"

DATA = ROOT / "data"
CATEGORIES = DATA / "categories.json"
OVERRIDES = DATA / "overrides.json"  # слой обогащения: пишут люди и PR, сборка только читает
GEOCACHE = DATA / "geocache.json"  # короткая ссылка Google Maps → координаты, пишет сборка

BRAND = ROOT / "brand"  # tokens.yml, style-guide.md, icons.svg, favicon.svg, og.png — бренд v1 «Улица»
BRAND_ASSETS = ("icons.svg", "favicon.svg", "og.png")  # сборка копирует их в site/: страница берёт их рядом с собой

SITE = ROOT / "site"
DATA_JS = SITE / "data.js"  # рядом с ним сборка пересоздаёт b/ — страницы-ссылки «Поделиться»
