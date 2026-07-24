"use strict";

const $ = (s) => document.querySelector(s);

// Mappa url -> {n, source} per numerare le fonti e collegare le citazioni.
let sourceIndex = new Map();

function buildIndex(hits) {
  const map = new Map();
  (hits || []).forEach((h, i) => {
    if (!map.has(h.url)) map.set(h.url, { n: map.size + 1, source: h.source });
  });
  return map;
}

/* Rende una sintesi segmentata con citazioni cliccabili [n] verso la fonte.
   Ogni passaggio è così verificabile aprendo la fonte da cui è estratto. */
function renderSegments(segments, index) {
  if (!segments || !segments.length) return "";
  return segments.map((seg) => {
    const info = index.get(seg.url);
    const label = info ? `[${info.n}]` : (seg.source || "fonte");
    return `${esc(seg.text)}<a class="cite" href="${esc(seg.url)}" target="_blank" rel="noopener" title="Verifica sulla fonte: ${esc(seg.source)}">${esc(label)}</a>`;
  }).join(" ");
}

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

// --- Context switch: Ricerca norma / Fonti istituzionali ---
const resultsIstEl = () => $("#results-ist");
document.querySelectorAll(".ctx-tab").forEach((t) => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".ctx-tab").forEach((x) => {
      x.classList.remove("active"); x.setAttribute("aria-selected", "false");
    });
    t.classList.add("active"); t.setAttribute("aria-selected", "true");
    const ist = t.dataset.ctx === "ist";
    $("#panel-norma").classList.toggle("hidden", ist);
    $("#panel-ist").classList.toggle("hidden", !ist);
    // nascondi i risultati dell'altro contesto
    resultsEl.hidden = true;
    $("#results-ist").hidden = true;
    statusEl.classList.add("hidden");
  });
});

$("#form-ist").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#qi").value.trim();
  if (q) runIstituzionali(q);
});

// --- Submit handlers ---
formFree.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q) return;
  runSearch({ query: q });
});

// La Costituzione non ha numero/anno di atto (URN fisso): nasconde quei
// campi e non li richiede nella validazione.
function syncTipoCostituzione() {
  const isCost = $("#tipo").value === "costituzione";
  $("#field-numero").classList.toggle("hidden", isCost);
  $("#field-anno").classList.toggle("hidden", isCost);
}
$("#tipo").addEventListener("change", syncTipoCostituzione);
syncTipoCostituzione();

