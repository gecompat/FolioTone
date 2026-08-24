"use strict";

const panels = {
  setup: document.querySelector("#setup-panel"),
  login: document.querySelector("#login-panel"),
  overview: document.querySelector("#overview-panel"),
};

function show(panel) {
  Object.entries(panels).forEach(([name, node]) => { node.hidden = name !== panel; });
}

async function initialise() {
  const setup = await fetch("/api/v1/setup-status", { credentials: "same-origin" });
  if (!setup.ok) { document.querySelector("#surface-status").textContent = "Lokaler Status nicht verfügbar."; return; }
  if ((await setup.json()).setup_required) { show("setup"); return; }
  const session = await fetch("/api/v1/session", { credentials: "same-origin" });
  show(session.ok ? "overview" : "login");
  document.querySelector("#session-action").textContent = session.ok ? "Abmelden" : "Anmelden";
  if (!session.ok) { return; }
  const registry = await fetch("/api/v1/media-lines", { credentials: "same-origin" });
  if (!registry.ok) { document.querySelector("#surface-status").textContent = "Medienlinien nicht verfügbar."; return; }
  const target = document.querySelector("#media-lines");
  (await registry.json()).items.forEach((item) => {
    const entry = document.createElement("li");
    entry.textContent = item.enabled ? item.media_line : `${item.media_line} (noch nicht aktiviert)`;
    target.append(entry);
  });
  document.querySelector("#surface-status").textContent = "Lokale E-Book-Übersicht bereit.";
  await loadList("/api/v1/jobs", "#job-list", "Jobs");
  await loadList("/api/v1/audit-events", "#audit-list", "Audit-Ereignisse");
}

async function request(path, body) {
  const response = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "Origin": location.origin, "X-FolioTone-CSRF": window.csrf || "" }, body: JSON.stringify(body) });
  if (!response.ok) { throw new Error("Anfrage abgelehnt"); }
  return response.json();
}

async function loadList(path, selector, label) {
  const node = document.querySelector(selector);
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok) { node.textContent = `${label} nicht verfügbar.`; return; }
  renderPage(node, await response.json(), label, path);
}

function scalar(value) { return value === null ? "—" : String(value); }

function renderTable(items) {
  const table = document.createElement("table");
  const columns = [...new Set(items.flatMap((item) => Object.keys(item).filter((key) => typeof item[key] !== "object")))];
  const head = document.createElement("tr");
  columns.forEach((column) => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = column; head.append(cell); });
  table.append(head);
  items.forEach((item) => { const row = document.createElement("tr"); columns.forEach((column) => { const cell = document.createElement("td"); cell.textContent = scalar(item[column]); row.append(cell); }); table.append(row); });
  return table;
}

function renderValue(node, value, label) {
  const entries = Object.entries(value).filter(([, item]) => typeof item !== "object");
  if (entries.length) { node.replaceChildren(renderTable([Object.fromEntries(entries)])); return; }
  node.textContent = `${label}: keine anzeigbaren Werte.`;
}

function renderPage(node, payload, label, path) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const content = items.length ? renderTable(items) : document.createTextNode(`${label}: keine Einträge.`);
  node.replaceChildren(content);
  if (!payload.next_cursor) { return; }
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "Nächste Seite";
  next.addEventListener("click", () => loadList(`${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(payload.next_cursor)}`, `#${node.id}`, label));
  node.append(next);
}

async function loadDetail(node, paths, label) {
  node.textContent = "Wird geladen …";
  const responses = await Promise.all(paths.map((path) => fetch(path, { credentials: "same-origin" })));
  if (responses.some((response) => !response.ok)) { node.textContent = `${label} nicht verfügbar.`; return; }
  const values = await Promise.all(responses.map((response) => response.json()));
  const rows = values.map((value, index) => ({ Projektion: paths[index].split("/").at(-1), ...Object.fromEntries(Object.entries(value).filter(([, item]) => typeof item !== "object")) }));
  node.replaceChildren(renderTable(rows));
}

document.querySelector("#setup-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); await request("/api/v1/setup", data); show("login"); });
document.querySelector("#login-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session", Object.fromEntries(new FormData(event.currentTarget))); window.csrf = data.csrf; await initialise(); });
document.querySelector("#reauth-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session/reauth", Object.fromEntries(new FormData(event.currentTarget))); window.csrf = data.csrf; document.querySelector("#surface-status").textContent = "Private Locator sind für diese Session freigegeben."; });
document.querySelector("#search-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); await loadList(`/api/v1/ebooks/collection-states/${encodeURIComponent(data.snapshot)}/search?query=${encodeURIComponent(data.query)}`, "#search-results", "Suche"); });
document.querySelector("#snapshot-details-form").addEventListener("submit", async (event) => { event.preventDefault(); const { snapshot } = Object.fromEntries(new FormData(event.currentTarget)); await loadDetail(document.querySelector("#snapshot-details"), [`/api/v1/ebooks/collection-states/${encodeURIComponent(snapshot)}`, `/api/v1/ebooks/collection-states/${encodeURIComponent(snapshot)}/library-health`], "Snapshot"); });
document.querySelector("#scan-details-form").addEventListener("submit", async (event) => { event.preventDefault(); const { scan_root } = Object.fromEntries(new FormData(event.currentTarget)); await loadDetail(document.querySelector("#scan-details"), [`/api/v1/ebooks/scan-roots/${encodeURIComponent(scan_root)}/status`, `/api/v1/ebooks/scan-roots/${encodeURIComponent(scan_root)}/inventory`], "Scan"); });
document.querySelector("#run-details-form").addEventListener("submit", async (event) => { event.preventDefault(); const { run } = Object.fromEntries(new FormData(event.currentTarget)); await loadDetail(document.querySelector("#run-details"), [`/api/v1/ebooks/collection-runs/${encodeURIComponent(run)}/analysis`, `/api/v1/ebooks/collection-runs/${encodeURIComponent(run)}/evidence`, `/api/v1/ebooks/collection-runs/${encodeURIComponent(run)}/reviews`], "Analyse"); });
document.querySelector("#readiness-action").addEventListener("click", async () => { const node = document.querySelector("#readiness-details"); const response = await fetch("/api/v1/ebooks/readiness", { credentials: "same-origin" }); if (!response.ok) { node.textContent = "Readiness nicht verfügbar."; return; } renderValue(node, await response.json(), "Readiness"); });
document.querySelector("#plans-action").addEventListener("click", async () => loadList("/api/v1/ebooks/plans", "#plan-list", "Nicht ausführbare Pläne"));
document.querySelector("#session-action").addEventListener("click", async () => { if (window.csrf) { await fetch("/api/v1/session", { method: "DELETE", credentials: "same-origin", headers: { "Content-Type": "application/json", "Origin": location.origin, "X-FolioTone-CSRF": window.csrf } }); } location.reload(); });

void initialise();
