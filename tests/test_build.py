"""Разбор таблицы: правила, на которых держится карта. Сеть не нужна: в фикстурах полные ссылки Google Maps."""
import json
import urllib.parse

import pytest

from komsije import build
from komsije import todo as todo_mod

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
    # обогащение находится по любому из двух номеров; id — тот, под которым бизнес записан в обогащении,
    # а если записи нет — первый номер ячейки
    monkeypatch.setattr(build, "OVERRIDES", {"100000002": {"categories": ["eda"]}})
    data, _ = build.build(sheet(
        f"Pekara,Pekara,10000001 / 100000002,Ulica 13,Beograd,{gmaps(44.81, 20.47)},,,,",
        f"Kafa,Kafe,10000005 / 100000006,Ulica 14,Beograd,{gmaps(44.82, 20.47)},,,,",
    ))
    known, fresh = data["businesses"]
    assert (known["id"], known["categories"]) == ("100000002", ["eda"])
    assert known["key"].endswith("-100000002")
    assert fresh["id"] == "10000005"


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


def test_same_number_twice_is_one_card(isolated):
    # инициатива внесла бизнес дважды («Cacafe» и «Ca.ca.fe», 2 ноя): одна карточка, новый адрес к ней,
    # и строка-продолжение после дубля относится к нему, а не к соседу выше
    data, warnings = build.build(sheet(
        f"Kafa,Kafe,12345678,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,",
        f"Bar,Bar,87654321,Ulica 9,Beograd,{gmaps(44.82, 20.47)},,,,",
        f"K.a.f.a,Kafe,12345678,Ulica 1,Beograd,{gmaps(44.81, 20.46)},,,,",
        f",,,Bulevar 2,Novi Sad,{gmaps(45.25, 19.83)},,,,",
    ))
    kafa, bar = data["businesses"]
    assert [loc["address"] for loc in kafa["locations"]] == ["Ulica 1", "Bulevar 2"]
    assert [loc["address"] for loc in bar["locations"]] == ["Ulica 9"]
    assert any("склеены" in w for w in warnings)


def test_todo_lists_what_still_needs_hands(isolated, monkeypatch):
    # список дел: бизнес без записи в обогащении и адрес без точки; no_point — искали и не нашли, из списка уходит
    monkeypatch.setattr(build, "OVERRIDES", {"12345678": {"no_point": ["B 2"]}})
    _, warnings, todo = build.assemble(sheet(
        '"Mreža",Kafe,12345678,"A 1\nB 2",Beograd,https://www.google.com/maps/placelists/list/abc,,,,',
        f'Novi,Bar,87654321,Ulica 9,Beograd,"{gmaps(44.82, 20.47)}",,,,',  # в ссылке запятые: в CSV — в кавычках
    ))
    assert [(t["id"], t["curated"], [m["address"] for m in t["missing"]]) for t in todo] == [
        ("12345678", True, ["A 1"]), ("87654321", False, [])]
    assert not any("B 2" in w for w in warnings)


@pytest.mark.parametrize(("address", "query"), [
    ("Cerska 115 stan PP (zakazivanje samo putem instagrama)", ("Cerska 115", "115")),
    ("Beograd, Dalmatinska 72", ("Dalmatinska 72", "72")),
    ("Kраљевића Марка 5, Београд 11050, Сербия", ("Kраљевића Марка 5", "5")),
    ("Maršala Birjuzova 2-4", ("Maršala Birjuzova 2", "2")),
    ("Dimitrija Tucovića 2a, 8 (moze i online)", ("Dimitrija Tucovića 2a", "2a")),
    ("Bulevar Kralja Aleksandra", None),
    ("Mix Markt, Beograđanka", None),
])
def test_street_query_keeps_street_and_house_number(address, query):
    assert todo_mod.street_query(address) == query


