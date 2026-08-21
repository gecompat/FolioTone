# E-Book-Toolchain unter Windows bereitstellen

FolioTone stellt calibre, Poppler, Java und EPUBCheck Docker-first bereit. Der
Host benötigt keine separaten Installationen dieser Werkzeuge und keine
manuelle `PATH`-Konfiguration. Provisioning und Analyse bleiben getrennt.

## Voraussetzung

- Windows mit WSL2 oder einer nativen Docker-Laufzeit für Linux-Container;
- eine laufende Linux-Docker-Engine mit Architektur `x86_64`;
- Netzwerkzugriff ausschließlich für den erstmaligen Image-Build.

Der Windows-Docker-Dienst kann parallel für Windows-Container bestehen bleiben.
Das Skript verwendet ihn nur, wenn er tatsächlich `linux` meldet; andernfalls
wählt es eine WSL2-Distribution mit erreichbarer Linux-Docker-Engine.

## Explizites Provisioning

Im Repository-Stamm:

```powershell
pwsh -File .\scripts\provision-ebook-tools.ps1
```

Eine bestimmte WSL2-Distribution kann fest vorgegeben werden:

```powershell
pwsh -File .\scripts\provision-ebook-tools.ps1 `
    -DockerBackend Wsl `
    -WslDistribution Codex-Ubuntu-24.04
```

Das Skript baut `foliotone-ebook-tools:local` aus der eingecheckten Lockfile
und führt anschließend den Doctor ohne Netzwerk aus. Es installiert keine
Pakete auf Windows, verändert weder Registry noch `PATH` und startet keinen
Analysebefehl.

## Readiness prüfen

Direkt im Image:

```powershell
wsl.exe -d Codex-Ubuntu-24.04 -- docker run --rm `
    --network none --read-only --tmpfs /tmp --cap-drop ALL `
    --security-opt no-new-privileges `
    foliotone-ebook-tools:local ebook-tools-doctor
```

Maschinenlesbar:

```powershell
wsl.exe -d Codex-Ubuntu-24.04 -- docker run --rm --network none `
    foliotone-ebook-tools:local ebook-tools-doctor --json
```

Der Doctor meldet `READY` oder `NOT_READY` getrennt für EPUB, MOBI, AZW, AZW3
und PDF. Exitcode 0 bedeutet vollständige Readiness; Exitcode 2 zeigt fehlende
oder inkompatible Werkzeuge. Absolute Pfade werden nicht ausgegeben.

## Compose-Profil

Bei einer nativ erreichbaren Linux-Docker-Engine steht zusätzlich das optionale
Profil `ebook-tools` bereit:

```powershell
docker compose --profile ebook-tools run --rm `
    foliotone-ebook ebook-tools-doctor
```

Die Medienwurzel wird über `FOLIOTONE_EBOOKS_DIR` read-only nach
`/media/ebooks` eingebunden. Laufzeitdaten liegen über
`FOLIOTONE_DATA_DIR` unter `/data`. Das normale minimale `foliotone`-Image und
der Standard-Compose-Dienst bleiben unverändert.

## Fehlerbilder

- `The active native Docker engine is not a Linux engine`: Linux-Container-
  Backend aktivieren oder `-DockerBackend Wsl` verwenden.
- `No reachable Linux Docker engine was found in WSL2`: Docker in einer
  WSL2-Distribution installieren, starten und den Benutzer der Docker-Gruppe
  zuordnen.
- `NOT_READY`: den Image-Build erneut ausführen; Analysebefehle reparieren oder
  installieren bewusst nichts.

Architektur- und Distributionsgrenzen stehen in
[ADR-0057](../decisions/ADR-0057-docker-first-ebook-toolchain-provisioning.md).
