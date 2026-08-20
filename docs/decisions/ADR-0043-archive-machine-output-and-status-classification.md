# ADR-0043: Archive-Machine-Output und technische Statusklassifikation

**Status:** Akzeptiert

**Datum:** 2026-08-20
**Geltungsbereich:** EBAR-05, 7-Zip 26.02, unverschlüsseltes Listing und Integrity

## Kontext

ADR-0038 und ADR-0039 legen feste Archive-Statuswerte, den isolierten
Streaming-Runner und den Parser `archive-7zip-slt-parser/v1` fest. Vor dem
ersten realen EBAR-05-Lauf wurden zwei Lücken sichtbar:

1. Der feste Listing-Befehl verwendet `l -slt -ba`. Im bytegenau gebundenen
   7-Zip-26.02-Quellstand setzt `-ba` `EnableHeaders=false`. `List.cpp` gibt
   dadurch weder Archive-Properties noch die Trennzeile `----------` aus.
   Parser v1 verlangt jedoch genau diesen Header. Ein erfolgreiches reales
   Listing wäre deshalb nicht als v1 parsebar; ein leeres Archiv erzeugt
   erfolgreich einen leeren stdout-Stream.
2. Die 7-Zip-Exitcodes unterscheiden nur Erfolg, Warnung, fatalen Fehler,
   Benutzerfehler, Speichermangel und Abbruch. Sie unterscheiden insbesondere
   nicht verlässlich Passwortbedarf, nicht unterstützte Methode und
   Korruption. ADR-0038 nennt die Zielstatuswerte, aber noch keine mechanische
   Klassifikationsregel.

Die Referenz ist ausschließlich das bereits durch ADR-0040 gebundene
7-Zip-26.02-Artefakt und dessen Source-Tarball mit SHA-256
`cf967c98bca02a4b8b16375f441825a8e141362f14be1969bbec8e1ca0bff9dd`.
Ein Toolupgrade benötigt ein neues Parser- und Klassifikationsprofil.

## Entscheidung

### 1. Member-only Parser v2

Vor EBAR-05 wird das additive Profil `archive-7zip-slt-parser/v2` eingeführt.
Parser v1 und seine DTOs bleiben unverändert lesbar.

V2 verarbeitet ausschließlich stdout des bereits akzeptierten festen Befehls
`7zzs l -slt -ba -bd -bb0 -bso1 -bse2 -bsp0 -sccUTF-8 -- A`:

- Der Stream besteht aus null bis `max_member_count` technischen
  Member-Records.
- Die exakte Grammatik lautet `EOF | (FIELD+ BLANK)+ EOF`. Jeder nichtleere
  Record besteht ausschließlich aus der bereits in ADR-0039 erlaubten
  Member-Feldmenge und endet mit genau einer zusätzlichen Leerzeile. Führende,
  doppelte oder fehlende Abschluss-Leerzeilen sowie Banner, Archive-Header,
  Trennzeile, Summen und nachlaufendes Material sind unzulässig.
- Jeder Record verlangt die fünf v1-Pflichtfelder `Path`, `Folder`, `Size`,
  `Packed Size` und `Encrypted` mit ihren bestehenden nichtleeren kanonischen
  Wertgrammatiken. Fehlende, leere oder doppelte Pflichtfelder bleiben
  `GRAMMAR_REJECTED`. Da 7-Zip die konkrete Propertymenge formatabhängig aus
  dem Handler bezieht, muss EBAR-05 dieses Pflichtset real für jede freigegebene
  Familie belegen. Eine Abweichung erfordert ein neues formatgebundenes Profil
  und eine Vertragsentscheidung; der generische Parser darf sie nicht still
  lockern.
- Ein byteleerer Stream bei Prozess-Exitcode `0` ist ein erfolgreiches leeres
  Listing. Whitespace-only, ein unvollständiger Record oder ein Record ohne
  `Path` bleibt `GRAMMAR_REJECTED`.
- V2 erzeugt ein eigenes immutable Resultat aus Profil, Parse-Status und
  geordneten Membern. Es erfindet keinen Archive-Header. Containerfamilie,
  Volumegruppe und Source-Größe stammen aus der bereits validierten
  Signatur-/Volume-/Observation-Evidence und werden nicht aus stdout geraten.
- Alle vorhandenen UTF-8-, NFC-, Locator-, Feld-, Zeilen-, Chunk-, Stream- und
  Membergrenzen gelten unverändert. Rohbytes werden inkrementell verarbeitet
  und unmittelbar verworfen.
- `-ba` bleibt verpflichtend. Das Entfernen von `-ba` würde Banner-, Scan- und
  menschenorientierte Headerausgabe wieder einführen und ist keine
  Maschinenformat-Korrektur.

Das neue mechanische Paket heißt `S-EBAR-02A`. Es darf ausschließlich
`src/foliotone/archive/sevenzip_slt.py` und die zugehörige Unit-Testdatei
ändern. EBAR-05 beginnt erst nach dessen Merge.

