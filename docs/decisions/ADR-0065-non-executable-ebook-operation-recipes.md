# ADR-0065: Nicht ausführbare E-Book-Operationsrezepte

- Status: Accepted
- Datum: 2026-08-23

## Kontext

ADR-0062 trennt die reviewte Auswahl einer Metadatenkorrektur von ihrem
dauerhaft nicht ausführbaren Plan. `ConsolidationPlan` erfüllt dieselbe Grenze
für bestätigte Duplicate-Fälle. Für Rename, Reorganisation, Import, Export,
Formattransformation sowie Archive-/Containeränderungen fehlt bisher ein
vergleichbar reproduzierbarer, operationstypisierter W9-Vertrag.

Ein generisches Rezept mit freien Source-/Zielpfaden oder einem frei
konfigurierbaren Toolkommando würde die späteren operation-spezifischen
W10-Gates umgehen. Ein bereits reviewter finaler Plan kann zugleich nicht
Gegenstand seines eigenen vorausgehenden Reviews sein, weil die
Reviewentscheidung materieller Bestandteil dieses Plans wird. Der Vertrag
benötigt daher wie ADR-0062 eine getrennte Candidate- und Planstufe.

ADR-0061 erlaubt die kontrollierte Entwicklung dieser E-Book-Operationen mit
synthetischen Fixtures. Die Freigabe erzeugt keine Runtime-Authorization und
öffnet insbesondere nicht die vorhandenen read-only calibre- oder
7-Zip-Adapter für Schreiboperationen.

## Entscheidung

W9-007 verwendet die Profile:

```text
ebook-operation-recipe-candidate/v1
ebook-operation-recipe-plan/v1
canonical-json/v1
```

Ein `EbookOperationRecipeCandidate` bindet genau einen Operationstyp, eine
abgeschlossene Source-Lineage, einen bounded Ziel-Slot, die erwartete
Outputidentität, Processor- und Dependency-Anforderungen, Collision-,
Workspace-, Recovery- und Verification-Verträge sowie begrenzte Evidence-
Referenzen. Der Candidate ist der Gegenstand eines append-only Reviews.

Erst die neueste kompatible Reviewentscheidung wird zusammen mit festen
changed-since-analysis-Preconditions in einen
`EbookOperationRecipePlan` reduziert. Candidate und Plan sind immutable,
content-addressed und besitzen keine Ausführungsfunktion. Der einzige
Execution-State ist `NOT_EXECUTABLE`; auch
`APPROVED_NON_EXECUTABLE` ist keine W10-Authorization.

## Operationstypen und feste Matrix

`EbookOperationKind` besitzt genau diese Literale:

```text
FILE_RENAME
FILE_REORGANIZE
FILE_IMPORT
FILE_EXPORT
FORMAT_TRANSFORM
ARCHIVE_REWRITE
```

Die operationstypisierte Matrix ist kein frei kombinierbarer Optionsraum:

| Operation | Ziel | Outputidentität | Collision | Workspace | Recovery |
|---|---|---|---|---|---|
| `FILE_RENAME` | anderer Basename im selben Parent und `ScanRoot` | byte-identisch zur Primärquelle | Ziel muss fehlen | nicht erforderlich | umgekehrte Relocation |
| `FILE_REORGANIZE` | anderer Parent im selben `ScanRoot` | byte-identisch zur Primärquelle | Ziel muss fehlen | nicht erforderlich | umgekehrte Relocation |
| `FILE_IMPORT` | anderer verwalteter `ScanRoot` | byte-identisch zur Primärquelle | Ziel muss fehlen | privates Staging | Source bleibt unverändert |
| `FILE_EXPORT` | externer Endpoint-Slot | byte-identisch zur Primärquelle | Ziel muss fehlen | privates Staging | Source bleibt unverändert |
| `FORMAT_TRANSFORM` | neuer generierter Slot, niemals derselbe Source-Slot | erwarteter Full-SHA-256 | Ziel muss fehlen | privates Staging | Source bleibt unverändert |
| `ARCHIVE_REWRITE` | exakter Source-Replacement-Slot | erwarteter Full-SHA-256 | exakte Source muss vorliegen | privates Staging | Original bleibt erhalten |

Byte-identische Operationen binden Format, Größe und vollständigen SHA-256
der Primärquelle. Eine erfolgreiche Relocation, Transformation oder
Archive-Verarbeitung trifft keine Identity-, Keeper-, Purge- oder
Entbehrlichkeitsentscheidung.

## Source- und Zielgrenzen

