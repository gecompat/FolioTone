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
  const list = document.createElement("ul");
  (await response.json()).items.forEach((item) => { const row = document.createElement("li"); row.textContent = Object.values(item).filter((value) => typeof value !== "object").join(" · "); list.append(row); });
  node.replaceChildren(list);
}

document.querySelector("#setup-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); await request("/api/v1/setup", data); show("login"); });
document.querySelector("#login-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session", Object.fromEntries(new FormData(event.currentTarget))); window.csrf = data.csrf; await initialise(); });
document.querySelector("#reauth-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session/reauth", Object.fromEntries(new FormData(event.currentTarget))); window.csrf = data.csrf; document.querySelector("#surface-status").textContent = "Private Locator sind für diese Session freigegeben."; });
document.querySelector("#search-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); const response = await fetch(`/api/v1/ebooks/collection-states/${encodeURIComponent(data.snapshot)}/search?query=${encodeURIComponent(data.query)}`, { credentials: "same-origin" }); const node = document.querySelector("#search-results"); node.textContent = response.ok ? "Begrenzte Treffer geladen." : "Suche nicht verfügbar."; });
document.querySelector("#session-action").addEventListener("click", async () => { if (window.csrf) { await fetch("/api/v1/session", { method: "DELETE", credentials: "same-origin", headers: { "Content-Type": "application/json", "Origin": location.origin, "X-FolioTone-CSRF": window.csrf } }); } location.reload(); });

void initialise();
