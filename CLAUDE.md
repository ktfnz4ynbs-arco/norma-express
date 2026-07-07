# CLAUDE.md — Norma Express

Contesto di progetto per sessioni Claude Code future. Leggere prima di modificare il codice.

## Cos'è
App di **ricerca giuridica rapida**. Da un **articolo di legge** (o una richiesta libera)
restituisce tre sezioni:
1. **Articolo** — testo ufficiale da **Normattiva** (versione in vigore).
2. **Interpretazione giuridica** — risultati da ricerca web reale, con link (nessuna AI).
3. **Giurisprudenza** — sentenze/massime da ricerca web + link diretti alle banche dati ufficiali.

> ⚖️ Strumento informativo, **non** parere legale. Interpretazioni/giurisprudenza sono
> fonti terze da verificare; solo il testo dell'articolo è ufficiale (Normattiva).

## Stack & struttura
- **Backend:** FastAPI + requests + BeautifulSoup (Python 3.11). Serve anche il frontend.
- **Frontend:** statico, `frontend/` (HTML/CSS/JS vanilla, nessun build step).
- **Deploy:** Railway (Nixpacks). Avvio: `uvicorn app:app --host 0.0.0.0 --port $PORT --app-dir backend`.

```
backend/
  app.py         # FastAPI: /api/ricerca (+ /api/health) e serve il frontend
  lawref.py      # parsing riferimento normativo (testo libero o campi) → URN Normattiva
  normattiva.py  # recupero testo articolo da Normattiva
  search.py      # ricerca web: Brave API → DuckDuckGo → deep-link banche dati
frontend/        # index.html, style.css, app.js  (montato su /assets, index su /)
```

## Decisioni chiave (fissate con l'utente)
- **Niente generazione AI** delle interpretazioni: solo ricerca web reale con link, per
  evitare citazioni giurisprudenziali inventate. Non introdurre chiamate a LLM per questo.
- Testo articoli **solo da Normattiva** (leggi/decreti; i codici funzionano via regio decreto).
- Ricerca web con catena di fallback (vedi sotto).

## Come funziona Normattiva (`normattiva.py`)
- URN: `urn:nir:stato:{tipo}:{anno};{numero}~art{N}` — funziona con **solo anno+numero**
  (non serve la data di promulgazione). Permalink: `https://www.normattiva.it/uri-res/N2Ls?<URN>`.
- Flusso: GET permalink con **sessione cookie** → dalla pagina si ricavano `codiceRedazionale`
  e `dataPubblicazioneGazzetta` e i link `caricaArticolo`. La versione **vigente** dell'articolo
  è quella **senza** `imUpdate=true`. GET di `caricaArticolo` → testo in `div.bodyTesto`
  (heading `.article-heading-akn`, vigenza `.vigore`).
- Gestisce articoli **abrogati** (mostra la nota "ARTICOLO ABROGATO…").

## Ricerca web (`search.py`) — ⚠️ punto delicato
Catena di provider:
1. **Brave Search API** se è impostata `BRAVE_API_KEY` (free tier 2000/mese). **Consigliato in
   produzione**: gli IP datacenter (Railway) vengono bloccati dai motori scrapati.
2. **DuckDuckGo HTML** (best-effort). Da IP datacenter torna spesso HTTP 202 "challenge" → 0 risultati.
3. **Deep-link banche dati** (Cassazione/ItalgiureWeb, Google Scholar, Brocardi, Altalex) —
   sempre presenti nella risposta, così l'utente non resta mai a mani vuote.

Se le liste web sono vuote il frontend mostra un empty-state + i deep-link. È il comportamento atteso.

## Frontend / design
Estetica "studio legale premium": hero gradiente **navy** con bagliore **oro**, icona bilancia,
wordmark serif **Fraunces** + body **Inter**, search card che fluttua sull'hero, card risultati
con icone/badge/pill, dark mode completo. **Mantenere questa direzione.**
`app.js` dipende dagli **ID** in `index.html` (`#q`, `#form-free`, `#form-struct`, `#art-title`,
`#art-body`, `#interp-list`, `#giuri-list`, `#banche-links`, …): non rinominarli senza aggiornare il JS.

## Avvio locale
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app:app --app-dir backend --port 8077
# http://127.0.0.1:8077
```

## API
`POST /api/ricerca`
```jsonc
{ "query": "art. 1 legge 241/1990" }                                  // libera
{ "tipo": "legge", "numero": "241", "anno": "1990", "articolo": "1" } // strutturata
```
Tipi: `legge`, `decreto legislativo`, `decreto-legge`, `dpr`, `regio decreto`.
Riconosce anche i codici in testo libero (`art 2043 codice civile`, `art 18 c.p.`).

## TODO / possibili estensioni
- Aggiungere la **Costituzione** nel form strutturato (il parsing la già supporta in testo libero).
- Cache dei risultati Normattiva.
- Ricerca per rubrica / per parola chiave nell'atto.