### 2. Statusquellen und Vorrang

Der Provider bildet einen Status in folgender Reihenfolge. Der private
inkrementelle Consumer hält seinen terminalen Parsergrund separat vom
zusammengefassten Runnerstatus fest:

1. Runner `TOOL_FAILED`, einschließlich Cleanup-Fehler, dominiert und verwirft
   sämtliche Parse-Teilwerte. `TIMED_OUT`, `LIMIT_EXCEEDED` und
   `TOOL_UNAVAILABLE` werden unverändert abgebildet.
2. Ein parser-terminaler `LIMIT_EXCEEDED` wird fachlich `LIMIT_EXCEEDED`;
   `ENCODING_REJECTED` und `GRAMMAR_REJECTED` werden `TOOL_FAILED`. Der durch
   Consumer-Abbruch zusammengefasste Runnerstatus `POLICY_REJECTED` darf diese
   Parserursache nicht überdecken. Ein unabhängiger Sandbox-
   `POLICY_REJECTED` ohne Parserterminalgrund bleibt `POLICY_REJECTED`.
3. `CANCELLED` erzeugt ausschließlich eine `ToolExecution` mit
   `CANCELLED`; es entsteht kein terminaler Archive-Snapshot.
4. Listing ist nur bei Runner `COMPLETED`, Exitcode `0` und vollständig
   finalisiertem Parser v2 `LISTED`. Integrity ist nur bei Runner `COMPLETED`
   und Exitcode `0` `PASSED`.
5. Jeder nicht akzeptierte Exitcode wird `TOOL_FAILED`. stdout und stderr
   dürfen diese konservative Zuordnung nicht durch Textsuche verfeinern.

Exitcode allein ist niemals Authority für `PASSWORD_REQUIRED`,
`UNSUPPORTED_METHOD`, `CORRUPT`, `MISSING_VOLUME` oder `UNSUPPORTED_FORMAT`.

### 3. stderr ist keine Ursachen-Authority

`-sccUTF-8` legt nur die Console-Codepage fest. Es garantiert weder Sprache
noch die Stabilität menschenorientierter Fehlermeldungen. Auch die groben
7-Zip-26.02-Exitcodes teilen mehrere Ursachen:

| Exitcode | 7-Zip-Bedeutung | EBAR-05 |
| --- | --- | --- |
| `0` | Erfolg | nur zusammen mit Runner-Erfolg und vollständig validiertem Output akzeptiert |
| `1` | Warnung | `TOOL_FAILED` |
| `2` | fataler Fehler | `TOOL_FAILED` |
| `7` | Command-Line-Fehler | `TOOL_FAILED` |
| `8` | Speichermangel | `TOOL_FAILED` |
| `255` | Tool-seitiger Abbruch | `TOOL_FAILED`; nur ein unabhängig vom Runner erkanntes Cancellation-Signal wird `CANCELLED` |

stderr wird parallel bis zur vorhandenen 1-MiB-Grenze konsumiert und danach
vollständig verworfen. Der Provider sucht darin weder mit Substrings noch mit
regulären Ausdrücken und erzeugt daraus keine fachliche Ursache. Ein späterer
Status `PASSWORD_REQUIRED`, `CORRUPT` oder `UNSUPPORTED_METHOD` benötigt eine
separat spezifizierte strukturierte Preflight- oder Helper-Evidence. Solange
diese fehlt, bleibt der entsprechende reale 7-Zip-Fehler `TOOL_FAILED` mit
`ArchiveEncryptionStatus.UNKNOWN`.

### 4. Zustände außerhalb stderr

- `MISSING_VOLUME` und Volume-`POLICY_REJECTED` entstehen ausschließlich aus
  der vor dem Runner vollständig validierten Volumegruppe. stderr darf diese
  Zustände nicht erzeugen.
- `UNSUPPORTED_FORMAT` entsteht ausschließlich aus der Signatur-/Format-
  Allowlist vor dem Runner. Ein vom Tool nicht geöffnetes, zuvor als erlaubt
  klassifiziertes Objekt ist `TOOL_FAILED`; EBAR-05 leitet daraus nicht
  `CORRUPT` ab.
- Die Verschlüsselungsaggregation betrachtet ausschließlich nicht-directory,
  datenführende Member. Ein leeres Archiv, nur Verzeichnisse oder ausschließlich
  `Encrypted = -` ergeben `NONE`; ausschließlich `Encrypted = +` ergibt
  `DATA_ENCRYPTED`; eine Mischung ergibt `MIXED`. Ein `+` an einem Directory
  wird ignoriert. `DATA_ENCRYPTED` und `MIXED` lassen den Listingstatus
  `LISTED`, verhindern jeden Integrity-Aufruf und erzeugen `NOT_TESTED` ohne
  Execution-ID sowie `SECURE_CHANNEL_UNAVAILABLE`. Header-Verschlüsselung kann
  ohne strukturierte Evidence nicht von anderen Open-Fehlern unterschieden
  werden und ergibt in EBAR-05 `TOOL_FAILED`, `UNKNOWN` und `NOT_TESTED`.
