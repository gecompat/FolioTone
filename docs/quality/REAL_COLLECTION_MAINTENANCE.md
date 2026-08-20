# Reale E-Book-Collection: Wartungs- und Analyse-Workflow

Ziel dieses Leitfadens ist eine fortsetzbare, read-only Inventarisierung und technische Analyse für eine große private E-Book-Sammlung mit kontrollierter I/O- und Resume-Strategie.

## Annahmen

- `foliotone` läuft entweder direkt im Repo-Venv oder über `docker compose run --rm foliotone`.
- Der Sammlungsordner ist lokal oder als Netzlaufwerk eingebunden. Die Beispiele
  verwenden den neutralen Platzhalter `X:\Books`.
- `ScanRoot`-Name bleibt stabil, damit `resume` auf derselben Logik arbeitet.
- Für reale Daten werden nur Pfadinformationen aus der Sammlung intern verarbeitet; in Logs und Ausgaben werden keine absoluten Medienpfade ausgegeben.

## 1) Initialer Read-only Scan

Erzeuge zuerst/erneuere den `ScanRoot` mit einem vollständigen Scan:

```powershell
foliotone scan `
  --name real-ebooks `
  --path X:\Books `
  --media-type ebook `
  --hash quick `
  --database C:\rep\artifacts\FolioTone\real-ebook\foliotone.db `
  --suffix epub `
  --suffix mobi `
  --suffix azw `
  --suffix azw3 `
  --suffix pdf
```

Hinweise:

- Wenn der Scan nicht abgeschlossen werden kann, wird mit `INTERRUPTED` sauber
  resumierbar.
- Auf einer interaktiven Konsole zeigt `foliotone scan` standardmäßig einen
  pfadfreien Datei-, Datenmengen- und Durchsatzfortschritt. `--no-progress`
  deaktiviert ihn; `--progress` erzwingt ihn auch bei umgeleiteter Ausgabe.
- `--hash-workers auto` ist der Default. Eine Zahl von 1 bis 8 bleibt für eine
  gezielte Begrenzung möglich. Die Batchgröße bleibt standardmäßig 256 und wird
  nicht allein aus dem momentanen Dateidurchsatz abgeleitet.
- Pfad- und Datenbankparameter sollten auf einen dauerhaften, privaten Pfad in `C:\rep`
  zeigen.

## 2) Wartungsrunde mit Analyse + optionalen Folgeberichten

Für große Mengen arbeitet `ebook-collection-maintain` mit festen Blöcken:

```powershell
foliotone ebook-collection-maintain `
  --root X:\Books `
  --scan-root real-ebooks `
  --database C:\rep\artifacts\FolioTone\real-ebook\foliotone.db `
  --artifact-root C:\rep\artifacts\FolioTone\real-ebook\tool-artifacts `
  --work-root C:\rep\tmp\FolioTone\real-ebook\tool-work `
  --workers 2 `
  --plan-per-format 500 `
  --max-items 2000 `
  --run-hash-candidates `
  --hash-workers 2 `
  --hash-max-items 500 `
  --run-inventory-report `
  --inventory-report-root C:\rep\artifacts\FolioTone\real-ebook\inventory-reports `
  --run-collection-report `
  --collection-report-root C:\rep\artifacts\FolioTone\real-ebook\collection-reports
```

Wichtige Punkte:

- `--max-items` begrenzt die aktuelle Invoke-Last.  
- Bei `Status: INTERRUPTED` wird nur ein Teil der Zielmenge bearbeitet; anschließend mit
  `--resume-last-interrupted` weiterlaufen.
- `--run-collection-report` ist nur nach nicht-interrupteten Collection-Läufen sinnvoll.
  Bei Unterbrechung wird das in der Ausgabe klar signalisiert.

## 3) Fortsetzen nach Unterbrechung

Nach einem unterbrochenen Lauf:

```powershell
foliotone ebook-collection-maintain `
  --root X:\Books `
  --scan-root real-ebooks `
  --database C:\rep\artifacts\FolioTone\real-ebook\foliotone.db `
  --artifact-root C:\rep\artifacts\FolioTone\real-ebook\tool-artifacts `
  --work-root C:\rep\tmp\FolioTone\real-ebook\tool-work `
  --resume-last-interrupted `
  --max-items 2000 `
  --workers 2
```

Optionaler Schritt:

- `--run-hash-candidates --hash-workers 4 --hash-max-items 1000`
- oder `--run-inventory-report --inventory-report-root ...`
- oder `--run-collection-report --collection-report-root ...`

## 4) Sicherheitsregeln

- Source-Pfade werden in Konsolen- und JSON-Berichten nicht als vollständige absolute
  Pfade propagiert.
- `work-root` und `artifact-root` sollten **nicht** unterhalb von `--root` liegen.
- Externe Tools müssen vorhanden sein, damit Analysen vollständig durchlaufen; fehlt ein Tool,
  bleiben bereits erfasste Daten unverändert, der Lauf endet als `COMPLETED_WITH_FAILURES`.

## 5) Ergebnis-Status in der Praxis

- `COMPLETED`: Durchlauf vollständig ohne harte Fehler.
- `COMPLETED_WITH_FAILURES`: Teilfehler, aber fortsetzbar weiter nutzbar; erneutiger Lauf ist sinnvoll.
- `INTERRUPTED`: Ausführung abgebrochen; nur wiederaufnehmbare Fortschritte vorhanden.

Für einen großen Bestand werden in dieser Weise mehrere Durchläufe empfohlen:  
kleine `--max-items` starten, dann in Folgeaufrufen hochskalieren.
