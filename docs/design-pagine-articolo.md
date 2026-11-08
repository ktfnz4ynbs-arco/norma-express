# Progetto — Pagine server-rendered per articolo

Stato: **fase 1 implementata** (2026-11-08): `catalogo.py`, `cache.py`, `pagine.py`,
`test_pagine.py`. Fasi 2 e 3 da fare. Decisioni utente: volume Railway sì, slug leggibili.
Obiettivo: rendere ogni articolo una pagina con URL proprio, testo già nell'HTML,
indicizzabile da Google, senza tradire i vincoli del progetto (niente AI generativa,
niente fonti a pagamento, prima l'articolo poi il resto).

---

## 0. Da sapere prima di iniziare

1. **Il solo testo dell'articolo è contenuto duplicato.** Lo stesso testo è già su
   Normattiva, Brocardi, Altalex, Gazzetta. Per "art. 2043 c.c." Google ha già scelto chi
   mostrare: una pagina che ripete il testo **non scavalcherà Brocardi**. Le pagine
   rendono se aggiungono qualcosa che gli altri non hanno nello stesso posto (§5) e
   puntando sulla coda lunga (testi unici, articoli meno coperti), non sui 50 articoli
   più cercati del codice civile.
2. **Normattiva non è "testo ufficiale" in senso stretto.** La stessa Normattiva
   avverte che fa fede solo la Gazzetta Ufficiale. La pagina deve dirlo (§5.6);
   `CLAUDE.md` oggi usa "ufficiale" in modo impreciso.
3. **Ogni visita di Googlebot oggi = 2 richieste a Normattiva.** Con migliaia di pagine
   e senza cache si rischia il blocco dell'IP Railway. La **cache persistente non è
   facoltativa** (§4).
4. **Da verificare (non ho fonti certe):** termini d'uso di Normattiva sull'accesso
   automatizzato e l'esistenza di un canale open data/bulk ufficiale. Se esiste un
   canale ufficiale, va preferito allo scraping. Sul diritto d'autore il dato solido è
   l'**art. 5 L. 633/1941**: i testi degli atti ufficiali dello Stato non sono protetti,
   quindi riprodurre il testo normativo è lecito. **Non** vale per massime redazionali
   e commenti di Brocardi e simili: per questo restano fuori dall'HTML indicizzato (§5.4).

---

## 1. URL

```
/{atto}/art-{numero}            pagina articolo   es. /codice-civile/art-2043
/{atto}                         pagina indice     es. /codice-civile
/sitemap.xml                    sitemap index
/sitemaps/{atto}.xml            una sitemap per atto
```

- `{atto}` è uno **slug canonico** da un registro unico (`backend/catalogo.py`):
  - codici e testi noti → nome leggibile: `codice-civile`, `codice-penale`,
    `codice-procedura-civile`, `codice-procedura-penale`, `costituzione`,
    `codice-della-strada`, `statuto-dei-lavoratori`, `testo-unico-immigrazione`, …
  - qualsiasi altro atto → schema numerico: `legge-241-1990`, `dlgs-196-2003`,
    `dl-18-2020`, `dpr-380-2001`, `rd-267-1942`.
- `{numero}`: minuscolo, suffissi con trattino: `art-2043`, `art-2-bis`, `art-416-ter`.
- **Un solo URL per articolo.** Varianti (`/Codice-Civile/Art-2043`, `/cc/art-2043`,
  `/legge-300-1970/art-18` quando esiste lo slug `statuto-dei-lavoratori`) → **301**
  verso il canonico.
- Esclusi: atti che Normattiva non ospita (es. GDPR `regolamento_ue` in `KNOWN_LAWS`).

Registro (bozza):

```python
# backend/catalogo.py
@dataclass(frozen=True)
class Atto:
    slug: str            # "codice-civile"
    ref: LawRef          # tipo/numero/anno/allegato, senza articolo
    nome: str            # "Codice civile"
    abbr: str            # "c.c."  → title e breadcrumb
    in_sitemap: bool     # True = catalogo curato, entra in sitemap

ATTI: dict[str, Atto]          # costruito da lawref.CODES + KNOWN_LAWS + Costituzione
def da_slug(slug) -> LawRef | None     # anche gli slug numerici, via lawref.from_fields
def slug_di(ref: LawRef) -> str        # inverso: usato da SPA e dai link interni
```

Test di andata e ritorno `slug → LawRef → slug` su tutto il registro.

---

## 2. Codici di stato (decisivi per Google)

| Caso | Stato | Note |
|---|---|---|
| Articolo trovato | 200 | indicizzabile, anche se abrogato (§5.3) |
| URL non canonico | 301 | verso lo slug canonico |
| Articolo inesistente (Normattiva non lo trova) | **404** | cache negativa 24 h |
| Slug di atto sconosciuto | 404 | |
| Normattiva irraggiungibile **e** nessuna copia in cache | **503** + `Retry-After: 3600` | **mai** 404 o 200 vuoto: Google ritenta invece di de-indicizzare |
| Normattiva irraggiungibile, copia in cache | 200 con la copia | anche se scaduta (§4) |

---

## 3. Rendering

- **Jinja2** (nuova dipendenza, piccola) con autoescape: `backend/templates/`
  `base.html` · `articolo.html` · `indice.html`. Niente f-string per l'HTML: il testo
  arriva da un sito terzo e va sempre escapato.
- **Stessa interfaccia della SPA.** La pagina articolo usa lo stesso hero (compatto),
  la stessa search card e lo stesso `style.css`. La card *Articolo* è già nell'HTML;
  le altre card (sintesi, fonti, banche dati, genesi, domanda) le carica `app.js`
  come oggi, partendo dalla fase 2.
- Passaggio dati alla SPA: `<script type="application/json" id="articolo-iniziale">`
  con l'`ArticleResult` serializzato. `app.js` lo legge e **salta `/api/articolo`**
  (testo già presente → nessuna seconda richiesta a Normattiva).
- Il testo resta testo: paragrafi `<p>` dai capoversi, commi riconoscibili. Nessuna
  riscrittura.

---

## 4. Dati e cache (`backend/cache.py`)

**SQLite** su file in `$DATA_DIR` (volume Railway montato, es. `/data`).

```
articoli(urn PK, slug, num, json, sha256, fetched_at, changed_at, status)
indici  (slug PK, json, fetched_at)
```

- **Fresco 7 giorni**: servito subito.
- **Scaduto (7–180 giorni)**: servito subito e **riaggiornato in background**
  (stale-while-revalidate). Googlebot non attende mai Normattiva per una pagina vista.
- **Mancante**: richiesta sincrona a Normattiva (timeout breve, 10 s) → 200 / 404 / 503.
- `changed_at` si aggiorna **solo se `sha256` del testo cambia** → è il `lastmod`
  reale della sitemap. Mai date finte.
- **Freno verso Normattiva**: limitatore globale (≈1 richiesta/s, un token bucket in
  memoria) + *single-flight* per URN (due richieste simultanee per lo stesso articolo =
  un solo fetch).
- `ETag` = sha256 → risposte `304` a chi lo rimanda. `Cache-Control: public,
  max-age=3600, stale-while-revalidate=86400`.

Senza volume la cache si azzera a ogni deploy: ogni deploy scatenerebbe migliaia di
richieste a Normattiva. **Il volume è un prerequisito**, vedi domande aperte.

---

## 5. Contenuto della pagina articolo

Ordine nella pagina, tutto nell'HTML iniziale salvo dove indicato:

1. **Breadcrumb**: Norma Express › Codice civile › Libro IV › Titolo IX › Art. 2043
   (le partizioni vengono da `fetch_index`, già in cache).
2. **H1**: `Art. 2043 codice civile — Risarcimento per fatto illecito` (rubrica da
   `article_heading`).
3. **Stato**: badge *in vigore dal …* (`in_force_from`) oppure **ABROGATO**;
   numero di versioni (`versions`) + controllo "testo a una data" (`!vig=`), già
   esistenti.
4. **Testo dell'articolo**.
5. **Valore aggiunto proprio** (ciò che giustifica la pagina rispetto a Normattiva):
   - **rinvii interni cliccabili**: "art. 2059" nel testo → link a
     `/codice-civile/art-2059`. Solo riferimenti **nello stesso atto**, regex
     prudente; in caso di dubbio, nessun link (meglio un rinvio mancato che uno
     sbagliato);
   - **modifiche** (`updates`, già estratte) con data;
   - **articolo precedente / successivo** e link all'indice dell'atto;
   - fase 3: **"citato da"**, cioè gli articoli del catalogo che rinviano a questo
     (calcolato offline dai rinvii in cache). Nessuna delle fonti gratuite lo offre
     in questa forma.
6. **Fonte**: "Testo tratto da Normattiva il {data}. Fa fede la pubblicazione in
   Gazzetta Ufficiale." + permalink Normattiva.
7. **Interpretazione, giurisprudenza, banche dati, genesi, domanda**: **caricate dal
   client**, come oggi. Motivi per non metterle nell'HTML indicizzato:
   - sono estratti di pagine altrui → contenuto duplicato e possibile violazione dei
     diritti sulle massime redazionali;
   - richiederebbero ricerche web dal vivo a ogni visita di Googlebot (lente, spesso
     bloccate dagli IP datacenter);
   - cambiano a ogni richiesta → pagina instabile agli occhi del motore.

### Meta

- `<title>`: `Art. 2043 c.c. — Risarcimento per fatto illecito | Norma Express`
  (troncare la rubrica oltre ~60 caratteri complessivi).
- `description`: primi ~150 caratteri del testo, tagliati a fine parola.
- `canonical`: l'URL stesso. `robots`: `index, follow` (anche se abrogato: chi cerca un
  articolo abrogato deve scoprire che lo è).
