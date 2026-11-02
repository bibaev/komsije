"""Бренд v1 «Улица»: страница повторяет brand/tokens.yml, у каждой категории есть пиктограмма."""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TOKENS = yaml.safe_load((ROOT / "brand" / "tokens.yml").read_text(encoding="utf-8"))
CSS = (ROOT / "site" / "style.css").read_text(encoding="utf-8")


def _block(selector: str) -> str:
    start = CSS.index(selector)
    return CSS[CSS.index("{", start) + 1:CSS.index("}", start)]


def _declared(block: str) -> dict[str, str]:
    return {m.group(1): m.group(2).upper() for m in re.finditer(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})", block)}


@pytest.mark.parametrize(("theme", "selector"), [
    ("fasad", ":root {"),
    ("noc", ':root:not([data-theme="light"]) {'),
    ("noc", ':root[data-theme="dark"] {'),
])
def test_page_colors_match_tokens(theme, selector):
    # инвариант 10: цвета живут в tokens.yml, style.css их только повторяет
    css = _declared(_block(selector))
    for role, value in TOKENS["themes"][theme].items():
        assert css.get(role.replace("_", "-")) == value.upper(), f"{theme}.{role}"


def test_page_fonts_match_tokens():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    for role in ("display", "body", "label"):
        font = TOKENS["fonts"][role]
        assert font["google"] in html, role
        assert font["family"] in CSS, role


ICONS = (ROOT / "brand" / TOKENS["icons"]).read_text(encoding="utf-8")


def test_every_category_has_a_pictogram():
    # категорию на карте отличают значком, а не цветом
    categories = json.loads((ROOT / "data" / "categories.json").read_text(encoding="utf-8"))
    for cid in categories:
        assert f'id="i-{cid}"' in ICONS, cid


def test_every_link_kind_has_an_icon():
    # ссылки бизнеса — значками без подписи: у каждого вида ссылки из сборки есть знак
    for kind in ("instagram", "telegram", "threads", "site"):
        assert f'id="i-{kind}"' in ICONS, kind
