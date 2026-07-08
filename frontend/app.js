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
  showStatus('<span class="spinner" aria-hidden="true"></span>Ricerca in corso su Normattiva e sul web…');
  setBusy(true);
  try {
    const res = await fetch("/api/ricerca", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      showStatus(`<span class="error-box">${esc(data.error || "Errore nella ricerca.")}</span>`, true);
      return;
    }
    render(data);
    statusEl.classList.add("hidden");
    resultsEl.hidden = false;
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showStatus('<span class="error-box">Impossibile contattare il server. Riprova.</span>', true);
  } finally {
    setBusy(false);
  }
}

function setBusy(b) {
  document.querySelectorAll(".go").forEach((x) => (x.disabled = b));
}

function render(data) {
  renderArticle(data.article);
  renderHits("#interp-list", data.interpretazioni, "Nessuna interpretazione trovata sul web per questa ricerca.");
  renderHits("#giuri-list", data.giurisprudenza, "Nessuna pronuncia trovata sul web. Usa le banche dati ufficiali qui sotto.");
  renderBanche(data.banche_dati);
  $("#disclaimer").textContent = data.disclaimer || "";
  loadSummaries(data);
}

/* Riassunti estrattivi: frasi reali dalle fonti, caricate in modo progressivo. */
async function loadSummaries(data) {
  const take = (hits) => (hits || []).slice(0, 3).map((h) => h.url);
  const interp_urls = take(data.interpretazioni);
  const giuri_urls = take(data.giurisprudenza);
  if (!interp_urls.length && !giuri_urls.length) return;

  // placeholder di caricamento sotto i primi risultati
  [...interp_urls, ...giuri_urls].forEach((u) => {
    document.querySelectorAll(`.hit[data-url="${CSS.escape(u)}"]`).forEach((li) => {
      if (!li.querySelector(".hit-sum")) {
        const p = document.createElement("p");
        p.className = "hit-sum loading";
        p.textContent = "Estraggo il riassunto dalla fonte…";
        li.appendChild(p);
      }
    });
  });

  try {
    const res = await fetch("/api/riassunti", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: data.label || "", interp_urls, giuri_urls }),
    });
    const enr = await res.json();

    // riempi i riassunti
    document.querySelectorAll(".hit-sum.loading").forEach((p) => {
      const li = p.closest(".hit");
      const url = li && li.dataset.url;
      const sum = enr.summaries && enr.summaries[url];
      if (sum) {
        p.classList.remove("loading");
        p.innerHTML = `${esc(sum)} <a class="sum-link" href="${esc(url)}" target="_blank" rel="noopener">Approfondisci alla fonte →</a>`;
      } else {
        p.remove();
      }
    });

    // massime Brocardi in testa alla giurisprudenza
    const bro = enr.brocardi || {};
    if (bro.massime && bro.massime.length) {
      const ul = $("#giuri-list");
      const blocks = bro.massime.map((m) => `
        <li class="massima">
          <span class="massima-ref">${esc(m.ref || "Massima")}</span>
          <p>${esc(m.text)}</p>
          <a class="sum-link" href="${esc(bro.massime_url)}" target="_blank" rel="noopener">Testo integrale e altre massime →</a>
        </li>`).join("");
      ul.insertAdjacentHTML("afterbegin", blocks);
    }
  } catch (err) {
    document.querySelectorAll(".hit-sum.loading").forEach((p) => p.remove());
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
  const ul = $(sel);
  if (!hits || !hits.length) {
    ul.innerHTML = `<li class="empty-note">${esc(emptyMsg)}</li>`;
    return;
  }
  ul.innerHTML = hits.map((h) => {
    const trusted = h.trusted ? " trusted" : "";
    const verified = h.trusted ? '<span class="verified">fonte giuridica</span> · ' : "";
    const snip = h.snippet ? `<p class="snippet">${esc(h.snippet)}</p>` : "";
    return `<li class="hit${trusted}" data-url="${esc(h.url)}">
      <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
      ${snip}
      <span class="src"><span class="dot"></span>${verified}${esc(h.source)}</span>
    </li>`;
  }).join("");
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
