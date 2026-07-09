"""
Norma Express — API + frontend.

Endpoint:
  GET  /                     -> frontend
  GET  /api/health           -> stato
  POST /api/ricerca          -> { query } oppure { tipo, numero, anno, articolo }
                                risponde con articolo Normattiva + interpretazioni +
                                giurisprudenza (ricerca web reale) + link banche dati.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import enrich
import lawref
import search
from normattiva import fetch_article, fetch_index, resolve_law

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Norma Express", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class Query(BaseModel):
    query: Optional[str] = None
    tipo: Optional[str] = None
    numero: Optional[str] = None
    anno: Optional[str] = None
    articolo: Optional[str] = None


class EnrichReq(BaseModel):
    query: str = ""
    interp_urls: list = []
    giuri_urls: list = []


class DomandaReq(BaseModel):
    query: str = ""      # contesto: etichetta articolo (es. "Art. 2043 c.c.")
    domanda: str = ""


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "norma-express"}


@app.post("/api/ricerca")
def ricerca(q: Query):
    # 1) Determina il riferimento normativo
    ref = None
    if q.tipo:
        ref = lawref.from_fields(q.tipo, q.numero or "", q.anno or "", q.articolo or "")
    if ref is None and q.query:
        ref = lawref.parse(q.query)

    label = ref.label if ref else (q.query or "").strip()
    if not label:
        return {"ok": False, "error": "Inserisci un articolo di legge o una richiesta."}

    # 2) In parallelo: articolo (Normattiva) + interpretazione + giurisprudenza (web)
    free_terms = (q.query or "") if (q.query and ref and ref.articolo) else (q.query or "")
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_art = ex.submit(fetch_article, ref) if ref else None
        f_int = ex.submit(search.interpretazione, label, free_terms)
        f_giu = ex.submit(search.giurisprudenza, label, free_terms)

        article = None
        if f_art is not None:
            a = f_art.result()
            article = {
                "ok": a.ok, "query_label": a.query_label, "act_title": a.act_title,
                "article_heading": a.article_heading, "text": a.text,
                "in_force_from": a.in_force_from, "permalink": a.permalink,
                "updates": a.updates, "error": a.error,
                "abrogato": a.abrogato, "versions": a.versions,
            }
        interpretazioni = f_int.result()
        giurisprudenza = f_giu.result()

    return {
        "ok": True,
        "label": label,
        "reference_found": ref is not None,
        "search_provider": search.provider_status(),
        "article": article,
        "interpretazioni": interpretazioni,
        "giurisprudenza": giurisprudenza,
        "banche_dati": search.deep_links(label),
        "disclaimer": "Interpretazioni e giurisprudenza provengono da ricerche web su fonti "
                      "terze e vanno verificate. Il testo dell'articolo e' tratto da Normattiva. "
                      "Questo strumento non costituisce parere legale.",
    }


def _resolve_ref(q: Query):
    ref = None
    if q.tipo:
        ref = lawref.from_fields(q.tipo, q.numero or "", q.anno or "", q.articolo or "")
    if ref is None and q.query:
        ref = lawref.parse(q.query)
    label = ref.label if ref else (q.query or "").strip()
    return ref, label


def _index_payload(idx):
    return {"ok": idx.ok, "act_title": idx.act_title, "label": idx.label,
            "permalink": idx.permalink, "groups": idx.groups, "total": idx.total,
            "error": idx.error}


@app.post("/api/articolo")
def articolo(q: Query):
    """Articolo preciso, OPPURE indice della legge se la ricerca e' per parole chiave."""
    ref, label = _resolve_ref(q)
    if not label:
        return {"ok": False, "error": "Inserisci un articolo di legge o una richiesta."}

    # 1) Riferimento con articolo -> il testo dell'articolo
    if ref and ref.articolo:
        a = fetch_article(ref)
        article = {
            "ok": a.ok, "query_label": a.query_label, "act_title": a.act_title,
            "article_heading": a.article_heading, "text": a.text,
            "in_force_from": a.in_force_from, "permalink": a.permalink,
            "updates": a.updates, "error": a.error,
            "abrogato": a.abrogato, "versions": a.versions,
        }
        return {"ok": True, "mode": "article", "label": label,
                "reference_found": True, "article": article}

    # 2) Legge senza articolo, o parola chiave -> INDICE / voci della legge
    law = ref or resolve_law(q.query or label)
    if law:
        idx = fetch_index(law)
        if idx.ok:
            return {"ok": True, "mode": "index", "label": idx.label,
                    "reference_found": True, "index": _index_payload(idx)}

    # 3) Nessuna legge individuata -> solo ricerca web (interpretazione/giurisprudenza)
    return {"ok": True, "mode": "none", "label": label,
            "reference_found": False, "article": None}


