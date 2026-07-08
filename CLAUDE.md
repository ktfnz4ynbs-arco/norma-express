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
  app.py         # FastAPI: /api/ricerca, /api/riassunti (+ /api/health) e serve il frontend
  lawref.py      # parsing riferimento normativo (testo libero o campi) → URN Normattiva
  normattiva.py  # recupero testo articolo da Normattiva (+ flag abrogato, n. versioni)
  search.py      # ricerca web: Brave(opz.) → Startpage(keyless) → DuckDuckGo → deep-link
  enrich.py      # riassunti ESTRATTIVI dalle fonti + Brocardi (Spiegazione/Massime)
frontend/        # index.html, style.css, app.js  (montato su /assets, index su /)
```

## Riassunti dalle fonti (`enrich.py` + `/api/riassunti`)
Meccanismo stile RegTech (Aptus.AI/Daitomic) ma **estrattivo, mai generativo**: frasi reali
prese dalla pagina fonte, selezionate per pertinenza (scoring keyword), max ~420 char,
sempre con link "Approfondisci alla fonte →". Il frontend chiama `/api/riassunti` DOPO aver
mostrato i risultati (progressive enhancement: prima i link, poi i riassunti).
- Caso speciale **brocardi.it** (pagina articolo `/artNNNN.html`): estrae la sezione
  "Spiegazione" (→ interpretazione) e le **Massime** in `div.sentenza.corpoDelTesto`
  (→ giurisprudenza, card verdi con estremi Cassazione). Attenzione all'encoding:
  impostare `r.encoding = r.apparent_encoding`.
- Frasi: proteggere le abbreviazioni giuridiche (art., Cass., n., …) prima dello split.
- Aptus-style nel risultato articolo: `abrogato` (badge rosso) e `versions` (multivigenza).

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
