# Bewertung der E-Book-Toolchain

Stand: 2026-08-21

Diese Bewertung schloss `W3-001` ab und dokumentiert zusätzlich die in
`W3-002` bis `W3-009` implementierten calibre-, Poppler-, EPUBCheck- und
Pillow-Verträge. Sie betrachtet nur dokumentierte, automatisierbare und bis
einschließlich W9 nicht mutierende Analysepfade. Die Versionsangaben sind ein
zeitgebundener Snapshot und müssen vor einem späteren Upgrade oder einer neuen
Integration erneut geprüft werden.

## Entscheidungsmatrix

| Werkzeug | geprüfter Stand | Lizenz | geeignete FolioTone-Rolle | Entscheidung |
|---|---:|---|---|---|
| calibre | 9.13.0 | GPL-3.0 | Metadaten aus mehreren Formaten; EPUB/MOBI/AZW/AZW3-Text- und Embedded-Cover-Extraktion; spätere optionale Library-Abfragen | `ebook-meta` für `W3-002`/`W3-005`/`W3-006`, `ebook-convert` für `W3-003`/`W3-005` und einen festen `calibre-debug -e`-Helper für `W3-009` wiederverwenden; direkten `ebook-meta --get-cover`-Pfad und `calibredb` vorerst zurückstellen |
| Pillow | 12.3.0 | MIT-CMU | begrenzte Rasterdekodierung, EXIF-Orientierung, Graustufen- und Lanczos-Normalisierung | für `W3-009` wiederverwenden; dHash-Vertrag und Versionierung bleiben FolioTone-eigen |
| ImageHash | 4.3.2 | BSD-2-Clause | mehrere perzeptuelle Bildhash-Verfahren | nicht übernehmen: der kleine feste dHash benötigt keine zusätzlichen NumPy-/SciPy-/PyWavelets-Abhängigkeiten |
| EPUBCheck | 5.3.0 | BSD-3-Clause | EPUB-2-/EPUB-3-Konformität und strukturelle Fehler mit JSON-Report | mit `epubcheck-json/1` für `W3-008` implementiert; nicht für Metadaten- oder Textextraktion verwenden |
| Poppler | 26.07.0 | GPL-2.0-or-later in den geprüften Frontend-Quellen; vor Redistribution komponentengenau prüfen | PDF-Metadaten, Seitenzahl und Text über `pdfinfo`/`pdftotext` | für `W3-004` als zwei feste CLI-Adapterpfade implementiert |
| qpdf | 12.4.0 | Apache-2.0 | PDF-Struktur, Integrität und maschinenlesbare JSON-v2-Repräsentation | optional ergänzend für strukturelle Evidence; nicht für Textextraktion |

MuPDF und FolioTone-native EPUB-/PDF-Parser werden zunächst nicht ausgewählt.
Calibre, EPUBCheck, Poppler und qpdf decken die aktuell geplanten Rollen besser
ab. Ein weiterer Spezialist wird erst bewertet, wenn ein konkreter, durch diese
Toolchain nicht erfüllter Vertrag vorliegt.

## Bereitstellungsentscheidung

ADR-0057 entscheidet die operative Lücke Docker-first. Das optionale
`ebook-toolchain-linux-amd64/v1`-Image enthält exakt die bewerteten calibre-,
Poppler- und EPUBCheck-Versionen sowie Temurin JRE 21.0.12+8. Upstream-Archive,
Basisimage und Debian-Snapshot sind gelockt; das PowerShell-Provisioning nutzt
unter Windows eine Linux-Docker-Engine direkt oder über WSL2.

`foliotone ebook-tools-doctor` übernimmt die nicht mutierende Vorabprüfung und
meldet Readiness für EPUB, MOBI, AZW, AZW3 und PDF. Er ersetzt weder die
adaptereigene Prüfung unmittelbar vor dem Öffnen einer Source noch persistierte
`ToolExecution`-Provenance. Analysebefehle lösen niemals Provisioning aus.

