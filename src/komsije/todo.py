"""Что осталось обогатить: бизнесы без записи в data/overrides.json и адреса без точки на карте.

    python -m komsije.todo               # скачать таблицу и показать список
    python -m komsije.todo --geocode     # плюс предложить точки из OpenStreetMap (1 запрос в секунду)
    python -m komsije.todo --csv x.csv   # из локального CSV

Точка «надежно» — только если OpenStreetMap нашел тот же номер дома внутри границ того же города, и в одном месте.
Остальное проверяют руками (ссылка Google Maps из таблицы) или записывают адрес в no_point.
Порядок работы — .claude/commands/enrich.md.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import build

# Границы городов для поиска: без них OpenStreetMap находит тот же адрес в пригороде за 40 км
# (2 ноя «Maršala Birjuzova 2» нашелся у Барајево вместо центра Белграда).
BOUNDS = {  # id города → (запад, юг, восток, север)
    "beograd": (20.25, 44.70, 20.65, 44.90),
    "novi-sad": (19.75, 45.20, 19.95, 45.32),
}
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def street_query(address: str) -> tuple[str, str] | None:
    """Адрес как в таблице → («улица номер», номер) для поиска; без номера дома — None.

    «Cerska 115 stan PP (zakazivanje…)» → («Cerska 115», «115»); «Beograd, Dalmatinska 72» → («Dalmatinska 72», «72»).
    Почтовый индекс (5 цифр) номером дома не считается; из диапазона «2-4» берется первый номер.
    """
    for part in address.split("(")[0].split(","):
        m = re.match(r"\s*([^\W\d_][\w.'\- ]*?)\s+(\d{1,4}[^\W\d_]?)(?!\d)", part)
        if m:
            return f"{m.group(1).strip()} {m.group(2)}", m.group(2)
    return None


def _house(n: str) -> str:
    """Номер дома для сравнения: кириллическая «а» и латинская «a» — одна буква."""
    return n.lower().replace("а", "a").replace("б", "b").replace(" ", "")


def reliable(number: str, city: str | None, hit: dict) -> bool:
    """Точке можно верить: тот же номер дома (у диапазона «2-4» — первый) и внутри границ нужного города."""
    found = _house(hit.get("address", {}).get("house_number", ""))
    if city not in BOUNDS or _house(number) not in (found, found.split("-")[0]):
        return False
    west, south, east, north = BOUNDS[city]
    return south <= float(hit["lat"]) <= north and west <= float(hit["lon"]) <= east


def geocode(street: str, city: str | None) -> list[dict]:
    """До пяти кандидатов: одного мало, в Белграде бывает несколько улиц с одним именем."""
    params = {"street": street, "country": "Serbia", "format": "json", "limit": 5, "addressdetails": 1}
    if city in BOUNDS:
        params.update(viewbox=",".join(map(str, BOUNDS[city])), bounded=1)
    req = urllib.request.Request(f"{NOMINATIM}?{urllib.parse.urlencode(params)}", headers={"User-Agent": build.UA})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except (OSError, ValueError):
        return []


def same_street(street: str, hit: dict) -> bool:
    """У кандидата та же улица: общее слово длиннее трех букв, кириллица и латиница сравниваются как одно.

    OpenStreetMap подмешивает соседние улицы с тем же номером: 3 ноя на «Gajeva 8» вернулась и «Лагумска 8».
    """
    def words(s: str) -> set[str]:
        return {w for w in build.addr_key(s).split() if len(w) > 3}
    return bool(words(street) & words(hit.get("address", {}).get("road", "")))


def judge(street: str, number: str, city: str | None, hits: list[dict]) -> tuple[str, dict | None]:
    """Вердикт по кандидатам: «надежно» — только если тот же дом на той же улице в городе нашелся в одном месте.

    2 ноя «Jug Bogdanova 8» нашелся в Савском венце, Винче и Лештане — все три в границах Белграда,
    и первым OpenStreetMap отдал Винчу, а бизнес в центре. Несколько мест — «проверить».
    Кандидаты с другой улицей не считаются, если есть хоть один с той же.
    """
    good = [h for h in hits if reliable(number, city, h)]
    good = [h for h in good if same_street(street, h)] or good
    places = {(round(float(h["lat"]), 2), round(float(h["lon"]), 2)) for h in good}  # ~1 км
    if len(places) == 1:
        return "надежно", good[0]
    if good:
        return f"проверить, таких домов в городе несколько ({len(places)})", good[0]
    return ("проверить", hits[0]) if hits else ("не нашел", None)


def report(todo: list[dict], cities: dict, do_geocode: bool) -> str:
    out: list[str] = []
    fresh = [t for t in todo if not t["curated"]]
    out.append(f"## Нужна запись в overrides.json: {len(fresh)}")
    for t in fresh:
        out.append(f"- {t['id']} · {t['name']} · {t['activity'] or '(без описания)'}"
                   f" · угадано: {', '.join(t['categories'])} · ссылки: {', '.join(t['links']) or 'нет'}")
    missing = [(t, m) for t in todo for m in t["missing"]]
    out.append(f"\n## Адреса без точки: {len(missing)}")
    for t, m in missing:
        city = cities.get(m["city"], {}).get("sr", "?")
        line = f"- {t['name']} ({t['id']}) · {city} · {json.dumps(m['address'], ensure_ascii=False)}"
        q = street_query(m["address"])
        if not q:
            out.append(f"{line} → без номера дома: ссылка Google Maps из таблицы или no_point")
            continue
        if not do_geocode:
            out.append(f"{line} → искать: {q[0]}")
            continue
        verdict, hit = judge(q[0], q[1], m["city"], geocode(q[0], m["city"]))
        time.sleep(1.1)  # правила OpenStreetMap: не чаще запроса в секунду
        if not hit:
            out.append(f"{line} → OpenStreetMap не нашел: ссылка Google Maps из таблицы или no_point")
            continue
        a = hit.get("address", {})
        found = f"{a.get('road', '?')} {a.get('house_number', '?')}, {a.get('suburb') or a.get('city_district') or '?'}"
        point = [round(float(hit["lat"]), 7), round(float(hit["lon"]), 7)]
        out.append(f"{line} → {verdict}: {found}\n    \"points\": {{{json.dumps(m['address'], ensure_ascii=False)}: {point}}}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", type=Path, help="локальный CSV вместо скачивания")
    ap.add_argument("--geocode", action="store_true", help="предложить точки из OpenStreetMap")
    args = ap.parse_args()
    text = args.csv.read_text(encoding="utf-8") if args.csv else build.fetch_csv()
    data, _, todo = build.assemble(text)
    print(report(todo, data["cities"], args.geocode) if todo else "Все бизнесы обогащены, у всех адресов есть точка.")


if __name__ == "__main__":
    main()
