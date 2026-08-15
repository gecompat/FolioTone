# Synthetischer E-Book-Vergleichskorpus v2

Der additive Korpus für `W3-014` erweitert die Ground Truth aus
`foliotone-ebook-comparison-fixture/v1`. Alle Container-Surrogate, Texte,
Namen und Identifier wurden ausschließlich für FolioTone erzeugt. Der Korpus
enthält keine realen Medien und keine privaten Sammlungsdaten.

Die sechs zusätzlichen Items decken AZW, AZW3 und PDF, eine mittlere
Cover-dHash-Distanz, vollständig fehlende Analyse-Evidence und gezielt
inkompatible beziehungsweise unvollständige Evidence ab. Zusammen mit v1
stehen damit Cover-Distanzen von 0, 1, 8, 32 und 64 Bit sowie alle aktuell
unterstützten Formate EPUB, MOBI, AZW, AZW3 und PDF zur Verfügung.

`SPARSE` bedeutet, dass nur der beim Scan erzeugte vollständige Datei-
Fingerprint vorhanden ist. `MALFORMED` erzeugt ausschließlich synthetisch
eine fehlgeschlagene Metadatenanalyse, ein inkompatibles Textprofil, einen
ungültigen Cover-dHash und unvollständige EPUB-Struktur-Evidence. Erwartet
wird jeweils ein begrenzter technischer Zustand, keine Identitätsableitung.

Die Dateien unter `files/` sind kleine Container-Surrogate und keine gültigen
Mediencontainer. Die Textdateien repräsentieren bereits extrahierte private
Tool-Artefakte. Der produktive Normalisierungsvertrag berechnet daraus die im
Manifest deklarierten Fingerprints. Externe Werkzeuge werden für diese Tests
nicht ausgeführt.
