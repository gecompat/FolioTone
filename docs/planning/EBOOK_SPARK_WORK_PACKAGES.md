# Spark-Arbeitspakete für die E-Book-Endgerade

**Status:** In Ausführung; S-EBA-01 bis S-EBA-07, S-EBAR-01 bis
S-EBAR-03A, EBAR-04, S-EBAR-02A bis S-EBAR-02C und EBAR-05 abgeschlossen;
FG-A-STORAGE-FAMILY, FG-A-FORMAT-LOCK und
FG-A-EXTRACTION-LIFECYCLE entschieden; S-EBAR-05A als nächstes Paket

**Stand:** 2026-08-20

**Scope:** Atomare Implementierungspakete für Codex Spark innerhalb der
E-Book-Lieferwellen EB-00, EB-03A, EB-03B, EB-04, EB-07, EB-08 sowie begrenzter
Vorarbeiten aus EB-A1 und EB-A2

**Vorgesehene Ausführung:** 5.3 Codex Spark mit Thinking `high` als Standard
und kontrollierter Eskalation gemäß diesem Dokument; die Aufgabengrenzen
bleiben unabhängig von der konkreten Modellverfügbarkeit verbindlich

## Einordnung

Dieses Dokument verfeinert den
[`E-Book-Endgame-Ausführungsplan`](EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md). Die
W-, E-, EA- und EB-Bezeichnungen, Statuswerte und Sicherheitsgrenzen des
Endgame-Plans bleiben maßgeblich. Die Kennzeichnung „Spark-tauglich“ ist eine
FolioTone-interne Aufgabeneinstufung und keine allgemeine Aussage über eine
Modellgarantie.

Ein Paket ist nur dann Spark-tauglich, wenn alle fachlichen Entscheidungen vor
Beginn feststehen, der erlaubte Dateibereich klein ist, das Ergebnis durch
deterministische Tests beweisbar ist und ein Abbruch bei Vertragsabweichung
keinen unfertigen Zustand auf `main` hinterlässt.

## Adaptive Modell- und Thinking-Regel

Der repositoryweite Vertrag steht in
[`MODEL_ROUTING_POLICY.md`](MODEL_ROUTING_POLICY.md). Der koordinierende
Codex-Task wählt Modell und Thinking automatisch anhand dieser Richtlinie und
der nachstehenden strengeren E-Book-Grenzen. Eine erneute Benutzerfrage ist
nicht erforderlich, solange die Arbeit innerhalb des genehmigten E-Book-Scopes
und dieser Grenzen bleibt.

| Aufgabenklasse | Modell | Standard | Zulässige Eskalation |
|---|---|---|---|
| Atomare Pakete dieses Dokuments | `gpt-5.3-codex-spark` | `high` | Wechsel zu 5.4 Mini oder 5.6 Terra nur nach dem repositoryweiten Fallback-Vertrag; eine offene Architekturfrage stoppt das Paket |
| Statusabgleich, gewöhnliche Reviews, CI-Triage und Merge-Verifikation | `gpt-5.6-luna` | `low` oder `medium` | 5.4 Mini oder 5.6 Terra nur bei Kapazitäts- oder Qualitätsbedarf |
| Gewöhnliche Integration innerhalb akzeptierter Verträge | `gpt-5.6-terra` | `medium` | `high`, wenn mehrere Schichten oder ein ungeklärter reproduzierbarer Fehler betroffen sind |
| Frontier-Gates für Provider, Classification, Calibre, Persistenz und nicht ausführbare Planung | `gpt-5.6-sol` | `medium` | `high`, wenn neue öffentliche Verträge oder mehrere kanonische Schichten betroffen sind |
| EB-01, EB-02, EB-05, EB-06, Archive-Security und vergleichbare kritische Architekturarbeit | `gpt-5.6-sol` | `high` | `xhigh` nur für die unten genannten kritischen Risikoklassen; `max` nur nach den festgelegten Kriterien |
| W10-Entscheidung oder bestätigter datenverlustrelevanter Fehler | `gpt-5.6-sol` | `max` | keine automatische Erweiterung des genehmigten Scopes |

Eine Eskalation von `medium` auf `high` erfolgt, wenn mindestens eines der
folgenden Merkmale vorliegt:

- ein neuer öffentlicher Vertrag, ein Persistenzschema oder eine
  Rückwärtskompatibilitätsregel muss festgelegt oder überprüft werden;
- mehrere kanonische Plan-, Domain- oder Statusquellen müssen widerspruchsfrei
  zusammengeführt werden;
- ein Fehler bleibt nach einem gezielten Reproduktions- und Diagnoseversuch
  ungeklärt;
- ein Pull Request verändert mehrere Schichten trotz bereits begrenztem Scope.

Eine Eskalation des nach der Modellmatrix zuständigen Frontier-Modells auf
`xhigh` erfolgt nur bei:

- Lease, Fencing, stale Takeover, atomaren Writes oder anderer Nebenläufigkeit;
- Identity Resolution, Relation Taxonomy, Candidate Blocking, Scoring,
  automatischer Bestätigung oder Review-Reuse;
- Secret Handling, Sandbox-/Archive-Grenzen oder adversarial Input;
- sicherheitskritischen Preconditions eines `ConsolidationPlan`;
- einem wiederholten, belastbar reproduzierten Fehler, dessen Ursache mehrere
  dieser Risikoklassen berührt.

`max` bleibt reserviert für eine ausdrückliche W10-Sicherheitsentscheidung oder
einen bestätigten Fehler mit realistischer Gefahr irreversiblen Datenverlusts.
Die höhere Thinking-Stufe erteilt niemals zusätzliche Berechtigungen. Bei einer
Scope-Erweiterung, destruktiven Aktion oder fehlenden Benutzerentscheidung muss
der Task unabhängig von Modell und Thinking stoppen.

Wenn Spark während eines Pakets eine nicht im Frontier-Gate entschiedene
Architektur- oder Sicherheitsfrage entdeckt, darf das Paket nicht allein durch
Eskalation auf `xhigh` fortgesetzt werden. Es stoppt unverändert; ein separates
Frontier-Task klärt die Frage mit der für die Risikoklasse vorgesehenen Stufe.

## Nicht autonom an Spark delegieren

Folgende Kernwellen bleiben bei einem Frontier-Modell und werden nicht durch
die nachstehenden Pakete ersetzt:

| Welle | Grund |
|---|---|
| EB-01 | Lease, Fencing, stale Takeover und atomare Writer-Koordination sind nebenläufigkeits- und sicherheitskritisch. |
| EB-02 | Entity Resolution, Identitätsebenen und Review-Reuse bestimmen langfristige Domain- und Persistenzverträge. |
| EB-05 | Candidate Blocking und Relation Taxonomy entscheiden über Recall, False Positives und Skalierung. |
| EB-06 | Scoring, automatische Bestätigung und Review-Status sind fachlich und sicherheitskritisch. |
| EB-A2 Extraction Runtime | Toolauswahl, Prozessisolation, Secret Channel und Archivbomben-Abwehr benötigen ein Security Gate. |
| EB-A3 | Archive-aware Matching und Deduplizierungsplanung hängen von EB-05, EB-06 und EB-07 ab. |
| W10/EA11/EA12 | Jede Mutation, Quarantäne, Löschung oder Verzeichnisbereinigung bleibt gesperrt. |

Spark darf nach einem Frontier-Gate mechanische Folgearbeiten für diese Wellen
übernehmen, beispielsweise Fixture-Erweiterungen oder einen bereits exakt
spezifizierten Mapper. Solche Folgearbeiten benötigen ein eigenes Paket und
dürfen nicht aus diesem Dokument abgeleitet werden.

## Verbindlicher Vertrag für jedes Spark-Paket

Jedes Paket wird einzeln auf dem dann aktuellen `origin/main` begonnen. Ein
Paket entspricht genau einem Branch, einem Commit-Scope und einem Pull Request.
Der Pull Request erhält genau einen vollständigen CI-Gate.

Vor dem ersten Schreibzugriff muss der ausführende Task:

1. `AGENTS.md`, den Endgame-Plan und dieses Dokument lesen;
2. Arbeitsverzeichnis, Branch, `origin/main`, Dirty State und die im Paket
   erlaubten Dateien prüfen;
3. bestätigen, dass alle genannten Voraussetzungen auf `origin/main` erfüllt
   sind;
4. vorhandene Benutzeränderungen unangetastet lassen und bei Überschneidung
   einen sauberen Worktree unter `C:\rep\worktrees\FolioTone` verwenden;
5. ausschließlich synthetische Fixtures und projektbezogene Cache-, Temp- und
   Artefaktpfade unter `C:\rep` verwenden.

Für jedes Paket gelten zusätzlich folgende Grenzen:

- höchstens ein fachlicher Vertrag oder ein Persistenzschritt pro Paket;
- grundsätzlich höchstens zwei Produktdateien und zwei Testdateien; ein
  Migrationspaket darf zusätzlich genau eine Migration und die zentrale
  Schema-Datei ändern;
- keine neue Abhängigkeit, kein neuer Online-Provider und keine Änderung eines
  öffentlichen Vertrags, sofern das Paket dies nicht ausdrücklich erlaubt;
- keine Live-Netzwerktests, privaten Pfade, realen Sammlungsdaten, Secrets oder
  Runtime-Berichte im Repository;
