# ADR-0037: Book Classification trennt Assertions und Projections

- Status: Accepted
- Datum: 2026-08-20

## Kontext

ADR-0008 verlangt eine mehrdimensionale, Provenance-erhaltende
Klassifikation. Die book-only Verträge stellen bereits die sieben Dimensionen
`domain`, `genre`, `subgenre`, `topic`, `audience`, `language` und `form`
bereit. Das initiale Schema enthält außerdem bereits
`classification_assertions`; das generische `SQLiteRepository.save()` kann
eine vorhandene Zeile anhand ihrer ID aktualisieren. W5C-001 und W5C-002 sind
daher implementierte Tatsachen und keine Arbeit, die EB-04 erneut anlegen darf.

EB-04 benötigt weiterhin einen immutable und idempotenten Assertion-
Schreibpfad, eindeutige Source-Lineage, begrenzte Abfragen und eine
rebuild-fähige lokale Projection. Ohne einen getrennten Vertrag könnte eine
Migration die vorhandene Assertion-Tabelle duplizieren, Legacy-Zeilen
stillschweigend umdeuten oder Raw Assertions beim Auswählen einer Projection
überschreiben.

Classification bleibt Supporting Evidence. Sie darf Suche, Filterung und
Candidate Blocking unterstützen, kann aber allein weder `EXACT_DUPLICATE`,
`SAME_EDITION`, `SAME_WORK` noch eine andere Identity Relation bestätigen.

## Entscheidung

### Scope und öffentliche Literale

FG-04 ist book-only. Ein Classification Target ist ein bestehendes `WORK` oder
eine bestehende `EDITION`. Die exakten `ClassificationDimension`-Literale
bleiben:

- `domain`;
- `genre`;
- `subgenre`;
- `topic`;
- `audience`;
- `language`;
- `form`.

Die Dimensionen bilden keine Hierarchie ab. Insbesondere begründet `subgenre`
keinen Parent-`genre`, und eine Language Assertion beweist keine Work- oder
Edition-Identity.

Ein v1-Assertion-Wert ist NFC-normalisiert, nach der vorhandenen Whitespace-
und Casefold-Regel normalisiert und 1 bis 512 Unicode-Codepoints lang.
`taxonomy` ist ein 1 bis 128 Zeichen langer lowercase Identifier nach
`[a-z0-9][a-z0-9._-]{0,127}`. Freie Pfade, URLs und Provider-Payloads sind
keine Taxonomy-Identifier. `source_name` und `source_version` sind jeweils 1
bis 128 Unicode-Codepoints lang und dürfen keine Pfade enthalten.

Die Source-Kind-Literale lauten:

- `LOCAL_DERIVED` — eine versionierte lokale Regel oder ein lokaler Mapper;
- `TOOL_PROVIDER` — ein begrenztes Ergebnis einer konkreten `ToolExecution`;
- `KNOWLEDGE_PROVIDER` — ein normalisiertes Provider-Mapping-Ergebnis;
- `USER_CONFIRMED` — eine aus einer akzeptierten append-only
  `ReviewDecision` erzeugte Classification Assertion.

`USER_CONFIRMED` bezeichnet einen im Review bestätigten Classification-Fakt.
Eine Anzeige-, Sortier-, Keeper-, Quality- oder andere Nutzerpräferenz ist
keine Classification Evidence und darf keine `USER_CONFIRMED` Assertion
erzeugen.

Die Source-Reference-Kind-Literale lauten `LOCAL_RULE_RUN`, `TOOL_RESULT`,
`PROVIDER_MAPPING_OUTPUT` und `REVIEW_DECISION`. Die Kombination mit dem
Source Kind ist fest: `LOCAL_DERIVED` verwendet `LOCAL_RULE_RUN`,
`TOOL_PROVIDER` verwendet `TOOL_RESULT`, `KNOWLEDGE_PROVIDER` verwendet
`PROVIDER_MAPPING_OUTPUT` und `USER_CONFIRMED` verwendet `REVIEW_DECISION`.

Die Priority-Tier-Literale lauten:

- `AUTOMATED`;
- `USER_CONFIRMED`.

