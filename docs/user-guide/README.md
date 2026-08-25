# FolioTone Benutzeranleitung

**Stand:** 25. August 2026
**Produktoberfläche:** `local-single-operator/v1`

Diese Dokumentation beschreibt die lokale FolioTone-Oberfläche für genau einen
Benutzer. In der aktuellen Version ist ausschließlich die E-Book-Linie aktiv.
`MUSIC` und `IMAGE` werden in der Navigation als noch nicht aktiviert angezeigt,
besitzen aber keine eigenen Bedienabläufe.

## Der passende Einstieg

| Ziel | Dokument |
|---|---|
| FolioTone mit Docker, Podman oder Python installieren und das lokale Konto einrichten | [Installation und erster Start](INSTALLATION.md) |
| In kurzer Zeit einen ersten read-only E-Book-Bestand in der Oberfläche ansehen | [Schnellstart](SCHNELLSTART.md) |
| Alle Bereiche, Anzeigen und den begrenzten Rename-Ablauf verstehen | [Umfassendes Benutzerhandbuch](BENUTZERHANDBUCH.md) |
| Scans, Analysen, Berichte und erweiterte Abläufe im Terminal ausführen | [CLI-Referenz](CLI.md) |

Installation, Aktualisierung, Kontoeinrichtung und Start des lokalen Dienstes
stehen ausschließlich in der Installationsanleitung. Schnellstart und Handbuch
verweisen darauf, statt dieselben Schritte zu wiederholen. Die CLI-Referenz ist
die gemeinsame Quelle für Terminalbefehle, die derzeit noch zur Vorbereitung
der grafischen Oberfläche erforderlich sind.

## Aktueller Funktionsumfang

Die grafische Oberfläche kann vorhandene E-Book-Projektionen durchsuchen und
anzeigen. Dazu gehören Scanstatus, Inventar, `CollectionState`, `Library Health`,
Analyseabdeckung, Evidence, Reviews, nicht ausführbare Pläne, Jobs und Audit.
Der erste Scan und der Aufbau eines `CollectionState` werden derzeit noch über
die CLI gestartet.

Die Fixity-Surface ergänzt manuell gestartete Baseline- und
Verifikationsjobs, Status- und Ergebnisprojektionen, private Details sowie
append-only Reviews und Einzelrevisionen in CLI, REST und Browser.
`Library Health` und `ebook-postscan-verify` bleiben davon getrennte
Prüfungen. Fixity liest Source Media, öffnet aber keine W10- oder
Source-Write-Capability.

Die Bildschirmaufnahmen wurden mit einer eigens erzeugten synthetischen
E-Book-Datenbank aufgenommen. Sichtbare opaque IDs sind nur Beispiele für
diesen Dokumentationslauf und dürfen nicht in einen eigenen Workflow kopiert
werden. Die Bilder enthalten keine privaten Dateinamen, Pfade oder Medieninhalte.

Als einziger schreibender Browserablauf ist der bereits separat abgesicherte
Same-Parent-`FILE_RENAME` verfügbar. Er benennt genau eine Datei im vorhandenen
Ordner um. Er ist weder ein allgemeiner Datei-Manager noch eine Freigabe für
Verschieben, Löschen, Überschreiben, Reorganisation oder automatische
Metadatenkorrektur. Der EPUB-Titelwriter und die enge Interim-Quarantäne besitzen
nur CLI-Abläufe und keine Browser-Controls.

## Sicherheits- und Datenschutzgrenze

- Die Oberfläche ist nur unter einer expliziten Loopback-Adresse auf demselben
  Gerät erreichbar; Remote-, LAN- und Mehrbenutzerbetrieb sind nicht vorgesehen.
- Normale Ansichten zeigen keine absoluten Hostpfade, Passwörter, Sessionwerte,
  Capabilities oder private Jobinputs.
- Ein Scan liest Source Media. Er löscht, verschiebt, benennt und verändert keine
  E-Book-Datei.
- Reauthentisierung in der Oberfläche erzeugt nur einen kurzlebigen, eng
  begrenzten Grant. Sie ersetzt keine operation-spezifische Authorization oder
  Capability.
- Fehler- und Supportberichte dürfen keine privaten Dateinamen, Medieninhalte,
  absoluten Pfade, Datenbanken, Tokens oder Passwörter enthalten.