@app.post("/api/fonti")
def fonti(q: Query):
    """Interpretazioni + giurisprudenza (ricerca web su fonti gratuite)."""
    ref, label = _resolve_ref(q)
    if not label:
        return {"ok": False, "error": "Inserisci un articolo di legge o una richiesta."}
    free_terms = q.query or ""
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_int = ex.submit(search.interpretazione, label, free_terms)
        f_giu = ex.submit(search.giurisprudenza, label, free_terms)
        interpretazioni = f_int.result()
        giurisprudenza = f_giu.result()
    return {
        "ok": True, "label": label,
        "search_provider": search.provider_status(),
        "interpretazioni": interpretazioni,
        "giurisprudenza": giurisprudenza,
        "banche_dati": search.deep_links(label),
        "disclaimer": "Interpretazioni e giurisprudenza provengono da ricerche web su fonti "
                      "gratuite e vanno verificate. Il testo dell'articolo e' tratto da "
                      "Normattiva. Questo strumento non costituisce parere legale.",
    }


@app.post("/api/istituzionali")
def istituzionali(q: Query):
    """Contesto separato: Gazzetta Ufficiale, lavori parlamentari (proposte di
    legge) e motore federato regionale di Normattiva. Ricerca web keyless per
    contesto, con link ai portali ufficiali."""
    query = (q.query or "").strip()
    if not query:
        return {"ok": False, "error": "Inserisci una parola chiave o un riferimento."}
    with ThreadPoolExecutor(max_workers=3) as ex:
        fg = ex.submit(search.gazzetta_ufficiale, query)
        fp = ex.submit(search.parlamento, query)
        fr = ex.submit(search.regionale, query)
        return {
            "ok": True, "query": query,
            "gazzetta": fg.result(),
            "parlamento": fp.result(),
            "regionale": fr.result(),
            "disclaimer": "Risultati da ricerca web su portali istituzionali, da "
                          "verificare sulle fonti ufficiali. Non costituisce parere legale.",
        }


@app.post("/api/riassunti")
def riassunti(req: EnrichReq):
    """Sintesi unica estrattiva (interpretazione + giurisprudenza) + massime Brocardi."""
    return enrich.enrich(req.query, req.interp_urls, req.giuri_urls)


@app.post("/api/domanda")
def domanda(req: DomandaReq):
    """Risposta ESTRATTIVA a una domanda: cerca sul web (fonti gratuite), estrae i
    passaggi piu' pertinenti alla domanda e rimanda alle fonti. Nessuna generazione AI."""
    dom = (req.domanda or "").strip()
    if not dom:
        return {"ok": False, "error": "Scrivi una domanda."}
    ctx = (req.query or "").strip()
    hits = search.web_search(f"{ctx} {dom}".strip(), 6)
    urls = [h["url"] for h in hits]
    risposta = enrich.unified_summary(urls, dom, max_sentences=7, max_chars=1200)
    fonti = [{"title": h["title"], "url": h["url"], "source": h["source"],
              "trusted": h["trusted"]} for h in hits]
    return {"ok": True, "risposta": risposta, "fonti": fonti}


# --- Frontend statico (montato per ultimo cosi' le API hanno precedenza) ---
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND)), name="assets")

    @app.get("/")
    def index():
        return FileResponse(str(FRONTEND / "index.html"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