- keine Source-Media-Mutation und keine ausführbare W10-Operation;
- keine unaufgeforderte Bereinigung angrenzender Module;
- gezielte Tests während der Arbeit und genau ein vollständiger PR-CI-Gate;
- Merge nur bei grünem Gate und konsistentem Diff.

Der Task bricht ohne Implementierung ab, wenn eine Voraussetzung fehlt, der
aktuelle Code dem festgelegten Vertrag widerspricht, eine zusätzliche
Architekturentscheidung nötig wird, die Dateigrenze nicht eingehalten werden
kann oder ein Test nur durch Abschwächung einer Sicherheitsinvariante grün
würde.

## Frontier-Gates vor Spark-Ausführung

Ein Frontier-Gate ist eine dokumentierte Entscheidung, keine umfangreiche
Implementierungswelle. Der Gate-PR muss die genannten Literale, Invarianten,
Persistenzgrenzen und Kompatibilitätsregeln so festlegen, dass Spark sie nur
noch implementiert.

| Gate | Muss vorliegen, bevor Spark beginnt |
|---|---|
| FG-00 | Durch [ADR-0026](../decisions/ADR-0026-provider-access-and-cache-policy.md) akzeptiert: exakte `ProviderAccessMode`-/`ProviderCachePolicy`-Literale, Legacy-Mapping und Deprecation-Regel. |
| FG-03A | Durch [ADR-0035](../decisions/ADR-0035-provider-cache-runtime-contract.md) akzeptiert: Cache-Payload-Regel je Provider, TTL-/Freshness-Regeln, getrennte Source-/Mapping-Keys, CAS-Transaktionsgrenze und bounded Retention. |
| FG-03B | Durch [ADR-0036](../decisions/ADR-0036-open-library-first-book-provider.md) akzeptiert: Open Library als erster begrenzter realer Book Provider, feste Endpoint- und Identifierreihenfolge, normalisierte Source-DTOs, Privacy-, Rate-, Cache-, Lizenz- und Bulk-Grenzen. |
| FG-04 | Durch [ADR-0037](../decisions/ADR-0037-book-classification-assertions-and-projections.md) akzeptiert: book-only Facets/Literale, immutable Assertion-Lineage, Projection-Priorität, Konfliktstatus, Profile, Compatibility und Reprojection. |
| FG-07 | Durch [ADR-0033](../decisions/ADR-0033-read-only-calibredb-library-reconciliation.md) akzeptiert: vollständige read-only `calibredb`-Command-Shapes, Toolmanifest, Snapshot-Lineage sowie Ownership-/Sidecar-Vertrag. |
| FG-08 | Durch [ADR-0034](../decisions/ADR-0034-non-executable-consolidation-plans.md) akzeptiert: finale `ConsolidationPlan`-DTOs, Status-/Blocker-Literale, Identity-/Keeper-/Candidate-Grenzen, Precondition-Semantik, kanonische Serialisierung, Persistenzschema und Non-Execution-Grenze. |
| FG-A | Durch [ADR-0038](../decisions/ADR-0038-safe-archive-container-analysis.md) akzeptiert: 7-Zip 26.02 nur für feste read-only Shapes, exakte Format-/Signatur-Allowlist, Status-/Profil-/Budgetliterale, `SecretHandle`-Grenze und blockierte verschlüsselte Runtime ohne sicheren Secret-Kanal. |
| FG-A-RUNTIME | Durch [ADR-0039](../decisions/ADR-0039-safe-archive-runtime-and-secret-channel.md) akzeptiert: spezialisierter bounded Streaming-Runner und private Extraction-Sandbox für unverschlüsselte Archive; Raw-Ausgaben bleiben unpersistiert und jeder Secret-Kanal bleibt bis FG-A-SECRET blockiert. |
| FG-A-IMAGE | Durch [ADR-0040](../decisions/ADR-0040-reproducible-archive-runtime-image.md) akzeptiert: projekt-eigenes `linux/amd64`-`scratch`-Rezept mit dem statischen `7zzs`-Tar-Member, festen Binär- und Source-Lizenzinputs, UID/GID `65532:65532`, gepinntem Buildx-/BuildKit-Profil, zweistufigem Plattform-Manifest-Digest-Lock, nachträglichen SBOM-/Provenance-Attestations sowie öffentlichen/source-associated GHCR- und CI-Grenzen. |
| FG-A-STORAGE-FAMILY | Durch [ADR-0046](../decisions/ADR-0046-archive-publication-and-storage-family.md) akzeptiert: Publication Kind, direkte Storage Family und äußere Kompression sind orthogonal; Suffix, Containerklasse und Tooloutput dürfen die Signature-basierte Storage-Familie nicht überschreiben. |
| FG-A-FORMAT-LOCK | Durch [ADR-0047](../decisions/ADR-0047-final-archive-7zip-format-lock.md) akzeptiert: Der finale maschinenlesbare Lock bindet Capability-Zellen, geordnete Recordprojektionen und alle materiellen Measurement-/Runtimeidentitäten. |
| FG-A-EXTRACTION-LIFECYCLE | Durch [ADR-0048](../decisions/ADR-0048-private-archive-extraction-lifecycle.md) akzeptiert: privater EBAR-05-Listing-/CRC-Handoff, reiner interner Extraction-Validator, separates hartes Quota-Gate, synchroner Runner-owned Workspace-Consumer, zusätzlicher Polling-Frühabbruch, post-run no-follow-Revalidierung vor Cleanup sowie direkte Extraction ohne Wrapper. |

## EB-00: Provider-Vertrag ausrichten

**Voraussetzung für alle Pakete:** FG-00 ist gemergt.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB00-01 | Bestehende `OFFLINE`-/`ONLINE`-/`CACHE`-Verwendungen werden als Characterization Tests festgehalten; noch keine Produktionsänderung. | `tests/unit/test_enrichment.py` und höchstens eine neue Unit-Testdatei | Alle Legacy-Fälle sind parametrisiert und grün. |
| S-EB00-02 | Die in FG-00 festgelegten Access- und Cache-Policy-Enums werden additiv eingeführt. | `src/foliotone/enrichment/contracts.py`, `src/foliotone/enrichment/__init__.py`, `tests/unit/test_enrichment.py` | Literale, strikte Validierung und ungültige Kombinationen sind getestet; Legacy-Verhalten bleibt grün. |
| S-EB00-03 | Request-/Provider-DTOs verwenden die getrennten Dimensionen und das festgelegte Legacy-Mapping. | `src/foliotone/enrichment/contracts.py`, `src/foliotone/enrichment/providers.py`, `tests/unit/test_enrichment.py` | Jeder Legacy-Fall besitzt genau eine erwartete Abbildung; `OFFLINE` kann keinen Netzwerkzugriff anfordern. |
| S-EB00-04 | Veraltete Dokumentation wird entfernt und W5B-001 erst nach erfolgreicher Gesamtprüfung auf `DONE` gesetzt. | `docs/planning/BACKLOG.md`, `docs/planning/PROJECT_STATUS.md`, betroffene Provider-Referenz | Dokumentationsverträge, Linkprüfung und Suche nach widersprüchlichen Moduslisten sind grün. |

## EB-03A: Provider Cache und Runtime

**Voraussetzungen:** EB-01 ist abgeschlossen; S-EB00-01 bis S-EB00-04 und
FG-03A sind gemergt. Alle Pakete bleiben ohne echten Provider ausführbar.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB03A-01 | Immutable Content-/Failure-Slot-DTOs, Cache-Limits und die festgelegten Result-/Freshness-Literale werden implementiert. | neue Datei unter `src/foliotone/enrichment/`, tests/unit/test_enrichment.py | Sum-Type-Invarianten, Zeitgrenzen, Limits, ungültige Zustände und path-free Repräsentation sind getestet. |
| S-EB03A-02 | `BookKnowledgeQuery` erhält den versionierten kanonischen v2-Fingerprint; Key-Builder erzeugen den vierteiligen `source_cache_key` und den um `mapping_profile_version` erweiterten fünfteiligen `mapping_input_key`. | `src/foliotone/enrichment/contracts.py`, Cache-Modul aus S-EB03A-01, neue fokussierte Unit-Testdatei | Delimiter-Angriffe, Reihenfolgeunabhängigkeit, Mapping-Reuse, Versionsänderungen und Unicode-Grenzfälle besitzen feste Golden Values. |
| S-EB03A-03 | Eine additive Migration und Schemaobjekte speichern Cache-Metadaten ohne private Pfade. | genau eine neue Alembic-Migration, `src/foliotone/persistence/w3_schema.py` oder der durch FG-03A benannte Nachfolger, ein Migrationstest | Upgrade vom vorherigen Head, Indizes, Foreign Keys und Head-Eindeutigkeit sind geprüft. |
| S-EB03A-04 | Ein Store bietet `get`, generation-gefencetes `compare_and_replace` und bounded Expired-Pruning. | neue Persistenzdatei, `src/foliotone/persistence/__init__.py`, eine Integrationstestdatei | Hit, Miss, CAS-Konflikt, Capacity-Failure, Replace und injizierter Rollback sind deterministisch getestet. |
| S-EB03A-05 | Ein reiner Freshness-Evaluator klassifiziert frisch, stale und abgelaufen mit injizierbarer Clock. | Cache-Modul, fokussierte Unit-Tests | Grenzzeitpunkte werden ohne Sleeps getestet. |
| S-EB03A-06 | `NOT_FOUND` erhält die kürzere negative TTL; Failure-, Rate-Limit- und Timeout-Ergebnisse werden nicht als `NOT_FOUND` gespeichert. | Cache-Modul und Store-Test | Ergebnismatrix und Persistenzzeilen entsprechen exakt FG-03A. |
| S-EB03A-07 | Die Provider Runtime nutzt Cache Hit, Stale Policy und Refresh, ohne Provider Mapping und Transport zu vermischen. | `src/foliotone/enrichment/providers.py`, Cache-Modul, `tests/unit/test_enrichment.py` | Fake Transport zählt Aufrufe; Hit verursacht null Fetches, Refresh genau einen Fetch. |
| S-EB03A-08 | Ein harter Offline-Test lässt jeden Socket-/HTTP-Versuch sofort fehlschlagen. | ausschließlich Provider-Runtime-Tests | `OFFLINE` funktioniert mit Cache Hit und Miss ohne Netzwerk; der Test enthält keine Live-Adresse. |
| S-EB03A-09 | Mapping-Reanalyse verwendet zulässige Cache-Bytes erneut, ohne Fetch; Status und Backlog werden aktualisiert. | Provider Runtime, ein Integrationstest, betroffene Planungsdokumente | Mapping-Versionswechsel erhöht Mapping-Aufrufe, aber nicht Transport-Aufrufe; gesamter EB-03A-DoD ist nachgewiesen. |