Das Repository enthält nur Rezept, Lockfile und Hinweise, keine Drittanbieter-
Binaries. Ein fertiges Image wird nicht publiziert; Redistribution benötigt
eine separate komponentengenaue Lizenz- und Source-Offer-Prüfung.

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
gegen genau diese `FileObservation`. `W3-006` erweitert Adapter und Parser auf
`ebook-meta-opf/2`: Provider-nahe `calibre_metadata`-Beobachtungen bleiben
erhalten; zusätzlich projiziert der provider-neutrale Vertrag
`ebook-metadata-candidate/v1` OPF-2-Attribute und OPF-3-Refinements.

Stabile Feldpfade gruppieren Identifier-Namespace/-Wert, Contributor-Name,
Quelle, MARC-Relator-Rolle und Sortiername sowie Serienname/-position. Direkte
Felder umfassen Titel, Sprache, Verlag, Publikationsdatum, Subject,
Beschreibung, Rechte, Typ, Titelsortierung und calibre-Rating, soweit
vorhanden. Explizite ISBN-Schemes, `urn:isbn` und die ONIX-Codelist-5-Werte 02
und 15 werden als ISBN-Namespace abgebildet; der Identifierwert bleibt als
Evidence unverändert. Die unterstützten MARC-Relator-Codes sind `aut`, `bkp`,
`ctb`, `edt`, `ill`, `nrt`, `oth` und `trl`. Andere Rollen/Schemes werden
beobachtet, aber nicht geraten.

Jeder Kandidat verweist auf dieselbe konkrete `FileObservation` und die exakte
`ToolExecution`; Profil und OPF-Quellposition stehen in der Erklärung. Eine
Confidence von 1,0 beschreibt die direkte Projektion, nicht die Richtigkeit
oder Kanonizität des Quellwerts. Der Slice legt keine `Agent`-, `Work`-,
`Edition`-, `Series`- oder `SeriesMembership`-Identität an und führt keinen
Identity-Merge aus.

Offizielle Referenzen:

- https://manual.calibre-ebook.com/generated/en/ebook-meta.html
- https://manual.calibre-ebook.com/generated/en/cli-index.html
- https://github.com/kovidgoyal/calibre
- https://www.w3.org/TR/epub-33/
- https://www.loc.gov/marc/relators/relacode.html
- https://github.com/kovidgoyal/calibre/blob/master/src/calibre/ebooks/metadata/opf3.py

### EPUB/MOBI/AZW/AZW3-Text und FolioTone-Fingerprint

`W3-003` verwendet die dokumentierte `ebook-convert`-Schnittstelle, weil
calibre EPUB-Spine, Markup und Zeichencodierung bereits formatgerecht in eine
TXT-Repräsentation überführt. FolioTone implementiert deshalb keinen parallelen
EPUB-Parser. `W3-005` verwendet dieselbe dokumentierte Schnittstelle für MOBI,
AZW und AZW3, statt formatspezifischen Code hinzuzufügen. Adapterversion
`ebook-convert-text/2` akzeptiert ausschließlich eine zuvor persistierte,
unveränderte EPUB-, MOBI-, AZW- oder AZW3-`FileObservation` und besitzt diese
feste Befehlsform:

```text
ebook-convert <runtime-source-file> content.txt
  --txt-output-formatting=plain
  --txt-output-encoding=utf-8
  --newline=unix
  --max-line-length=0
```

Aufrufende Komponenten können keine zusätzlichen Konvertierungs- oder
Schreiboptionen übergeben. Die Ausgabe wird als privates `CALIBRE_TEXT`-
`ToolArtifact` mit maximal 64 MiB, Größe und SHA-256 übernommen. Der Rohtext
wird weder als `ToolResult` noch über die CLI ausgegeben. Er bleibt im
konfigurierten Runtime-Artefaktbereich außerhalb des Repositorys.

calibre liefert keinen FolioTone-kompatiblen Inhalts-Fingerprint. Diese Lücke
schließt FolioTone nach der Artefakt-Integritätsprüfung mit einer eigenen,
versionierten Ableitung:

1. strikt als UTF-8 decodieren und einen optionalen führenden BOM entfernen;
2. Unicode-Normalisierung `NFKC` anwenden;
3. alle Unicode-Whitespace-Folgen auf genau ein Leerzeichen reduzieren und
   äußeren Whitespace entfernen;
4. SHA-256 über die UTF-8-Repräsentation des normalisierten Textes berechnen.

