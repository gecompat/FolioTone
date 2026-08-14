# Bewertung der E-Book-Toolchain

Stand: 2026-08-14

Diese Bewertung schließt `W3-001` ab. Sie betrachtet nur dokumentierte,
automatisierbare und bis einschließlich W9 nicht mutierende Analysepfade. Die
Versionsangaben sind ein zeitgebundener Snapshot und müssen vor einem späteren
Upgrade oder einer neuen Integration erneut geprüft werden.

## Entscheidungsmatrix

| Werkzeug | geprüfter Stand | Lizenz | geeignete FolioTone-Rolle | Entscheidung |
|---|---:|---|---|---|
| calibre | 9.13.0 | GPL-3.0 | Metadaten aus EPUB, PDF, MOBI, AZW/AZW3 und weiteren Formaten; spätere optionale Library-Abfragen | `ebook-meta` für `W3-002` wiederverwenden; `calibredb` vorerst zurückstellen |
| EPUBCheck | 5.3.0 | BSD-3-Clause | EPUB-2-/EPUB-3-Konformität und strukturelle Fehler mit JSON-Report | für `W3-008` vormerken; nicht für Metadaten- oder Textextraktion verwenden |
| Poppler | 26.08.0 | GPL-2.0-or-later in den geprüften Frontend-Quellen; vor Redistribution komponentengenau prüfen | PDF-Metadaten, Seitenzahl und Text über `pdfinfo`/`pdftotext` | bevorzugter Kandidat für `W3-004`; noch kein Adapter in diesem Slice |
| qpdf | 12.4.0 | Apache-2.0 | PDF-Struktur, Integrität und maschinenlesbare JSON-v2-Repräsentation | optional ergänzend für strukturelle Evidence; nicht für Textextraktion |

MuPDF und FolioTone-native EPUB-/PDF-Parser werden zunächst nicht ausgewählt.
Calibre, EPUBCheck, Poppler und qpdf decken die aktuell geplanten Rollen besser
ab. Ein weiterer Spezialist wird erst bewertet, wenn ein konkreter, durch diese
Toolchain nicht erfüllter Vertrag vorliegt.

## calibre

### Wiederverwendete Fähigkeit

Die aktuelle calibre-Dokumentation beschreibt `ebook-meta ebook_file [options]`
als Lese-/Schreibwerkzeug für zahlreiche E-Book-Formate. Der FolioTone-Adapter
stellt deshalb keine frei konfigurierbaren Optionen bereit, sondern erlaubt nur
diese feste Befehlsform:

```text
ebook-meta <runtime-source-file> --to-opf metadata.opf
```

`--to-opf` schreibt die gelesenen Metadaten in eine OPF-Datei. Setter wie
`--title`, `--authors`, `--from-opf` oder andere Schreiboptionen sind nicht Teil
des Adaptervertrags. Der absolute Runtime-Pfad wird an den lokalen Prozess
übergeben, aber nicht persistiert. `ToolExecution.input_identity` enthält nur
die interne `FileObservation`-ID.

Der erste Slice normalisiert ausgewählte OPF-Werte als rohe `ToolResult`-Evidence
gegen genau diese `FileObservation`: Titel, Creator mit vorhandener Rolle,
Identifier mit vorhandenem Scheme, Sprache, Verlag, Datum, Subject und
Calibre-Series-Felder. Diese Werte sind weder kanonische Metadaten noch ein
Identity-Merge.

Offizielle Referenzen:

- https://manual.calibre-ebook.com/generated/en/ebook-meta.html
- https://manual.calibre-ebook.com/generated/en/cli-index.html
- https://github.com/kovidgoyal/calibre

### Verbindliche Sicherheitsuntergrenze

Die veröffentlichte Advisory `GHSA-2j4m-2q7x-2c47`/`CVE-2026-53511` bewertet
eine Code-Execution-Lücke beim Lesen manipulierter EPUB-, OPF- oder PDF-Metadaten
als `High`. Betroffen sind calibre-Versionen bis einschließlich 9.9.0; 9.10.0
ist als korrigierte Version ausgewiesen.

Der Adapter muss deshalb die erkannte Version **vor** dem Öffnen der Source-Datei
prüfen. Unbekannte Versionen und Versionen kleiner als 9.10.0 erzeugen eine
auditierbare `FAILED`-Ausführung ohne Medienanalyse. Sowohl Versionsabfrage als
auch Analyse verwenden ein ephemeres `CALIBRE_CONFIG_DIRECTORY`; globale
Calibre-Konfiguration und Plugins werden nicht als implizite Eingabe verwendet.
Zusätzlich setzt der Adapter `CALIBRE_ALLOW_PYTHON_TEMPLATES=0` als
Defense-in-Depth.

Zusätzliche Grenzen:

- das deklarierte OPF-Artefakt ist auf 4 MiB begrenzt und erhält Größe plus
  SHA-256;
- der Parser prüft Pfad, Größe und Digest des persistierten Artefakts;
- `DOCTYPE`- und `ENTITY`-Deklarationen werden abgewiesen;
- fehlende, zu große oder ungültige deklarierte Ausgaben machen einen sonst
  erfolgreichen Toollauf für diesen Adapter unbrauchbar;
- das Produktions-Deployment muss Source Media weiterhin read-only mounten;
  der lokale Befehlsvertrag allein ersetzt keine Betriebssystemgrenze.