## EB-03B: erster realer Book Provider

**Voraussetzungen:** EB-03A ist abgeschlossen und FG-03B ist durch ADR-0036
akzeptiert. Alle Pakete verwenden ausschließlich synthetische Daten. Die
bereits umgesetzten S-EB03B-01 bis S-EB03B-04 dokumentieren den v1-Ausgang;
S-EB03B-03A erhöht Adapter und Source auf `openlibrary-book-adapter/v2` sowie
`openlibrary-source-record/v2`, S-EB03B-05 danach das Mapping auf
`openlibrary-book-mapping/v2`. Die ursprünglichen v1-Profile werden nicht
in-place umgedeutet. S-EB03B-03A ist das verpflichtende Parser-Addendum vor
S-EB03B-05; Query-Shapes und direkte Work-/Edition-Semantik bleiben
unverändert.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB03B-01 | Handgeschriebene synthetische JSON-Fixtures decken direkten Work-/Edition-/Author-Treffer, ISBN, OCLC/LCCN, leeres Ergebnis, die exakte Zwei-Seiten-Search-Regel, Sparse Data und ungültige Antwort ab. | `tests/fixtures/openlibrary/v1/**`, `tests/unit/test_openlibrary_fixtures.py` | README bestätigt synthetische Erzeugung; Page-2-Fixtures unterscheiden `numFound`/`num_found > 10` ohne starken Doc vom Seite-1-Stop mit gültigem Work-OLID plus eingebettetem Edition-OLID oder ISBN; keine realen Titel, Personen, OLIDs, Anfragen, Pfade, Dumps oder kopierten Antworten; JSON-, Größen-, Page- und Privacy-Strukturtest ist grün. |
| S-EB03B-02 | Reine Query-/Route-DTOs setzen Identifierreihenfolge, exakt erlaubte URL-Shapes und das Zwei-Request-Budget je Queryroute aus ADR-0036 um. | `src/foliotone/adapters/openlibrary/query.py`, `src/foliotone/adapters/openlibrary/__init__.py`, `tests/unit/test_openlibrary_query.py` | Edition-OLID, Work-OLID, ISBN-13, ISBN-10, OCLC, LCCN und Titel-plus-genau-ein-resolved-Author besitzen Golden URLs; Search verbraucht Request 2 nur für die exakte Pagination und direkte Routen höchstens für einen referenzierten Author; Sortierung/Deduplizierung sowie negative Pfad-, Filename-, Host-, Parameter-, Fan-out- und freie-`q`-Fälle sind grün. |
| S-EB03B-03 | Ein reiner Parser erzeugt ausschließlich `openlibrary-source-record/v1` mit getrennten Work-/Edition-/Author-Records und festen Bounds. | `src/foliotone/adapters/openlibrary/source.py`, `tests/unit/test_openlibrary_source.py` | Alle S-EB03B-01-Fixtures liefern exakt `SUCCESS`, `NOT_FOUND` oder `INVALID_RESPONSE`; unbekannte/ausgeschlossene Felder werden verworfen, Kürzung ist sichtbar, Ausgabe bleibt unter 262.144 Byte und Netzwerk wird technisch blockiert. |
| S-EB03B-04 | Der Mapper projiziert Work-/Edition-Identifier und erlaubte bibliografische Felder getrennt in FolioTone Evidence. | `src/foliotone/adapters/openlibrary/mapping.py`, `tests/unit/test_openlibrary_mapping.py` | Keine Edition kollabiert zum Work; Identifier bleiben namespaced, Search-Rang wird nicht Confidence, alle Werte sind `ValueState.EXTERNAL` und tragen Provider-/Source-/Adapter-/Mapping-Provenance. |
| S-EB03B-03A | Parser-Addendum: `SearchSourceRecord.contributor_names` bewahrt Top-Level-`author_name` getrennt von `author_refs`; Source-/Codec- und Adapterprofil wechseln ohne Queryänderung auf v2, das ref-only Mapping bleibt vorläufig `openlibrary-book-mapping/v1`. | `src/foliotone/adapters/openlibrary/source.py`, ausschließlich Adapter-/Provider-Source-/Source-Profil-Konstanten in `src/foliotone/adapters/openlibrary/mapping.py`, `tests/unit/test_openlibrary_source.py`, bei Bedarf ausschließlich Versionsassertions in `tests/unit/test_openlibrary_mapping.py` | Fehlend/`null` ergibt `[]`; falsche Topologie macht den Search-Record malformed; höchstens 32 nichtleere NFC-Namen mit je höchstens 512 Codepoints werden exakt dedupliziert und lexikografisch sortiert; Verwerfungen setzen `truncated`; `author_key` und `author_name` werden nie positionsweise gekoppelt; direkte Work-/Edition-DTOs bleiben ref-only; kanonische v2-Bytes bleiben unter 262.144 Byte und alle `repr`-/Fehlerpfade sind wertfrei redigiert. |
| S-EB03B-05 | Referenzierte Author-Records und Contributor-Namen werden nach dem v2-Vertrag als getrennte externe Agent-Kandidaten ohne lokale Identitätsbestätigung gemappt. | `src/foliotone/adapters/openlibrary/mapping.py`, `tests/unit/test_openlibrary_mapping.py` | Author-Records liefern OLID plus getrennte `name`-/`alternate_names`-Assertions. Search-Namen liefern ungebundene Kandidaten mit `candidate_kind=AGENT`, `source_field=author_name`, `ValueState.EXTERNAL`, `confidence=null`, nichtleeren sortierten `source_record_refs` und vollständiger v2-Provenance, aber ohne lokale `EntityId`/`target_ref` und ohne Author-OLID. Exakte Vollschlüssel werden deterministisch dedupliziert; OLID, Alias, Homonym, fehlende Author-ID und widersprüchliche Namen bleiben getrennt; kein Ergebnis ist `USER_CONFIRMED`, `CANONICAL`, lokaler Alias oder automatische Resolution. |
| S-EB03B-06 | Der bounded Transport implementiert nur HTTPS-Allowlist, User-Agent, 3-/10-Sekunden-Timeouts, 524.288-Byte-Limit, Concurrency 1, einen Request pro Sekunde und die ADR-0036-Fehlermatrix. | `src/foliotone/adapters/openlibrary/transport.py`, `tests/unit/test_openlibrary_transport.py` | Fake Clock/HTTP prüfen 0 Redirects/Retrys, Oversize, Content-Type/UTF-8/JSON, jeden Statusbereich, `Retry-After` als Sekunden/Datum/Fallback/Cap und redigierte Fehler; kein Live-Netzwerk. |
| S-EB03B-07 | Descriptor, Adapter, Provider Runtime und Cache bilden den ersten Vertical Slice mit `NORMALIZED_SOURCE_DTO` und `json/openlibrary-source-dto-v2`; v1-Cacheeinträge werden nicht als v2 gelesen. | `src/foliotone/adapters/openlibrary/provider.py`, `src/foliotone/adapters/openlibrary/__init__.py`, `tests/integration/test_openlibrary_provider.py` | Fake-Transport-Aufruf, Fresh-Hit, getrennte v1-/v2-Source-Cache-Keys, 30/180-Tage-Positive-TTL, 6/24-Stunden-Negative-TTL, Failure-TTLs, `OFFLINE`-Hit/Miss, fetch-freie Mapping-Reanalyse innerhalb desselben Source-Profils und `BULK_DATASET_REQUIRED` sind deterministisch grün. |
| S-EB03B-08 | Privacy-, Failure-, Attribution- und Provenance-Matrix sowie Providerdokumentation schließen EB-03B ab. | `tests/integration/test_openlibrary_provider.py`, `tests/static/test_openlibrary_documentation_contract.py`, `docs/reference/EXTERNAL_DATA_SOURCES.md`, `docs/planning/BACKLOG.md`, `docs/planning/PROJECT_STATUS.md` | Keine Pfade, Filenames, Rohanfragen/-antworten, Archive.org-/Cover-/Availability-Daten oder Inventare in Query, Cache, Fehler und Reports; Attribution/Retention/Bulk-Grenze und alle EB-03B-Verträge sind grün. |

