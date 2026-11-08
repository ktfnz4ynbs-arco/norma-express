"""
Registro degli atti con pagine server-rendered: slug <-> LawRef.

Un solo URL per articolo: /{slug-atto}/art-{numero}[-{suffisso}]
  /codice-civile/art-2043      /codice-penale/art-416-bis      /costituzione/art-21

- Atti del CATALOGO (slug leggibile, in sitemap): i quattro codici + Costituzione.
- Qualsiasi altro atto: slug numerico (legge-241-1990, dlgs-196-2003, dl-18-2020,
  dpr-380-2001, rd-267-1942). Pagina servita, non in sitemap.
Gli slug, una volta pubblicati, non si cambiano: Google li ha gia' indicizzati.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

import lawref
from lawref import LawRef

# Suffissi latini degli articoli inseriti (art. 2-bis, 25-duodecies, ...).
# Ordine: dal piu' lungo, perche' "ter" non mangi "terdecies".
LATINI = sorted("""bis ter quater quinquies sexies septies octies novies nonies decies
undecies duodecies terdecies quaterdecies quinquiesdecies sexiesdecies septiesdecies
octiesdecies duodevicies novesdecies undevicies vicies""".split(), key=len, reverse=True)
_ART_RE = re.compile(r"^(\d{1,5})(?:[-\s]?(" + "|".join(LATINI) + r"))?$")


@dataclass(frozen=True)
class Atto:
    slug: str
    nome: str           # "Codice civile"
    abbr: str           # "c.c."  -> title e breadcrumb
    ref: LawRef         # senza articolo
    in_sitemap: bool = True

    def ref_articolo(self, articolo: str) -> LawRef:
        return replace(self.ref, articolo=articolo,
                       label=f"Art. {articolo} {self.abbr}")

    def query(self, articolo: str) -> str:
        """Ricerca equivalente in testo libero (per /api/fonti nella SPA)."""
        return f"art {articolo} {self.nome.lower()}"


def _codice(slug, nome, abbr, chiave) -> Atto:
    tipo, anno, numero, allegato = lawref.CODES[chiave]
    return Atto(slug, nome, abbr,
                LawRef(tipo=tipo, numero=numero, anno=anno, articolo=None,
                       allegato=allegato, label=nome))


CATALOGO: dict[str, Atto] = {a.slug: a for a in [
    _codice("codice-civile", "Codice civile", "c.c.", "codice civile"),
    _codice("codice-penale", "Codice penale", "c.p.", "codice penale"),
    _codice("codice-procedura-civile", "Codice di procedura civile", "c.p.c.",
            "codice di procedura civile"),
    _codice("codice-procedura-penale", "Codice di procedura penale", "c.p.p.",
            "codice di procedura penale"),
    Atto("costituzione", "Costituzione", "Cost.",
         LawRef(tipo="costituzione", numero=None, anno=None, articolo=None,
                label="Costituzione")),
]}

# Alias -> slug canonico (risposta 301)
ALIAS = {"cc": "codice-civile", "cp": "codice-penale", "cpc": "codice-procedura-civile",
         "cpp": "codice-procedura-penale", "cost": "costituzione",
         "codice-di-procedura-civile": "codice-procedura-civile",
         "codice-di-procedura-penale": "codice-procedura-penale"}

# Slug numerici: prefisso <-> tipo LawRef
_PREFISSI = {"legge": "legge", "dlgs": "decreto legislativo", "dl": "decreto-legge",
             "dpr": "dpr", "rd": "regio decreto"}
_TIPO_PREF = {v: k for k, v in _PREFISSI.items()}
_NUM_SLUG = re.compile(r"^(" + "|".join(_PREFISSI) + r")-(\d{1,5})-(\d{4})$")
_ABBR_TIPO = {"legge": "L.", "decreto legislativo": "D.Lgs.", "decreto-legge": "D.L.",
              "dpr": "D.P.R.", "regio decreto": "R.D."}


def norm_articolo(s: str) -> Optional[str]:
    """'2043' -> '2043'; '2-bis', '2bis', '2 bis', '2-BIS' -> '2-bis'. None se non valido."""
    m = _ART_RE.match((s or "").strip().lower())
    if not m:
        return None
    return m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")


def atto_da_slug(slug: str) -> Optional[Atto]:
    """Atto per slug canonico (catalogo o numerico). Gli alias NON sono risolti qui."""
    if slug in CATALOGO:
        return CATALOGO[slug]
    m = _NUM_SLUG.match(slug)
    if not m:
        return None
    tipo, numero, anno = _PREFISSI[m.group(1)], int(m.group(2)), int(m.group(3))
    nome = f"{_ABBR_TIPO[tipo]} {numero}/{anno}"
    return Atto(slug, nome, nome,
                LawRef(tipo=tipo, numero=numero, anno=anno, articolo=None, label=nome),
                in_sitemap=False)


def canonico(slug: str) -> Optional[str]:
    """Slug canonico per uno slug richiesto (minuscolo, alias, atti del catalogo)."""
    s = (slug or "").strip().lower()
    s = ALIAS.get(s, s)
    a = atto_da_slug(s)
    if not a:
        return None
    # Uno slug numerico che coincide con un atto del catalogo -> slug leggibile
    for c in CATALOGO.values():
        if (c.ref.tipo, c.ref.numero, c.ref.anno) == (a.ref.tipo, a.ref.numero, a.ref.anno) \
                and not c.ref.allegato:
            return c.slug
    return s


def slug_di(ref: LawRef) -> Optional[str]:
    """Inverso: LawRef (anche con articolo) -> slug dell'atto, o None."""
    for a in CATALOGO.values():
        r = a.ref
        if (r.tipo, r.numero, r.anno, r.allegato) == (ref.tipo, ref.numero, ref.anno,
                                                       ref.allegato):
            return a.slug
    pref = _TIPO_PREF.get(ref.tipo)
    if pref and ref.numero and ref.anno and not ref.allegato:
        return f"{pref}-{ref.numero}-{ref.anno}"
    return None


def path_articolo(slug: str, articolo: str) -> str:
    return f"/{slug}/art-{articolo}"
