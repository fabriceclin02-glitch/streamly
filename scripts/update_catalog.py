#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STREAMLY — mise à jour automatique du catalogue
================================================
Lance :   python scripts/update_catalog.py
(sur GitHub, ça tourne tout seul chaque jour : .github/workflows/update-catalog.yml)

Ce que fait le script :
 1. Films COMPLETS lisibles sur STREAMLY (100 % légaux) :
    - Internet Archive : films du domaine public / sous licence Creative Commons
    - Wikimedia Commons (via Wikidata) : films libres avec fichier vidéo
 2. Rangée « Avant-première : l'IA au cinéma » (films protégés) :
    fiche, jaquette, bande-annonce officielle et plateformes légales (TMDB).
 3. Jaquettes : jamais copiées sur le site. On enregistre seulement l'adresse
    de l'image sur Internet (archive.org, image.tmdb.org, Wikimedia).

Option : clé gratuite TMDB (https://www.themoviedb.org/settings/api)
 - en local :   TMDB_API_KEY=xxxx python scripts/update_catalog.py
 - sur GitHub : Settings › Secrets and variables › Actions › TMDB_API_KEY
Sans clé, tout fonctionne quand même (visuels générés à la place des jaquettes TMDB).

Aucune dépendance : uniquement la bibliothèque standard de Python 3.8+.
"""
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_seeds import AI_SEEDS  # noqa: E402

CATALOG_JSON = os.path.join(ROOT, "catalog.json")
CATALOG_JS = os.path.join(ROOT, "catalog.js")

MAX_ARCHIVE = int(os.environ.get("MAX_ARCHIVE", "400"))      # films archive.org
MAX_COMMONS = int(os.environ.get("MAX_COMMONS", "300"))      # films Wikimedia Commons
MAX_PREMIERES = int(os.environ.get("MAX_PREMIERES", "80"))   # rangée IA
TMDB_POSTERS_FOR_FREE = int(os.environ.get("TMDB_POSTERS_FOR_FREE", "250"))
TMDB_KEY = os.environ.get("TMDB_API_KEY", "").strip()
UA = "STREAMLY-catalog-bot/1.0 (https://github.com/fabriceclin02-glitch/streamly)"
TODAY = date.today().isoformat()
TMDB_IMG = "https://image.tmdb.org/t/p/"

# --------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------
def log(*a):
    print(*a, flush=True)


def get_json(url, headers=None, data=None, tries=3):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h, data=data)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # réseau, quota…
            last = e
            time.sleep(2 * (i + 1))
    raise last


def slug(s, n=48):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:n] or "x"


def norm(s):
    return slug(s, 200).replace("-", "")


def clean_text(s, n=420):
    if isinstance(s, list):
        s = " ".join(map(str, s))
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return s


def clean_title(t):
    t = clean_text(t, 120)
    t = re.sub(r"\s*[\(\[][^\)\]]*(18|19|20)\d\d[^\)\]]*[\)\]]\s*$", "", t)
    t = re.sub(r"\s*[-_|]\s*(full movie|full film|hd|1080p|720p)\s*$", "", t, flags=re.I)
    return t.strip(" -_") or "Sans titre"


def parse_year(*vals):
    for v in vals:
        m = re.search(r"(18|19|20)\d\d", str(v or ""))
        if m:
            return int(m.group(0))
    return None


def parse_minutes(v):
    v = str(v or "").strip()
    if not v:
        return None
    m = re.match(r"^(\d+):(\d\d):(\d\d)", v)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"^(\d+):(\d\d)$", v)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(min|m\b|minutes)", v, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*h\s*(\d+)?", v, re.I)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    return None


GENRE_WORDS = [
    (("science fiction", "sci-fi", "scifi", "sci fi", "space", "robot", "alien"), "Science-fiction"),
    (("horror", "horreur", "monster", "vampire", "zombie"), "Horreur"),
    (("comedy", "comédie", "comedie", "slapstick"), "Comédie"),
    (("noir", "crime", "gangster", "detective", "mystery", "policier"), "Policier"),
    (("western",), "Western"),
    (("thriller", "suspense"), "Thriller"),
    (("animation", "cartoon", "animated", "anime"), "Animation"),
    (("documentary", "documentaire"), "Documentaire"),
    (("silent", "muet"), "Muet"),
    (("romance", "romantic", "love"), "Romance"),
    (("war", "guerre", "history", "historical", "historique"), "Historique"),
    (("adventure", "aventure"), "Aventure"),
    (("action", "martial"), "Action"),
    (("fantasy", "fantastique", "fairy"), "Fantastique"),
    (("family", "children", "famille", "kids"), "Famille"),
    (("drama", "drame"), "Drame"),
]
COLLECTION_GENRES = {
    "scifi_horror": ["Science-fiction", "Horreur"],
    "film_noir": ["Policier", "Thriller"],
    "comedy_films": ["Comédie"],
    "silent_films": ["Muet"],
    "feature_films": ["Drame"],
}
ART_FOR = {
    "Science-fiction": "scifi", "Horreur": "horror", "Comédie": "family", "Policier": "noir",
    "Western": "western", "Thriller": "noir", "Animation": "meadow", "Documentaire": "lumiere",
    "Muet": "expr", "Romance": "drama", "Historique": "epic", "Aventure": "sea",
    "Action": "epic", "Fantastique": "castle", "Famille": "family", "Drame": "drama",
}
PAL = {
    "scifi": ["#3d8aff", "#060a1a", "#ff3d8a"], "horror": ["#2a2f2a", "#050605", "#c9c3a6"],
    "family": ["#ff7a5c", "#2a0f3d", "#fff35c"], "noir": ["#2a2a33", "#050508", "#e8e8f0"],
    "western": ["#c96a2a", "#2a1206", "#ffcf5c"], "meadow": ["#7ed957", "#2a7a3d", "#fff35c"],
    "lumiere": ["#c9b28a", "#2a2214", "#fff6e0"], "expr": ["#5a3d2a", "#140b06", "#e8c27a"],
    "drama": ["#5c2a3d", "#12060c", "#ffb38a"], "epic": ["#8a3d1a", "#1a0a04", "#ffb35c"],
    "sea": ["#1a5c8a", "#03111f", "#7ae0ff"], "castle": ["#2a2a5c", "#05050f", "#c2c2ff"],
    "machine": ["#5c5c6b", "#0a0a10", "#5cf0ff"],
}


def genres_from(texts, collections=()):
    blob = " ".join(str(t) for t in texts if t).lower()
    out = []
    for words, g in GENRE_WORDS:
        if any(w in blob for w in words) and g not in out:
            out.append(g)
    if not out:
        for c in collections:
            out += [g for g in COLLECTION_GENRES.get(str(c).lower(), []) if g not in out]
    return out[:4] or ["Drame"]


def style_for(genres, default="drama"):
    art = next((ART_FOR[g] for g in genres if g in ART_FOR), default)
    return art, PAL.get(art, PAL["drama"])


# --------------------------------------------------------------------------
# 1a. Internet Archive — films complets libres
# --------------------------------------------------------------------------
LEGAL_LICENSE = re.compile(r"publicdomain|creativecommons", re.I)
BLOCKED_COLLECTIONS = {"stream_only", "inlibrary", "lendinglibrary", "printdisabled", "tvarchive"}


def fetch_archive():
    q = ("(collection:(feature_films OR SciFi_Horror OR Film_Noir OR comedy_films OR silent_films)) "
         "AND mediatype:movies AND -collection:(stream_only OR inlibrary OR tvarchive)")
    fields = ["identifier", "title", "year", "date", "description", "subject", "creator",
              "runtime", "licenseurl", "collection", "downloads"]
    out, page, seen = [], 1, set()
    while len(out) < MAX_ARCHIVE and page <= 12:
        params = [("q", q), ("rows", "200"), ("page", str(page)), ("output", "json"),
                  ("sort[]", "downloads desc")] + [("fl[]", f) for f in fields]
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params)
        docs = get_json(url).get("response", {}).get("docs", [])
        if not docs:
            break
        for d in docs:
            ident = d.get("identifier")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            cols = d.get("collection") or []
            cols = cols if isinstance(cols, list) else [cols]
            if BLOCKED_COLLECTIONS & {str(c).lower() for c in cols}:
                continue
            year = parse_year(d.get("year"), d.get("date"), d.get("title"))
            lic_url = str(d.get("licenseurl") or "")
            if LEGAL_LICENSE.search(lic_url):
                lic = "Creative Commons (" + lic_url.rstrip("/").split("/licenses/")[-1] + ")" \
                    if "creativecommons" in lic_url and "publicdomain" not in lic_url else "Domaine public"
            elif year and year <= 1929:
                lic = "Domaine public (œuvre de " + str(year) + ")"
            else:
                continue  # statut des droits incertain : on n'affiche pas
            subj = d.get("subject") or []
            g = genres_from([subj, d.get("title")], cols)
            if year and year < 1930 and "Muet" not in g:
                g.append("Muet")
            art, pal = style_for(g)
            mins = parse_minutes(d.get("runtime"))
            if mins is not None and mins < 3:
                continue
            out.append({
                "id": "ar-" + slug(ident, 40), "type": "film", "auto": "archive",
                "title": clean_title(d.get("title") or ident), "year": year or 1930,
                "by": clean_text(d.get("creator"), 60) or "Inconnu",
                "genres": g, "age": "12+" if ("Horreur" in g or "Policier" in g) else "Tous publics",
                "min": mins or 80, "art": art, "pal": pal, "tagline": "",
                "desc": clean_text(d.get("description")) or "Film libre de droits, version intégrale.",
                "src": {"archive": ident},
                "poster": "https://archive.org/services/img/" + urllib.parse.quote(ident),
                "lic": lic, "dl": int(d.get("downloads") or 0),
            })
            if len(out) >= MAX_ARCHIVE:
                break
        page += 1
    log(f"  archive.org : {len(out)} films")
    return out


# --------------------------------------------------------------------------
# 1b. Wikimedia Commons (via Wikidata) — films avec fichier vidéo libre
# --------------------------------------------------------------------------
SPARQL = "https://query.wikidata.org/sparql"


def sparql(q):
    url = SPARQL + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    return get_json(url, {"Accept": "application/sparql-results+json"})["results"]["bindings"]


def v(row, k):
    return row.get(k, {}).get("value")


def commons_file_url(u):
    # http://commons.wikimedia.org/wiki/Special:FilePath/Foo.webm -> https
    return (u or "").replace("http://", "https://")


def fetch_commons():
    q = """
SELECT ?film ?filmLabel ?video ?date ?dirLabel ?desc ?dur ?poster (GROUP_CONCAT(DISTINCT ?gl; separator="|") AS ?genres) WHERE {
  VALUES ?type { wd:Q11424 wd:Q202866 wd:Q24862 wd:Q506240 wd:Q93204 }
  ?film wdt:P31 ?type ; wdt:P10 ?video .
  OPTIONAL { ?film wdt:P577 ?date }
  OPTIONAL { ?film wdt:P57 ?dir }
  OPTIONAL { ?film wdt:P2047 ?dur }
  OPTIONAL { ?film wdt:P3383 ?poster }
  OPTIONAL { ?film schema:description ?desc FILTER(LANG(?desc) = "fr") }
  OPTIONAL { ?film wdt:P136 ?g . ?g rdfs:label ?gl FILTER(LANG(?gl) IN ("fr","en")) }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
}
GROUP BY ?film ?filmLabel ?video ?date ?dirLabel ?desc ?dur ?poster
LIMIT 3000"""
    rows = sparql(q)
    out, seen = [], set()
    for r in rows:
        qid = v(r, "film").rsplit("/", 1)[-1]
        video = commons_file_url(v(r, "video"))
        name = urllib.parse.unquote(video.rsplit("/", 1)[-1]).lower()
        if qid in seen or not video or re.search(r"trailer|bande[-_ ]annonce|teaser|excerpt|extrait|clip", name):
            continue
        dur = v(r, "dur")
        try:
            mins = round(float(dur)) if dur else None
        except ValueError:
            mins = None
        if mins is not None and mins < 3:
            continue
        label = v(r, "filmLabel") or qid
        if re.fullmatch(r"Q\d+", label):
            continue
        seen.add(qid)
        g = genres_from([v(r, "genres"), v(r, "desc")])
        year = parse_year(v(r, "date"))
        if year and year < 1930 and "Muet" not in g:
            g.append("Muet")
        art, pal = style_for(g)
        item = {
            "id": "wd-" + qid.lower(), "type": "film", "auto": "commons",
            "title": clean_title(label), "year": year or 1930, "by": v(r, "dirLabel") or "Inconnu",
            "genres": g, "age": "Tous publics", "min": mins or 60, "art": art, "pal": pal, "tagline": "",
            "desc": clean_text(v(r, "desc")) or "Film libre, diffusé depuis Wikimedia Commons.",
            "src": {"mp4": video}, "lic": "Licence libre (Wikimedia Commons)",
            "wikidata": qid,
        }
        if v(r, "poster"):
            item["poster"] = commons_file_url(v(r, "poster")) + "?width=400"
        out.append(item)
        if len(out) >= MAX_COMMONS:
            break
    log(f"  Wikimedia Commons : {len(out)} films")
    return out


# --------------------------------------------------------------------------
# 2. Avant-première IA — Wikidata (sans clé) + TMDB (avec clé)
# --------------------------------------------------------------------------
def fetch_ai_wikidata():
    q = """
SELECT DISTINCT ?film ?filmLabel ?orig ?date ?dirLabel ?desc ?poster WHERE {
  VALUES ?subj { wd:Q11660 wd:Q11012 }
  ?film wdt:P31 wd:Q11424 ; wdt:P921 ?subj ; wdt:P577 ?date ; wdt:P345 ?imdb ; wikibase:sitelinks ?sl .
  FILTER(YEAR(?date) >= 1960 && ?sl >= 12)
  OPTIONAL { ?film wdt:P1476 ?orig }
  OPTIONAL { ?film wdt:P57 ?dir }
  OPTIONAL { ?film wdt:P3383 ?poster }
  OPTIONAL { ?film schema:description ?desc FILTER(LANG(?desc) = "fr") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
}
ORDER BY DESC(?date) LIMIT 150"""
    out = []
    for r in sparql(q):
        label = v(r, "filmLabel")
        if not label or re.fullmatch(r"Q\d+", label):
            continue
        out.append({"title": label, "orig": v(r, "orig") or label, "year": parse_year(v(r, "date")),
                    "by": v(r, "dirLabel") or "", "desc": clean_text(v(r, "desc")),
                    "poster": commons_file_url(v(r, "poster")) + "?width=400" if v(r, "poster") else None})
    log(f"  Wikidata (IA) : {len(out)} films")
    return out


def tmdb(path, **params):
    headers = {}
    if TMDB_KEY.startswith("eyJ"):  # jeton « lecture » v4
        headers["Authorization"] = "Bearer " + TMDB_KEY
    else:
        params["api_key"] = TMDB_KEY
    url = "https://api.themoviedb.org/3" + path + "?" + urllib.parse.urlencode(params)
    return get_json(url, headers)


_GENRES = {}


def tmdb_genres():
    if not _GENRES:
        for g in tmdb("/genre/movie/list", language="fr-FR").get("genres", []):
            _GENRES[g["id"]] = g["name"]
    return _GENRES


def tmdb_search(title, year):
    for y in (year, None):
        p = {"query": title, "language": "fr-FR", "include_adult": "false"}
        if y:
            p["year"] = y
        res = tmdb("/search/movie", **p).get("results", [])
        if res:
            return res[0]
    return None


def tmdb_details(mid):
    return tmdb(f"/movie/{mid}", language="fr-FR",
                append_to_response="videos,watch/providers,release_dates,credits",
                include_video_language="fr,en,null")


def pick_trailer(videos):
    vids = [x for x in (videos or {}).get("results", []) if x.get("site") == "YouTube"]
    rank = lambda x: (x.get("type") != "Trailer", not x.get("official", False), x.get("iso_639_1") != "fr")
    vids.sort(key=rank)
    return vids[0]["key"] if vids else None


def providers_fr(wp):
    fr = ((wp or {}).get("results") or {}).get("FR") or {}
    kinds = [("free", "Gratuit"), ("ads", "Gratuit avec pub"), ("flatrate", "Abonnement"),
             ("rent", "Location"), ("buy", "Achat")]
    out, seen = [], set()
    for k, label in kinds:
        for p in fr.get(k, []) or []:
            if p["provider_name"] in seen:
                continue
            seen.add(p["provider_name"])
            out.append({"name": p["provider_name"], "type": label,
                        "logo": TMDB_IMG + "w92" + p["logo_path"] if p.get("logo_path") else None})
    return fr.get("link"), out


def premiere_entry(base, det=None):
    """Construit la fiche d'un film IA (protégé : fiche + bande-annonce + où regarder)."""
    title = base["title"]
    year = base.get("year")
    item = {
        "id": "ia-" + slug(f'{base.get("orig") or title}-{year}', 50), "type": "film", "kind": "info",
        "auto": "premiere", "title": title, "orig": base.get("orig") or title, "year": year or 2000,
        "by": base.get("by") or "", "genres": ["Science-fiction", "IA & robots"], "age": "12+",
        "min": base.get("min") or 110, "art": "machine", "pal": PAL["machine"],
        "tagline": "", "desc": base.get("desc") or "", "lic": "Fiche, bande-annonce et liens légaux",
        "watch": {"link": "https://www.justwatch.com/fr/recherche?q=" + urllib.parse.quote(title), "providers": []},
    }
    if base.get("poster"):
        item["poster"] = base["poster"]
    if det:
        item["tmdb"] = det["id"]
        if det.get("title"):
            item["title"] = det["title"]
        if det.get("overview"):
            item["desc"] = clean_text(det["overview"], 600)
        if det.get("tagline"):
            item["tagline"] = det["tagline"]
        if det.get("runtime"):
            item["min"] = det["runtime"]
        rd = det.get("release_date") or ""
        if rd:
            item["year"] = int(rd[:4])
            item["release"] = rd
            if rd > TODAY:
                item["upcoming"] = 1
        if det.get("poster_path"):
            item["poster"] = TMDB_IMG + "w500" + det["poster_path"]
        if det.get("backdrop_path"):
            item["backdrop"] = TMDB_IMG + "w1280" + det["backdrop_path"]
        gs = [g["name"] for g in det.get("genres", [])][:3]
        gs = ["Science-fiction" if g.lower() == "science-fiction" else g for g in gs]
        item["genres"] = list(dict.fromkeys(gs + ["Science-fiction", "IA & robots"]))
        crew = (det.get("credits") or {}).get("crew", [])
        dirs = [c["name"] for c in crew if c.get("job") == "Director"]
        if dirs:
            item["by"] = ", ".join(dirs[:2])
        cast = [c["name"] for c in (det.get("credits") or {}).get("cast", [])[:4]]
        if cast:
            item["cast"] = cast
        trailer = pick_trailer(det.get("videos"))
        if trailer:
            item["trailer"] = trailer
        link, provs = providers_fr(det.get("watch/providers"))
        if link:
            item["watch"]["link"] = link
        item["watch"]["providers"] = provs
        vote = det.get("vote_average")
        if vote:
            item["score"] = round(vote, 1)
    return item


def fetch_premieres():
    bases = [{"title": t, "orig": o, "year": y, "by": b, "desc": d} for t, o, y, b, d in AI_SEEDS]
    try:
        bases += fetch_ai_wikidata()
    except Exception as e:
        log("  ! Wikidata IA indisponible :", e)

    tmdb_extra = []
    if TMDB_KEY:
        try:
            kw_ids = []
            for kw in ("artificial intelligence", "robot", "android", "cyborg"):
                res = tmdb("/search/keyword", query=kw).get("results", [])
                exact = [k for k in res if k["name"].lower() == kw]
                if exact:
                    kw_ids.append(str(exact[0]["id"]))
            if kw_ids:
                common = {"with_keywords": "|".join(kw_ids), "language": "fr-FR", "region": "FR",
                          "with_genres": "878"}
                for p in (dict(sort_by="popularity.desc", page=1), dict(sort_by="popularity.desc", page=2),
                          dict(sort_by="primary_release_date.desc", **{"primary_release_date.gte": TODAY}),
                          dict(sort_by="primary_release_date.desc", **{"primary_release_date.lte": TODAY},
                               **{"vote_count.gte": 50})):
                    for m in tmdb("/discover/movie", **common, **p).get("results", []):
                        tmdb_extra.append(m["id"])
        except Exception as e:
            log("  ! TMDB discover indisponible :", e)

    items, seen_keys, seen_tmdb = [], set(), set()

    def add(base, det=None):
        it = premiere_entry(base, det)
        key = (norm(it.get("orig") or it["title"]), it["year"])
        tkey = norm(it["title"])
        if key in seen_keys or tkey in seen_keys or (det and det["id"] in seen_tmdb):
            return
        seen_keys.add(key)
        seen_keys.add(tkey)
        if det:
            seen_tmdb.add(det["id"])
        items.append(it)

    for b in bases:
        if len(items) >= MAX_PREMIERES:
            break
        det = None
        if TMDB_KEY:
            try:
                hit = tmdb_search(b.get("orig") or b["title"], b.get("year"))
                if hit and hit["id"] not in seen_tmdb:
                    det = tmdb_details(hit["id"])
            except Exception as e:
                log("  ! TMDB", b["title"], e)
        add(b, det)

    for mid in tmdb_extra:
        if len(items) >= MAX_PREMIERES + 40 or mid in seen_tmdb:
            continue
        try:
            det = tmdb_details(mid)
            add({"title": det.get("title"), "orig": det.get("original_title"),
                 "year": parse_year(det.get("release_date"))}, det)
        except Exception as e:
            log("  ! TMDB", mid, e)

    # Prochaines sorties d'abord, puis les plus récents
    items.sort(key=lambda x: (not x.get("upcoming"), -(x.get("year") or 0)))
    log(f"  Avant-première IA : {len(items)} films (TMDB {'activé' if TMDB_KEY else 'non configuré'})")
    return items


# --------------------------------------------------------------------------
# 3. Jaquettes TMDB pour les films libres (optionnel)
# --------------------------------------------------------------------------
def enrich_free_posters(films):
    if not TMDB_KEY:
        return
    n = 0
    for f in sorted(films, key=lambda x: -x.get("dl", 0))[:TMDB_POSTERS_FOR_FREE]:
        try:
            hit = tmdb_search(f["title"], f.get("year"))
            if hit and hit.get("poster_path") and abs((parse_year(hit.get("release_date")) or 0) - (f.get("year") or 0)) <= 1:
                f["poster"] = TMDB_IMG + "w500" + hit["poster_path"]
                if hit.get("backdrop_path"):
                    f["backdrop"] = TMDB_IMG + "w1280" + hit["backdrop_path"]
                if hit.get("overview") and len(f.get("desc", "")) < 60:
                    f["desc"] = clean_text(hit["overview"])
                n += 1
        except Exception:
            pass
    log(f"  Jaquettes TMDB ajoutées aux films libres : {n}")


# --------------------------------------------------------------------------
# Assemblage
# --------------------------------------------------------------------------
def main():
    with open(CATALOG_JSON, encoding="utf-8") as f:
        data = json.load(f)
    old = data.get("titles", [])
    curated = [t for t in old if not t.get("auto")]
    prev = {}
    for t in old + data.get("premieres", []):
        if t.get("auto"):
            prev.setdefault(t["auto"], []).append(t)

    curated_keys = {(norm(t["title"]), t.get("year")) for t in curated}
    curated_archive = {t.get("src", {}).get("archive") for t in curated} - {None}

    log("Mise à jour du catalogue STREAMLY…")
    results = {}
    for name, fn in (("archive", fetch_archive), ("commons", fetch_commons), ("premiere", fetch_premieres)):
        try:
            results[name] = fn()
        except Exception as e:
            log(f"  ! {name} indisponible ({e}) — on garde la version précédente")
            results[name] = prev.get(name, [])

    free, keys = [], set(curated_keys)
    for t in results["archive"] + results["commons"]:
        k = (norm(t["title"]), t.get("year"))
        if k in keys or t.get("src", {}).get("archive") in curated_archive:
            continue
        keys.add(k)
        free.append(t)
    enrich_free_posters(free)

    # « Nouveauté » = films libres apparus depuis la dernière mise à jour
    prev_ids = {t["id"] for t in old}
    for t in free:
        if t["id"] not in prev_ids and prev_ids:
            t["isNew"] = 1
        t.pop("dl", None)

    data["titles"] = curated + free
    data["premieres"] = results["premiere"]
    data["updated"] = TODAY
    data["stats"] = {"curated": len(curated), "archive": sum(t["auto"] == "archive" for t in free),
                     "commons": sum(t["auto"] == "commons" for t in free), "premieres": len(data["premieres"]),
                     "tmdb": bool(TMDB_KEY)}

    with open(CATALOG_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    with open(CATALOG_JS, "w", encoding="utf-8") as f:
        f.write("/* Généré automatiquement par scripts/update_catalog.py — ne pas modifier à la main */\n")
        f.write("window.STREAMLY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    log(f"OK : {len(data['titles'])} films lisibles, {len(data['premieres'])} fiches avant-première.")


if __name__ == "__main__":
    main()