## EB-04: Classification Persistence und Projection

**Voraussetzung:** FG-04 ist gemergt. Classification bleibt Supporting Evidence
und darf allein keine Identitätsrelation bestätigen.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB04-01 | Migration `0018_book_classification_projection` ergänzt nur die fehlende Lineage zur bestehenden `classification_assertions`-Tabelle sowie immutable Projection-/Value-/Link-Tabellen. | genau Migration `0018`, neue `src/foliotone/persistence/classification_schema.py`, `tests/integration/test_classification_migration.py` | Upgrade von `0017`, Empty-DB-Upgrade, Foreign Keys, Unique Keys, Target-/Profilindizes und unveränderte Legacy-Assertions sind geprüft. |
| S-EB04-02 | Ein dedizierter insert-only Store schreibt Assertions und Lineage atomar; der generische Update-by-ID-Store ist ausgeschlossen. | bestehende `classification/contracts.py`, neue `persistence/classification.py`, `tests/integration/test_classification_persistence.py` | Exakte Wiederholung ist idempotent; andere Bytes unter gleicher ID/gleichem Key und injizierter Rollback scheitern; Providerwerte bleiben getrennte Zeilen. |
| S-EB04-03 | Begrenzte, sortierte Assertion Queries liefern nur eine angeforderte Entity und exakt `book-classification-assertion/v1`. | Persistenzdatei aus S-EB04-02, derselbe Integrationstest | Limit 1..500, `limit + 1`-Overflow, stabile Reihenfolge, Legacy-Ausschluss und Indexplan sind geprüft; kein `list_all()`-Fallback. |
| S-EB04-04 | Ein reiner Projection Reducer verarbeitet konfliktfreie Assertions nach ADR-0037. | neue `src/foliotone/classification/projection.py`, Paketexport, `tests/unit/test_classification_projection.py` | Golden Cases für alle sieben Facets, Priorität, Coalescing und exakte Set-Grenzen sind grün. |
| S-EB04-05 | Konflikte erzeugen `REVIEW_REQUIRED` und exakte Conflict-/Link-Rollen ohne Assertion-Verlust oder Confidence-Winner. | Projection-Modul und Unit-Tests aus S-EB04-04 | Automated Domain Conflict, bestätigte Priorität, bestätigter Widerspruch, Cardinality Overflow und das abgegrenzte Fiction/Computer-Science/Technical-Reference-Beispiel sind grün. |
| S-EB04-06 | Der Workflow persistiert immutable Projection Snapshots; gleiche Inputs sind ein No-op, neue Inputs oder Profile erzeugen neue Ableitungen. | neue `src/foliotone/workflows/classification.py`, dedizierter Store, `tests/integration/test_classification_workflow.py` | Kanonischer Input-Fingerprint, Determinismus, Compatibility, Versionswechsel und exakte Assertion-Links sind geprüft. |
| S-EB04-07 | Read-only Ausgabe und Dokumentationsstatus werden ergänzt. | `src/foliotone/cli/main.py`, Classification-Workflow, `tests/integration/test_classification_cli.py`, ein Classification-Static-Test, `BACKLOG.md`, `PROJECT_STATUS.md` | Ausgabe enthält nur feste Labels, IDs und Counts; keine Pfade/Werte/Rohdaten; statischer Identity-Negativtest, EB-04-DoD und ein PR-CI-Gate sind grün. |

## EB-07: read-only Calibre Library Reconciliation

**Voraussetzungen:** EB-05 ist abgeschlossen und FG-07 ist gemergt. Kein Paket
darf ein frei zusammensetzbares `calibredb`-Kommando oder eine schreibende
Operation anbieten.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB07-01 | Synthetische `calibredb`-Ausgaben decken Fälle A bis G, leere Bibliothek und malformed output ab. | neuer Fixture-Ordner, Fixture-README, Fixture-Test | Keine reale Calibre-Bibliothek oder private Metadaten; Fixtures sind deterministisch. |
| S-EB07-02 | Feste Command Builder erzeugen ausschließlich die in FG-07 erlaubten read-only Shapes. | neuer Calibre-Library-Adapter, Unit-Tests | Positive Allowlist und negative Tests für `add`, `remove`, Format-/Metadatenwrites, Backup/Restore und `export`. |
| S-EB07-03 | Parser für Library Records und Formate verarbeitet ausschließlich Fixture-Bytes. | Calibre-Library-Adapter, Unit-Tests | Stable ordering, leere Felder, mehrere Formate und malformed input sind geprüft. |
| S-EB07-04 | Ein ToolProvider-Descriptor registriert nur die festen Capability Shapes. | Tooling-/Adapterregistrierung, Tool-Runtime-Test | Keine Passthrough-Argumente; accepted exit codes, Timeout und Outputgrenze sind fest. |
| S-EB07-05 | Immutable Snapshot-/Ownership-DTOs modellieren Record, Format und Sidecar-Beziehungen. | neues Core- oder Workflowmodul gemäß FG-07, Unit-Tests | Multi-Format ist kein Duplicate; DTOs enthalten keine absoluten Exportpfade. |
| S-EB07-06 | Additive Persistenz speichert Snapshot-Lineage und Ownership Evidence. | genau eine Migration, festgelegte Schemadatei, neuer Store, Migration-/Store-Test | Wiederholung ist idempotent; unterschiedliche Snapshots bleiben nachvollziehbar. |
| S-EB07-07 | Reconciliation Mapper implementiert ausschließlich Fälle A bis D. | neuer Workflow, Unit- oder Integrationstest | Feste Finding-Codes; mehrere Formate eines Records erzeugen keinen Duplicate-Finding. |
| S-EB07-08 | Reconciliation Mapper ergänzt Fälle E bis G als Evidence beziehungsweise Review Candidates. | derselbe Workflow, fokussierte Tests | Keine Metadatenkorrektur und keine automatische Authority-Bestätigung. |
| S-EB07-09 | Read-only CLI/Report verbindet Snapshot und Findings und schließt die Welle ab. | `src/foliotone/cli/main.py`, Workflow/Reporter, CLI-Test, Planungsdokumente | Fake Tool only; pfadfreie Ausgabe; negative Tests beweisen das Fehlen schreibender Command Shapes. |

## EB-08: nicht ausführbarer ConsolidationPlan

**Voraussetzungen:** EB-06, EB-07 und FG-08 sind abgeschlossen. Jedes Paket
bleibt technisch nicht ausführbar und darf keine Filesystem-Mutations-API
einführen.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB08-01 | Immutable `ConsolidationPlan`-DTOs und feste Status-/Blocker-Literale werden implementiert. | `src/foliotone/consolidation/`, neue Unit-Testdatei | Ungültige Identity-/Keeper-/Candidate-Kombinationen werden abgelehnt. |
| S-EB08-02 | Kanonische Serialisierung und `content_hash` werden als reine Funktionen ergänzt. | Consolidation-Modul, Golden-Value-Tests | Gleiche Inputs und Planversion liefern gleiche Bytes und Hashes; Reihenfolgen sind stabil. |
| S-EB08-03 | Ein reiner Precondition Builder erzeugt die in FG-08 festgelegten Candidate-/Keeper-Snapshots. | Consolidation-Modul, Unit-Tests | FileObservation-, Hash-, Size-, Presence- und Generation-Fälle sind vollständig parametrisiert. |
| S-EB08-04 | Hard Blocker für geschützte Roots, fehlende Reviews sowie unbekannte Calibre-/Sidecar-/Archivbeziehungen werden implementiert. | Consolidation-Modul, Unit-Tests | Jeder Blocker verhindert einen freigegebenen Planstatus und bleibt in der Explanation sichtbar. |
| S-EB08-05 | Keep Preference wird als reine, versionierte Bewertung nach FG-08 implementiert. | Consolidation-Modul, Unit-Tests | Formatpräferenz ist konfigurierbar; Größe ist höchstens Tie-Breaker; Identity bleibt getrennt. |
| S-EB08-06 | Additive Persistenz speichert Plan, Lineage, Content Hash, Blocker und Reviews. | genau eine Migration, festgelegte Schemadatei, neuer Store, Migration-/Store-Test | Insert/read, idempotente Wiederholung und atomarer Rollback sind geprüft. |
| S-EB08-07 | Der Planner verbindet bestätigte Relation, Quality Evidence, Keep Preference und Preconditions. | Consolidation Planner, Integrationstest | Unresolved oder unreviewed Inputs erzeugen nur blockierte Pläne; keine Operation wird ausgeführt. |
| S-EB08-08 | Deterministischer, pfadfreier Reporter und read-only CLI werden ergänzt. | Reporter/Workflow, `src/foliotone/cli/main.py`, CLI-Test | Ausgabe enthält Plan-ID, Status, Counts und Blocker, aber keine absoluten Pfade oder privaten Evidence-Werte. |
| S-EB08-09 | Ein statischer Non-Execution-Test verbietet Mutations-APIs und schließt W9 ab. | neue statische Testdatei, Planungsdokumente | `unlink`, `remove`, `rename`, `replace`, `move`, mutierendes Calibre und Shell-Löschbefehle fehlen im Package; W10 bleibt blockiert. |

## Abgeschlossene Spark-Vorarbeiten für EB-A1 und EB-A2

