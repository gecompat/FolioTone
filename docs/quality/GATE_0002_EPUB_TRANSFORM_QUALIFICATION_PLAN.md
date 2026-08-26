# GATE-0002: Kombiniertes EPUB-Transformationsprofil qualifizieren

- Status: `DONE`
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

## Ergebnis

`GATE-0002` endet mit `PASS`. Zwei getrennte frische, netzlose und identisch
begrenzte calibre-9.13.0-Läufe erzeugten erwartungsgemäß unterschiedliche rohe
Zwischenausgaben: 2.058 und 2.057 Byte mit den SHA-256
`186a4428e84526318a1e036948bb8d8868582a559e8d6b2f455039542e1e5c46`
und
`20ef99fcf5ee24acf8cd1546b5abaf045aa30c0a925cbe6cab78b4659b650f59`.
Die nachgelagerte FolioTone-Normalisierung erzeugte aus beiden Outputs sowie
bei idempotentem Replay jeweils exakt 2.073 Byte mit SHA-256
`c1f02fa795de03fa445b6d2917be8d089acf22b3c5f3ad47dba67e9536e15c54`.

Der vollständige Metadaten-Snapshot ist mit SHA-256
`c7a7d976cee966805a48b9f5996bcc4c6462d490b2894e9e80e84030c90aac17`
gebunden. Das kanonische Profil trägt SHA-256
`6b059d7e62f42ae21531c4356869ed995675ac882d53b4ed3373e3a6eefafbd6`
und bindet das lokal gebaute `linux/amd64`-Image
`sha256:61c760dc60283af8ac11b0aeb1833417eae88d67092176b7070bbcfc09561e67`,
calibre 9.13.0, CPython 3.12.11, zlib 1.3.1, EPUBCheck 5.3.0, OpenJDK
21.0.12, Base-, Tool- und JAR-Digests, die kanonische Inventarliste aus
Toolchain-Lock, 145 Debian- und 25 Python-Paketen sowie alle Command-,
Environment-, Serializer-, Packer-, Kompressions- und ZIP-Konstanten.

Die übrigen vollständigen Binder sind:

- Base-Image-Digest
  `0b29ab9e420820f53d1cd5ce0157dfe07bea8a7cff5b4754d6d95c07b0e5bc47`;
- calibre-Archiv-SHA-256
  `d664fe74953463f1b679945a5460234b61cbf539da48fc78f2111ff8d9503cc0`;
- EPUBCheck-JAR-SHA-256
  `f7f96617c929371821609b88c8484d6dc9f24fe916499863c46094c5fb778a65`;
- kanonischer Toolchain-Inventar-SHA-256
  `7afd8f60306ed9653f963e24164a81514059a04889f3d0033b53115023bbbd39`;
- Command-/Limit-Konfigurations-SHA-256
  `1ef351820ad7c4362a491cf7dc1b81b82f0f3e20aa4a9c613fc6f22aa58cc651`;
- Environment-SHA-256
  `ffd0ade581e2256a3c6bac7d785d3def6a3767090a8b9d5ec08127bb1aeeefab`.

Das Toolchain-Inventar ist das sortierte kanonische JSON aus dem gelockten
Toolchain-Dokument, allen `dpkg-query`-Paaren und `pip freeze --all`-Paaren.
Die Command-Bindung umfasst feste `ebook-polish --opf`-Argumente, Inputprofil,
Plattform, netzlose und read-only Ausführung, Capability-Drop,
No-new-privileges, Speicher-, CPU-, PID-, File-Descriptor- und Temp-Limits.

EPUBCheck 5.3.0 meldete für den finalen Output 0 Fatal-, 0 Error-, 0 Warning-
und 0 Usage-Befunde. Ein von der Produktimplementierung unabhängiger
ZIP-/XML-Read-back bestätigte dieselbe Membermenge, den Zieltitel,
Serienname `Synthetische Reihe`,
Serientyp `series`, Position `1.5`, Navigation, Spine und Cover. `mimetype`
blieb erster unkomprimierter Entry; Container, Navigation, Text und Cover
waren gegenüber der direkt in den Gate-Runner gebundenen Quelle in ihren
unkomprimierten Bytes identisch. Preserve-Metadaten wurden ebenfalls vor A,
vor B und nach der Kanonisierung gegen die Quelle verglichen. Ein eigener
kanonischer OPF-Strukturhash bindet Package-, Manifest- und Spine-Semantik;
die von calibre geänderte reine Manifest-Reihenfolge wird fest sortiert. Die
Quelle blieb bei 3.556 Byte und SHA-256
`03de1f669683d99c192a68a3faba71fd29efe3ae8908f3832545edc73f6b2929`
unverändert.

Die fokussierte synthetische Suite prüft die vollständige Positiv- und
Negativmatrix einschließlich bösartiger Template-Payloads vor dem Toolprozess.
Verwaiste oder mehrdeutige OPF-Refinements, unbekannte Metadatenattribute und
vollständig OCF-widrige Dateinamen werden fail-closed abgewiesen. Die aktuelle
offizielle Prüfung bestätigt calibre 9.13.0 als
gepflegte, gegenüber `GHSA-4f7g-rjfp-hmvx` gepatchte Version und EPUBCheck
5.3.0 als aktuellen Validator. calibre bleibt als GPL-3.0-Prozess getrennt;
EPUBCheck bleibt BSD-3-Clause. Es werden weder deren Code importiert noch das
lokal gebaute Image oder Drittanbieterartefakte veröffentlicht.

Damit wird `WI-0004` auf `READY` gesetzt. Das Gate selbst implementiert weder
Dry Run, Persistenz, Application-/CLI-/REST-/Browser-Fläche, Publish,
Capability, Authorization noch W10-Operation.

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