Ein Candidate enthält genau eine geordnete Primärquelle. Nur
`ARCHIVE_REWRITE` darf bis zu 31 weitere Companion-Quellen binden. Alle
Companions müssen aus demselben abgeschlossenen `ScanRun` und `ScanRoot`
stammen. Batchlisten, Globs, rekursive Verzeichnisoperationen und implizite
Auswahl eines nächsten Kandidaten sind nicht Bestandteil des Vertrags.

Jede Source bindet mindestens:

```text
scan_root_id
source_scan_run_id
source_scan_run_status
file_id
observation_id
relative_locator
format_label
expected_presence_state
expected_full_sha256
expected_size_bytes
expected_modified_at
expected_observed_at
source_evidence_fingerprint
```

Nur `COMPLETED`, `PRESENT` und ein vollständiger SHA-256 sind zulässig. Der
private Locator ist relativ, normalisiert, auf 1.024 UTF-8-Bytes und
255 UTF-8-Bytes je Komponente begrenzt und weist absolute, Drive-relative,
leere, Punkt- und Parent-Komponenten ab. Source- und Ziel-Locators sowie
Material-Fingerprints bleiben aus `repr`, Standard-Reports, Logs und Fehlern
ausgeschlossen. Absolute lokale Pfade gehören weder in Domain noch
Persistenz.

Der relative Locator ist für einen späteren exakten Execution-Slot materiell
und daher Bestandteil der privaten content-addressed Candidate-Identität.
Eine spätere REST-, UI- oder CLI-Projektion darf ihn nur unter einer eigenen
expliziten privaten Berechtigung zeigen; W9-007C zeigt ihn nicht.

## Processor- und Toolgrenze

`EbookOperationProcessorRequirement` beschreibt ausschließlich eine
semantische Fähigkeit und deren Konfigurations-Fingerprint. Er unterscheidet
`FOLIOTONE_NATIVE` und `TOOL_PROVIDER`. Bei einem `ToolProvider` werden
Provider-, Tool- und Adapterversion gebunden. Ein Processor Requirement
enthält keinen Executable-Pfad, kein argv, keine Shell, keinen freien
Command-String und keine Environment-Konfiguration.

Die vier byte-erhaltenden Dateioperationen verlangen
`FOLIOTONE_NATIVE`. Transformation und Archive-Rewrite dürfen lediglich eine
versionierte ToolProvider-Anforderung beschreiben. Damit wird keine
Write-Capability eines vorhandenen Adapters behauptet. Vor einem späteren
Tool-basierten Writer müssen die aktuellen offiziellen Tool-, Lizenz-,
Automations-, Versions- und Sicherheitsbedingungen erneut geprüft und in
einer operation-spezifischen W10-ADR entschieden werden.

## Dependencies, Preconditions und Verifikation

Jeder Candidate enthält die fünf Dependency-Achsen `CALIBRE`, `SIDECAR`,
`ARCHIVE`, `VOLUME_GROUP` und `EXTERNAL_LIBRARY` genau einmal in kanonischer
Reihenfolge. Jede Achse bindet Zustand, Snapshotart, opaque Snapshot-ID und
Material-Fingerprint. `UNKNOWN` erzeugt den festen Blocker
`DEPENDENCY_EVIDENCE_INCOMPLETE`; `KNOWN_PRESENT` autorisiert keine Änderung
der Dependency.

Jeder Plan bindet die erwarteten Zustände durch die festen Preconditions:

```text
SOURCE_LINEAGE_UNCHANGED
SOURCE_BYTES_UNCHANGED
TARGET_STATE_UNCHANGED
DEPENDENCIES_UNCHANGED
PROCESSOR_REQUIREMENT_UNCHANGED
OUTPUT_EXPECTATION_UNCHANGED
RECOVERY_REQUIREMENT_UNCHANGED
VERIFICATION_REQUIREMENT_UNCHANGED
REVIEW_APPROVAL_UNCHANGED
```

Die Review-Precondition entsteht nur für eine aktuelle kompatible
`ACCEPT`-Decision. W9 prüft die erwarteten Zustände nicht gegen Source Media;
eine spätere W10-Ausführung muss sie unmittelbar vor genau einer Mutation
unter einer frischen `ScanRootWriteLease` erneut prüfen.

Alle Operationen verlangen Input- und Target-Revalidierung, vollständige
Output-Hash- und Größenprüfung sowie Source-Presence-Verifikation. Operationen
in einem verwalteten `ScanRoot` verlangen zusätzlich Rescan und
`CollectionState`-Reconciliation. Transformation und Archive-Rewrite
verlangen Format-Lesbarkeit; Archive-Rewrite verlangt außerdem Dependency-
Reconciliation. Ein Tool-Exitcode allein ist kein Verifikationsnachweis.

## Review, Status und Blocker

W9-007B erweitert den generischen Review-Core additiv um die feste Paarung:

