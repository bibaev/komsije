"""Собрать site/data.js из открытой таблицы сообщества.

Таблица — единственный источник данных: модераторы проверяют каждую запись
по MB/ПИБ. Здесь только чтение, раскладка адресов по точкам и теги.

    python -m komsije.build              # скачать таблицу и собрать
    python -m komsije.build --csv x.csv  # собрать из локального CSV

Только stdlib, чтобы контрибьютору не нужно было ничего ставить.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from . import paths

CONFIG = json.loads(paths.CONFIG.read_text(encoding="utf-8"))
CATEGORIES = json.loads(paths.CATEGORIES.read_text(encoding="utf-8"))
OVERRIDES = json.loads(paths.OVERRIDES.read_text(encoding="utf-8"))
CACHE_PATH = paths.GEOCACHE
OUT_PATH = paths.DATA_JS

UA = "komsije/0.1"
CITIES = {
    "beograd": {"ru": "Белград", "sr": "Beograd"},
    "novi-sad": {"ru": "Нови-Сад", "sr": "Novi Sad"},
    "subotica": {"ru": "Суботица", "sr": "Subotica"},  # 3 ноя — первый бизнес (SU Bar)
}
# Как люди пишут город в таблице → id. Ключи после norm(); кириллица в нём остаётся кириллицей.
CITY_ALIASES = {
    "beograd": "beograd", "belgrade": "beograd", "novi beograd": "beograd", "zemun": "beograd",
    "београд": "beograd", "белград": "beograd", "нови београд": "beograd",
    "novi sad": "novi-sad", "novisad": "novi-sad", "нови сад": "novi-sad", "нови-сад": "novi-sad",
    "subotica": "subotica", "суботица": "subotica",
}
ONLINE = re.compile(r"online|onlajn|онлајн|онлайн|internet")
# Хвосты ссылок из соцсетей: метки трекинга, не адрес.
DROP_PARAMS = re.compile(r"^(utm_.*|fbclid|hl|mdxt|xmt|igsh|igshid|si|g_ep|skid|entry)$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("đ", "d")


# Кириллица → латиница для сравнения адресов (сербская азбука плюс русские буквы, которые встречаются в таблице)
CYR = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "d", "е": "e", "ж": "z", "з": "z", "и": "i",
    "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "ћ": "c", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "c", "џ": "dz", "ш": "s",
    "щ": "s", "ы": "y", "э": "e", "ю": "ju", "я": "ja", "ь": "", "ъ": "", "й": "j",
})


def addr_key(address: str) -> str:
    """Адрес → ключ для точек из overrides.json: без регистра, диакритики, разницы кириллицы и латиницы,
    города, индекса и знаков. 2 ноя инициатива почистила адреса («Palmoticheva, 5» → «Palmoticheva 5»,
    кириллицу → латиницу), и точки, привязанные к адресу дословно, отвалились."""
    s = norm(address).translate(CYR)
    s = re.sub(r"\b\d{5}\b", " ", s)  # почтовый индекс
    s = re.sub(r"\b(beograd|belgrade|novi sad|srbija|serbija|serbia)\b", " ", s)
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def lines(cell: str) -> list[str]:
    return [x.strip() for x in cell.splitlines() if x.strip() and x.strip() != "-"]


def clean_url(url: str) -> str | None:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return None
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not DROP_PARAMS.match(k)]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urllib.parse.urlencode(q), ""))


# Ссылки в таблице пишут как придётся: «@askona_serbia», «reparo.rs», «t.me/Reparo_NS», «@a — текст, @b».
PROFILE = {
    "instagram": "https://www.instagram.com/{}/",
    "telegram": "https://t.me/{}",
    "threads": "https://www.threads.com/@{}",
}
HANDLE = re.compile(r"^@?([A-Za-z0-9._]{2,40})$")
DOMAIN = re.compile(r"^(www\.)?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(/\S*)?$")


def to_link(kind: str, raw: str) -> str | None:
    """Ячейка ссылки → https-адрес. Берётся первое слово ячейки; непонятное — None, а не догадка."""
    word = raw.strip().split()[0].rstrip(",;") if raw.strip() else ""
    if not word or word == "-":
        return None
    if re.match(r"^https?://", word, re.IGNORECASE):
        return clean_url(word)
    if re.match(r"^(t\.me|www\.(instagram|threads)\.com|instagram\.com|threads\.(net|com))/", word, re.IGNORECASE):
        return clean_url("https://" + word)
    if kind == "site":
        return clean_url("https://" + word) if DOMAIN.match(word) and not word.startswith("@") else None
    m = HANDLE.match(word)
    return PROFILE[kind].format(m.group(1)) if m else None


# --- координаты -------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _expand(url: str) -> str:
    """Короткая ссылка maps.app.goo.gl → полный URL Google Maps (один редирект)."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        return opener.open(req, timeout=15).geturl()
    except urllib.error.HTTPError as e:
        return e.headers.get("Location", "") or url


