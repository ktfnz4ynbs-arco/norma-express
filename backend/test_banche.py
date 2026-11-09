"""Test della ricerca per banca dati (nessuna rete).

I provider vengono sostituiti con una finta SERP: cosi' si verifica la LOGICA
(deduplica, restrizione al dominio, attribuzione, degrado senza risultati)
in modo deterministico, senza dipendere dai siti reali.

Avvio:  python3 -m pytest backend/test_banche.py -q
        oppure  python3 backend/test_banche.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import search  # noqa: E402


def _hit(url, title="t", snippet="s"):
    return search.Hit(title=title, url=url, snippet=snippet,
                      source=search._domain(url), trusted=False)


def _finto_provider(mappa):
    """Restituisce un provider che risponde in base a cosa c'e' nella query."""
    def engine(query, n, dedupe="domain"):
        for chiave, urls in mappa.items():
            if chiave in query:
                return [_hit(u) for u in urls][:n]
        return []
    return engine


def _usa(monkeypatch_like, engine):
    search._engines = lambda: [engine]


def test_dedupe_url_non_collassa_lo_stesso_dominio():
    """Col vecchio dedupe per dominio una ricerca site: dava 1 solo risultato."""
    urls = ["https://www.italgiure.giustizia.it/a", "https://www.italgiure.giustizia.it/b",
            "https://www.italgiure.giustizia.it/c"]
    _usa(None, _finto_provider({"italgiure": urls}))
    assert len(search.web_search("site:italgiure.giustizia.it x", 5, dedupe="url")) == 3


def test_ogni_banca_riceve_solo_i_propri_domini():
    """Se il motore ignora site: e sporca i risultati, il filtro per dominio tiene."""
    _usa(None, _finto_provider({"italgiure": [
        "https://www.italgiure.giustizia.it/ok",
        "https://www.altrosito.it/rumore",          # da scartare
        "https://www.cortedicassazione.it/ok2",     # dominio gemello: da tenere
    ]}))
    b = search._cerca_banca(search.BANCHE[0], "art. 2043 c.c.", "", 5)
    domini = sorted(search._domain(h["url"]) for h in b["results"])
    assert domini == ["cortedicassazione.it", "italgiure.giustizia.it"]
    assert b["id"] == "cassazione"


def test_blocco_vuoto_conserva_i_link():
    """Senza risultati il blocco non sparisce: restano portale e ricerca."""
    _usa(None, _finto_provider({}))
    b = search._cerca_banca(search.BANCHE[1], "art. 3 Cost.", "", 4)
    assert b["results"] == []
    assert b["ricerca"].startswith("https://duckduckgo.com/?q=")
    assert b["portale"]["url"].startswith("https://www.cortecostituzionale.it")


def test_il_link_di_ricerca_porta_con_se_la_query():
    """Il difetto corretto: i link a Cassazione/Consulta ignoravano la query."""
    u = search._url_ricerca(search.BANCHE[0], "art. 2043 codice civile")
    assert "2043" in u and "codice" in u
    assert "site%3Aitalgiure.giustizia.it" in u


# ------------------------------------- l'argomento dell'utente arriva fino al link
def test_il_link_porta_anche_l_argomento_non_solo_la_norma():
    """Il difetto: il link ripeteva solo il riferimento, non cosa si cercava.

    Coi motori bloccati il blocco resta vuoto e quel link e' l'unica cosa in
    mano all'utente: senza argomento gli tocca ridigitare tutto.
    """
    u = search._url_ricerca(search.BANCHE[0], "art. 2043 codice civile",
                            "art. 2043 c.c. responsabilita del medico")
    assert "responsabilita" in u and "medico" in u, u


def test_l_argomento_non_ripete_le_parole_del_riferimento():
    q = search._con_argomento("art. 2043 codice civile",
                              "art. 2043 c.c. responsabilita del medico")
    assert q.lower().count("2043") == 1, q
    assert q.lower().count("codice") == 1, q
    assert "responsabilita del medico" in q, q


def test_senza_argomento_il_link_resta_quello_di_prima():
    assert search._con_argomento("art. 3 Cost.", "") == "art. 3 Cost."
    assert search._con_argomento("art. 3 Cost.", "art. 3 Cost.") == "art. 3 Cost."


def test_ogni_blocco_banca_dati_porta_l_argomento_nel_suo_link():
    _usa(None, _finto_provider({}))
    for b in search.banche_dati("art. 2043 c.c.", "danno da emotrasfusione"):
        assert "emotrasfusione" in b["ricerca"], b["id"]


def test_anche_le_fasi_dell_iter_portano_l_argomento():
    _usa(None, _finto_provider({}))
    for f in search.iter_parlamentare("legge 241/1990", "silenzio assenso"):
        assert "silenzio" in f["ricerca"], f["id"]


def test_deep_links_portano_l_argomento():
    links = search.deep_links("art. 2043 c.c.", "danno da emotrasfusione")
    con = [l for l in links if "emotrasfusione" in l["url"]]
    assert len(con) >= 4, [l["name"] for l in links]


def test_tutte_e_quattro_le_banche_sono_coperte():
    ids = [b["id"] for b in search.BANCHE]
    assert ids == ["cassazione", "costituzionale", "gazzetta", "brocardi"]


def test_banche_dati_restituisce_un_blocco_per_banca():
    _usa(None, _finto_provider({"brocardi": ["https://www.brocardi.it/art2043.html"]}))
    blocchi = search.banche_dati("art. 2043 c.c.")
    assert len(blocchi) == len(search.BANCHE)
    broc = [b for b in blocchi if b["id"] == "brocardi"][0]
    assert broc["results"] and "brocardi.it" in broc["results"][0]["url"]
    # le altre restano vuote ma presenti, coi loro link
    assert all("ricerca" in b for b in blocchi)


def test_label_vuota_non_interroga_nulla():
    assert search.banche_dati("") == []


def test_deep_links_include_ogni_banca_con_query():
    links = search.deep_links("art. 2043 c.c.")
    nomi = " ".join(l["name"] for l in links)
    for atteso in ("Cassazione", "Corte Costituzionale", "Gazzetta Ufficiale", "Brocardi"):
        assert atteso in nomi, atteso
    # almeno un link per banca porta con se' la query
    con_query = [l for l in links if "2043" in l["url"]]
    assert len(con_query) >= 4


# ------------------------------------------------ iter parlamentare / genesi
def test_le_fasi_dell_iter_sono_distinte_e_in_ordine():
    ids = [f["id"] for f in search.FASI_ITER]
    assert ids == ["ddl", "lavori", "emendamenti", "legge"]


def test_ogni_fase_cerca_sui_propri_domini():
    _usa(None, _finto_provider({"emendamenti": [
        "https://www.camera.it/em1",
        "https://www.quotidiano.it/rumore",      # fuori dominio: va scartato
        "https://www.senato.it/em2",
    ]}))
    fase = [f for f in search.FASI_ITER if f["id"] == "emendamenti"][0]
    b = search._cerca_fase(fase, "legge 241/1990", "", 5)
    domini = sorted(search._domain(h["url"]) for h in b["results"])
    assert domini == ["camera.it", "senato.it"]


def test_iter_restituisce_tutte_le_fasi_anche_se_vuote():
    _usa(None, _finto_provider({}))
    fasi = search.iter_parlamentare("legge 241/1990")
    assert len(fasi) == 4
    assert all(f["results"] == [] and f["ricerca"] for f in fasi)


def test_genesi_chiusa_quando_non_serve():
    """Una domanda qualunque su una norma vecchia non apre il contesto."""
    assert search.motivi_genesi("art. 2043 codice civile", "risarcimento danno",
                                anno_corrente=2026) == []


def test_numero_di_articolo_non_scambiato_per_anno():
    """Regressione: "art. 2043" veniva letto come l'anno 2043 -> norma recente."""
    for label in ("art. 2043 codice civile", "art. 2056 c.c.", "art. 1957 c.c."):
        assert search.motivi_genesi(label, "", anno_corrente=2026) == [], label
    # l'anno vero invece viene riconosciuto
    for label, atteso in (("legge 241/1990", False),
                          ("decreto legislativo 36/2023", True),
                          ("legge 7 agosto 1990, n. 241", False)):
        recente = any("recente" in m.lower()
                      for m in search.motivi_genesi(label, "", anno_corrente=2026))
        assert recente is atteso, label


