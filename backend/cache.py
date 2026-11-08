"""
Cache persistente (SQLite) per le pagine server-rendered.

Perche' esiste: ogni visita di Googlebot a una pagina articolo costerebbe 2 richieste
a Normattiva. Con migliaia di pagine, senza cache, l'IP di Railway verrebbe bloccato.

Politica:
- FRESCO (< 7 giorni): servito cosi' com'e'.
- SCADUTO (7-180 giorni): servito SUBITO e riaggiornato in background
  (stale-while-revalidate): Googlebot non aspetta mai Normattiva per una pagina gia' vista.
- MANCANTE o troppo vecchio: richiesta sincrona. Se Normattiva non risponde si usa
  comunque l'eventuale copia vecchia; senza copia -> "unavailable" (pagina 503).
- "Non trovato" e' cache negativa per 24 ore.
- changed_at cambia SOLO se cambia l'hash del testo: e' il lastmod reale della sitemap.

Freno verso Normattiva: un recupero alla volta, distanziati di FETCH_INTERVAL secondi
(ogni recupero = 2 richieste HTTP), e single-flight per chiave.

DATA_DIR: cartella del database. Su Railway = volume montato (es. /data); senza volume
la cache si azzera a ogni deploy.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

FRESH = 7 * 86400
STALE_MAX = 180 * 86400
NEG_TTL = 86400
FETCH_INTERVAL = float(os.environ.get("NORMATTIVA_FETCH_INTERVAL", "2.0"))
MAX_WAIT = 20.0          # oltre: meglio un 503 subito che far aspettare il crawler

OK, NOTFOUND, UNAVAILABLE = "ok", "notfound", "unavailable"

# Da incrementare quando cambia il modo di estrarre gli articoli da Normattiva.
# v2 (2026-11-08): gli articoli bis/ter/... restituivano l'articolo base.
VERSIONE_DATI = 2


def _data_dir() -> Path:
    d = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


class Busy(Exception):
    """Coda verso Normattiva troppo lunga."""


class _Limiter:
    def __init__(self, interval: float):
        self.interval = interval
        self.lock = threading.Lock()
        self.next_at = 0.0

    def acquire(self, max_wait: float = MAX_WAIT):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            if start - now > max_wait:
                raise Busy()
            self.next_at = start + self.interval
        if start > now:
            time.sleep(start - now)


class Store:
    def __init__(self, path: Optional[Path] = None, interval: float = FETCH_INTERVAL):
        self.path = str(path or _data_dir() / "cache.sqlite")
        self.limiter = _Limiter(interval)
        self._inflight: dict[str, threading.Event] = {}
        self._inflight_lock = threading.Lock()
        self._bg = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refresh")
        with self._db() as c:
            c.execute("PRAGMA journal_mode=WAL")
            # Versione dei dati: se cambia l'ESTRAZIONE (es. fix 416-bis -> 416, v2), le
            # copie salvate con la logica vecchia possono essere sbagliate: si buttano.
            if c.execute("PRAGMA user_version").fetchone()[0] < VERSIONE_DATI:
                c.execute("DROP TABLE IF EXISTS voci")
                c.execute(f"PRAGMA user_version={VERSIONE_DATI}")
            c.execute("""CREATE TABLE IF NOT EXISTS voci(
                chiave TEXT PRIMARY KEY, gruppo TEXT, sotto TEXT, json TEXT,
                sha TEXT, status TEXT, fetched_at REAL, changed_at REAL)""")
            c.execute("CREATE INDEX IF NOT EXISTS voci_gruppo ON voci(gruppo, status)")

    def _db(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ------------------------------------------------------------------ lettura
    def _row(self, chiave: str) -> Optional[sqlite3.Row]:
        with self._db() as c:
            return c.execute("SELECT * FROM voci WHERE chiave=?", (chiave,)).fetchone()

    def gruppo(self, gruppo: str, status: str = OK) -> list[sqlite3.Row]:
        with self._db() as c:
            return c.execute("SELECT sotto, changed_at FROM voci WHERE gruppo=? AND status=?",
                             (gruppo, status)).fetchall()

    # ---------------------------------------------------------------- scrittura
    def _save(self, chiave, gruppo, sotto, status, data):
        now = time.time()
        js = json.dumps(data, ensure_ascii=False) if data is not None else None
        sha = hashlib.sha256(js.encode()).hexdigest() if js else None
        with self._db() as c:
            old = c.execute("SELECT sha, changed_at FROM voci WHERE chiave=?",
                            (chiave,)).fetchone()
            changed = old["changed_at"] if old and old["sha"] == sha else now
            c.execute("""INSERT OR REPLACE INTO voci
                (chiave, gruppo, sotto, json, sha, status, fetched_at, changed_at)
                VALUES (?,?,?,?,?,?,?,?)""", (chiave, gruppo, sotto, js, sha, status,
                                               now, changed))

    # ------------------------------------------------------------------ recupero
    def _fetch(self, chiave, gruppo, sotto, fetcher, max_wait=MAX_WAIT) -> tuple[str, Optional[dict]]:
        """Esegue fetcher() una sola volta per chiave anche con richieste concorrenti.

        fetcher -> (status, data): status in OK / NOTFOUND / UNAVAILABLE.
        """
        with self._inflight_lock:
            ev = self._inflight.get(chiave)
            owner = ev is None
            if owner:
                ev = self._inflight[chiave] = threading.Event()
        if not owner:
            ev.wait(max_wait + 30)
            row = self._row(chiave)
            if row and row["status"] in (OK, NOTFOUND):
                return row["status"], json.loads(row["json"]) if row["json"] else None
            return UNAVAILABLE, None
        try:
            self.limiter.acquire(max_wait)
            status, data = fetcher()
            if status in (OK, NOTFOUND):
                self._save(chiave, gruppo, sotto, status, data if status == OK else None)
            return status, data
        except Busy:
            return UNAVAILABLE, None
        except Exception:                      # mai un 500 per un problema a monte
            return UNAVAILABLE, None
        finally:
            with self._inflight_lock:
                self._inflight.pop(chiave, None)
            ev.set()

    def get(self, chiave: str, gruppo: str, sotto: str,
            fetcher: Callable[[], tuple[str, Optional[dict]]]) -> dict:
        """-> {status, data, fetched_at, changed_at, stale}"""
        row = self._row(chiave)
        now = time.time()
        if row:
            age = now - row["fetched_at"]
            ttl = FRESH if row["status"] == OK else NEG_TTL
            data = json.loads(row["json"]) if row["json"] else None
            hit = {"status": row["status"], "data": data, "fetched_at": row["fetched_at"],
                   "changed_at": row["changed_at"], "stale": age >= ttl}
            if age < ttl:
                return hit
            if row["status"] == OK and age < STALE_MAX:
                self._bg.submit(self._fetch, chiave, gruppo, sotto, fetcher, 3600)
                return hit
        status, data = self._fetch(chiave, gruppo, sotto, fetcher)
        if status == UNAVAILABLE and row and row["status"] == OK:
            return {"status": OK, "data": json.loads(row["json"]),
                    "fetched_at": row["fetched_at"], "changed_at": row["changed_at"],
                    "stale": True}
        new = self._row(chiave)
        return {"status": status, "data": data,
                "fetched_at": new["fetched_at"] if new else now,
                "changed_at": new["changed_at"] if new else now, "stale": False}


_store: Optional[Store] = None
_store_lock = threading.Lock()


def store() -> Store:
    global _store
    with _store_lock:
        if _store is None:
            _store = Store()
        return _store


def reset(path: Optional[Path] = None, interval: float = 0.0) -> Store:
    """Per i test: store nuovo su un file dato, senza attese."""
    global _store
    with _store_lock:
        _store = Store(path, interval)
        return _store
