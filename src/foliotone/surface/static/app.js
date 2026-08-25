"use strict";

const panels = {
  setup: document.querySelector("#setup-panel"),
  login: document.querySelector("#login-panel"),
  overview: document.querySelector("#overview-panel"),
};
const fixityPrivate = { active: false };
const fixityReview = { active: false };
const actionKeys = new WeakMap();

function show(panel) {
  Object.entries(panels).forEach(([name, node]) => { node.hidden = name !== panel; });
}

function scalar(value) { return value == null ? "—" : String(value); }

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

function clearFixityPrivateValues(message = "Private Werte sind gesperrt.") {
  fixityPrivate.active = false;
  document.querySelector("#fixity-private-grant-status").textContent = message;
  document.querySelector("#fixity-private-entries").replaceChildren();
  document.querySelector("#fixity-private-result").replaceChildren();
}

function setCsrf(csrf) {
  window.csrf = csrf;
  fixityReview.active = false;
  clearFixityPrivateValues("Private Werte wurden nach dem Sessionwechsel entfernt.");
}

class SurfaceRequestError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}

function germanError(error, fallback) {
  const codes = {
    FIXITY_BASELINE_ACTIVATION_REJECTED: "Die Baseline-Aktivierung wurde abgelehnt.",
    FIXITY_EXPECTATION_REJECTED: "Die Einzelrevision wurde abgelehnt.",
    FIXITY_REVIEW_REJECTED: "Die Review-Entscheidung wurde abgelehnt.",
    REAUTH_REJECTED: "Die erneute Passwortprüfung wurde abgelehnt.",
  };
  const text = codes[error.code] || fallback;
  return error.code ? `${text} Code: ${error.code}.` : text;
}

function actionKey(form, signature) {
  const current = actionKeys.get(form);
  if (current && current.signature === signature) { return current.key; }
  const key = crypto.randomUUID();
  actionKeys.set(form, { signature, key });
  return key;
}

function finishAction(form) { actionKeys.delete(form); }

async function responseJson(response) {
  if (response.ok) { return response.json(); }
  if (response.status === 401 || response.status === 403) {
    clearFixityPrivateValues("Die private Freigabe ist nicht aktiv oder abgelaufen; angezeigte Werte wurden entfernt.");
  }
  let code = "";
  try { code = (await response.json()).code || ""; } catch { code = ""; }
  throw new SurfaceRequestError(response.status, code);
}

async function request(path, body, idempotency = false) {
  const headers = { "Content-Type": "application/json", "Origin": location.origin, "X-FolioTone-CSRF": window.csrf || "" };
  if (idempotency) { headers["Idempotency-Key"] = typeof idempotency === "string" ? idempotency : crypto.randomUUID(); }
  return responseJson(await fetch(path, { method: "POST", credentials: "same-origin", headers, body: JSON.stringify(body) }));
}

async function getJson(path) {
  return responseJson(await fetch(path, { credentials: "same-origin" }));
}

function publicSearchItems(payload) {
  if (!Array.isArray(payload.hits)) { return []; }
  return payload.hits.map((hit) => ({
    file_id: hit.file_id,
    observation_id: hit.observation_id,
    format: hit.format,
    statuses: Object.entries(hit.statuses || {}).map(([component, status]) => `${component}: ${status}`).join(", "),
  }));
}

function renderPage(node, payload, label, path, collection = "items") {
  const items = Array.isArray(payload[collection]) ? payload[collection] : publicSearchItems(payload);
  node.replaceChildren(items.length ? renderTable(items) : document.createTextNode(`${label}: keine Einträge.`));
  if (!payload.next_cursor) { return; }
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "Nächste Seite";
  next.addEventListener("click", () => renderGetPage(`${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(payload.next_cursor)}`, node, label, collection));
  node.append(next);
}

async function renderGetPage(path, node, label, collection = "items") {
  try { renderPage(node, await getJson(path), label, path, collection); } catch { node.textContent = `${label} nicht verfügbar.`; }
}

async function loadList(path, selector, label) {
  await renderGetPage(path, document.querySelector(selector), label);
}

async function loadDetail(node, paths, label) {
  node.textContent = "Wird geladen …";
  try {
    const values = await Promise.all(paths.map((path) => getJson(path)));
    const rows = values.map((value, index) => ({ Projektion: paths[index].split("/").at(-1), ...Object.fromEntries(Object.entries(value).filter(([, item]) => typeof item !== "object")) }));
    node.replaceChildren(renderTable(rows));
  } catch { node.textContent = `${label} nicht verfügbar.`; }
}

