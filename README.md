# Norma Express

Ricerca giuridica rapida. Da un **articolo di legge** o da una **richiesta libera** ottieni in pochi secondi:

1. **Testo ufficiale dell'articolo** — tratto da **Normattiva** (fonte ufficiale, versione in vigore).
2. **Interpretazione giuridica** — risultati da ricerca web su fonti dottrinali, con link verificabili.
3. **Giurisprudenza** — sentenze/massime da ricerca web + link diretti alle banche dati ufficiali.

> ⚖️ Strumento informativo. Interpretazioni e giurisprudenza provengono da fonti terze e **vanno verificate**. Non costituisce parere legale.

---

## Architettura

```
norma-express/
├── backend/
│   ├── app.py          # FastAPI: API + serve il frontend
│   ├── lawref.py       # parsing del riferimento normativo → URN Normattiva
│   ├── normattiva.py   # recupero testo articolo da Normattiva
│   └── search.py       # ricerca web (Brave API → DuckDuckGo → deep-link)
├── frontend/           # UI statica (HTML/CSS/JS, nessun build step)
├── requirements.txt
├── Procfile            # comando web per il deploy
├── railway.json        # config deploy Railway
└── .python-version     # Python 3.11
```

### Fonti dei dati
| Sezione | Fonte | Affidabilità |
|---|---|---|
| Articolo | Normattiva (`normattiva.it`) | Ufficiale |
| Interpretazione / Giurisprudenza | Ricerca web (Startpage/DuckDuckGo, **solo fonti gratuite**) con riassunti estrattivi | Fonti terze, da verificare |
| Banche dati (link) | Cassazione/ItalgiureWeb, Corte Costituzionale, Google Scholar, Brocardi | Gratuite, sempre disponibili |

---

## Avvio in locale

```bash
cd norma-express
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app:app --app-dir backend --port 8077
# apri http://127.0.0.1:8077
```

---

## Ricerca web affidabile (consigliato per la produzione)

I motori scrapati (DuckDuckGo) **bloccano spesso gli IP dei datacenter** come quelli di
Railway: in produzione la ricerca di interpretazioni/giurisprudenza potrebbe restare vuota
(l'app mostra comunque i link alle banche dati ufficiali come fallback).

Per una ricerca web stabile, usa la **Brave Search API** (free tier: 2000 query/mese, gratis):

1. Crea una chiave gratuita su <https://brave.com/search/api/>.
2. Imposta la variabile d'ambiente `BRAVE_API_KEY`.

L'app usa automaticamente Brave se la chiave è presente, altrimenti ripiega su DuckDuckGo.

---

## Deploy su Railway

1. Crea un repo Git e collegalo a Railway (New Project → Deploy from GitHub repo).
2. Railway rileva `requirements.txt` (Nixpacks) e avvia il comando in `railway.json`.
3. (Consigliato) In **Variables** aggiungi `BRAVE_API_KEY` = la tua chiave.
4. Deploy. L'app espone `/` (frontend) e `/api/ricerca` (API).

Comando di avvio (già configurato):
```
uvicorn app:app --host 0.0.0.0 --port $PORT --app-dir backend
```

---

## API

`POST /api/ricerca`

```jsonc
// Ricerca libera
{ "query": "art. 1 legge 241/1990" }

// Ricerca strutturata
{ "tipo": "legge", "numero": "241", "anno": "1990", "articolo": "1" }
```

Tipi supportati: `legge`, `decreto legislativo`, `decreto-legge`, `dpr`, `regio decreto`.
Riconosce anche i codici in testo libero (es. `art 2043 codice civile`, `art 18 c.p.`).
