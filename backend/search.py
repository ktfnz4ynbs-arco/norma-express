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
STARTPAGE = "https://www.startpage.com/sp/search"
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "").strip()

# Fonti giuridiche note AD ACCESSO GRATUITO -> punteggio (piu' alto = piu' su)
TRUSTED = {
    "cortedicassazione.it": 10,
    "italgiure.giustizia.it": 10,
    "giustizia-amministrativa.it": 9,
    "cortecostituzionale.it": 9,
    "brocardi.it": 8,
    "normattiva.it": 6,
    "gazzettaufficiale.it": 6,
    "laleggepertutti.it": 6,
    "giurisprudenzapenale.com": 6,
    "giustiziainsieme.it": 6,
    "bosettiegatti.eu": 6,
    "diritto.it": 5,
    "ilprocessocivile.it": 5,
    "salvisjuribus.it": 4,
    "wikilabour.it": 4,
}

# Esclusi: rumore + SERVIZI A PAGAMENTO (paywall/abbonamento)
BLOCK = ("youtube.com", "facebook.com", "amazon.", "wikipedia.org", "pinterest.",
         "instagram.com", "tiktok.com", "studocu.com",
         # banche dati / editoria giuridica a pagamento
         "dejure.it", "leggiditalia.it", "quotidianogiuridico.it", "altalex.com",
         "onelegale.wolterskluwer.it", "wolterskluwer.it", "giuffre.it",
         "giuffrefrancislefebvre.it", "giuffrefl.it", "plusplus24diritto",
         "ilsole24ore.com", "24o.it", "giappichelli.it", "zanichelli.it",
         "edotto.com", "dirittoegiustizia.it", "iusexplorer.it", "lexology.com",
         "shop.")


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


_DOC_RE = re.compile(r"\.(pdf|docx?|pptx?|xlsx?|rtf|zip)(?:$|[?#])", re.I)


def _rank(hits: list, n: int) -> list:
    # niente documenti binari (PDF/Office): non riassumibili in modo leggibile
    hits = [h for h in hits if not _DOC_RE.search(h.url)]
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


# --------------------------------------------------------- Startpage (keyless)
def _startpage(query: str, n: int) -> list:
    """Risultati Google via Startpage: nessuna API key, nessuna registrazione."""
    try:
        r = requests.get(
            STARTPAGE, params={"query": query, "cat": "web"},
            headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9",
                     "Accept": "text/html,application/xhtml+xml"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException:
        return []

    clean = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", r.text)
    snips = [_strip(s) for s in re.findall(
        r'<p class="description[^"]*"[^>]*>(.*?)</p>', clean, re.S)]

    hits, seen = [], set()
    for i, m in enumerate(re.finditer(
            r'<a\b([^>]*\bclass="[^"]*result-title[^"]*"[^>]*)>(.*?)</a>', clean, re.S)):
        hm = re.search(r'href="([^"]+)"', m.group(1))
        url = hm.group(1) if hm else ""
        title = _strip(m.group(2))
        dom = _domain(url)
        if not url.startswith("http") or not dom or dom in seen or not title:
            continue
        if any(x in dom for x in BLOCK):
            continue
        seen.add(dom)
        hits.append(Hit(title=title, url=url, snippet=snips[i] if i < len(snips) else "",
                        source=dom, trusted=dom in TRUSTED))
    return _rank(hits, n)


# --------------------------------------------------------------------- public
def _engines():
    """Provider in ordine di preferenza. Brave solo se c'e' la key (opzionale)."""
    chain = []
    if BRAVE_KEY:
        chain.append(_brave)
    chain += [_startpage, _ddg]
    return chain


def web_search(query: str, n: int = 6) -> list:
    """Prova i provider keyless in sequenza finche' uno restituisce risultati."""
    for engine in _engines():
        try:
            hits = engine(query, n)
        except Exception:
            hits = []
        if hits:
            return [asdict(h) for h in hits]
    return []


def interpretazione(label: str, extra: str = "") -> list:
    q = f"{label} {extra} interpretazione spiegazione commento dottrina".strip()
    return web_search(q, 6)


def giurisprudenza(label: str, extra: str = "") -> list:
    q = f"{label} {extra} giurisprudenza sentenza cassazione massima".strip()
    return web_search(q, 6)


def deep_links(ref_label: str) -> list:
    """Ricerche pronte verso banche dati GRATUITE (sempre disponibili)."""
    q = quote_plus(ref_label)
    return [
        {"name": "Corte di Cassazione (ItalgiureWeb)",
         "url": "https://www.italgiure.giustizia.it/sncass/"},
        {"name": "Corte Costituzionale",
         "url": "https://www.cortecostituzionale.it/actionPronuncia.do"},
        {"name": "Giurisprudenza su Google Scholar",
         "url": f"https://scholar.google.com/scholar?q={q}"},
        {"name": "Brocardi — spiegazioni e massime",
         "url": f"https://www.brocardi.it/ricerca/?q={q}"},
        {"name": "Ricerca web generale",
         "url": f"https://duckduckgo.com/?q={q}+giurisprudenza"},
    ]


def normattiva_url(query: str) -> str:
    """Trova il permalink Normattiva della legge che corrisponde alla parola chiave."""
    for h in _startpage(f"{query} normattiva", 10):
        if "normattiva.it" in h.url and ("uri-res" in h.url or "N2Ls" in h.url):
            return h.url
    return ""


def provider_status() -> str:
    return "brave" if BRAVE_KEY else "startpage+duckduckgo"