**Status:** S-EBA-01 bis S-EBA-07 sind auf `main` abgeschlossen. Die Pakete
implementieren keine reale Toolausführung, Extraktion, Persistenzmigration,
sichere Secret-Übergabe, keinen Online-Passwortprovider und keine
Archive-aware Deduplizierung. Die Literale, Bounds und Profile aus ADR-0038
bleiben unverändert maßgeblich.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EBA-01 | Kleine synthetische Header-/Suffix-Fixtures bilden die ADR-0038-Allowlist einschließlich Publication Container, Generic Archives, TAR-Filter und Volumeformen ab. | neuer Archive-Fixture-Ordner und Fixture-Test | EPUB/CBZ/CBR werden nicht allein wegen ZIP-/RAR-Signatur als generische Archive klassifiziert; Fixtures enthalten keine realen Archive oder Secrets. |
| S-EBA-02 | `archive-signature-observer/v1` erzeugt nur Signature-/Suffix-Evidence und die feste Containerklasse, ohne Dateien umzubenennen. | neues Archive-Modul, Unit-Tests | Alle Signaturen, ZIP-mit-RAR-Signatur, komprimierter Stream ohne bestätigten TAR und unbekannte Signatur besitzen feste Ergebnisse; keine Mutation oder Toolausführung. |
| S-EBA-03 | `archive-sidecar-classifier/v1` erkennt ausschließlich die in ADR-0038 erlaubten NFO/TXT/DIZ/INFO/URL/HTML/SFV/README/PASSWORD-Klassen im direkten Verzeichnis. | Archive-Modul, Unit-Tests | Extensionless Basenames, 32-Dateien-Grenze und negative Rekursions-/Inhaltsausführungsfälle sind grün. |
| S-EBA-04 | `archive-secret-candidate/v1` extrahiert unter den exakten ADR-0038-Byte-/Zeilen-/Kandidatenlimits ausschließlich ephemere lokale Kandidaten. | neues Secret-Candidate-Modul, Unit-Tests | Decoder-Allowlist, Deduplizierung, Ranking, 64 Kandidaten/16 Versuche und negative Brute-Force-, Kombinations-, Filename- und Netzwerkfälle sind geprüft. |
| S-EBA-05 | `SecretHandle`-/Versuchsmetadaten setzen die ADR-0038-Redaction- und Persistenzgrenze mechanisch um. | Secret-Contract-Modul, Unit- und statische Tests | Plaintext, Länge, Prefix und Hash erscheinen weder in `repr`/`str`, Exception, LogRecord, DTO, Cache Key noch persistierbarem Payload. |
| S-EBA-06 | Reine `archive-safety-policy/v1`-Budget- und Member-Path-Validatoren lehnen sämtliche ADR-0038-Grenzverletzungen ab. | Archive-Policy-Modul, Unit-Tests | Exakte Bounds sowie adversarial Windows-/POSIX-Pfade, NFC-/Casefold-Kollision, Symlink, Reparse Point, Hardlink, Device, nested Archive und Byte-/Ratio-Overflow sind parametrisiert; keine Toolausführung. |
| S-EBA-07 | Eine Fake-Tool-Integration modelliert `archive-listing/v1`, feste Statuswerte und immutable `ArchiveMemberObservation`, ohne einen echten Extraktionsprozess zu starten. | Archive-Workflow, synthetische Integrationstests | Member ist kein `FileRecord`; Listing-Reuse und `archive-member-reuse/v1` enthalten alle ADR-0038-Versionen, `SECURE_CHANNEL_UNAVAILABLE` verhindert Secret-Übergabe und Source bleibt unverändert. |

FG-A-RUNTIME ist nach erfolgreicher Prüfung dieser Vorarbeiten durch ADR-0039
akzeptiert. Die reale Toolanbindung beginnt mit den nachstehenden Paketen. Eine
sichere Secret-Übergabe bleibt davon getrennt bis FG-A-SECRET blockiert.

## Folgepakete für FG-A-RUNTIME

ADR-0039 trennt die freigegebene unverschlüsselte Runtime von der weiterhin
blockierten Passwortverarbeitung. Die nachstehenden Pakete dürfen keine
Source-Media-Mutation, Raw-Ausgabe-Persistenz, Online-Passwortrecherche oder
W10-Funktion einführen.