`LOCAL_DERIVED`, `TOOL_PROVIDER` und `KNOWLEDGE_PROVIDER` werden
`AUTOMATED` zugeordnet. `USER_CONFIRMED` wird `USER_CONFIRMED` zugeordnet.
Das zuletzt genannte Tier besitzt Vorrang vor `AUTOMATED`; zwischen
automatisierten Sources besteht keine Prioritätsreihenfolge. FolioTone
definiert keinen globalen universellen Classification Score.

Die Projection-Statusliterale lauten:

- `EMPTY` — es existiert keine geeignete profilierte Assertion;
- `PROJECTED` — jedes nicht leere Facet kann konfliktfrei projiziert werden;
- `REVIEW_REQUIRED` — mindestens ein Facet enthält einen Konflikt.

Die Statusliterale je Facet lauten `EMPTY`, `PROJECTED` und `CONFLICT`. Die
Conflict-Code-Literale lauten `MULTIPLE_EXCLUSIVE_VALUES`,
`CARDINALITY_EXCEEDED` und `CONFIRMED_CONTRADICTION`. Die Link-Rollen zwischen
Projection und Assertion lauten `SELECTED`, `CONSIDERED` und `CONFLICTING`.

### Grenze zwischen Assertion und Projection

Eine `ClassificationAssertion` ist Source Evidence. Sie behält Target,
Dimension, normalisierten Wert, Taxonomy, Assertion-lokale Confidence,
Provenance, Source Kind, stabile Source Reference und Assertion Profile. Die
Projection Logic aktualisiert sie niemals.

Eine `BookClassificationProjection` ist Derived State. Sie enthält nur
ausgewählte Facet-Werte, Status, Conflict Codes, exakte Assertion Links, Input
Fingerprint und Projection Profile. Sie ist keine Source Assertion und darf
nicht als neue Classification Evidence zurückgeführt werden. Reprojection
erzeugt oder verwendet einen immutable Projection Snapshot; sie bearbeitet
oder löscht keine Assertion.

Die kanonischen Profile-Literale der ersten Implementierung lauten:

- `book-classification-assertion/v1`;
- `book-classification-projection/v1`;
- `book-classification-decision-compatibility/v1`;
- `book-classification-canonical-json/v1`.

Producer-spezifische Parser-, Tool-, Provider- und Mapping-Versionen bleiben
zusätzlich zum Assertion Profile in der Provenance erhalten. Ein Profile-
Literal ist exakt; neue Semantik benötigt ein neues Profile statt einer
In-place-Umdeutung.

### Bestehende Tabelle und Compatibility

Migration `0018_book_classification_projection` ist additiv. Sie darf keine
zweite Raw-Assertion-Tabelle erstellen und `classification_assertions` weder
umbenennen noch umschreiben oder löschen. Sie ergänzt:

- `book_classification_assertion_lineage` mit einem one-to-one Foreign Key zu
  `classification_assertions`, eindeutigem `assertion_key`, Assertion
  Profile, Source Kind, stabiler Source Reference, Priority Tier und
  Erstellungszeit;
- immutable `book_classification_projections`;
- geordnete `book_classification_projection_values`;
- `book_classification_projection_assertions` mit exakter Link Role und
  optionalem Conflict Code.

Die Migration ergänzt gemessene Target-/Profile- und Projection-Lookup-
Indizes. Sie führt kein geratenes Backfill der Lineage aus. Vorhandene
Assertion-Zeilen ohne Lineage Record bleiben über das W1-Compatibility-
Repository lesbar, EB-04-Queries und Projections schließen sie jedoch aus.
Sie sind `legacy-unprofiled` und werden nicht stillschweigend als
`book-classification-assertion/v1` behandelt. Ein künftiger expliziter
Importer darf sie nur dann profilieren, wenn er die Source-Lineage belegen
kann.

Der bestehende Helper `build_classification_assertions()` und das generische
Repository bleiben importkompatibel. Ihre zufälligen IDs und das Update-by-ID-
Verhalten sind nicht für EB-04-Persistenz freigegeben. Der dedizierte EB-04-
Store verwendet insert-only SQL. Eine Wiederholung derselben Assertion ist ein
No-op; eine vorhandene ID oder ein vorhandener Key mit anderem kanonischem
Inhalt ist ein Integritätsfehler.

