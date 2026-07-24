"""
Modelli di atti che si adattano alla norma cercata (document assembly).

Ispirato a Docassemble (progetto open source, MIT license, usato da studi
legali e organizzazioni di legal-aid per generare atti tramite "guided
interview": https://github.com/jhpyle/docassemble) MA reimplementato qui in
forma minima e autonoma, per restare coerenti col vincolo di progetto
"niente generazione AI": nessun LLM, nessuna rete neurale. E' un motore
puramente a REGOLE:

  1. un CATALOGO di atti tipo (diffida, messa in mora, disdetta, istanza...)
     ciascuno associato alla norma di riferimento (stesso `LawRef` usato dal
     resto dell'app: tipo/numero/anno/articolo) e/o a parole chiave;
  2. il MATCH tra la norma appena letta e i modelli pertinenti (`match`);
  3. la COMPILAZIONE del testo: sostituzione campi + paragrafi opzionali
     attivati solo se il campo e' valorizzato (`<<SE:campo>>...<<FINESE>>`),
     l'equivalente "a regole" delle domande di un'intervista guidata.

Il testo prodotto e' un FAC-SIMILE compilato dai dati inseriti dall'utente:
va sempre controllato da un professionista prima dell'uso, non e' un parere
legale ne' un atto gia' pronto per il deposito.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"          # text | textarea | number | date
    required: bool = False
    placeholder: str = ""
    default: str = ""


@dataclass
class Match:
    tipo: str
    numero: Optional[int] = None
    anno: Optional[int] = None
    articoli: Optional[list] = None  # None = qualunque articolo della stessa legge


@dataclass
class Template:
    id: str
    titolo: str
    norma: str                  # riferimento mostrato all'utente (es. "Art. 1454 c.c.")
    descrizione: str
    fields: list
    corpo: str
    match: list = field(default_factory=list)
    keywords: str = ""          # regex, cerca in label + query libera


_BASE_FIELDS = [
    Field("mittente", "Tuo nome / ragione sociale", required=True, placeholder="Mario Rossi"),
    Field("mittente_indirizzo", "Tuo indirizzo (facoltativo)", placeholder="Via Roma 1, 00100 Roma"),
    Field("destinatario", "Destinatario", required=True, placeholder="Rossi S.r.l."),
    Field("destinatario_indirizzo", "Indirizzo destinatario (facoltativo)", placeholder="Via Milano 2, 20100 Milano"),
    Field("luogo", "Luogo", required=True, placeholder="Roma"),
    Field("data", "Data", type="date", required=True),
]

_HEADER = (
    "{luogo}, {data}\n\n"
    "Mittente: {mittente}<<SE:mittente_indirizzo>> — {mittente_indirizzo}<<FINESE>>\n"
    "Destinatario: {destinatario}<<SE:destinatario_indirizzo>> — {destinatario_indirizzo}<<FINESE>>\n\n"
)

CATALOGO = [
    Template(
        id="diffida_adempiere",
        titolo="Diffida ad adempiere",
        norma="Art. 1454 c.c.",
        descrizione="Intima alla controparte di adempiere entro un termine, pena la risoluzione di diritto del contratto.",
        match=[Match("regio decreto", 262, 1942, ["1453", "1454"])],
        keywords=r"inadempi|risoluzione (del )?contratto|diffida",
        fields=_BASE_FIELDS + [
            Field("contratto", "Contratto/obbligazione (data, oggetto)", required=True,
                  placeholder="scrittura privata del 10/01/2026 avente ad oggetto ..."),
            Field("inadempimento", "In cosa consiste l'inadempimento", type="textarea", required=True),
            Field("termine_giorni", "Termine per adempiere (giorni)", type="number", default="15"),
        ],
        corpo=_HEADER +
        "Oggetto: Diffida ad adempiere ex art. 1454 c.c.\n\n"
        "Con riferimento a {contratto}, si contesta quanto segue:\n\n"
        "{inadempimento}\n\n"
        "Con la presente il/la sottoscritto/a {mittente} DIFFIDA e INTIMA la "
        "S.V. ad adempiere entro e non oltre {termine_giorni} giorni dal "
        "ricevimento della presente, avvertendo che, decorso inutilmente "
        "tale termine, il contratto si intendera' risolto di diritto ai "
        "sensi dell'art. 1454 c.c., con riserva di ogni ulteriore azione per "
        "il risarcimento del danno.\n\n"
        "Distinti saluti.\n\n{mittente}",
    ),
    Template(
        id="costituzione_mora",
        titolo="Costituzione in mora",
        norma="Art. 1219 c.c.",
        descrizione="Intimazione scritta che fa decorrere gli effetti della mora del debitore.",
        match=[Match("regio decreto", 262, 1942, ["1218", "1219", "1223"])],
        keywords=r"mora del debitore|costituzione in mora",
        fields=_BASE_FIELDS + [
            Field("credito", "Obbligazione/credito", type="textarea", required=True,
                  placeholder="somma di € ... dovuta a titolo di ..."),
            Field("termine_giorni", "Termine per adempiere (giorni)", type="number", default="10"),
        ],
        corpo=_HEADER +
        "Oggetto: Costituzione in mora ex art. 1219 c.c.\n\n"
        "Il/La sottoscritto/a {mittente}, con la presente, costituisce in "
        "mora la S.V. in relazione a: {credito}\n\n"
        "Si intima il pagamento/adempimento entro {termine_giorni} giorni "
        "dal ricevimento, decorsi i quali si agira' nelle sedi opportune per "
        "il recupero, oltre interessi legali e risarcimento del danno "
        "ulteriore ai sensi dell'art. 1224 c.c.\n\n"
        "Distinti saluti.\n\n{mittente}",
    ),
    Template(
        id="richiesta_risarcimento",
        titolo="Richiesta di risarcimento danni",
        norma="Art. 2043 c.c.",
        descrizione="Richiesta stragiudiziale di risarcimento per fatto illecito.",
        match=[Match("regio decreto", 262, 1942, ["2043", "2049", "2050", "2051", "2059"])],
        keywords=r"risarciment|danno ingiust|fatto illecito|responsabilit.\s*civile",
        fields=_BASE_FIELDS + [
            Field("fatto", "Descrizione del fatto e del danno subito", type="textarea", required=True),
            Field("importo", "Importo richiesto (€, facoltativo)", placeholder="1.500,00"),
            Field("termine_giorni", "Termine per rispondere (giorni)", type="number", default="15"),
        ],
        corpo=_HEADER +
        "Oggetto: Richiesta di risarcimento danni ex art. 2043 c.c.\n\n"
        "Il/La sottoscritto/a {mittente} premette quanto segue:\n\n{fatto}\n\n"
        "Per l'effetto, si richiede il risarcimento del danno subito"
        "<<SE:importo>>, quantificato in € {importo}<<FINESE>>, entro "
        "{termine_giorni} giorni dal ricevimento della presente, con "
        "riserva di agire in ogni sede competente in caso di mancato "
        "riscontro.\n\nDistinti saluti.\n\n{mittente}",
    ),
    Template(
        id="disdetta_locazione",
        titolo="Disdetta del contratto di locazione",
        norma="Art. 1596 c.c. — L. 431/1998",
        descrizione="Comunicazione di recesso/disdetta dal contratto di locazione alla prima scadenza utile.",
        match=[Match("regio decreto", 262, 1942, ["1596", "1571"])],
        keywords=r"disdetta|recesso.*locazione|locazione.*recesso",
        fields=_BASE_FIELDS + [
            Field("immobile", "Immobile locato (indirizzo)", required=True),
            Field("contratto_data", "Data del contratto di locazione", required=True),
            Field("data_rilascio", "Data prevista per il rilascio", type="date"),
        ],
        corpo=_HEADER +
        "Oggetto: Disdetta del contratto di locazione\n\n"
        "Il/La sottoscritto/a {mittente}, conduttore/locatore dell'immobile "
        "sito in {immobile}, oggetto del contratto di locazione stipulato in "
        "data {contratto_data}, con la presente comunica DISDETTA del "
        "contratto"
        "<<SE:data_rilascio>>, con rilascio dell'immobile entro il "
        "{data_rilascio}<<FINESE>>, ai sensi dell'art. 1596 c.c. e della L. "
        "431/1998.\n\nDistinti saluti.\n\n{mittente}",
    ),
    Template(
        id="dimissioni",
        titolo="Lettera di dimissioni",
        norma="Art. 2118 c.c.",
        descrizione="Recesso del lavoratore dal rapporto di lavoro con preavviso.",
        match=[Match("regio decreto", 262, 1942, ["2118", "2119"])],
        keywords=r"dimission|recesso.*lavoro|licenziament",
        fields=_BASE_FIELDS + [
            Field("qualifica", "Qualifica/ruolo", placeholder="impiegato/a amministrativo/a"),
            Field("data_ultimo_giorno", "Data ultimo giorno di lavoro (fine preavviso)", type="date"),
        ],
        corpo=_HEADER +
        "Oggetto: Lettera di dimissioni\n\n"
        "Il/La sottoscritto/a {mittente}"
        "<<SE:qualifica>>, {qualifica} presso codesta azienda<<FINESE>>, "
        "comunica con la presente le proprie DIMISSIONI dal rapporto di "
        "lavoro, ai sensi dell'art. 2118 c.c., con decorrenza del periodo di "
        "preavviso di legge/contratto"
        "<<SE:data_ultimo_giorno>> e con ultimo giorno di lavoro il "
        "{data_ultimo_giorno}<<FINESE>>.\n\n"
        "Si ricorda che le dimissioni vanno trasmesse in modalita' "
        "telematica tramite il portale ministeriale, pena l'inefficacia.\n\n"
        "Distinti saluti.\n\n{mittente}",
    ),
    Template(
        id="contestazione_disciplinare",
        titolo="Contestazione disciplinare",
        norma="Art. 7 L. 300/1970 (Statuto dei lavoratori)",
        descrizione="Contestazione scritta di un addebito disciplinare al lavoratore, con termine per le giustificazioni.",
        match=[Match("legge", 300, 1970, ["7"])],
        keywords=r"contestazione disciplinare|procedimento disciplinare",
        fields=_BASE_FIELDS + [
            Field("addebito", "Fatto contestato", type="textarea", required=True),
            Field("termine_giorni", "Termine per le giustificazioni (giorni)", type="number", default="5"),
        ],
        corpo=_HEADER +
        "Oggetto: Contestazione disciplinare ex art. 7 L. 300/1970\n\n"
        "Con la presente si contesta al/alla Sig./Sig.ra {destinatario} il "
        "seguente addebito:\n\n{addebito}\n\n"
        "Ai sensi dell'art. 7 dello Statuto dei lavoratori, La invitiamo a "
        "far pervenire eventuali giustificazioni scritte, o a chiedere di "
        "essere sentito/a oralmente con l'eventuale assistenza di un "
        "rappresentante sindacale, entro {termine_giorni} giorni dal "
        "ricevimento della presente. Decorso tale termine senza riscontro, "
        "si procedera' all'adozione dei provvedimenti conseguenti.\n\n"
        "Distinti saluti.\n\n{mittente}",
    ),
    Template(
        id="accesso_atti",
        titolo="Istanza di accesso agli atti",
        norma="Art. 22 L. 241/1990",
        descrizione="Richiesta di accesso a documenti amministrativi alla Pubblica Amministrazione.",
        match=[Match("legge", 241, 1990, ["22", "23", "24", "25"])],
        keywords=r"accesso agli atti|accesso documentale",
        fields=_BASE_FIELDS + [
            Field("documenti", "Documenti richiesti", type="textarea", required=True),
            Field("motivazione", "Interesse diretto/concreto/attuale (facoltativo)", type="textarea"),
        ],
        corpo=_HEADER +
        "Oggetto: Istanza di accesso agli atti ex artt. 22 e ss. L. 241/1990\n\n"
        "Il/La sottoscritto/a {mittente} chiede, ai sensi degli artt. 22 e "
        "seguenti della L. 241/1990, di poter accedere/ottenere copia dei "
        "seguenti documenti:\n\n{documenti}\n\n"
        "<<SE:motivazione>>A fondamento del proprio interesse diretto, "
        "concreto e attuale, si rappresenta quanto segue: "
        "{motivazione}\n\n<<FINESE>>"
        "Si resta in attesa di riscontro nei termini di legge.\n\n"
        "Distinti saluti.\n\n{mittente}",
    ),
    Template(
        id="recesso_consumatore",
        titolo="Recesso del consumatore",
        norma="Art. 52 Codice del Consumo (D.Lgs. 206/2005)",
        descrizione="Comunicazione di recesso da un contratto a distanza o negoziato fuori dai locali commerciali.",
        match=[Match("decreto legislativo", 206, 2005, ["52", "54"])],
        keywords=r"recesso.*consumator|diritto di ripensamento",
        fields=_BASE_FIELDS + [
            Field("contratto", "Contratto/ordine (numero, data, oggetto)", required=True),
        ],
        corpo=_HEADER +
        "Oggetto: Comunicazione di recesso ex art. 52 Codice del Consumo\n\n"
        "Il/La sottoscritto/a {mittente} comunica, ai sensi dell'art. 52 del "
        "D.Lgs. 206/2005 (Codice del Consumo), di voler esercitare il "
        "diritto di recesso dal seguente contratto: {contratto}\n\n"
        "Si chiede conferma di ricezione della presente e le istruzioni per "
        "la restituzione di quanto eventualmente ricevuto e per il rimborso "
        "delle somme versate.\n\nDistinti saluti.\n\n{mittente}",
    ),
    Template(
        id="accesso_dati_gdpr",
        titolo="Istanza di accesso ai dati personali",
        norma="Art. 15 GDPR — D.Lgs. 196/2003",
        descrizione="Richiesta all'interessato di accedere ai propri dati personali trattati dal titolare.",
        match=[Match("decreto legislativo", 196, 2003)],
        keywords=r"accesso ai (propri )?dati personali|diritto di accesso.*gdpr|privacy.*accesso",
        fields=_BASE_FIELDS + [
            Field("servizio", "Rapporto/servizio a cui si riferisce la richiesta", placeholder="cliente dal 2022, contratto n. ..."),
        ],
        corpo=_HEADER +
        "Oggetto: Istanza di accesso ai dati personali ex art. 15 GDPR\n\n"
        "Il/La sottoscritto/a {mittente}"
        "<<SE:servizio>>, in qualita' di {servizio}<<FINESE>>, chiede di "
        "esercitare il diritto di accesso ai sensi dell'art. 15 del "
        "Regolamento (UE) 2016/679 (GDPR), richiedendo conferma "
        "dell'esistenza di dati personali che La riguardano, copia degli "
        "stessi e le informazioni di cui all'art. 15, par. 1, lett. a)-h) "
        "GDPR.\n\nSi resta in attesa di riscontro entro un mese dal "
        "ricevimento, come previsto dall'art. 12 GDPR.\n\n"
        "Distinti saluti.\n\n{mittente}",
    ),
    Template(
        id="opposizione_decreto_ingiuntivo",
        titolo="Atto di opposizione a decreto ingiuntivo (bozza)",
        norma="Art. 645 c.p.c.",
        descrizione="Bozza dei contenuti essenziali per l'atto di citazione in opposizione a decreto ingiuntivo — da affidare a un avvocato per il deposito.",
        match=[Match("regio decreto", 1443, 1940, ["645", "633"])],
        keywords=r"opposizione.*decreto ingiuntivo|decreto ingiuntivo.*opposizione",
        fields=_BASE_FIELDS + [
            Field("decreto_estremi", "Estremi del decreto ingiuntivo (numero, data, importo)", required=True),
            Field("motivi", "Motivi di opposizione", type="textarea", required=True),
        ],
        corpo=_HEADER +
        "Oggetto: Bozza di opposizione a decreto ingiuntivo ex art. 645 c.p.c.\n\n"
        "Il/La sottoscritto/a {mittente}, con riferimento al decreto "
        "ingiuntivo {decreto_estremi}, intende proporre opposizione per i "
        "seguenti motivi:\n\n{motivi}\n\n"
        "NOTA: l'opposizione va proposta con atto di citazione notificato "
        "entro 40 giorni dalla notifica del decreto (termine ordinario, "
        "art. 641 c.p.c.); questo testo e' solo una bozza dei contenuti e "
        "va necessariamente affidata a un avvocato per la redazione e il "
        "deposito nei termini.\n\n{mittente}",
    ),
]

_BY_ID = {t.id: t for t in CATALOGO}

_COND_RE = re.compile(r"<<SE:(\w+)>>(.*?)<<FINESE>>", re.S)
_FIELD_RE = re.compile(r"\{(\w+)\}")


def _norm_art(a: Optional[str]) -> str:
    return re.sub(r"[^0-9a-z]", "", (a or "").lower())


def _law_matches(m: Match, ref) -> bool:
    if ref is None or ref.tipo != m.tipo:
        return False
    if m.numero is not None and ref.numero != m.numero:
        return False
    if m.anno is not None and ref.anno != m.anno:
        return False
    return True


def _score(t: Template, ref, text: str) -> int:
    """Il solo 'stessa legge' non basta per i codici (c.c./c.p./c.p.c. coprono
    migliaia di articoli non pertinenti): conta solo se l'articolo richiesto
    e' tra quelli del modello, oppure se il modello non lega a articoli
    specifici (leggi piccole, es. GDPR). Le parole chiave restano un canale
    di match indipendente (ricerche libere senza articolo preciso)."""
    score = 0
    for m in t.match:
        if not _law_matches(m, ref):
            continue
        if m.articoli is None:
            score += 2
        elif ref and ref.articolo and _norm_art(ref.articolo) in m.articoli:
            score += 7
    if t.keywords and re.search(t.keywords, text, re.I):
        score += 3
    return score


def match_templates(ref, label: str, extra: str = "", limit: int = 6) -> list:
    """Ritorna i modelli pertinenti alla norma/richiesta corrente, piu' rilevanti prima."""
    text = f"{label} {extra}".strip()
    scored = [(t, _score(t, ref, text)) for t in CATALOGO]
    scored = [(t, s) for t, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [_summary(t) for t, _ in scored[:limit]]


def _summary(t: Template) -> dict:
    return {
        "id": t.id, "titolo": t.titolo, "norma": t.norma, "descrizione": t.descrizione,
        "fields": [{"name": f.name, "label": f.label, "type": f.type,
                    "required": f.required, "placeholder": f.placeholder,
                    "default": f.default} for f in t.fields],
    }


def get_template(template_id: str) -> Optional[Template]:
    return _BY_ID.get(template_id)


def render(t: Template, values: dict) -> dict:
    """Compila il corpo del modello sostituendo i campi e attivando/disattivando
    i paragrafi opzionali (<<SE:campo>>...<<FINESE>>). Nessuna generazione: solo
    sostituzione di stringhe fornite dall'utente in un testo predefinito."""
    values = values or {}

    def cond(m):
        name, block = m.group(1), m.group(2)
        return block if str(values.get(name) or "").strip() else ""

    text = _COND_RE.sub(cond, t.corpo)

    missing = []
    for f in t.fields:
        if f.required and not str(values.get(f.name) or "").strip():
            missing.append(f.label)

    def sub(m):
        name = m.group(1)
        val = values.get(name)
        if val is None or str(val).strip() == "":
            default = next((f.default for f in t.fields if f.name == name), "")
            return default or f"[{name}]"
        return str(val)

    text = _FIELD_RE.sub(sub, text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {"testo": text, "campi_mancanti": missing}
