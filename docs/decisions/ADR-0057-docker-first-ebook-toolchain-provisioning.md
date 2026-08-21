# ADR-0057: Docker-first-Bereitstellung der E-Book-Toolchain

- Status: Accepted
- Datum: 2026-08-21

## Kontext

Die implementierten E-Book-Adapter benötigen calibre (`ebook-meta`,
`ebook-convert`, `calibre-debug`), Poppler (`pdfinfo`, `pdftotext`), Java und
EPUBCheck. Eine frische Windows-Umgebung stellte diese Werkzeuge bislang nicht
reproduzierbar bereit. Manuelle Installationen und lokale `PATH`-Änderungen
erzeugen uneinheitliche Versionen und verdecken fehlende Laufzeitvoraussetzungen.

Analysebefehle dürfen weder Pakete installieren noch Images bauen oder aus dem
Netz laden. Toolbereitstellung ist eine administrative, explizite Operation.

## Entscheidung

FolioTone erhält ein optionales, projekt-eigenes `linux/amd64`-Image für die
vollständige E-Book-Toolchain. Windows verwendet Docker mit Linux-Container-
Backend, direkt oder über eine vorhandene WSL2-Distribution. Eine native
Installation der Spezialwerkzeuge auf dem Host ist nicht erforderlich.

Das Profil `ebook-toolchain-linux-amd64/v1` bindet:

- das Basisimage per Plattform-Manifest-Digest;
- einen datierten Debian-Snapshot;
- calibre 9.13.0, Poppler 26.07.0, Temurin JRE 21.0.12+8 und EPUBCheck 5.3.0;
- URL, Archivname, Bytelänge und SHA-256 jedes Upstream-Artefakts.

Der Build lädt nur die Lockfile-Einträge über HTTPS, prüft Größe und SHA-256
vor dem Entpacken und verwirft Traversal- oder Link-Fluchtversuche. Poppler
wird aus dem gelockten Quellarchiv nur mit den benötigten Utilities gebaut.
Lizenzhinweise und Lockfile werden in das Image übernommen. Das Rezept baut
lokal; diese Entscheidung autorisiert keine Veröffentlichung eines fertigen
Images. Vor Redistribution sind Lizenzen, Quellangebot und Abhängigkeiten
separat zu prüfen.

Der explizite Windows-Einstieg ist `scripts/provision-ebook-tools.ps1`. Er
verwendet eine erreichbare native Linux-Docker-Engine oder findet eine
WSL2-Distribution mit laufender Linux-Docker-Engine. Eine Windows-Container-
Engine wird nicht akzeptiert. Nach dem Build läuft der Doctor offline, mit
read-only Root-Dateisystem, leerem Netzwerk, `cap-drop=ALL` und
`no-new-privileges`.

`foliotone ebook-tools-doctor` führt ausschließlich begrenzte, feste
Versionsabfragen aus. Er öffnet weder Medien noch Datenbank, installiert oder
aktualisiert nichts und liefert eine pfadfreie Projektion unter
`ebook-toolchain-doctor/v1`. Die Readiness wird getrennt ausgewiesen:

- EPUB: drei calibre-Programme, Java und EPUBCheck;
- MOBI, AZW und AZW3: drei calibre-Programme;
- PDF: `pdfinfo` und `pdftotext`.

Fehlende, nicht erkennbare oder zu alte Komponenten ergeben `NOT_READY` und
Exitcode 2. Alle bisherigen Analysebefehle bleiben unverändert und lösen
niemals Provisioning aus.

## Folgen

Eine frische Windows-Umgebung benötigt nur WSL2 oder eine andere erreichbare
Linux-Docker-Laufzeit sowie Netzwerkzugriff während des expliziten Builds.
Danach kann der Doctor vollständig offline ausgeführt werden. Source Media
wird im Compose-Profil read-only eingehängt; `/data` bleibt der einzige
persistente Schreibbereich. Native Hostinstallationen bleiben möglich, gelten
aber als `UNMANAGED_LOCAL` und müssen denselben Doctor-Vertrag erfüllen.