`assertion_key` ist SHA-256 über `book-classification-canonical-json/v1` sowie
Target Kind/ID, Dimension, normalisierten Wert, Taxonomy, Assertion Profile,
Source Kind und stabile Source Reference. Observation Time und Confidence
gehören zum gespeicherten Inhalt, ersetzen aber keine stabile Source
Reference. Ein Producer ohne stabilen ToolResult-, Provider-Mapping-, Local-
Rule-Run- oder ReviewDecision-Bezug darf keine EB-04 Assertion persistieren.
Neue Assertion IDs sind deterministische UUIDv5-Werte aus dem Assertion Key.
Der feste Namespace lautet
`d3636547-6437-5d62-bf35-37a004008630`.

### Source-, Confidence- und Priority-Regeln

Jede Source Reference ist path-free und verweist auf genau eine der folgenden
Source-Klassen:

- ein lowercase SHA-256 über Regelprofil, Target-Input-Fingerprint und
  Producer-Version als Local-Rule-Run-Reference für `LOCAL_DERIVED`;
- die kanonische UUID eines konkreten `ToolResult` und damit dessen
  `ToolExecution` für `TOOL_PROVIDER`;
- einen Provider-Mapping-Output-Fingerprint einschließlich Mapping Input Key,
  Source-Payload-Generation beziehungsweise -Digest und Provider-/Source-/
  Mapping Profile als lowercase SHA-256 für `KNOWLEDGE_PROVIDER`;
- die kanonische UUID einer konkreten akzeptierten `ReviewDecision` für
  `USER_CONFIRMED`.

`source_reference` ist damit entweder eine kanonische 36-Zeichen-UUID oder ein
lowercase SHA-256 mit 64 Hex-Zeichen; andere Formen sind ungültig. Der Store
validiert lokal persistierte `ToolResult`- und `ReviewDecision`-References in
derselben Transaktion. Provider Mapping References sind begrenzte kanonische
Hashes; Classification-Tabellen übernehmen keine Raw Provider Payloads.

Eine Source Reference bezeichnet einen immutable Source Event. Wird
Confidence, Observation Time oder ein anderer gespeicherter Inhalt neu
bewertet, benötigt die neue Assertion eine neue Source Reference oder eine
erhöhte Producer-/Mapping-Version. Andernfalls behandelt der Store die
abweichenden Bytes als Integritätsfehler.

Confidence ist `null` oder ein endlicher Wert im geschlossenen Intervall
`[0.0, 1.0]`. Sie beschreibt nur die Source Assertion innerhalb ihres eigenen
Producer-Vertrags. Sie ändert das Priority Tier nicht, macht Scores
verschiedener Provider nicht vergleichbar und löst niemals einen Widerspruch
auf. Die Projection kann semantisch gleiche Werte mehrerer Sources
zusammenführen; jeder Assertion Link bleibt dabei erhalten.

### Projection Reducer

Der Reducer ist rein und akzeptiert ausschließlich Assertions eines Targets
mit exakt `book-classification-assertion/v1`. Vor der Auswertung sortiert er
alle Inputs anhand des Assertion Key. Für jede Dimension wählt er zunächst das
höchste vorhandene Priority Tier. Assertions eines niedrigeren Tiers bleiben
als `CONSIDERED` verknüpft.

`domain` ist in Projection v1 single-valued. Mehr als ein unterschiedlicher
Wert im höchsten Tier erzeugt `CONFLICT`; kein Domain-Wert wird ausgewählt.
Bei zwei widersprüchlichen `USER_CONFIRMED` Assertions lautet der Conflict
Code `CONFIRMED_CONTRADICTION`, andernfalls
`MULTIPLE_EXCLUSIVE_VALUES`.

Die übrigen Facets sind set-valued und besitzen nach Deduplication folgende
exakten Höchstwerte:

| Dimension | Maximal projizierte Werte |
|---|---:|
| `genre` | 8 |
| `subgenre` | 16 |
| `topic` | 32 |
| `audience` | 8 |
| `language` | 8 |
| `form` | 8 |

