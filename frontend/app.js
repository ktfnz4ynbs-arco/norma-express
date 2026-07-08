"use strict";

const $ = (s) => document.querySelector(s);

// --- Mode toggle ---
const tabs = document.querySelectorAll(".mode-toggle button");
const formFree = $("#form-free");
const formStruct = $("#form-struct");

tabs.forEach((t) => {
  t.addEventListener("click", () => {
    tabs.forEach((x) => { x.classList.remove("active"); x.setAttribute("aria-selected", "false"); });
    t.classList.add("active"); t.setAttribute("aria-selected", "true");
    const free = t.dataset.mode === "free";
    formFree.classList.toggle("hidden", !free);
    formStruct.classList.toggle("hidden", free);
  });
});

// Example chips
document.querySelectorAll(".chip").forEach((c) => {
  c.addEventListener("click", () => {
    $("#q").value = c.dataset.ex;
    formFree.requestSubmit();
  });
});

// --- Submit handlers ---
formFree.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q) return;
  runSearch({ query: q });
});

formStruct.addEventListener("submit", (e) => {
  e.preventDefault();
  const payload = {
    tipo: $("#tipo").value,
    numero: $("#numero").value.trim(),
    anno: $("#anno").value.trim(),
    articolo: $("#art").value.trim(),
  };
  if (!payload.numero || !payload.anno) {
    showStatus('<span class="error-box">Inserisci almeno numero e anno dell\'atto.</span>', true);
    return;
  }
  runSearch(payload);
});

// --- Core ---
const statusEl = $("#status");
const resultsEl = $("#results");

function showStatus(html, isError) {
  statusEl.innerHTML = html;
  statusEl.classList.remove("hidden");
  if (isError) resultsEl.hidden = true;
}

async function runSearch(payload) {
  resultsEl.hidden = true;
  showStatus('<span class="spinner" aria-hidden="true"></span>Recupero l’articolo da Normattiva…');
  setBusy(true);
  try {
    // FASE 1 — prima di tutto: l'articolo preciso della norma
    const resArt = await fetch("/api/articolo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const art = await resArt.json();
    if (!art.ok) {
      showStatus(`<span class="error-box">${esc(art.error || "Errore nella ricerca.")}</span>`, true);
      return;
    }
    renderArticle(art.article);
    setListLoading("#interp-list", "Cerco interpretazioni su fonti gratuite…");
    setListLoading("#giuri-list", "Cerco giurisprudenza su fonti gratuite…");
    $("#banche-links").innerHTML = "";
    $("#disclaimer").textContent = "";
    statusEl.classList.add("hidden");
    resultsEl.hidden = false;
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });

    // FASE 2 — poi il resto: interpretazioni e giurisprudenza
    const resFonti = await fetch("/api/fonti", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const fonti = await resFonti.json();
    if (!fonti.ok) {
      renderHits("#interp-list", [], "Ricerca fonti non riuscita. Usa le banche dati qui sotto.");
      renderHits("#giuri-list", [], "Ricerca fonti non riuscita. Usa le banche dati qui sotto.");
      return;
    }
    renderHits("#interp-list", fonti.interpretazioni, "Nessuna interpretazione trovata su fonti gratuite.");
    renderHits("#giuri-list", fonti.giurisprudenza, "Nessuna pronuncia trovata. Usa le banche dati gratuite qui sotto.");
    renderBanche(fonti.banche_dati);
    $("#disclaimer").textContent = fonti.disclaimer || "";

    // FASE 3 — riassunti estrattivi (approfondimento progressivo)
    loadSummaries(fonti);
  } catch (err) {
    showStatus('<span class="error-box">Impossibile contattare il server. Riprova.</span>', true);
  } finally {
    setBusy(false);
  }
}

function setListLoading(sel, msg) {
  $(sel).innerHTML = `<p class="empty-note loading-note"><span class="spinner" aria-hidden="true"></span>${esc(msg)}</p>`;
}

function setBusy(b) {
  document.querySelectorAll(".go").forEach((x) => (x.disabled = b));
}

/* Riassunti estrattivi di TUTTE le fonti, caricati in modo progressivo:
   riempiono la finestra "Sintesi dalle fonti" di ciascun pannello. */
