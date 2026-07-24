"""
Indice della Costituzione (Parte/Titolo/Sezione -> articoli) da dataset
open source: dataciviclab/costituzione-italiana
https://github.com/dataciviclab/costituzione-italiana
(testo CC BY-SA 3.0, da Wikisource; codice MIT).

Uso qui: SOLO per costruire l'albero di navigazione con cui la card
"Indice della legge" mostra le voci della Costituzione (finora l'indice
lo si otteneva scrapando Normattiva, che per la Costituzione non espone
la stessa struttura delle leggi ordinarie). Il TESTO dell'articolo resta
SEMPRE quello ufficiale di Normattiva (vincolo di progetto invariato):
questo modulo produce solo l'etichetta/il percorso per arrivarci con un
clic, mai il contenuto legale mostrato all'utente.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests

RAW_URL = ("https://raw.githubusercontent.com/dataciviclab/"
           "costituzione-italiana/main/Costituzione.md")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 12
_TTL = 24 * 3600  # la Costituzione cambia raramente: cache lunga

_cache = {"ts": 0.0, "groups": [], "total": 0}


def _fetch() -> Optional[str]:
    try:
        r = requests.get(RAW_URL, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None


def _build_groups(text: str) -> list:
    """Albero Parte > Titolo > Sezione con i 139 articoli numerati. Le
    disposizioni transitorie e finali (numerazione romana, in coda al
    documento) restano fuori dall'indice cliccabile: non hanno un URN
    articolo su Normattiva raggiungibile con lo stesso schema "art N"."""
    parte = titolo = sezione = ""
    groups, current_label, current = [], None, None

    def flush():
        if current and current["articles"]:
            groups.append(current)

    for line in text.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            if "disposizioni transitorie" in m.group(1).lower():
                break  # fine della parte indicizzabile
            parte, titolo, sezione = m.group(1).strip(), "", ""
            continue
        m = re.match(r"^##\s+Art\.?\s*(\d+[a-z\-]*)\b", line, re.I)
        if m:
            num = m.group(1)
            label = " · ".join(p for p in (parte, titolo, sezione) if p)
            if label != current_label:
                flush()
                current_label, current = label, {"partition": label, "articles": []}
            current["articles"].append({"num": num, "q": f"art {num} costituzione"})
            continue
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            sezione = m.group(1).strip()
            continue
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            titolo, sezione = m.group(1).strip(), ""
            continue
    flush()
    return groups


def index() -> dict:
    """{'ok', 'groups', 'total'}, con cache in memoria (24h). In caso di
    errore di rete ritorna l'ultima cache valida se presente, altrimenti
    ok=False (il chiamante puo' ripiegare sull'indice scrapato da
    Normattiva)."""
    now = time.time()
    if _cache["groups"] and now - _cache["ts"] < _TTL:
        return {"ok": True, "groups": _cache["groups"], "total": _cache["total"]}
    text = _fetch()
    if not text:
        if _cache["groups"]:
            return {"ok": True, "groups": _cache["groups"], "total": _cache["total"]}
        return {"ok": False, "groups": [], "total": 0}
    groups = _build_groups(text)
    total = sum(len(g["articles"]) for g in groups)
    if not total:
        return {"ok": False, "groups": [], "total": 0}
    _cache.update(ts=now, groups=groups, total=total)
    return {"ok": True, "groups": groups, "total": total}
