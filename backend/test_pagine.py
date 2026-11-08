"""Test delle pagine server-rendered e della cache (nessuna rete).

Normattiva e' sostituita da funzioni finte: si verificano URL canonici, codici di
stato (200/301/404/503), cache (fresco, scaduto, negativo, lastmod reale), escaping
del testo, sitemap.

Avvio:  python3 -m pytest backend/test_pagine.py -q
        oppure  python3 backend/test_pagine.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ne-test-"))
os.environ.pop("PUBLIC_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

import app as app_mod  # noqa: E402
import cache  # noqa: E402
import catalogo  # noqa: E402
import normattiva  # noqa: E402
import pagine  # noqa: E402
from normattiva import ArticleResult, IndexResult  # noqa: E402

_PICK_ORIG = normattiva._pick_article_link

client = TestClient(app_mod.app)
CHIAMATE = []

TESTO = "Qualunque fatto doloso o colposo, che cagiona ad altri un danno ingiusto, " \
        "obbliga colui che ha commesso il fatto a risarcire il danno."


def _ok(ref):
    CHIAMATE.append(ref.articolo)
    return ArticleResult(ok=True, query_label=ref.label, act_title="REGIO DECRETO 16 marzo 1942, n. 262",
                         article_heading="Art. 2043 — (Risarcimento per fatto illecito)",
                         text=TESTO, in_force_from="21/04/1942",
                         permalink="https://www.normattiva.it/uri-res/N2Ls?urn:x", versions=1)


def _nontrovato(ref):
    CHIAMATE.append(ref.articolo)
    return ArticleResult(ok=False, query_label=ref.label, error="Articolo non individuato")


def _giu(ref):
    CHIAMATE.append(ref.articolo)
    return ArticleResult(ok=False, query_label=ref.label, error="timeout", network_error=True)


def _indice(ref):
    return IndexResult(ok=True, label="c.c.", act_title="Codice civile", total=3, groups=[
        {"partition": "LIBRO IV", "articles": [{"num": "2043"}, {"num": "2043 bis"},
                                                {"num": "2044"}, {"num": "2043"}]}])


def _setup(fetch=_ok, index=_indice):
    cache.reset(Path(tempfile.mkdtemp(prefix="ne-cache-")) / "c.sqlite", interval=0.0)
    normattiva.fetch_article = fetch
    normattiva.fetch_index = index
    CHIAMATE.clear()


# -------------------------------------------------------------- catalogo / URL
def test_slug_andata_e_ritorno_sul_catalogo():
    for slug, atto in catalogo.CATALOGO.items():
        assert catalogo.slug_di(atto.ref_articolo("1")) == slug
        assert catalogo.canonico(slug) == slug


def test_norm_articolo():
    assert catalogo.norm_articolo("2043") == "2043"
    for v in ("2-bis", "2bis", "2 bis", "2-BIS"):
        assert catalogo.norm_articolo(v) == "2-bis", v
    assert catalogo.norm_articolo("25-terdecies") == "25-terdecies"   # non "ter"
    assert catalogo.norm_articolo("2043-foo") is None
    assert catalogo.norm_articolo("abc") is None


def test_slug_numerici():
    a = catalogo.atto_da_slug("legge-241-1990")
    assert (a.ref.tipo, a.ref.numero, a.ref.anno) == ("legge", 241, 1990)
    assert not a.in_sitemap
    assert catalogo.atto_da_slug("dlgs-196-2003").ref.tipo == "decreto legislativo"
    assert catalogo.atto_da_slug("pippo-1-2000") is None
    # codice di procedura penale = d.P.R. 447/1988 senza allegato -> slug leggibile
    assert catalogo.canonico("dpr-447-1988") == "codice-procedura-penale"


def test_query_equivalente_e_riconosciuta_da_lawref():
    import lawref
    for slug, atto in catalogo.CATALOGO.items():
        r = lawref.parse(atto.query("2-bis"))
        assert r and r.articolo == "2-bis", slug
        assert catalogo.slug_di(r) == slug, (slug, r)


# --------------------------------------------------------------- stati HTTP
def test_200_testo_nell_html_senza_javascript():
    _setup()
    r = client.get("/codice-civile/art-2043")
    assert r.status_code == 200
    assert TESTO in r.text                       # il testo e' nell'HTML iniziale
    assert "<h1 id=\"art-title\">Art. 2043 Codice civile — Risarcimento per fatto illecito</h1>" in r.text
    assert "<title>Art. 2043 c.c. — Risarcimento per fatto illecito | Norma Express</title>" in r.text
    assert 'rel="canonical" href="http://testserver/codice-civile/art-2043"' in r.text
    assert 'content="index, follow"' in r.text
    assert "Fa fede la pubblicazione nella Gazzetta Ufficiale" in r.text
    assert r.headers["cache-control"].startswith("public")


def test_un_solo_h1_e_jsonld_valido():
    _setup()
    html = client.get("/codice-civile/art-2043").text
    assert len(re.findall(r"<h1\b", html)) == 1
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    ld = json.loads(m.group(1))
    assert ld["@type"] == "Legislation"
    assert ld["legislationLegalForce"].endswith("InForce")
    ini = json.loads(re.search(r'id="articolo-iniziale">(.*?)</script>', html, re.S).group(1))
    assert ini["payload"]["query"] == "art 2043 codice civile"
    assert ini["art"]["article"]["text"] == TESTO


def test_301_verso_url_canonico():
    _setup()
    for v in ("/cc/art-2043", "/Codice-Civile/art-2043", "/codice-civile/art-2043BIS",
              "/dpr-447-1988/art-1"):
        r = client.get(v, follow_redirects=False)
        assert r.status_code == 301, v
    assert client.get("/cc/art-2043", follow_redirects=False).headers["location"] == \
        "/codice-civile/art-2043"
    assert client.get("/codice-civile/art-2043BIS", follow_redirects=False) \
        .headers["location"] == "/codice-civile/art-2043-bis"


def test_404_atto_o_articolo_non_validi_senza_chiamare_normattiva():
    _setup()
    assert client.get("/pippo/art-1").status_code == 404
    assert client.get("/codice-civile/art-xyz").status_code == 404
    assert CHIAMATE == []


def test_404_articolo_inesistente_e_cache_negativa():
    _setup(fetch=_nontrovato)
    r = client.get("/codice-civile/art-99999")
    assert r.status_code == 404
    assert 'content="noindex, follow"' in r.text
    client.get("/codice-civile/art-99999")
    assert CHIAMATE == ["99999"]                 # la seconda volta: cache negativa


def test_503_se_normattiva_giu_e_nessuna_copia():
    _setup(fetch=_giu)
    r = client.get("/codice-civile/art-2043")
    assert r.status_code == 503
    assert r.headers["retry-after"] == "3600"
    client.get("/codice-civile/art-2043")
    assert CHIAMATE == ["2043", "2043"]          # l'errore transitorio NON va in cache


def test_copia_vecchia_servita_se_normattiva_giu():
    _setup()
    client.get("/codice-civile/art-2043")
    st = cache.store()
    with st._db() as c:                           # copia oltre la finestra stale
        c.execute("UPDATE voci SET fetched_at=?", (time.time() - cache.STALE_MAX - 10,))
    normattiva.fetch_article = _giu
    r = client.get("/codice-civile/art-2043")
    assert r.status_code == 200 and TESTO in r.text


def test_cache_fresca_non_richiama_normattiva():
    _setup()
    client.get("/codice-civile/art-2043")
    client.get("/codice-civile/art-2043")
    assert CHIAMATE == ["2043"]


def test_scaduta_servita_subito_e_riaggiornata():
    _setup()
    client.get("/codice-civile/art-2043")
    st = cache.store()
    with st._db() as c:
        c.execute("UPDATE voci SET fetched_at=?", (time.time() - cache.FRESH - 10,))
    r = client.get("/codice-civile/art-2043")
    assert r.status_code == 200
    st._bg.submit(lambda: None).result(5)          # attende il refresh in background
    assert CHIAMATE == ["2043", "2043"]


def test_lastmod_cambia_solo_se_cambia_il_testo():
    _setup()
    st = cache.store()
    st._save("k", "g", "1", cache.OK, {"text": "a"})
    t1 = st._row("k")["changed_at"]
    time.sleep(0.01)
    st._save("k", "g", "1", cache.OK, {"text": "a"})
    assert st._row("k")["changed_at"] == t1
    st._save("k", "g", "1", cache.OK, {"text": "b"})
    assert st._row("k")["changed_at"] > t1


def test_etag_304():
    _setup()
    r = client.get("/codice-civile/art-2043")
    r2 = client.get("/codice-civile/art-2043", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304


def test_testo_escapato():
    def cattivo(ref):
        return ArticleResult(ok=True, article_heading="Art. 1", permalink="https://x",
                             text='<script>alert(1)</script> "virgolette" </script>')
    _setup(fetch=cattivo)
    html = client.get("/costituzione/art-1").text
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)" in html
    # anche dentro il JSON iniziale nessun </script> che chiuda il blocco
    blocco = re.search(r'id="articolo-iniziale">(.*?)</script>', html, re.S).group(1)
    assert "<" not in blocco


def test_rubrica():
    assert pagine.rubrica("Art. 2043 — (Risarcimento per fatto illecito)") == \
        "Risarcimento per fatto illecito"
    assert pagine.rubrica("Art. 416-bis. Associazioni di tipo mafioso") == \
        "Associazioni di tipo mafioso"
    assert pagine.rubrica("Art. 21") == ""


# ------------------------------------------------------------------ sitemap
def test_sitemap_index_e_per_atto():
    _setup()
    idx = client.get("/sitemap.xml").text
    assert "/sitemaps/home.xml" in idx and "/sitemaps/codice-civile.xml" in idx
    client.get("/codice-civile/art-2044")         # questo e' in cache -> ha lastmod
    sm = client.get("/sitemaps/codice-civile.xml").text
    locs = re.findall(r"<loc>(.*?)</loc>", sm)
    assert locs == ["http://testserver/codice-civile/art-2043",
                    "http://testserver/codice-civile/art-2043-bis",
                    "http://testserver/codice-civile/art-2044"]
    assert sm.count("<lastmod>") == 1
    assert client.get("/sitemaps/legge-241-1990.xml").status_code == 404


def test_sitemap_503_se_indice_irraggiungibile_e_cache_vuota():
    _setup(index=lambda ref: IndexResult(ok=False, network_error=True))
    assert client.get("/sitemaps/codice-penale.xml").status_code == 503


# ---------------------------------------------------------------- home
def test_home_invariata_e_rotte_esistenti():
    _setup()
    h = client.get("/")
    assert h.status_code == 200 and 'content="index, follow"' in h.text
    assert 'id="articolo-iniziale"' not in h.text and "<h1 class=\"brand-title\">" in h.text
    assert 'content="noindex, follow"' in client.get("/?q=art 2043 cc").text
    assert client.get("/assets/style.css").status_code == 200
    assert "Sitemap:" in client.get("/robots.txt").text
    assert client.get("/api/health").json()["status"] == "ok"


# ------------------------------------------- articoli bis/ter (bug 416-bis -> 416)
_FIX = Path(__file__).resolve().parent / "fixtures" / "cp_416_links.html"


def _scelto(articolo):
    url, versioni = _PICK_ORIG(_FIX.read_text(), articolo, "1")
    return url, versioni


def test_bis_ter_scelgono_il_sottoarticolo_giusto_su_link_reali():
    url, v = _scelto("416-bis")
    assert "idArticolo=416&art.idSottoArticolo=2&art.idSottoArticolo1=10" in url, url
    assert "imUpdate" not in url and v == 10          # vigente; 10 versioni del 416-bis
    url, _ = _scelto("416")
    assert "idSottoArticolo=1&" in url, url           # l'articolo base resta il base
    url, _ = _scelto("416-ter")
    assert "idSottoArticolo=3&" in url, url
    assert _scelto("416-quater") == (None, 0)          # non esiste: nessun ripiego sul 416


def test_articolo_coincide_rete_di_sicurezza():
    assert not normattiva.articolo_coincide("Art. 416. (Associazione per delinquere)", "416-bis")
    assert normattiva.articolo_coincide("Art. 416-bis. Associazioni di tipo mafioso", "416-bis")
    assert normattiva.articolo_coincide("Art. 2 bis Conseguenze per il ritardo", "2-bis")
    assert normattiva.articolo_coincide("Art. 21 Tutti hanno diritto", "21")
    assert normattiva.articolo_coincide("Tutti hanno diritto", "21")   # senza "Art.": si accetta
    assert not normattiva.articolo_coincide("Art. 25-undecies (Reati)", "25-duodecies")


def test_rubrica_dal_testo_se_manca_nell_intestazione():
    assert pagine.rubrica("Art. 2043", "Art. 2043. (Risarcimento per fatto illecito). Qualunque") \
        == "Risarcimento per fatto illecito"
    assert pagine.rubrica("Art. 21", "Art. 21 Tutti hanno diritto") == ""
    assert pagine.rubrica("Art. 416-bis", "Art. 416-bis. Associazioni di tipo mafioso") == ""


def test_versione_dati_svuota_la_cache_vecchia():
    path = Path(tempfile.mkdtemp(prefix="ne-ver-")) / "c.sqlite"
    st = cache.Store(path, 0)
    st._save("art:codice-penale:416-bis", "art:codice-penale", "416-bis", cache.OK,
             {"text": "Art. 416. (testo sbagliato)"})
    with st._db() as c:
        c.execute("PRAGMA user_version=1")                # dati della logica vecchia
    st2 = cache.Store(path, 0)
    assert st2._row("art:codice-penale:416-bis") is None


if __name__ == "__main__":
    falliti = 0
    orig = (normattiva.fetch_article, normattiva.fetch_index)
    for nome, fn in sorted(globals().items()):
        if not nome.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("  ok   " + nome)
        except Exception as e:                    # noqa: BLE001
            falliti += 1
            print("  FAIL " + nome + "  " + repr(e))
        finally:
            normattiva.fetch_article, normattiva.fetch_index = orig
    print(("TUTTI I TEST PASSATI" if not falliti else "%d TEST FALLITI" % falliti))
    sys.exit(1 if falliti else 0)