function selectFixityReview(resultId) {
  document.querySelector("#fixity-review-form [name=result_id]").value = resultId;
  document.querySelector("#fixity-review-form [name=decision]").focus();
}

function updateFixityConfirmationInstruction(manifestId) {
  const instruction = document.querySelector("#fixity-confirmation-instruction");
  instruction.textContent = manifestId
    ? `Exakte Bestätigung: ACCEPT FIXITY BASELINE ${manifestId}`
    : "Gib nach Auswahl eines Manifests die exakte Bestätigung ein.";
}

function requireFixityReview(node) {
  if (fixityReview.active) { return true; }
  node.textContent = "Diese Aktion benötigt zuerst eine REVIEW-Reauthentisierung.";
  return false;
}

function selectFixityExpectation(resultId, result) {
  const form = document.querySelector("#fixity-expectation-form");
  const select = form.querySelector("[name=action]");
  const action = result === "MISSING" ? "RETIRE_MISSING" : "ACCEPT_CURRENT";
  form.querySelector("[name=result_id]").value = resultId;
  select.replaceChildren();
  const option = document.createElement("option");
  option.value = action;
  option.textContent = action === "RETIRE_MISSING" ? "Fehlende Erwartung einzeln ausmustern" : "Aktuelle Bytes einzeln akzeptieren";
  select.append(option);
  select.disabled = false;
  form.querySelector("button").disabled = false;
  select.focus();
}

function renderFixityResults(node, payload, path) {
  const items = Array.isArray(payload.results) ? payload.results : [];
  const table = document.createElement("table");
  const header = document.createElement("tr");
  ["Ergebnis-ID", "Datei-ID", "Befund", "Fehlercode", "Aktion"].forEach((text) => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = text; header.append(cell); });
  table.append(header);
  items.forEach((item) => {
    const row = document.createElement("tr");
    [item.result_id, item.file_id, item.result, item.failure_code].forEach((value) => { const cell = document.createElement("td"); cell.textContent = scalar(value); row.append(cell); });
    const actions = document.createElement("td");
    const review = document.createElement("button");
    review.type = "button"; review.textContent = "Review auswählen";
    review.addEventListener("click", () => selectFixityReview(item.result_id));
    actions.append(review);
    if (["UNEXPECTED_BYTE_CHANGE", "UNBASELINED", "MISSING"].includes(item.result)) {
      const revise = document.createElement("button");
      revise.type = "button"; revise.textContent = "Passende Revision auswählen";
      revise.addEventListener("click", () => selectFixityExpectation(item.result_id, item.result));
      actions.append(revise);
    }
    row.append(actions); table.append(row);
  });
  node.replaceChildren(items.length ? table : document.createTextNode("Öffentliche Ergebnisse: keine Einträge."));
  if (!payload.next_cursor) { return; }
  const next = document.createElement("button");
  next.type = "button"; next.textContent = "Nächste Seite";
  next.addEventListener("click", () => loadFixityResults(`${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(payload.next_cursor)}`));
  node.append(next);
}

async function loadFixityResults(path) {
  const node = document.querySelector("#fixity-results");
  try { renderFixityResults(node, await getJson(path), path); } catch { node.textContent = "Öffentliche Ergebnisse nicht verfügbar."; }
}

function renderPrivateBaselineEntries(node, payload, path) {
  const rows = (payload.entries || []).map((entry) => ({ Datei_ID: entry.file_id, relativer_Locator: entry.relative_locator, Größe_Bytes: entry.size_bytes, SHA_256: entry.sha256 }));
  node.replaceChildren(rows.length ? renderTable(rows) : document.createTextNode("Private Baseline-Einträge: keine Einträge."));
  if (!payload.next_cursor) { return; }
  const next = document.createElement("button");
  next.type = "button"; next.textContent = "Nächste Seite";
  next.addEventListener("click", () => loadPrivateBaselineEntries(`${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(payload.next_cursor)}`));
  node.append(next);
}

async function loadPrivateBaselineEntries(path) {
  const node = document.querySelector("#fixity-private-entries");
  try { renderPrivateBaselineEntries(node, await getJson(path), path); } catch (error) { if (fixityPrivate.active) { node.textContent = germanError(error, "Private Baseline-Einträge nicht verfügbar."); } }
}

