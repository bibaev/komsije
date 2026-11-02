"""Разбор таблицы: правила, на которых держится карта. Сеть не нужна: в фикстурах полные ссылки Google Maps."""
import json

import pytest

from komsije import build

HEADER = (
    ',"Važno! Obavezno navedite matični broj ili PIB firme."\n'
    ",,,\n"
    "Naziv,Delatnost,Matični broj / PIB,Adresa,Grad,Google maps,Sajt biznisa,Threads ,Telegram,Instagram\n"
)


def gmaps(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps/place/x/@{lat},{lng},17z/data=!3d{lat}!4d{lng}"


def sheet(*rows: str) -> str:
    return HEADER + "\n".join(rows) + "\n"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Сборка пишет во временную папку и не видит настоящий слой обогащения."""
    (tmp_path / "site").mkdir()
    monkeypatch.setattr(build, "OUT_PATH", tmp_path / "site" / "data.js")
    monkeypatch.setattr(build, "CACHE_PATH", tmp_path / "geocache.json")
    monkeypatch.setattr(build, "OVERRIDES", {})
    return tmp_path


def test_row_without_name_adds_location_to_previous_business(isolated):
    data, _ = build.build(sheet(
        f"Kafa,Kafe,12345678,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,",
        f",,,Bulevar 2,Novi Sad,{gmaps(45.25, 19.83)},,,,",
    ))
    [b] = data["businesses"]
    assert [loc["city"] for loc in b["locations"]] == ["beograd", "novi-sad"]


def test_mb_and_pib_in_one_cell(isolated, monkeypatch):
    # id — первый номер; обогащение находится по любому из двух
    monkeypatch.setattr(build, "OVERRIDES", {"100000002": {"categories": ["eda"]}})
    data, _ = build.build(sheet(f"Pekara,Pekara,10000001 / 100000002,Ulica 13,Beograd,{gmaps(44.81, 20.47)},,,,"))
    [b] = data["businesses"]
    assert b["id"] == "10000001"
    assert b["key"].endswith("-10000001")
    assert b["categories"] == ["eda"]


def test_one_link_for_many_addresses_is_a_places_list(isolated):
    # одна ссылка на несколько адресов — список мест, а не точка: пинов нет, ссылка — на весь список
    data, _ = build.build(sheet(
        '"Mreža",Kafe,12345678,"A 1\nB 2\nC 3",Beograd,https://www.google.com/maps/placelists/list/abc,,,,'
    ))
    [b] = data["businesses"]
    assert len(b["locations"]) == 3
    assert all(loc["lat"] is None for loc in b["locations"])
    assert b["places_list"].startswith("https://www.google.com/maps/placelists/")


def test_points_fill_addresses_the_links_cannot(isolated, monkeypatch):
    # точку дают ссылки; где её нет (список мест, текст в колонке карт) — слой обогащения по адресу,
    # в том числе для строки-продолжения; точка под адрес, которого больше нет, — в предупреждения
    monkeypatch.setattr(build, "OVERRIDES", {"12345678": {"points": {
        "A 1": [44.81, 20.46], "C 3": [45.25, 19.83], "Stara 9": [44.8, 20.4]}}})
    data, warnings = build.build(sheet(
        '"Mreža",Kafe,12345678,"A 1\nB 2",Beograd,https://www.google.com/maps/placelists/list/abc,,,,',
        ",,,C 3,Novi Sad,Radim onlajn,,,,",
    ))
    [b] = data["businesses"]
    assert [(loc["address"], loc["lat"]) for loc in b["locations"]] == [("A 1", 44.81), ("B 2", None), ("C 3", 45.25)]
    assert any("Stara 9" in w for w in warnings)
    assert "Radim onlajn" not in json.loads((isolated / "geocache.json").read_text(encoding="utf-8"))


def test_hidden_business_disappears_with_its_extra_rows(isolated, monkeypatch):
    # бизнес попросил убрать себя: нет ни карточки, ни строк-продолжений, ни города, заведённого только ради него
    monkeypatch.setattr(build, "OVERRIDES", {"12345678": {"hidden": "попросили убрать"}})
    data, warnings = build.build(sheet(
        f"Kafa,Kafe,87654321,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,",
        f"Skriven,Kafe,12345678,Ulica 2,Beograd,{gmaps(44.82, 20.47)},,,,",
        f",,,Bulevar 2,Novi Sad,{gmaps(45.25, 19.83)},,,,",
    ))
    [b] = data["businesses"]
    assert b["id"] == "87654321" and len(b["locations"]) == 1
    assert list(data["cities"]) == ["beograd"]
    assert any("попросили убрать" in w for w in warnings)


def test_row_without_mb_or_pib_is_not_a_business(isolated):
    # инициатива проверяет по номеру: строка без него — шум (2 ноя попала строка «`»), как и ее продолжения
    data, warnings = build.build(sheet(
        f"Kafa,Kafe,87654321,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,",
        "`,,,,,,,,,",
        f",,,Bulevar 2,Novi Sad,{gmaps(45.25, 19.83)},,,,",
    ))
    [b] = data["businesses"]
    assert b["id"] == "87654321" and len(b["locations"]) == 1
    assert list(data["cities"]) == ["beograd"]
    assert any("«`»" in w for w in warnings)


def test_publish_stops_when_a_third_of_businesses_vanish():
    def biz(n):
        return {"businesses": [{"id": str(i)} for i in range(n)]}
    assert build.shrink_error(biz(30), biz(19)) is not None
    assert build.shrink_error(biz(30), biz(20)) is None
    assert build.shrink_error(None, biz(1)) is None


@pytest.mark.parametrize(("cell", "ids"), [
    ("Beograd", ["beograd"]),
    ("Нови Сад", ["novi-sad"]),
    ("Novi sad ", ["novi-sad"]),
    ("Beograd, Novi Beograd", ["beograd"]),
    ("Beograd, Novi Sad", ["beograd", "novi-sad"]),
    ("Online prodavnica", []),
    ("Online", []),
])
def test_city_spellings_collapse_to_one_id(cell, ids):
    assert [cid for cid, _ in build.cities_of(cell)] == ids


def test_two_cities_for_two_addresses_pair_in_order(isolated):
    data, _ = build.build(sheet(
        f'Mreža,Kafe,12345678,"A 1\nB 2","Beograd, Novi Sad","{gmaps(44.81, 20.46)}\n{gmaps(45.25, 19.83)}",,,,'
    ))
    [b] = data["businesses"]
    assert [loc["city"] for loc in b["locations"]] == ["beograd", "novi-sad"]
    assert set(data["cities"]) == {"beograd", "novi-sad"}


@pytest.mark.parametrize(("kind", "cell", "url"), [
    ("instagram", "@askona_serbia", "https://www.instagram.com/askona_serbia/"),
    ("instagram", "reparo.rs", "https://www.instagram.com/reparo.rs/"),
    ("instagram", "@malceva.brand — sivenje, @malceva.popravka", "https://www.instagram.com/malceva.brand/"),
    ("telegram", "t.me/Reparo_NS", "https://t.me/Reparo_NS"),
    ("telegram", "@huntudown", "https://t.me/huntudown"),
    ("threads", "@between_belgrade", "https://www.threads.com/@between_belgrade"),
    ("site", "www.fixlab.rs", "https://www.fixlab.rs"),
    ("site", "Sunrice.rs", "https://sunrice.rs"),
    ("site", "-", None),
    ("site", "@nije_sajt", None),
    ("instagram", "javascript:alert(1)", None),
])
def test_link_cells_written_as_handles_or_bare_domains(kind, cell, url):
    assert build.to_link(kind, cell) == url


def test_enrichment_can_rename_and_fix_serbian_description(isolated, monkeypatch):
    monkeypatch.setattr(build, "OVERRIDES", {"10000001": {"name": "Pekara Mesto", "description_sr": "Pekara"}})
    data, _ = build.build(sheet(f"Mesto Pekara PR,pekara i tako to,10000001,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,"))
    [b] = data["businesses"]
    assert b["name"] == "Pekara Mesto"
    assert b["key"] == "pekara-mesto-10000001"
    assert b["description"]["sr"] == "Pekara"


def test_clean_url_keeps_only_http_and_drops_tracking():
    assert build.clean_url("javascript:alert(1)") is None
    assert build.clean_url("https://x.rs/?utm_source=threads&fbclid=1&id=7") == "https://x.rs/?id=7"


def test_missing_header_row_stops_the_build(isolated):
    with pytest.raises(SystemExit):
        build.build("Ime,Grad\nKafa,Beograd\n")


def test_sync_time_is_every_run_change_time_only_with_data(isolated):
    # synced_at — каждая сверка (видит человек); generated_at — только когда данные поменялись
    text = sheet(f"Kafa,Kafe,12345678,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,")
    first, _ = build.build(text)
    first["generated_at"] = first["synced_at"] = "2026-01-01T00:00+00:00"
    build.publish(first)
    second, _ = build.build(text)
    assert second["generated_at"] == "2026-01-01T00:00+00:00"
    assert second["synced_at"] != "2026-01-01T00:00+00:00"


def test_page_gets_links_for_source_and_adding(isolated):
    data, _ = build.build(sheet(f"Kafa,Kafe,12345678,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,"))
    assert data["source"].endswith("/htmlview")
    assert data["add_url"].endswith("#gid=" + build.CONFIG["pending_gid"])
    assert data["initiative"]["name"]
    assert data["initiative"]["author"]["url"].startswith("https://")  # кто начал — по имени и ссылкой


def test_share_page_escapes_sheet_values(isolated):
    data, _ = build.build(sheet(f'"<script>x</script>",Kafe,12345678,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,'))
    build.publish(data)
    [page] = (isolated / "site" / "b").glob("*/index.html")
    html = page.read_text(encoding="utf-8")
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert json.loads((isolated / "site" / "data.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
