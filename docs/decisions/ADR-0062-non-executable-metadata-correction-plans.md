# ADR-0062: Nicht ausführbare, reviewte Metadatenkorrekturpläne

- Status: Accepted
- Datum: 2026-08-22

## Kontext

FolioTone bewahrt beobachtete E-Book-Metadaten, abgeleitete Kandidaten,
externe Aussagen und lokal bestätigte Werte getrennt mit Provenance. Ein
kanonischer oder `USER_CONFIRMED`-Wert ist jedoch noch keine Erlaubnis, eine
Datei, einen Sidecar oder ein externes Library-System zu ändern.

ADR-0061 gibt die kontrollierte Writer-Entwicklung frei. Vor dem ersten
Metadata-Writer verlangt `W9-006` deshalb einen content-addressed,
reviewpflichtigen und nicht ausführbaren Plan. Der Vertrag muss mehrwertige
Felder, unterschiedliche Zielträger und die spätere Revalidierung abbilden,
ohne ein Format-, Tool- oder Writerkommando in die Domain zu übernehmen.

Der finale Plan kann nicht selbst Gegenstand seines vorausgehenden Reviews
sein, weil seine Review-Decision wiederum materieller Bestandteil des Plans
ist. Wie bei ADR-0034 wird dieser Zyklus durch einen separaten immutable
Candidate-Snapshot aufgelöst.

## Entscheidung

W9-006 verwendet die Profile:

```text
metadata-correction-candidate/v1
metadata-correction-plan/v1
ebook-metadata-write-intent/v1
metadata-correction-verification/v1
canonical-json/v1
```

Zuerst wird ein `MetadataCorrectionCandidate` aus einem abgeschlossenen
book-only `ScanRun`, der exakten aktuellen `FileObservation`, persistierter
Metadata-Evidence und einer expliziten Wertauswahl erzeugt. Ein append-only
Review bestätigt oder verwirft exakt diesen Candidate. Erst danach entsteht
ein `MetadataCorrectionPlan`, der Candidate, neueste kompatible Review-
Decision, Preconditions und Post-write-Verifikation bindet.

Candidate und Plan sind immutable, insert-only, bounded, path-free und
content-addressed. Der einzige Execution-State lautet `NOT_EXECUTABLE`.
Weder `APPROVED_NON_EXECUTABLE` noch ein `ACCEPT`-Review wird in eine W10-
Authorization umgedeutet.

## Zielträger und Writeranforderung

`MetadataTargetCarrier` besitzt genau diese Literale:

```text
FOLIOTONE_PROJECTION
SIDECAR
SOURCE_METADATA
CALIBRE_LIBRARY
EXTERNAL_TOOL
```

Genau ein Zielträger ist je Candidate zulässig. Er bindet eine opaque
Zielreferenz, deren festen Kind-Literal und einen materiellen
`carrier_state_fingerprint`. Die zulässigen Referenzarten sind entsprechend
`DOMAIN_ENTITY`, `SIDECAR_SLOT`, `SOURCE_FILE`, `CALIBRE_RECORD` und
`EXTERNAL_RECORD`. Ein Sidecar-Slot darf content-addressed als abwesender
Zielzustand repräsentiert werden; ein Pfad gehört nicht in den Vertrag.

`ebook-metadata-write-intent/v1` beschreibt nur die erforderliche semantische
Writerfähigkeit für Format und Zielträger. Das Profil enthält keine
ausführbaren Argumente, keinen Adapter- oder Toolpfad und behauptet nicht,
dass ein Writer vorhanden ist. Die spätere W10-Authorization muss zusätzlich
einen konkret implementierten, kompatiblen Writer samt Adapter-, Tool- und
Konfigurationsversion binden.

Eine Freigabe für einen Zielträger öffnet keinen anderen. Insbesondere
autorisiert `SOURCE_METADATA` weder Sidecar- noch Calibrewrite, und ein
Calibre-Record ist keine Source-Datei.

## Feldkorrekturen und Werterhalt

Ein Candidate enthält zwischen einem und 64 eindeutige Feldpfade. Ein
Feldpfad folgt der bestehenden provider-neutralen E-Book-Metadatenstruktur
und wird durch eine feste bounded Syntax validiert. Freie JSON-Pfade,
Writeroptionen oder Provider-DTOs sind nicht zulässig.

`MetadataCorrectionOperation` besitzt:

```text
REPLACE
REMOVE
```

Jede `MetadataFieldCorrection` enthält:

- den Feldpfad;
- geordnete beobachtete Werte mit Zustand, opaque Source-Referenz und
  materiellem Fingerprint;
- geordnete ausgewählte Werte mit `CANONICAL` oder `USER_CONFIRMED`, Source-
  Referenz und materiellem Fingerprint;
- die Operation und einen Fingerprint der vollständigen Feldauswahl;
- begrenzte Evidence-Referenzen.

