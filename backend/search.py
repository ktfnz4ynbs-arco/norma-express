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
from concurrent.futures import ThreadPoolExecutor

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
    "giurcost.org": 8,
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


def _rank(hits: list, n: int, drop_docs: bool = True) -> list:
    # di norma niente documenti binari (non riassumibili); ma per le fonti
    # istituzionali (es. Gazzetta Ufficiale) i PDF ufficiali vanno tenuti.
    if drop_docs:
        hits = [h for h in hits if not _DOC_RE.search(h.url)]
    hits.sort(key=lambda h: TRUSTED.get(h.source, 0), reverse=True)
    return hits[:n]


# ---------------------------------------------------------------- Brave API
def _brave(query: str, n: int, dedupe: str = "domain") -> list:
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
        key = dom if dedupe == "domain" else url
        if not url.startswith("http") or not dom or key in seen:
            continue
        if any(x in dom for x in BLOCK):
            continue
        seen.add(key)
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


def _ddg(query: str, n: int, dedupe: str = "domain") -> list:
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
        key = (dom + title[:20]) if dedupe == "domain" else url
        if not url.startswith("http") or not dom or key in seen:
            continue
        if any(x in dom for x in BLOCK):
            continue
        seen.add(key)
        hits.append(Hit(title=title, url=url, snippet=snippet, source=dom,
                        trusted=dom in TRUSTED))
    return _rank(hits, n)


# --------------------------------------------------------- Startpage (keyless)
def _startpage(query: str, n: int, drop_docs: bool = True, dedupe: str = "domain") -> list:
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
        key = dom if dedupe == "domain" else url
        if not url.startswith("http") or not dom or key in seen or not title:
            continue
        if any(x in dom for x in BLOCK):
            continue
        seen.add(key)
        hits.append(Hit(title=title, url=url, snippet=snips[i] if i < len(snips) else "",
                        source=dom, trusted=dom in TRUSTED))
    return _rank(hits, n, drop_docs)


# --------------------------------------------------------------------- public
def _engines():
    """Provider in ordine di preferenza. Brave solo se c'e' la key (opzionale)."""
    chain = []
    if BRAVE_KEY:
        chain.append(_brave)
    chain += [_startpage, _ddg]
    return chain


def web_search(query: str, n: int = 6, dedupe: str = "domain") -> list:
    """Prova i provider keyless in sequenza finche' uno restituisce risultati.

    `dedupe="url"` serve alle ricerche ristrette a un singolo dominio
    (operatore `site:`): deduplicando per dominio tornerebbe UN solo risultato.
    """
    for engine in _engines():
        try:
            hits = engine(query, n, dedupe=dedupe)
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
    links = []
    for b in BANCHE:
        links.append({"name": b["ricerca_nome"], "url": _url_ricerca(b, ref_label)})
        if b.get("portale"):
            links.append(b["portale"])
    links += [
        {"name": "Giurisprudenza su Google Scholar",
         "url": f"https://scholar.google.com/scholar?q={q}"},
        {"name": "Ricerca web generale",
         "url": f"https://duckduckgo.com/?q={q}+giurisprudenza"},
    ]
    return links