```text
ReviewType.EBOOK_OPERATION_RECIPE
ReviewCandidateKind.EBOOK_OPERATION_RECIPE_CANDIDATE
```

Der technische Review-Snapshot bindet Candidate-ID, Candidate-Content-Hash,
Evidence-Fingerprint, Producer- und Decision-Compatibility-Version. Nur die
neueste kompatible `ACCEPT`-Decision kann einen blockerfreien Status
`APPROVED_NON_EXECUTABLE` erzeugen. `PENDING` und `DEFER` ergeben
`REVIEW_REQUIRED`. Fehlender, fremder, stale oder abgelehnter Review sowie
unvollständige Lineage, Evidence, Target-, Output-, Processor-, Dependency-,
Precondition-, Recovery- oder Verification-Verträge ergeben `BLOCKED` mit
einem festen Blockerliteral.

## Kanonische Identität und Privacy

Candidate und Plan verwenden Unicode NFC, UTC-Zeitpunkte mit sechs
Nachkommastellen, sortierte Objektschlüssel und kompaktes UTF-8-JSON. Floats
sind verboten. `id`, `created_at` und `content_hash` fehlen im jeweiligen
Hash-Payload. Der lowercase SHA-256 des domain-separierten Payloads bestimmt
per UUIDv5 die `EntityId`. Ein anderer Auditzeitpunkt ändert die Identität
nicht; eine materielle Änderung an Source, privatem Ziel-Slot, Output,
Processor, Dependency, Evidence, Review, Recovery oder Verification erzeugt
einen neuen Snapshot.

Der Plan serialisiert nur die content-addressed Candidate-Bindung und nicht
erneut dessen private Locators. Persistenz und Reports aus den Folgewaves
müssen Child-Counts hart begrenzen, private Werte aus Fehlern fernhalten und
Standardausgaben auf opaque IDs, Profile, Operationstyp, Status, Counts,
Reviewstatus und Blockerliterale beschränken.

## Non-Execution-Grenze

`foliotone.ebook_operation_recipes` enthält nur immutable DTOs, reine Builder,
Reducer und kanonische Serializer. Das Paket importiert keine CLI-,
Persistence-, Tooling-, Adapter-, Filesystem-, Prozess- oder Temp-Module. Es
öffnet weder Source Media noch Ziel-Slots und besitzt keine öffentliche
Apply-, Delete-, Execute-, Move-, Purge-, Quarantine-, Rename- oder
Write-Fläche. Ein statischer Regressionstest prüft Import-, Call-, Command-
und öffentliche Surface-Grenzen.

Die ADR entscheidet keinen technischen Writer. Insbesondere bleiben
`FG-W10-RENAME`, `FG-W10-ARCHIVE-REWRITE`, Import, Export und Transformation
jeweils an eine eigene Capability-/Authorize-/Execute-/Recovery-Kette
gebunden. Die bestehende ADR-0056-Quarantäne und der ADR-0063/ADR-0064-EPUB-
Titelwriter dürfen nicht als generische Operations-Backends wiederverwendet
werden.

## Lieferpakete

1. `S-W9-007A`: reine DTOs, Builder, Reducer, kanonische Serialisierung,
   Golden Values und statischer Non-Execution-Gate;
2. `S-W9-007B`: additive Migration `0030`, Review-Literale und insert-only
   Store mit vollständiger Source-/Evidence-/Dependency-/Review-Lineage und
   idempotentem Rebuild;
3. `S-W9-007C`: echter SQLite-Read-only-Report und CLI mit privacy-begrenzter
   Text-/JSON-Projektion und Abschluss von `W9-007`.

Jedes Paket ist eine eigene kleine Wave. Lokal laufen nur fokussierte Unit-,
Migrations-, Persistenz-, Privacy- und statische Regressionen; der exakte
stabile Pull-Request-Head erhält genau einen vollständigen CI-Gate.

## Folgen

- Die sechs Operationsfamilien erhalten einen stabilen Planungs- und
  Reviewgegenstand, ohne eine Dateisystem- oder Toolausführung zu öffnen.
- Private relative Source-/Ziel-Slots bleiben für spätere exakte
  Revalidierung materiell, aber aus allen Standardprojektionen ausgeschlossen.
- Persistenz und read-only Oberfläche können in getrennten kleinen Waves auf
  denselben content-addressed Verträgen aufbauen.
- Jeder spätere Writer muss weiterhin seinen eigenen technischen
  Mutationstyp, Capability-Scope, Collision-/Fencing-/Journal-/Recovery-
  Vertrag und synthetische Conformance-Matrix entscheiden.
- REST/UI, Music, Bilder und weitere Medienlinien werden nicht aktiviert.
