"""
Recupero del testo ufficiale di un articolo da Normattiva.

Strategia (verificata):
  1. GET del permalink URN con sessione (cookie JSESSIONID) -> pagina dell'atto.
     Da qui si estraggono: titolo, codiceRedazionale, dataPubblicazioneGazzetta
     e i link 'caricaArticolo' (uno per versione/articolo).
  2. Si sceglie il link dell'articolo richiesto nella versione VIGENTE
     (quella senza il parametro imUpdate=true).
  3. GET di caricaArticolo -> HTML del singolo articolo, si estrae il testo
     dal contenitore div.bodyTesto (heading + commi + data di vigenza).
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

from lawref import LawRef

BASE = "https://www.normattiva.it"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 25


@dataclass
class ArticleResult:
    ok: bool
    query_label: str = ""
    act_title: str = ""
    article_heading: str = ""
    text: str = ""
    in_force_from: str = ""
    permalink: str = ""
    updates: list = field(default_factory=list)
    error: str = ""
    abrogato: bool = False      # rilevamento automatico stato abrogazione
    versions: int = 0           # numero versioni dell'articolo (multivigenza)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
    return s


def _clean(node) -> str:
    for bad in node.select("script, style"):
        bad.decompose()
    txt = node.get_text("\n", strip=True)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _pick_article_link(html: str, articolo: Optional[str]) -> tuple:
    """Trova il link caricaArticolo dell'articolo richiesto (versione vigente)
    e il numero di versioni esistenti (multivigenza)."""
    links = re.findall(r'caricaArticolo\?[^"\'<> ]+', html)
    if not links:
        return None, 0
    links = [unquote(l) for l in links]

    if articolo:
        target = re.sub(r"[^0-9]", "", articolo)  # "2-bis" -> "2"
        cands = [l for l in links if re.search(rf"art\.idArticolo={re.escape(target)}(?:&|$)", l)]
        if not cands:
            return None, 0
    else:
        cands = links

    versions = 0
    for l in cands:
        m = re.search(r"art\.versione=(\d+)", l)
        if m:
            versions = max(versions, int(m.group(1)))

    # Versione vigente = senza imUpdate=true (le storiche lo hanno)
    current = [l for l in cands if "imUpdate=true" not in l]
    chosen = current[0] if current else cands[0]
    return BASE + "/atto/" + chosen, versions


def _parse_article(html: str) -> tuple[str, str, str]:
    """Ritorna (heading, testo, in_force_from) dal contenitore bodyTesto."""
    soup = BeautifulSoup(html, "html.parser")

    heading = ""
    h = soup.select_one(".article-heading-akn")
    if h:
        heading = _clean(h)

    in_force = ""
    v = soup.select_one(".vigore")
    if v:
        m = re.search(r"in vigore dal[:\s]*([0-9./-]+)", v.get_text(" ", strip=True), re.I)
        if m:
            in_force = m.group(1).strip()

    body = soup.select_one(".bodyTesto")
    if body:
        # rimuovi elementi non testuali: toolbar, vigenza duplicata e
        # preambolo di promulgazione ("La Camera... PROMULGA la seguente legge")
        for sel in [".vigore", ".d-flex", ".preamble-before-title-akn",
                    ".formula-introduttiva", ".preamble", ".formula-promulgazione"]:
            for n in body.select(sel):
                n.decompose()
        text = _clean(body)
    else:
        text = _clean(soup)

    # Rete di sicurezza: taglia un eventuale preambolo residuo prima di "Art. N"
    m = re.search(r"\bArt\.?\s*\d", text)
    if m and m.start() > 0 and m.start() < 400:
        text = text[m.start():]

    # Se manca l'heading, prova a ricavarlo dalla prima riga "Art. N (...)"
    if not heading:
        m = re.search(r"(Art\.\s*\d+[^\n]*)", text)
        if m:
            heading = m.group(1).strip()

    # Leggibilita': unisci il numero di comma ("1.", "1-bis.", "a)") al testo che segue
    text = re.sub(
        r"\n\s*(\d+(?:-(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?[.)]"
        r"|[a-z][.)])\s*\n",
        r"\n\1 ", text)
    return heading, text, in_force


def _parse_updates(page_html: str, articolo: Optional[str]) -> list:
    """Estrae le note di aggiornamento visibili nella pagina dell'atto."""
    updates = []
    for m in re.finditer(r"aggiornament[oi][^<]{0,120}", page_html, re.I):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        if s and s.lower() != "aggiornamenti all'articolo" and s not in updates:
            updates.append(s)
    return updates[:5]


def fetch_article(ref: LawRef) -> ArticleResult:
    urn = ref.urn()
    permalink = ref.permalink()
    if not urn or not permalink:
        return ArticleResult(ok=False, query_label=ref.label,
                             error="Riferimento normativo non valido o incompleto.")

    s = _session()
    try:
        r = s.get(permalink, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        return ArticleResult(ok=False, query_label=ref.label, permalink=permalink,
                             error=f"Normattiva non raggiungibile: {e}")

    page = r.text
    title_m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    act_title = re.sub(r"\s*-\s*Normattiva\s*$", "", title_m.group(1).strip()) if title_m else ""

    if re.search(r"nessun\s+(risultat|att)", page, re.I) and not title_m:
        return ArticleResult(ok=False, query_label=ref.label, permalink=permalink,
                             error="Atto non trovato su Normattiva. Verifica tipo, numero e anno.")

    # Se non e' richiesto un articolo specifico, restituiamo titolo + link
    if not ref.articolo:
        return ArticleResult(ok=True, query_label=ref.label, act_title=act_title,
                             article_heading="", text="",
                             permalink=permalink,
                             error="Indica un numero di articolo per il testo completo. "
                                   "Apri l'atto su Normattiva dal link.")

    art_url, versions = _pick_article_link(page, ref.articolo)
    if not art_url:
        return ArticleResult(ok=False, query_label=ref.label, act_title=act_title,
                             permalink=permalink,
                             error=f"Articolo {ref.articolo} non individuato nell'atto. "
                                   "Puo' avere numerazione bis/ter o non esistere: apri Normattiva.")

    try:
        ra = s.get(art_url, timeout=TIMEOUT)
        ra.raise_for_status()
    except requests.RequestException as e:
        return ArticleResult(ok=False, query_label=ref.label, act_title=act_title,
                             permalink=permalink, error=f"Errore nel caricamento dell'articolo: {e}")

    heading, text, in_force = _parse_article(ra.text)
    updates = _parse_updates(ra.text, ref.articolo)

    # Intestazione leggibile: "Art. N — (rubrica)"
    if heading and not re.match(r"\s*art", heading, re.I):
        heading = f"Art. {ref.articolo} — {heading}"
    elif not heading:
        heading = f"Art. {ref.articolo}"

    if not text or len(text) < 15:
        return ArticleResult(ok=False, query_label=ref.label, act_title=act_title,
                             permalink=permalink,
                             error="Testo dell'articolo non estraibile. Apri l'atto su Normattiva.")

    abrogato = bool(re.search(r"ARTICOLO ABROGATO", text, re.I))
    return ArticleResult(ok=True, query_label=ref.label, act_title=act_title,
                         article_heading=heading, text=text, in_force_from=in_force,
                         permalink=permalink, updates=updates,
                         abrogato=abrogato, versions=versions)
