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

## Banche dati interrogate per dominio (2026-11-04)
Prima la giurisprudenza veniva da **una sola ricerca generica**: che comparissero
Cassazione o Consulta era questione di fortuna, `TRUSTED` si limitava a riordinare cio'
che il motore aveva gia' restituito. E i deep-link a Cassazione/Consulta **buttavano via
la query**, scaricando sull'utente il compito di ridigitare tutto in un form vuoto.

- `search.BANCHE` + `banche_dati(label, extra)`: ogni fonte (Cassazione: italgiure +
  cortedicassazione · Consulta: cortecostituzionale + giurcost · Gazzetta Ufficiale ·
  Brocardi) e' interrogata con una ricerca **ristretta al suo dominio** (`site:`), in
  parallelo. Risultato: blocchi **attribuibili** a chi li ha emessi. Esposti in
  `/api/fonti` come `banche_dati_risultati` (le chiavi vecchie restano intatte).
- **Nessuno scraping dei portali**: si passa sempre dai provider gia' in uso, che reggono
  i blocchi anti-bot molto meglio di un client nostro verso siti (Italgiure in primis)
  notoriamente ostili. Il filtro per dominio si applica comunque ai risultati, perche'
  l'operatore `site:` non e' onorato allo stesso modo da tutti i motori.
- ⚠️ **Trappola**: i provider deduplicavano **per dominio** → una ricerca `site:` avrebbe
  restituito **un solo risultato**. Aggiunto `dedupe="url"` a `_brave`/`_ddg`/`_startpage`
  e a `web_search`. Non rimuoverlo.
- `deep_links()` ora include, per ogni banca dati, un link che **porta con se' la query**
  (motore + operatore `site:`, forma di URL stabile) oltre al portale ufficiale.
- Un blocco **senza risultati non sparisce**: resta coi suoi link, cosi' si vede che la
  fonte e' stata interrogata e non dimenticata.

## Genesi della norma: contesto separato richiamato quando serve (2026-11-04)
Richiesta utente: distinguere **disegno di legge · lavori preparatori · emendamenti ·
legge approvata**, in un contesto a parte che si apra quando l'argomento lo merita
(ratio della norma, differenze con la disciplina previgente, applicazione di una norma
nuova).

- `search.FASI_ITER` + `iter_parlamentare()`: una ricerca per **fase**, su camera.it e
  senato.it (la fase "legge approvata" guarda anche GU e Normattiva). La vecchia
  `parlamento()` faceva una ricerca indistinta e resta per `/api/istituzionali`.
- `POST /api/lavori` = il contesto separato. **Non si apre ad ogni ricerca**: `/api/fonti`
  restituisce `genesi.motivi` e il frontend mostra la card solo se la lista non e' vuota;
  gli atti si caricano al clic.
- `motivi_genesi()` decide **senza AI**, da segnali osservabili: parole della domanda
  (ratio/perche'/finalita' · differenze/riforma/previgente · applicazione/decorrenza),
  norma **recente** (≤3 anni), `versioni>1`, `abrogato`. Lista vuota = card chiusa.
- ⚠️ **Trappola (bug trovato dai test)**: i numeri di articolo collidono con gli anni —
  "art. 2043 c.c." veniva letto come l'anno 2043 e marcato "norma recente". `_ART_RE`
  toglie prima il riferimento all'articolo e `_ANNO_RE` riconosce l'anno **solo** dove e'
  davvero tale (dopo la barra, "241/1990", o in una data). C'e' un test di regressione.
- Frontend: card `#card-banche` (blocchi per fonte) e `#card-genesi` (motivi + pulsante
  che carica le fasi).

## Test (`backend/test_banche.py`)
18 test **senza rete**: i provider sono sostituiti con una finta SERP, cosi' la logica
(deduplica, restrizione al dominio, attribuzione, degrado a vuoto, trigger della genesi)
e' verificabile in modo deterministico.
```bash
.venv/bin/python backend/test_banche.py     # oppure: python3 -m pytest backend/test_banche.py -q
```
⚠️ I **domini giuridici e i motori di ricerca sono bloccati** nell'ambiente di sviluppo
Claude Code (proxy: 403 su CONNECT). Qui i risultati sono sempre vuoti **per progetto**:
la resa reale si verifica solo sul deploy Railway o da una macchina con rete libera.

## Decisioni chiave (fissate con l'utente)
- **Niente generazione AI** delle interpretazioni: solo ricerca web reale con link, per
  evitare citazioni giurisprudenziali inventate. Non introdurre chiamate a LLM per questo.
- Testo articoli **solo da Normattiva** (leggi/decreti; i codici funzionano via regio decreto).
- Ricerca web con catena di fallback (vedi sotto).

## Correttezza codici + multivigenza (da avvocati-e-mac/skill-legali, 2026-07-09)
- **Codici = allegati numerati di R.D.**: `LawRef.allegato` (c.c.=2, c.p.c./c.p./l.fall.=1).
  L'URN include `:{allegato}` e `_pick_article_link` filtra per `flagTipoArticolo={allegato}`
  (0=corpo atto). SENZA questo, gli articoli a numero basso risolvono nel preambolo del R.D.
  (bug storico: art.1 c.c. dava "approvazione del testo" invece di "Capacità giuridica").