| Paket | Ergebnis und erlaubter Dateibereich | Gezielter Nachweis | Routing und Stopbedingung |
|---|---|---|---|
| S-EBAR-01 | Archive-Execution-DTOs trennen Listing-, Integrity- und Extraction-Provenance. Erlaubt: `src/foliotone/archive/workflow.py`, `src/foliotone/archive/__init__.py`, `tests/unit/test_archive_workflow.py`. | Exakte Execution-ID-Sum-Types, Statusmatrix, Reuse-v1-Characterization und pfadfreie Repräsentation. | Spark `high`; 5.4 Mini, danach Terra als Fallback. Stop bei zusätzlicher Domain- oder Persistenzentscheidung. |
| S-EBAR-02 | Ein reiner bounded `archive-7zip-slt-parser/v1` verarbeitet synthetische Chunkstreams exakt nach ADR-0039. Erlaubt: neue Datei `src/foliotone/archive/sevenzip_slt.py`, `src/foliotone/archive/__init__.py`, neue fokussierte Unit-Testdatei. | Exakte Header-/Member-Allowlist, Chunk-/UTF-8-/Record-Grammatik, 8-MiB- und konkrete Zeilen-/Feld-/Memberbounds, ausschließlich ephemerer redigierter Header-Kommentar, unbekannte Felder fail-closed und keinerlei Raw-Artefakt, Preview, Sidecar-Umetikettierung oder Pfadleck. | Spark `high`; 5.4 Mini, danach Terra als Fallback. Stop bei einer Abweichung des fest gepinnten `7zzs` 26.02 von der akzeptierten v1-Grammatik oder bei neuer Encoding-, Redaktions- oder Feldsemantik. |
| FG-A-IMAGE | Durch ADR-0040 abgeschlossenes Dokumentationsgate für den Supply-Chain-Vertrag von `archive-linux-container-runner/v1`. | `scratch`-Base ohne pullbaren Base-Digest, feste offizielle Upstream-/Lizenzhashes, fehlender Upstream-Signaturnachweis, projekt-eigenes GHCR-Image, UID/GID `65532:65532`, gepinntes Buildx-/BuildKit-Profil, zweistufiger Plattform-Manifest-Digest-Lock, nachträgliche SBOM/Provenance, öffentliche/source-associated anonyme Registryverifikation, Reproduzierbarkeit/Updates und private/öffentliche CI-Grenzen sind entschieden; die Gate-Welle führte kein Tool aus. | Sol `high`; abgeschlossen. Der akzeptierte Vertrag hebt `TOOL_UNAVAILABLE` allein noch nicht auf. |
| S-EBAR-03 | Mechanische Umsetzung von ADR-0040, getrennte Archive-`ToolCapability`-Werte und feste Command Builder. Erlaubt: `packaging/archive/7zip-26.02/**`, die unmittelbar erforderliche neue Supply-Chain-Workflowdatei unter `.github/workflows/`, `src/foliotone/archive/sevenzip.py`, `src/foliotone/core/enums.py` sowie eine fokussierte Unit- und eine Integrationstestdatei. | Upstream- und Lizenzhashes, der unveränderte statische Linux-x86-64-ELF-Tar-Member `7zzs`, feste Imageinhalte, UID/GID und `SOURCE_DATE_EPOCH` werden geprüft. Das exakt gepinnte Buildx-v0.36.1-/BuildKit-v0.32.2-Profil erzeugt zweimal ein einzelnes `linux/amd64`-OCI-Layout ohne Inline-Attestations; verglichen und in `archive-image-lock/v1` fixiert wird der Plattform-Manifest-Digest. Der finale Gatebuild reproduziert ihn. Erst danach werden SBOM/Provenance angehängt. Geschützter Owner-Setup, öffentliches und source-associated GHCR-Package sowie anonymer Manifest-by-Digest-Abruf sind verpflichtend. Golden argv für `i`, `l`, `t`, `x`; `-p`, freie Optionen, Wildcards, Listfiles, Pull und mutierende Shapes werden abgewiesen. | Spark `high`; 5.4 Mini, danach Terra als Fallback. Stop bei Builder-, Digest-, ELF-, Lizenz-, Reproduzierbarkeits-, Public-/Source-Association-, anonymer Verifikations-, Publish-/Attestations- oder Command-Shape-Abweichung; bis zur vollständigen Post-Merge-Verifikation bleibt `TOOL_UNAVAILABLE`. |
| FG-A-RUNTIME-AVAILABILITY | Durch [ADR-0041](../decisions/ADR-0041-offline-archive-runtime-availability.md) abgeschlossenes Dokumentationsgate zwischen S-EBAR-03 und EBAR-04. | Reviewte FolioTone Source als Release-Authority, geschlossener Acceptance-Record, exakte Custom-SLSA-/SPDX-/Workflow-Claims, kontrolliertes Provisioning, lokaler monotoner State, 90-Tage-Offline-Fenster, Rotation/Revocation sowie vollständige lokale OCI-/Docker-Revalidierung sind festgelegt. Public/Source-Association sind Provisioning-/Refresh-Gates; ein ungepinntes `gh` ist keine Runtime-Authority. | Sol `high`; abgeschlossen. Ein eigenständiger kryptografischer Runtime-Verifier benötigt ein neues Gate. |
| S-EBAR-03A | Implementiert ADR-0041 vor jedem Runnercode. Erlaubt sind ausschließlich `packaging/archive/7zip-26.02/archive-runtime-release.json`, `packaging/archive/7zip-26.02/archive-runtime-revocations.json`, die drei Dateien `archive-runtime-evidence/{custom-slsa.jsonl,spdx.jsonl,trusted_root.jsonl}`, `packaging/archive/7zip-26.02/supply_chain_evidence.py`, `.github/workflows/archive-image.yml`, `src/foliotone/archive/sevenzip.py`, `tests/unit/test_archive_sevenzip.py` und `tests/integration/test_archive_image_packaging.py`. | Tatsächlich beobachtete Release-, Commit-, Invocation-, Bundle- und Trust-Root-Digests schließen den Record. Erstprovisionierung und atomarer Refresh erzeugen den privaten lokalen State. Jeder Per-Run-Test bleibt netzwerkfrei und verlangt Record, Evidence, Revocation, Offline-Fenster, vollständiges lokales OCI-Layout und passendes Docker-Inspect. Missing/corrupt State, Generation-/Clock-Rollback, Ablauf, Denylist und jede Identity-Abweichung bleiben `TOOL_UNAVAILABLE`; `BOOTSTRAP_LOCKED` plus Inspect genügt nicht. | Sol `high`; Fallback 5.5 nur ohne neue Trust-Root-/Signaturentscheidung. Kein Spark-/Terra-/Luna-Routing. Stop bei benötigter Runtime-Signaturprüfung, ungepinnter Verifier-Supply-Chain oder nicht beobachtbarer Acceptance-Evidence. |
| EBAR-04 | Docker-Backend `archive-linux-container-runner/v1`. Erlaubt: neue Dateien `src/foliotone/archive/process_runner.py`, `src/foliotone/archive/container_sandbox.py`, eine Unit- und eine Integrationstestdatei. | Exakt validierte Volumegruppe wird nach opaque privatem Temp-Staging kopiert und byte-/vollhashverifiziert; niemals ScanRoot-Mount. No-follow-Preflight und Bind-Projektion beweisen Link-/Junction-/Reparse-Freiheit, Input-Owner `65532:65532` mit Verzeichnissen `0500`/Dateien `0400` und einen neuen leeren Output-Root `65532:65532`/`0700`; zusätzliche ACL-Rechte oder nicht beweisbare Semantik schließen das Backend. Input read-only und Output read-write sind die einzigen Mounts; non-root, `network=none`, read-only Root-FS, Capabilities drop-all, no-new-privileges, Default-oder-strengeres Seccomp, keine Devices, feste PID-/RAM-/CPU-Limits, minimales Environment sowie vollständiger Kill/Remove/Cleanup. Native Windows bleibt bis `FG-A-WINDOWS-SANDBOX` `TOOL_UNAVAILABLE`. | Sol `high`; 5.5 nur ohne offene Secret-/Sandboxfrage. Stop bei nicht belegbarer Source-, Ownership-/Modus-, Link-/Reparse-, Netzwerk-, Filesystem-, Supply-Chain- oder Cleanup-Isolation. |
| S-EBAR-02A | Additiver Member-only-Parser `archive-7zip-slt-parser/v2` für den realen festen `-ba -slt`-Stream. Erlaubt: `src/foliotone/archive/sevenzip_slt.py` und die bestehende zugehörige Unit-Testdatei. | Null/ein/mehrere Member, beliebige Chunkgrenzen, Header-/Banner-Ablehnung, vollständige v1-Regression und unveränderte Privacy-/Locator-/Budgetgrenzen nach ADR-0043. | 5.4 Mini; bei Parser-/UTF-8-Grenzproblem Terra `medium`. Stop bei neuer Grammatik- oder Privacyentscheidung. |
| S-EBAR-02B | Minimaler hash- und lizenzgebundener Format-Fixturekorpus plus geschütztes Messmanifest für den exakten Linux-Image-Digest nach ADR-0044. Erlaubt: `tests/fixtures/archive/7zip-26.02/v1/**`, eine fokussierte Integrationstestdatei, ein kleiner rein lokaler Messhelper unter `packaging/archive/7zip-26.02/` und die bestehende Archive-Image-Workflowdatei. | ZIP, RAR4, RAR5, 7z, TAR, gzip-, bzip2-, xz- und zstd-TAR werden ohne Rawoutput/Locatorwerte vermessen; RAR-Quelle/Lizenz/Hashes, Generatorprofile, Image-Digest und ein nicht überspringbarer Linux-Gate-Lauf sind geschlossen. | Terra `medium`; für Lizenz-, Format- oder Privacyabweichung Sol `high`. Stop bei fehlender Redistribution, Rawoutputbedarf oder nicht deterministischer Feldprojektion. |
| S-EBAR-02B2 | Additives `archive-7zip-format-measurement/v2`. Erlaubt: `tests/fixtures/archive/7zip-26.02/v2/**`, der bestehende Messhelper, seine fokussierten Tests und die bestehende Archive-Image-Workflowdatei. Kein Produktionscode. | Jede ZIP/RAR4/RAR5/7z/TAR-Zelle für Plaintext, Directory, all-encrypted, mixed, encrypted-directory sowie positive Symbolic-/Hard-/Copy-Link-Fälle erhält `MEASURED`, source-gepinntes `FORMAT_UNSUPPORTED` oder begründetes `EVIDENCE_UNAVAILABLE`; kein Skip. `Commented`, `Split Before`, `Split After` werden als `VT_BOOL` mit ausschließlich `+`/`-` klassifiziert. V1 bleibt diagnostisch unverändert. | Terra `medium`; bei Lizenz-, Encryption-, Link-, Format- oder Privacyfrage Sol `high`. Stop bei nicht belegbarer Redistribution, sicherer Erzeugbarkeit, Primärevidence oder Rawwertbedarf. |
| FG-A-STORAGE-FAMILY | Durch ADR-0046 abgeschlossenes Docs-only-Gate für orthogonale Publication Kind `NONE/EPUB/CBZ/CBR`, Storage Family `ZIP/RAR4/RAR5/SEVEN_Z/TAR/UNKNOWN` und äußere Kompression `NONE/GZIP/BZIP2/XZ/ZSTD`. | ZIP-basierte EPUB/CBZ und RAR4-/RAR5-basierte CBR behalten alle Evidence-Achsen; Wrapper behalten als Source-Beobachtung Storage `UNKNOWN`, auch wenn ADR-0051 den inneren TAR-Strom privat bestätigt. Profil v1 bleibt legacy-read-only; v2 und Compatibility `archive-publication-storage-compatibility/v1` sind für neue Produktionspfade verpflichtend. | Sol `high`; abgeschlossen. |
| FG-A-FORMAT-LOCK | Durch ADR-0047 abgeschlossenes Frontier-Gate nach S-EBAR-02B2 und FG-A-STORAGE-FAMILY. | `archive-7zip-format-lock/v1` bindet maschinenlesbar alle 40 Capability-Zellen und 21 geordneten Recordprojektionen, hat einen getrennten SHA-256 und wird im geschützten Workflow strikt verify-only geprüft. | Sol `high`; abgeschlossen. |
| S-EBAR-02C | Additiver Produktionsparser erst nach beiden Gates. Erlaubt: `src/foliotone/archive/signatures.py`, `src/foliotone/archive/__init__.py`, `src/foliotone/archive/sevenzip_slt.py`, `src/foliotone/archive/sevenzip.py` und bestehende fokussierte Signatur-/Parser-/Command-Tests. Kein Provider-, Runner-, Persistence-, Wrapper-, Extraction- oder Secret-Code. | Orthogonales Publication-/Storage-/Outer-Compression-Routing und exakt final gelockte Profile. Wrapper werden vor Verbrauch des ersten Parserchunks abgewiesen; ein No-Provider-Call-Test gehört nicht hierher. Unveränderte Chunk-/Privacy-/v1-/v2-Regression. | Terra `medium`; bei Link-, Stream-, Routing- oder Privacysemantik Sol `high`. Stop bei Manifestabweichung, zusätzlicher Feldsemantik oder Wrapperbedarf. |
| EBAR-05 | Reales formatgelocktes Listing und Integrity nach S-EBAR-02C. Erlaubt: neue Datei `src/foliotone/archive/provider.py`, `src/foliotone/archive/workflow.py`, eine Unit- und eine Integrationstestdatei. | Nur final als `MEASURED` akzeptierte Storage-/Fallkombinationen laufen. Gemessene Datenverschlüsselung wird zu `DATA_ENCRYPTED` beziehungsweise `MIXED` reduziert, startet aber weder Integrity noch Passwortübergabe. Unsupported/unavailable Kombinationen starten keinen Lauf. No-Provider-Call für alle vier Wrapper, konservative Status-/Exitcodematrix, getrennte Execution-Provenance, Raw-Discard und unveränderte Sourcebytes. | Terra `medium`, bei schichtübergreifender Diagnose `high`; Fallback 5.4. Stop bei nicht final gelockter Verschlüsselungssemantik, Header-Verschlüsselung ohne strukturierte Evidence, benötigter Passwort-/Secretübergabe, Manifestabweichung oder ungeklärter Toolfehlermatrix. |
| S-EBAR-05A | Underscore-interner Extraction-Handoff aus exakt demselben EBAR-05-Lauf. Erlaubt ausschließlich: `src/foliotone/archive/provider.py`, `tests/unit/test_ebar05_archive_provider.py`, `tests/integration/test_ebar05_archive_provider_integration.py`. | Locator, CRC, Ordinal, Kind, Größen und Memberidentität bleiben `repr`-/`str`-/Exception-/DTO-/Persistenz-frei. Der private Envelope referenziert exakt dasselbe öffentliche Outcome und dieselben Executions; Signature-, Storage-, Case- und Lockidentity sind zusätzliche private Bindungen und erweitern die öffentliche API nicht. Kein Handoff bei Cancellation, Wrapper, Encryption, Policy- oder Integrityfehler; Listing/Integrity laufen nie doppelt. | 5.4 Mini `medium`; bei Privacy-/Lineageabweichung Terra `high`. Stop bei öffentlichem Export, Persistenzbedarf oder neuer Parsersemantik. |
| S-EBAR-06A | Reiner underscore-interner Extraction-Consumer vor jeder Runner-Integration. Erlaubt ausschließlich: `src/foliotone/archive/extraction.py`, `tests/unit/test_archive_extraction.py`. | Konsumiert den S-EBAR-05A-Handoff und eine synthetische borrowed Workspace-Sicht; validiert listed/extracted, Ordinal, Typ, Größen, CRC, Hash, Kollisionen und Budgetprojektion deterministisch. Kein Tool-, Prozess-, Docker-, echter Filesystem- oder Runnerzugriff; kein öffentlicher Export. | Terra `high`; bei Privacy-/TOCTOU-/Budgetsemantik Sol `high`. Stop bei öffentlichem DTO, I/O-Bedarf oder fehlender exakter Handoff-Bindung. |
| FG-A-EXTRACTION-QUOTA | Durch ADR-0049 abgeschlossenes Docs-only-Frontier-Gate für eine atomar begrenzte Workspace-Capability vor S-EBAR-04Q. | Definiert ausschließlich dateisystemneutrale Byte-/Objekt-/Reserve-/Parallelitäts-, Lease-, Return- und Quarantäneeigenschaften. Ein konkretes Dateisystem, Volume- oder Quota-Backend braucht ein eigenes Plattformadapter-Gate. FolioTone erhält keine Mount-/Device-/Root-Authority. | Sol `high`; abgeschlossen. |
| S-EBAR-04Q | Mechanische Implementierung von `archive-bounded-workspace-capability/v1`. Erlaubt ausschließlich `src/foliotone/archive/quota_slots.py`, `tests/unit/test_archive_quota_slots.py` sowie die unmittelbar betroffenen Safety-/Tool-/Backlog-/Statusabschnitte. | Liefert nur den neutralen Provider-, Lease-, Capability-, Empty-Revalidation-, Return- und Quarantänevertrag mit begrenzten Fakes. Kein Container-, Extraction-, Dateisystem-, Mount-, Formatierungs- oder automatischer Recovery-Lifecycle. Reale Backends folgen als separate Plattformpakete mit nicht überspringbarem Konformitätsgate. | Terra `high`; Sol nur bei neuer Authorityentscheidung. Stop bei Kernabhängigkeit von einem Dateisystem, nicht atomarem Cap, überlebender Capability oder automatischer Wiederverwendung unsicherer Leases. |
| FG-A-WORKSPACE-BACKEND | Durch ADR-0050 abgeschlossenes negatives Docs-only-Frontier-Gate. | Bind-Mount, Docker-Layer, `tmpfs` und nicht konkret live attestierte Linux-Quota belegen Byte-, Objekt-, Reserve- und Consumer-Lifecycle nicht gemeinsam. Keine Backend-Allowlist, keine Dateisystem- oder FIEMAP-Kernvoraussetzung. Revalidation erst mit administrativ vorprovisioniertem Kandidaten und echtem Linux-/Docker-Conformancehost. | 5.6 Sol `high`; abgeschlossen und fail-closed. 5.5 nur ohne neue Authority und bei unverändertem Ergebnis; kein Spark/Luna/Terra. |
| S-EBAR-04A | Privater Runner-owned Workspace-Consumer-Lifecycle erst nach akzeptiertem realem Backend-Konformitätsvertrag; derzeit `TOOL_UNAVAILABLE`. Erlaubt ausschließlich: `src/foliotone/archive/container_sandbox.py`, `tests/unit/test_archive_container_sandbox.py`, `tests/integration/test_archive_container_sandbox_runtime.py`. Die öffentliche `run`-Grenze weist Extraction ab. | Konsumiert nur die unprivilegierte Quota-Slot-Capability; per-run Attestation, zusätzlicher Polling-Frühabbruch und `RLIMIT_FSIZE`, vollständiger Kill/Remove, bewiesene Container-Abwesenheit vor genau einem synchronen S-EBAR-06A-Consumer, Cleanup, leerer Slotbeweis, Return/Quarantäne und Evidence-Freigabe erst danach. Ein realer Linux-Test ist verpflichtend. | Sol `high`; Fallback 5.5 nur ohne neue Sandboxentscheidung. Stop bei fehlendem akzeptierten Backend, frei injizierbarem Callback/Pfad, überlebender Capability, nicht unterscheidbarem Abbruchgrund oder nicht beweisbarer Cap-/Container-/Cleanup-/Return-Reihenfolge. |
| EBAR-06 | Direkte private Extraction-Sandbox, Workspace-Revalidierung und Member-Hashing nach S-EBAR-05A, S-EBAR-06A, FG-A-EXTRACTION-QUOTA, S-EBAR-04Q und S-EBAR-04A. Erlaubt: `src/foliotone/archive/extraction.py`, `src/foliotone/archive/safety_policy.py`, eine Unit- und eine Integrationstestdatei. | Ausschließlich direkte ZIP-/RAR4-/RAR5-/7z-/TAR-Handoffs mit `MEASURED`, `LISTED`, Encryption `NONE`, Integrity `PASSED` und Safety `ACCEPTED`. Traversal, Links/Reparse Points/Devices, Kollisionen, Bombenlimits, Prozessabbruch, listed/extracted-Gleichheit, Größen/CRC, TOCTOU, Cleanup und keine Partial-Evidence. Alle Wrapper starten keinen Lauf. | Sol `high`; kein Spark-/Terra-Fallback. Stop bei unvollständiger Prozess-, Filesystem-, harter Budget- oder Cleanup-Isolation. |
| FG-A-WRAPPER-PIPELINE | Durch ADR-0051 abgeschlossenes Frontier-Gate für gzip-/bzip2-/xz-/zstd-Wrapper; kein Bestandteil von EBAR-06. | Zwei getrennte read-only Composite-Läufe streamen feste äußere Dekompression über einen bounded TAR-Rahmenprüfer an feste innere TAR-Listing-/Integrity-Container. Source bleibt `OUTER_COMPRESSION_ONLY`, Storage `UNKNOWN`, `max_nested_depth=0`; kein Extraction-Handoff. | Sol `high`; abgeschlossen. |
| S-EBAR-W01 | Reiner TAR-Rahmenprüfer und feste Wrapper-/stdin-Commands. Erlaubt: neue `src/foliotone/archive/wrapper_stream.py`, `src/foliotone/archive/sevenzip.py`, eine fokussierte Unit-Testdatei sowie unmittelbar betroffene Statuszeilen. | 512-Byte-State-Machine, Headerchecksumme, gebundene Zahlengrammatik, Größen/Member/Totalgrenzen, Payload/Padding, mindestens zwei Nullblöcke, nullhaltiger Nachlauf, SHA-256/Bytecount. Keine Prozesse, Provider, Rawpersistenz oder Extraction. | Spark `high`; umgesetzt. 5.4 Mini als Fallback. Bei TAR-Grammatik-/Privacyabweichung Terra `high`. |
| S-EBAR-W02 | Bounded Duplex-Broker im bestehenden privaten Runner. Erlaubt: `src/foliotone/archive/process_runner.py`, `src/foliotone/archive/container_sandbox.py` und die beiden fokussierten Runner-Testdateien. | Zwei no-shell Container, feste Backpressure, stdin-Attestation, `--log-driver=none`, Kill/Remove/Absence/Quieszenz bei jedem Fehler; echte provisionierte Linux-Integration ohne Pull. Keine Provider- oder Membersemantik. | Sol `high`; kein Spark-Fallback. Stop bei unbounded Queue, überlebendem Prozess/Container oder neuer Runtimeauthority. |
| S-EBAR-W03 | Read-only Provider-Integration für die vier Wrapper. Erlaubt: `src/foliotone/archive/provider.py` sowie die bestehenden EBAR-05 Unit-/Integrationstests. | Zwei Composite-Executions, identische innere Länge/SHA-256, gelocktes TAR-Listing/Integrity, konservative Statusmatrix und vier gebundene Fixtures. Kein Extraction-Handoff, keine Persistenz, kein Source-Rewrite. | Terra `high`; bei Lineage-/Privacy-/Statuskonflikt Sol `high`. |
| S-EBAR-W04 | Wrapper-Abschluss in Status-, Roadmap-, Safety- und Tooldokumentation. | Fokussierte direkte Archive-Regression, Wrapper-Matrix, Links, Privacy-/Rawstream-Suche und Statuskonsistenz. Keine neue Runtimeentscheidung. | Luna `medium`; bei semantischer Abweichung Terra `medium`. |
| FG-A-SECRET | Separates dokumentationsbasiertes Gate für Helper, Kanal und tatsächlich unterstützte verschlüsselte Formate. Erlaubt: neue ADR sowie die unmittelbar betroffenen Safety-/Tool-/Planungsdokumente. | Primärquellen, Leakage-Matrix, explizite Handle-Vererbung, Speicherbereinigung und adversarial Fixtureplan; keine Toolausführung im Gate. | Sol `xhigh`; kein niedrigeres Fallback. Ohne technischen Nachweis bleibt `SECURE_CHANNEL_UNAVAILABLE`. |
| FG-A-PERSISTENCE | Separates Gate benennt immutable Archive-/Member-/Execution-Lineage, Reuse, Tabellen, Indizes, Lease/Fencing und Migration nach dem dann aktuellen Head. Erlaubt: neue ADR und unmittelbar betroffene Planungs-/Persistenzarchitektur-Dokumente. | Schema-, Privacy-, Restart-, Stale-Writer- und Migration-in-place-Widerspruchsprüfung; kein Code und keine Migration im Gate. | Sol `high`; kein Spark-Fallback. Stop bei offener Writer-, Reuse- oder Privacy-Semantik. |
| S-EBAR-07 | Die durch FG-A-PERSISTENCE exakt benannte additive Migration und der insert-only Archive-Store werden mechanisch umgesetzt. Der Gate-PR legt den exakten Dateibereich fest. | Upgrade vom vorherigen Head, Head-Eindeutigkeit, Insert/read, idempotente Wiederholung, Reuse, atomarer Rollback und keine Raw-/Pfad-/Secretspalten. | Spark `high`; 5.4 Mini, danach Terra als Fallback. Stop bei zusätzlicher Schema- oder Reuse-Entscheidung. |
| EBAR-08 | Restartbare Collection-Orchestrierung ergänzt Lease/Fencing, Heartbeat und pfadfreie Reports. Der Dateibereich wird durch FG-A-PERSISTENCE festgelegt. | Deterministische Konkurrenz-, stale-Takeover-, Resume-, Keeper-, bounded Batch- und echte SQLite-read-only Reporttests. | Sol `high`; kein Spark-Fallback. Stop bei ungeklärter Writer- oder stale-Fencing-Semantik. |
| EBAR-09 | Status, Backlog und EB-A2-/EB-A3-Übergang werden nach Gesamtprüfung synchronisiert. Erlaubt: `docs/planning/PROJECT_STATUS.md`, `docs/planning/BACKLOG.md`, Archive-Roadmap und tatsächlich betroffene Referenz. | Link-, Status-, Privacy- und W10-Widerspruchssuche sowie gezielte Archive-Regressionen. | Luna `medium`; semantische Integration Terra `medium`. Kein EB-A3-Start ohne eigenes Gate. |