Der `Fingerprint` besitzt den Kind-Wert `EBOOK_NORMALIZED_TEXT`, verweist auf
die konkrete `FileObservation` und `ToolExecution` und speichert als
`algorithm_version` das Profil
`unicode-nfkc-whitespace-v1+ucd-<Unicode-Datenversion>`. Ein Wechsel der
Unicode-Datenversion, des Adapterprofils oder der calibre-Version macht die
Ableitung über die vorhandenen Reanalyse-Verträge selektiv veraltet.

`ToolResult` speichert `text_status = TEXT_EXTRACTED` oder `NO_TEXT` sowie
`normalized_character_count`. Bei `NO_TEXT` entsteht bewusst kein Fingerprint.
Der Fingerprint beschreibt nur den durch calibre extrahierbaren Plaintext in
der von calibre bestimmten Lesereihenfolge. Layout, CSS, Bilder, Linkziele,
OCR und nicht extrahierbarer Bildtext gehören nicht zu diesem Vertrag.

KFX, AZW1, AZW4 und weitere Formate sind nicht Teil der expliziten Text-
Allowlist. Calibre unterstützt laut eigener Dokumentation keine DRM-Entfernung.
FolioTone ergänzt weder Entschlüsselung noch DRM-Umgehung. Geschützte,
beschädigte oder anderweitig nicht konvertierbare Dateien bleiben
fehlgeschlagene `ToolExecution`-Records ohne Textstatus oder Fingerprint. Nur
eine erfolgreiche Konvertierung mit leerem normalisiertem Inhalt ist
`NO_TEXT`.

Offizielle Referenz:

- https://manual.calibre-ebook.com/generated/en/ebook-convert.html
- https://manual.calibre-ebook.com/drm.html

### EPUB/MOBI/AZW/AZW3-Embedded-Cover und FolioTone-dHash

`W3-009` verwendet die dokumentierte Fähigkeit von `calibre-debug`, ein festes
Standalone-Skript über `-e` auszuführen. Der paketierte Helper akzeptiert nur
die vom Adapter gesetzten Argumente, kopiert die konkrete Source-Observation
zuerst in den privaten Workspace und übergibt ausschließlich diese Kopie an den
calibre-Metadatenreader. Für EPUB wird `allow_rendered_cover=False` gesetzt.
Damit bezeichnet ein extrahiertes Raster tatsächlich ein eingebettetes Cover;
eine sonst von calibre gerenderte erste Seite wird nicht als Cover-Evidence
missverstanden.

Der scheinbar einfachere dokumentierte `ebook-meta --get-cover`-Pfad erfüllt
den Vertrag nicht. Ohne `--disallow-rendered-cover` erzeugt calibre für ein
coverloses EPUB ein gerendertes Titelbild. Der lokale calibre-9.13-Test zeigte,
dass die zusätzliche Option von `ebook-meta` zugleich als schreibende Option
klassifiziert wird und die Eingabe neu serialisieren kann. Selbst eine
nachgelagerte Hashprüfung wäre dafür keine ausreichende Schutzgrenze. Der
implementierte Helper lässt den calibre-Reader deshalb nur auf der ephemeren
Kopie arbeiten und verwendet `ebook-meta` nicht.

Der Helper liefert ein erforderliches, maximal 1 KiB großes JSON-Ergebnis mit
`COVER_EXTRACTED` oder `NO_EMBEDDED_COVER`, Covergröße und SHA-256 der
gestagten Source. FolioTone vergleicht den Digest nach dem Prozess erneut mit
der unveränderten `FileObservation`. Das optionale Cover ist auf 32 MiB
begrenzt und bleibt privates `CALIBRE_EMBEDDED_COVER`-`ToolArtifact`.

Pillow 12.3.0 ist die einzige neue Runtime-Abhängigkeit. Zugelassen sind JPEG,
PNG, WebP und GIF bis 40 Megapixel; Decompression-Bomb-Warnungen werden als
Fehler behandelt. FolioTone verwendet den EXIF-orientierten ersten Frame,
konvertiert ihn nach Graustufen und skaliert mit Lanczos auf 9 x 8 Pixel. Acht
horizontale Vergleiche pro Zeile ergeben den 64-Bit-`dhash-64`. Das Profil
`horizontal-luma-9x8-lanczos-v1+pillow-<version>` macht sämtliche
reproduktionsrelevanten Entscheidungen sichtbar.

