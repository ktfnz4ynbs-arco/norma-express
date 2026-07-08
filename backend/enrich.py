"""
Arricchimento dei risultati con RIASSUNTI ESTRATTIVI dalle fonti reali.

Meccanismo ispirato alle piattaforme RegTech (es. Aptus.AI/Daitomic):
ogni sintesi e' tracciabile alla fonte — ma qui NIENTE testo generato:
si estraggono frasi reali dalla pagina fonte, selezionate per rilevanza
rispetto alla ricerca. Per l'approfondimento si rimanda alla fonte diretta.

Casi speciali:
- brocardi.it: pagine articolo strutturate -> "Spiegazione" (interpretazione)
  e "Massime" (giurisprudenza reale con estremi di Cassazione).
"""
from __future__ import annotations

import html as _html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 10
MAX_SUMMARY = 420
STOPWORDS = {"della", "delle", "degli", "dello", "nella", "nelle", "sulla", "sulle",
             "con", "per", "che", "una", "uno", "gli", "dei", "del", "alla", "alle",
             "art", "articolo", "legge", "codice", "comma"}


# ------------------------------------------------------------------ fetching
def _get(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers={"User-Agent": UA,
                                       "Accept-Language": "it-IT,it;q=0.9"},
                         timeout=TIMEOUT)
        r.raise_for_status()
        # solo HTML: PDF/Office/binari produrrebbero testo illeggibile
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and "html" not in ctype and "text/plain" not in ctype:
            return None
        if r.content[:5] == b"%PDF-":
            return None
        if r.encoding in (None, "ISO-8859-1"):
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except requests.RequestException:
        return None


def _readable(text: str) -> bool:
    """True se il testo sembra linguaggio naturale (non spazzatura binaria)."""
    if not text or len(text) < 60:
        return False
    sample = text[:600]
    word_chars = sum(1 for c in sample if c.isalpha() or c.isspace() or c in ".,;:'()-–«»0123456789")
    return word_chars / len(sample) > 0.85


def _clean(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


# --------------------------------------------------------- extractive summary
_ABBR = re.compile(r"\b(art|artt|n|cass|civ|pen|sez|cod|proc|lett|co|comma|d|lgs|reg|par|pag|cfr|ss|op|cit)\.",
                   re.I)


def _sentences(text: str) -> list:
    # proteggi le abbreviazioni giuridiche ("art.", "Cass. civ. n.") dallo split
    guarded = _ABBR.sub(lambda m: m.group(1) + "\x00", text)
    parts = re.split(r"(?<=[.;!?])\s+(?=[A-ZÀ-Ú«(0-9])", guarded)
    return [p.replace("\x00", ".").strip() for p in parts if len(p.strip()) > 40]


def _terms(query: str) -> set:
    words = re.findall(r"[a-zà-ú]{3,}|\d{1,5}", query.lower())
    return {w for w in words if w not in STOPWORDS}


def _score(sentence: str, terms: set) -> float:
    low = sentence.lower()
    hits = sum(1 for t in terms if t in low)
    bonus = 1.5 if re.search(r"cass\.|cassazione|sentenza|corte|risarc|responsabilit", low) else 0
    return hits + bonus


def _main_text(html: str) -> str:
    """Estrae il testo principale: paragrafi dal blocco piu' denso della pagina."""
    body = re.sub(r"(?is)<(script|style|noscript|nav|header|footer|aside|form)[^>]*>.*?</\1>",
                  " ", html)
    paras = [_clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]
    paras = [p for p in paras if len(p) > 60]
    if not paras:
        return _clean(body)[:4000]
    return " ".join(paras[:40])


def summarize_page(url: str, query: str) -> str:
    """Riassunto estrattivo: frasi reali della pagina, le piu' pertinenti.
    Ritorna "" se il contenuto non e' testo leggibile (PDF/binari)."""
    html = _get(url)
    if not html:
        return ""
    text = _main_text(html)
    if not _readable(text):
        return ""
    sents = _sentences(text)
    if not sents:
        return text[:MAX_SUMMARY] if _readable(text[:MAX_SUMMARY]) else ""
    terms = _terms(query)
    ranked = sorted(enumerate(sents), key=lambda x: _score(x[1], terms), reverse=True)
    picked = sorted(i for i, _ in ranked[:3])
    out = " ".join(sents[i] for i in picked)
    if len(out) > MAX_SUMMARY:
        out = out[:MAX_SUMMARY].rsplit(" ", 1)[0] + "…"
    return out if _readable(out) else ""


def batch_summaries(urls: list, query: str, max_workers: int = 5) -> dict:
    """Riassunti in parallelo per una lista di URL. {url: summary}"""
    out = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(summarize_page, u, query): u for u in urls[:8]}
        for f in as_completed(futs):
            u = futs[f]
            try:
                out[u] = f.result()
            except Exception:
                out[u] = ""
    return out


# ----------------------------------------------------------------- Brocardi
def _is_brocardi_article(url: str) -> bool:
    return "brocardi.it" in url and re.search(r"/art\d+[a-z]*\.html", url) is not None


def brocardi_extract(url: str) -> dict:
    """Da una pagina articolo Brocardi: spiegazione + massime (Cassazione)."""
    html = _get(url)
    if not html:
        return {}
    out = {}

    m = re.search(r"Spiegazione dell'art[^<]*</h\d>(.*?)<h\d", html, re.S)
    if m:
        sp = re.search(r'class="corpoDelTesto[^"]*"[^>]*>(.*?)</div>', m.group(1), re.S)
        if sp:
            text = _clean(sp.group(1))
            sents = _sentences(text) or [text]
            out["spiegazione"] = " ".join(sents[:3])[:600]

    massime = []
    for raw in re.findall(r'class="sentenza corpoDelTesto"[^>]*>(.*?)</div>', html, re.S):
        t = _clean(raw)
        ref = re.match(r"((?:Cass|Corte|Cons|Trib|App)[^0-9]*n\.?\s*[\d/]+)", t)
        if ref:
            t = t[ref.end():].strip()  # il riferimento va solo nell'intestazione
        if len(t) > 60:
            massime.append({
                "ref": ref.group(1).strip() if ref else "",
                "text": t[:380] + ("…" if len(t) > 380 else ""),
            })
        if len(massime) >= 4:
            break
    if massime:
        out["massime"] = massime
        out["massime_url"] = url
    return out


def enrich(query: str, interp_urls: list, giuri_urls: list) -> dict:
    """Endpoint core: riassunti per tutti gli URL + estrazione speciale Brocardi."""
    all_urls = list(dict.fromkeys((interp_urls or []) + (giuri_urls or [])))[:8]

    brocardi_url = next((u for u in all_urls if _is_brocardi_article(u)), None)
    result = {"summaries": {}, "brocardi": {}}

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_sum = ex.submit(batch_summaries,
                          [u for u in all_urls if u != brocardi_url], query)
        f_bro = ex.submit(brocardi_extract, brocardi_url) if brocardi_url else None
        result["summaries"] = f_sum.result()
        if f_bro is not None:
            bro = f_bro.result()
            result["brocardi"] = bro
            if bro.get("spiegazione"):
                result["summaries"][brocardi_url] = bro["spiegazione"]
    return result
