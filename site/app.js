(function () {
  "use strict";

  const D = window.KOMSIJE_DATA;
  const $ = (s) => document.querySelector(s);

  // --- тексты ----------------------------------------------------------------
  function plural(n, f) {
    const a = n % 10, b = n % 100;
    if (a === 1 && b !== 11) return f[0];
    if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return f[1];
    return f[2];
  }
  const T = {
    ru: {
      brand: "Комшије", title: "Зайди к соседям",
      lede: "Здесь бизнесы, чьи деньги застряли в Alta banka, а аренда и зарплаты ждать не могут. Среди них могут оказаться и твои соседи: кофейня, парикмахер, книжный за углом. Зайти к ним сейчас значит больше, чем обычно.",
      search: "Кофе, маникюр, суши или название",
      all: "Все", allCats: "Всё", online: "Онлайн",
      near: "Рядом со мной", locating: "Ищу, где ты…",
      geoFail: "Не получилось определить, где ты. Разреши доступ к геолокации и попробуй еще раз.",
      sorted: "Сначала ближайшие к тебе", random: "В случайном порядке, чтобы никто не был первым всегда",
      share: "Поделиться", copied: "Ссылка скопирована", copyThis: "Скопируй ссылку:",
      route: "Маршрут", site: "Сайт", onlineShop: "Работает онлайн, заказ через соцсети или сайт",
      noPin: "нет на карте", placesList: "Все точки на Google Maps", more: (n) => `еще ${n}`,
      empty: "Ничего не нашлось.", reset: "Сбросить фильтры",
      places: (n) => `${n} ${plural(n, ["место", "места", "мест"])}`,
      srcLabel: "Откуда список", quote: ["«", "»"],
      srcText: ["Список собирает и проверяет по ПИБ сербская инициатива ", ". Карта только показывает его."],
      srcBy: ", ее начала ",
      srcSheet: "Таблица инициативы ↗", srcAdd: "Добавить свой бизнес ↗",
      synced: "Сверено с таблицей",
      report: ["Ошибка на карте? ", "Сообщи о ней на GitHub"],
      contact: "Вопрос или идея? Пиши в Telegram: ",
      code: ["Код открыт, правку можно предложить на ", "GitHub"],
      km: "км", m: "м", locale: "ru-RU",
      and: " и ",
    },
    sr: {
      brand: "Komšije", title: "Svrati kod komšija",
      lede: "Ovde su biznisi čiji je novac zaglavljen u Alta banci, a kirija i plate ne mogu da čekaju. Među njima su možda i tvoje komšije: kafić, frizer, knjižara iza ugla. Svratiti kod njih sada znači više nego inače.",
      search: "Kafa, manikir, suši ili naziv",
      all: "Svi", allCats: "Sve", online: "Online",
      near: "Blizu mene", locating: "Tražim lokaciju…",
      geoFail: "Nije uspelo određivanje lokacije. Dozvoli pristup lokaciji i pokušaj ponovo.",
      sorted: "Prvo najbliži tebi", random: "Nasumičnim redosledom, da niko nije uvek prvi",
      share: "Podeli", copied: "Link je kopiran", copyThis: "Kopiraj link:",
      route: "Kako stići", site: "Sajt", onlineShop: "Radi online, porudžbine preko mreža ili sajta",
      noPin: "nije na mapi", placesList: "Sve lokacije na Google Maps", more: (n) => `još ${n}`,
      empty: "Nema rezultata.", reset: "Poništi filtere",
      places: (n) => `${n} ${plural(n, ["mesto", "mesta", "mesta"])}`,
      srcLabel: "Odakle spisak", quote: ["„", "“"],
      srcText: ["Spisak prikuplja i proverava po PIB-u srpska inicijativa ", ". Mapa ga samo prikazuje."],
      srcBy: ", koju je pokrenula ",
      srcSheet: "Tabela inicijative ↗", srcAdd: "Dodaj svoj biznis ↗",
      synced: "Usklađeno sa tabelom",
      report: ["Greška na mapi? ", "Prijavi je na GitHubu"],
      contact: "Pitanje ili ideja? Piši mi na Telegramu: ",
      code: ["Kod je otvoren, izmenu možeš da predložiš na ", "GitHubu"],
      km: "km", m: "m", locale: "sr-Latn-RS",
      and: " i ",
    },
  };

  // --- хранилище (может быть недоступно) ---------------------------------------
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* приватное окно */ } },
  };

  function initialLang() {
    const p = new URLSearchParams(location.search).get("lang");
    if (p && T[p]) return p;
    const s = store.get("komsije-lang");
    if (s && T[s]) return s;
    return /^(sr|hr|bs|me)\b/i.test(navigator.language || "") ? "sr" : "ru";
  }

  // Город по умолчанию — Белград: в режиме «Все» два города на одной карте
  // слипаются в два комка, и непонятно, куда идти. Ссылка ?city=novi-sad — для чатов Нови-Сада.
  function initialCity() {
    const ok = (c) => c && (c === "all" || c === "online" || D.cities[c]);
    const p = new URLSearchParams(location.search).get("city");
    if (ok(p)) return p;
    const s = store.get("komsije-city");
    if (ok(s)) return s;
    return D.cities.beograd ? "beograd" : "all";
  }

  const state = { lang: initialLang(), city: initialCity(), cat: "all", q: "", me: null, active: null, expanded: new Set() };
  const t = () => T[state.lang];

  // --- ссылка на конкретный бизнес: ?b=<key>, ключ = имя + номер; ищем по номеру в хвосте ----
  function byKey(k) {
    if (!k) return null;
    const m = /(\d{8,9})$/.exec(k);
    return D.businesses.find((b) => b.key === k) || (m && D.businesses.find((b) => b.id === m[1])) || null;
  }
  const deep = byKey(new URLSearchParams(location.search).get("b"));
  if (deep) {
    const loc = deep.locations.find((l) => l.lat != null) || deep.locations[0];
    state.city = deep.online ? "online" : (loc && loc.city) || "all";
  }
  function setParam(k, v) {
    try {
      const u = new URL(location.href);
      if (v) u.searchParams.set(k, v); else u.searchParams.delete(k);
      history.replaceState(null, "", u.pathname + u.search + u.hash);
    } catch (e) { /* file:// или старый браузер */ }
  }

  // --- случайный порядок: свой на каждый визит, стабильный внутри визита ----------
  const seed = (() => {
    try {
      let s = sessionStorage.getItem("komsije-seed");
      if (!s) { s = String(Math.random()).slice(2); sessionStorage.setItem("komsije-seed", s); }
      return s;
    } catch (e) { return String(Math.random()).slice(2); }
  })();
  function rank(id) { // FNV-1a от seed+id
    let h = 2166136261;
    const s = seed + ":" + id;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  // --- поиск: без диакритики, кириллица → латиница -----------------------------
  const CYR = { а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ё:"e",ж:"z",з:"z",и:"i",й:"j",к:"k",л:"l",м:"m",н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"h",ц:"c",ч:"c",ш:"s",щ:"s",ъ:"",ы:"i",ь:"",э:"e",ю:"ju",я:"ja",ђ:"d",ј:"j",љ:"lj",њ:"nj",ћ:"c",џ:"dz" };
  const fold = (s) => (s || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");
  const translit = (s) => s.replace(/[а-яёђјљњћџ]/g, (c) => CYR[c] ?? c);
  const hay = new Map(D.businesses.map((b) => {
    const parts = [b.name, b.description.ru, b.description.sr, ...(b.tags.ru || []), ...(b.tags.sr || []),
      ...b.categories.flatMap((c) => [D.categories[c].ru, D.categories[c].sr]), ...b.locations.map((l) => l.address)];
    const f = fold(parts.join(" "));
    return [b.id, f + " " + translit(f)];
  }));

  // --- фильтры -----------------------------------------------------------------
  const inCity = (b, city) => city === "all" || (city === "online" ? b.online : b.locations.some((l) => l.city === city));
  const inCat = (b, cat) => cat === "all" || b.categories.includes(cat);
  function inQuery(b) {
    if (!state.q) return true;
    const q = fold(state.q.trim());
    const h = hay.get(b.id);
    return q.split(/\s+/).every((w) => h.includes(w) || h.includes(translit(w)));
  }
  const locsInCity = (b) => b.locations.filter((l) => state.city === "all" || l.city === state.city);

  function haversine(a, b) {
    const R = 6371, r = Math.PI / 180;
    const dLat = (b[0] - a[0]) * r, dLng = (b[1] - a[1]) * r;
    const x = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }
  function distOf(b) {
    if (!state.me) return Infinity;
    const ds = locsInCity(b).filter((l) => l.lat != null).map((l) => haversine(state.me, [l.lat, l.lng]));
    return ds.length ? Math.min(...ds) : Infinity;
  }
  const fmtDist = (km) => (km < 1 ? `${Math.max(50, Math.round(km * 20) * 50)} ${t().m}` : `${km.toFixed(km < 10 ? 1 : 0).replace(".", ",")} ${t().km}`);

  // --- DOM-помощники (только textContent, ссылки только http/https) ----------------
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function link(href, text, cls) {
    if (!/^https?:\/\//i.test(href || "")) return null;
    const a = el("a", cls, text);
    a.href = href; a.target = "_blank"; a.rel = "noopener";
    return a;
  }
  const cityLabel = (id) => (D.cities[id] ? D.cities[id][state.lang] : id);
  // Пиктограмма категории из brand/icons.svg (сборка кладёт копию в site/icons.svg). Категорию отличают значком, не цветом.
  function glyph(name) {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "ico"); svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(NS, "use");
    use.setAttribute("href", `icons.svg#i-${name}`);
    svg.append(use);
    return svg;
  }
  const pictogram = (cat) => glyph(D.categories[cat] ? cat : "drugoe");
  // Событие в счётчик: только действие и ключ бизнеса, ничего о посетителе. Нет счётчика — тишина.
  function track(path, title) {
    try { if (window.goatcounter && window.goatcounter.count) window.goatcounter.count({ path, title: title || path, event: true }); }
    catch (e) { /* счётчик не должен ломать страницу */ }
  }

  // --- карта -------------------------------------------------------------------
  const map = L.map("map", { zoomControl: false, scrollWheelZoom: true }).setView([45.03, 20.15], 9);
  L.control.zoom({ position: "topright" }).addTo(map);
  // Тайлы и подпись к ним — из config.json (D.tiles); приглушение и тёмная тема — CSS-фильтром на .leaflet-tile-pane.
  L.tileLayer(D.tiles.url, { maxZoom: D.tiles.max_zoom, attribution: D.tiles.attribution }).addTo(map);
  // Подпись Leaflet без флажка из префикса по умолчанию: символов на сайте нет (CLAUDE.md, «Границы»)
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');

  const layer = L.layerGroup().addTo(map);
  const markers = new Map(); // id -> [{marker, loc}]
  for (const b of D.businesses) {
    const list = [];
    for (const loc of b.locations) {
      if (loc.lat == null) continue;
      // Точка на карте — табличка со значком первой категории; элемент, а не HTML-строка
      const pin = el("span", "pin"); pin.append(pictogram(b.categories[0]));
      const icon = L.divIcon({ className: "pin-wrap", html: pin, iconSize: [16, 16], iconAnchor: [8, 8], popupAnchor: [0, -14] });
      const m = L.marker([loc.lat, loc.lng], { icon, title: b.name, riseOnHover: true });
      m.on("click", () => select(b.id, { fly: false, scroll: true, loc }));
      list.push({ marker: m, loc });
    }
    markers.set(b.id, list);
  }
  let meMarker = null;

  function popupFor(b, loc) {
    const box = el("div", "pop");
    box.append(el("b", null, b.name), el("span", null, b.categories.map((c) => D.categories[c][state.lang]).join(" · ")),
      el("span", null, `${loc.address}, ${cityLabel(loc.city)}`));
    const a = link(loc.route, `${t().route} ↗`);
    if (a) { a.addEventListener("click", () => track(`route/${b.key}`, b.name)); box.append(a); }
    return box;
  }

  function pinEls(id) {
    return (markers.get(id) || []).map((x) => x.marker.getElement()?.querySelector(".pin")).filter(Boolean);
  }

  // --- выбор карточки / точки --------------------------------------------------------
  function select(id, { fly = true, scroll = false, loc = null, via = "open" } = {}) {
    if (state.active) {
      pinEls(state.active).forEach((p) => p.classList.remove("is-active"));
      (markers.get(state.active) || []).forEach((x) => x.marker.setZIndexOffset(0));
    }
    document.querySelectorAll(".card.is-active").forEach((c) => c.classList.remove("is-active"));
    state.active = id;
    // Выбранная точка поверх соседних, чтобы её не закрывали
    (markers.get(id) || []).forEach((x) => x.marker.setZIndexOffset(1000));
    const b = D.businesses.find((x) => x.id === id);
    setParam("b", b.key);
    track(`${via}/${b.key}`, b.name); // open — карточка или точка, link — пришли по ссылке «Поделиться»
    const card = document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
    if (card) {
      card.classList.add("is-active");
      if (scroll) card.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    const ms = (markers.get(id) || []).filter((x) => state.city === "all" || x.loc.city === state.city);
    pinEls(id).forEach((p) => p.classList.add("is-active"));
    if (!ms.length) return;
    let target = loc ? ms.find((x) => x.loc === loc) : null;
    if (!target && state.me) target = ms.slice().sort((a, c) => haversine(state.me, [a.loc.lat, a.loc.lng]) - haversine(state.me, [c.loc.lat, c.loc.lng]))[0];
    target = target || ms[0];
    // Окно открываем после перелёта: если открыть сразу, его автоподвиг обрывает полёт,
    // и у бизнеса с несколькими точками карта оставалась на месте.
    const open = () => {
      if (state.active !== id || target.marker.isPopupOpen()) return;
      target.marker.bindPopup(popupFor(b, target.loc), { closeButton: true, autoPanPadding: [24, 24] }).openPopup();
    };
    if (!fly) return open();
    map.once("moveend", open);
    if (ms.length === 1 || state.me) map.flyTo(target.marker.getLatLng(), Math.max(map.getZoom(), 15), { duration: 0.6 });
    else map.flyToBounds(L.latLngBounds(ms.map((x) => x.marker.getLatLng())).pad(0.3), { maxZoom: 15, duration: 0.6 });
    setTimeout(open, 900); // карта уже на месте — moveend может не прийти
  }

  // --- отрисовка ---------------------------------------------------------------
  function renderStatic() {
    document.documentElement.lang = state.lang === "sr" ? "sr-Latn" : "ru";
    document.title = `${t().brand} · ${t().title}`;
    $("#title").textContent = t().title;
    $("#lede").textContent = t().lede;
    $("#q").placeholder = t().search;
    renderSource();
    renderFooter();
    document.querySelectorAll(".lang button").forEach((bt) => bt.setAttribute("aria-pressed", String(bt.dataset.lang === state.lang)));
    const cities = Object.keys(D.cities).map(cityLabel);
    $("#eyebrow").textContent = `${t().places(D.businesses.length)} · ${cities.slice(0, -1).join(", ")}${cities.length > 1 ? t().and : ""}${cities[cities.length - 1] || ""}`;
  }

  // «Откуда список»: чья таблица, как попасть на карту, когда сверено. Список — инициативы, мы только интерфейс.
  function textWithLink(before, href, label, after = "") {
    const p = document.createDocumentFragment();
    p.append(document.createTextNode(before), link(href, label) || document.createTextNode(label));
    if (after) p.append(document.createTextNode(after));
    return p;
  }
  function renderSource() {
    $("#source-label").textContent = t().srcLabel;
    const text = $("#source-text"); text.textContent = "";
    const [qo, qc] = t().quote;
    text.append(textWithLink(t().srcText[0], D.initiative.url, `${qo}${D.initiative.name}${qc}`));
    // Кто начал инициативу — по имени: список сделали они, мы только показываем
    const by = D.initiative.author;
    if (by) text.append(textWithLink(t().srcBy, by.url, by.name));
    text.append(document.createTextNode(t().srcText[1]));
    const links = $("#source-links"); links.textContent = "";
    [[D.source, t().srcSheet], [D.add_url, t().srcAdd]].forEach(([href, label]) => { const a = link(href, label); if (a) links.append(a); });
    const when = new Date(D.synced_at || D.generated_at);
    $("#synced").textContent = `${t().synced}: ${when.toLocaleString(t().locale, { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })}`;
  }
  // Подвал: куда сообщить об ошибке, как связаться, где код. Всё из config.json, чтобы форк подписал своё.
  function handle(url) {
    const m = /^https:\/\/t\.me\/(\w+)\/?$/i.exec(url);
    return m ? `@${m[1]}` : url.replace(/^https?:\/\//, "");
  }
  function renderFooter() {
    const foot = $("#foot"); foot.textContent = "";
    const line = (node) => { const p = el("p"); p.append(node); foot.append(p); };
    // Сразу форма «Ошибка на карте» (.github/ISSUE_TEMPLATE/oshibka.yml), без экрана выбора шаблона
    if (D.repo) line(textWithLink(t().report[0], `${D.repo}/issues/new?template=oshibka.yml`, t().report[1]));
    if (D.contact) line(textWithLink(t().contact, D.contact, handle(D.contact)));
    if (D.repo) line(textWithLink(t().code[0], D.repo, t().code[1]));
  }

  function button(label, count, pressed, onClick, cls, cat) {
    const b = el("button", cls);
    b.type = "button";
    if (cat) b.append(pictogram(cat));
    b.append(document.createTextNode(label));
    if (count != null) b.append(el("span", "n", String(count)));
    b.setAttribute("aria-pressed", String(pressed));
    b.addEventListener("click", onClick);
    return b;
  }

  function renderFilters() {
    const byQ = D.businesses.filter(inQuery);
    const cityBox = $("#cities"); cityBox.textContent = "";
    const cityIds = ["all", ...Object.keys(D.cities), ...(D.businesses.some((b) => b.online) ? ["online"] : [])];
    for (const c of cityIds) {
      const n = byQ.filter((b) => inCity(b, c) && inCat(b, state.cat)).length;
      const label = c === "all" ? t().all : c === "online" ? t().online : cityLabel(c);
      cityBox.append(button(label, c === "all" ? null : n, state.city === c, () => { state.city = c; store.set("komsije-city", c); track(`city/${c}`); update({ fit: true }); }));
    }
    const catBox = $("#cats"); catBox.textContent = "";
    const pool = byQ.filter((b) => inCity(b, state.city));
    catBox.append(button(t().allCats, pool.length, state.cat === "all", () => { state.cat = "all"; update({ fit: true }); }, "chip"));
    for (const [id, c] of Object.entries(D.categories)) {
      const n = pool.filter((b) => b.categories.includes(id)).length;
      if (!n && state.cat !== id) continue;
      catBox.append(button(c[state.lang], n, state.cat === id, () => { state.cat = state.cat === id ? "all" : id; if (state.cat === id) track(`cat/${id}`); update({ fit: true }); }, "chip", id));
    }
    const near = $("#near");
    near.setAttribute("aria-pressed", String(!!state.me));
    $("#near-label").textContent = t().near;
  }

  function card(b) {
    const li = el("li", "card");
    li.dataset.id = b.id;
    li.tabIndex = 0;
    if (b.id === state.active) li.classList.add("is-active");

    const top = el("div", "card-top");
    const cats = el("div", "cats");
    for (const c of b.categories) {
      const s = el("span", "cat");
      s.append(pictogram(c), document.createTextNode(D.categories[c][state.lang]));
      cats.append(s);
    }
    top.append(cats);
    if (b._dist < Infinity) top.append(el("span", "dist", fmtDist(b._dist)));
    li.append(top, el("h3", "name", b.name), el("p", "desc", b.description[state.lang]));

    const tags = b.tags[state.lang] || [];
    if (tags.length) {
      const ul = el("ul", "tags"); tags.forEach((x) => ul.append(el("li", null, x))); li.append(ul);
    }

    if (b.online) {
      li.append(el("p", "online", t().onlineShop));
    } else {
      let locs = locsInCity(b);
      if (state.me) locs = locs.slice().sort((a, c) => (a.lat == null) - (c.lat == null) || (a.lat != null && c.lat != null ? haversine(state.me, [a.lat, a.lng]) - haversine(state.me, [c.lat, c.lng]) : 0));
      const ul = el("ul", "locs");
      const limit = state.expanded.has(b.id) ? Infinity : 3;
      locs.slice(0, limit).forEach((l) => {
        const row = el("li", "loc");
        // Адрес — уличной табличкой, как записан в таблице: не переводим и не транслитерируем
        const where = el("span", "where");
        where.append(el("span", "plate", l.address));
        if (state.city === "all" && l.city) where.append(el("span", "city", cityLabel(l.city)));
        if (l.lat == null && !b.places_list) where.append(el("span", "nopin", t().noPin));
        row.append(where);
        const a = !b.places_list && link(l.route, `${t().route} ↗`);
        if (a) { a.addEventListener("click", () => track(`route/${b.key}`, b.name)); row.append(a); }
        ul.append(row);
      });
      if (locs.length > limit) {
        const more = el("button", "more", t().more(locs.length - limit)); more.type = "button";
        more.addEventListener("click", (e) => { e.stopPropagation(); state.expanded.add(b.id); render(); });
        const row = el("li", "loc"); row.append(more); ul.append(row);
      }
      if (b.places_list) {
        const row = el("li", "loc"); const a = link(b.places_list, `${t().placesList} ↗`, "places");
        if (a) { row.append(a); ul.append(row); }
      }
      li.append(ul);
    }

    const links = el("div", "links");
    const L_ = b.links;
    // Ссылки — значками без подписи; название в подсказке и для экранных читалок
    [["instagram", "Instagram"], ["telegram", "Telegram"], ["threads", "Threads"], ["site", t().site]].forEach(([k, label]) => {
      const a = link(L_[k], null, "lnk");
      if (!a) return;
      a.addEventListener("click", () => track(`contact/${k}/${b.key}`, b.name));
      a.title = label; a.setAttribute("aria-label", `${label}: ${b.name}`);
      a.append(glyph(k));
      links.append(a);
    });
    const sh = el("button", "share", t().share); sh.type = "button";
    sh.addEventListener("click", (e) => { e.stopPropagation(); share(b); });
    links.append(sh);
    li.append(links);

    li.addEventListener("click", (e) => { if (!e.target.closest("a, button")) select(b.id); });
    li.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === li) select(b.id); });
    li.addEventListener("mouseenter", () => pinEls(b.id).forEach((p) => p.classList.add("is-hover")));
    li.addEventListener("mouseleave", () => pinEls(b.id).forEach((p) => p.classList.remove("is-hover")));
    return li;
  }

  // --- поделиться: страница b/<key>/ даёт превью в мессенджерах и открывает этот бизнес ----
  function shareUrl(b) {
    const base = location.href.split(/[?#]/)[0].replace(/[^/]*$/, "");
    return `${base}b/${encodeURIComponent(b.key)}/`;
  }
  let toastTimer;
  function toast(text, ms = 2200) {
    const n = $("#toast");
    n.textContent = text;
    n.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => n.classList.remove("show"), ms);
  }
  async function share(b) {
    const url = shareUrl(b);
    track(`share/${b.key}`, b.name);
    const touch = window.matchMedia("(pointer: coarse)").matches;
    if (touch && navigator.share) {
      try { await navigator.share({ title: b.name, text: `${b.name}: ${b.description[state.lang]}`, url }); return; }
      catch (e) { if (e && e.name === "AbortError") return; }
    }
    try { await navigator.clipboard.writeText(url); toast(t().copied); }
    catch (e) { toast(`${t().copyThis} ${url}`, 8000); }
  }

  function visible() {
    const list = D.businesses.filter((b) => inCity(b, state.city) && inCat(b, state.cat) && inQuery(b));
    list.forEach((b) => { b._dist = distOf(b); });
    // Infinity − Infinity = NaN → falsy, значит без геолокации решает случайный ранг.
    return list.sort((a, b) => (a._dist - b._dist) || (rank(a.id) - rank(b.id)));
  }

  function render() {
    const vis = visible();
    $("#order").textContent = vis.length > 1 ? (state.me ? t().sorted : t().random) : "";
    const ol = $("#list"); ol.textContent = "";
    if (!vis.length) {
      const box = el("li", "empty"); box.append(el("div", null, t().empty));
      const r = el("button", null, t().reset); r.type = "button";
      r.addEventListener("click", () => { state.city = "all"; state.cat = "all"; state.q = ""; $("#q").value = ""; update({ fit: true }); });
      box.append(r); ol.append(box);
    } else {
      vis.forEach((b) => ol.append(card(b)));
    }
    return vis;
  }

  function renderMap(vis, fit) {
    layer.clearLayers();
    const pts = [];
    for (const b of vis) for (const x of markers.get(b.id) || []) {
      if (state.city !== "all" && x.loc.city !== state.city) continue;
      layer.addLayer(x.marker); pts.push(x.marker.getLatLng());
    }
    if (state.active) pinEls(state.active).forEach((p) => p.classList.add("is-active"));
    if (!fit || !pts.length) return;
    if (state.me) {
      const near = pts.slice().sort((a, b) => haversine(state.me, [a.lat, a.lng]) - haversine(state.me, [b.lat, b.lng])).slice(0, 4);
      map.flyToBounds(L.latLngBounds([L.latLng(state.me), ...near]).pad(0.2), { maxZoom: 15, duration: 0.6 });
    } else {
      map.fitBounds(L.latLngBounds(pts).pad(0.15), { maxZoom: 15 });
    }
  }

  function update({ fit = false } = {}) {
    if (fit) { setParam("b", null); state.active = null; map.closePopup(); } // сменили фильтр — ссылка больше не про один бизнес
    renderFilters();
    const vis = render();
    renderMap(vis, fit);
  }

  // --- события -----------------------------------------------------------------
  let qTimer;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.q = e.target.value; update({ fit: true }); }, 120);
  });
  document.querySelectorAll(".lang button").forEach((bt) => bt.addEventListener("click", () => {
    state.lang = bt.dataset.lang; store.set("komsije-lang", state.lang); track(`lang/${state.lang}`);
    map.closePopup(); renderStatic(); update();
  }));
  $("#near").addEventListener("click", () => {
    const status = $("#status");
    if (state.me) {
      state.me = null; status.textContent = "";
      if (meMarker) { map.removeLayer(meMarker); meMarker = null; }
      update({ fit: true }); return;
    }
    if (!navigator.geolocation) { status.textContent = t().geoFail; return; }
    status.textContent = t().locating;
    navigator.geolocation.getCurrentPosition((pos) => {
      state.me = [pos.coords.latitude, pos.coords.longitude]; // координаты остаются в браузере, в счётчик — только факт
      track("near");
      status.textContent = "";
      if (meMarker) map.removeLayer(meMarker);
      meMarker = L.marker(state.me, { icon: L.divIcon({ className: "pin-wrap", html: el("span", "me"), iconSize: [16, 16], iconAnchor: [8, 8] }), interactive: false, zIndexOffset: 1000 }).addTo(map);
      update({ fit: true });
    }, () => { status.textContent = t().geoFail; }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  });

  renderStatic();
  update({ fit: true });
  if (deep) select(deep.id, { scroll: true, via: "link" });
})();
