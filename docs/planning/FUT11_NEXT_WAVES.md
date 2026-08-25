# Ausführungsvertrag für S-FUT11-03 und S-FUT11-04

**Status:** ausführungsbereit

**Ausgangsbasis:** `origin/main` nach `S-FUT11-02`

**Reihenfolge:** `S-FUT11-03` vor `S-FUT11-04`

## Zweck

Dieses Dokument macht die beiden nächsten Produktwaves implementierbar,
ohne den Implementierungsstatus vorwegzunehmen. `BACKLOG.md` bleibt die
einzige Status- und Ausführungsfront. ADR-0067 definiert die gemeinsame
Produktoberfläche; ADR-0066 und ADR-0069 begrenzen den ersten GUI-Writer.

Jede Wave beginnt von einem aktuell verifizierten `origin/main`, verwendet
einen eigenen Branch und Worktree sowie einen eigenen Pull Request. Eine
vorhandene lokale oder uncommittete Arbeit ist vor dem ersten Schreibzugriff
zu inventarisieren und bleibt unangetastet, bis ihre Übernahme ausdrücklich
geklärt ist.

## S-FUT11-03: Read-only E-Book-Oberfläche

### Ergebnis und Grenzen

Die Wave liefert die deutsche responsive same-origin Browseroberfläche und
sessiongebundene read-only E-Book-Projektionen. Sie verwendet Vanilla HTML,
CSS und JavaScript ohne Node- oder Framework-Runtime. Stabile Translation
Keys trennen sichtbare Texte von API-Verträgen.

Die HTTP-Schicht delegiert über adapterneutrale `ApplicationQuery`- und
Result-Verträge. Persistence- und Workflowadapter enden hinter Application-
Ports; der HTTP-Adapter erhält keine allgemeine Engine- oder direkte
Workflow-Abhängigkeit.

Die freigegebene API-Fläche umfasst:

- Media-Line-Registry mit aktivem `EBOOK` und sichtbar deaktiviertem `MUSIC`
  und `IMAGE`;
- Tool-/Format-Readiness, Scanstatus und `CollectionState`;
- Suche und `Library Health` für einen gebundenen Snapshot;
- Analyse-/Quality-Coverage und Candidate-Hash-Evidence;
- Review Queues und nicht ausführbare Pläne;
- Job- und Auditlisten sowie genau eine Jobdetailprojektion;
- relative Locator nur unter `/api/v1/private`.

Listen verwenden resource-gebundene opaque Keyset-Cursor, Defaultgröße 50 und
Maximum 100. Ein Cursor wird mindestens an Ressourcenprofil, Sortierschlüssel
und letzte ID gebunden. Ein ungültiger oder für eine andere Ressource
erzeugter Cursor endet mit einem festen RFC-9457-Fehlercode. Collection-weite
unbegrenzte Antworten existieren nicht.

Normale Responses verwenden feste Allowlists und enthalten keine Pfade,
Locator, Metadatenwerte, Hashes, Secrets oder Capability-Informationen.
Private Locator erfordern Passwort-Reauthentisierung, Session- und CSRF-
Rotation sowie einen höchstens 15 Minuten gültigen `PRIVATE_READ`-Grant an
der neuen Session. Jede private Erfolgs- und Fehlerantwort setzt
`Cache-Control: no-store`; absolute Hostpfade bleiben verboten.

Die UI implementiert Setup, Login, Logout, Reauthentisierung, Übersicht,
Suche, Detailansichten und Pagination als strukturierte Tabellen oder Karten.
Sie rendert keine allgemeinen Roh-JSON-Blöcke, lädt keine externen Assets und
enthält keine W10-Route oder schreibendes Control.

### Dateigrenzen und Stopbedingungen

Der erwartete Scope liegt in `foliotone.application`, `foliotone.surface`,
den read-only Persistence-Adaptern, den statischen Web-Assets sowie den
zugehörigen Tests und Planungsdokumenten. Eine additive Migration ist nur
zulässig, wenn ein unverzichtbarer read-only Cursor- oder Projection-Binder
nicht aus der bestehenden Persistenz rekonstruiert werden kann.

Die Wave stoppt bei Sourcezugriff im API-Prozess, ungebundener Pagination,
privaten Werten in Standardprojektionen, fehlender Sessionrotation, einer
neuen Domainidentität, einem W10-Control oder einer notwendigen allgemeinen
Frontend-/API-Architekturentscheidung. Das verbindliche Tier ist `BALANCED`;
eine neue Security- oder Privacyentscheidung verlangt `FRONTIER`.

### Abnahme

Fokussierte Tests belegen Application-Verträge, API-/OpenAPI-Shape, Auth und
Sessionrotation, Scopes, Cursor, Suche, Privacy, RFC-9457-Fehler, CSP,
Same-Origin-Assets, responsive Shell und Accessibility-Kernwege. Die Tests
verwenden ausschließlich synthetische SQLite-Daten. Ruff, Mypy,
Dokumentationsverträge, `git diff --check`, die erforderliche lokale Suite
und der Compose-Start müssen für den stabilen Head grün sein.