def test_genesi_si_apre_sulla_ratio():
    m = search.motivi_genesi("art. 2043 c.c.", "qual e' la ratio della norma",
                             anno_corrente=2026)
    assert any("ratio" in x.lower() for x in m)


def test_genesi_si_apre_sul_confronto_con_il_previgente():
    m = search.motivi_genesi("legge 241/1990", "differenze con la disciplina precedente",
                             anno_corrente=2026)
    assert any("cambiato" in x.lower() or "precedente" in x.lower() for x in m)


def test_genesi_si_apre_per_norma_recente():
    m = search.motivi_genesi("decreto legislativo 36/2023", "", anno_corrente=2026)
    assert any("recente" in x.lower() for x in m)
    # ma non per una norma lontana nel tempo
    assert search.motivi_genesi("regio decreto 262/1942", "", anno_corrente=2026) == []


def test_genesi_si_apre_su_norma_stratificata_o_abrogata():
    assert search.motivi_genesi("art. 5", "", versioni=4, anno_corrente=2026)
    assert search.motivi_genesi("art. 5", "", abrogato=True, anno_corrente=2026)


def test_motivi_senza_duplicati():
    m = search.motivi_genesi("legge 36/2023", "ratio e finalita della riforma",
                             versioni=2, anno_corrente=2026)
    assert len(m) == len(set(m))


if __name__ == "__main__":
    falliti = 0
    for nome, fn in sorted(globals().items()):
        if not nome.startswith("test_") or not callable(fn):
            continue
        originale = search._engines
        try:
            fn()
            print("  ok   " + nome)
        except AssertionError as e:
            falliti += 1
            print("  FAIL " + nome + "  " + str(e))
        finally:
            search._engines = originale
    print(("TUTTI I TEST PASSATI" if not falliti else "%d TEST FALLITI" % falliti))
    sys.exit(1 if falliti else 0)
