# ADR-0054: Archive-aware Matching Frontier

- Status: Accepted
- Datum: 2026-08-21

## Kontext

EBAR-09 schließt die restartbare read-only Archive-Collection-Orchestrierung
ab. Archive-, Source-, Execution-, Member- und Wrapper-Lineage liegen
insert-only und an einen abgeschlossenen `ScanRun` gebunden vor. EB-08 kann
bereits dauerhaft nicht ausführbare `ConsolidationPlan`-Snapshots erzeugen,
behandelt `ARCHIVE=UNKNOWN` oder `ARCHIVE=KNOWN_PRESENT` jedoch nur als vom
Aufrufer bereitgestellte Dependency.

Die geplante Welle EB-A3 umfasst Archive-aware Matching, Keep Preference und
die vollständige nicht ausführbare Planintegration. Der aktuelle Evidence-
Stand reicht dafür nicht vollständig aus. Migration `0019_archive_evidence`
erzwingt bei jedem persistierten `ArchiveMemberObservation`
`member_sha256 IS NULL` und `observed_uncompressed_bytes IS NULL`, solange
keine Extraction stattgefunden hat. ADR-0050 hält jede reale Extraction
weiterhin `TOOL_UNAVAILABLE`.

Dateiname, privater Memberlocator, deklarierte Größe, CRC, Kompressionsgröße,
Toolstatus oder ein Online-Passworttreffer sind kein Ersatz für Memberbytes.
Sie dürfen weder eine File-Identity noch `KNOWN_NONE` für eine mögliche
Archive-Mitgliedschaft begründen.

## Entscheidung

EB-A3 wird in eine jetzt implementierbare Source-Dependency-Strecke und eine
weiterhin blockierte Member-Byte-Strecke geteilt. Das Profil
`consolidation-archive-dependency/v1` projiziert ausschließlich belegte
Archive-Source-Beziehungen in die vorhandene
`ConsolidationDependencyKind.ARCHIVE`-Achse.

### Vergleichsebenen

Die Ebenen bleiben getrennt:

| Vergleich | Zulässige aktuelle Aussage |
|---|---|
| physische Datei ↔ physische Datei mit identischem `FILE_SHA256` | bestehender `EXACT_DUPLICATE`-File-Relation-Candidate |
| generisches Archive/Volume als Source eines `ArchiveObservation`-Graphs | `ARCHIVE=KNOWN_PRESENT` als Dependency, keine neue Identity |
| Publication Container EPUB/CBZ/CBR | normale physische Datei und Publication; nicht allein wegen ZIP-/RAR-Struktur eine Archive-Dependency |
| Archive Member ↔ physische Datei | `UNKNOWN`, bis vollständige Memberbytes und SHA-256 verfügbar sind |
| Archive Member ↔ Archive Member | `UNKNOWN`, bis beide vollständigen Member-SHA-256 verfügbar sind |
| Wrapper-Inner-Stream ↔ physische Datei | nur Wrapper-Lineage; keine File- oder Member-Identity |
| Edition/Work eines Members | nicht modelliert; kein virtuelles `FileRecord`, keine geratene Domain-Entity |

Identische Containerbytes werden weiterhin ausschließlich als File↔File-
`EXACT_DUPLICATE` behandelt. Ein Archive-Dependency-Nachweis bestätigt nicht,
dass ein kompletter Container redundant ist. Ein Member-/File-Treffer würde
später ebenfalls nur die konkrete Inhaltsbeziehung bestätigen, niemals die
Entbehrlichkeit aller übrigen Containerinhalte.

### Source-Dependency-Projektion

Die reine Projektion erhält genau eine gerichtete Consolidation-File-Rolle,
eine aktuelle `FileObservation` mit Root-/Scan-Lineage und eine bounded Menge
von höchstens 16 bereits validierten Archive-Source-Bindings.

Ein Binding ist nur verwendbar, wenn:

- `FileObservation`, `ArchiveObservation` und Sourcezeile demselben
  `ScanRoot` und `source_scan_run_id` angehören;
- die Sourcezeile exakt auf die geprüfte `FileObservation` zeigt;
- der Archivegraph ein unterstütztes aktuelles Profil und einen materiellen
  `content_hash` besitzt;
- `publication_kind=NONE` gilt;
- Storage-/Outer-/Recognition- und Sourceordinal-Sum-Types gültig sind;
- alle Bindings kanonisch sortiert, eindeutig und innerhalb des festen Bounds
  von 16 liegen.

