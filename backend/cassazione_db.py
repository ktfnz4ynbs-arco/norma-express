"""
Giurisprudenza penale recente da dataset open source:
Synthos-Logic/cassazione-penale-db
https://github.com/Synthos-Logic/cassazione-penale-db

Banca dati aperta, aggiornata settimanalmente via GitHub Action, delle
pronunce di Cassazione penale segnalate dall'Ufficio del Massimario.
Provvedimenti = atti ufficiali dello Stato (non soggetti a copyright);
schede in CC BY 4.0. Principio dichiarato dal progetto: "nessun dato
inventato", ogni scheda riporta solo campi testuali della Corte.

Uso qui: SOLO estrazione, in linea col resto dell'app. Si legge
SEGNALATE/INDICE.md (organizzato per materia) per trovare le pronunce
pertinenti alla ricerca via corrispondenza di parole chiave, poi si
scarica la singola scheda per il testo ufficiale della massima
("Oggetto") e il link al PDF autentico. Dataset non esaustivo (copre
solo le pronunce "segnalate" dal 2023): va trattato come integrazione
best-effort alla ricerca web di giurisprudenza, non come fonte completa.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests

REPO = "Synthos-Logic/cassazione-penale-db"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
REPO_URL = f"https://github.com/{REPO}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 12
_INDEX_TTL = 6 * 3600

_index_cache = {"ts": 0.0, "entries": []}

_PENALE_RE = re.compile(
    r"penal|\breat[oi]\b|imputat|delitt|contravvenzion|c\.?\s*p\.?\s*p\.?\b|"
    r"codice di procedura penale|cassazione", re.I)

_ENTRY_RE = re.compile(
    r"^- \*\*(Cass\.[^*]+)\*\*\s*·\s*dep\.\s*([\d-]+)\s*→\s*\[scheda\]\(([^)]+)\)")
_MATERIA_RE = re.compile(r"^###\s+(.+?)\s*$")

STOPWORDS = {"della", "delle", "degli", "dello", "nella", "nelle", "sulla",
             "sulle", "articolo", "codice", "legge", "comma", "penale",
             "cassazione", "sentenza", "sezione"}


def _get(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        if r.encoding in (None, "ISO-8859-1"):
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except requests.RequestException:
        return None


def _parse_indice(text: str) -> list:
    """Ogni citazione eredita la materia (intestazione ### ) sotto cui compare."""
    entries, materia = [], ""
    for line in text.splitlines():
        mt = _MATERIA_RE.match(line)
        if mt:
            materia = mt.group(1).strip()
            continue
        me = _ENTRY_RE.match(line)
        if me:
            entries.append({"materia": materia, "citazione": me.group(1).strip(),
                            "data_deposito": me.group(2).strip(), "path": me.group(3).strip()})
    return entries


def _index() -> list:
    now = time.time()
    if _index_cache["entries"] and now - _index_cache["ts"] < _INDEX_TTL:
        return _index_cache["entries"]
    text = _get(f"{RAW}/SEGNALATE/INDICE.md")
    entries = _parse_indice(text) if text else []
    if entries:
        _index_cache.update(ts=now, entries=entries)
        return entries
    return _index_cache["entries"]


def _terms(text: str) -> set:
    words = re.findall(r"[a-zà-ú]{4,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def _score(entry: dict, terms: set) -> int:
    hay = f"{entry['materia']} {entry['citazione']}".lower()
    return sum(1 for t in terms if t in hay)


def _scheda_extract(path: str) -> dict:
    text = _get(f"{RAW}/SEGNALATE/{path}")
    if not text:
        return {}
    out = {}
    m = re.search(r'url_pdf:\s*"?([^"\n]+)"?', text)
    if m:
        out["url_pdf"] = m.group(1).strip()
    m = re.search(r'url_scheda:\s*"?([^"\n]+)"?', text)
    if m:
        out["url_scheda"] = m.group(1).strip()
    m = re.search(r"(?m)^##\s*Massima ufficiale[^\n]*\n+((?:^>.*\n?)+)", text)
    if m:
        raw = re.sub(r"(?m)^>\s?", "", m.group(1))
        out["massima"] = re.sub(r"\s+", " ", raw).strip()[:500]
    m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    if m:
        out["titolo"] = m.group(1).strip()
    return out


def giurisprudenza_penale(label: str, extra: str = "", n: int = 3) -> list:
    """Pronunce Cassazione penale segnalate pertinenti alla ricerca
    (best-effort, dataset curato e non esaustivo). Gira solo per richieste
    riconducibili alla materia penale, per evitare falsi abbinamenti su
    ricerche civili/amministrative."""
    text = f"{label} {extra}"
    if not _PENALE_RE.search(text):
        return []
    terms = _terms(text)
    if not terms:
        return []
    entries = _index()
    if not entries:
        return []
    scored = sorted(((e, _score(e, terms)) for e in entries),
                    key=lambda x: x[1], reverse=True)
    top = [e for e, s in scored if s > 0][:n]

    out = []
    for e in top:
        sc = _scheda_extract(e["path"])
        if not sc:
            continue
        out.append({
            "citazione": e["citazione"], "materia": e["materia"],
            "data_deposito": e["data_deposito"],
            "massima": sc.get("massima", ""),
            "url_pdf": sc.get("url_pdf", ""),
            "url_scheda": sc.get("url_scheda") or f"{REPO_URL}/blob/main/SEGNALATE/{e['path']}",
        })
    return out
