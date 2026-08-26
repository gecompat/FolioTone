# GATE-0002: Kombiniertes EPUB-Transformationsprofil qualifizieren

- Status: `READY`
- Datum: 2026-08-26
- Artefakt: `urn:uuid:01a03cca-930f-702f-82f2-839d4407eac6`
- Entscheidung: `DEC-0002`
- blockierte Umsetzung: `WI-0004`
- Tier: `FRONTIER`

## Zweck und Grenze

Das Gate qualifiziert Option A aus `DEC-0002`: calibre 9.13.0 verarbeitet
einen vollständigen Transformations-Metadaten-Snapshot; danach normalisiert
FolioTone das OPF und verpackt den calibre-Output mit einem kanonischen
EPUB-Profil. Der Gate-Kandidat erzeugt ausschließlich neue private Outputs aus
synthetischen EPUBs. Er öffnet keine Source Media, Calibre-Bibliothek,
Persistenz-, CLI-, REST-, Browser-, Publish-, Capability-, Authorization- oder
W10-Fläche.

`GATE-0001` bleibt der negative Charakterisierungsnachweis des rohen
`ebook-polish --opf`-Profils. `GATE-0002` darf dessen Ergebnis nicht durch eine
schwächere semantische Gleichheit umdeuten. Nur exakt gleiche Bytelänge und
vollständiger SHA-256 schließen die Reproduzierbarkeitsachse positiv.

## Fester Kandidatenscope

Der Gate-Slice umfasst genau:

1. ein bounded synthetisches EPUB-3-Eingangsprofil mit genau einem Package
   Document, Navigation, Spine, Text, Cover und vollständigem
   Metadateninventar einschließlich Contributor- und Serienwerten. Der Snapshot trennt
   reviewte neue oder ersetzte `CANONICAL`-/`USER_CONFIRMED`-Werte von
   `OBSERVED`-/`EXTERNAL`-Source-Werten mit Preserve-Obligation;
2. das bereits charakterisierte feste calibre-9.13.0-
   `ebook-polish --opf`-Command Shape mit vollständigem OPF-Snapshot;
3. eine neue reine FolioTone-Normalisierung des erzeugten OPF auf eine im
   Gate versionierte Byte-Serialisierung;
4. eine neue reine kanonische EPUB-Verpackung mit vollständig versioniertem
   Entry-, Header-, Zeit-, Flag-, Attribut-, Extra-Field-, Kommentar- und
   Kompressionsprofil;
5. unabhängige Struktur-, Metadaten-, Text-, Navigation-, Cover-,
   Preserved-Field- und Nutzdatenverifikation.

calibres Zwischenoutput bleibt untrusted `ToolProvider`-Output und wird vor
jeder Normalisierung erneut bounded, no-follow und ohne naive Extraktion
geprüft. Die FolioTone-Stufe importiert keine calibre-Interna. calibre bleibt
ein getrennt ausgeführter Prozess; das Gate verändert oder veröffentlicht das
lokal gebaute Toolchain-Image nicht.

Vorhandene bounded OCF-/ZIP-/XML-Parser, Archive-Inventare und
Streamingmuster aus `foliotone.metadata_write` dürfen als technische
Bausteine extrahiert oder wiederverwendet werden. Der Gate-Code darf keine
Source-Writer-, Plan-, Capability-, Authorization-, Executor-,
`renameat2`-, Recovery- oder Reconciliation-Schnittstelle importieren oder
exponieren.

## Wave-Vertrag

Die Gate-Wave beginnt auf einem nach Merge dieser Entscheidung frisch
verifizierten `origin/main` in einem eigenen Worktree und Branch. Ihr
erlaubter Scope ist:

- ein reines, bounded Transformationsprofil unter
  `src/foliotone/ebook_transform/`;
- ausschließlich synthetische Fixtures unter
  `tests/fixtures/ebook_transform/gate-0002/`;
- fokussierte Unit-/Gate-Tests für den neuen Scope;
- die Ergebnisfortschreibung dieses Gate-Dokuments sowie der betroffenen
  Planungs-, Architektur-, Tool- und Artefaktverträge.

Ausgeschlossen sind Persistenzmigrationen, öffentliche Application-/CLI-/
REST-/Browser-Flächen, Scan- oder Collection-Mutation, reale Medien,
Source-/Output-`ScanRoot`-Writes, Publish, Calibre-Library-Änderungen und jede
Vorarbeit an der späteren `WI-0004`-Authority.

## Positive Akzeptanz

Das Gate ist nur positiv, wenn der exakte stabile Head alle folgenden
Nachweise erfüllt:

