# CLI-Referenz für Endbenutzer

Die grafische Oberfläche ist der primäre Bedienweg. Diese Referenz bündelt die
Terminalbefehle, die für Installation, Scan, Analyse, Berichte und
operation-spezifische Administration weiterhin erforderlich sind. Sie
beschreibt ausschließlich die E-Book-Linie.

## Aufruf je Installationsart

Ein nativer Aufruf beginnt mit:

```text
foliotone <Befehl> <Optionen>
```

Im Docker-Container beginnt derselbe Aufruf mit:

```text
docker compose run --rm --no-deps foliotone <Befehl> <Optionen>
```

Im Podman-Container beginnt er mit:

```text
podman compose run --rm --no-deps foliotone <Befehl> <Optionen>
```

Die Containerbefehle verwenden standardmäßig `/data/foliotone.db` und sehen
den konfigurierten E-Book-Bestand read-only unter `/media/ebooks`. Native
Aufrufe benötigen den tatsächlichen Hostpfad zu Datenbank und Bestand. Nutze
in allen Fällen die für diesen Endpunkt passende Pfadwelt; vermische keine
Windows-Hostpfade mit Linux-Containerpfaden.

Zeige die aktuell verfügbaren Befehle und Optionen so an:

```text
foliotone --help
foliotone <Befehl> --help
```

Ersetze den nativen Launcher bei Docker oder Podman durch den oben gezeigten
Compose-Präfix. Passwörter, Bootstrap-Codes, Bestätigungen und private Locator
gehören nicht in eine Shell-History, ein Skript oder einen Supportbericht.

## GUI-Datenbasis vorbereiten

Die Browseroberfläche startet derzeit weder einen Scan noch den Aufbau eines
`CollectionState`. Dieser Abschnitt liefert den read-only Vorlauf für den
[Schnellstart](SCHNELLSTART.md).

### 1. E-Book-Bestand scannen

Wähle für `--name` einen dauerhaft stabilen logischen Namen. Ein erster Lauf
mit Quick Hash und den üblichen E-Book-Suffixen sieht nativ unter Windows
beispielsweise so aus:

```powershell
foliotone scan --name meine-ebooks --path "D:\Ebooks" --media-type ebook --database $FolioToneDatabase --hash quick --suffix epub --suffix mobi --suffix azw --suffix azw3 --suffix pdf
```

Nativ unter Linux:

```bash
foliotone scan --name meine-ebooks --path "/srv/ebooks" --media-type ebook --database "$FOLIOTONE_DATABASE_PATH" --hash quick --suffix epub --suffix mobi --suffix azw --suffix azw3 --suffix pdf
```

Mit Docker:

```text
docker compose run --rm --no-deps foliotone scan --name meine-ebooks --path /media/ebooks --media-type ebook --database /data/foliotone.db --hash quick --suffix epub --suffix mobi --suffix azw --suffix azw3 --suffix pdf
```

Mit Podman:

```text
podman compose run --rm --no-deps foliotone scan --name meine-ebooks --path /media/ebooks --media-type ebook --database /data/foliotone.db --hash quick --suffix epub --suffix mobi --suffix azw --suffix azw3 --suffix pdf
```

Notiere die ausgegebene opaque `ScanRun`-ID und die `ScanRoot`-ID. Nur ein
vollständig abgeschlossener E-Book-`ScanRun` kann den nächsten Schritt speisen.
Der Scan liest Dateien und persistiert Beobachtungen; er verändert keine
Source Media. `MISSING` oder `DELETED` sind Indexzustände und kein von diesem
Befehl ausgeführtes Löschen.

### 2. Unveränderlichen CollectionState bauen

Nativ:

```text
foliotone collection-state-build --scan-run-id <ScanRun-ID> --database <Datenbankpfad>
```

Mit Docker:

```text
docker compose run --rm --no-deps foliotone collection-state-build --scan-run-id <ScanRun-ID> --database /data/foliotone.db
```

Mit Podman:

```text
podman compose run --rm --no-deps foliotone collection-state-build --scan-run-id <ScanRun-ID> --database /data/foliotone.db
```

Notiere die ausgegebene `Snapshot-ID`. Sie wird in **Suche** und **Details**
der Browseroberfläche verwendet. Ein `CollectionState` ist an persistierte
Evidence gebunden und liest beim späteren Anzeigen keine Source Media.

### 3. Optional eine Collection-Analyse erzeugen

Für die Detailprojektionen **Analyse, Evidence und Reviews** ist zusätzlich
eine `CollectionRun-ID` erforderlich. Der kleinste Einstieg lautet:

```text
foliotone ebook-collection-analyze --help
```