def coords_from_maps_url(url: str) -> tuple[float, float] | None:
    # !3d…!4d… — точка самого места; @lat,lng — центр карты, хуже, но рядом.
    for pat in (r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", r"@(-?\d+\.\d+),(-?\d+\.\d+)",
                r"[?&](?:q|query|ll)=(-?\d+\.\d+),(-?\d+\.\d+)"):
        m = re.search(pat, url)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


def resolve(url: str, cache: dict) -> tuple[float, float] | None:
    if url not in cache:
        full = _expand(url) if "goo.gl" in url else url
        c = coords_from_maps_url(full)
        cache[url] = list(c) if c else None
    c = cache[url]
    return tuple(c) if c else None


# --- таблица ----------------------------------------------------------------

COLS = {
    # Номер: сначала был одной колонкой «Matični broj / PIB», 2 ноя ее разделили на две — читаем оба вида,
    # значения склеиваются в одно поле (MB первым), поэтому id бизнеса и ссылки «Поделиться» не меняются.
    "naziv": "name", "delatnost": "activity", "maticni broj / pib": "pib", "maticni broj": "pib", "pib": "pib",
    "adresa": "address", "grad": "city", "google maps": "maps",
    "sajt biznisa": "site", "threads": "threads", "telegram": "telegram",
    "instagram": "instagram",
}


