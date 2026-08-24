# ADR-0070: Foundation 1.4 mit persistenter Planungsidentität und Registrierung

- Status: Accepted
- Datum: 2026-08-24

## Kontext

ADR-0068 integrierte die AI Repository Foundation 1.2.0 semantisch. Der aktuelle Foundation-Stand 1.4.0 ergänzt eine geschichtssichere Identitätstrennung und eine sprachneutrale Registration Authority für dauerhafte Artefakte. FolioTone besitzt bereits viele veröffentlichte, hierarchisch geprägte Planungs- und Entscheidungsreferenzen. Eine automatische Umbenennung würde Links, Handover und Nachweislinien gefährden.

Die Foundation-Version 1.4.0 wurde aus Commit `2c9de5d5299a0eefec59fdc6131519886dc5e195` ausschließlich gemäß `foundation/manifest.json` bewertet. Die Root-Lizenz, der geschützte README-Lizenzblock, Projektstatus des Foundation-Repositorys und nicht manifestierte Dateien bleiben ausgeschlossen.

## Entscheidung

Die v1.4-Core-Regeln, die drei Registrierungsschemas und die bewusst gewählte optionale Capability `artifact-registration-clients` werden unter `.ai/foundation/` übernommen. Die selektierten Python- und PowerShell-Clients sind nur austauschbare Clients; die Authority ist die FolioTone-eigene, versionierte Registry unter `docs/planning/artifact_registry.json`.

Für sämtliche vorhandenen FolioTone-Referenzen gilt `PRESERVE`. Für neue dauerhafte Planungs-/Governance-Artefakte gilt ab dem registrierten Startpunkt `WI-0001` `ADOPT_FORWARD`. Ihre UUIDv7-URN ist die maschinenauflösbare Identität; `WI-0001` und nachfolgende flache Typreferenzen sind stabile projektlokale Referenzen. Wave, Status, Tier, Owner und Hierarchie sind Metadaten oder explizite Relationen. Sie führen nicht zu einem ID-Wechsel.

`DEFERRED` ist für parallele oder nicht eindeutig serialisierte Arbeit der Standard. `DIRECT` darf nur der zuständige Orchestrator nach verifiziertem Ausgangsstand, Registry-Lock und Revision-Check nutzen. Die Authority wird nicht durch Markdown-Suche, Dateinamen, Git-Historie, Chatverlauf oder Modellgedächtnis ersetzt. Eine Zuteilung verleiht niemals W10-, Änderungs- oder Freigaberechte.

Die FolioTone-Authority und Metadatenform sind in [`ARTIFACT_REGISTRATION.md`](../planning/ARTIFACT_REGISTRATION.md) dokumentiert. Das aktuelle Artefakt `WI-0001` demonstriert den vollständigen registrierten, aber rein governance-bezogenen Scope.

## Semantischer Abgleich

| Bereich | Klasse | FolioTone-Auslegung |
|---|---|---|
| Bestehende IDs | `PROJECT_SELECTABLE_OVERRIDE` | `PRESERVE`; keine Migration oder Neuinterpretation. |
| Neue Planungsartefakte | `COMPLEMENTARY` | `ADOPT_FORWARD` mit UUIDv7, Registry und expliziten Metadaten. |
| Registration Authority | `COMPLEMENTARY` | Projektlokale Registry ist die einzige Authority des neuen Scope; beide Referenzclients bleiben gleichwertige Zugänge. |
| Wave-/Git-Workflow | `PROJECT_STRONGER` | FolioTone ergänzt PR-, Worktree-, Review- und CI-Gates; sie ersetzen keine Collision-/Revision-Prüfung. |
| Privacy, Safety und W10 | `PROJECT_STRONGER` | Registry und IDs enthalten keine Secrets und autorisieren keine Runtime-Operation. |
| Foundation- und Projektprüfung | `COMPLEMENTARY` | `FOUNDATION_INTEGRITY` bleibt getrennt von FolioTone Static-, Test- und Runtime-Nachweisen. |

Es besteht kein `FOUNDATION_REQUIRED_CONFLICT`, `TARGET_INTERNAL_CONFLICT`, `ORPHANED_AUTHORITY` oder `ADAPTER_GOVERNANCE_MISPLACED`.

## Folgen

- Neue Aufgaben besitzen eine eindeutig registrierte, pfadunabhängige und hierarchieunabhängige Referenz plus maschinenlesbare UID.
- Alte Referenzen bleiben für Handover, Backlog, ADRs, Branches und externe Links gültig.
- Mehrere KI-Systeme und Menschen verwenden dieselbe Registry statt eine neue Nummer aus sichtbaren Dokumenten abzuleiten.
- Keine Domain-Entity-ID, Datenbankschema, W10-Capability oder Runtime-Authorization wird verändert.
- Verteilte Mehrhost-Allocation ist nicht als bewiesen markiert; bei Bedarf erhält sie eine eigene technische Entscheidung und einen empirischen Test.
- Die transferierten Referenzclients bleiben byte-identisch zur Foundation und liegen außerhalb von FolioTones Ruff-Scope; ihre Foundation-Contract-Validierung bleibt verpflichtend.

## Validierung

Die Wave validiert manifestierte Foundation-Dateien, Source-Provenance, Registry-/Artefaktschema, Client-`validate`/`resolve`, FolioTone-Static-Contracts und die unveränderte Lizenzgrenze. Foundation-Prüfung, FolioTone-Semantikprüfung und CI bleiben getrennte Nachweisbereiche.
