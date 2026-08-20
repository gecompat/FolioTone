# ADR-0015: Scan-Resume als neuer Run mit persistenter Lineage

- Status: Accepted
- Datum: 2026-08-09

## Kontext

Ein großer Filesystem-Scan kann durch Benutzerabbruch, Container-Neustart oder Prozessunterbrechung enden, nachdem bereits ein Teil der Dateien verarbeitet wurde. FolioTone persistiert Beobachtungen, `FileRecord`-Zustände und Fingerprints batchweise. Ein `INTERRUPTED`-Run darf jedoch nicht so behandelt werden, als wäre der gesamte `ScanRoot` erfolgreich beobachtet worden; insbesondere darf er keine `MISSING`-Evidenz für nicht mehr erreichte Pfade erzeugen.

Ein Resume sollte bereits geleistete teure Arbeit wiederverwenden, ohne einen instabilen Filesystem-Cursor als dauerhaften Vertrag einzuführen. Die Iterationsreihenfolge von `os.scandir` ist nicht als portable, unveränderliche Reihenfolge garantiert. Ein Checkpoint wie „letzter Pfad“ könnte deshalb bei einer späteren Fortsetzung Dateien überspringen oder doppelt behandeln.

## Entscheidung

Ein Resume öffnet den alten `ScanRun` nicht erneut. FolioTone erzeugt einen neuen `ScanRun` und speichert dessen `resumed_from_run_id` als Referenz auf den vorherigen Versuch.

Ein Run darf als Resume-Quelle nur verwendet werden, wenn:

1. er bereits persistent existiert;
2. sein Status `INTERRUPTED` ist;
3. er zum selben logischen `ScanRoot` gehört.

Die CLI stellt dafür `foliotone scan --resume-run <ScanRunId>` bereit. Ohne diese Option bleibt ein Scan ein normaler neuer Versuch ohne Resume-Lineage.

## Wiederverwendung der Teilverarbeitung

Resume führt die Filesystem Discovery erneut vollständig und streaming-basiert aus. Es wird kein persistenter `os.scandir`-Cursor verwendet.

Bereits vor dem Interrupt erfolgreich verarbeitete Dateien haben ihren aktuellen
`FileRecord` und gegebenenfalls Fingerprints bereits persistent gespeichert.
Wenn dieselben Dateien beim Resume unverändert beobachtet werden, klassifiziert
der bestehende Incremental-Vergleich sie als `UNCHANGED`. FolioTone öffnet diese
Quelldateien nicht erneut, sondern projiziert die vollständigen versionierten
Hashwerte der jeweils jüngsten vorherigen `FileObservation` auf die neue
Observation. Ein älterer Hash darf nicht über eine jüngere unvollständige
Observation hinweg wiederverwendet werden. Fehlt der erforderliche Hash gerade
in der jüngsten Observation, wird ausschließlich dieses unvollständige Objekt
nachgehasht.

Berechnung und Persistenz bleiben begrenzt: Die CLI verwendet standardmäßig
`--hash-workers auto`. Diese Heuristik wählt höchstens die Hälfte der sichtbaren
CPU-Anzahl und bleibt auf 1 bis 8 Worker begrenzt; eine explizite Zahl ersetzt
die Heuristik. Alle Fingerprints eines Discovery-Batches werden erst
nach der Berechnungsphase gemeinsam in einer Transaktion gespeichert. Ein
interner Abbruch hinterlässt deshalb keine neue partielle Fingerprintmenge. Ein
Discovery-Batch persistiert außerdem seine `FileRecord`-, `FileObservation`-
und `FileEvent`-Änderungen set-orientiert in einer Store-Transaktion. Ein
objektspezifischer `OSError` bleibt dagegen auf das betroffene Objekt begrenzt:
Der vollständige Discovery-Run kann beendet werden, die CLI meldet eine
Teilfehlermenge und ein Folgescan versucht nur die fehlende jüngste Hash-
Evidence erneut.

Dateien, die vor dem Interrupt noch nicht erreicht wurden, werden beim Resume entsprechend ihrem realen aktuellen Zustand normal verarbeitet. Auf diese Weise entsteht ein vollständiger neuer erfolgreicher Scan, ohne den alten partiellen Run inhaltlich umzuschreiben.

## Abwesenheit und Unterbrechung

Die `MISSING`-/`DELETED`-Phase läuft weiterhin ausschließlich nach vollständig
erfolgreicher Discovery. Ein `KeyboardInterrupt` signalisiert aktiven
In-Process-Hashreads zuerst einen kooperativen Abbruch, setzt den aktuellen Run
auf `INTERRUPTED` und verlässt den Scan vor `mark_missing`. Die CLI beendet den
kontrollierten Abbruch ohne Traceback mit Exitcode 130.

Das bedeutet:

- nicht erreichte bekannte Dateien werden durch einen unterbrochenen Run nicht als `MISSING` markiert;
- eine `DELETED`-Bestätigungsserie wird durch einen unterbrochenen Run nicht erhöht;
- erst der erfolgreich abgeschlossene Resume-Run darf Abwesenheit für den gesamten `ScanRoot` klassifizieren.

## Audit und Fehlerfälle

Der Resume-Run besitzt eine eigene ID, eigene Zeitstempel, eigene `FileObservation`- und `FileScanEvent`-Einträge und eine explizite Lineage zum unterbrochenen Vorgänger. Der Vorgänger bleibt unverändert `INTERRUPTED`.

`FAILED`, `COMPLETED` oder noch `RUNNING` befindliche Runs sind keine zulässigen Resume-Quellen. Ebenso kann ein Run eines anderen `ScanRoot` nicht als Resume-Quelle verwendet werden.

ADR-0025 lässt einen `RUNNING`-Lauf weiterhin nicht direkt als Resume-Quelle
zu. Eine ausdrückliche stale-Run-Recovery muss ihn zuerst unter Lease- und
Konkurrenzprüfung atomar auf `INTERRUPTED` setzen; erst danach gilt der hier
definierte Resume-Vertrag.

## Konsequenzen

- einzelne Scanversuche bleiben unveränderlich nachvollziehbar;
- ein Resume benötigt keinen nicht-portablen Directory-Cursor;
- Discovery-I/O wird erneut durchgeführt, teures Rehashing unveränderter bereits verarbeiteter Dateien wird jedoch vermieden;
- die aktuelle Observation erhält wiederverwendete Hash-Evidence, ohne die Source erneut zu öffnen;
- nur fehlende jüngste Hash-Evidence wird gezielt ergänzt; stale ältere Evidence wird nicht als vollständig behandelt;
- Hashberechnung ist ausdrücklich begrenzt parallelisierbar und Persistenz bleibt pro Batch atomar;
- Zustandsänderungen eines Discovery-Batches werden set-orientiert statt objektweise geschrieben;
- objektspezifische Hash-I/O-Fehler brechen die übrige Sammlung nicht ab und werden im Folgescan selektiv erneut versucht;
- partielle `FileRecord`-/Fingerprint-Arbeit bleibt nutzbar;
- Abwesenheitsentscheidungen bleiben an einen vollständigen erfolgreichen Scan gebunden;
- das Verfahren bleibt bounded-memory und benötigt keine collection-weite Pfadliste;
- Source Media bleibt read-only; Resume führt keine Move-, Rename-, Delete- oder Retag-Operation aus.