1. Zwei zeitlich getrennte, frische, netzlose und identisch begrenzte
   Containerläufe erzeugen nach calibre, Normalisierung und Verpackung exakt
   dieselbe Bytelänge und denselben vollständigen SHA-256.
2. Eine erneute Normalisierung und Verpackung eines bereits kanonischen
   Outputs ist byteidentisch und belegt Idempotenz.
3. Das vollständige Profil bindet calibre-, Adapter-, Parser-, Serializer-,
   Packer-, Python-, zlib-, Image- und Konfigurationsidentität. Kein Outputbyte
   hängt von realer Uhrzeit, Locale, Host-Environment, Arbeitsverzeichnis,
   zufälliger Entry-Reihenfolge oder Dateisystemmetadaten ab.
4. Der Metadaten-Snapshot ist vollständig und immutable. Review-Lineage bindet
   ausschließlich neue oder ersetzte `CANONICAL`-/`USER_CONFIRMED`-Werte;
   unveränderte `OBSERVED`-/`EXTERNAL`-Source-Werte behalten Provenance und
   Preserve-Obligation. Der v1-Inventarvertrag umfasst Titel, `title_sort`,
   Identifier mit Namespace und Wert, Contributor mit Namen, Rollen und
   Sortierwerten, Sprache, Publisher, Publikationsdatum, Subjects,
   Beschreibung, Rechte, `type`, `rating` sowie Serienname, -typ und -position.
   Für jedes Feld existiert ein Inventareintrag mit gebundenem Wert und
   Provenance oder mit explizit beobachteter Source-Abwesenheit; ein
   ausgelassener Inventareintrag ist keine Abwesenheit. Zusätzliche oder nicht
   verlustfrei repräsentierbare Source-Felder werden vor calibre fail-closed
   abgewiesen.
5. Die technische Metadaten-Delta-Allowlist enthält genau
   `dcterms:modified`. Sein Wert ist vor dem Toollauf immutable im Snapshot
   gebunden und unabhängig von der realen Laufzeit. Jedes andere OPF-Delta ist
   entweder ein reviewter Snapshotwert oder ein Gate-Fehler.
6. EPUBCheck 5.3.0 bewertet den finalen Output als konform. Unabhängige
   Read-backs bestätigen Package Document, Navigation, Spine, Text, Cover,
   Preserved Fields und die unkomprimierten Hashes aller nicht durch den
   Snapshot veränderten Nutzdaten.
7. Die synthetische Negativmatrix umfasst mindestens `DOCTYPE`/Entity,
   ungültiges UTF-8, Duplicate Entry-Namen, absolute, Drive-relative,
   Backslash-, Punkt-, Parent- und Traversal-Namen, Symlink-/Reparse-/Hardlink-
   ähnliche Entries, NFC-/Casefold-Kollisionen, ZIP64, Verschlüsselung,
   unerlaubte Kompression, Kompressionsbomben sowie Einzel-, Verhältnis-,
   Aggregat- und Entry-Count-Limits, mehrere Rootfiles oder Renditions,
   beschädigtes ZIP/XML und ein nicht vollständig abbildbares
   Metadatenprofil.
8. Die aktuellen offiziellen Maintenance-, Automations-, Security-, Lizenz-
   und lokalen Imagebedingungen für calibre und EPUBCheck sind geprüft. Das
   Gate autorisiert weiterhin keine Veröffentlichung des Toolchain-Images.
9. Fokussierte Tests, betroffene statische Verträge, `git diff --check` und
   genau ein vollständiger PR-CI-Gate sind für denselben stabilen Head grün.

## Stopbedingungen und Ergebnis

Die Wave stoppt negativ, wenn eine Zeit-, Serializer-, ZIP-, zlib-, Host- oder
Toolvarianz nicht vollständig an die Profilidentität gebunden werden kann,
ein Snapshotfeld verloren geht, ein Preserved Field oder Nutzdateninhalt
abweicht, ein Malicious Fixture die bounded Grenze verlässt, eine aktuelle
Security-/Lizenzbedingung ungeklärt bleibt oder eine Source-/W10-Fläche nötig
wird.

Ein positives Ergebnis aktualisiert `GATE-0002` auf `DONE` mit einem
pfadfreien Evidence-Nachweis und setzt `WI-0004` auf `READY`. Ein negatives
Ergebnis aktualisiert das Gate auf `DONE` mit festem Fehlerausgang und lässt
`WI-0004` `BLOCKED`. Ein unvollständiger Lauf bleibt nicht als positiv
interpretierbar.
