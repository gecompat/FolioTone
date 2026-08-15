# ADR-0020: Begrenzte und indexgestützte E-Book-Evidence-Abfragen

- Status: Accepted
- Datum: 2026-08-15

## Kontext

`ebook-comparison/v1` benötigt für einen Paarvergleich ausschließlich die
persistierte Evidence zweier expliziter `FileObservation`-IDs. Die erste
Implementierung filterte dafür die Ergebnisse von `Repository.list_all()`.
Der fachliche Output war korrekt, Laufzeit und Speicherbedarf wuchsen jedoch
mit allen `ToolExecution`-, `ToolResult`- und `Fingerprint`-Datensätzen der
Sammlung. Dieses Zugriffsverhalten ist für große Sammlungen ungeeignet.

Ein Performance-Test muss ohne private Medien reproduzierbar bleiben. Eine
reine Laufzeitschwelle genügt außerdem nicht als Skalierungsnachweis, weil sie
von Host und Dateisystem abhängt. Der Test muss auch die Zahl und Form der
Datenbankabfragen sowie die verwendeten Indizes prüfen.

## Entscheidung

FolioTone lädt Paarvergleichs-Evidence mit
`load_observation_evidence()` ausschließlich für eine explizite Menge von
`FileObservation`-IDs. Eine Anfrage ist auf 16 IDs begrenzt; der aktuelle
Paarvergleich verwendet genau zwei. Die drei SQL-Abfragen enthalten jeweils
einen Target-Filter und ein zusätzliches `LIMIT maximum + 1`:

- höchstens 1.024 `ToolExecution`-Datensätze;
- höchstens 16.384 `ToolResult`-Datensätze;
- höchstens 4.096 `Fingerprint`-Datensätze.

Eine Überschreitung erzeugt `EvidenceQueryLimitError`. Der Vergleich bricht
mit einem technischen `EbookComparisonError` ab und fällt nicht auf einen
collection-weiten Scan zurück. Die Grenzwerte begrenzen die Historie und
Evidence-Dichte der angeforderten Beobachtungen, nicht die Zahl der Dateien in
der Sammlung.

Alembic `0006_ebook_evidence_lookup_indexes` ergänzt folgende additive
Indizes:

- `ix_tool_executions_input_capability_provider_started`;
- `ix_tool_results_target_execution`;
- `ix_fingerprints_target_kind_execution`.

Der synthetische Performance-Vertrag erzeugt 10.000 nicht angeforderte
Datensätze je Evidence-Tabelle. Er verlangt genau drei gefilterte
Evidence-Abfragen, die drei neuen Indizes im SQLite-Query-Plan, ausschließlich
die angeforderten Records und eine lokale Obergrenze von zwei Sekunden für
den isolierten Read. Die Zeitgrenze ist ein Regression Guard für CI und keine
allgemeine Laufzeitgarantie für andere Hardware.

Der additive Korpus `foliotone-ebook-comparison-fixture/v2` ergänzt die
Ground Truth um AZW, AZW3 und PDF, `SPARSE`- und `MALFORMED`-Evidence sowie
Cover-dHash-Distanzen von 0, 1, 8, 32 und 64 Bit. Er verwendet ausschließlich
kleine synthetische Container-Surrogate und bereits extrahierte synthetische
Textartefakte. Weder externe Tools noch reale Medien sind Bestandteil dieses
Vertrags.

## Konsequenzen

- Die Kosten eines Paarvergleichs hängen von der Evidence-Historie der beiden
  Beobachtungen ab, nicht von collection-weiten Tabellenzeilen.
- Ungewöhnlich dichte oder beschädigte Evidence führt zu einem begrenzten,
  erklärbaren Fehler statt zu unbeschränktem Speicherverbrauch.
- Die Migration schreibt keine bestehenden Domain-Datensätze um.
- `ebook-comparison/v1` und seine fachlichen Zustände bleiben unverändert;
  W3-014 ändert nur den Leseweg und erweitert die kontrollierte Ground Truth.
- Collection-Batch-Orchestrierung erhält in W3-015 einen eigenen
  fortsetzbaren Vertrag und darf die Paarabfragegrenzen nicht durch globale
  Vorabladung umgehen.