ImageHash 4.3.2 wurde geprüft, aber nicht als Abhängigkeit aufgenommen. Das
Paket implementiert deutlich mehr Verfahren und deklariert NumPy, SciPy,
Pillow und PyWavelets; für den bewusst kleinen dHash-Vertrag wären drei davon
unnötig. Ein späterer Bedarf an pHash, Wavelet-, Farb- oder crop-resistentem
Hashing erfordert eine neue Bewertung und ein neues `algorithm_version`-
Profil. Der aktuelle dHash ist ausschließlich unterstützende Evidence und
kein automatischer Datei-, `Edition`- oder `Work`-Identitätsbeweis.

Offizielle Referenzen:

- https://manual.calibre-ebook.com/generated/en/calibre-debug.html
- https://manual.calibre-ebook.com/generated/en/ebook-meta.html
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/metadata/cli.py
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/metadata/epub.py
- https://pypi.org/project/pillow/
- https://pillow.readthedocs.io/en/stable/reference/Image.html
- https://github.com/JohannesBuchner/imagehash
- https://github.com/JohannesBuchner/imagehash/blob/master/setup.py

### Verbindliche Sicherheitsuntergrenze

Die veröffentlichte Advisory `GHSA-2j4m-2q7x-2c47`/`CVE-2026-53511` bewertet
eine Code-Execution-Lücke beim Lesen manipulierter EPUB-, OPF- oder PDF-
Metadaten als `High`. Betroffen sind calibre-Versionen bis einschließlich
9.9.0; 9.10.0 war für diesen Befund die korrigierte Version. Die neuere
Advisory `GHSA-4f7g-rjfp-hmvx`/`CVE-2026-73248` betrifft jedoch Versionen bis
einschließlich 9.11.0 und ist erst ab 9.12.0 behoben. Sie konnte die Sperre für
Python-Templates umgehen.

Der Adapter muss deshalb die erkannte Version **vor** dem Öffnen der Source-Datei
prüfen. Unbekannte Versionen und Versionen kleiner als 9.12.0 erzeugen eine
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
- https://github.com/kovidgoyal/calibre/security/advisories/GHSA-4f7g-rjfp-hmvx

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

### calibre Book-Diff

Die dokumentierte Schnittstelle `calibre-debug --diff file1 file2` startet das
calibre-Diff-Werkzeug aus dem GUI-Modul. Sie besitzt keinen dokumentierten
headless JSON-, Report- oder stabilen Exitcode-Vertrag. Der am 2026-08-15
lokal geprüfte Aufruf mit calibre 9.13 bestätigt nur die GUI-orientierte
`--diff`-Option; er stellt keine automatisierbare Evidence-Schnittstelle bereit.

FolioTone implementiert deshalb keinen `calibre-debug --diff`-Adapter. Der
spätere Inhaltsvergleich soll provider-neutrale, bereits persistierte Evidence
wie Datei-Hashes, normalisierte Text-Fingerprints, Metadatenkandidaten,
Strukturdiagnosen und Cover-Fingerprints vergleichen. Damit bleibt die
Matching-Erklärung versionierbar und hängt nicht von einem interaktiven
Diff-Renderer ab. Das calibre-Diff-Werkzeug kann unabhängig davon für manuelle
Einzelfallprüfung nützlich sein.

Offizielle Referenzen:

- https://manual.calibre-ebook.com/generated/en/calibre-debug.html
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/debug.py

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

`W3-008` implementiert Adapterversion `epubcheck-json/1` und den CLI-Befehl
`foliotone epub-validate`. Der Adapter akzeptiert nur EPUB und verwendet diese
feste Befehlsform:

```text
java -Djava.awt.headless=true -Djava.io.tmpdir=. -jar epubcheck.jar
  <runtime-source-file> --json report.json --locale en
```

Die JAR-Datei und das Java-Executable sind konfigurierbare
Runtime-Abhängigkeiten; zusätzliche EPUBCheck-Optionen sind nicht exponiert.
EPUBCheck 5.3.0 ist die Schemaprofil-Untergrenze. Die Source-Datei muss vor und
nach dem Toollauf noch exakt zur persistierten `FileObservation` passen.