def test_geocode_hit_is_reliable_only_with_same_house_inside_city():
    hit = {"lat": "44.8143", "lon": "20.4591", "address": {"house_number": "2а"}}
    assert todo_mod.reliable("2a", "beograd", hit)  # кириллическая «а» = латинская
    assert not todo_mod.reliable("4", "beograd", hit)
    assert not todo_mod.reliable("2a", "beograd", {**hit, "lat": "44.49"})  # тот же адрес в пригороде
    assert not todo_mod.reliable("2a", None, hit)
    assert todo_mod.reliable("2", "beograd", {**hit, "address": {"house_number": "2-4"}})  # дом-диапазон


SPLIT_HEADER = "Naziv,Delatnost,Matični broj,PIB,Adresa,Grad,Google maps,Sajt biznisa,Threads ,Telegram,Instagram,Komentar\n"


def test_mb_and_pib_in_separate_columns_keep_the_known_id(isolated, monkeypatch):
    # 2 ноя таблица разделила «Matični broj / PIB» на две колонки: читаются обе, а id остается тем,
    # под которым бизнес уже есть в обогащении (иначе разосланные ссылки «Поделиться» ломаются)
    monkeypatch.setattr(build, "OVERRIDES", {"100000002": {"name": "Pekara"}})
    data, _ = build.build(SPLIT_HEADER + "\n".join([
        f'Stara,Pekara,10000001,100000002,Ulica 1,Beograd,"{gmaps(44.81, 20.46)}",,,,,',
        f'Nova,Kafe,10000003,100000004,Ulica 2,Beograd,"{gmaps(44.82, 20.47)}",,,,,',
    ]) + "\n")
    old, new = data["businesses"]
    assert (old["id"], old["name"]) == ("100000002", "Pekara")
    assert new["id"] == "10000003"  # нового в обогащении нет — первым идет MB


def test_rows_above_the_column_names_are_not_businesses(isolated):
    # 3 ноя над названиями колонок появились строки со ссылками на сайты-карты и оговоркой:
    # заголовок ищется по «Naziv», все, что выше, — не бизнесы
    above = "SAJTOVI ZA PREGLED TABELE,,,,,,,,,,,\nhttps://example.org/,,,,,,,,,,,\n*Napomena,,,,,,,,,,,\n"
    data, _ = build.build(above + SPLIT_HEADER + f'Kafe,Kafe,10000001,100000002,Ulica 1,Beograd,"{gmaps(44.81, 20.46)}",,,,,\n')
    assert [b["name"] for b in data["businesses"]] == ["Kafe"]


@pytest.mark.parametrize(("in_overrides", "in_sheet"), [
    ("Kраљевића Марка 5, Београд 11050, Сербия", "Kraljevića Marka 5"),  # латинская K среди кириллицы
    ("Palmoticheva, 5", "Palmoticheva 5"),
    ("Beograd, Dalmatinska 72", "Dalmatinska 72"),
    ("Kapetan-Misina 17, Beograd", "Kapetan Mišina 17"),
    ("Маjке Jeвросиме 35", "Majke Jevrosime 35"),
])
def test_point_survives_address_rewritten_in_the_sheet(in_overrides, in_sheet):
    # инициатива чистит адреса: точка в overrides.json должна найтись и после этого
    assert build.addr_key(in_overrides) == build.addr_key(in_sheet)


def test_different_houses_stay_different():
    assert build.addr_key("Cerska 115") != build.addr_key("Cerska 11")
    assert build.addr_key("Beogradska 5") != build.addr_key("5")  # «Beograd» вычеркивается только словом


def test_same_house_in_two_places_is_not_reliable():
    # одна улица с тем же домом и в центре, и на окраине — оба в границах Белграда: точку проверяют руками
    center = {"lat": "44.8141", "lon": "20.4558", "address": {"road": "Липова", "house_number": "8"}}
    edge = {"lat": "44.7491", "lon": "20.6016", "address": {"road": "Lipova", "house_number": "8"}}
    assert todo_mod.judge("Lipova 8", "8", "beograd", [center])[0] == "надежно"
    verdict, hit = todo_mod.judge("Lipova 8", "8", "beograd", [edge, center])
    assert verdict.startswith("проверить") and hit is edge
    assert todo_mod.judge("Lipova 8", "8", "beograd", [])[0] == "не нашел"


