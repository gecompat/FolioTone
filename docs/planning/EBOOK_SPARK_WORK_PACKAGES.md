# Spark-Arbeitspakete für die E-Book-Endgerade

**Status:** Geplant

**Stand:** 2026-08-17

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
| FG-03A | Cache-Payload-Regel je Provider, TTL-/Freshness-Regeln, Cache-Key-Kanonisierung und Transaktionsgrenze. |
| FG-03B | Erneut geprüfte Provider-Primärdokumentation, Lizenz-/Cache-Regeln, feste Endpoints, Rate Limits und DTO-Mapping. |
| FG-04 | Classification-Taxonomie, Projection-Priorität, Konfliktstatus und Profilversion. |
| FG-07 | Durch [ADR-0033](../decisions/ADR-0033-read-only-calibredb-library-reconciliation.md) akzeptiert: vollständige read-only `calibredb`-Command-Shapes, Toolmanifest, Snapshot-Lineage sowie Ownership-/Sidecar-Vertrag. |
| FG-08 | Finale `ConsolidationPlan`-DTOs, Blocker, Precondition-Semantik, kanonische Serialisierung und Persistenzschema. |
| FG-A | Archivtoolentscheidung, Format-Allowlist, sichere Secret-Übergabe und Extraktions-/Sandbox-Grenzen. |

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
| S-EB03A-01 | Immutable Cache-DTOs und die festgelegten Result-/Freshness-Literale werden implementiert. | neue Datei unter `src/foliotone/enrichment/`, `tests/unit/test_enrichment.py` | Konstruktion, ungültige Zustände und path-free Repräsentation sind getestet. |
| S-EB03A-02 | Der kanonische Cache-Key-Builder erzeugt aus den fünf festgelegten Komponenten deterministische Bytes und einen Fingerprint. | Cache-Modul aus S-EB03A-01, neue fokussierte Unit-Testdatei | Reihenfolgeunabhängige Eingaben, Versionsänderungen und Unicode-Grenzfälle besitzen feste Golden Values. |
| S-EB03A-03 | Eine additive Migration und Schemaobjekte speichern Cache-Metadaten ohne private Pfade. | genau eine neue Alembic-Migration, `src/foliotone/persistence/w3_schema.py` oder der durch FG-03A benannte Nachfolger, ein Migrationstest | Upgrade vom vorherigen Head, Indizes, Foreign Keys und Head-Eindeutigkeit sind geprüft. |
| S-EB03A-04 | Ein Store bietet exakt die in FG-03A festgelegten Put-/Get-Operationen und atomare Ersetzung. | neue Persistenzdatei, `src/foliotone/persistence/__init__.py`, eine Integrationstestdatei | Hit, Miss, Replace und injizierter Rollback sind deterministisch getestet. |
| S-EB03A-05 | Ein reiner Freshness-Evaluator klassifiziert frisch, stale und abgelaufen mit injizierbarer Clock. | Cache-Modul, fokussierte Unit-Tests | Grenzzeitpunkte werden ohne Sleeps getestet. |
| S-EB03A-06 | `NOT_FOUND` erhält die kürzere negative TTL; Failure-, Rate-Limit- und Timeout-Ergebnisse werden nicht als `NOT_FOUND` gespeichert. | Cache-Modul und Store-Test | Ergebnismatrix und Persistenzzeilen entsprechen exakt FG-03A. |
| S-EB03A-07 | Die Provider Runtime nutzt Cache Hit, Stale Policy und Refresh, ohne Provider Mapping und Transport zu vermischen. | `src/foliotone/enrichment/providers.py`, Cache-Modul, `tests/unit/test_enrichment.py` | Fake Transport zählt Aufrufe; Hit verursacht null Fetches, Refresh genau einen Fetch. |
| S-EB03A-08 | Ein harter Offline-Test lässt jeden Socket-/HTTP-Versuch sofort fehlschlagen. | ausschließlich Provider-Runtime-Tests | `OFFLINE` funktioniert mit Cache Hit und Miss ohne Netzwerk; der Test enthält keine Live-Adresse. |
| S-EB03A-09 | Mapping-Reanalyse verwendet zulässige Cache-Bytes erneut, ohne Fetch; Status und Backlog werden aktualisiert. | Provider Runtime, ein Integrationstest, betroffene Planungsdokumente | Mapping-Versionswechsel erhöht Mapping-Aufrufe, aber nicht Transport-Aufrufe; gesamter EB-03A-DoD ist nachgewiesen. |

