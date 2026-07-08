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
from normattiva import fetch_article

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


@app.post("/api/articolo")
def articolo(q: Query):
    """Solo l'articolo da Normattiva: risposta rapida, mostrata per prima."""
    ref, label = _resolve_ref(q)
    if not label:
        return {"ok": False, "error": "Inserisci un articolo di legge o una richiesta."}
    article = None
    if ref:
        a = fetch_article(ref)
        article = {
            "ok": a.ok, "query_label": a.query_label, "act_title": a.act_title,
            "article_heading": a.article_heading, "text": a.text,
            "in_force_from": a.in_force_from, "permalink": a.permalink,
            "updates": a.updates, "error": a.error,
            "abrogato": a.abrogato, "versions": a.versions,
        }
    return {"ok": True, "label": label, "reference_found": ref is not None,
            "article": article}


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


@app.post("/api/riassunti")
def riassunti(req: EnrichReq):
    """Riassunti estrattivi dalle fonti (frasi reali, tracciabili) + massime Brocardi."""
    return enrich.enrich(req.query, req.interp_urls, req.giuri_urls)


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