S-EBAR-01 bis S-EBAR-03A, EBAR-04, S-EBAR-02A bis S-EBAR-02C und EBAR-05
sind abgeschlossen. FG-A-IMAGE, FG-A-RUNTIME-AVAILABILITY,
FG-A-STORAGE-FAMILY und FG-A-FORMAT-LOCK sind abgeschlossen.
FG-A-EXTRACTION-LIFECYCLE ist durch ADR-0048 entschieden; S-EBAR-05A und
S-EBAR-06A sind abgeschlossen. FG-A-EXTRACTION-QUOTA ist durch ADR-0049
entschieden und S-EBAR-04Q abgeschlossen. FG-A-WORKSPACE-BACKEND ist durch
ADR-0050 negativ entschieden; die Allowlist bleibt leer. S-EBAR-04A und
EBAR-06 bleiben `TOOL_UNAVAILABLE`. Ein Revalidation-Gate darf erst mit einem
konkreten administrativ vorprovisionierten Backend und einem echten Linux-/
Docker-Conformancehost beginnen und autorisiert selbst noch keinen Code.
FG-A-WRAPPER-PIPELINE ist durch ADR-0051 entschieden. S-EBAR-W01 bis
S-EBAR-W04 können unabhängig von der blockierten Extractionstrecke folgen und
autorisieren nur read-only Listing und Integrity. Anschließend legt
FG-A-PERSISTENCE den exakten Schema- und Writer-Vertrag fest; erst dann darf
S-EBAR-07 beginnen. FG-A-SECRET bleibt separat blockiert.

