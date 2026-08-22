# ADR-0029: Begrenztes E-Book-Candidate-Blocking und Relation Contracts

- Status: Accepted
- Datum: 2026-08-17

## Kontext

FolioTone besitzt technische Hash-, Text-, Metadaten-, Struktur- und Cover-
Evidence sowie persistierte lokale Resolution Candidates und Review-
Entscheidungen. Ein Matching über alle Dateien gegen alle anderen Dateien
würde bei großen Sammlungen dennoch quadratisch wachsen. Auch ein einzelner
großer Block darf nicht ungeprüft als vollständige Paarmenge expandiert
werden.

Die bestehende `RelationType`-Taxonomie benennt technische und
bibliografische Beziehungen, erzwingt aber noch nicht für jeden book-only Typ
die zulässige Identitätsebene. Blockzugehörigkeit und Relation müssen zudem
getrennt bleiben: Ein Candidate Block reduziert den Suchraum, bestätigt aber
keine Identität.

## Entscheidung

EB-05 führt einen provider-neutralen, read-only `CandidateBlock`-Vertrag ein.
Ein Block enthält ausschließlich:

- einen festen `CandidateBlockType`;
- einen domain-separierten SHA-256-Key-Fingerprint und eine Blockversion;
- die fachliche Identitätsebene;
- Anzahl und begrenzte, deterministisch sortierte Mitglieder;
- konkrete opake Evidence-IDs;
- Status und gegebenenfalls einen deterministischen Representative.

Rohwerte von Hashes, Identifiern, Namen, Titeln oder Pfaden werden weder im
DTO noch in Ausgaben gespeichert. Der Key-Fingerprint ist ein technischer
Gruppierungsschlüssel und niemals Identitätsbeweis.

Primäre book-only Blocktypen sind:

1. `FILE_SHA256`;
2. `EDITION_IDENTIFIER`;
3. `RESOLVED_EDITION`;
4. `RESOLVED_WORK`;
5. `AGENT_TITLE`;
6. `TEXT_FINGERPRINT`.

`SERIES_CONTEXT` ist ausschließlich unterstützend und darf allein keinen
Identity Candidate erzeugen. Dasselbe gilt für Classification, Cover und
Quality Evidence.

## Größen- und Komplexitätsgrenze

Jede öffentliche Abfrage besitzt feste Obergrenzen für Blockanzahl und
ausgegebene Mitglieder. Ein nicht exakter Block oberhalb der konfigurierten
Mitgliedergrenze erhält `SECONDARY_REQUIRED` und darf nicht paarweise
expandiert werden. Nachfolgende Matcher müssen ihn anhand zusätzlicher
unabhängiger Evidence weiter unterteilen oder überspringen.

`FILE_SHA256` wird als `EXACT_GROUP` mit dem lexikografisch kleinsten
Observation-Identifier als Representative dargestellt. Auch tausend
bytegleiche Dateien erzeugen damit einen Group-Vertrag und begrenzte
Membership-Daten statt 499.500 Paarrelationen.

Der Reader bindet sich an einen expliziten neuesten `COMPLETED`-`ScanRun` und
öffnet keine Source Media. Er verwendet ausschließlich aktuelle, weiterhin
passende E-Book-Observations und konsistente persistierte Fingerprints.
Akzeptierte beziehungsweise exakt wiederverwendete EB-02-Resolution wird als
Blocking-Key verwendet, ohne Source Evidence oder kanonische Entity-Felder zu
ändern.

EB-05 persistiert weder Candidate Blocks noch Relation Proposals. Damit
entstehen keine neue Writer-Art, Root-Lease oder Runtime-Tabelle. EB-06 kann
auf dem stabilen Blockvertrag versionierte Relation Candidates, Scoring,
Explanation und Review aufbauen.

## Relation Contracts

Die book-only Endpoint-Matrix lautet:

| Relation | Endpoint-Ebene | Semantik |
|---|---|---|
| `EXACT_DUPLICATE` | `FILE` | gleiche vollständige File-Bytes |
| `CONTENT_DUPLICATE` | `FILE` | gleicher relevanter Inhalt, technische Bytes können abweichen |
| `FORMAT_VARIANT` | `FILE` | technische Repräsentationsvariante, keine alleinige Identitätsaussage |
| `QUALITY_VARIANT` | `FILE` | Qualitätsvariante, keine alleinige Identitätsaussage |
| `SAME_EDITION` | `EDITION` | zwei Kandidaten bezeichnen dieselbe Edition |
| `DIFFERENT_EDITION` | `EDITION` | nachweislich verschiedene Editionen desselben Work |
| `SAME_WORK` | `WORK` | zwei Kandidaten bezeichnen dasselbe abstrakte Work |

Self-Relations bleiben verboten. `DIFFERENT_EDITION` bedeutet nicht bloß
„nicht dieselbe Edition“, sondern verlangt sowohl Same-Work- als auch
Distinct-Edition-Evidence. `FORMAT_VARIANT` und `QUALITY_VARIANT` bestätigen
keine bibliografische Identität. Ein Provider- oder Tool-Treffer darf starke
widersprechende lokale Evidence nicht überstimmen.

Relation Contracts definieren erforderliche Evidence-Codes, führen in EB-05
aber weder Scoring noch automatische Relation-Persistenz aus.

## Datenschutz und Sicherheit

- Source Media bleiben read-only und werden nicht geöffnet.
- Es gibt keine Lösch-, Move-, Rename-, Retag- oder Calibre-Mutation.
- DTOs und Fehler enthalten keine Pfade, Dateinamen oder materiellen
  Metadatenwerte.
- Nur synthetische Daten werden in Tests verwendet.
- Dieser Slice öffnet keinen eigenen W10-Pfad; nur die getrennte
  ADR-0056-Interim-Quarantäne ist ausführbar.

## Konsequenzen

- Candidate Generation bleibt bounded und vermeidet globales All-vs-All.
- Exact-Duplicate-Gruppen bleiben näher an O(n) als an O(n²).
- Blocktypen und Relationsebenen können in EB-06 nicht still umgedeutet
  werden; eine Semantikänderung erfordert eine neue Profilversion.
- Fehlende oder widersprüchliche Evidence erzeugt höchstens Candidates, keine
  bestätigte Relation.
- Zusätzliche Persistenzindizes oder persistierte Matching Runs sind nicht Teil
  dieser ADR und benötigen einen getrennten, ausdrücklich freigegebenen
  Schema-Slice.

## Verifikation

Deterministische Unit- und SQLite-Integrationstests prüfen Literale,
Key-Fingerprints, Relationsebenen, path-free DTOs, Snapshot-Lineage,
konsistente Hashwerte, akzeptierte Resolution, übergroße Blocks und eine
synthetische Exact-Duplicate-Gruppe mit tausend Mitgliedern ohne Paarliste.