Die Statusmatrix ist geschlossen:

| Evidence | `ConsolidationDependencyState` | Snapshot |
|---|---|---|
| exakt ein kanonischer generischer direkter, mehrteiliger oder Wrapper-Archivegraph verwendet die FileObservation als Source | `KNOWN_PRESENT` | `snapshot_kind=ARCHIVE_OBSERVATION`, exakte `ArchiveObservation`-ID |
| kein generisches Source-Binding | `UNKNOWN` | kein Snapshot |
| mehrere materiell verschiedene aktuelle generische Graphen oder fremde/inkonsistente Lineage | fail-closed | kein DTO |

`KNOWN_NONE` und `NOT_APPLICABLE` werden in v1 niemals erzeugt. Auch eine
Publication-Datei oder eine nicht als Archive-Source verwendete Datei könnte
als Member eines anderen Archives vorkommen. Ohne vollständige Member-Hash-
Coverage bleibt diese Beziehung unbekannt.

Der materielle Fingerprint verwendet `canonical-json/v1`, eine eigene
Domain-Separation, Profil, Rolle, FileObservation-/Root-/Scan-ID, Status sowie
bei `KNOWN_PRESENT` die ArchiveObservation-ID und deren `content_hash`.
Pfade, Locator, Basenames, CRC-Werte, Rohhashwerte der Source und Zeitpunkte
werden nicht serialisiert. Der Fingerprint ist keine neue Evidence-ID und
keine Identity-Aussage.

### Publication Container

EPUB, CBZ und CBR bleiben entsprechend ADR-0038 und ADR-0046 Publication
Container. Ihre interne ZIP-/RAR-Struktur allein erzeugt keine generische
Archive-Dependency. Besitzt dieselbe FileObservation zusätzlich ein
materiell widersprüchliches generisches Source-Binding, scheitert die
Projektion fail-closed; sie wählt keine günstigere Interpretation.

### Consolidation-Grenze

Für den Candidate erzeugt `KNOWN_PRESENT` weiterhin den bestehenden Blocker
`ARCHIVE_MEMBERSHIP_PRESENT`. Für den Keeper bleibt die Dependency sichtbar
und wird durch `ARCHIVE_RELATIONSHIP_UNCHANGED` in einem nicht ausführbaren
Plan gebunden. `UNKNOWN` erzeugt unverändert
`ARCHIVE_RELATIONSHIP_UNKNOWN`.

Die Persistenz darf `ARCHIVE_OBSERVATION` erst akzeptieren, nachdem der
Consolidation-Store die referenzierte Zeile, Root-/Scan-Lineage,
Sourcebindung, Publication-Grenze und den materiellen Fingerprint unabhängig
revalidiert. Ein frei konstruierter DTO oder lediglich syntaktisch gültiger
Snapshot-Identifier genügt nicht.

### Weiterhin blockierte Member-Byte-Strecke

Ein späteres Gate `FG-A3-MEMBER-BYTE` darf erst beginnen, wenn eine der
folgenden Evidence-Grenzen tatsächlich implementiert und auf einer
unterstützten Plattform geprüft ist:

1. die durch ADR-0048/ADR-0049 vorgesehene bounded Extraction mit vollständigem
   Member-SHA-256 und erfolgreichem Cleanup; oder
2. ein separat akzeptierter bounded Streaming-Hash-Vertrag, der ohne
   Locator-/argv-/Rawstream-Leak dieselben vollständigen unkomprimierten
   Memberbytes beweist.

CRC plus Größe bleibt auch dann ausschließlich Candidate-Blocking-Evidence.
`member_sha256` muss an ArchiveObservation, Memberordinal, Memberidentity,
Extraction-/Streaming-Execution, Tool-/Parser-/Formatlockprofil und Source-
Lineage gebunden sein. Fehlende, partielle, verschlüsselte, limitierte oder
stale Member-Evidence bleibt `UNKNOWN`.

Archive Member werden durch diese Entscheidung nicht zu `FileRecord` oder
neuen Relation-Endpoints. Falls EB-A3 später virtuelle Member-Entities,
Edition-/Work-Projektionen oder neue `RelationType`-Werte benötigt, ist dafür
ein weiteres Frontier-Gate erforderlich.

## Mechanische Pakete

### S-EBA3-01 — Reiner Source-Dependency-Vertrag

Erlaubt sind ausschließlich:

```text
src/foliotone/consolidation/archive_dependencies.py
src/foliotone/consolidation/__init__.py
tests/unit/test_consolidation_archive_dependencies.py
```