- **JSON-LD**: `Legislation` (`name`, `legislationIdentifier` = URN,
  `legislationJurisdiction: "IT"`, `legislationLegalForce: InForce|NotInForce`,
  `isPartOf` → l'atto, `sameAs` → permalink Normattiva) + `BreadcrumbList`.
  Per `Legislation` Google non mostra risultati arricchiti: serve solo a far capire
  la pagina. Il breadcrumb invece compare nei risultati.

---

## 6. Pagina indice dell'atto (`/{atto}`)

- Albero da `fetch_index` (Libri/Titoli/Capi → numeri articolo), in cache.
- Ogni voce è un `<a href="/codice-civile/art-N">` vero (oggi sono pulsanti JS: Google
  non li segue).
- È lo **snodo dei link interni**. La home avrà una sezione "Codici e testi unici" con
  link a tutti gli indici del catalogo → ogni articolo è raggiungibile in 2 clic dalla
  home.

---

## 7. Sitemap

- `/sitemap.xml` diventa un **sitemap index**: home + una sitemap per atto in catalogo.
- `/sitemaps/{atto}.xml`: i numeri articolo vengono dall'**indice Normattiva dell'atto**
  (una richiesta per atto, in cache 7 giorni) + gli articoli già in cache. `lastmod` solo
  per gli articoli in cache (= `changed_at`), mai inventato.
  *Correzione rispetto alla prima stesura*, che voleva "solo articoli già in cache": in
  fase 1, senza `warm.py`, la sitemap sarebbe rimasta vuota (la cache si riempie solo con
  le visite). Il prezzo: un articolo non ancora in cache viene scaricato alla visita di
  Googlebot, a ritmo frenato; se la coda è lunga risponde 503 e Google rallenta da sé.
- Limite 50.000 URL per file: il codice civile (~3.000 articoli) ci sta.

---

## 8. Integrazione con la ricerca esistente

- `GET /?q=art 2043 cc` → il server esegue `lawref.parse` (locale, nessuna rete). Se
  ne esce un articolo con slug valido → **302** a `/codice-civile/art-2043`. Altrimenti
  la SPA come oggi (con `noindex`, già in place). 302 e non 301: è una ricerca, non un
  indirizzo permanente.
- `?embed=1` resta sulla SPA (l'iframe di POL·PEN Assistant non cambia).
- Ricerca dalla search card: se `/api/articolo` restituisce un articolo, la risposta
  include `page_url` e `app.js` naviga lì (`location.assign`); indice e richieste
  libere restano nella SPA.
- I chip dell'indice nella SPA diventano link reali alle pagine articolo.

---

## 9. Riscaldamento della cache (fase 3)

Script `backend/warm.py` (job manuale o cron Railway): per ogni atto del catalogo
scarica l'indice, poi gli articoli mancanti o scaduti, **a 1 richiesta ogni 2 s**.
Ordine di grandezza: catalogo attuale ≈ 10–15 mila articoli × 2 richieste × 2 s ≈
**11–17 ore** la prima volta, poi solo gli scaduti. Riprende da dove si è interrotto
(lo stato è nel DB).

---

## 10. Test (senza rete, come `test_banche.py`)

Fixture HTML di Normattiva salvate in `backend/fixtures/` (vanno catturate dal deploy:
qui Normattiva non è raggiungibile). Casi:

- slug ↔ LawRef sull'intero registro; 301 sulle varianti;
- 200 / 404 / 503 con fetch finto (ok, non trovato, eccezione di rete, con e senza cache);
- stale-while-revalidate: copia scaduta servita + aggiornamento accodato;
- `lastmod` cambia solo se cambia l'hash del testo;
- escaping: testo con `<script>` nel fixture non esce come markup;
- rinvii interni: "art. 2059" → link; "art. 7 della legge 241/1990" in un articolo del
  c.c. → **nessun** link;
- sitemap: contiene solo articoli `ok` in cache;
- `/?q=art 2043 cc` → 302; `/?q=licenziamento` → SPA con `noindex`.

---

## 11. Fasi

| Fase | Contenuto | Esito verificabile |
|---|---|---|
| **1 — MVP** | `catalogo.py` (4 codici + Costituzione), `cache.py`, route articolo, template, stati 200/301/404/503, sitemap per atto, test | `/codice-civile/art-2043` risponde 200 con testo nell'HTML; Search Console accetta le sitemap |
| **2 — Rete interna** | pagine indice, sezione home "Codici e testi unici", breadcrumb, prec/succ, rinvii interni, JSON-LD, integrazione SPA (§8) | ogni articolo a 2 clic dalla home; nessun link orfano |
| **3 — Scala** | tutti gli atti di `KNOWN_LAWS`, `warm.py`, "citato da" | copertura sitemap ≈ catalogo |

**Metriche** (Search Console, a 8–12 settimane dalla fase 1): pagine indicizzate /
pagine inviate, impressioni e CTR su query `art N …`. Se le pagine dei codici restano
"scansionate ma non indicizzate" (il segnale tipico del contenuto duplicato), spostare
lo sforzo sui testi unici e sul valore aggiunto del §5.5, non su altri articoli dei
codici.

---

## 12. Domande aperte (da decidere con l'utente)

1. **Volume Railway per SQLite** (costo piccolo ma non nullo; vincolo "niente servizi a
   pagamento"). Alternativa senza volume: cache solo in memoria + `warm.py` limitato ai
   codici → più richieste a Normattiva a ogni deploy, rischio blocco più alto.
2. **Dominio definitivo** (serve per `PUBLIC_URL`, sitemap, Search Console). Un
   sottodominio `*.up.railway.app` funziona, ma un dominio proprio si consolida meglio
   nel tempo.
3. **Slug leggibili o numerici** per le leggi note (`statuto-dei-lavoratori` vs
   `legge-300-1970`). Proposta: leggibili per codici e testi noti, numerici per il
   resto. Una volta pubblicati, gli slug non si cambiano.