formStruct.addEventListener("submit", (e) => {
  e.preventDefault();
  const payload = {
    tipo: $("#tipo").value,
    numero: $("#numero").value.trim(),
    anno: $("#anno").value.trim(),
    articolo: $("#art").value.trim(),
  };
  if (payload.tipo !== "costituzione" && (!payload.numero || !payload.anno)) {
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
  $("#results-ist").hidden = true;
  showStatus('<span class="spinner" aria-hidden="true"></span>Ricerca su Normattiva…');
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
    if (art.mode === "index") {
      renderIndex(art.index);
    } else {
      renderArticle(art.article);
    }
    currentLabel = art.label || "";
    $("#sintesi-body").innerHTML =
      '<div class="digest"><div class="digest-unified provisional"><span class="spinner" aria-hidden="true"></span>Sto sintetizzando interpretazione e giurisprudenza…</div>' +
      '<p class="verify-cap" hidden>Ogni passaggio riporta la fonte <strong>[n]</strong>: clicca per verificarlo.</p></div>';
    $("#massime-body").innerHTML = "";
    $("#penale-body").innerHTML = "";
    $("#fonti-body").innerHTML = '<p class="empty-note loading-note"><span class="spinner" aria-hidden="true"></span>Cerco le fonti gratuite…</p>';
    $("#banche-links").innerHTML = "";
    $("#modelli-list").innerHTML = '<p class="empty-note loading-note"><span class="spinner" aria-hidden="true"></span>Cerco modelli adatti alla norma…</p>';
    $("#modello-form-wrap").classList.add("hidden");
    $("#modello-form-wrap").innerHTML = "";
    $("#modello-output").classList.add("hidden");
    $("#modello-output").innerHTML = "";
    $("#facsimile-body").innerHTML = "";
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
    renderPenale(fonti.cassazione_penale);
    $("#disclaimer").textContent = fonti.disclaimer ||
      "Sintesi e fonti provengono da ricerche web su fonti gratuite e vanno verificate. Il testo dell'articolo è tratto da Normattiva. Non costituisce parere legale.";

    // FASE 3 — la sintesi unica (interpretazione + giurisprudenza)
    loadSintesi(interp.map((h) => h.url), giuri.map((h) => h.url));

    // FASE 4 — modelli di atti che si adattano alla norma (non bloccante)
    loadModelli(payload);
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

/* ---- Fonti istituzionali: GU, Parlamento, Regionale (contesto separato) ---- */
async function runIstituzionali(query) {
  resultsEl.hidden = true;
  $("#results-ist").hidden = true;
  showStatus('<span class="spinner" aria-hidden="true"></span>Cerco su Gazzetta Ufficiale, Parlamento e portali regionali…');
  setBusy(true);
  try {
    const res = await fetch("/api/istituzionali", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const d = await res.json();
    if (!d.ok) {
      showStatus(`<span class="error-box">${esc(d.error || "Errore nella ricerca.")}</span>`, true);
      return;
    }
    fillIst("#gu-body", d.gazzetta);
    fillIst("#parl-body", d.parlamento);
    fillIst("#reg-body", d.regionale);
    $("#disclaimer-ist").textContent = d.disclaimer || "";
    statusEl.classList.add("hidden");
    $("#results-ist").hidden = false;
    $("#results-ist").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showStatus('<span class="error-box">Impossibile contattare il server. Riprova.</span>', true);
  } finally {
    setBusy(false);
  }
}

function fillIst(sel, ctx) {
  const box = $(sel);
  const results = (ctx && ctx.results) || [];
  const portali = (ctx && ctx.portali) || [];
  const list = results.length
    ? `<ul class="ist-list">${results.map((h) => {
        const snip = h.snippet ? `<p class="ist-snip">${esc(h.snippet)}</p>` : "";
        return `<li>
          <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
          ${snip}
          <span class="fonte-dom">${esc(h.source)}</span>
        </li>`;
      }).join("")}</ul>`
    : '<p class="empty-note">Nessun risultato trovato per questa fonte. Prova con altre parole chiave o apri il portale ufficiale.</p>';
  const portalLinks = portali.map((p) =>
    `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)} →</a>`
  ).join("");
  box.innerHTML = list +
    `<div class="ist-portali"><span class="ist-portali-label">Portale ufficiale:</span>${portalLinks}</div>`;
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
    const html = renderSegments(sintesi, sourceIndex);
    if (html) {
      box.innerHTML = html;
      const cap = document.querySelector("#sintesi-body .verify-cap");
      if (cap) cap.hidden = false;
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

/* Giurisprudenza penale recente segnalata (dataset open source
   Synthos-Logic/cassazione-penale-db, aggiornato settimanalmente
   dall'Ufficio del Massimario): best-effort, solo per ricerche penali. */
function renderPenale(hits) {
  const box = $("#penale-body");
  if (!hits || !hits.length) { box.innerHTML = ""; return; }
  const blocks = hits.map((h) => `
    <div class="massima massima-penale">
      <span class="massima-ref">${esc(h.citazione)}${h.materia ? ` · ${esc(h.materia)}` : ""}</span>
      <p>${esc(h.massima)}</p>
      <a class="sum-link" href="${esc(h.url_pdf || h.url_scheda)}" target="_blank" rel="noopener">PDF autentico della pronuncia →</a>
    </div>`).join("");
  box.innerHTML = `<p class="block-title massime-title">Giurisprudenza penale recente segnalata (Cassazione)</p>${blocks}`;
}

function renderFonti(hits) {
  const box = $("#fonti-body");
  sourceIndex = buildIndex(hits);
  if (!hits || !hits.length) {
    box.innerHTML = '<p class="empty-note">Nessuna fonte gratuita trovata. Usa le banche dati ufficiali qui sotto.</p>';
    return;
  }
  const items = hits.map((h) => {
    const n = sourceIndex.get(h.url)?.n;
    const verified = h.trusted ? ' <span class="verified">· fonte gratuita</span>' : "";
    return `<li id="fonte-${n}">
      <span class="fonte-n">[${n}]</span>
      <span class="fonte-main">
        <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
        <span class="fonte-dom">${esc(h.source)}${verified}</span>
      </span>
    </li>`;
  }).join("");
  box.innerHTML = `<ul class="fonti-list numbered">${items}</ul>`;
}

/* ---- Modelli di atti che si adattano alla norma (nessuna AI: motore a
   regole in modelli.py, ispirato al document-assembly open source
   Docassemble) + fac-simile reali trovati sul web ---- */
let modelliCache = new Map();

async function loadModelli(payload) {
  try {
    const res = await fetch("/api/modelli", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    renderModelli((d.ok && d.templates) || []);
    renderFacsimile((d.ok && d.facsimile_web) || []);
  } catch (err) {
    renderModelli([]);
    renderFacsimile([]);
  }
}

function renderModelli(templates) {
  const box = $("#modelli-list");
  modelliCache = new Map(templates.map((t) => [t.id, t]));
  if (!templates.length) {
    box.innerHTML = '<p class="empty-note">Nessun modello del catalogo interno è pertinente a questa norma. Guarda i fac-simile trovati sul web qui sotto, se presenti.</p>';
    return;
  }
  box.innerHTML = `<div class="voci modelli-voci">${templates.map((t) =>
    `<button type="button" class="voce modello-voce" data-id="${esc(t.id)}" title="${esc(t.descrizione)}">${esc(t.titolo)}</button>`
  ).join("")}</div>`;
  box.querySelectorAll(".modello-voce").forEach((b) => {
    b.addEventListener("click", () => renderModelloForm(modelliCache.get(b.dataset.id)));
  });
}

function renderModelloForm(t) {
  if (!t) return;
  const wrap = $("#modello-form-wrap");
  const today = new Date().toISOString().slice(0, 10);
  const fieldsHtml = t.fields.map((f) => {
    const id = `mf-${f.name}`;
    const req = f.required ? " *" : "";
    const val = (f.type === "date" && f.name === "data") ? today
      : (f.name === "riferimento_normativo") ? currentLabel
      : (f.default || "");
    const inputType = f.type === "number" ? "number" : f.type === "date" ? "date" : "text";
    const control = f.type === "textarea"
      ? `<textarea id="${id}" name="${esc(f.name)}" rows="3" placeholder="${esc(f.placeholder)}">${esc(val)}</textarea>`
      : `<input id="${id}" name="${esc(f.name)}" type="${inputType}" placeholder="${esc(f.placeholder)}" value="${esc(val)}" />`;
    const wideClass = f.type === "textarea" ? " mf-field-wide" : "";
    return `<div class="field mf-field${wideClass}"><label for="${id}">${esc(f.label)}${req}</label>${control}</div>`;
  }).join("");
  wrap.innerHTML = `
    <div class="modello-form-head">
      <p class="block-title">${esc(t.titolo)}</p>
      <span class="modello-norma">${esc(t.norma)}</span>
    </div>
    <p class="modello-desc">${esc(t.descrizione)}</p>
    <form id="form-modello" class="mf-grid" autocomplete="off">
      ${fieldsHtml}
      <button type="submit" class="go full">Genera bozza</button>
    </form>`;
  wrap.classList.remove("hidden");
  $("#modello-output").classList.add("hidden");
  $("#modello-output").innerHTML = "";
  $("#form-modello").addEventListener("submit", (e) => {
    e.preventDefault();
    const valori = {};
    t.fields.forEach((f) => { valori[f.name] = $(`#mf-${f.name}`).value.trim(); });
    compilaModello(t.id, valori);
  });
  wrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function compilaModello(templateId, valori) {
  const out = $("#modello-output");
  out.classList.remove("hidden");
  out.innerHTML = '<p class="empty-note loading-note"><span class="spinner" aria-hidden="true"></span>Compilo la bozza…</p>';
  try {
    const res = await fetch("/api/modelli/compila", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: templateId, valori }),
    });
    const d = await res.json();
    if (!d.ok) {
      out.innerHTML = `<p class="empty-note">${esc(d.error || "Impossibile compilare il modello.")}</p>`;
      return;
    }
    const warn = (d.campi_mancanti && d.campi_mancanti.length)
      ? `<p class="modello-warn">Campi non compilati (segnati tra parentesi quadre nel testo): ${d.campi_mancanti.map(esc).join(", ")}</p>`
      : "";
    out.innerHTML = `
      ${warn}
      <textarea id="modello-testo" class="modello-testo" rows="14" readonly>${esc(d.testo)}</textarea>
      <div class="modello-actions">
        <button type="button" class="go" id="modello-copia">Copia negli appunti</button>
        <button type="button" class="go" id="modello-scarica">Scarica .txt</button>
      </div>
      <p class="modello-caveat">Bozza compilata dai dati inseriti (nessuna AI): va sempre controllata da un professionista prima dell'uso.</p>`;
    $("#modello-copia").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(d.testo);
        const btn = $("#modello-copia");
        btn.textContent = "Copiato ✓";
        setTimeout(() => { btn.textContent = "Copia negli appunti"; }, 1800);
      } catch (err) { /* clipboard non disponibile: selezione manuale */ }
    });
    $("#modello-scarica").addEventListener("click", () => {
      const blob = new Blob([d.testo], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${templateId}.txt`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
    out.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    out.innerHTML = '<p class="empty-note">Impossibile contattare il server. Riprova.</p>';
  }
}

function renderFacsimile(hits) {
  const box = $("#facsimile-body");
  if (!hits || !hits.length) { box.innerHTML = ""; return; }
  const items = hits.map((h) => `
    <li>
      <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
      <span class="fonte-dom">${esc(h.source)}</span>
    </li>`).join("");
  box.innerHTML = `<p class="block-title modelli-web-title">Fac-simile trovati sul web</p><ul class="fonti-list">${items}</ul>`;
}

function renderArticle(a) {
  $("#card-index").classList.add("hidden");
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

  renderVigenza(a);
}

/* Multivigenza: apre il testo dell'articolo a una data storica su Normattiva. */
function renderVigenza(a) {
  const box = $("#art-vigenza");
  if (!box) return;
  if (!a.permalink) { box.innerHTML = ""; return; }
  const base = a.permalink.split("!vig=")[0];
  const preset = a.vigenza || "";
  box.innerHTML = `
    <span class="vig-label">📅 Testo a una data (multivigenza):</span>
    <input type="date" id="vig-date" class="vig-date" value="${esc(preset)}" max="${new Date().toISOString().slice(0,10)}" />
    <button type="button" id="vig-go" class="vig-go">Apri versione storica →</button>`;
  const openHist = () => {
    const d = $("#vig-date").value;
    if (d) window.open(base + "!vig=" + d, "_blank", "noopener");
  };
  $("#vig-go").addEventListener("click", openHist);
  if (preset) {
    box.insertAdjacentHTML("beforeend",
      `<p class="vig-note">Nella tua ricerca hai indicato una data: il testo qui sopra è quello <strong>vigente oggi</strong>; apri la versione al ${esc(preset)} per il testo storico.</p>`);
  }
}

function metaItem(label, val) {
  return `<span class="m-item">${esc(label)}: <strong>${esc(val)}</strong></span>`;
}

/* Indice della legge: partizioni + voci-articolo cliccabili (navigazione). */
function renderIndex(idx) {
  $("#card-article").classList.add("hidden");
  const card = $("#card-index");
  card.classList.remove("hidden");

  $("#index-title").textContent =
    `${idx.act_title || "Indice della legge"} · ${idx.total} articoli`;

  const groups = (idx.groups || []).map((g) => {
    const chips = g.articles.map((a) =>
      `<button type="button" class="voce" data-q="${esc(a.q)}">Art. ${esc(a.num)}</button>`
    ).join("");
    const head = g.partition
      ? `<p class="index-part">${esc(g.partition)}</p>` : "";
    return `<div class="index-group">${head}<div class="voci">${chips}</div></div>`;
  }).join("");
  $("#index-body").innerHTML = groups;

  const link = $("#index-link");
  if (idx.permalink) { link.href = idx.permalink; link.classList.remove("hidden"); }
  else link.classList.add("hidden");

  // click su una voce -> apre quell'articolo
  $("#index-body").querySelectorAll(".voce").forEach((b) => {
    b.addEventListener("click", () => {
      const q = b.dataset.q;
      $("#q").value = q;
      // torna alla modalità libera e cerca
      const freeTab = document.querySelector('.mode-toggle [data-mode="free"]');
      if (freeTab) freeTab.click();
      $("#form-free").requestSubmit();
    });
  });
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
    const idx = buildIndex(d.fonti);
    const fonti = (d.fonti || []).map((h) => {
      const n = idx.get(h.url)?.n;
      return `<li id="dfonte-${n}"><span class="fonte-n">[${n}]</span>
        <span class="fonte-main"><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
        <span class="fonte-dom">${esc(h.source)}</span></span></li>`;
    }).join("");
    const html = renderSegments(d.risposta, idx);
    const risposta = html
      ? `<div class="digest"><p class="block-title">Risposta dalle fonti</p><div class="digest-unified">${html}</div></div>`
      : '<p class="empty-note">Non ho trovato un passaggio pertinente. Prova a riformulare o consulta le fonti qui sotto.</p>';
    box.innerHTML = `<div class="risposta">
      <p class="domanda-eco">« ${esc(domanda)} »</p>
      ${risposta}
      ${fonti ? `<p class="block-title fonti-domanda-title">Fonti per approfondire</p><ul class="fonti-list numbered">${fonti}</ul>` : ""}
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

/* --- Deep-link & modalità incorporata (embed) ---
   Permette di aprire l'app già su una ricerca precisa (?q=...) e in versione
   compatta (?embed=1). Serve per incorporarla DAL VIVO in un iframe (es. la
   scheda "Fonti Normattiva" di POL·PEN Assistant, pre-caricata sulla norma del
   caso): così l'incorporamento resta sempre allineato a questa app e ogni
   miglioria di Norma Express vi appare automaticamente. */
(function initFromUrl() {
  const params = new URLSearchParams(location.search);
  if (params.get("embed") === "1") document.body.classList.add("embed");
  const q = (params.get("q") || "").trim();
  if (q) {
    const freeTab = document.querySelector('.mode-toggle [data-mode="free"]');
    if (freeTab) freeTab.click();
    $("#q").value = q;
    formFree.requestSubmit();
  }
})();