# ======================================= BANCHE DATI INTERROGATE PER DOMINIO
# Finche' la giurisprudenza arriva da UNA ricerca generica, che compaia la
# Cassazione o la Consulta e' questione di fortuna: TRUSTED si limita a
# riordinare cio' che il motore ha gia' restituito. Qui invece ogni banca dati
# viene interrogata CON UNA RICERCA RISTRETTA AL SUO DOMINIO (operatore
# `site:`), cosi' i risultati sono attribuibili alla corte che li ha emessi.
#
# Nessuno scraping dei portali: si passa sempre dai provider gia' in uso, che
# reggono i blocchi anti-bot molto meglio di un client nostro verso siti
# (Italgiure in primis) notoriamente ostili ai client automatici.
BANCHE = (
    {"id": "cassazione", "nome": "Corte di Cassazione",
     "domini": ("italgiure.giustizia.it", "cortedicassazione.it"),
     "termini": "sentenza massima",
     "ricerca_nome": "Cassazione - cerca questa norma",
     "portale": {"name": "Corte di Cassazione (ItalgiureWeb)",
                 "url": "https://www.italgiure.giustizia.it/sncass/"}},
    {"id": "costituzionale", "nome": "Corte Costituzionale",
     "domini": ("cortecostituzionale.it", "giurcost.org"),
     "termini": "sentenza ordinanza illegittimita costituzionale",
     "ricerca_nome": "Corte Costituzionale - cerca questa norma",
     "portale": {"name": "Corte Costituzionale - pronunce",
                 "url": "https://www.cortecostituzionale.it/actionPronuncia.do"}},
    {"id": "gazzetta", "nome": "Gazzetta Ufficiale",
     "domini": ("gazzettaufficiale.it",),
     "termini": "pubblicazione testo",
     "ricerca_nome": "Gazzetta Ufficiale - cerca questa norma",
     "portale": {"name": "Gazzetta Ufficiale", "url": "https://www.gazzettaufficiale.it/"}},
    {"id": "brocardi", "nome": "Brocardi",
     "domini": ("brocardi.it",),
     "termini": "spiegazione massime",
     "ricerca_nome": "Brocardi - spiegazioni e massime",
     "portale": None},
)


def _url_ricerca(banca: dict, label: str) -> str:
    """Link che PORTA CON SE' la query.

    I portali di Cassazione e Consulta espongono form che non accettano la
    ricerca in query string: linkarli e basta scarica sull'utente il compito di
    ridigitare tutto. Si passa quindi da un motore con l'operatore `site:`, la
    cui forma di URL e' stabile e verificabile.
    """
    siti = " OR ".join("site:" + d for d in banca["domini"])
    return "https://duckduckgo.com/?q=" + quote_plus(f"{siti} {label}")


def _cerca_banca(banca: dict, label: str, extra: str, n: int) -> dict:
    siti = " OR ".join("site:" + d for d in banca["domini"])
    q = " ".join(x for x in (siti, label, extra, banca["termini"]) if x)
    try:
        hits = web_search(q, n, dedupe="url")
    except Exception:
        hits = []
    # L'operatore site: non e' onorato allo stesso modo da tutti i provider:
    # si filtra comunque per dominio, cosi' l'attribuzione alla corte e' certa.
    hits = [h for h in hits if any(d in h.get("source", "") for d in banca["domini"])]
    return {"id": banca["id"], "nome": banca["nome"], "results": hits[:n],
            "ricerca": _url_ricerca(banca, label), "portale": banca.get("portale")}


def banche_dati(label: str, extra: str = "", n: int = 4) -> list:
    """Interroga in parallelo ogni banca dati e restituisce i blocchi per corte.

    Un blocco senza risultati NON viene nascosto: resta con i suoi link, cosi'
    l'utente ha sempre una via verificabile (stesso principio dei deep_links).
    """
    if not label:
        return []
    with ThreadPoolExecutor(max_workers=len(BANCHE)) as ex:
        futures = [ex.submit(_cerca_banca, b, label, extra, n) for b in BANCHE]
        return [f.result() for f in futures]


