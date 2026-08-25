# Synthetisches EPUB-Transformationsfixture

`generate_fixture.py` erzeugt ausschließlich das kleine synthetische
`ebook-transform-gate-input/v1` für den negativen Nachweis von `GATE-0001`.
Feste Member-Reihenfolge, Zeitstempel, Unix-Dateimodi und unkomprimierte
Member machen den Eingang unabhängig von der zlib-Version bytegleich. Das
Fixture enthält eine feste UUID, einen Titel, eine Rollenverfeinerung,
Serienmetadaten, Navigation, genau ein Spine-Dokument und ein minimales Cover.
Die reviewte vollständige Metadatenprojektion führt Rolle und Serie ebenfalls,
damit `ebook-polish --opf` nicht irrtümlich als partielle Patch-Schnittstelle
charakterisiert wird.

Die erzeugten EPUB-/OPF-Dateien und Tooloutputs werden nicht eingecheckt. Sie
liegen nur in einem aufgabenspezifischen Verzeichnis unter `C:\rep\tmp`.
`fixture-manifest.json` bindet die erwarteten Digests und Größen. Der Generator
erteilt keine Writer- oder W10-Autorisierung und beschreibt kein positiv
qualifiziertes Transformationsprofil.