Offizielle Advisory:

- https://github.com/kovidgoyal/calibre/security/advisories/GHSA-2j4m-2q7x-2c47

### `calibredb`

`calibredb list --for-machine` liefert JSON, und `show_metadata --as-opf` bietet
einen read-oriented Metadatenpfad. Dasselbe Programm enthält jedoch zahlreiche
mutierende Subcommands wie `add`, `remove`, `set_metadata` und
`embed_metadata`. Eine spätere Integration darf daher nur eine explizite
Read-Command-Allowlist besitzen.

Für `W3-002` ist `calibredb` nicht erforderlich: Der aktuelle Vertical Slice
analysiert konkrete `FileObservation`-Eingaben. Library Reconciliation gehört
inhaltlich zu W8. Bis dafür ein konkreter Vertrag und eine Test-Library vorliegen,
wird kein `calibredb`-Adapter implementiert.

Offizielle Referenz:

- https://manual.calibre-ebook.com/generated/en/calibredb.html

### Lizenz- und Distributionsgrenze

calibre ist GPL-3.0. FolioTone ruft in diesem Slice eine separat installierte CLI
als Prozess auf und übernimmt keine calibre-Quellen in das Repository. Eine
spätere Verteilung eines Images oder Installationspakets mit gebündeltem calibre
muss Lizenztexte, Source-Angebot und weitere Distributionspflichten separat
prüfen. Dieser Slice trifft keine Bundling-Entscheidung.

## EPUBCheck

EPUBCheck 5.3.0 ist laut Upstream die aktuelle produktionsreife Version für EPUB
2 und EPUB 3. Das von DAISY im Auftrag des W3C gepflegte Projekt bietet CLI,
Java-Library, Container und JSON-Ausgabe. Diese Schnittstelle ist für
strukturelle Konformitäts-Evidence deutlich geeigneter als eine native
FolioTone-Neuimplementierung.

EPUBCheck liest weder die fachlichen Metadaten für den ersten Slice noch liefert
es einen normalisierten Buchtext-Fingerprint. Es wird deshalb für `W3-008`
vorgemerkt und blockiert `W3-002`/`W3-003` nicht.

Offizielle Referenzen:

- https://github.com/w3c/epubcheck
- https://github.com/w3c/epubcheck/releases/tag/v5.3.0

## Poppler

Poppler 26.08.0 ist der aktuelle stabile Upstream-Stand. Für `W3-004` sind vor
allem die etablierten CLI-Utilities relevant:

- `pdfinfo` für technische Metadaten und Seitenzahl;
- `pdftotext` für begrenzte Textextraktion und die explizite Erkennung eines
  PDFs ohne extrahierbaren Text.

Die Werkzeuge werden nicht in `W3-002` benötigt. Vor Implementierung sind ihre
konkreten Exitcodes, Zeichencodierung, Ausgabegrenzen und das Verhalten bei
verschlüsselten oder beschädigten PDFs mit synthetischen Fixtures festzulegen.
Vor einer gebündelten Distribution ist die Lizenzlage der tatsächlich
ausgelieferten Poppler-Komponenten und Abhängigkeiten nochmals zu prüfen.

Offizielle Referenzen:

- https://poppler.freedesktop.org/
- https://poppler.freedesktop.org/api/cpp/poppler-global_8h_source.html

## qpdf

qpdf 12.4.0 ist aktiv gepflegt und unter Apache-2.0 verfügbar. Seit qpdf 11 kann
CLI/API eine vollständige JSON-v2-Repräsentation der PDF-Objekte erzeugen. Die
Dokumentation stellt zugleich klar, dass qpdf keine Textextraktion und keine
inhaltliche Dokumentstruktur liefert.

qpdf ist daher ein optionaler zweiter Provider für PDF-Struktur-/Integritäts-
Evidence. Poppler bleibt der bevorzugte Kandidat für Seiten-/Textanalyse. Falls
qpdf später integriert wird, darf der Adapter nur reine Inspektionsoptionen
freigeben; JSON-Input-/Update- und Output-Rewrite-Pfade bleiben durch W9
verboten.

Offizielle Referenzen:

- https://github.com/qpdf/qpdf/releases/tag/v12.4.0
- https://qpdf.readthedocs.io/en/latest/json.html
- https://github.com/qpdf/qpdf/blob/main/LICENSE.txt

## Verifizierter `W3-002`-Slice

Am 2026-08-14 wurde calibre 9.13.0 als separates administratives Abbild außerhalb
des Repositorys installiert. Das offizielle MSI hatte den erwarteten
SHA-256-Wert
`F5F19E870163C20EC63A656D6F5D0C123E07C4254899380EBEEC51B00766E615` und eine
gültige Signatur von Kovid Goyal.

Ein lokaler End-to-End-Smoke-Test verwendete ausschließlich ein synthetisches
EPUB. `foliotone scan` erzeugte eine `FileObservation`; danach lieferte
`foliotone ebook-metadata` eine erfolgreiche `ToolExecution`, ein geprüftes
`CALIBRE_OPF`-Artefakt und sechs persistierte rohe Metadatenbeobachtungen. Das
ephemere Work-Verzeichnis war nach dem Lauf leer. Es wurden keine echten Medien
und keine Calibre-Library verwendet.
