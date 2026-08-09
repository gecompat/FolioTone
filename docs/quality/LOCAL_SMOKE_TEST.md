# Lokaler W2-Smoke-Test

**Status:** am 2026-08-09 lokal unter Windows/Docker Desktop erfolgreich ausgeführt  
**Scope:** read-only Incremental Index und Docker-Bootstrap

Dieser Test verwendet ausschließlich synthetische Dateien unter dem lokalen, von Git ignorierten Verzeichnis `media/ebooks`. Es werden keine realen E-Books benötigt. Der Test prüft den grundlegenden W2-Scanpfad, nicht die späteren calibre-, Matching- oder Entity-Resolution-Funktionen.

## Voraussetzungen

- aktueller FolioTone-Stand ist lokal ausgecheckt;
- Docker Compose ist verfügbar;
- das Repository ist das aktuelle Arbeitsverzeichnis;
- `data/` und `media/` bleiben lokale Runtime-Verzeichnisse und werden durch `.gitignore` ausgeschlossen.

## 1. Lokale Testverzeichnisse vorbereiten

PowerShell:

```powershell
New-Item -ItemType Directory -Force .\data | Out-Null
New-Item -ItemType Directory -Force .\media\ebooks | Out-Null
New-Item -ItemType Directory -Force .\media\music | Out-Null
Set-Content -Path .\media\ebooks\A.epub -Value 'alpha' -NoNewline
Set-Content -Path .\media\ebooks\B.epub -Value 'bravo' -NoNewline
```

Die Dateien besitzen absichtlich nur eine `.epub`-Endung. W2 prüft an dieser Stelle Dateierkennung, Zustandsänderungen und Hashing; eine EPUB-Inhaltsanalyse ist noch nicht Bestandteil dieses Tests.

## 2. Image bauen

```powershell
docker compose build
```

Erwartung: Der Build endet ohne Fehler.

## 3. Bootstrap prüfen

```powershell
docker compose run --rm foliotone status
```

Erwartung: FolioTone meldet den W2-Status und weist darauf hin, dass keine Source-Media-Mutation implementiert ist.

## 4. Ersten Scan ausführen

```powershell
docker compose run --rm foliotone scan `
  --name local-ebook-smoke `
  --path /media/ebooks `
  --media-type ebook `
  --hash quick `
  --suffix epub
```

Erwartete Kernausgabe:

```text
Status: COMPLETED
Observed files: 2
NEW: 2
```

## 5. Unveränderten zweiten Scan ausführen

Den Befehl aus Schritt 4 unverändert erneut ausführen.

Erwartete Kernausgabe:

```text
Status: COMPLETED
Observed files: 2
UNCHANGED: 2
```

Dieser Schritt bestätigt, dass der logische `ScanRoot` über die persistente SQLite-Datenbank wiederverwendet wird.

## 6. Änderung und fehlende Datei simulieren

```powershell
Set-Content -Path .\media\ebooks\A.epub -Value 'alpha-modified' -NoNewline
Remove-Item .\media\ebooks\B.epub
```

Danach den Scanbefehl aus Schritt 4 erneut ausführen.

Erwartete Kernausgabe:

```text
Status: COMPLETED
Observed files: 1
MODIFIED: 1
MISSING: 1
```

`MISSING` bedeutet ausdrücklich nicht automatisch `DELETED`. Dieser Basistest aktiviert die optionale `DELETED`-Bestätigung bewusst nicht. Ohne explizite Policy-Konfiguration bleibt auch wiederholt beobachtete Abwesenheit `MISSING`.

## 7. Datei wieder erscheinen lassen

```powershell
Set-Content -Path .\media\ebooks\B.epub -Value 'bravo' -NoNewline
```

Danach den Scanbefehl erneut ausführen.

Erwartete Kernausgabe:

```text
Status: COMPLETED
Observed files: 2
UNCHANGED: 1
REAPPEARED: 1
```

## 8. Read-only-Mount optional gegenprüfen

Der Compose-Vertrag bindet `/media/ebooks` read-only ein. Eine absichtliche Schreibprobe aus dem Container muss fehlschlagen:

```powershell
docker compose run --rm --entrypoint sh foliotone -lc "echo x >> /media/ebooks/A.epub"
```

Erwartung: Der Befehl endet mit einem Read-only-Fehler. Der Inhalt von `A.epub` darf sich dadurch nicht verändern.

## Optionale `DELETED`-Bestätigung

Seit `W2-004` kann `foliotone scan` eine konservative `DELETED`-Bestätigung ausdrücklich aktivieren. Die CLI verwendet dafür:

```text
--confirm-deleted-after-missing-scans <N>
--confirm-deleted-after-hours <H>
```

Die zweite Option ist optional und verwendet bei aktivierter Bestätigung standardmäßig 24 Stunden. Die Mindestanzahl erfolgreicher aufeinanderfolgender `MISSING`-Scans ist 2. Beide Bedingungen, Anzahl und verstrichene Zeit, müssen erfüllt sein. Failed oder interrupted Scans erhöhen die Bestätigungsserie nicht.

Diese Policy wird automatisiert in den Integrationstests geprüft. Sie wird im grundlegenden lokalen Smoke-Test nicht künstlich durch verkürzte Zeitfenster nachgestellt, weil dessen Zweck die plattformspezifische Docker-/Mount-Verifikation ist.

`DELETED` bezeichnet ausschließlich einen bestätigten Indexzustand. FolioTone löscht dadurch keine Datei; Source Media bleibt durch W9 read-only.

## 9. Ergebnis melden

Für die Rückmeldung genügen:

- Ausgabe von `docker compose build`, falls ein Fehler auftritt;
- Ausgabe von `foliotone status`;
- die vier Scan-Ausgaben aus den Schritten 4 bis 7;
- Ergebnis der optionalen Read-only-Prüfung;
- Betriebssystem, Docker-Engine und Docker-Compose-Version, falls ein plattformspezifisches Problem auftritt.

Keine realen Medienpfade, privaten Dateinamen oder Sammlungsinhalte müssen für diesen Test weitergegeben werden.

## Nicht Bestandteil dieses Tests

Noch nicht lokal geprüft werden:

- die opt-in `DELETED`-Bestätigung; sie ist automatisiert durch Integrationstests abgedeckt;
- Move-/Rename-Erkennung;
- Filename-/Path-Parsing;
- calibre, ffprobe, Chromaprint, beets, SongKong oder Picard;
- Entity Resolution, externe Provider, Matching und Review;
- jede Form von Source-Media-Schreiboperation.