## EB-03B: erster realer Book Provider

**Voraussetzungen:** EB-03A ist abgeschlossen und FG-03B benennt Open Library
oder dokumentiert stattdessen einen anderen Provider. Die Paketnamen bleiben
stabil; providerbezogene Pfade werden im Gate festgelegt.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB03B-01 | Kleine, lizenzkonforme und anonymisierte Response-Fixtures decken Treffer, Nichtfund, Pagination, Sparse Data und ungültige Antwort ab. | neuer Fixture-Ordner unter `tests/fixtures/`, Fixture-README | Fixtures enthalten keine privaten Anfragen, Pfade oder ungeklärten Voll-Dumps; Strukturtest ist grün. |
| S-EB03B-02 | Ein reiner Query Builder erzeugt ausschließlich die freigegebenen Identifier-Anfragen. | neuer Adapter unter `src/foliotone/adapters/`, neue Unit-Testdatei | Open-Library-ID, ISBN, OCLC und LCCN werden exakt kodiert; Pfad-/Filename-Sentinels fehlen im Output. |
| S-EB03B-03 | Der Response Parser bildet Treffer, Nichtfund und ungültige Antworten in providerinterne DTOs ab. | Provider-Adapter, zugehörige Unit-Tests | Alle S-EB03B-01-Fixtures werden deterministisch und ohne Netzwerk verarbeitet. |
| S-EB03B-04 | Work-/Edition-Identifier und bibliografische Felder werden getrennt auf FolioTone Evidence projiziert. | Provider-Adapter, `tests/unit/test_enrichment.py` | Keine Edition wird zum Work kollabiert; alle Werte sind `ValueState.EXTERNAL` und besitzen Provenance. |
| S-EB03B-05 | Author-/Contributor-Referenzen werden als externe Kandidaten gemappt, ohne lokale Agent-Identität automatisch zu bestätigen. | Provider-Adapter und dessen Unit-Tests | Homonyme und fehlende Author-IDs bleiben Kandidaten; kein `USER_CONFIRMED`/`CANONICAL`. |
| S-EB03B-06 | Der bounded Transport Adapter implementiert feste Endpoint-, Timeout-, User-Agent- und Response-Size-Regeln aus FG-03B. | genau ein Transportmodul und Fake-Transport-Tests | Kein Live-Netzwerk; Timeout, Oversize, Rate Limit und `Retry-After` werden als festgelegte Resultate klassifiziert. |
| S-EB03B-07 | Adapter, Provider Runtime und Cache werden zu einem Vertical Slice verbunden. | Provider-Registrierung, eine Integrationstestdatei | Erster Aufruf nutzt Fake Transport, zweiter Cache, `OFFLINE` nur Cache; Mapping-Reanalyse fetch-frei. |
| S-EB03B-08 | Privacy-, Failure- und Provenance-Matrix sowie Providerdokumentation schließen die Welle ab. | Tests, Providerreferenz, `BACKLOG.md`, `PROJECT_STATUS.md` | Keine absoluten/relativen Sammlungspfade in Query, Cache oder Fehlertext; alle EB-03B-Fälle und Dokumentationsverträge sind grün. |

## EB-04: Classification Persistence und Projection

**Voraussetzung:** FG-04 ist gemergt. Classification bleibt Supporting Evidence
und darf allein keine Identitätsrelation bestätigen.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EB04-01 | Additive Migration und Schema speichern einzelne Classification Assertions mit Source, Provenance und Profilversion. | genau eine Migration, festgelegte W5-Schemadatei, Migrationstest | Upgrade, Indizes und Erhalt mehrerer widersprechender Assertions sind geprüft. |
| S-EB04-02 | Ein Store schreibt und liest Assertions, ohne andere Quellen zu überschreiben. | neue Persistenzdatei, ein Integrationstest | Mehrere Providerwerte bleiben getrennte Zeilen; atomarer Rollback ist getestet. |
| S-EB04-03 | Begrenzte, sortierte Assertion Queries liefern nur die angeforderte Entity und Profilversion. | Persistenzdatei, Integrationstest | Keine collection-weite Liste; stabile Reihenfolge und Limit-Grenzen sind geprüft. |
| S-EB04-04 | Ein reiner Projection Reducer verarbeitet konfliktfreie Assertions nach FG-04. | neues Modul unter `src/foliotone/classification/`, neue Unit-Testdatei | Golden Cases für Domain, Genre, Topics, Audience, Language und Form sind grün. |
| S-EB04-05 | Konflikte erzeugen den festgelegten Review-Status, ohne Assertion-Verlust. | Projection-Modul und Unit-Tests | Fiction/Computer-Science/Technical-Reference-Beispiel bleibt vollständig nachvollziehbar. |
| S-EB04-06 | Reprojection erzeugt aus gleichen Inputs gleiche Ausgabe; Profiländerung erzeugt eine neue Ableitung. | Classification Workflow, ein Integrationstest | Determinismus, Versionswechsel und idempotente Wiederholung sind geprüft. |
| S-EB04-07 | Read-only Ausgabe und Dokumentationsstatus werden ergänzt. | festgelegter Workflow-/CLI-Adapter, Tests, Planungsdokumente | Ausgabe enthält nur feste Labels, IDs und Counts; keine Pfade; EB-04-DoD und CI sind grün. |

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