function renderPrivateResult(node, item) {
  node.replaceChildren(renderTable([
    { Zustand: "Erwartet", Beobachtung_ID: item.expected.observation_id, relativer_Locator: item.expected.relative_locator, Größe_Bytes: item.expected.size_bytes, SHA_256: item.expected.sha256 },
    { Zustand: "Aktuell", Beobachtung_ID: item.current.observation_id, relativer_Locator: item.current.relative_locator, Größe_Bytes: item.current.size_bytes, SHA_256: item.current.sha256 },
  ]));
}

async function initialise() {
  let setup;
  try { setup = await getJson("/api/v1/setup-status"); } catch { document.querySelector("#surface-status").textContent = "Lokaler Status nicht verfügbar."; return; }
  if (setup.setup_required) { show("setup"); return; }
  try { await getJson("/api/v1/session"); } catch (error) {
    show("login");
    document.querySelector("#session-action").textContent = "Anmelden";
    if (error.status !== 401 && error.status !== 403) { document.querySelector("#surface-status").textContent = "Sitzungsstatus nicht verfügbar."; }
    return;
  }
  show("overview");
  document.querySelector("#session-action").textContent = "Abmelden";
  let registry;
  try { registry = await getJson("/api/v1/media-lines"); } catch { document.querySelector("#surface-status").textContent = "Medienlinien nicht verfügbar."; return; }
  const target = document.querySelector("#media-lines");
  target.replaceChildren();
  registry.items.forEach((item) => { const entry = document.createElement("li"); entry.textContent = item.enabled ? item.media_line : `${item.media_line} (noch nicht aktiviert)`; target.append(entry); });
  document.querySelector("#surface-status").textContent = "Lokale E-Book-Übersicht bereit.";
  await loadList("/api/v1/jobs", "#job-list", "Jobs");
  await loadList("/api/v1/audit-events", "#audit-list", "Audit-Ereignisse");
}

