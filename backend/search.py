"""
Ricerca web di INTERPRETAZIONI e GIURISPRUDENZA reali (con link verificabili).

Nessuna generazione AI. Catena di provider, dal piu' affidabile al fallback:

  1. Brave Search API  -> se e' impostata la variabile d'ambiente BRAVE_API_KEY.
     Free tier 2000 query/mese, JSON stabile: consigliato in produzione (Railway),
     dove gli IP datacenter vengono spesso bloccati dai motori scrapati.
  2. DuckDuckGo (HTML)  -> best-effort, funziona da IP "residenziali" ma puo'
     essere bloccato/limitato.
  3. Link diretti alle banche dati ufficiali -> sempre disponibili (deep_links),
     cosi' l'utente ha comunque una via verificabile anche se 1 e 2 falliscono.
"""
from __future__ import annotations

import html as _html
import os
import re
from dataclasses import dataclass, asdict
from urllib.parse import unquote, urlparse, quote_plus

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 20
DDG = "https://html.duckduckgo.com/html/"
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "").strip()

# Fonti giuridiche note -> punteggio di affidabilita' (piu' alto = piu' su)
TRUSTED = {
    "cortedicassazione.it": 10,
    "italgiure.giustizia.it": 10,
    "giustizia-amministrativa.it": 9,
    "cortecostituzionale.it": 9,
    "brocardi.it": 8,
    "altalex.com": 7,
    "dejure.it": 7,
    "normattiva.it": 6,
    "laleggepertutti.it": 6,
    "giurisprudenzapenale.com": 6,
    "giustiziainsieme.it": 6,
    "bosettiegatti.eu": 6,
    "diritto.it": 5,
    "ilprocessocivile.it": 5,
    "quotidianogiuridico.it": 5,
    "salvisjuribus.it": 4,
}

BLOCK = ("youtube.com", "facebook.com", "amazon.", "wikipedia.org", "pinterest.",
         "instagram.com", "tiktok.com", "studocu.com")


@dataclass
class Hit:
    title: str
    url: str
    snippet: str
    source: str
    trusted: bool


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""


def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return _html.unescape(s).strip()


def _rank(hits: list, n: int) -> list:
    hits.sort(key=lambda h: TRUSTED.get(h.source, 0), reverse=True)
    return hits[:n]


# ---------------------------------------------------------------- Brave API
def _brave(query: str, n: int) -> list:
    try:
        r = requests.get(
            BRAVE_ENDPOINT,
            headers={"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"},
            params={"q": query, "count": max(n * 2, 10), "country": "it",
                    "search_lang": "it", "result_filter": "web"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []

    hits, seen = [], set()
    for item in (data.get("web", {}) or {}).get("results", []):
        url = item.get("url", "")
        dom = _domain(url)
        if not url.startswith("http") or not dom or dom in seen:
            continue
        if any(x in dom for x in BLOCK):
            continue
        seen.add(dom)
        hits.append(Hit(title=_strip(item.get("title", "")), url=url,
                        snippet=_strip(item.get("description", "")),
                        source=dom, trusted=dom in TRUSTED))
    return _rank(hits, n)


# ------------------------------------------------------------ DuckDuckGo HTML
def _unwrap(url: str) -> str:
    m = re.search(r"[?&]uddg=([^&]+)", url)
    if m:
        return unquote(m.group(1))
    if url.startswith("//"):
        return "https:" + url
    return url


def _ddg(query: str, n: int) -> list:
    try:
        r = requests.post(DDG, data={"q": query}, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException:
        return []
    # pagina di challenge/anomaly: nessun risultato utile
    if "result__a" not in r.text:
        return []

    hits, seen = [], set()
    for b in re.split(r'class="result[ _]', r.text)[1:]:
        mu = re.search(r'result__a"?[^>]*href="([^"]+)"[^>]*>(.*?)</a>', 'class="result_' + b, re.S)
        if not mu:
            continue
        url = _unwrap(mu.group(1))
        title = _strip(mu.group(2))
        ms = re.search(r'result__snippet[^>]*>(.*?)</a>', b, re.S) or \
             re.search(r'result__snippet[^>]*>(.*?)</div>', b, re.S)
        snippet = _strip(ms.group(1)) if ms else ""
        dom = _domain(url)
        key = dom + title[:20]
        if not url.startswith("http") or not dom or key in seen:
            continue
        if any(x in dom for x in BLOCK):
            continue
        seen.add(key)
        hits.append(Hit(title=title, url=url, snippet=snippet, source=dom,
                        trusted=dom in TRUSTED))
    return _rank(hits, n)


# --------------------------------------------------------------------- public
def web_search(query: str, n: int = 6) -> list:
    """Esegue la ricerca usando il miglior provider disponibile."""
    hits = _brave(query, n) if BRAVE_KEY else []
    if not hits:
        hits = _ddg(query, n)
    return [asdict(h) for h in hits]


def interpretazione(label: str, extra: str = "") -> list:
    q = f"{label} {extra} interpretazione spiegazione commento dottrina".strip()
    return web_search(q, 6)


def giurisprudenza(label: str, extra: str = "") -> list:
    q = f"{label} {extra} giurisprudenza sentenza cassazione massima".strip()
    return web_search(q, 6)


def deep_links(ref_label: str) -> list:
    """Ricerche pronte verso le banche dati ufficiali (sempre disponibili)."""
    q = quote_plus(ref_label)
    return [
        {"name": "Corte di Cassazione (ItalgiureWeb)",
         "url": "https://www.italgiure.giustizia.it/sncass/"},
        {"name": "Giurisprudenza su Google Scholar",
         "url": f"https://scholar.google.com/scholar?q={q}"},
        {"name": "Brocardi — spiegazioni e massime",
         "url": f"https://www.brocardi.it/ricerca/?q={q}"},
        {"name": "Altalex — dottrina e sentenze",
         "url": f"https://www.altalex.com/ricerca?q={q}"},
        {"name": "Ricerca web generale",
         "url": f"https://duckduckgo.com/?q={q}+giurisprudenza"},
    ]


def provider_status() -> str:
    return "brave" if BRAVE_KEY else "duckduckgo"