- Integrity wird nur nach einem erfolgreichen, unverschlüsselten Listing
  gestartet. Ein Integrity-Status ungleich `NOT_TESTED` bindet eine eigene,
  vom Listing verschiedene `ToolExecution`-ID.

### 5. Privacy und öffentliche API

Die öffentliche Produktions-API konstruiert beziehungsweise verlangt den
festen `ArchiveLinuxContainerRunner`; ein injizierbarer Runner ist keine
Runtime-Authority. Testseams liegen hinter einer privaten reinen Reduktions-
oder Lifecycle-Grenze.

Input-Identität ist ausschließlich ein geschlossenes, domain-separiertes
SHA-256-Literal. Öffentliche DTOs und `repr` enthalten nur opaque IDs,
Statusliterale, Profile und Zähler. Raw stdout/stderr, Pfade, Membernamen,
Kommentare und freie Fehlertexte bleiben ausgeschlossen.

## Tests und Abnahme

`S-EBAR-02A` belegt mindestens:

- einen, mehrere und null Member unter `-ba -slt`;
- Chunk- und Zeilengrenzen über beliebigen Bytegrenzen;
- die exakte Abschluss-Leerzeile sowie Ablehnung von führenden/doppelten/
  fehlenden Leerzeilen, Header, Banner und Separator;
- das vollständige Pflichtfeldset und unveränderte v1-Regression;
- exakt dieselben Locator-, NFC-, Feld-, Deduplikations- und Privacy-Regeln wie
  v1.

EBAR-05 belegt danach mit generierten synthetischen Archiven und kleinen
technischen Exitcode-Fixtures:

- alle Runner- und Exitcodepfade; beliebige, fremdsprachige und adversariale
  stderr-Prosa verändert den konservativen Status nicht;
- parser-terminales Limit/Encoding/Grammar, unabhängiges Sandbox-
  `POLICY_REJECTED`, Cleanup-Fehler und Cancellation mit der festgelegten
  Vorrangfolge;
- Daten- versus Header-Verschlüsselung, kein Integrity-Lauf bei
  Verschlüsselung und keine Passwortübergabe; die Aggregationsmatrix umfasst
  leer, nur Verzeichnisse, nur Klartext, nur verschlüsselte Daten, Mischung
  und verschlüsseltes Directory neben Klartext;
- getrennte Listing-/Integrity-Execution-Provenance und die Sum-Type-Regeln
  aus ADR-0039;
- inkrementellen Verbrauch ohne Raw-Stream-Akkumulation;
- unveränderte Sourcegröße und vollständigen SHA-256 vor und nach dem Lauf;
- den echten provisionierten Runner nur bei nachweisbarer lokaler
  Availability, ansonsten einen deterministischen Skip ohne Pull oder Netz.
- je eine echte Golden-Fixture für ZIP, RAR4, RAR5, 7z, TAR sowie gzip-,
  bzip2-, xz- und zstd-komprimiertes TAR. Jede Familie muss die fünf
  Pflichtfelder liefern; andernfalls stoppt EBAR-05 für ein neues
  formatgebundenes Profil.

Es erfolgt pro Paket nur der fokussierte Testlauf; das vollständige Gate läuft
einmal pro PR.

## Folgen

- EBAR-05 erhält eine mechanisch testbare, versionsgebundene Eingabe statt
  geratenem Verhalten.
- Leere Archive sind ohne erfundenen Header darstellbar.
- Künftige 7-Zip-Versionen müssen das Outputprofil neu vermessen.
- Nicht eindeutig erklärbare Toolfehler verlieren Detail, aber niemals
  Sicherheit: Sie bleiben `TOOL_FAILED`.

ADR-0043 supersediert für die reale 7-Zip-26.02-Runtime ausdrücklich jeden
älteren Verweis auf Parser v1 sowie jede Aussage, stderr-Prosa werde in
fachliche Fehlerliterale klassifiziert. Die unveränderten v1-DTOs bleiben nur
für bereits vorhandene synthetische Verträge gültig.

## Primärquellen

- 7-Zip 26.02 Source-Tag: https://github.com/ip7z/7zip/tree/26.02
- `ArchiveCommandLine.cpp` (`-ba`):
  https://github.com/ip7z/7zip/blob/26.02/CPP/7zip/UI/Common/ArchiveCommandLine.cpp
- `List.cpp` (Header- und Memberausgabe):
  https://github.com/ip7z/7zip/blob/26.02/CPP/7zip/UI/Console/List.cpp
- `ExitCode.h`:
  https://github.com/ip7z/7zip/blob/26.02/CPP/7zip/UI/Common/ExitCode.h