## Abnahme eines Spark-Pakets

Ein Paket ist nur abgeschlossen, wenn:

1. alle Voraussetzungen und Vorgänger auf `origin/main` vorhanden sind;
2. der Diff ausschließlich den erlaubten Dateibereich enthält;
3. neue öffentliche Literale exakt dem zugehörigen Frontier-Gate entsprechen;
4. alle genannten fokussierten Tests sowie relevante bestehende Regressionstests
   grün sind;
5. `git diff --check`, Ruff und Mypy für den betroffenen Scope grün sind;
6. der eine vollständige PR-CI-Gate grün ist;
7. der Merge-Commit auf `origin/main` und der Post-Merge-Vertrag erfolgreich
   verifiziert wurden;
8. keine privaten Pfade, Daten, Secrets, Runtime-Berichte oder Cache-Inhalte in
   Git gelangt sind;
9. Statusdokumente nur dann fortgeschrieben wurden, wenn die behauptete
   Funktion tatsächlich vollständig implementiert ist.

## Wiederverwendbarer Ausführungsauftrag

Der folgende Auftrag wird immer nur für genau eine Paket-ID verwendet. Die
Platzhalter werden vor Start durch den koordinierenden Task ersetzt.

```text
Arbeite im FolioTone-Repository unter C:\rep und implementiere ausschließlich
das Paket <PAKET-ID> aus
docs/planning/EBOOK_SPARK_WORK_PACKAGES.md.

Dieser Task ist für 5.3 Codex Spark mit Thinking `high` vorgesehen. Wenn die
Aufgabe trotz des bereits festgelegten Vertrags mehrere Schichten integriert
oder einen schwer reproduzierbaren Fehler betrifft, darf der koordinierende
Task gemäß `MODEL_ROUTING_POLICY.md` auf 5.6 Terra mit `high` wechseln.
Eine fehlende Architektur- oder Sicherheitsentscheidung ist kein
Eskalationsgrund, sondern eine Stoppbedingung für dieses Paket.

Ausgangsbasis ist origin/main bei <COMMIT>. Lies AGENTS.md,
docs/planning/MODEL_ROUTING_POLICY.md,
docs/planning/EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md und den vollständigen
Paketeintrag. Prüfe zuerst Voraussetzungen, Vorgänger, Dirty State und den
erlaubten Dateibereich. Verwende bei vorhandenen Benutzeränderungen einen
sauberen Worktree unter C:\rep\worktrees\FolioTone.

Der Vertrag aus <FRONTIER-GATE-PR-ODER-COMMIT> ist verbindlich. Triff keine
zusätzliche Architektur-, Schema-, Sicherheits- oder Produktentscheidung.
Ändere nur die im Paket erlaubten Dateien und halte die allgemeine Dateigrenze
des Spark-Katalogs ein. Verwende ausschließlich synthetische Fixtures. Keine
Live-Netzwerktests, privaten Sammlungsdaten, Secrets oder Source-Media-Writes.
W10 bleibt gesperrt.

Führe die im Paket genannten fokussierten Tests sowie Ruff, Mypy und
git diff --check für den betroffenen Scope aus. Erzeuge genau einen Pull
Request mit genau einem vollständigen CI-Gate. Merge nur bei grünem Gate und
konsistentem Diff nach origin/main; prüfe anschließend Merge-Commit und
Post-Merge-Vertrag.

Stoppe ohne Implementierung und dokumentiere den konkreten Widerspruch, falls
eine Voraussetzung fehlt, der Code vom Gate-Vertrag abweicht, eine weitere
Entscheidung erforderlich wäre, die Dateigrenze überschritten werden müsste
oder ein Test nur durch Lockerung einer Sicherheitsinvariante grün würde.
```

## Reihenfolge

Innerhalb einer Gruppe werden die Pakete in aufsteigender Nummer ausgeführt.
Zwischen Gruppen gilt weiterhin die Reihenfolge des Endgame-Plans:

```text
FG-00 → S-EB00-01..04
EB-01
FG-03A → S-EB03A-01..09
FG-03B → S-EB03B-01..08
FG-04 → S-EB04-01..07
EB-02 → EB-05 → EB-06
FG-07 → S-EB07-01..09
FG-08 → S-EB08-01..09

parallel nach EB-01:
FG-A → S-EBA-01..07 → FG-A-RUNTIME → S-EBAR-01..EBAR-05
    → FG-A-EXTRACTION-LIFECYCLE → S-EBAR-05A → S-EBAR-06A
    → FG-A-EXTRACTION-QUOTA → S-EBAR-04Q
    → FG-A-WORKSPACE-BACKEND (fail-closed)
    → FG-A-WORKSPACE-BACKEND-REVALIDATION → Plattformpaket
    → S-EBAR-04A → EBAR-06
    → FG-A-PERSISTENCE → S-EBAR-07..EBAR-09

separat und weiterhin blockiert:
FG-A-SECRET → erst danach sichere Passwortversuche
FG-A-WRAPPER-PIPELINE → S-EBAR-W01 → S-EBAR-W02 → S-EBAR-W03 → S-EBAR-W04
```

Unabhängige Pakete dürfen erst parallel laufen, wenn ihre Dateibereiche sich
nicht überschneiden, ihre Gates gemergt sind und kein gemeinsamer
Migrations-Head verändert wird. Zwei Schema- oder Migrationspakete laufen nie
parallel.
