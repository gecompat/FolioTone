# ADR-0019: Provider-neutraler Vergleich persistierter E-Book-Evidence

- Status: Accepted
- Datum: 2026-08-15

## Kontext

FolioTone persistiert für eine exakte `FileObservation` rohe Datei-
Fingerprints sowie versionierte Text-, Metadaten-, Struktur- und Cover-
Evidence. Für Duplicate- und Variantenanalyse müssen zwei Beobachtungen diese
Evidence reproduzierbar vergleichen können, ohne Source Media erneut zu öffnen
oder einen provider-spezifischen GUI-Diff zu benötigen.

Ein Vergleich einzelner Signale ist noch kein Matching. Identische Dateibytes,
normalisierter Text, Metadaten oder Cover bestätigen allein weder dieselbe
`Edition` noch dasselbe `Work`. Fehlende, inkompatible oder veraltete Evidence
darf nicht als Unterschied umgedeutet werden. Rohe Metadatenwerte und private
Pfade dürfen nicht über die CLI offengelegt werden.

## Entscheidung

FolioTone stellt `EbookComparisonService`, den CLI-Befehl `ebook-compare` und
das Profil `ebook-comparison/v1` bereit. Der Service liest ausschließlich
persistierte, an zwei explizite `FileObservation`-IDs gebundene Evidence. Er
öffnet keine Source-Datei, führt kein externes Tool aus und schreibt weder
`Relation` noch `Evidence`, Confidence oder Matchstatus.

Das Ergebnis enthält die stabil geordneten Dimensionen `FILE_BYTES`,
`NORMALIZED_TEXT`, `METADATA`, `STRUCTURE` und `COVER`. Jede Dimension meldet
`SAME`, `DIFFERENT`, `INDETERMINATE` oder `NOT_APPLICABLE` sowie die getrennte
Coverage `COMPLETE`, `PARTIAL`, `NONE` oder `NOT_APPLICABLE`. Der
Gesamtzustand `COMPLETE`, `PARTIAL` oder `UNAVAILABLE` beschreibt nur die
Evidence-Coverage und ist kein Identitätsurteil.

Für die Dimensionen gelten folgende Grenzen:

- `FILE_BYTES` verwendet ausschließlich kompatible vollständige
  `FILE_SHA256`-Fingerprints. `QUICK_FILE` genügt nicht für Bytegleichheit.
- `NORMALIZED_TEXT` vergleicht ausschließlich dieselbe Algorithmus- und
  Profilversion von `EBOOK_NORMALIZED_TEXT`.
- `METADATA` vergleicht Mengen provider-neutral projizierter Feldkandidaten.
  Bei gleichartigen Provider-Schemas zählt auch ein nur einseitig vorhandenes
  Feld als Unterschied; bei unterschiedlichen Schemas wird nur der sichere
  gemeinsame Feldumfang verglichen. Die CLI nennt Feldpfade und Counts, aber
  keine Werte.
- Der interne, bei calibre-Extraktionen ohne stabilen Identifier neu erzeugte
  Namespace `identifier.calibre` wird nicht als bibliografisches
  Vergleichsfeld verwendet. Die rohe Candidate-Evidence bleibt unverändert
  persistiert.
- `STRUCTURE` vergleicht bei zwei EPUB-Beobachtungen den Konformitätszustand,
  Severity-Counts und begrenzte Diagnostic-Codes. Für andere Formatpaare ist
  die Dimension `NOT_APPLICABLE`.
- `COVER` vergleicht bei calibre-Formaten Cover-Präsenz und kompatible
  `EBOOK_COVER_DHASH`-Fingerprints. Die Hamming-Distanz ist ein technischer
  Fakt ohne Ähnlichkeitsschwelle oder Identitätsbedeutung.

Für jeden Provider und jede Capability gilt nur dessen neueste persistierte
Ausführung für die Beobachtung. Ist diese Ausführung fehlgeschlagen oder
abgebrochen, wird ältere Evidence desselben Providers nicht als aktuell
verwendet. Evidence verschiedener Provider bleibt gleichzeitig sichtbar;
mehrere Werte werden nicht zu einem kanonischen Wert zusammengeführt.

Die CLI-Ausgabe ist begrenzt auf IDs, Formate, Zustände, Coverage, Evidence-
Counts, ToolExecution-IDs und sichere Feld-/Profilfakten. Sie endet
ausdrücklich mit `Identity verdict: NOT_PRODUCED` und
`Relation records written: 0`.

## Konsequenzen

- Paarvergleiche sind reproduzierbar, provider-neutral und ohne erneuten
  Medienzugriff möglich.
- Exact-Duplicate- und Varianten-Candidate-Blocking kann später dieselben
  Einzeldimensionen verwenden, benötigt aber einen eigenen versionierten
  Vertrag für Gruppenbildung, Relationstypen, Confidence und Review.
- Fehlende oder inkompatible Evidence bleibt `INDETERMINATE`; ein technischer
  Mangel erzeugt keinen falschen Unterschied.
- Cover-Distanz und Metadatenunterschiede bleiben unterstützende Evidence und
  dürfen nicht allein eine Datei-, `Edition`- oder `Work`-Identität bestätigen.
- Collection-Batch-Optimierung und datenbankseitige Evidence-Indizes bleiben
  nachgelagerten, messungsbasierten Wellen vorbehalten.