Werte werden anhand von `(taxonomy, normalized_value)` sortiert. Das
Überschreiten eines Höchstwerts erzeugt `CARDINALITY_EXCEEDED`; das Facet wählt
keine Werte aus und behält alle Inputs als `CONFLICTING`. Projection v1 leitet
keine dimensionenübergreifenden semantischen Widersprüche ab. Der
Fiction-/Computer-Science-/Technical-Reference-Abnahmefall ist daher nur dann
ein Konflikt, wenn das Mapping Profile gegenseitig ausschließende `domain`-
Werte emittiert. Emittieren die Sources getrennte `domain`-, `topic`- und
`form`-Facets, bleiben alle drei unabhängige gültige Assertions.

Ein konfliktbehaftetes Facet setzt den Gesamtstatus auf `REVIEW_REQUIRED`;
konfliktfreie Facets bleiben inspizierbar. Der Reducer erzeugt keine
`ReviewDecision` und schreibt keine kanonischen Work- oder Edition-Metadaten.

### Idempotency, Compatibility und Reprojection

Der Projection Input Fingerprint ist SHA-256 über kanonisches JSON mit Target,
Assertion Profile und den vollständig sortierten Assertion Keys. Zeitstempel
und Datenbank-Reihenfolge sind ausgeschlossen. Die Projection Identity ist
eine deterministische UUIDv5 über Target, Projection Profile und Input
Fingerprint.
Der feste Projection-Namespace lautet
`3b130592-d8aa-5f56-9c9f-acde3b159e89`.

Das eindeutige Tupel `(target_kind, target_id,
projection_profile_version, input_fingerprint)` macht eine exakte Wiederholung
zum No-op. Neue Assertion Inputs oder ein neues Projection Profile erzeugen
einen neuen immutable Snapshot. Ein alter Snapshot bleibt auditierbar und
wird nicht auf die neue Semantik umgeschrieben.

Eine künftige Wiederverwendung einer Classification Review Decision benötigt
exakt `book-classification-decision-compatibility/v1`, Target, Assertion
Profile, Projection Profile und Input Fingerprint. Eine technische
Implementierungsversion allein begründet keine Compatibility. EB-04 ergänzt
keine zweite Review-Historie neben dem bestehenden append-only Review Core.

### Begrenzter Zugriff, Privacy und Lineage

Assertion Reads verlangen ein Target, ein Assertion Profile und ein Limit von
1 bis 500. Sie sortieren nach Dimension, Taxonomy, normalisiertem Wert und
Assertion Key, lesen höchstens `limit + 1` Records und scheitern bei Overflow
explizit. EB-04 besitzt keinen collection-weiten `list_all()`-Pfad.

Projection- und read-only Report-DTOs enthalten feste Literale, interne IDs,
Counts, Profile Versions, Fingerprints sowie Truncation-/Conflict-Marker. Sie
enthalten keine absoluten oder relativen Pfade, Filenames, Raw Provider
Responses, Raw Tool Outputs, extrahierten Inhalte, Collection Inventories oder
User Identity. Classification Values bleiben im privaten lokalen Projection-
State und in begrenzten Target-spezifischen Anwendungsergebnissen; die CLI-
Zusammenfassung aus S-EB04-07 gibt ausschließlich feste Labels, IDs und Counts
aus.

Alle Tests verwenden synthetische Targets, Values und Source References.
EB-04 führt keinen Netzwerkzugriff aus, öffnet keine Source Media und
autorisiert weder Metadata Write, Move, Quarantine, Delete noch eine andere
W10-Operation.

## Paketgrenzen

- `S-EB04-01` besitzt ausschließlich
  `src/foliotone/persistence/alembic/versions/0018_book_classification_projection.py`,
  `src/foliotone/persistence/classification_schema.py` und
  `tests/integration/test_classification_migration.py`. Das Paket erstellt alle
  fehlenden Lineage- und Projection-Tabellen, aber keinen Store oder Reducer.