# ============================================ ITER PARLAMENTARE (contesto a parte)
# La vecchia funzione `parlamento()` faceva UNA ricerca indistinta. Una norma
# pero' attraversa fasi diverse, e un giurista cerca quasi sempre UNA di
# quelle: il testo presentato, cosa si e' detto in commissione, quali
# emendamenti sono passati, come e' uscita la legge. Qui ogni fase e'
# interrogata per conto suo, cosi' il risultato dice A CHE PUNTO DELL'ITER
# appartiene invece di mescolare tutto.
FASI_ITER = (
    {"id": "ddl", "nome": "Disegni e proposte di legge",
     "descrizione": "Il testo come e' stato presentato alle Camere.",
     "domini": ("camera.it", "senato.it"),
     "termini": "disegno di legge proposta di legge testo presentato"},
    {"id": "lavori", "nome": "Lavori preparatori",
     "descrizione": "Relazione illustrativa, esame in commissione, discussione in aula.",
     "domini": ("camera.it", "senato.it"),
     "termini": "lavori preparatori relazione illustrativa commissione discussione aula resoconto"},
    {"id": "emendamenti", "nome": "Emendamenti",
     "descrizione": "Proposte di modifica al testo, approvate o respinte.",
     "domini": ("camera.it", "senato.it"),
     "termini": "emendamenti fascicolo approvati respinti"},
    {"id": "legge", "nome": "Legge approvata",
     "descrizione": "Il testo definitivo e la sua pubblicazione.",
     "domini": ("gazzettaufficiale.it", "normattiva.it", "camera.it", "senato.it"),
     "termini": "legge approvata testo definitivo pubblicata in gazzetta ufficiale"},
)

PORTALI_ITER = (
    {"name": "Camera - Progetti di legge", "url": "https://www.camera.it/leg19/126"},
    {"name": "Senato - Disegni di legge (iter)",
     "url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/index.html"},
    {"name": "Normattiva - testo vigente e multivigenza", "url": "https://www.normattiva.it/"},
)


def _cerca_fase(fase: dict, label: str, extra: str, n: int) -> dict:
    siti = " OR ".join("site:" + d for d in fase["domini"])
    q = " ".join(x for x in (siti, label, extra, fase["termini"]) if x)
    try:
        hits = web_search(q, n, dedupe="url")
    except Exception:
        hits = []
    hits = [h for h in hits if any(d in h.get("source", "") for d in fase["domini"])]
    return {"id": fase["id"], "nome": fase["nome"], "descrizione": fase["descrizione"],
            "results": hits[:n],
            "ricerca": "https://duckduckgo.com/?q=" + quote_plus(
                " ".join((siti, label, fase["termini"])))}


def iter_parlamentare(label: str, extra: str = "", n: int = 4) -> list:
    """Blocchi per fase dell'iter: ddl -> lavori -> emendamenti -> legge."""
    if not label:
        return []
    with ThreadPoolExecutor(max_workers=len(FASI_ITER)) as ex:
        futures = [ex.submit(_cerca_fase, f, label, extra, n) for f in FASI_ITER]
        return [f.result() for f in futures]


# -------- quando conviene richiamare il contesto "genesi della norma"
# I numeri di articolo collidono con gli anni ("art. 2043 c.c." non e' il 2043):
# si toglie prima il riferimento all'articolo, poi si cerca l'anno SOLO dove e'
# davvero un anno - dopo la barra ("241/1990") o in una data ("7 agosto 1990").
_ART_RE = re.compile(
    r"\bart(?:icolo)?\.?\s*\d+(?:[-\s]?(?:bis|ter|quater|quinquies|sexies|septies|octies))?",
    re.I)
_ANNO_RE = re.compile(
    r"(?:/\s*|\bdel\s+|\bn\.?\s*\d{1,5}\s+del\s+|\b\d{1,2}\s+[a-z]+\s+)((?:18|19|20)\d{2})\b",
    re.I)
_SEGNALI = (
    ("ratio", ("ratio", "perche", "perché", "finalita", "finalità", "scopo",
               "intenzione del legislatore", "spirito della norma")),
    ("confronto", ("differenz", "novita", "novità", "riforma", "riformat", "modific",
                   "previgente", "prima della", "rispetto alla precedente", "abrogat")),
    ("applicazione", ("applicazione", "applicare", "si applica", "entrata in vigore",
                      "transitori", "decorrenza")),
)


