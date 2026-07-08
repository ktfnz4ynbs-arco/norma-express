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
let currentLabel = "";

// Approfondimento: domande sull'argomento
$("#form-domanda").addEventListener("submit", (e) => {
  e.preventDefault();
  const d = $("#domanda").value.trim();
  if (d) askQuestion(d);
});

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
    currentLabel = art.label || "";
    $("#sintesi-body").innerHTML =
      '<div class="digest"><div class="digest-unified provisional"><span class="spinner" aria-hidden="true"></span>Sto sintetizzando interpretazione e giurisprudenza…</div></div>';
    $("#massime-body").innerHTML = "";
    $("#fonti-body").innerHTML = '<p class="empty-note loading-note"><span class="spinner" aria-hidden="true"></span>Cerco le fonti gratuite…</p>';
    $("#banche-links").innerHTML = "";
    $("#domanda-risposta").innerHTML = "";
    $("#disclaimer").textContent = "";
    statusEl.classList.add("hidden");
    resultsEl.hidden = false;
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });

    // FASE 2 — le fonti (interpretazione + giurisprudenza), elenco combinato
    const resFonti = await fetch("/api/fonti", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const fonti = await resFonti.json();
    const interp = (fonti.ok && fonti.interpretazioni) || [];
    const giuri = (fonti.ok && fonti.giurisprudenza) || [];
    const combined = dedupeByUrl([...interp, ...giuri]);
    renderFonti(combined);
    renderBanche(fonti.banche_dati);
    $("#disclaimer").textContent = fonti.disclaimer ||
      "Sintesi e fonti provengono da ricerche web su fonti gratuite e vanno verificate. Il testo dell'articolo è tratto da Normattiva. Non costituisce parere legale.";

    // FASE 3 — la sintesi unica (interpretazione + giurisprudenza)
    loadSintesi(interp.map((h) => h.url), giuri.map((h) => h.url));
  } catch (err) {
    showStatus('<span class="error-box">Impossibile contattare il server. Riprova.</span>', true);
  } finally {
    setBusy(false);
  }
}

function dedupeByUrl(hits) {
  const seen = new Set();
  return hits.filter((h) => !seen.has(h.url) && seen.add(h.url));
}

function setBusy(b) {
  document.querySelectorAll(".go").forEach((x) => (x.disabled = b));
}

/* Una sola sintesi estrattiva (interpretazione + giurisprudenza) + massime. */
async function loadSintesi(interp_urls, giuri_urls) {
  if (!interp_urls.length && !giuri_urls.length) {
    fillSintesi("", 0, {});
    return;
  }
  try {
    const res = await fetch("/api/riassunti", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: currentLabel, interp_urls, giuri_urls }),
    });
    const enr = await res.json();
    fillSintesi(enr.sintesi, interp_urls.length + giuri_urls.length, enr.brocardi || {});
  } catch (err) {
    fillSintesi("", interp_urls.length + giuri_urls.length, {});
  }
}

function fillSintesi(sintesi, hasSources, brocardi) {
  const box = document.querySelector("#sintesi-body .digest-unified");
  if (box) {
    box.classList.remove("provisional");
    if (sintesi) {
      box.textContent = sintesi;
    } else if (hasSources) {
      box.innerHTML = '<span class="digest-note">Sintesi automatica non disponibile per questa ricerca. Consulta le fonti qui sotto o fai una domanda.</span>';
    } else {
      box.innerHTML = '<span class="digest-note">Nessuna fonte trovata per la sintesi.</span>';
    }
  }
  const bro = brocardi || {};
  if (bro.massime && bro.massime.length) {
    const blocks = bro.massime.map((m) => `
      <div class="massima">
        <span class="massima-ref">${esc(m.ref || "Massima")}</span>
        <p>${esc(m.text)}</p>
        <a class="sum-link" href="${esc(bro.massime_url)}" target="_blank" rel="noopener">Testo integrale e altre massime →</a>
      </div>`).join("");
    $("#massime-body").innerHTML =
      `<p class="block-title massime-title">Massime della Cassazione</p>${blocks}`;
  }
}

function renderFonti(hits) {
  const box = $("#fonti-body");
  if (!hits || !hits.length) {
    box.innerHTML = '<p class="empty-note">Nessuna fonte gratuita trovata. Usa le banche dati ufficiali qui sotto.</p>';
    return;
  }
  const items = hits.map((h) => {
    const verified = h.trusted ? ' <span class="verified">· fonte gratuita</span>' : "";
    return `<li>
      <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
      <span class="fonte-dom">${esc(h.source)}${verified}</span>
    </li>`;
  }).join("");
  box.innerHTML = `<ul class="fonti-list">${items}</ul>`;
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

/* Approfondimento: risposta ESTRATTIVA a una domanda + rimando alle fonti. */
async function askQuestion(domanda) {
  const box = $("#domanda-risposta");
  box.innerHTML = '<div class="risposta"><p class="digest-unified provisional"><span class="spinner" aria-hidden="true"></span>Cerco la risposta nelle fonti…</p></div>';
  document.querySelectorAll("#form-domanda .go").forEach((b) => (b.disabled = true));
  try {
    const res = await fetch("/api/domanda", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: currentLabel, domanda }),
    });
    const d = await res.json();
    if (!d.ok) {
      box.innerHTML = `<p class="empty-note">${esc(d.error || "Riprova.")}</p>`;
      return;
    }
    const fonti = (d.fonti || []).map((h) =>
      `<li><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
        <span class="fonte-dom">${esc(h.source)}</span></li>`).join("");
    const risposta = d.risposta
      ? `<div class="digest"><p class="block-title">Risposta dalle fonti</p><div class="digest-unified">${esc(d.risposta)}</div></div>`
      : '<p class="empty-note">Non ho trovato un passaggio pertinente. Prova a riformulare o consulta le fonti qui sotto.</p>';
    box.innerHTML = `<div class="risposta">
      <p class="domanda-eco">« ${esc(domanda)} »</p>
      ${risposta}
      ${fonti ? `<p class="block-title fonti-domanda-title">Fonti per approfondire</p><ul class="fonti-list">${fonti}</ul>` : ""}
    </div>`;
  } catch (err) {
    box.innerHTML = '<p class="empty-note">Impossibile contattare il server. Riprova.</p>';
  } finally {
    document.querySelectorAll("#form-domanda .go").forEach((b) => (b.disabled = false));
  }
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