Der JSON-Report ist auf 8 MiB und 10.000 Meldungen begrenzt. Er wird als
privates `EPUBCHECK_JSON`-`ToolArtifact` mit Größe und SHA-256 persistiert.
Der Parser verifiziert Dateiname, Tool-/Reportversion, Count-Felder,
Severity-Allowlist und Diagnose-ID-Form. `ToolResult` enthält ausschließlich:

- `conformance_status = CONFORMANT` oder `NONCONFORMANT`;
- Fatal-, Error-, Warning-, Usage- und Info-Anzahl;
- aggregierte Counts je Severity und EPUBCheck-Diagnosecode.

Meldungstexte, Publication-Metadaten und lokale Pfade werden nicht in
`ToolResult` oder CLI-Ausgabe übernommen. Der private Rohreport kann den
Runtime-Pfad enthalten und bleibt deshalb außerhalb von Git.

EPUBCheck dokumentiert Exitcode `1` für einen abgeschlossenen Lauf mit
Konformitätsfehlern. `LocalCommand.accepted_exit_codes = {0, 1}` trennt diesen
negativen Befund von einem technischen Ausführungsfehler. Ein fehlender,
ungültiger oder zu großer Report macht den Lauf weiterhin unbrauchbar. Die
normalisierte Konformitätsaussage bleibt externe Evidence und ist weder eine
vollständige Qualitätsbewertung noch kanonische Wahrheit.

EPUBCheck liest weder die fachlichen Metadaten für diesen Slice noch liefert es
einen normalisierten Buchtext-Fingerprint. Diese Rollen bleiben bei den bereits
implementierten calibre-Verträgen.

Offizielle Referenzen:

- https://github.com/w3c/epubcheck
- https://github.com/w3c/epubcheck/releases/tag/v5.3.0
- https://github.com/w3c/epubcheck/blob/v5.3.0/src/main/java/com/adobe/epubcheck/tool/EpubChecker.java

## Poppler

Poppler 26.07.0 ist der am 2026-08-14 aktuelle stabile Upstream-Stand und die
verbindliche Untergrenze des `W3-004`-Adapters. Poppler 26.05 führte die für den
festen Textpfad verwendete Option `pdftotext -remove-hyphens` ein. Poppler
26.07 härtete außerdem die `pdfinfo`-Ausgabe gegen Terminal-Escape-Injection
und Zeilenspoofing. Unbekannte und ältere Versionen werden deshalb vor dem
Öffnen der Source-Datei auditierbar abgelehnt.

Der Adapter exponiert ausschließlich diese festen Befehlsformen:

```text
pdfinfo -enc UTF-8 -isodates <runtime-source-file>
pdftotext -enc UTF-8 -eol unix -nopgbrk -remove-hyphens all
  <runtime-source-file> content.txt
```

Beide Befehle erhalten eigene `ToolExecution`-Records und unveränderliche
Provider-/Capability-/Adapter-/Konfigurationsidentitäten. `pdfinfo` liefert
technische Metadaten und Seitenzahl. Seine UTF-8-Ausgabe wird mit einer
1-MiB-Grenze und einer Feld-Allowlist geparst; doppelte oder ungültige Felder
werden abgewiesen. Die gemeldete Dateigröße muss zur unveränderten
`FileObservation` passen. `pdftotext` schreibt ausschließlich in den privaten
Workspace; FolioTone übernimmt maximal 64 MiB als integritätsgeprüftes
`POPPLER_TEXT`-Artefakt.

Nach erfolgreicher Extraktion verwendet PDF denselben FolioTone-eigenen
`NFKC`-/Whitespace-Normalisierer und denselben versionierten
`EBOOK_NORMALIZED_TEXT`-Fingerprint wie EPUB. Leerer normalisierter Output ist
`NO_TEXT` und erzeugt keinen Fingerprint. Fehlerhafte, beschädigte,
verschlüsselte oder nicht lesbare PDFs werden dagegen nicht als `NO_TEXT`
umgedeutet. Die dokumentierten Exitcodes 0, 1, 2, 3 und 99 bleiben in der
jeweiligen `ToolExecution` nachvollziehbar.

Nicht Teil des Vertrags sind OCR, Passwortargumente, caller-kontrollierte
Poppler-Optionen oder schreibende PDF-Operationen. Poppler-Binaries werden
nicht in diesem Repository ausgeliefert. Vor einer späteren gebündelten
Distribution sind GPL-2.0-or-later-Pflichten der tatsächlich ausgelieferten
Komponenten und ihrer Abhängigkeiten separat zu prüfen.