def motivi_genesi(label: str, extra: str = "", versioni: int = 0,
                  abrogato: bool = False, anno_corrente: int = 0) -> list:
    """Perche' valga la pena aprire i lavori parlamentari, in parole chiare.

    Niente AI: sono segnali osservabili (eta' della norma, stratificazione,
    parole della domanda). Lista vuota = il contesto resta chiuso.
    """
    testo = (label + " " + (extra or "")).lower()
    motivi = []

    for _id, parole in _SEGNALI:
        if any(p in testo for p in parole):
            motivi.append({
                "ratio": "La domanda riguarda la ratio della norma: i lavori "
                         "preparatori dicono cosa il legislatore voleva ottenere.",
                "confronto": "La domanda tocca il confronto con la disciplina "
                             "precedente: l'iter mostra cosa e' cambiato e perche'.",
                "applicazione": "La domanda riguarda l'applicazione: nei lavori si "
                                "trovano regime transitorio e decorrenze.",
            }[_id])

    if versioni and versioni > 1:
        motivi.append("La norma ha %d versioni successive: l'iter spiega le modifiche."
                      % versioni)
    if abrogato:
        motivi.append("La norma risulta abrogata: i lavori aiutano a capire da cosa "
                      "e' stata sostituita.")

    if anno_corrente:
        anni = [int(m.group(1)) for m in _ANNO_RE.finditer(_ART_RE.sub(" ", label))]
        if anni and max(anni) >= anno_corrente - 3:
            motivi.append("Norma recente (%d): per le nuove discipline la "
                          "giurisprudenza e' ancora scarsa e i lavori preparatori "
                          "sono spesso la fonte piu' solida." % max(anni))

    # dedup conservando l'ordine
    visti, out = set(), []
    for m in motivi:
        if m not in visti:
            visti.add(m)
            out.append(m)
    return out


# ================================================== FONTI ISTITUZIONALI
def _institutional(query: str, prefer: list, n: int = 8) -> list:
    """Ricerca web (keyless) ri-ordinata dando priorita' ai domini del contesto.
    Tiene i PDF: per le fonti istituzionali sono i documenti ufficiali."""
    hits = _startpage(query, 14, drop_docs=False)
    if not hits:
        hits = _ddg(query, 14)

    def pref_score(h):
        for i, d in enumerate(prefer):
            if d in h.source:
                return len(prefer) - i
        return -1  # domini non prioritari in coda ma non esclusi

    hits.sort(key=pref_score, reverse=True)
    return [asdict(h) for h in hits[:n]]


def gazzetta_ufficiale(query: str) -> dict:
    hits = _institutional(f"gazzetta ufficiale {query}", ["gazzettaufficiale.it"])
    return {"results": hits, "portali": [
        {"name": "Gazzetta Ufficiale — ricerca", "url": "https://www.gazzettaufficiale.it/"},
        {"name": "GU Serie Generale", "url": "https://www.gazzettaufficiale.it/gazzetta/serie_generale/caricaDettaglio"},
    ]}


def parlamento(query: str) -> dict:
    hits = _institutional(
        f"{query} disegno di legge proposta di legge iter parlamentare",
        ["camera.it", "senato.it", "openpolis.it"])
    return {"results": hits, "portali": [
        {"name": "Camera — Progetti di legge", "url": "https://www.camera.it/leg19/126"},
        {"name": "Senato — Disegni di legge (iter)", "url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/index.html"},
    ]}


def regionale(query: str) -> dict:
    hits = _institutional(
        f"{query} legge regionale consiglio regionale",
        ["consiglio.regione", "regione.", "normelombardia", "arianna"])
    return {"results": hits, "portali": [
        {"name": "Normattiva — Motore federato regionale",
         "url": "https://www.normattiva.it/legislazioneRegionale"},
    ]}


def normattiva_url(query: str) -> str:
    """Trova il permalink Normattiva della legge che corrisponde alla parola chiave."""
    for h in _startpage(f"{query} normattiva", 10):
        if "normattiva.it" in h.url and ("uri-res" in h.url or "N2Ls" in h.url):
            return h.url
    return ""


def provider_status() -> str:
    return "brave" if BRAVE_KEY else "startpage+duckduckgo"