Prüfe vor dem Lauf mit `ebook-tools-doctor`, welche optionalen ToolProvider
bereit sind. Der Containerweg verwendet dafür abweichend den spezialisierten
Dienst `foliotone-ebook`, wie in der
[Installationsanleitung](INSTALLATION.md#optionale-e-book-werkzeuge-prüfen)
beschrieben. Verwende die im Hilfetext geforderten IDs und Grenzen und notiere
die ausgegebene `CollectionRun-ID`. Ein `ScanRun`, ein `CollectionRun` und ein
`CollectionState` sind unterschiedliche Ressourcen und nicht austauschbar.

## Laufzeit und lokales Konto

| Befehl | Zweck | Wichtige Grenze |
|---|---|---|
| `auth-bootstrap` | einmaligen Code für das erste lokale Konto erzeugen | nur interaktives owner-lokales Terminal |
| `auth-reset` | Passwort des einzigen lokalen Kontos zurücksetzen | widerruft Sessions und Grants |
| `surface-api` | lokale REST-/Browseroberfläche starten | nativ nur explizites Loopback |
| `analysis-worker` | read-only Browserjobs abarbeiten | kein Netzwerk-Listener, `--once` für höchstens einen Job |
| `operator-worker` | operation-spezifische Writerjobs abarbeiten | nur mit exakt provisionierter Capability und Source-Grenze |
| `status` | implementierten Produktoberflächenstatus anzeigen | keine Readiness-Prüfung |

Start, Stopp, Compose-Profile und Kontoeinrichtung stehen zentral in der
[Installationsanleitung](INSTALLATION.md).

## Scan, Analyse und Tool-Readiness

| Befehl | Zweck |
|---|---|
| `ebook-tools-doctor` | calibre, Poppler, Java, EPUBCheck und Format-Readiness prüfen |
| `scan` | inkrementellen read-only Scan eines logischen `ScanRoot` ausführen |
| `ebook-metadata` | rohe E-Book-Metadaten und versionierte Candidates mit calibre lesen |
| `ebook-text` | EPUB-/MOBI-/AZW-/AZW3-Text read-only fingerprinten |
| `ebook-cover` | eingebettetes Cover read-only extrahieren und fingerprinten |
| `pdf-analyze` | PDF-Metadaten, Seitenzahl und Text mit Poppler lesen |
| `epub-validate` | EPUB mit EPUBCheck strukturell validieren |
| `ebook-analyze` | alle für eine Observation passenden read-only Analyzer ausführen |
| `ebook-collection-analyze` | abgeschlossenen Scan begrenzt und fortsetzbar analysieren |
| `ebook-collection-maintain` | Collection-Analyse, optionale Vollhashes und Inventar orchestrieren |
| `ebook-hash-candidates` | Quick-Hash-Candidates durch bounded Full SHA-256 bestätigen |
| `ebook-hash-status` | pfadfreien Fortschritt des Candidate-Hashings lesen |
| `ebook-postscan-verify` | abgeschlossene Hash-, Inventar- und Collection-Kette prüfen |

Ein Toolfehler verändert vorhandene Source Media nicht. Ein `NOT_READY` aus
dem Doctor ist eine fehlende Voraussetzung für abhängige Analysen, keine
Beschädigung der Datenbank.

## CollectionState, Suche und Berichte

| Befehl | Zweck |
|---|---|
| `collection-state-build` | unveränderlichen book-only Zustand aus einem abgeschlossenen Scan bauen |
| `collection-state-report` | einen persistierten `CollectionState` read-only anzeigen |
| `collection-state-diff` | zwei kompatible Snapshots vergleichen |
| `collection-search` | begrenzten `collection-query/v1`-Filter ausführen |
| `library-health-report` | mehrdimensionale `Library Health` lesen |
| `ebook-collection-report` | private deterministische JSON-/CSV-Berichte schreiben |
| `ebook-inventory-report` | Format-, Größen-, Hash- und Duplikatübersicht schreiben |
| `ebook-classification-report` | bounded Klassifikationsprojektion anzeigen |
| `calibre-reconciliation-report` | persistierte Calibre-Reconciliation lesen |
| `ebook-consolidation-report` | dauerhaft nicht ausführbaren ConsolidationPlan lesen |
| `ebook-metadata-correction-report` | dauerhaft nicht ausführbaren MetadataCorrectionPlan lesen |
| `ebook-operation-recipe-report` | dauerhaft nicht ausführbares OperationRecipe lesen |
| `archive-collection-status` | persistierten Archive-Collection-Lauf lesen |

Beispiel für eine pfadfreie EPUB-Suche:

```text
foliotone collection-search --snapshot <Snapshot-ID> --query "{\"where\":{\"field\":\"format\",\"operator\":\"EQ\",\"value\":\"EPUB\"}}" --database <Datenbankpfad>
```

`--private-details` ist ausschließlich für interaktive native Textausgabe
gedacht. JSON-Ausgabe bleibt private-detail-frei. Berichtsdateien können
private Sammlungsinformationen enthalten und gehören in das geschützte
Datenverzeichnis, nicht in Git oder Supportanhänge.

## Matching und Review

| Befehl | Zweck |
|---|---|
| `ebook-compare` | persistierte File-, Text-, Metadata-, Structure- und Cover-Evidence vergleichen |
| `ebook-match` | bounded Offline-Relation-Candidates für einen abgeschlossenen Scan persistieren |
| `ebook-match-review-list` | offene oder aufgeschobene Matching-Reviews pfadfrei auflisten |
| `ebook-match-review-decide` | optimistisch gefencete Reviewentscheidung anhängen |

Candidates, Scores und externe Toolergebnisse sind Evidence. Sie sind weder
allein kanonische Wahrheit noch eine Freigabe für eine Dateioperation.

## Operation-spezifische Writer

Die folgenden Befehle sind keine allgemeinen Dateiverwaltungsfunktionen. Sie
dürfen nur innerhalb der jeweils akzeptierten ADR, mit synthetisch oder
operativ freigegebenem Scope, exakten opaque IDs, zweiter Bestätigung,
Capability, Fencing, unmittelbarer Verifikation und Recoveryvertrag verwendet
werden.

| Kette | Befehle | Erlaubter enger Scope |
|---|---|---|
| Same-Parent-Rename | `ebook-rename-propose`, `ebook-rename-preview`, `ebook-rename-review`, `ebook-rename-plan`, `ebook-rename-authorize`, `ebook-rename-execute`, `ebook-rename-recover`, `ebook-rename-status` | genau eine byte-identische Datei im selben Ordner umbenennen |
| EPUB-3-Titelwriter | `metadata-write-authorize`, `metadata-write-execute`, `metadata-write-recover`, `metadata-write-status` | genau einen reviewten EPUB-3-Titelwert ersetzen |
| Interim-Quarantäne | `quarantine-authorize`, `quarantine-execute`, `quarantine-recover`, `quarantine-status` | genau eine ausdrücklich freigegebene Datei in die enge Quarantäne verschieben |

Ein nicht ausführbarer Plan wird nicht dadurch ausführbar, dass er in der CLI
oder Oberfläche angezeigt oder akzeptiert wurde. Beginne keinen Execute-Retry,
wenn Status oder Journal `RECOVERY_REQUIRED` melden. Verwende dann nur den
operation-spezifischen Recoverybefehl mit der exakten `Run-ID`.

Der Browser-Same-Parent-Rename benötigt beim Containerbetrieb zusätzlich das
administrative Overlay `compose.rename.yaml`. Es verlangt fail-closed eine
exakte Dependency-Scope-Datei, Capability-Datei und genau den autorisierten
schreibbaren `ScanRoot`. Die Bereitstellung dieser Werte ist ein
fortgeschrittener Operatorablauf und keine Voraussetzung für read-only Scan,
Suche oder Details.

### Container-Overlay für den Browser-Rename

Setze vor dem Start ausschließlich im lokalen Operator-Terminal diese drei
Variablen auf die bereits operation-spezifisch erzeugten Hostressourcen:

```text
FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE
FOLIOTONE_EBOOK_RENAME_CAPABILITIES_FILE
FOLIOTONE_EBOOK_RENAME_WRITABLE_ROOT
```

Für diese Bind-Quellen gilt dieselbe provider-spezifische Windows-Pfadform wie
für Daten- und E-Book-Verzeichnis in der Installationsanleitung. Prüfe und
starte den erweiterten `surface-api` mit Docker:

```text
docker compose -f compose.yaml -f compose.rename.yaml --profile local-surface --profile ebook-rename config --quiet
docker compose -f compose.yaml -f compose.rename.yaml --profile local-surface --profile ebook-rename up --detach --force-recreate surface-api
```

Mit Podman:

```text
podman compose -f compose.yaml -f compose.rename.yaml --profile local-surface --profile ebook-rename config
podman compose -f compose.yaml -f compose.rename.yaml --profile local-surface --profile ebook-rename up --detach --force-recreate surface-api
```

Nach jedem im Browser angelegten Authorize-, Execute- oder Recovery-Job
beansprucht genau ein separater Worker-Aufruf höchstens den nächsten passenden
Auftrag. Docker:

```text
docker compose -f compose.yaml -f compose.rename.yaml --profile ebook-rename run --rm --no-deps operator-worker
```

Podman:

```text
podman compose -f compose.yaml -f compose.rename.yaml --profile ebook-rename run --rm --no-deps operator-worker
```

Halte die drei Variablen bis zum `down` des Overlay-Projekts gesetzt, weil die
Compose-Auswertung sonst absichtlich abbricht. Kehre anschließend zum
read-only Basisprofil aus der Installationsanleitung zurück. Ersetze niemals
eine fehlende exakte Capability durch einen allgemeinen schreibbaren Mount.