## S-FUT11-04: Same-Parent-Rename als erster GUI-Writer

### Voraussetzung und Ergebnis

Die Wave beginnt erst nach dem Merge und Post-Merge-Nachweis von
`S-FUT11-03`. Sie adaptiert ausschließlich den durch ADR-0066 implementierten
Same-Parent-`FILE_RENAME`. Titelwrite, Quarantäne, Reorganisation, Sidecar,
externe Library, Archive, Purge und Cleanup bleiben unerreichbar.

Die Application-Grenze erhält feste Commands und Results für Proposal,
Private Preview, Review, Plan, Authorize, Execute, Status und Recover. CLI,
HTTP und Worker verwenden dieselben vorhandenen Planning-, Operator- und
Statusservices; keine Transportebene dupliziert Domain- oder W10-Logik.

Die REST-Fläche verwendet folgende Ressourcen:

- Rename Candidates für Proposal und normale Preview;
- einen getrennten privaten Preview-Endpunkt unter `/api/v1/private`;
- append-only Review und nicht ausführbaren Plan;
- Rename Authorizations, Executions und Recoveries als dauerhafte
  `ApplicationJob`-Ressourcen;
- read-only Rename-Run-Status mit Folgescan- und Reconciliation-Zustand.

State-changing Requests benötigen CSRF und einen bounded `Idempotency-Key`.
Proposal, Review und Plan prüfen mindestens `REVIEW`; Private Preview prüft
einen frischen `PRIVATE_READ`-Grant. Authorize, Execute und Recover prüfen
einen frischen `OPERATE`-Grant. Die API akzeptiert keine freien Pfade,
Commandfragmente oder Targetänderungen nach Proposal.

### Job- und Workergrenze

ADR-0069 definiert `ebook-rename-operator-job/v1`. Eine additive Migration
persistiert immutable operation-spezifische Command-Binder und getrennte
insert-only Result-Referenzen. Die Raw Confirmation wird im API-Prozess exakt
geprüft und sofort verworfen; nur ihr bestehender domänengetrennter Digest
wird an den Job gebunden.

Der `operator-worker` claimt ausschließlich `AUTHORIZE`, `EXECUTE` und
`RECOVER` dieses Profils. Nur er löst
`FOLIOTONE_EBOOK_RENAME_CAPABILITIES_FILE` auf und erhält über das ohne
Default erforderliche `FOLIOTONE_EBOOK_RENAME_WRITABLE_ROOT` nur den exakt
capabilitygebundenen `ScanRoot` als beschreibbaren E-Book-Mount bei
`network=none`. Für Proposal darf
`surface-api` ausschließlich die durch ADR-0066 validierte, pfad- und
capability-freie `FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE` lesen. API
und Analyseworker behalten keine Rename-Capability und keinen Source-Write-
Mount; der Worker löst den Scope bei Authorize erneut auf.

Joblease und Job-Fence sind zusätzliche Transportgrenzen. Sie ersetzen weder
One-use-W10-Authorization noch `ScanRootWriteLease`, W10-Fence, Revalidierung,
Journal, unmittelbare Verifikation, Folgescan oder Reconciliation. Nach einer
möglichen irreversiblen Grenze wird niemals still ein neuer Execute-Job
gestartet; Status und Recovery setzen ausschließlich den gebundenen Run fort.

### Stopbedingungen und Abnahme

Die Wave stoppt bei einer Abweichung von ADR-0066, einer breiteren Capability,
Raw-Confirmation-Persistenz, direkter Ausführung im API-Prozess, generischer
Job-Payload, automatischem W10-Retry, fehlendem Recoveryweg oder einem
benötigten stärkeren Out-of-band-Threat-Model. Das verbindliche Tier ist
`FRONTIER`.

Die Abnahme umfasst Migration und Immutability, Confirmation-Privacy,
Idempotency, Replay, abgelaufene Authorization, Job-/Root-Fencing,
Worker-Allowlist, Scope-/Reauth-Grenzen, Status und Recovery. Ein
synthetischer Linux-/Docker-End-to-End-Fall belegt Rename, unmittelbare
Verifikation, Folgescan und Reconciliation. Die vorhandene CLI-Rename-Kette
und alle betroffenen W10-Safety-Verträge bleiben grün.

## Git- und CI-Abschluss

Jede Wave besitzt genau einen stabilen Implementierungsbranch und einen Pull
Request gegen `main`. Nach fokussierten lokalen Checks läuft genau ein
vollständiger `quality`-Gate für den exakten stabilen PR-Head. Gemergt wird
ausschließlich dieser Head als Merge-Commit mit genau zwei Eltern. Danach
werden Remote-Head, Merge-SHA und der kurze `post-merge-contract` geprüft.

`BACKLOG.md`, `PROJECT_STATUS.md` und `HANDOVER.md` werden in jeder Wave mit
dem tatsächlichen Scope, ausgeführten Prüfungen, offenen Nachweisen und der
nächsten Aufgabe synchronisiert. Ein nicht ausgeführter Test oder Gate bleibt
ausdrücklich als offen dokumentiert.