document.querySelector("#setup-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); await request("/api/v1/setup", data); show("login"); });
document.querySelector("#login-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session", Object.fromEntries(new FormData(event.currentTarget))); setCsrf(data.csrf); await initialise(); });
document.querySelector("#reauth-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session/reauth", Object.fromEntries(new FormData(event.currentTarget))); event.currentTarget.reset(); setCsrf(data.csrf); document.querySelector("#surface-status").textContent = "Private Locator sind für diese Session freigegeben."; });
function renameResult(value) { renderValue(document.querySelector("#rename-result"), value, "Umbenennen"); }
document.querySelector("#rename-review-reauth-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session/reauth-review", Object.fromEntries(new FormData(event.currentTarget))); event.currentTarget.reset(); setCsrf(data.csrf); renameResult({ status: "REVIEW_GRANT_ISSUED" }); });
document.querySelector("#rename-proposal-form").addEventListener("submit", async (event) => { event.preventDefault(); renameResult(await request("/api/v1/ebooks/rename/candidates", Object.fromEntries(new FormData(event.currentTarget)), true)); });
document.querySelector("#rename-review-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); const candidate = data.candidate_id; delete data.candidate_id; renameResult(await request(`/api/v1/ebooks/rename/candidates/${encodeURIComponent(candidate)}/reviews`, data, true)); });
document.querySelector("#rename-plan-form").addEventListener("submit", async (event) => { event.preventDefault(); const { candidate_id } = Object.fromEntries(new FormData(event.currentTarget)); renameResult(await request(`/api/v1/ebooks/rename/candidates/${encodeURIComponent(candidate_id)}/plans`, {}, true)); });
document.querySelector("#rename-operate-reauth-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = await request("/api/v1/session/reauth-operate", Object.fromEntries(new FormData(event.currentTarget))); event.currentTarget.reset(); setCsrf(data.csrf); renameResult({ status: "OPERATE_GRANT_ISSUED" }); });
document.querySelector("#rename-authorize-form").addEventListener("submit", async (event) => { event.preventDefault(); renameResult(await request("/api/v1/ebooks/rename/authorizations", Object.fromEntries(new FormData(event.currentTarget)), true)); });
document.querySelector("#rename-execute-form").addEventListener("submit", async (event) => { event.preventDefault(); renameResult(await request("/api/v1/ebooks/rename/executions", Object.fromEntries(new FormData(event.currentTarget)), true)); });
document.querySelector("#rename-recover-form").addEventListener("submit", async (event) => { event.preventDefault(); renameResult(await request("/api/v1/ebooks/rename/recoveries", Object.fromEntries(new FormData(event.currentTarget)), true)); });
document.querySelector("#search-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); await loadList(`/api/v1/ebooks/collection-states/${encodeURIComponent(data.snapshot)}/search?query=${encodeURIComponent(data.query)}`, "#search-results", "Suche"); });
document.querySelector("#snapshot-details-form").addEventListener("submit", async (event) => { event.preventDefault(); const { snapshot } = Object.fromEntries(new FormData(event.currentTarget)); await loadDetail(document.querySelector("#snapshot-details"), [`/api/v1/ebooks/collection-states/${encodeURIComponent(snapshot)}`, `/api/v1/ebooks/collection-states/${encodeURIComponent(snapshot)}/library-health`], "Snapshot"); });
document.querySelector("#scan-details-form").addEventListener("submit", async (event) => { event.preventDefault(); const { scan_root } = Object.fromEntries(new FormData(event.currentTarget)); await loadDetail(document.querySelector("#scan-details"), [`/api/v1/ebooks/scan-roots/${encodeURIComponent(scan_root)}/status`, `/api/v1/ebooks/scan-roots/${encodeURIComponent(scan_root)}/inventory`], "Scan"); });
document.querySelector("#run-details-form").addEventListener("submit", async (event) => { event.preventDefault(); const { run } = Object.fromEntries(new FormData(event.currentTarget)); await loadDetail(document.querySelector("#run-details"), [`/api/v1/ebooks/collection-runs/${encodeURIComponent(run)}/analysis`, `/api/v1/ebooks/collection-runs/${encodeURIComponent(run)}/evidence`, `/api/v1/ebooks/collection-runs/${encodeURIComponent(run)}/reviews`], "Analyse"); });
document.querySelector("#readiness-action").addEventListener("click", async () => { const node = document.querySelector("#readiness-details"); try { renderValue(node, await getJson("/api/v1/ebooks/readiness"), "Readiness"); } catch { node.textContent = "Readiness nicht verfügbar."; } });
document.querySelector("#plans-action").addEventListener("click", async () => loadList("/api/v1/ebooks/plans", "#plan-list", "Nicht ausführbare Pläne"));

document.querySelector("#fixity-baseline-build-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const node = document.querySelector("#fixity-baseline-job-result"); try { const result = await request("/api/v1/ebooks/fixity/baselines", { ...data, worker_count: Number(data.worker_count) }, actionKey(form, `${data.scan_root_id}:${data.worker_count}`)); finishAction(form); renderValue(node, result, "Baseline-Build-Job"); } catch (error) { node.textContent = germanError(error, "Baseline-Build-Job wurde nicht angelegt."); } });
document.querySelector("#fixity-baseline-status-form").addEventListener("submit", async (event) => { event.preventDefault(); const { manifest_id } = Object.fromEntries(new FormData(event.currentTarget)); const node = document.querySelector("#fixity-baseline-status"); try { renderValue(node, await getJson(`/api/v1/ebooks/fixity/baselines/${encodeURIComponent(manifest_id)}`), "Baseline-Status"); updateFixityConfirmationInstruction(manifest_id); document.querySelector("#fixity-baseline-activation-form [name=manifest_id]").value = manifest_id; } catch (error) { node.textContent = germanError(error, "Baseline-Status nicht verfügbar."); } });
document.querySelector("#fixity-baseline-activation-form [name=manifest_id]").addEventListener("input", (event) => updateFixityConfirmationInstruction(event.currentTarget.value));
document.querySelector("#fixity-review-reauth-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const node = document.querySelector("#fixity-review-grant-status"); try { const data = await request("/api/v1/session/reauth-review", Object.fromEntries(new FormData(form))); form.reset(); setCsrf(data.csrf); fixityReview.active = true; node.textContent = "Review-Grant ist für diese Session aktiv."; } catch (error) { form.reset(); node.textContent = germanError(error, "Review-Grant wurde nicht erteilt."); } });
document.querySelector("#fixity-baseline-activation-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const node = document.querySelector("#fixity-baseline-activation-result"); if (!requireFixityReview(node)) { return; } form.querySelector("[name=confirmation]").value = ""; try { const result = await request(`/api/v1/ebooks/fixity/baselines/${encodeURIComponent(data.manifest_id)}/activation`, { confirmation: data.confirmation }, actionKey(form, data.manifest_id)); finishAction(form); renderValue(node, result, "Baseline-Aktivierung"); } catch (error) { node.textContent = germanError(error, "Baseline-Aktivierung wurde nicht abgeschlossen."); } });
document.querySelector("#fixity-verification-build-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const node = document.querySelector("#fixity-verification-job-result"); try { const result = await request("/api/v1/ebooks/fixity/verifications", { ...data, worker_count: Number(data.worker_count) }, actionKey(form, `${data.scan_root_id}:${data.worker_count}`)); finishAction(form); renderValue(node, result, "Verifikations-Job"); } catch (error) { node.textContent = germanError(error, "Verifikations-Job wurde nicht angelegt."); } });
document.querySelector("#fixity-verification-status-form").addEventListener("submit", async (event) => { event.preventDefault(); const { run_id } = Object.fromEntries(new FormData(event.currentTarget)); const node = document.querySelector("#fixity-verification-status"); try { renderValue(node, await getJson(`/api/v1/ebooks/fixity/verifications/${encodeURIComponent(run_id)}`), "Verifikationsstatus"); } catch (error) { node.textContent = germanError(error, "Verifikationsstatus nicht verfügbar."); } });
document.querySelector("#fixity-results-form").addEventListener("submit", async (event) => { event.preventDefault(); const { run_id } = Object.fromEntries(new FormData(event.currentTarget)); await loadFixityResults(`/api/v1/ebooks/fixity/verifications/${encodeURIComponent(run_id)}/results?limit=50`); });
document.querySelector("#fixity-private-reauth-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const node = document.querySelector("#fixity-private-grant-status"); try { const data = await request("/api/v1/session/reauth", Object.fromEntries(new FormData(form))); form.reset(); setCsrf(data.csrf); fixityPrivate.active = true; node.textContent = "Private Werte sind für diese Session sichtbar."; } catch (error) { form.reset(); node.textContent = germanError(error, "Private Freigabe wurde nicht erteilt."); } });
document.querySelector("#fixity-private-entries-form").addEventListener("submit", async (event) => { event.preventDefault(); if (!fixityPrivate.active) { document.querySelector("#fixity-private-grant-status").textContent = "Private Werte benötigen zuerst eine PRIVATE_READ-Freigabe."; return; } const { manifest_id } = Object.fromEntries(new FormData(event.currentTarget)); await loadPrivateBaselineEntries(`/api/v1/private/ebooks/fixity/baselines/${encodeURIComponent(manifest_id)}/entries?limit=50`); });
document.querySelector("#fixity-private-result-form").addEventListener("submit", async (event) => { event.preventDefault(); const node = document.querySelector("#fixity-private-result"); if (!fixityPrivate.active) { document.querySelector("#fixity-private-grant-status").textContent = "Private Werte benötigen zuerst eine PRIVATE_READ-Freigabe."; return; } const { result_id } = Object.fromEntries(new FormData(event.currentTarget)); try { renderPrivateResult(node, await getJson(`/api/v1/private/ebooks/fixity/results/${encodeURIComponent(result_id)}`)); } catch (error) { if (fixityPrivate.active) { node.textContent = germanError(error, "Privates Ergebnisdetail nicht verfügbar."); } } });
document.querySelector("#fixity-review-queue-action").addEventListener("click", async () => renderGetPage("/api/v1/ebooks/fixity/reviews?limit=50", document.querySelector("#fixity-review-queue"), "Fixity-Reviewqueue", "reviews"));
document.querySelector("#fixity-review-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const node = document.querySelector("#fixity-review-result"); if (!requireFixityReview(node)) { return; } try { const result = await request(`/api/v1/ebooks/fixity/results/${encodeURIComponent(data.result_id)}/reviews`, { decision: data.decision }, actionKey(form, `${data.result_id}:${data.decision}`)); finishAction(form); renderValue(node, result, "Fixity-Review"); } catch (error) { node.textContent = germanError(error, "Fixity-Review wurde nicht gespeichert."); } });
document.querySelector("#fixity-expectation-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const node = document.querySelector("#fixity-expectation-result"); if (!requireFixityReview(node)) { return; } try { const result = await request(`/api/v1/ebooks/fixity/results/${encodeURIComponent(data.result_id)}/expectations`, { action: data.action }, actionKey(form, `${data.result_id}:${data.action}`)); finishAction(form); renderValue(node, result, "Einzelrevision"); } catch (error) { node.textContent = germanError(error, "Die Einzelrevision wurde ohne Pfadangaben abgelehnt."); } });
document.querySelector("#session-action").addEventListener("click", async () => { clearFixityPrivateValues("Private Werte wurden beim Abmelden entfernt."); if (window.csrf) { await fetch("/api/v1/session", { method: "DELETE", credentials: "same-origin", headers: { "Content-Type": "application/json", "Origin": location.origin, "X-FolioTone-CSRF": window.csrf } }); } location.reload(); });

void initialise();
