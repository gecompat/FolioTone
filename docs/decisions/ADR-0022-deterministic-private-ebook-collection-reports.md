# ADR-0022: Deterministische private E-Book-Collection-Berichte

- Status: Accepted
- Datum: 2026-08-15

## Kontext

`ebook-collection-analysis/v1` hält einen stabilen, fortsetzbaren Plan und
begrenzte Ergebniszähler. Für die tatsächliche Arbeit an einer großen privaten
Sammlung werden zusätzlich nachvollziehbare Summen, priorisierte Review-Items
und begrenzte Duplicate-/Varianten-Kandidaten benötigt. Ein Bericht darf dafür
weder Source Media erneut öffnen noch rohe Fingerprints, extrahierte Inhalte
oder private Laufzeitdaten nach Git übertragen.

Die bisherigen Batch-Zähler reichen nicht aus, um einen Befund auf seine
konkreten `ToolExecution`-Quellen zurückzuführen. Collection-weite
Kandidatensuche darf außerdem nicht alle Gruppen und Mitglieder gleichzeitig
im Speicher halten. Gleicher Inhalt ist nur technische Evidence und darf nicht
als Datei-, `Edition`- oder `Work`-Identität ausgegeben werden.

## Entscheidung

FolioTone verwendet das Profil `ebook-collection-report/v1` und die CLI
`foliotone ebook-collection-report`. Ein Bericht liest genau einen
persistierten `EbookCollectionRun` in einer Datenbanktransaktion. Ein noch
`RUNNING` befindlicher Lauf wird abgelehnt; abgeschlossene und unterbrochene
Läufe können berichtet werden. Der Bericht öffnet keine Source-Media-Datei und
ruft keinen `ToolProvider` auf.

Alembic `0008_ebook_collection_reports` ergänzt:

- `ebook_collection_item_executions` für die geordneten Workflow-Schritte,
  Dispositionen und exakten `ToolExecution`-Referenzen eines Items;
- `ebook_collection_findings` für geordnete Quality-Befundcodes, Dimensionen
  und Schweregrade;
- `ebook_collection_finding_executions` für die geordneten
  `ToolExecution`-Quellen jedes Befunds;
- einen zusammengesetzten `fingerprints`-Index für die tatsächlich verwendete
  Gruppierung nach Kind, Algorithmus, Version, Wert und Target.

Neue Collection-Abschlüsse schreiben diese Projektionen zusammen mit dem
terminalen Item-Zustand in einer Transaktion. Stimmen persistierte
Schrittzähler und Ausführungsprojektion oder `finding_count` und
Befundprojektion nicht überein, wird der Bericht abgelehnt. Damit werden ältere
oder unvollständige Läufe nicht scheinbar vollständig interpretiert.

Der JSON-Bericht enthält vollständige aggregierte Format-, Analyse-, Quality-
und Befundzähler sowie eine begrenzte priorisierte Review-Liste. Die
Priorisierung lautet: technischer Analysefehler, fehlgeschlagene Analyse, noch
nicht analysiert, `ACTION_REQUIRED`, `INCOMPLETE`, `PARTIAL_FAILURE` und
`REVIEW`. Befunde behalten ihre exakten verfügbaren `ToolExecution`-IDs.

Zwei technische Kandidatenmengen werden getrennt erzeugt:

- Exact-Duplicate-Kandidaten besitzen denselben aktuellen vollständigen
  `FILE_SHA256` mit Algorithmus `sha256` und Version `1`;
- Content-Variant-Kandidaten besitzen denselben versionierten
  `EBOOK_NORMALIZED_TEXT`-Fingerprint, aber mindestens zwei unterschiedliche
  vollständige `FILE_SHA256`-Werte.

Diese Gruppen sind Review-Kandidaten. Sie erzeugen keine `Relation`, keine
Confidence und kein Identitätsurteil. Rohe Datei- und Textfingerprints werden
nicht ausgegeben. Die stabile Gruppen-ID ist ein SHA-256 über Basis,
Algorithmus, Version und internen Gruppenwert.

Die Kandidatenabfragen lesen sortierte SQL-Ergebnisse mit `fetchmany(500)`.
Nur die nach Mitgliederzahl größten begrenzten Gruppen werden in einem Heap
gehalten. Standardgrenzen sind 10.000 Review-Items, 1.000 Gruppen je Basis und
100 Mitglieder je Gruppe; feste Maxima sind 100.000, 10.000 und 1.000. Der
Bericht weist vollständige Gesamtzahlen und jede Kürzung ausdrücklich aus.

Die Ausgabe besteht aus deterministischem JSON, Review-CSV, zwei Kandidaten-
CSV-Dateien und `checksums.sha256`. Sie liegt ausschließlich unter einem
privaten Report Root außerhalb des Source Root. Das SHA-256 des JSON-Inhalts
bestimmt das stabile Unterverzeichnis; Schreiben erfolgt über ein temporäres
Verzeichnis mit atomarer Veröffentlichung und Integritätsprüfung bei
Wiederholung. CSV-Zellen mit Tabellenformel-Präfixen werden neutralisiert.
Relative Pfade dürfen im privaten Bericht stehen, werden aber nicht in der
CLI-Zusammenfassung ausgegeben und bleiben außerhalb von Git.

## Konsequenzen

- Ein vorhandener Lauf kann offline und ohne erneuten Medienzugriff mehrfach
  byte-stabil berichtet werden.
- Begrenzte Outputs bleiben auch bei großen Sammlungen kontrollierbar; die
  vollständigen Summen zeigen, wenn Detailzeilen gekürzt wurden.
- Alte W3-015-Läufe mit Schritt- oder Befundzählern ohne W3-016-Projektion
  müssen erneut als neuer Collection-Lauf analysiert werden, bevor ein
  vollständiger Bericht möglich ist.
- Duplicate- und Varianten-Gruppen liefern einen konkreten Review-Einstieg,
  bleiben aber ausdrücklich unterhalb der späteren Matching- und
  Identitätsentscheidung.
- Report Root, Datenbank und andere Runtime-Artefakte bleiben beschreibbar;
  Source Media bleibt read-only und unverändert.