- **Multivigenza `!vig=AAAA-MM-GG`**: `LawRef.vigenza` (parsata da "al 6/3/2015", "vigente al
  2022"). L'ESTRAZIONE resta il testo vigente; il frontend offre un controllo data
  ("Testo a una data") che apre `permalink + !vig=data` su Normattiva (versione storica).
- **Lookup esteso**: `KNOWN_LAWS` e `CODES` coprono cod. crisi 14/2019, contratti pubblici
  36/2023, assicurazioni, TUEL, TUIR, pubblico impiego 165/2001, jobs act, 231/2001, 81/2008,
  l.fall., cod. navigazione. `URN_TYPES` include dpcm e legge costituzionale.

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
3. **Deep-link banche dati GRATUITE** (Cassazione/ItalgiureWeb, Corte Costituzionale,
   Google Scholar, Brocardi) — sempre presenti nella risposta.

**VINCOLO UTENTE (2026-07-08): niente servizi a pagamento.** `search.py::BLOCK` esclude
Giuffrè/DeJure, Altalex, Leggi d'Italia, Wolters Kluwer, Sole 24 Ore, Giappichelli, ecc.
Non aggiungere fonti paywall nei risultati né nelle banche dati.

**Flusso UI (vincolo utente): prima l'articolo, poi il resto.** Il frontend chiama in
sequenza: `/api/articolo` (rapido, solo Normattiva → card articolo subito) →
`/api/fonti` (ricerca web) → `/api/riassunti`. `/api/ricerca` resta per compatibilità.

**Ricerca per parole chiave → INDICE della legge (vincolo utente 2026-07-08).** Se la query
non individua un articolo preciso, `/api/articolo` risponde con `mode:"index"`: risolve la
legge (`lawref.resolve_known` mappa curata `KNOWN_LAWS` → fallback `search.normattiva_url`
via Startpage → `lawref.from_urn`) e `normattiva.fetch_index` estrae l'albero Normattiva
(partizioni Titoli/Capi + numeri articolo dai link `numero_articolo`, scartando versioni
storiche `agg./orig.` e il chrome di pagina). Il frontend mostra la **card Indice** con
chip-voci cliccabili; ogni voce porta una query `art N <legge>` che apre l'articolo.
Modi: `article` (ref con articolo) · `index` (legge senza articolo o keyword) · `none`.

**Fonti istituzionali (vincolo utente 2026-07-09) — CONTESTO SEPARATO.** Nav in alto
("Ricerca norma" | "Fonti istituzionali"). `POST /api/istituzionali` risponde con tre
blocchi: `gazzetta`, `parlamento`, `regionale`, ognuno `{results, portali}`. Implementati
in `search.py::_institutional(query, prefer, n)` = ricerca web keyless (`_startpage`
`drop_docs=False` → la Gazzetta pubblica PDF ufficiali!) ri-ordinata per priorita' dei
domini del contesto (gazzettaufficiale.it; camera.it/senato.it; consigli/banche dati
regionali) senza escludere gli altri. `portali` = link ufficiali (GU; Camera "Progetti di
legge" leg19/126; Senato DDL iter; Normattiva `/legislazioneRegionale` = motore federato
regionale). Frontend: vista `#results-ist` con 3 card (`#gu-body`, `#parl-body`, `#reg-body`).

**Layout risultati (vincolo utente 2026-07-08):** 4 card in ordine —
1. **Articolo** (Normattiva).
2. **Sintesi "Interpretazione e giurisprudenza"**: UNA SOLA sintesi che fonde interpretazione
   + giurisprudenza di tutte le fonti. **VERIFICABILE (vincolo utente 2026-07-08):**
   `unified_summary` ritorna una LISTA di segmenti tracciabili `{text,url,source}`; il
   frontend mostra accanto a ogni passaggio una **citazione cliccabile `[n]`** collegata alla
   fonte (numero coerente con l'elenco "Fonti consultabili"). `enrich()` ritorna
   `{sintesi:[segmenti], brocardi{massime}}`. La pagina Brocardi grezza e' esclusa dal pool
   (rumore "Consulenze legali/Q-code"): la sua parte utile entra via `extra` (spiegazione).
   Sotto, le **Massime della Cassazione** (Brocardi).
3. **Fonti consultabili**: elenco combinato dei link (interp+giuri, deduplicati) + banche dati.
4. **Approfondisci con una domanda**: box Q&A → `POST /api/domanda {query,domanda}`. Risposta
   **ESTRATTIVA** (nessuna generazione AI): cerca sul web `label+domanda`, estrae con
   `unified_summary` i passaggi piu' pertinenti alla DOMANDA, e restituisce `{risposta, fonti[]}`
   con i rimandi. `_clean()` rimuove i marcatori-nota `(1)`/`[2058]` tipici di Brocardi.

**VINCOLO UTENTE (2026-07-08): mai contenuto illeggibile.** I PDF/documenti binari sono
esclusi dai risultati (`search.py::_DOC_RE`) e comunque scartati in `enrich.py`
(check Content-Type HTML, magic bytes `%PDF-`, euristica `_readable`). Se un risultato
resta senza riassunto né snippet, il frontend lo rimuove del tutto.

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
