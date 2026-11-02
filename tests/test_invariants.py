"""Инварианты из CLAUDE.md, которые держатся тестом, а не памятью."""
import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "komsije"
APP_JS = (ROOT / "site" / "app.js").read_text(encoding="utf-8")


def _imports() -> set[str]:
    found = set()
    for p in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_build_runtime_is_stdlib_only():
    # инварианты 1 и 2: код не тянет ничего снаружи репозитория, собрать сайт можно без установки зависимостей
    assert _imports() <= set(sys.stdlib_module_names)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == []


def test_page_never_renders_sheet_values_as_html():
    # инвариант 4: значения из таблицы попадают в DOM только как текст
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in APP_JS, sink


def test_no_cookies():
    # инвариант 6: без кук — без окна согласия
    assert "document.cookie" not in APP_JS


def test_only_cookieless_counter():
    # инвариант 6: счётчик — только GoatCounter, никаких счётчиков с куками
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert "gc.zgo.at/count.js" in html
    for tracker in ("googletagmanager", "gtag(", "google-analytics", "facebook.net", "fbq(", "mc.yandex"):
        assert tracker not in html, tracker


def test_tile_source_lives_in_config():
    # инвариант 11: политика OSM требует менять источник тайлов без правки кода страницы
    assert "tile.openstreetmap.org" not in APP_JS
    assert "{z}" in json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["tiles"]["url"]


def test_build_never_writes_the_enrichment_layer():
    # инвариант 7: overrides.json пишут люди, сборка его только читает
    src = (SRC / "build.py").read_text(encoding="utf-8")
    assert "OVERRIDES.write" not in src
    assert "paths.OVERRIDES.open" not in src