- `S-EB04-02` besitzt `src/foliotone/classification/contracts.py`, die neue
  `src/foliotone/persistence/classification.py` und
  `tests/integration/test_classification_persistence.py`. Es ergänzt die
  Assertion-/Lineage-Verträge und implementiert atomare insert-only Assertions
  und Lineage. Es verwendet nicht `SQLiteRepository.save()`; Paketexporte
  folgen gemeinsam mit dem Projection-Vertrag in S-EB04-04.
- `S-EB04-03` ändert ausschließlich
  `src/foliotone/persistence/classification.py` und
  `tests/integration/test_classification_persistence.py`, um die begrenzte
  Target-/Profile-Query und einen gemessenen Indexplan zu ergänzen.
- `S-EB04-04` besitzt `src/foliotone/classification/projection.py`,
  `src/foliotone/classification/__init__.py` und
  `tests/unit/test_classification_projection.py`. Es deckt konfliktfreie
  Golden Cases und keine Persistenz ab.
- `S-EB04-05` ändert ausschließlich das Projection-Modul und dessen
  Unit-Testdatei für die exakte Priority-, Confidence-, Cardinality- und
  Conflict-Semantik.
- `S-EB04-06` besitzt `src/foliotone/workflows/classification.py`, den
  dedizierten Store und `tests/integration/test_classification_workflow.py`.
  Es persistiert immutable Projection Snapshots und belegt Deterministic No-op
  sowie Profile-changing Reprojection.
- `S-EB04-07` besitzt `src/foliotone/cli/main.py`, das Classification-
  Workflow-Modul, `tests/integration/test_classification_cli.py`, genau einen
  Classification-spezifischen Static Test, `BACKLOG.md` und
  `PROJECT_STATUS.md`. Es schließt W5C-004 erst, wenn der vollständige EB-04-
  Vertrag grün ist.

Kein Paket darf W1-Migrationen ändern, Legacy Assertions umdeuten, ein
Provider-Schema in Domain Logic einführen oder W5C-001/W5C-002 von `DONE`
wegsetzen.

## Erforderliche Tests

Die Pakettests decken mindestens ab:

- Migration von `0017` und Empty-Database-Upgrade, Tabellen, Foreign Keys,
  Unique Keys und Target-/Profile-Indizes;
- Erhalt von Legacy Assertions und Ausschluss aus profilierten Queries;
- Idempotency einer exakten Wiederholung, Different-content Collision und
  atomaren Rollback;
- Koexistenz widersprüchlicher Provider und exakte Source-Lineage-Links;
- begrenzte Target-/Profile-Reads, deterministische Reihenfolge, Overflow und
  das Fehlen eines collection-weiten Fallbacks;
- jede Dimension, jedes öffentliche Literal und jede Set-Grenze;
- Equal-value Coalescing ohne Assertion-Verlust;
- Automated Conflict, bestätigte Priority und bestätigten Widerspruch;
- Nichtvergleichbarkeit von Confidence und Nichtauflösung von Konflikten;
- stabile Input Fingerprints, Same-profile No-op und New-profile Snapshot;
- privacy-sichere `repr`-/DTO-/CLI-Ausgabe und statischen Nachweis, dass
  Classification allein keine Identity Relation bestätigen kann.

## Folgen

- Bestehende W1-/W5C-Classification-Daten bleiben unverändert und kompatibel.
- Raw Source Assertions und abgeleitete lokale Views erhalten unterschiedliche
  immutable Persistenzpfade.
- Konflikte bleiben reviewbar, ohne einen universellen Score zu erfinden oder
  Evidence eines niedrigeren Tiers zu verwerfen.
- Reprojection ist deterministisch und anhand des Profiles selektiv
  invalidierbar.
- Das zusätzliche Schema erhöht den Umfang, vermeidet aber Update-in-place-
  Mehrdeutigkeit und erhält vollständige Lineage.

## Verwandte Entscheidungen

- [ADR-0008](ADR-0008-multidimensional-classification.md)
- [ADR-0006](ADR-0006-authority-entity-resolution-provenance.md)
- [ADR-0028](ADR-0028-persisted-resolution-and-review-core.md)
- [ADR-0029](ADR-0029-bounded-ebook-candidate-blocking.md)