Das Paket implementiert immutable bounded Input-/Binding-DTOs, kanonische
Sortierung, die geschlossene Statusmatrix und den domain-separierten
Fingerprint. Es führt kein SQLite-, Filesystem-, Provider- oder Tool-I/O aus.

Routing: 5.3 Codex Spark `high`; bei fehlender Spark-Verfügbarkeit 5.4 Mini,
danach 5.6 Terra. Stop bei neuer Identity-, Publication-, Member- oder
Persistenzentscheidung.

### S-EBA3-02 — Bounded Archive-Source-Query und Store-Revalidierung

Erlaubt sind ausschließlich:

```text
src/foliotone/persistence/archive.py
src/foliotone/persistence/consolidation.py
tests/integration/test_archive_consolidation_dependencies.py
```

Die Query liest für höchstens zwei explizite FileObservation-IDs die
kanonischen Source-Bindings über vorhandene Indizes. Der Consolidation-Store
erweitert seine feste Dependency-Snapshot-Allowlist um
`ARCHIVE_OBSERVATION` und revalidiert den vollständigen v1-Vertrag vor jedem
Insert. Keine Migration und keine collection-weite Vorabladung sind zulässig.

Routing: 5.6 Terra `high`; Fallback 5.4 `high`. Stop bei fehlendem Index,
mehrdeutiger aktueller Graphauswahl oder notwendiger Schemaänderung.

### S-EBA3-03 — Nicht ausführbare Planintegration

Erlaubt sind ausschließlich:

```text
src/foliotone/workflows/archive_consolidation.py
src/foliotone/consolidation/planner.py
tests/unit/test_archive_consolidation_workflow.py
tests/integration/test_archive_consolidation_dependencies.py
```

Das Paket erzeugt für exakt die zwei File-Endpunkte eines vorhandenen
actionable `EXACT_DUPLICATE`-Candidates je eine Archive-Dependency und reicht
sie an den bestehenden Planner. Es erzeugt weder neue Relation Candidates
noch Keep Preference oder Reviewentscheidungen. Candidate-Sourcegraph,
Keeper-Unchanged-Precondition, Publication-Grenze, `UNKNOWN` und
Planner→Store-Roundtrip werden fokussiert geprüft.

Routing: 5.6 Terra `high`; Fallback 5.4 `high`. Stop bei Erweiterung des
`consolidation-plan/v1`-Status-, Review-, Intent- oder Execution-Vertrags.

## Abnahme

Das Gate und seine Pakete benötigen:

- eine Widerspruchssuche gegen ADR-0034, ADR-0038, ADR-0046, ADR-0050,
  ADR-0052 und ADR-0053;
- direkte DTO-Negativtests für fremde Lineage, Publication-Konflikt,
  Mehrdeutigkeit, Bounds, Reihenfolge und Fingerprint-Drift;
- Query-/Store-Tests für generische direkte, Volume-, Wrapper- und
  Publication-Fälle sowie fehlende Evidence;
- Planner-/Blocker-/Precondition-Regressionen ohne Ausführungssurface;
- path-/locator-/hash-/secret-freie Fehler und Repräsentationen;
- genau einen vollständigen PR-CI-Gate je stabilem Paket.

## Nicht autorisiert

Diese Entscheidung autorisiert nicht:

- Extraction, Member-Byte- oder Member-/File-Matching;
- eine neue `Relation`, `RelationCandidate`, Identity- oder Confidence-Regel;
- virtuelle `FileRecord`-/`Edition`-/`Work`-Entitäten für Archive Member;
- Secretübergabe oder Passwortversuch;
- Onlineprovider oder collection-weite Inventarübertragung;
- Keep-Preference-, Review- oder Quality-Regeländerungen;
- Source-, Archive-, Sidecar-, Calibre- oder Metadatenwrites;
- Quarantäne, Move, Rename, Delete, Purge, Cleanup oder W10-Ausführung.

## Folgen

FolioTone kann bestehende Archive-Sourceverantwortung im nicht ausführbaren
Plan erstmals reproduzierbar belegen, ohne fehlende Memberbytes zu erraten.
Das reduziert `UNKNOWN` nur für tatsächlich bekannte generische
Sourcegraphen. Die vollständige EA8-Member-Identity, EA9-Integration und der
EB-A3-Abschluss bleiben bis zu weiterer Evidence beziehungsweise eigenen
Paketen offen.