## Begrenzte Spark-Vorarbeiten für EB-A1 und EB-A2

**Voraussetzung:** FG-A ist gemergt. Diese sieben Pakete implementieren keine
reale Extraktion, keinen Online-Passwortprovider und keine Archive-aware
Deduplizierung.

| Paket | Ergebnis | Erlaubter Dateibereich | Gezielter Nachweis |
|---|---|---|---|
| S-EBA-01 | Kleine synthetische Header-/Suffix-Fixtures bilden Publication Container und freigegebene Generic Archives ab. | neuer Archive-Fixture-Ordner und Fixture-Test | EPUB/CBZ/CBR werden nicht allein wegen ZIP-Signatur als generische Archive klassifiziert. |
| S-EBA-02 | Ein reiner Signature-/Suffix-Observer erzeugt Evidence und meldet Abweichungen, ohne Dateien umzubenennen. | neues Archive-Modul, Unit-Tests | ZIP-mit-RAR-Signatur und unbekannte Signatur besitzen feste Findings; keine Mutation. |
| S-EBA-03 | Ein Sidecar-Klassifizierer erkennt nur die in FG-A erlaubten NFO/TXT/DIZ/INFO/URL/HTML/SFV/README/PASSWORD-Klassen. | Archive-Modul, Unit-Tests | Extensionless Fälle sind begrenzt; keine Verzeichnisrekursion oder Inhaltsausführung. |
| S-EBA-04 | Ein lokaler Kandidatenparser extrahiert begrenzte Passwortkandidaten aus synthetischen Sidecars und gibt ausschließlich ephemere Werte zurück. | neues Secret-Candidate-Modul, Unit-Tests | Limits, Deduplizierung und Ranking sind geprüft; keine Brute-Force-, Kombinations- oder Persistenzfunktion. |
| S-EBA-05 | `SecretHandle`-/Versuchsmetadaten und Redaction Tests setzen den in FG-A festgelegten Vertrag mechanisch um. | Secret-Contract-Modul, Unit- und statische Tests | Plaintext erscheint weder in Repräsentation, Exception, Log-Record noch persistierbarem DTO. |
| S-EBA-06 | Reine Budget- und Member-Path-Validatoren lehnen Traversal, absolute/Device Paths, ADS, Symlink-/Reparse-Marker und Root Escape ab. | Archive-Policy-Modul, Unit-Tests | Alle Grenzwerte und adversarial Windows-/POSIX-Pfade sind parametrisiert; keine Toolausführung. |
| S-EBA-07 | Eine Fake-Tool-Integration modelliert bounded Listing und `ArchiveMemberObservation`, ohne einen echten Extraktionsprozess zu starten. | Archive-Workflow, synthetische Integrationstests | Member ist kein `FileRecord`; Provenance- und Reuse-Key enthalten die in FG-A festgelegten Versionen; Source bleibt unverändert. |

Die reale Toolanbindung, sichere Secret-Übergabe, private Testextraktion,
Prozessisolation und Archive-Member-Extraktion beginnen erst in einem separaten
Frontier-Task nach erfolgreicher Prüfung dieser Vorarbeiten.

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
FG-A → S-EBA-01..07 → Frontier-Implementierung der sicheren Extraction Runtime
```

Unabhängige Pakete dürfen erst parallel laufen, wenn ihre Dateibereiche sich
nicht überschneiden, ihre Gates gemergt sind und kein gemeinsamer
Migrations-Head verändert wird. Zwei Schema- oder Migrationspakete laufen nie
parallel.
