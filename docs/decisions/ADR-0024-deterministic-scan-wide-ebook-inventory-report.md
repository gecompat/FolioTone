# ADR-0024: Deterministischer scanweiter E-Book-Inventarbericht

- Status: Accepted
- Datum: 2026-08-15

## Kontext

Die fortsetzbare Collection-Analyse liefert tiefe Metadaten-, Text-, Struktur-
und Quality-Evidence für geplante Dateien. Für einen frühen praktischen Nutzen
auf großen Sammlungen wird zusätzlich eine schnelle Übersicht über den bereits
persistierten Scan benötigt: Format- und Größenverteilung, Abdeckung der Hash-
Evidence, noch offene Quick-Duplikatkandidaten und bereits exakt bestätigte
byte-identische Dateien. Dieser Überblick darf weder einen vollständigen
Analyzer-Lauf noch einen erneuten Zugriff auf Source Media voraussetzen.

Ein Bericht über einen laufenden Scan wäre nicht reproduzierbar. Rohe Hashwerte
oder private relative Pfade dürfen außerdem nicht in Konsolenausgabe oder Git
gelangen. Ein Exact-Duplicate-Nachweis ist noch keine Lösch-, Keep- oder
Identitätsentscheidung.

## Entscheidung

FolioTone verwendet das Profil `ebook-inventory-report/v1` und die CLI
`foliotone ebook-inventory-report`. Die Projektion bindet sich ausschließlich
an den neuesten `COMPLETED`-`ScanRun` eines aktivierten EBOOK-`ScanRoot`. Ist
der neueste Lauf noch aktiv, fehlgeschlagen oder unterbrochen, wird der Bericht
abgelehnt statt einen älteren oder sich verändernden Stand stillschweigend zu
verwenden.

Berücksichtigt werden aktuelle `PRESENT`-Beobachtungen der unterstützten
EPUB/MOBI/AZW/AZW3/PDF-Formate, deren Pfad, Größe und Änderungszeitpunkt mit
dem zugehörigen `FileRecord` übereinstimmen. Die Projektion öffnet keine
Quelldatei. Sie ermittelt:

- vollständige Beobachtungs- und Byte-Summen je Format;
- Abdeckung durch konsistente `FILE_SHA256`-Evidence;
- Anzahl und Mitgliederumfang mehrfach belegter konsistenter `QUICK_FILE`-
  Gruppen sowie deren noch fehlende Vollhash-Evidence;
- vollständige Summen exakt gleicher `FILE_SHA256`-Gruppen und eine rein
  technische Schätzung potenziell redundanter Bytes.

Exact-Duplicate-Details werden nach potenziell redundanten Bytes und stabilen
Tie-Breakern priorisiert. Gruppen- und Mitgliederlimits begrenzen die private
Ausgabe; vollständige Summen und Kürzungsmarker bleiben erhalten. Sortierte
SQL-Streams mit festen Fetch-Batches halten den Speicherbedarf begrenzt. Rohe
Fingerprint-Werte verlassen die Query-Schicht nicht. Ein stabiler Gruppenbezug
wird aus Profil und Vollhash abgeleitet, ohne den Vollhash offenzulegen.

Der Workflow schreibt deterministische `inventory-report.json`,
`exact-duplicates.csv` und `checksums.sha256` außerhalb des Source Root. Die
privaten Artefakte dürfen relative Sammlungspfade enthalten; die CLI-
Zusammenfassung gibt keine Mitgliederpfade oder rohen Hashwerte aus. Der
Bericht erzeugt keine `Relation`, Confidence, Identitätsentscheidung,
Keep-Präferenz oder ausführbare Konsolidierungsaktion.

Die CLI `foliotone ebook-postscan-verify` rendert die erwarteten
Inventardateien für einen explizit adressierten Report-Identifier erneut im
Speicher und prüft Zielverzeichnis, Dateimenge, Checksummen und Bytes. Sie
verbindet diese Prüfung mit dem paketierten Schema-Head, dem neuesten
abgeschlossenen `ScanRun`, dem zugehörigen terminalen
`EbookCandidateHashRun` und einem expliziten begrenzten
`EbookCollectionRun`. Der Befehl verwendet SQLite `mode=ro`, öffnet keine
Source Media und gibt weder Artefaktpfade noch Report-Identifier, Dateinamen,
Fingerprint-Werte oder Lease-Token aus.

## Konsequenzen

- Ein abgeschlossener Scan liefert bereits vor einer vollständigen tiefen
  Collection-Analyse verwertbare Bestands-, Format-, Hash- und
  Speicherpotenzialübersichten.
- Der Bericht bleibt byte-stabil für denselben Snapshot und dieselben Limits.
- Die vollständige Postscan-Lineage kann ohne Source-Zugriff und ohne
  Datenbank-/Artefaktänderung maschinenlesbar verifiziert werden.
- Ein laufender Scan muss zuerst abgeschlossen oder als konsistenter
  abgeschlossener Snapshot bereitgestellt werden.
- Quick-Gruppen bleiben Kandidaten; nur gleiche vollständige SHA-256-Werte
  erscheinen als Exact-Duplicate-Evidence.
- Die Schätzung potenziell redundanter Bytes autorisiert keine Änderung an
  Source Media und ersetzt keine spätere Review-/Consolidation-Entscheidung.
- Für diese read-only Projektion ist keine neue Persistenzmigration nötig.