Offizielle Referenzen:

- https://poppler.freedesktop.org/
- https://gitlab.freedesktop.org/poppler/poppler/-/blob/poppler-26.07.0/NEWS

## qpdf

qpdf 12.4.0 ist aktiv gepflegt und unter Apache-2.0 verfügbar. Seit qpdf 11 kann
CLI/API eine vollständige JSON-v2-Repräsentation der PDF-Objekte erzeugen. Die
Dokumentation stellt zugleich klar, dass qpdf keine Textextraktion und keine
inhaltliche Dokumentstruktur liefert.

qpdf ist daher ein optionaler zweiter Provider für PDF-Struktur-/Integritäts-
Evidence. `W3-004` zeigte für Metadaten, Seitenzahl und Text keinen strukturellen
Gap, der eine zusätzliche qpdf-Integration rechtfertigt. Falls qpdf später
integriert wird, darf der Adapter nur reine Inspektionsoptionen
freigeben; JSON-Input-/Update- und Output-Rewrite-Pfade bleiben durch W9
verboten.

Offizielle Referenzen:

- https://github.com/qpdf/qpdf/releases/tag/v12.4.0
- https://qpdf.readthedocs.io/en/latest/json.html
- https://github.com/qpdf/qpdf/blob/main/LICENSE.txt

## Verifizierte `W3-002`- bis `W3-009`-Slices

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

Der anschließende `W3-003`-Smoke-Test verwendete ebenfalls ausschließlich
dieses synthetische EPUB und calibre 9.13.0. `foliotone ebook-text` erzeugte
eine erfolgreiche `ToolExecution`, ein 49 Byte großes `CALIBRE_TEXT`-Artefakt,
`TEXT_EXTRACTED`, 43 normalisierte Zeichen und einen
`EBOOK_NORMALIZED_TEXT`-Fingerprint. Das ephemere Work-Verzeichnis war nach
Abschluss leer. Repository-Ruff, Mypy für 59 Source-Dateien und 115 Pytest-
Tests waren erfolgreich. Der W3-003-Implementierungscommit
`dc2cd09ffbc07098e0c296bea231532c4f38051b` bestand GitHub Actions Run
`31809375485` für PR #13 einschließlich der Docker-, Migrations-, Scan- und
Bootstrap-Schritte.

Für `W3-004` wurde Poppler 26.07.0 als separates administratives Abbild unter
`C:\rep\cache\FolioTone` installiert; die Versionsabfragen für `pdfinfo` und
`pdftotext` meldeten jeweils 26.07.0. Ein lokaler End-to-End-Smoke-Test unter
`C:\rep\tmp\FolioTone` verwendete ausschließlich zwei synthetische PDFs. Das
Text-PDF erzeugte erfolgreiche `pdfinfo`-/`pdftotext`-Ausführungen, 20
Metadatenbeobachtungen, `page_count = 1`, `TEXT_EXTRACTED`, 45 normalisierte
Zeichen und einen `EBOOK_NORMALIZED_TEXT`-Fingerprint. Das leere PDF erzeugte
ebenfalls zwei erfolgreiche Ausführungen, 20 Metadatenbeobachtungen,
`page_count = 1`, `NO_TEXT`, null normalisierte Zeichen und keinen Fingerprint.
Die ephemeren Work-Verzeichnisse waren nach Abschluss leer; es wurden keine
echten Medien verwendet.

Der vollständige W3-004-Stand bestand anschließend lokal `ruff check .`, Mypy
für 63 Source-Dateien und alle 133 Pytest-Tests.

Der `W3-005`-Smoke-Test verwendete ausschließlich synthetische, DRM-freie
EPUB-, MOBI-, AZW- und AZW3-Dateien. `foliotone scan` erzeugte vier
`FileObservation`-Records. Danach lieferten `foliotone ebook-metadata` und
`foliotone ebook-text` je Format insgesamt acht erfolgreiche calibre-
`ToolExecution`-Records. Jeder Textlauf ergab `TEXT_EXTRACTED`, 43
normalisierte Zeichen und denselben `EBOOK_NORMALIZED_TEXT`-Fingerprint. Vier
Ausführungen wurden mit Adapterversion `ebook-convert-text/2` persistiert. Das
ephemere Work-Verzeichnis war nach Abschluss leer; Rohtext wurde nicht über die
CLI ausgegeben. Die gezielten 32 calibre-/CLI-Tests sowie Ruff und Mypy für 63
Source-Dateien waren erfolgreich.

