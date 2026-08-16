# ADR-0023: Selektives Vollhashing von Duplikatkandidaten

- Status: Accepted
- Datum: 2026-08-15

## Kontext

Ein vollständiger SHA-256-Hash aller Dateien einer großen, über ein
Netzlaufwerk gelesenen Sammlung verursacht erheblichen I/O, obwohl der größte
Teil der Dateien keine plausible Duplikatbeziehung besitzt. Der begrenzte
`QUICK_FILE`-Fingerprint aus Dateigröße sowie Head-/Tail-Samples eignet sich
zum billigen Blocking, ist aber ausdrücklich kein Beweis für Dateigleichheit.
Der deterministische Collection-Bericht darf Exact-Duplicate-Kandidaten nur
auf vollständiges `FILE_SHA256` stützen.

## Entscheidung

FolioTone verwendet das Profil `ebook-duplicate-hash/v1` und die CLI
`foliotone ebook-hash-candidates`. Ein Lauf bindet sich an den neuesten
`COMPLETED`-`ScanRun` eines aktivierten EBOOK-`ScanRoot` und berücksichtigt nur
aktuelle `PRESENT`-Beobachtungen, deren Pfad, Größe und Änderungszeitpunkt noch
mit dem zugehörigen `FileRecord` übereinstimmen.

Eine Beobachtung wird nur geplant, wenn genau ein konsistenter versionierter
`QUICK_FILE`-Wert vorliegt, mindestens eine zweite aktuelle Beobachtung
denselben Quick-Wert besitzt und für die Beobachtung noch kein vollständiger
`FILE_SHA256`-Nachweis im Profil `sha256/1` existiert. Quick-Kollisionen
erzeugen damit nur Kandidaten; erst gleiche vollständige SHA-256-Werte bilden
Exact-Duplicate-Evidence.

Die Kandidatenabfrage bleibt bounded-memory und verwendet stabile
Keyset-Batches statt einer collection-weiten Python-Liste. Die Abfrage
schränkt vor der Fingerprint-Aggregation auf den aktuellen Scan ein und
materialisiert den Kandidaten-Snapshot einmal pro Invocation in einer
verbindungslokalen Temp-Tabelle. Statistik und Batches wiederholen dadurch
nicht dieselbe historische Fingerprint-Aggregation. Ein Lauf verwendet 1 bis
8 Hash-Worker und persistiert höchstens 500 erfolgreiche Fingerprints je Batch
atomar. `--max-items` begrenzt eine Invocation. Ein erneuter identischer Aufruf
setzt implizit fort, weil bereits vollständig gehashte Beobachtungen von der
nächsten Abfrage ausgeschlossen werden.

Vor und nach dem Streaming-Hash wird die physische Datei gegen ihre
persistierte `FileObservation` validiert. Eine nicht verfügbare oder inzwischen
veränderte Datei bleibt ein isolierter pfadfreier Fehler; andere Kandidaten
laufen weiter. Die Source wird ausschließlich gelesen. Das Kommando verschiebt,
benennt, löscht oder schreibt keine Quelldatei.

Ein späterer normaler Quick-Scan darf vorhandene vollständige Evidence auf die
neue unveränderte Observation projizieren. Dadurch bleibt die selektive
Investition über inkrementelle Scans nutzbar, ohne die Datei erneut zu öffnen.

## Konsequenzen

- Vollständiger Datei-I/O skaliert mit plausiblen Quick-Kollisionen statt mit
  der gesamten Sammlung.
- Unterbrechungen verlieren höchstens den noch nicht persistierten aktuellen
  Batch; ein erneuter Aufruf überspringt abgeschlossene Kandidaten.
- Quick-Fingerprints bleiben Blocking-Evidence und werden nicht als
  Identitäts- oder Löschentscheidung interpretiert.
- Konkurrierende Kandidaten-Hashläufe für denselben Snapshot sind nicht Teil
  des aktuellen CLI-Vertrags; ein Lauf wird operativ einmalig gestartet und
  bei Bedarf fortgesetzt.
- Private Pfade und Hashwerte werden nicht in die CLI-Zusammenfassung oder das
  Repository geschrieben.
