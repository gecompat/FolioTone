# ADR-0021: Fortsetzbare E-Book-Collection-Analyse

- Status: Accepted
- Datum: 2026-08-15

## Kontext

`ebook-analyze` verarbeitet genau eine persistierte `FileObservation`. Für eine
Sammlung mit hunderttausenden Dateien reicht dieser Einzelaufruf nicht aus:
Der zu analysierende Snapshot muss stabil bleiben, Arbeit muss nach einem
Prozessabbruch fortsetzbar sein, und ein einzelner Tool- oder Dateifehler darf
die restliche Sammlung nicht blockieren.

Eine Collection-Orchestrierung darf weder alle Beobachtungen in eine Python-
Liste laden noch private Pfade oder Metadaten in ihren Laufzustand übernehmen.
Mehrere Worker müssen begrenzt bleiben. Gleichzeitig muss die bereits
implementierte exakte Evidence-Wiederverwendung gelten, damit unveränderte
Dateien und intakte Tool-Ergebnisse nicht erneut analysiert werden.

## Entscheidung

FolioTone verwendet das Profil `ebook-collection-analysis/v1`. Ein neuer Lauf
bindet einen unveränderlichen Plan an den neuesten `COMPLETED`-`ScanRun` eines
aktivierten EBOOK-`ScanRoot`. Der Plan enthält ausschließlich
EPUB/MOBI/AZW/AZW3/PDF-Beobachtungen dieses Scans, deren aktueller
`FileRecord` weiterhin `PRESENT` ist und bei relativem Pfad, Größe und
Änderungszeitpunkt exakt mit der Beobachtung übereinstimmt.

Die Planung liest den Snapshot einmal in stabiler Pfad-/ID-Reihenfolge und
übernimmt ihn mit `fetchmany(500)` in begrenzten Schreibbatches. `--plan-limit`
kann für einen deterministischen Pilotlauf den neuen Plan begrenzen. Nach der
Anlage bleibt der Plan unverändert; ein Resume plant nicht erneut.

Alembic `0007_ebook_collection_batches` führt zwei Tabellen ein:

- `ebook_collection_runs` hält `ScanRoot`, Source-`ScanRun`, Collection- und
  Analyseprofil, Evidence-Policy, Workerzahl, Lifecycle und Lease;
- `ebook_collection_items` hält Observation-ID, stabilen Ordinalwert, Format,
  Versuchszahl, technischen Status, Quality-Gesamtstatus sowie begrenzte
  Schritt- und Befundzähler.

Die Batch-Tabellen speichern keine relativen oder absoluten Pfade, keine
Metadatenwerte und keine extrahierten Inhalte. Die Observation-ID stellt den
Link zur bereits geschützten lokalen Runtime-Persistenz her.

Ein Lauf besitzt höchstens eine aktive Lease. Die Standarddauer beträgt 30
Minuten. Eine Invocation beansprucht höchstens das Zweifache der gespeicherten
Workerzahl; die Workerzahl liegt zwischen 1 und 8. Eine aktive, nicht
abgelaufene Lease verhindert konkurrierendes Resume. Nach Ablauf oder sauberer
Freigabe werden lediglich noch `RUNNING` markierte Items auf `PENDING`
zurückgesetzt und mit erhöhter Versuchszahl erneut bearbeitet.

Item-Zustände sind `PENDING`, `RUNNING`, `SUCCEEDED`, `PARTIAL_FAILURE`,
`FAILED` und `ERROR`. Erwartete oder unerwartete per-File-Fehler werden als
begrenzte pfadfreie Fehlercodes persistiert; unabhängige Items laufen weiter.
`--max-items` beendet eine Invocation kontrolliert mit `INTERRUPTED`, solange
Planpositionen offen sind. Ein vollständig abgearbeiteter Plan endet als
`COMPLETED` oder, bei technischen Teilfehlern, als
`COMPLETED_WITH_FAILURES`.

Jedes Item verwendet unverändert `ebook-analysis-workflow/v3` und dessen
exakte Evidence-Wiederverwendung. `--fresh` wird bei der Plananlage für den
gesamten Lauf gespeichert und kann beim Resume nicht geändert werden. Der
Batch-Modus aktiviert zusätzlich einen prozesslokalen, thread-sicheren Cache
für identische Tool-Versionsprobes. Verschiedene Tools können weiterhin
parallel geprüft werden; identische Probes laufen innerhalb einer Invocation
nur einmal. Der Cache ist für Einzeldatei-Kommandos nicht standardmäßig aktiv
und ersetzt keine persistierte Evidence-Prüfung.

Die CLI `ebook-collection-analyze` gibt ausschließlich logische Run-IDs,
Profile und Summenzähler aus. Datenbank, Tool-Artefakte und Work-Verzeichnis
müssen außerhalb des Source Root liegen. Die vorhandenen Adapter prüfen vor
jedem tatsächlichen Toollauf weiterhin, dass die Source-Datei der geplanten
`FileObservation` entspricht. Source Media wird weder geschrieben noch
verschoben, umbenannt oder gelöscht.

## Konsequenzen

- Ein unterbrochener oder zeitlich begrenzter Lauf kann ohne neuen Snapshot und
  ohne Wiederholung abgeschlossener Items fortgesetzt werden.
- Änderungen zwischen Planung und Analyse werden nicht stillschweigend
  übernommen; die exakte Observation-Prüfung erzeugt stattdessen einen
  begrenzten per-File-Fehler.
- Tool- oder Adapterversionen dürfen sich zwischen Invocations ändern. Die
  bestehende Evidence-Planung entscheidet dann pro Schritt erneut über
  Wiederverwendung oder Ausführung.
- SQLite-Verbindungen verwenden ein 30-Sekunden-`busy_timeout`. Item-
  Abschlüsse werden durch den Orchestrator serialisiert; ToolExecutions dürfen
  innerhalb der begrenzten Workerzahl parallel persistiert werden.
- Der Batchstatus ist keine Matching- oder Identitätsentscheidung. Der Lauf
  erzeugt keine `Relation`, keine Confidence und keine kanonischen Metadaten.
- Detaillierte lokale Qualitäts-, Duplicate- und Variantenberichte bleiben
  `W3-016`. Private Berichtsdaten und Sammlungspfade bleiben außerhalb von Git.