def test_neighbour_street_with_same_number_does_not_make_it_ambiguous():
    # OpenStreetMap подмешивает другую улицу с тем же номером дома — это не второй кандидат
    right = {"lat": "44.7995", "lon": "20.4871", "address": {"road": "Липова", "house_number": "8"}}
    other = {"lat": "44.8460", "lon": "20.4117", "address": {"road": "Brestova", "house_number": "8"}}
    verdict, hit = todo_mod.judge("Lipova 8", "8", "beograd", [right, other])
    assert verdict == "надежно" and hit is right


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


def test_online_in_the_address_column_is_an_online_business(isolated):
    # 3 ноя «online» написали в колонку адреса при городе Beograd: это не точка, а онлайн-бизнес
    data, _ = build.build(sheet(
        "Torte,Torte za pse,12345678,online,Beograd,,,,,",
        f'Engleski,Kursevi,12345679,Ulica 2a (moze i online),Novi Sad,"{gmaps(45.25, 19.84)}",,,,',
    ))
    online, address = data["businesses"]
    assert online["online"] and online["locations"] == []
    # «можно и онлайн» рядом с номером дома — адрес остается, точка на месте
    assert not address["online"] and address["locations"][0]["lat"] == 45.25


def test_continuation_row_without_city_keeps_the_business_city(isolated):
    # вторая точка Willow пришла строкой-продолжением без города: она в том же городе, что и бизнес
    data, _ = build.build(sheet(
        f'Kafe,Kafe,12345678,A 1,Novi Sad,"{gmaps(45.25, 19.84)}",,,,',
        f',,,B 2,,"{gmaps(45.26, 19.85)}",,,,',
    ))
    [b] = data["businesses"]
    assert [loc["city"] for loc in b["locations"]] == ["novi-sad", "novi-sad"]


def test_city_line_per_address_line_pairs_them(isolated):
    # Julianna и Kofilin, 4 ноя: два кафе в Нови-Саде и третье в Белграде, город строкой на каждый адрес
    data, _ = build.build(sheet(
        f'Mreža,Kafe,12345678,"A 1\nB 2\nC 3","Novi Sad\nNovi Sad\nBeograd",'
        f'"{gmaps(45.25, 19.84)}\n{gmaps(45.26, 19.85)}\n{gmaps(44.80, 20.45)}",,,,',
    ))
    [b] = data["businesses"]
    assert [loc["city"] for loc in b["locations"]] == ["novi-sad", "novi-sad", "beograd"]
    assert set(data["cities"]) == {"novi-sad", "beograd"}


def test_business_without_address_keeps_its_cities(isolated):
    # сеть без списка точек (Fix Price, 4 ноя): на карте ее нет, но фильтр города должен ее найти
    data, _ = build.build(sheet('Mreža,Prodavnica,12345678,,"Beograd, Novi Sad",,,,,'))
    [b] = data["businesses"]
    assert (b["locations"], b["online"], b["cities"]) == ([], False, ["beograd", "novi-sad"])


def test_address_without_link_searches_the_place_by_name(isolated):
    # по одному адресу Google показывает дом; с именем — карточку заведения с отзывами и фото,
    # и для строки-продолжения тоже, хотя имени в ней нет
    data, _ = build.build(sheet(
        'Kafe Zora,Kafe,12345678,Cerska 1,Beograd,,,,,',
        ',,,Gajeva 2,,,,,,',
    ))
    [b] = data["businesses"]
    links = [urllib.parse.unquote(loc["maps"]) for loc in b["locations"]]
    assert links == ["https://www.google.com/maps/search/?api=1&query=Kafe Zora, Cerska 1, Beograd, Srbija",
                     "https://www.google.com/maps/search/?api=1&query=Kafe Zora, Gajeva 2, Srbija"]


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
