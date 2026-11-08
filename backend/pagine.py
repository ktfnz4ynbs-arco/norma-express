"""
Pagine server-rendered (SEO) — fase 1 di docs/design-pagine-articolo.md.

  GET /{atto}/art-{numero}     pagina articolo: testo Normattiva gia' nell'HTML
  GET /sitemap.xml             sitemap index
  GET /sitemaps/home.xml       la home
  GET /sitemaps/{atto}.xml     articoli dell'atto (dall'indice Normattiva, in cache)

Stati: 200 trovato · 301 URL non canonico · 404 inesistente · 503 Normattiva
irraggiungibile senza copia in cache (Google ritenta invece di de-indicizzare).

Nell'HTML indicizzato c'e' SOLO il testo dell'articolo (atto ufficiale, art. 5
L. 633/1941). Interpretazione e giurisprudenza le carica il browser, come nella SPA.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

import cache
import catalogo
import normattiva

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
_env = Environment(loader=FileSystemLoader(str(FRONTEND)),
                   autoescape=select_autoescape(["html"]))
_TPL_HASH = hashlib.sha256((FRONTEND / "index.html").read_bytes()).hexdigest()[:12] \
    if (FRONTEND / "index.html").exists() else ""

router = APIRouter()
CACHE_HDR = "public, max-age=3600, stale-while-revalidate=86400"


# ------------------------------------------------------------------ base URL
def base_url(request: Request) -> str:
    """URL pubblico assoluto, senza barra finale.

    PUBLIC_URL (es. https://norma-express.up.railway.app) vince sempre: e' la forma
    canonica. Altrimenti si ricostruisce dagli header del proxy (Railway termina TLS e
    passa X-Forwarded-Proto/Host), con fallback alla richiesta.
    """
    env = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
    if env:
        return env
    h = request.headers
    proto = h.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = h.get("x-forwarded-host") or h.get("host") or request.url.netloc
    return f"{proto}://{host.split(',')[0].strip()}"


def render(request: Request, status: int = 200, robots: str = "index, follow",
           canonical_path: str = "/", **ctx) -> HTMLResponse:
    b = base_url(request)
    html = _env.get_template("index.html").render(
        BASE_URL=b, ROBOTS=robots, CANONICAL=b + canonical_path, **ctx)
    return HTMLResponse(html, status_code=status)


def render_home(request: Request) -> HTMLResponse:
    # Le pagine di ricerca (?q=) e l'incorporamento (?embed=1) non vanno indicizzate:
    # sono risultati dinamici, duplicati della home per Google.
    p = request.query_params
    robots = "noindex, follow" if (p.get("q") or p.get("embed")) else "index, follow"
    return render(request, robots=robots)


def _errore(request: Request, status: int, msg: str) -> HTMLResponse:
    r = render(request, status=status, robots="noindex, follow", errore=msg)
    if status == 503:
        r.headers["Retry-After"] = "3600"
    return r


# ------------------------------------------------------------ dati (in cache)
def _fetch_articolo(ref):
    def f():
        a = normattiva.fetch_article(ref)
        if a.ok and a.text:
            return cache.OK, asdict(a)
        return (cache.UNAVAILABLE if a.network_error else cache.NOTFOUND), None
    return f


def _fetch_indice(atto: catalogo.Atto):
    def f():
        idx = normattiva.fetch_index(atto.ref)
        if not idx.ok:
            return (cache.UNAVAILABLE if idx.network_error else cache.NOTFOUND), None
        nums, seen = [], set()
        for g in idx.groups:
            for voce in g.get("articles", []):
                n = catalogo.norm_articolo(voce.get("num", ""))
                if n and n not in seen:
                    seen.add(n)
                    nums.append(n)
        return cache.OK, {"nums": nums, "act_title": idx.act_title}
    return f


# --------------------------------------------------------- testi della pagina
_LAT = "|".join(catalogo.LATINI)
_HEAD_ART = re.compile(r"^\s*art(?:icolo)?\.?\s*\d+(?:[\s-]*(?:" + _LAT + r"))?\b\s*[.\-—–:]*\s*",
                       re.I)


_TESTO_RUB = re.compile(r"^\s*art(?:icolo)?\.?\s*\d+(?:[\s-]*(?:" + _LAT + r"))?\s*\.?\s*"
                        r"\(([^()]{3,160})\)", re.I)


def rubrica(heading: str, text: str = "") -> str:
    """'Art. 2043 — (Risarcimento per fatto illecito)' -> 'Risarcimento per fatto illecito'.

    Per molti articoli Normattiva mette in intestazione solo "Art. 2043" e la rubrica
    sta in apertura del testo: "Art. 2043. (Risarcimento per fatto illecito). Qualunque..."
    In quel caso si prende da li', ma SOLO se e' tra parentesi (forma certa)."""
    r = re.sub(r"\s+", " ", _HEAD_ART.sub("", heading or "")).strip(" ()[]—–-.:")
    if r:
        return r
    m = _TESTO_RUB.match(text or "")
    return re.sub(r"\s+", " ", m.group(1)).strip(" .") if m else ""


def _taglia(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def _data_it(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m/%Y")


def contesto_pagina(atto: catalogo.Atto, art: str, a: dict, url: str,
                    fetched_at: float) -> dict:
    rub = rubrica(a.get("article_heading", ""), a.get("text", ""))
    nome_art = f"Art. {art} {atto.abbr}"
    h1 = f"Art. {art} {atto.nome}" + (f" — {rub}" if rub else "")
    title = nome_art + (f" — {_taglia(rub, 58 - len(nome_art))}" if rub else "")
    meta = []
    if a.get("act_title"):
        meta.append(("Atto", a["act_title"]))
    if a.get("in_force_from"):
        meta.append(("In vigore dal", a["in_force_from"]))
    if (a.get("versions") or 0) > 1:
        meta.append(("Versioni dell'articolo", f"{a['versions']} (vigente: ultima)"))
    query = atto.query(art)
    ref = atto.ref_articolo(art)
    jsonld = {
        "@context": "https://schema.org", "@type": "Legislation",
        "name": h1, "url": url, "inLanguage": "it-IT",
        "legislationIdentifier": ref.urn(),
        "legislationJurisdiction": "IT",
        "legislationLegalForce": "https://schema.org/" +
                                 ("NotInForce" if a.get("abrogato") else "InForce"),
        "isPartOf": {"@type": "Legislation", "name": atto.nome},
        "sameAs": a.get("permalink") or None,
    }
    article = {k: a.get(k) for k in (
        "ok", "query_label", "act_title", "article_heading", "text", "in_force_from",
        "permalink", "updates", "error", "abrogato", "versions", "vigenza")}
    return {
        "title": f"{title} | Norma Express",
        "title_og": title,
        "description": _taglia(("Articolo abrogato. " if a.get("abrogato") else "") +
                               (a.get("text") or ""), 155),
        "h1": h1, "atto_nome": atto.nome, "articolo": art, "query": query,
        "a": a, "meta": meta, "data_estrazione": _data_it(fetched_at),
        "jsonld": {k: v for k, v in jsonld.items() if v is not None},
        "iniziale": {"payload": {"query": query},
                     "art": {"ok": True, "mode": "article", "label": nome_art,
                             "reference_found": True, "article": article}},
    }


# --------------------------------------------------------------------- route
@router.get("/{atto_slug}/art-{num}", response_class=HTMLResponse, include_in_schema=False)
def pagina_articolo(atto_slug: str, num: str, request: Request):
    slug = catalogo.canonico(atto_slug)
    art = catalogo.norm_articolo(num)
    if not slug or not art:
        return _errore(request, 404, "Pagina non trovata. Cerca l'articolo qui sopra.")
    path = catalogo.path_articolo(slug, art)
    if path != request.url.path:
        return RedirectResponse(path, status_code=301)

    atto = catalogo.atto_da_slug(slug)
    hit = cache.store().get(f"art:{slug}:{art}", f"art:{slug}", art,
                            _fetch_articolo(atto.ref_articolo(art)))
    if hit["status"] == cache.NOTFOUND:
        return _errore(request, 404, f"L'articolo {art} non risulta in {atto.nome} su "
                                     "Normattiva. Controlla il numero o cerca qui sopra.")
    if hit["status"] != cache.OK:
        return _errore(request, 503, "Normattiva non risponde in questo momento. "
                                     "Riprova tra qualche minuto.")

    etag = '"' + hashlib.sha256(
        (repr(hit["changed_at"]) + _TPL_HASH + base_url(request)).encode()).hexdigest()[:20] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_HDR})

    ctx = contesto_pagina(atto, art, hit["data"], base_url(request) + path, hit["fetched_at"])
    r = render(request, canonical_path=path, pagina=ctx)
    r.headers["ETag"] = etag
    r.headers["Cache-Control"] = CACHE_HDR
    return r


# ------------------------------------------------------------------- sitemap
def _xml(body: str) -> Response:
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n' + body,
                    media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_index(request: Request):
    b = base_url(request)
    nomi = ["home"] + [a.slug for a in catalogo.CATALOGO.values() if a.in_sitemap]
    righe = "".join(f"  <sitemap><loc>{xml_escape(b)}/sitemaps/{n}.xml</loc></sitemap>\n"
                    for n in nomi)
    return _xml('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + righe + "</sitemapindex>\n")


@router.get("/sitemaps/{nome}.xml", include_in_schema=False)
def sitemap_atto(nome: str, request: Request):
    b = xml_escape(base_url(request))
    ns = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    if nome == "home":
        return _xml(ns + f"  <url><loc>{b}/</loc></url>\n</urlset>\n")
    atto = catalogo.CATALOGO.get(nome)
    if not atto or not atto.in_sitemap:
        return Response("Not found", status_code=404)

    st = cache.store()
    idx = st.get(f"idx:{nome}", "idx", nome, _fetch_indice(atto))
    in_cache = {r["sotto"]: r["changed_at"] for r in st.gruppo(f"art:{nome}")}
    if idx["status"] != cache.OK and not in_cache:
        if idx["status"] == cache.UNAVAILABLE:
            return Response("Normattiva non raggiungibile", status_code=503,
                            headers={"Retry-After": "3600"})
    nums = list((idx["data"] or {}).get("nums", [])) if idx["status"] == cache.OK else []
    nums += [n for n in in_cache if n not in set(nums)]

    righe = []
    for n in nums:
        loc = f"{b}{catalogo.path_articolo(nome, n)}"
        lm = in_cache.get(n)
        lastmod = (f"<lastmod>{datetime.fromtimestamp(lm, timezone.utc):%Y-%m-%d}</lastmod>"
                   if lm else "")
        righe.append(f"  <url><loc>{loc}</loc>{lastmod}</url>\n")
    return _xml(ns + "".join(righe) + "</urlset>\n")