async function loadSummaries(data) {
  const take = (hits) => (hits || []).map((h) => h.url);
  const interp_urls = take(data.interpretazioni);
  const giuri_urls = take(data.giurisprudenza);
  if (!interp_urls.length && !giuri_urls.length) return;

  try {
    const res = await fetch("/api/riassunti", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: data.label || "", interp_urls, giuri_urls }),
    });
    const enr = await res.json();

    // sostituisci gli snippet provvisori con i riassunti estratti dalle fonti
    document.querySelectorAll(".digest-text.provisional").forEach((p) => {
      const item = p.closest(".digest-item");
      const url = item && item.dataset.url;
      const sum = enr.summaries && enr.summaries[url];
      if (sum) {
        p.classList.remove("provisional");
        p.textContent = sum;
      } else if (p.textContent.trim() === "Riassunto in preparazione…") {
        // nessun riassunto leggibile e nessuno snippet: via dalla sintesi
        item.remove();
      }
    });

    // massime Brocardi in testa alla sintesi della giurisprudenza
    const bro = enr.brocardi || {};
    if (bro.massime && bro.massime.length) {
      const digest = document.querySelector("#giuri-list .digest .block-title");
      if (digest) {
        const blocks = bro.massime.map((m) => `
          <div class="massima">
            <span class="massima-ref">${esc(m.ref || "Massima")}</span>
            <p>${esc(m.text)}</p>
            <a class="sum-link" href="${esc(bro.massime_url)}" target="_blank" rel="noopener">Testo integrale e altre massime →</a>
          </div>`).join("");
        digest.insertAdjacentHTML("afterend", blocks);
      }
    }
  } catch (err) {
    /* in caso di errore restano gli snippet provvisori: comunque leggibili */
  }
}

function renderArticle(a) {
  const card = $("#card-article");
  if (!a) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");

  const title = a.article_heading || a.query_label || a.act_title || "Articolo";
  $("#art-title").textContent = title;

  const meta = [];
  if (a.act_title) meta.push(metaItem("Atto", a.act_title));
  if (a.in_force_from) meta.push(metaItem("In vigore dal", a.in_force_from));
  if (a.versions > 1) meta.push(metaItem("Versioni dell'articolo", `${a.versions} (vigente: ultima)`));
  if (a.abrogato) meta.push('<span class="m-item m-abrogato">⚠ Articolo abrogato</span>');
  $("#art-meta").innerHTML = meta.join("");

  const body = $("#art-body");
  if (a.ok && a.text) {
    body.textContent = a.text;
    body.classList.remove("empty-note");
  } else {
    body.className = "empty-note";
    body.textContent = a.error || "Testo non disponibile. Apri l'atto su Normattiva.";
  }

  const up = $("#art-updates");
  if (a.updates && a.updates.length) {
    up.innerHTML = "<strong>Aggiornamenti:</strong><ul>" +
      a.updates.map((u) => `<li>${esc(u)}</li>`).join("") + "</ul>";
    up.classList.remove("hidden");
  } else {
    up.classList.add("hidden");
  }

  const link = $("#art-link");
  if (a.permalink) { link.href = a.permalink; link.classList.remove("hidden"); }
  else link.classList.add("hidden");
}

function metaItem(label, val) {
  return `<span class="m-item">${esc(label)}: <strong>${esc(val)}</strong></span>`;
}

function renderHits(sel, hits, emptyMsg) {
  const box = $(sel);
  if (!hits || !hits.length) {
    box.innerHTML = `<p class="empty-note">${esc(emptyMsg)}</p>`;
    return;
  }
  // FINESTRA UNICA con i riassunti di tutte le fonti…
  const digest = hits.map((h) => {
    const trusted = h.trusted ? " trusted" : "";
    const provisional = h.snippet || "Riassunto in preparazione…";
    return `<div class="digest-item${trusted}" data-url="${esc(h.url)}">
      <span class="digest-src">${esc(h.source)}</span>
      <p class="digest-text provisional">${esc(provisional)}</p>
    </div>`;
  }).join("");

  // …POI l'elenco delle fonti consultabili (link espliciti)
  const fonti = hits.map((h) => {
    const verified = h.trusted ? ' <span class="verified">· fonte gratuita</span>' : "";
    return `<li>
      <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
      <span class="fonte-dom">${esc(h.source)}${verified}</span>
    </li>`;
  }).join("");

  box.innerHTML = `
    <section class="digest">
      <p class="block-title">Sintesi dalle fonti</p>
      ${digest}
    </section>
    <section class="fonti">
      <p class="block-title">Fonti consultabili</p>
      <ul class="fonti-list">${fonti}</ul>
    </section>`;
}

function renderBanche(links) {
  const box = $("#banche-links");
  if (!links || !links.length) { box.innerHTML = ""; return; }
  box.innerHTML = links.map((l) =>
    `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)}</a>`
  ).join("");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