def fetch_csv() -> str:
    url = (f"https://docs.google.com/spreadsheets/d/{CONFIG['sheet_id']}"
           f"/export?format=csv&gid={CONFIG['gid']}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


def parse_rows(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    try:
        hi = next(i for i, r in enumerate(rows) if r and norm(r[0]) == "naziv")
    except StopIteration:
        sys.exit("Не нашёл строку заголовков (первая ячейка «Naziv»): структура таблицы поменялась")
    keys = [COLS.get(norm(h)) for h in rows[hi]]
    out = []
    for r in rows[hi + 1:]:
        rec: dict[str, str] = {}
        for k, v in zip(keys, r):
            if k:  # две колонки в одно поле (MB и PIB) — через пробел, а не последняя побеждает
                rec[k] = f"{rec[k]} {v}".strip() if k in rec else v
        if any(v.strip() for v in rec.values()):
            out.append(rec)
    return out


def guess_categories(activity: str) -> list[str]:
    a = norm(activity)
    found = [cid for cid, c in CATEGORIES.items()
             if any(re.search(p, a) for p in c.get("match", []))]
    return found[:2] or ["drugoe"]


def cities_of(raw: str) -> list[tuple[str, dict]]:
    """Ячейка «Grad» → [(id, подписи)]. Пустой список — бизнес онлайн.

    Пишут по-разному: «Online prodavnica», «Нови Сад», «Beograd, Novi Beograd» (один город),
    «Beograd, Novi Sad» (два города).
    """
    n = norm(raw)
    if not n or ONLINE.search(n):
        return []
    out: dict[str, dict] = {}
    for part in re.split(r"[,/;\n]|\s+i\s+|\s+и\s+", raw):
        p = norm(part)
        if not p:
            continue
        cid = CITY_ALIASES.get(p) or re.sub(r"[^\w]+", "-", p).strip("-")
        out.setdefault(cid, CITIES.get(cid, {"ru": part.strip(), "sr": part.strip()}))
    return list(out.items())


def build(text: str) -> tuple[dict, list[str]]:
    data, warnings, _ = assemble(text)
    return data, warnings


def assemble(text: str) -> tuple[dict, list[str], list[dict]]:
    """Данные сайта, предупреждения и список дел для обогащения (его печатает komsije.todo)."""
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    businesses: list[dict] = []
    cities: dict[str, dict] = {}
    warnings: list[str] = []

    used: set[str] = set()
    by_id: dict[str, dict] = {}
    current: dict | None = None  # бизнес, к которому относятся строки-продолжения
    ov: dict = {}
    skip = ""

    for rec in parse_rows(text):
        name = rec.get("name", "").strip()
        # В ячейке бывает «MB / PIB» вместе: id — первый номер, override ищем по любому.
        # Строка-продолжение (без имени) — ещё точки прошлого бизнеса, его override и берём.
        nums = re.findall(r"\d{8,9}", rec.get("pib", ""))
        if name:
            ov = next((OVERRIDES[n] for n in nums if n in OVERRIDES), {})
            # Не показываем ни бизнес, ни его строки-продолжения, и город ради него не заводим, если:
            # - нет номера MB или ПИБ: инициатива проверяет по нему, без номера это шум или поломка
            #   (2 ноя во вкладку попала строка из одного символа «`»);
            # - бизнес попросил убрать себя, а правка таблицы ждёт инициативу (hidden).
            skip = ("нет номера MB или ПИБ, строка пропущена" if not nums
                    else f"скрыт — {ov['hidden']}" if ov.get("hidden") else "")
            if skip:
                warnings.append(f"«{ov.get('name') or name}»: {skip}")
        if skip:
            continue
        row_cities = cities_of(rec.get("city", ""))
        cities.update(row_cities)
        city_ids = [cid for cid, _ in row_cities]
        # Город строкой на каждый адрес («Novi Sad\nNovi Sad\nBeograd», Julianna и Kofilin 4 ноя): строка города
        # к строке адреса. Список городов выше повторы склеивает, по нему пары не составить
        line_cities = [ids[0][0] if len(ids := cities_of(c)) == 1 else None for c in lines(rec.get("city", ""))]
        points = {addr_key(a): ll for a, ll in ov.get("points", {}).items()}

        # «online» пишут и в колонку адреса при обычном городе (3 ноя: психолог, торты для собак):
        # это не место, а признак онлайн-бизнеса. Но «Dimitrija Tucovića 2a (moze i online)» — адрес:
        # онлайн только строка без номера дома
        all_addrs = lines(rec.get("address", ""))
        addrs = [a for a in all_addrs if not (ONLINE.search(norm(a)) and not re.search(r"\d", a))]
        online_only = bool(all_addrs) and not addrs
        # В колонку карт пишут и текст («Radim onlajn…»): точку дают только ссылки.
        links = [u for u in lines(rec.get("maps", "")) if clean_url(u)]
        used.update(links)
        # Одна ссылка на несколько адресов (Smart Coffee) — это список мест,
        # а не точка: координат в нём нет.
        paired = len(links) == len(addrs) or (len(links) == 1 and not addrs)
        n_locs = max(len(addrs), len(links) if paired else 0)
        locs = []
        for i in range(n_locs):
            addr = addrs[i] if i < len(addrs) else ""
            link = clean_url(links[i]) if paired and i < len(links) else None
            ll = resolve(links[i], cache) if paired and i < len(links) else None
            # Ссылка «поделиться» с телефона и список мест ведут на поиск без координат:
            # точку по адресу ставят руками в overrides.json («points»).
            ll = ll or (tuple(points[addr_key(addr)]) if addr_key(addr) in points else None)
            # Город строкой на адрес или два города на два адреса — по порядку; иначе все точки в первом городе ячейки.
            if len(line_cities) == n_locs > 1 and all(line_cities):
                city = line_cities[i]
            else:
                city = city_ids[i] if len(city_ids) == n_locs > 1 else (city_ids[0] if city_ids else None)
            # Ссылка ведет на карточку места в Google Maps: отзывы и фото, маршрут оттуда же. Ссылки из таблицы
            # открывают карточку сами (3 ноя: 15 из 15 в выборке). Без ссылки ищем по имени и адресу: по одному
            # адресу Google показывает дом, а не заведение в нем
            who = name or (current["name"] if current else "")
            maps = link or (
                "https://www.google.com/maps/search/?api=1&query="
                + urllib.parse.quote(", ".join(p for p in (who, addr, rec.get("city", "").strip(), "Srbija") if p)))
            locs.append({"address": addr, "city": city,
                         "lat": ll[0] if ll else None, "lng": ll[1] if ll else None,
                         "maps": maps})
        list_link = clean_url(links[0]) if links and not paired else None

        if not name:
            # Строка-продолжение: ещё точки предыдущего бизнеса (VapeMe в Нови-Саде).
            # Город в ней часто не повторяют (Willow, 3 ноя) — тогда он тот же, что у бизнеса.
            if current:
                home = next((loc["city"] for loc in current["locations"] if loc["city"]), None)
                for loc in locs:
                    loc["city"] = loc["city"] or home
                current["locations"].extend(locs)
            continue

        # id — номер, под которым бизнес уже записан в обогащении: 2 ноя таблица разделила MB и PIB, и у части
        # бизнесов первым номером стал MB. Без этого их ключи и разосланные ссылки «Поделиться» сменились бы.
        pib = next((n for n in nums if n in OVERRIDES), nums[0])
        if pib in by_id:
            # Один бизнес двумя строками («Cacafe» и «Ca.ca.fe», 2 ноя): одна карточка, новые адреса — к ней.
            current = by_id[pib]
            have = {loc["address"] for loc in current["locations"]}
            current["locations"].extend(loc for loc in locs if loc["address"] not in have)
            warnings.append(f"«{name}»: тот же номер, что у «{current['name']}», строки склеены в одну карточку")
            continue
        activity = " ".join(lines(rec.get("activity", "")))
        # В таблице часто юридическое имя («… PR», «d.o.o.»); слой обогащения даёт человеческое.
        name = ov.get("name") or name
        slug = re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")[:40].strip("-") or "biz"
        b = {
            "id": pib,
            # Ключ ссылки «поделиться»: имя для читаемости, номер для стабильности —
            # app.js находит бизнес по номеру в хвосте, даже если имя поменяли.
            "key": f"{slug}-{pib}",
            "_curated": bool(ov),
            "_points": list(ov.get("points", {})),
            "_no_point": list(ov.get("no_point", [])),
            "name": name,
            "online": not city_ids or online_only,
            # Города из ячейки: по ним фильтр города находит бизнес без адреса (сеть Fix Price, 4 ноя)
            "cities": city_ids,
            "categories": ov.get("categories") or guess_categories(activity),
            "tags": ov.get("tags", {"ru": [], "sr": []}),
            "description": {"ru": ov.get("description_ru") or activity, "sr": ov.get("description_sr") or activity},
            "locations": locs,
            "places_list": list_link,
            "links": {k: u for k in ("instagram", "telegram", "threads", "site")
                      if (u := to_link(k, lines(rec.get(k, ""))[0] if lines(rec.get(k, "")) else ""))},
        }
        businesses.append(b)
        by_id[pib] = current = b

    todo: list[dict] = []
    for b in businesses:
        no_point = b.pop("_no_point")  # искали и не нашли: из списка дел уходит, в предупреждения не попадает
        no_point_keys = {addr_key(a) for a in no_point}
        missing = [loc for loc in b["locations"] if loc["lat"] is None and addr_key(loc["address"]) not in no_point_keys]
        if missing:
            warnings.append(f"{b['name']}: без точки на карте — {', '.join(loc['address'] for loc in missing)}")
        # Точка из overrides.json ищется по адресу (addr_key): адрес в таблице заменили на другой — точка пропала.
        here = {addr_key(loc["address"]) for loc in b["locations"]}
        stale = {a for a in b.pop("_points") + no_point if addr_key(a) not in here}
        if stale:
            warnings.append(f"{b['name']}: в overrides.json адрес, которого нет в таблице — "
                            f"{', '.join(sorted(stale))}")
        curated = b.pop("_curated")
        if not curated:
            warnings.append(f"{b['name']}: нет в overrides.json, теги угаданы по описанию")
        if missing or not curated:
            todo.append({"id": b["id"], "name": b["name"], "curated": curated,
                         "activity": b["description"]["sr"], "categories": b["categories"],
                         "links": sorted(b["links"]),
                         "missing": [{"address": loc["address"], "city": loc["city"]} for loc in missing]})

    # В кэше остаются только ссылки из текущей таблицы: удалённые строки не копятся.
    cache = {k: v for k, v in cache.items() if k in used}
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
    # Два времени: synced_at — эта сверка с таблицей (его и видит человек, точно до минуты);
    # generated_at — когда данные последний раз поменялись (для журнала и решения «деплоить ли»).
    synced_at = datetime.now(UTC).isoformat(timespec="minutes")
    changed_at = synced_at
    prev = read_data()
    if prev and prev.get("businesses") == businesses and prev.get("generated_at"):
        changed_at = prev["generated_at"]
    sheet = f"https://docs.google.com/spreadsheets/d/{CONFIG['sheet_id']}"
    return {
        "synced_at": synced_at,
        "generated_at": changed_at,
        "source": f"{sheet}/htmlview",
        "add_url": f"{sheet}/edit#gid={CONFIG['pending_gid']}" if CONFIG.get("pending_gid") else None,
        "initiative": {"name": CONFIG.get("initiative", ""), "url": CONFIG.get("initiative_url") or None,
                       "author": CONFIG.get("initiative_author") or None},
        "repo": CONFIG.get("repo_url") or None,
        # Источник тайлов — в config.json, а не в app.js: политика OSM требует менять его без правки кода.
        "tiles": CONFIG["tiles"],
        "contact": CONFIG.get("contact_url") or None,
        "categories": {k: {x: v[x] for x in ("ru", "sr")} for k, v in CATEGORIES.items()},
        "cities": cities,
        "businesses": businesses,
    }, warnings, todo


def read_data() -> dict | None:
    if not OUT_PATH.exists():
        return None
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
    except (IndexError, ValueError):
        return None


STUB = """<!doctype html>
<html lang="sr-Latn">
<head>
<meta charset="utf-8">
<title>{name} · Komšije</title>
<meta name="description" content="{desc}">
<link rel="icon" href="../../favicon.svg" type="image/svg+xml">
<meta property="og:site_name" content="Komšije">
<meta property="og:locale" content="sr_RS">
<meta property="og:title" content="{name}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">{image}
<meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url=../../?b={key}">
<script>location.replace("../../?b={key}" + (document.referrer ? "&ref=" + encodeURIComponent(document.referrer) : ""));</script>
</head>
<body><a href="../../?b={key}">{name}</a></body>
</html>
"""


def write_share_stubs(data: dict) -> None:
    """site/b/<key>/ — страница-ссылка с превью для мессенджеров, сразу ведёт в карту."""
    root = OUT_PATH.parent / "b"
    shutil.rmtree(root, ignore_errors=True)
    # Мессенджеры берут картинку превью только по полному адресу: без site_url в config.json — без картинки.
    site = (CONFIG.get("site_url") or "").rstrip("/")
    image = (f'\n<meta property="og:image" content="{html.escape(site)}/og.png">'
             '\n<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">'
             '\n<meta name="twitter:card" content="summary_large_image">') if site else ""
    for b in data["businesses"]:
        loc = next((l for l in b["locations"] if l["address"]), None)
        where = f"{loc['address']}, {data['cities'].get(loc['city'], {}).get('sr', '')}".strip(", ") if loc else "Online"
        desc = " · ".join(x for x in (b["description"]["sr"], b["description"]["ru"], where) if x)
        page = root / b["key"] / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(STUB.format(name=html.escape(b["name"]), desc=html.escape(desc), image=image,
                                    key=urllib.parse.quote(b["key"])), encoding="utf-8")


def publish(data: dict) -> None:
    """data.js для страницы, страницы-ссылки и копии ассетов бренда рядом с ним."""
    OUT_PATH.write_text("window.KOMSIJE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n",
                        encoding="utf-8")
    for name in paths.BRAND_ASSETS:
        shutil.copyfile(paths.BRAND / name, OUT_PATH.parent / name)
    write_share_stubs(data)


def fetch_published() -> None:
    """Прошлой сборки на диске нет (чистый checkout в CI) — берём опубликованный data.js.

    С ним есть с чем сравнить число бизнесов, и generated_at не сбрасывается на каждом запуске.
    Сайта ещё нет или он недоступен — молча без него: сравнивать не с чем.
    """
    site = (CONFIG.get("site_url") or "").rstrip("/")
    if not site or OUT_PATH.exists():
        return
    try:
        req = urllib.request.Request(f"{site}/data.js", headers={"User-Agent": UA})
        body = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
    except (OSError, ValueError):
        return
    OUT_PATH.write_text(body, encoding="utf-8")


def shrink_error(prev: dict | None, data: dict) -> str | None:
    """Бизнесов стало на треть меньше прошлой публикации — скорее поломка таблицы, чем жизнь."""
    if not prev or not prev.get("businesses"):
        return None
    was, now = len(prev["businesses"]), len(data["businesses"])
    if now >= was * 2 / 3:
        return None
    return (f"Бизнесов стало {now} вместо {was}: похоже, таблицу перестроили или испортили. "
            "Сайт не обновлён. Если так и задумано — запустить с --force.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, help="локальный CSV вместо скачивания")
    ap.add_argument("--force", action="store_true", help="опубликовать, даже если бизнесов стало на треть меньше")
    args = ap.parse_args()
    text = args.csv.read_text(encoding="utf-8") if args.csv else fetch_csv()
    fetch_published()
    prev = read_data()
    data, warnings = build(text)
    if (err := shrink_error(prev, data)) and not args.force:
        sys.exit(err)
    publish(data)
    pins = sum(1 for b in data["businesses"] for l in b["locations"] if l["lat"] is not None)
    print(f"{len(data['businesses'])} бизнесов, {pins} точек на карте → {OUT_PATH}")
    for w in warnings:
        print("  ·", w)


if __name__ == "__main__":
    main()