`REPLACE` verlangt mindestens einen ausgewählten Wert. `REMOVE` verlangt eine
leere Auswahl, bewahrt aber die beobachteten Werte und ihre Provenance. Damit
bleiben mehrwertige Contributor-, Identifier-, Subject- und Series-Felder
abbildbar, ohne sie in einen einzelnen String zu pressen.

Die tatsächlichen Werte sind private Runtime-Metadaten. Sie dürfen in den
insert-only Planzeilen gespeichert werden, werden aber aus `repr`, Standard-
Reports, Logs und Fehlern ausgeschlossen. Ein maschinenlesbarer Report zeigt
nur Feldpfade, Operationen, Counts, Status und opaque IDs.

## Source-, Dependency- und Precondition-Snapshot

Der Candidate bindet genau eine reguläre aktuelle E-Book-Datei durch:

```text
scan_root_id
source_scan_run_id
file_id
observation_id
format_label
expected_presence_state
expected_full_sha256
expected_size_bytes
expected_modified_at
expected_observed_at
metadata_evidence_fingerprint
```

`format_label` bleibt auf EPUB, MOBI, AZW, AZW3 und PDF begrenzt. Der
vollständige Datei-Hash stammt aus `FILE_SHA256`; ein Quick Fingerprint reicht
nicht. Candidate und Plan öffnen die Datei nicht.

Die Dependency-Achsen `CALIBRE`, `SIDECAR` und `ARCHIVE` werden mit Zustand,
Snapshotreferenz und materiellem Fingerprint gebunden. `UNKNOWN` erzeugt
`DEPENDENCY_EVIDENCE_INCOMPLETE`; `KNOWN_PRESENT` ist Plan-Evidence und noch
keine Erlaubnis, die Dependency zu verändern. Die jeweilige W10-ADR legt
später fest, welche bekannten Dependencies den Writer blockieren oder eine
Reconciliation verlangen.

Die festen Preconditions binden mindestens:

```text
FILE_RECORD_UNCHANGED
FILE_OBSERVATION_CURRENT
PRESENCE_IS_PRESENT
FULL_SHA256_MATCHES
SIZE_MATCHES
MODIFIED_AT_MATCHES
METADATA_EVIDENCE_UNCHANGED
TARGET_CARRIER_UNCHANGED
DEPENDENCIES_UNCHANGED
REVIEW_APPROVAL_UNCHANGED
WRITER_REQUIREMENT_UNCHANGED
```

W9 speichert ausschließlich die erwarteten Zustände. Eine spätere W10-
Ausführung muss sie unmittelbar vor genau einer Mutation erneut prüfen.

## Post-write-Verifikation

`metadata-correction-verification/v1` bindet:

- das read-only Reanalyseprofil;
- den Fingerprint der erwarteten ausgewählten Felder;
- den Fingerprint aller unverändert zu erhaltenden Metadatenfelder;
- die geordnete Allowlist absichtlich geänderter Feldpfade;
- erforderliche Format-/Lesbarkeitsprüfung;
- erforderliche Dependency-Reconciliation für den gewählten Zielträger.

Der Writer darf einen technischen Erfolg nicht allein aus seinem Exitcode
ableiten. Die spätere Ausführung muss die Source erneut lesen, die geänderten
Felder semantisch vergleichen und unbeabsichtigte Änderungen sichtbar
machen. Ein neuer `ScanRun` und `CollectionState` bleiben Teil der
übergeordneten End-to-End-Verifikation.

## Reviewvertrag

Der generische Review-Core wird additiv um genau diese Literale erweitert:

```text
ReviewType.METADATA_CORRECTION
ReviewCandidateKind.METADATA_CORRECTION_CANDIDATE
```

Der Review-Fall verwendet:

```text
review_type = METADATA_CORRECTION
subject_kind = FILE
subject_id = candidate.file_id
candidate_kind = METADATA_CORRECTION_CANDIDATE
candidate_id = metadata_correction_candidates.id
producer_name = ebook-metadata-correction
producer_version = 1
decision_compatibility_version = ebook-metadata-correction-decision/v1
```

Evidence- und Candidate-Set-Fingerprint müssen exakt dem Candidate
entsprechen. Nur die neueste kompatible `ACCEPT`-Decision ergibt
`APPROVED_NON_EXECUTABLE`. `PENDING` oder `DEFER` ergibt `REVIEW_REQUIRED`;
fehlender, fremder, stale oder `REJECT`-Review erzeugt einen festen Blocker.

## Status und Blocker

`MetadataCorrectionPlanStatus` besitzt:

```text
BLOCKED
REVIEW_REQUIRED
APPROVED_NON_EXECUTABLE
```

`MetadataCorrectionBlockerCode` besitzt:

```text
LINEAGE_MISMATCH
SOURCE_EVIDENCE_INCOMPLETE
FIELD_SELECTION_INVALID
TARGET_CARRIER_INVALID
WRITER_REQUIREMENT_INVALID
DEPENDENCY_EVIDENCE_INCOMPLETE
PRECONDITION_INCOMPLETE
VERIFICATION_CONTRACT_INCOMPLETE
REVIEW_MISSING
REVIEW_REJECTED
REVIEW_STALE
```

