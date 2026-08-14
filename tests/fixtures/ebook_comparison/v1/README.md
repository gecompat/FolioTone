# Synthetischer E-Book-Vergleichskorpus v1

Dieser Korpus bildet die kontrollierte Ground Truth für `W3-007`. Sämtliche
Namen, Identifier, Container-Surrogate und Texte wurden ausschließlich für die
FolioTone-Tests erzeugt. Die Dateien enthalten weder reale Medien noch private
Sammlungsdaten.

Die Dateien unter `files/` sind bewusst kleine Container-Surrogate und keine
gültigen EPUB- oder MOBI-Dateien. Sie machen Gleichheit und Abweichung der
rohen Dateibytes reproduzierbar, ohne Verhalten eines externen Parsers zu
imitieren. Die Dateien unter `text/` repräsentieren bereits extrahierte
Text-Artefakte. FolioTone berechnet daraus mit dem produktiven, versionierten
`EBOOK_NORMALIZED_TEXT`-Vertrag die Inhalts-Fingerprints.
Die Root-`.gitattributes` behandelt die Container-Surrogate als binär und
erzwingt für Text-Artefakte LF-Zeilenenden, damit die deklarierten Byte-Hashes
auf Windows und Linux stabil bleiben.

`manifest.json` verwendet das Schema
`foliotone-ebook-comparison-fixture/v1`. Jeder Eintrag bindet relative
Fixture-Pfade, Format, SHA-256-Werte, bibliografische Ground Truth und
synthetische Metadatenbeobachtungen. Die fünf Szenarien decken folgende
Abgrenzungen ab:

- byte-identische Dateien;
- geänderte Metadaten bei unverändertem normalisiertem Text und derselben
  `Edition`;
- dieselbe `Edition` als EPUB-/MOBI-Formatvariante;
- dasselbe `Work` als andere `Edition` und Übersetzung;
- widersprüchliche, versionsgebundene Tool-Beobachtungen ohne erzwungenen
  kanonischen Wert.

Die deklarierten `RelationType`-Werte sind gelabelte Ground Truth für spätere
Matching-Tests. Der Korpus implementiert weder Candidate Blocking noch
Scoring, Confidence-Schwellen oder automatische Review-Entscheidungen. Diese
Verträge bleiben W6 und W7 vorbehalten.
