"""
Parsing di riferimenti normativi da testo libero e costruzione dell'URN Normattiva.

Riconosce forme come:
  - "art. 1 legge 241/1990"
  - "articolo 7 d.lgs 196 del 2003"
  - "art 2043 codice civile" / "art 2043 c.c."
  - "l. 300/1970 art 18"
Restituisce un LawRef con tipo/numero/anno/articolo e l'URN Normattiva.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# Mappa tipo-atto -> token URN Normattiva
URN_TYPES = {
    "legge": "stato:legge",
    "decreto legislativo": "stato:decreto.legislativo",
    "decreto-legge": "stato:decreto.legge",
    "dpr": "stato:decreto.del.presidente.della.repubblica",
    "regio decreto": "stato:regio.decreto",
    "costituzione": "stato:costituzione",
}

# Codici italiani -> (tipo, anno, numero) dell'atto istitutivo su Normattiva
CODES = {
    "codice civile": ("regio decreto", 1942, 262),
    "codice penale": ("regio decreto", 1930, 1398),
    "codice di procedura civile": ("regio decreto", 1940, 1443),
    "codice di procedura penale": ("dpr", 1988, 447),
}

# Alias testuali -> tipo canonico
TYPE_ALIASES = [
    (r"\bd\.?\s*lgs\.?\b|\bdecreto\s+legislativo\b|\bd\.?\s*legisl", "decreto legislativo"),
    (r"\bd\.?\s*l\.?\b(?!gs)|\bdecreto[-\s]legge\b", "decreto-legge"),
    (r"\bd\.?\s*p\.?\s*r\.?\b|\bdecreto\s+del\s+presidente\s+della\s+repubblica\b", "dpr"),
    (r"\br\.?\s*d\.?\b|\bregio\s+decreto\b", "regio decreto"),
    (r"\bcostituzione\b|\bcost\.?\b", "costituzione"),
    (r"\bl\.?\b|\blegge\b", "legge"),
]

# Alias codici (piu specifici prima)
CODE_ALIASES = [
    (r"\bcodice\s+di\s+procedura\s+civile\b|\bc\.?\s*p\.?\s*c\.?\b", "codice di procedura civile"),
    (r"\bcodice\s+di\s+procedura\s+penale\b|\bc\.?\s*p\.?\s*p\.?\b", "codice di procedura penale"),
    (r"\bcodice\s+civile\b|\bc\.?\s*c\.?\b", "codice civile"),
    (r"\bcodice\s+penale\b|\bc\.?\s*p\.?\b", "codice penale"),
]


@dataclass
class LawRef:
    tipo: str                     # tipo canonico (es. "legge")
    numero: Optional[int]         # numero atto (None per costituzione)
    anno: Optional[int]           # anno atto
    articolo: Optional[str]       # numero articolo come stringa (es. "2043", "2-bis")
    label: str = ""               # etichetta leggibile
    permalink_url: Optional[str] = None  # permalink Normattiva risolto (fallback)

    def urn(self) -> Optional[str]:
        token = URN_TYPES.get(self.tipo)
        if not token:
            return None
        if self.tipo == "costituzione":
            base = f"urn:nir:{token}:1947-12-27"
        else:
            if self.numero is None or self.anno is None:
                return None
            base = f"urn:nir:{token}:{self.anno};{self.numero}"
        if self.articolo:
            art = re.sub(r"[^0-9a-z]", "", self.articolo.lower())
            base += f"~art{art}"
        return base

    def permalink(self) -> Optional[str]:
        u = self.urn()
        if u:
            return f"https://www.normattiva.it/uri-res/N2Ls?{u}"
        return self.permalink_url  # atto risolto per keyword con token URN atipico

    def short(self) -> str:
        """Riferimento breve per costruire query per-articolo (es. 'legge 354/1975')."""
        names = {"legge": "legge", "decreto legislativo": "dlgs",
                 "decreto-legge": "decreto-legge", "dpr": "dpr",
                 "regio decreto": "regio decreto"}
        kw = names.get(self.tipo, "legge")
        if self.numero and self.anno:
            return f"{kw} {self.numero}/{self.anno}"
        return self.label


def _find_article(text: str) -> Optional[str]:
    m = re.search(r"\bart(?:icolo|\.)?\s*\.?\s*(\d+)\s*(?:[-\s]?(bis|ter|quater|quinquies|sexies|septies|octies))?",
                  text, re.I)
    if not m:
        return None
    art = m.group(1)
    if m.group(2):
        art += "-" + m.group(2).lower()
    return art


def _find_number_year(text: str):
    """Estrae numero/anno da forme '241/1990', '241 del 1990', 'n. 196 2003'."""
    # numero/anno con slash
    m = re.search(r"\bn?\.?\s*(\d{1,5})\s*/\s*(\d{4})\b", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # "241 del 1990" o "n. 196 ... 2003"
    m = re.search(r"\bn?\.?\s*(\d{1,5})\b(?:\s+del)?\s+(?:.*?)(\b(?:19|20)\d{2})\b", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def parse(query: str) -> Optional[LawRef]:
    """Estrae un riferimento normativo dal testo libero. None se non trovato."""
    q = " " + query.strip().lower() + " "
    articolo = _find_article(q)

    # 1) Codici (hanno atto fisso, ma serve comunque l'articolo)
    for pattern, code in CODE_ALIASES:
        if re.search(pattern, q):
            tipo, anno, numero = CODES[code]
            return LawRef(tipo=tipo, numero=numero, anno=anno, articolo=articolo,
                          label=_label(code, None, None, articolo))

    # 2) Costituzione
    if re.search(r"\bcostituzione\b|\bcost\.?\b", q):
        return LawRef(tipo="costituzione", numero=None, anno=None, articolo=articolo,
                      label=_label("Costituzione", None, None, articolo))

    # 3) Atti con numero/anno
    numero, anno = _find_number_year(q)
    if numero and anno:
        tipo = "legge"
        for pattern, canonical in TYPE_ALIASES:
            if re.search(pattern, q):
                tipo = canonical
                break
        return LawRef(tipo=tipo, numero=numero, anno=anno, articolo=articolo,
                      label=_label(tipo, numero, anno, articolo))

    return None


# Leggi note per nome comune -> (tipo, numero, anno). Risoluzione istantanea
# per parole chiave frequenti (il resto passa dal fallback web su normattiva.it).
KNOWN_LAWS = [
    (r"ordinamento penitenziario", ("legge", 354, 1975)),
    (r"statuto (dei|del)? ?lavoratori", ("legge", 300, 1970)),
    (r"legge sul procedimento amministrativo|procedimento amministrativo", ("legge", 241, 1990)),
    (r"codice della strada", ("decreto legislativo", 285, 1992)),
    (r"codice del consumo", ("decreto legislativo", 206, 2005)),
    (r"codice (della )?privacy", ("decreto legislativo", 196, 2003)),
    (r"codice del processo amministrativo", ("decreto legislativo", 104, 2010)),
    (r"codice dell'?ambiente|testo unico ambientale", ("decreto legislativo", 152, 2006)),
    (r"codice antimafia", ("decreto legislativo", 159, 2011)),
    (r"testo unico (sull'?)?immigrazione", ("decreto legislativo", 286, 1998)),
    (r"testo unico (sugli|degli)? ?stupefacenti", ("dpr", 309, 1990)),
    (r"testo unico edilizia", ("dpr", 380, 2001)),
    (r"testo unico bancario|\btub\b", ("decreto legislativo", 385, 1993)),
    (r"testo unico (della )?finanza|\btuf\b", ("decreto legislativo", 58, 1998)),
    (r"legge fallimentare", ("regio decreto", 267, 1942)),
    (r"legge biagi", ("decreto legislativo", 276, 2003)),
    (r"codice del turismo", ("decreto legislativo", 79, 2011)),
    (r"gdpr|regolamento generale.*protezione dei dati", ("regolamento_ue", 679, 2016)),
]

# Reverse: token URN autorita' -> tipo canonico
_URN_TOKEN_MAP = [
    ("decreto.legislativo", "decreto legislativo"),
    ("decreto.legge", "decreto-legge"),
    ("decreto.del.presidente.della.repubblica", "dpr"),
    ("presidente.repubblica:decreto", "dpr"),
    ("regio.decreto", "regio decreto"),
    ("legge", "legge"),
]


def resolve_known(query: str) -> Optional[LawRef]:
    """Se la query nomina una legge nota (senza numero), restituisce il LawRef."""
    q = (query or "").lower()
    for pattern, (tipo, numero, anno) in KNOWN_LAWS:
        if re.search(pattern, q):
            if tipo == "regolamento_ue":  # non su Normattiva: nessun indice
                return None
            return LawRef(tipo=tipo, numero=numero, anno=anno, articolo=None,
                          label=_label(tipo, numero, anno, None))
    return None


def from_urn(urn: str, permalink_url: Optional[str] = None) -> Optional[LawRef]:
    """Costruisce un LawRef da un URN Normattiva (es. risolto via ricerca web)."""
    m = re.search(r"urn:nir:(.+?):(\d{4})(?:-\d{2}-\d{2})?;(\d+)", urn)
    if not m:
        return None
    token, anno, numero = m.group(1), int(m.group(2)), int(m.group(3))
    tipo = "legge"
    for frag, canonical in _URN_TOKEN_MAP:
        if frag in token:
            tipo = canonical
            break
    ref = LawRef(tipo=tipo, numero=numero, anno=anno, articolo=None,
                 label=_label(tipo, numero, anno, None), permalink_url=permalink_url)
    return ref


def from_fields(tipo: str, numero: str, anno: str, articolo: str) -> Optional[LawRef]:
    """Costruisce un LawRef dai campi del form strutturato."""
    tipo = (tipo or "").strip().lower()
    if tipo not in URN_TYPES:
        return None
    n = int(numero) if str(numero).strip().isdigit() else None
    a = int(anno) if str(anno).strip().isdigit() else None
    art = re.sub(r"^\s*art\.?\s*", "", str(articolo or "").strip(), flags=re.I) or None
    if tipo != "costituzione" and (n is None or a is None):
        return None
    return LawRef(tipo=tipo, numero=n, anno=a, articolo=art,
                  label=_label(tipo, n, a, art))


def _label(tipo, numero, anno, articolo) -> str:
    if tipo in CODES or tipo in ("codice civile", "codice penale",
                                 "codice di procedura civile", "codice di procedura penale"):
        base = tipo.title()
    elif tipo == "costituzione" or tipo == "Costituzione":
        base = "Costituzione"
    else:
        names = {
            "legge": "Legge",
            "decreto legislativo": "D.Lgs.",
            "decreto-legge": "D.L.",
            "dpr": "D.P.R.",
            "regio decreto": "R.D.",
        }
        base = names.get(tipo, tipo.title())
        if numero and anno:
            base += f" {numero}/{anno}"
    if articolo:
        base = f"Art. {articolo} — {base}"
    return base