Der vollständige W3-005-Stand bestand lokal `ruff check .`, Mypy für 63
Source-Dateien und alle 142 Pytest-Tests in 8 Minuten 50 Sekunden.

Der `W3-006`-Smoke-Test verwendete calibre 9.13 und ausschließlich ein bereits
synthetisch erzeugtes, DRM-freies MOBI. Die erfolgreiche
`ebook-meta-opf/2`-Ausführung persistierte elf rohe OPF-Beobachtungen und 21
Kandidaten unter `ebook-metadata-candidate/v1`. Alle 32 Ergebnisse waren mit
genau dieser `ToolExecution` und `FileObservation` verknüpft. Die Tabellen für
`Agent`, `Work`, `Edition` und `Series` blieben leer; das OPF-Artefakt wurde
übernommen und das ephemere Work-Verzeichnis bereinigt.

Die gezielten 26 calibre-Metadaten-Tests deckten OPF 2, OPF 3, Identifier-/ISBN-
Namespaces, MARC-Rollen, fremde Rollen-Schemes, Contributor-Sortiernamen,
Sprache, Verlag, Datum, Subject, Beschreibung, Rechte, Typ und Serien ab. Der
vollständige W3-006-Stand bestand lokal `ruff check .`, Mypy für 64
Source-Dateien und alle 152 Pytest-Tests in 8 Minuten 45 Sekunden.

Für `W3-008` wurden Temurin JRE 21.0.12+8 und EPUBCheck 5.3.0 ausschließlich
portabel unter `C:\rep\cache\FolioTone` bereitgestellt. Die offiziellen
Archive besaßen die verifizierten SHA-256-Werte
`B8AA18FEF5EDB69BEE8618F99677D66D0873D22CB40D974C15AC9FFCDECF73BA`
und
`6C07E68584B2E2CE2F89FE06E1246DFEAD3EB36B46B340E7D93524F29DCFF6C5`.
Es erfolgte keine systemweite Installation und kein Neustart.

Der echte CLI-Smoke-Test verwendete ausschließlich das bereits synthetisch
erzeugte EPUB. EPUBCheck meldete drei strukturelle Fehler und Exitcode `1`;
FolioTone persistierte dennoch korrekt eine erfolgreiche
`STRUCTURAL_VALIDATION`-`ToolExecution`, `NONCONFORMANT`, die fünf
Severity-Counts und je einen Count für `PKG-006`, `PKG-007` und `RSC-005`.
Die Source-Datei blieb bytegleich, der private JSON-Report wurde als Artefakt
übernommen und das ephemere Work-Verzeichnis war nach Abschluss leer.

Der vollständige W3-008-Stand bestand mit Python 3.12.10 lokal `ruff check .`,
Mypy für 66 Source-Dateien und alle 175 Pytest-Tests in 9 Minuten 23 Sekunden.

Für `W3-009` wurde Pillow 12.3.0 nur in der projektbezogenen Umgebung unter
`C:\rep\cache\FolioTone` installiert. Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-009-smoke-01` verwendete zwei ausschließlich
synthetische EPUBs. Das EPUB mit eingebettetem JPEG lieferte
`COVER_EXTRACTED`, Format und Abmessungen sowie den dHash
`4000000000000000`; das coverlose EPUB lieferte `NO_EMBEDDED_COVER` ohne
Fingerprint. Beide Läufe endeten erfolgreich, und beide Source-SHA-256 blieben
unverändert. Die 13 neuen Cover-Tests plus zwei Bootstrap-Tests, Ruff und Mypy
für 69 Source-Dateien waren erfolgreich.

Der vollständige W3-009-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 69 Source-Dateien und alle 188 Pytest-Tests in
11 Minuten 31 Sekunden. Der lokale Wheel-Build enthielt die neue
Cover-Implementierung einschließlich des `calibre-debug`-Helpers.
