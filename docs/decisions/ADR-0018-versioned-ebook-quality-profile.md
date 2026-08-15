# ADR-0018: Versioniertes E-Book-Qualitätsprofil

- Status: Accepted
- Datum: 2026-08-15

## Kontext

Die read-only E-Book-Adapter liefern technische Metadaten, normalisierten Text,
Embedded-Cover-Fakten und EPUB-Konformitäts-Evidence. Für eine große Sammlung
reicht die isolierte Ausgabe dieser Fakten nicht aus: Fehlende Metadaten,
textlose Dateien, strukturelle Fehler und unvollständige Analyseläufe müssen
einheitlich und filterbar dargestellt werden.

Ein einzelner numerischer Qualitätsscore würde unterschiedliche Ursachen
verdecken. Außerdem darf ein Tool- oder Artefaktfehler nicht als schlechte
Medienqualität erscheinen. Qualitätsbeobachtungen dürfen weder Datei-,
`Edition`- oder `Work`-Identität festlegen noch rohe private Inhalte in die
CLI-Ausgabe übernehmen.

## Entscheidung

FolioTone projiziert die begrenzten Fakten von
`ebook-analysis-workflow/v3` deterministisch in
`EbookQualityAssessment` unter dem separaten Profil `ebook-quality/v1`.
Das Assessment enthält die fünf stabil geordneten Dimensionen `METADATA`,
`TEXT`, `COVER`, `STRUCTURE` und `FORMAT_RISK`.

Jede Dimension verwendet `OK`, `REVIEW`, `ACTION_REQUIRED`, `INCOMPLETE` oder
`NOT_APPLICABLE`. Der Gesamtzustand ist kein Score: `INCOMPLETE` hat Vorrang vor
`ACTION_REQUIRED`, danach folgen `REVIEW` und `OK`. Dadurch bleibt fehlende
Evidence von einem negativen Qualitätsbefund unterscheidbar.

Die Befunde besitzen feste, maschinenlesbare Codes und `INFO`, `WARNING` oder
`ERROR` als Severity. Soweit eine Toolausführung existiert, verweist jeder
Befund auf deren exakte `ToolExecution`-ID. Erwartete Qualitätsbefunde ändern
nicht den technischen Exitcode von `ebook-analyze`; ausschließlich der
technische Workflowstatus bestimmt weiterhin Exitcode 0 oder 1.

Das erste Profil bewertet:

- vorhandene Titel-, Contributor-/Autor-, Sprach-, Identifier-, Verlags-,
  Datums- und Series-Kandidaten, ohne die Kandidaten zu kanonischen Metadaten
  zu erklären;
- verfügbaren normalisierten Text und eine dokumentierte Review-Grenze von
  2.000 Zeichen; ein textloses PDF wird zusätzlich als `PDF_OCR_CANDIDATE`
  ausgewiesen, ohne OCR auszuführen;
- `COVER_EXTRACTED` oder `NO_EMBEDDED_COVER` für calibre-Formate;
- EPUBCheck-Fatal-, Error- und Warning-Evidence;
- PDF-Verschlüsselung sowie die explizite Aussage, dass für Nicht-EPUB-Formate
  keine EPUB-Strukturprüfung vorliegt.

Die Projektion wird aus den vorhandenen, exakt wiederverwendbaren
Workflow-Ergebnissen berechnet. `ebook-quality/v1` führt keine zusätzlichen
Tools aus und benötigt keine eigene Persistenzmigration. Eine spätere
Sammlungsanalyse kann die Befundcodes aggregieren; Änderungen an Schwellen oder
Regeln erfordern eine neue Profilversion.

## Konsequenzen

- Sammlungsberichte können konkrete Review- und Maßnahmenlisten nach Dimension
  und Befundcode bilden, ohne private Metadaten oder Inhalte offenzulegen.
- Ein erfolgreich analysiertes E-Book kann `REVIEW` oder `ACTION_REQUIRED`
  erhalten, während ein unvollständig analysiertes E-Book `INCOMPLETE` bleibt.
- PDF-Cover und Nicht-EPUB-Struktur erhalten `NOT_APPLICABLE`; fehlende
  Anwendbarkeit wird nicht als Medienfehler gezählt.
- Die Qualitätsprojektion bleibt von Duplicate Matching und kanonischer
  Identität getrennt. Ähnlichkeit, Metadatenvollständigkeit oder Coverstatus
  bestätigen keine Datei-, `Edition`- oder `Work`-Relation.
- Neue Regeln benötigen stabile Befundcodes, Tests für widersprüchliche
  Evidence und eine explizite Profilversionierung.