Mindestens ein Blocker ergibt `BLOCKED`. Ohne Blocker ergibt ein vorhandener
offener Review `REVIEW_REQUIRED`. Nur ein vollständig gültiger Candidate mit
neuestem kompatiblem `ACCEPT` ergibt `APPROVED_NON_EXECUTABLE`.

## Kanonische Identität und Persistenz

Candidate und Plan verwenden `canonical-json/v1`, Unicode NFC, sortierte
Objektschlüssel, UTF-8 ohne Whitespace und UTC-Zeitpunkte mit sechs
Nachkommastellen. Values, Evidence, Dependencies, Preconditions und Blocker
besitzen feste kanonische Sortierungen und harte Obergrenzen. `id`,
`created_at` und der jeweilige Content Hash fehlen im Hash-Payload.

`content_hash` ist der lowercase SHA-256 über den domain-separierten
kanonischen Payload. Die jeweilige `EntityId` wird deterministisch per UUIDv5
aus Profil und Content Hash abgeleitet. Geänderte Source-Evidence,
Wertauswahl, Target, Dependency, Writeranforderung, Review oder Verifikation
erzeugt einen neuen Snapshot; ein anderer Auditzeitpunkt nicht.

Migration `0026_metadata_correction_plans` ergänzt getrennte Parent- und
Childtabellen für Candidate, Feldkorrekturen, beobachtete und ausgewählte
Werte, Evidence, Dependencies, Preconditions, Verifikation, Plan, Review und
Blocker. Parent- und Childzeilen sind insert-only; Update und Delete werden
durch Trigger abgewiesen. Die Migration erweitert die beiden Review-
Check-Constraints um die neuen Literale, ohne bestehende Reviewzeilen zu
ändern. Ein Downgrade wird verweigert, solange Metadata-Correction-Daten
vorhanden sind.

Der Store rehydriert den vollständigen Graph bounded, berechnet beide Hashes
erneut und validiert Source-/Scan-/Observation-/Fingerprint-, ToolResult-,
ValueAssertion-, Dependency- und neueste Review-Lineage in derselben kurzen
Transaktion. Ein exakter Retry verwendet den bestehenden Snapshot; ein
abweichender Payload unter demselben semantischen Schlüssel schlägt
fail-closed fehl. Planung benötigt keine `ScanRootWriteLease`, weil sie Source
Media nicht öffnet und nur neue immutable Daten schreibt.

## Reporter, CLI und Non-Execution-Grenze

`ebook-metadata-correction-report` liest genau einen persistierten Plan über
eine echte SQLite-Read-only-Verbindung. Text und JSON enthalten ausschließlich
Plan-/Candidate-ID, Profile, Status, Execution-State, Content Hash,
Zielträger, Format, Feldpfade, Operationen, Counts, Reviewstatus und
Blockerliterale. Werte, Pfade, Dateinamen, Source-/Target-Fingerprints und
private Evidence-Materialien bleiben ausgeschlossen.

`foliotone.metadata_correction` darf nur immutable DTOs, reine Builder und
Serializer enthalten. W9-006 darf Source Media weder öffnen noch schreiben
und keine mutierende Filesystem-, Calibre-, ToolProvider-, Shell- oder
Subprocessoperation anbieten. Öffentliche Methoden mit Execute-/Apply-/Write-
Semantik sind verboten. Ein statischer Non-Execution-Test prüft diese Grenze.

## Lieferpakete

1. `S-W9-006A`: reine DTOs, Reducer, kanonische Serialisierung, Golden Values
   und Non-Execution-Vertrag;
2. `S-W9-006B`: additive Migration, Review-Literale und insert-only Store mit
   vollständiger Lineage-/Idempotenzprüfung;
3. `S-W9-006C`: true-read-only Reporter, CLI, Privacy-/Bootstrap-Vertrag und
   Abschluss von W9-006.

Jedes Paket ist eine eigene kleine Wave. Lokal laufen nur fokussierte Unit-,
Migrations-, Persistenz-, Privacy- und statische Regressionen; der stabile
Pull-Request-Head erhält genau einen vollständigen CI-Gate.

## Folgen

- Eine reviewte Metadatenauswahl wird reproduzierbar, ohne einen Writer zu
  öffnen oder beobachtete Werte zu überschreiben.
- Mehrwertige Felder und alle fünf Zielträger bleiben abbildbar, während jede
  spätere Write-Capability getrennt bleibt.
- `FG-W10-METADATA-WRITE` kann auf einen stabilen Plan-, Revalidierungs- und
  Verifikationsvertrag aufbauen, muss aber Format, Backup, Byte-/Semantik-Diff
  und Recovery weiterhin selbst entscheiden.
- REST/UI, Sidecar-, Calibre-, externe Tool- und Source-Metadata-Ausführung
  werden durch diese ADR nicht aktiviert.
