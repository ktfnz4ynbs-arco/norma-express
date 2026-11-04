# Norma Express

Ricerca giuridica rapida. Da un **articolo di legge** o da una **richiesta in
lingua** si ottiene, in pochi secondi:

1. **Il testo ufficiale dell'articolo**, preso da **Normattiva** nella versione
   in vigore.
2. **Interpretazioni** e **giurisprudenza**, da ricerca web su fonti gratuite,
   sempre con il link alla fonte.
3. **Le banche dati interrogate una per una** — Cassazione, Corte
   Costituzionale, Gazzetta Ufficiale, Brocardi — ciascuna con la sua ricerca.
4. Quando serve, **la genesi della norma**: disegno di legge, lavori
   preparatori, emendamenti, legge approvata.

> ⚖️ Strumento informativo. Solo il testo dell'articolo è ufficiale; tutto il
> resto viene da fonti terze e **va verificato**. Non costituisce parere legale.

**Due regole che reggono il progetto:**

- **Nessuna generazione AI.** Interpretazioni e massime non vengono scritte da
  un modello: sono ricerca reale con link. È il modo più semplice per non
  ritrovarsi citazioni giurisprudenziali inesistenti.
- **Solo fonti gratuite.** Le banche dati a pagamento (Giuffrè/DeJure, Altalex,
  Leggi d'Italia, Wolters Kluwer, Sole 24 Ore, Giappichelli) sono escluse per
  scelta, in `search.py::BLOCK`.

---

## Le banche dati, interrogate per conto proprio

Prima la giurisprudenza veniva da **una sola ricerca generica**, e che tra i
risultati comparisse la Cassazione era questione di fortuna. Ora ogni fonte ha
la sua ricerca, ristretta ai suoi domini e lanciata in parallelo:

| Banca dati | Domini |
|---|---|
| Corte di Cassazione | `italgiure.giustizia.it`, `cortedicassazione.it` |
| Corte Costituzionale | `cortecostituzionale.it`, `giurcost.org` |
| Gazzetta Ufficiale | `gazzettaufficiale.it` |
| Brocardi | `brocardi.it` |

Un blocco **senza risultati non sparisce**: resta con il link al portale e alla
ricerca, così si vede che la fonte è stata interrogata e non dimenticata. E il
link di ricerca **porta con sé la query**, invece di aprire un form vuoto da
ricompilare.

I portali **non vengono scrapati**: si passa dai motori di ricerca già in uso,
che reggono le difese anti-bot molto meglio di un client nostro verso siti —
Italgiure in testa — notoriamente ostili. Il filtro per dominio viene comunque
riapplicato ai risultati, perché l'operatore `site:` non è onorato allo stesso
modo da tutti i motori.

## La genesi della norma, come contesto a parte

Perché una norma è stata scritta così, cosa cambia rispetto a prima, come si
applica: domande che hanno senso per una riforma recente e quasi mai per
l'art. 2043 del codice civile. Per questo **non si apre ad ogni ricerca**.

`motivi_genesi()` decide da segnali osservabili, senza modelli: le parole della
domanda (ratio, differenze con la disciplina precedente, applicazione), una
norma recente (≤ 3 anni), un testo stratificato (più versioni), una norma
abrogata. Se la lista dei motivi è vuota, la card non compare; se non lo è, i
motivi vengono mostrati in chiaro e gli atti si caricano al clic.

Le quattro fasi sono tenute distinte — **disegno di legge**, **lavori
preparatori**, **emendamenti**, **legge approvata** — perché chi cerca vuole
quasi sempre *una* di quelle, non il mucchio indistinto. Le prime tre su
`camera.it` e `senato.it`, l'ultima anche su Gazzetta Ufficiale e Normattiva.

---

## Architettura

```
norma-express/
├── backend/
│   ├── app.py          # FastAPI: API + serve il frontend
│   ├── lawref.py       # riferimento normativo (testo libero o campi) → URN Normattiva
│   ├── normattiva.py   # testo dell'articolo da Normattiva (+ abrogato, n. versioni)
│   ├── search.py       # ricerca web, banche dati, iter parlamentare
│   ├── enrich.py       # sintesi estrattive e massime
│   └── test_banche.py  # 18 test, senza rete
├── frontend/           # HTML/CSS/JS statici, nessun build step
├── .github/workflows/  # CI: i test su ogni push e PR
├── requirements.txt
├── Procfile · railway.json · .python-version
└── CLAUDE.md           # contesto per chi (o cosa) lavora sul codice
```

| Sezione | Fonte | Affidabilità |
|---|---|---|
| Testo dell'articolo | Normattiva | **Ufficiale** |
| Interpretazioni, giurisprudenza, banche dati, iter | Ricerca web su fonti gratuite, con riassunti estrattivi | Fonti terze, da verificare |
| Link ai portali | Cassazione, Consulta, Gazzetta Ufficiale, Brocardi, Camera, Senato | Sempre presenti, anche senza risultati |

---

## Avvio in locale

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app:app --app-dir backend --port 8077
# http://127.0.0.1:8077
```

## Test

```bash
.venv/bin/python backend/test_banche.py       # oppure: python3 -m pytest backend/test_banche.py -q
```

18 test che **non toccano la rete**: i motori di ricerca sono sostituiti con una
finta SERP, così deduplica, restrizione al dominio, attribuzione alla banca dati
giusta, degrado a vuoto e apertura della genesi si verificano in modo
deterministico, senza dipendere da cosa rispondono oggi i siti reali.

Girano in CI su ogni push e ogni pull request, insieme a un `import app` che
intercetta gli errori di sintassi che romperebbero il deploy senza che nessun
test se ne accorga.

---

## API

Tutte in `POST`, con lo stesso corpo: `{"query": "..."}` in lingua, oppure i
campi `{"tipo", "numero", "anno", "articolo"}`.

| Rotta | Cosa restituisce |
|---|---|
| `/api/ricerca` | Tutto insieme: articolo + interpretazioni + giurisprudenza. |
| `/api/articolo` | Il solo testo dell'articolo (o l'indice della legge, se la ricerca è per parole chiave). |
| `/api/fonti` | Interpretazioni, giurisprudenza, **banche dati per fonte**, e i `genesi.motivi` che dicono se vale la pena aprire la genesi. |
| `/api/lavori` | Le quattro fasi dell'iter parlamentare. Il contesto separato. |
| `/api/istituzionali` | Gazzetta Ufficiale, proposte di legge, motore federato regionale. |
| `/api/riassunti` | Sintesi estrattiva delle fonti già trovate. |
| `/api/domanda` | Risposta **estrattiva** a una domanda: cerca, estrae i passaggi pertinenti, rimanda alle fonti. |
| `/api/health` | `GET`. Stato del servizio. |

Tipi di atto: `legge`, `decreto legislativo`, `decreto-legge`, `dpr`,
`regio decreto`. In testo libero riconosce anche i codici (`art 2043 codice
civile`, `art 18 c.p.`).

### Due parametri che sono un contratto

Il frontend legge `?q=<norma>` e `?embed=1` dall'URL. Non sono un dettaglio
interno: **[PP-Assistant](https://github.com/ktfnz4ynbs-arco/PP-Assistent)
incorpora questa app in un iframe** usando quei due parametri. Cambiarli di qui
rompe l'altra app senza che niente lo segnali.

---

## Deploy su Railway

1. Collegare la repo a Railway (New Project → Deploy from GitHub repo).
2. Railway rileva `requirements.txt` e avvia il comando di `railway.json`:
   `uvicorn app:app --host 0.0.0.0 --port $PORT --app-dir backend`
3. In **Variables**, aggiungere `BRAVE_API_KEY` (vedi sotto).

### La chiave Brave non è un optional

I motori scrapati (DuckDuckGo, Startpage) **bloccano spesso gli indirizzi IP dei
datacenter**, Railway compreso. Senza chiave, in produzione la ricerca può
restare vuota: restano i link ai portali, ma i risultati no — e questo riguarda
*tutte* le sezioni che dipendono dalla ricerca, banche dati e iter parlamentare
inclusi.

La [Brave Search API](https://brave.com/search/api/) ha un piano gratuito da
2000 query al mese. Con `BRAVE_API_KEY` impostata l'app la usa da sé; senza,
ripiega sui motori scrapati.

---

## Per chi lavora sul codice

**[`CLAUDE.md`](CLAUDE.md)** raccoglie quello che non si deduce leggendo i file:
le decisioni prese con il proprietario, le trappole già pagate (i numeri di
articolo che si confondono con gli anni, la deduplica che azzerava le ricerche
`site:`, le stranezze di Normattiva) e le cose da non fare.
