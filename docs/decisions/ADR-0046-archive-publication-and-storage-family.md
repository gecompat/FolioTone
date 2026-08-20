# ADR-0046: Orthogonale Publication- und Storage-Familien für Archive

**Status:** Akzeptiert

**Datum:** 2026-08-20

**Geltungsbereich:** FG-A-STORAGE-FAMILY, FG-A-FORMAT-LOCK,
S-EBAR-02C, EBAR-05 und EBAR-06

## Kontext

Der bestehende Signaturbeobachter `archive-signature-observer/v1` verwendet
`ArchiveFormatKind` gleichzeitig für Publication-Kinds, direkte
Storage-Familien und äußere Kompressionsformen. Dadurch geht relevante
Signatur-Evidence verloren. Ein ZIP-signiertes EPUB wird nur als `EPUB`, ein
ZIP-signiertes CBZ nur als `CBZ` und ein RAR-signiertes CBR nur als `CBR`
projiziert. Bei CBR ist danach nicht mehr erkennbar, ob der gebundene Handler
RAR4 oder RAR5 ist.

[ADR-0045](ADR-0045-archive-7zip-format-lock.md) verlangt vor dem finalen
7-Zip-Formatlock deshalb orthogonale Achsen. S-EBAR-02B2 hat die direkte
Messmatrix für `ZIP`, `RAR4`, `RAR5`, `SEVEN_Z` und `TAR` inzwischen
hashgebunden abgeschlossen. Der Formatlock darf diese Storage-Familie nicht
aus Suffix, Publication-Kind, Containerklasse oder 7-Zip-Ausgabe erraten.

## Entscheidung

FolioTone führt mit Profil `archive-signature-observer/v2` drei unabhängige,
geschlossene fachliche Achsen und eine geschlossene Suffix-Evidence ein:

| Achse | Öffentliche Literale | Authority |
|---|---|---|
| `ArchivePublicationKind` | `NONE`, `EPUB`, `CBZ`, `CBR` | ausschließlich der normalisierte vollständige Basename-Suffix |
| `ArchiveStorageFamily` | `ZIP`, `RAR4`, `RAR5`, `SEVEN_Z`, `TAR`, `UNKNOWN` | ausschließlich die bereits begrenzt gelesenen Signaturebytes |
| `ArchiveOuterCompressionKind` | `NONE`, `GZIP`, `BZIP2`, `XZ`, `ZSTD` | ausschließlich die bereits begrenzt gelesenen Signaturebytes |

`ArchiveSuffixKind` bewahrt zusätzlich genau eine nicht private, normalisierte
Suffixklasse: `EPUB`, `CBZ`, `CBR`, `ZIP`, `RAR`, `SEVEN_Z`, `TAR`,
`TAR_GZIP`, `TAR_BZIP2`, `TAR_XZ`, `TAR_ZSTD`, `UNSUPPORTED` oder `OTHER`.
Sie ist keine vierte Format-Authority. Sie ermöglicht dem öffentlichen DTO,
Recognition-Status und Achsenkombination auch bei direkter Konstruktion zu
validieren, ohne den privaten Basename zu speichern.

`NONE` bei `ArchivePublicationKind` bedeutet, dass kein freigegebener
Publication-Suffix beobachtet wurde. `NONE` bei
`ArchiveOuterCompressionKind` bedeutet, dass keine freigegebene äußere
Kompressionssignatur beobachtet wurde. `ArchiveStorageFamily.UNKNOWN` ist
keine positive Formatbehauptung.

### Signatur- und Suffixprojektion

Der Basename wird weiterhin bounded, path-frei und ohne Dateisystemzugriff
validiert. Seine Publication-Projektion erfolgt unabhängig von der Signatur:

- `.epub` ergibt `EPUB`;
- `.cbz` ergibt `CBZ`;
- `.cbr` ergibt `CBR`;
- jeder andere Basename ergibt `NONE`.

Die übrige Suffixnormalisierung bleibt geschlossen: `.zip` ergibt `ZIP`;
`.rar`, `.rNN` und `.partN.rar` mit einem bis sechs Ziffern ergeben `RAR`;
`.7z` und `.7z.N` mit drei bis sechs Ziffern ergeben `SEVEN_Z`; `.tar` ergibt
`TAR`; die in ADR-0038 freigegebenen zweiteiligen Wrapper-Suffixe ergeben die
passende `TAR_*`-Klasse. `.arj`, `.cab`, `.exe`, `.iso`, `.wim`, `.gz`,
`.bz2`, `.xz`, `.zst`, `.z01` und `.z02` ergeben `UNSUPPORTED`, alle übrigen
Suffixe `OTHER`. Groß-/Kleinschreibung ändert die Klasse nicht.

Die Signaturebytes setzen unabhängig davon genau eine direkte Storage-Familie
oder genau eine äußere Kompressionsform:

- ZIP-Signaturen setzen Storage `ZIP`;
- die beiden RAR-Signaturen setzen Storage `RAR4` beziehungsweise `RAR5`;
- die 7z-Signatur setzt Storage `SEVEN_Z`;
- ein gültiger TAR-Header setzt Storage `TAR`;
- gzip, bzip2, xz und zstd setzen Storage `UNKNOWN` und die entsprechende
  äußere Kompressionsform;
- unbekannte Bytes setzen Storage `UNKNOWN` und äußere Kompression `NONE`.

Publication-Suffixe dürfen die Storage-Familie nicht überschreiben. Damit
werden insbesondere folgende Bindungen möglich:

| Basename/Signatur | Publication | Storage | Ergebnis |
|---|---|---|---|
| `.epub` + ZIP | `EPUB` | `ZIP` | Publication-Container, strukturelle Bestätigung erforderlich |
| `.cbz` + ZIP | `CBZ` | `ZIP` | Publication-Container, strukturelle Bestätigung erforderlich |
| `.cbr` + RAR4 | `CBR` | `RAR4` | Publication-Container, strukturelle Bestätigung erforderlich |
| `.cbr` + RAR5 | `CBR` | `RAR5` | Publication-Container, strukturelle Bestätigung erforderlich |
| `.zip` + ZIP | `NONE` | `ZIP` | generisches direktes Archiv |
| `.rar` + RAR4/RAR5 | `NONE` | `RAR4`/`RAR5` | generisches direktes Archiv |
| `.7z` + 7z | `NONE` | `SEVEN_Z` | generisches direktes Archiv |
| `.tar` + TAR | `NONE` | `TAR` | generisches direktes Archiv |

Eine fachlich unpassende Kombination, beispielsweise `.cbr` + ZIP oder
`.epub` + RAR5, behält beide beobachteten Achsen und erhält
`SIGNATURE_SUFFIX_MISMATCH`. Der Widerspruch wird nicht durch Umklassifikation
versteckt. Ein unbekannter Signaturetyp mit Publication-Suffix bleibt
`UNKNOWN_SIGNATURE`, Publication bleibt jedoch als Suffix-Evidence erhalten.

`ArchiveContainerClass.PUBLICATION_CONTAINER` wird in v2 genau dann gesetzt,
wenn `ArchivePublicationKind` nicht `NONE` ist. Diese Containerklasse ist eine
abgeleitete Präsentationsachse und keine Storage-Authority. Für Publication-
Container und äußere Kompression bleibt
`structural_confirmation_required=True`.

### Äußere Kompression

gzip-, bzip2-, xz- und zstd-Signaturen setzen vor EBAR-06 niemals Storage
`TAR`. Bei passendem Wrapper-Suffix lautet der Recognition-Status
`OUTER_COMPRESSION_ONLY`; Listing, Integrity, Memberparser und Formatlock
werden nicht aufgerufen. Erst EBAR-06 darf den äußeren Stream privat und
bounded dekomprimieren, die inneren Bytes erneut mit einem eigenen
`archive-signature-observer/v2`-Lauf prüfen und bei tatsächlich gültigem
TAR-Header Storage `TAR` setzen.

Ein Publication-Suffix oder ein unpassender generischer Suffix auf einer
äußeren Kompressionssignatur erzeugt `SIGNATURE_SUFFIX_MISMATCH`; die äußere
Kompressionsform bleibt trotzdem sichtbar und Storage bleibt `UNKNOWN`.
Ein bekannter nackter Einzelstream-Suffix wie `.gz` mit passender äußerer
Signatur bleibt `UNSUPPORTED_FORMAT`. Bei unbekannten Signaturebytes erzeugt
Suffix `UNSUPPORTED` ebenfalls `UNSUPPORTED_FORMAT`, jeder andere Suffix
`UNKNOWN_SIGNATURE`.

Der Recognition-Sum-Type ist damit geschlossen:

| Recognition-Status | Storage | Outer Compression | Suffixbedingung |
|---|---|---|---|
| `MATCHED` | positiv | `NONE` | exakt kompatibler direkter oder Publication-Suffix |
| `SIGNATURE_SUFFIX_MISMATCH` | positiv | `NONE` | jeder mit der direkten Storage-Signatur inkompatible Suffix, einschließlich `UNSUPPORTED` |
| `SIGNATURE_SUFFIX_MISMATCH` | `UNKNOWN` | positiv | Suffix ist weder die exakt passende `TAR_*`-Klasse noch `UNSUPPORTED` |
| `OUTER_COMPRESSION_ONLY` | `UNKNOWN` | positiv | exakt passender zweiteiliger `TAR_*`-Suffix und Publication `NONE` |
| `UNSUPPORTED_FORMAT` | `UNKNOWN` | beliebig | Suffix `UNSUPPORTED` |
| `UNKNOWN_SIGNATURE` | `UNKNOWN` | `NONE` | unbekannte Signaturebytes und Suffix nicht `UNSUPPORTED` |

`ArchiveContainerClass` ist vollständig abgeleitet: Publication ungleich
`NONE` ergibt `PUBLICATION_CONTAINER`; andernfalls ergibt eine positive
direkte Storage-Familie, äußere Kompression oder ein Signature-/Suffix-
Widerspruch `GENERIC_ARCHIVE`; `UNSUPPORTED_FORMAT` ergibt
`UNSUPPORTED_CONTAINER`; der verbleibende unbekannte Fall ergibt
`UNKNOWN_CONTAINER`.

### Profil- und DTO-Vertrag

S-EBAR-02C ersetzt den produktiven Selektor additiv durch
`ArchiveSignatureObservationV2` mit mindestens folgenden Feldern:

- `profile = "archive-signature-observer/v2"`;
- `container_class`;
- `suffix_kind`;
- `publication_kind`;
- `storage_family`;
- `outer_compression_kind`;
- `recognition_status`;
- `inspected_bytes`;
- `structural_confirmation_required`.

Der DTO-Konstruktor validiert die geschlossene Kombination. Insbesondere gilt:

- direkte Storage-Familie und äußere Kompression dürfen nicht gleichzeitig
  positiv sein;
- Publication Kind muss exakt aus `suffix_kind` ableitbar sein;
- `OUTER_COMPRESSION_ONLY` verlangt Storage `UNKNOWN` und eine positive äußere
  Kompressionsform sowie die passende `TAR_*`-Suffixklasse;
- `MATCHED` verlangt eine direkte Storage-Familie und eine mit
  `suffix_kind` kompatible direkte Suffixklasse;
- Publication `EPUB` oder `CBZ` ist bei `MATCHED` nur mit Storage `ZIP`
  zulässig;
- Publication `CBR` ist bei `MATCHED` nur mit Storage `RAR4` oder `RAR5`
  zulässig;
- Publication ungleich `NONE` verlangt
  `ArchiveContainerClass.PUBLICATION_CONTAINER` und strukturelle Bestätigung;
- Storage `UNKNOWN` darf kein direktes Formatprofil auswählen.

`ArchiveFormatKind`, `ArchiveSignatureObservation` und Profil v1 bleiben bis
zum Abschluss der Migration als ausdrücklich legacy-read-only API erhalten.
Sie werden nicht umgedeutet. Neue Runtime-, Parser-, Lock- und Providerpfade
akzeptieren ausschließlich v2.

`structural_confirmation_required=True` bedeutet weiterhin, dass Signature
und Suffix allein die fachliche Publication-Struktur nicht bestätigen. Es
blockiert nicht das bounded read-only Listing eines ansonsten exakt gerouteten
und gelockten Storage-Containers; dieses Listing darf die Publication-Identity
jedoch ebenfalls nicht als bestätigt ausgeben.

### Compatibility und Migration

Eine v1-Beobachtung wird nicht automatisch zur v2-Runtime-Authority. Auch wenn
einige v1-Literale wie `ZIP` oder `TAR` eindeutig erscheinen, bindet v1 weder
die getrennte Publication-Achse noch den neuen Profilvertrag. `CBR` ist ohne
erneute Signaturprüfung grundsätzlich nicht in RAR4 oder RAR5 auflösbar.

S-EBAR-02C migriert deshalb keine gespeicherten oder übergebenen v1-DTOs durch
Raten. Wenn weiterhin unveränderte bounded Headerbytes verfügbar sind, wird
eine neue v2-Beobachtung erzeugt. Fehlen diese Bytes oder weichen
FileObservation/Hash-/Größenbindung ab, endet der spätere Listingstatus
`UNSUPPORTED_FORMAT` und startet keinen 7-Zip-Lauf. Es gibt derzeit
keine persistierte Archive-Signaturtabelle, die ein Datenbank-Backfill
erfordert.

Die neue Compatibility-ID lautet
`archive-publication-storage-compatibility/v1`. Sie wird Bestandteil jeder
späteren Formatlock-, Parser- und Provideridentität. Änderungen an Suffix-,
Signature-, Achsen- oder Kombinationsregeln benötigen eine neue
Compatibility-Version und machen davon abhängige Evidence stale.

### Formatlock- und Providergrenze

Der finale `archive-7zip-format-lock/v1` wird ausschließlich nach
`ArchiveStorageFamily` und Messfall ausgewählt. Publication Kind ist gebundene
Evidence und steuert Publication-Sicherheitsregeln, aber niemals das
7-Zip-Feldprofil. Damit verwenden EPUB/CBZ das gelockte ZIP-Profil und CBR das
jeweilige RAR4- oder RAR5-Profil, sofern Recognition und Matrixdisposition
dies erlauben. Eine noch erforderliche Publication-Strukturprüfung bleibt als
getrennte Evidence sichtbar und wird durch das Listing nicht ersetzt.

`SIGNATURE_SUFFIX_MISMATCH`, `UNKNOWN_SIGNATURE`, Storage `UNKNOWN`, ein
unbekanntes Profil, eine alte Compatibility-ID oder eine nicht als `MEASURED`
akzeptierte Storage-/Fallzelle enden vor Parser- und Toolstart fail-closed.
7-Zip-Ausgabe darf weder Publication noch Storage nachträglich neu
klassifizieren.

Publication-Container bleiben unabhängig von erfolgreichem Listing oder
Integrity fachlich geschützt. EPUB, CBZ und CBR werden nicht als entbehrliche
Verpackung behandelt und erhalten aus diesem Vertrag keine Quarantäne-,
Lösch- oder Metadaten-Schreibfreigabe.

## Umsetzungspaket S-EBAR-02C

S-EBAR-02C darf den hier entschiedenen Vertrag zusammen mit dem finalen
Formatlock mechanisch umsetzen. Der erlaubte Dateibereich wird auf folgende
Dateien begrenzt:

- `src/foliotone/archive/signatures.py`;
- `src/foliotone/archive/__init__.py`;
- `src/foliotone/archive/sevenzip_slt.py`;
- `src/foliotone/archive/sevenzip.py`;
- `tests/unit/test_archive_signatures.py`;
- die bestehenden fokussierten SevenZip-Parser-/Command-Tests.

Diese Liste supersediert ausschließlich die S-EBAR-02C-Dateiliste aus
ADR-0045, indem sie `src/foliotone/archive/__init__.py` ergänzt. Die Ergänzung
ist erforderlich, damit die neuen öffentlichen Enum- und DTO-Verträge über
dieselbe Package-Grenze wie die v1-Typen exportiert werden. Alle anderen
Scopegrenzen aus ADR-0045 bleiben unverändert; eine weitere Erweiterung ist
nicht erlaubt.

S-EBAR-02C führt keine Provider-, Runner-, Persistenz-, Wrapper-
Dekompressions-, Extraction-, Secret- oder Source-Mutation ein. Wrapper
werden vor dem ersten Parserchunk abgewiesen. Ein No-Provider-Call-Nachweis
gehört weiterhin zu EBAR-05.

Die fokussierte Abnahme umfasst mindestens:

- EPUB/CBZ mit ZIP und CBR jeweils mit RAR4 und RAR5;
- generische ZIP/RAR4/RAR5/7z/TAR-Fälle;
- jede direkte Publication-/Storage-Kreuzkombination als sichtbaren Mismatch;
- ZIP-Signatur mit nacktem `.gz` als Mismatch sowie gzip-Signatur mit `.exe`
  eindeutig als `UNSUPPORTED_FORMAT`;
- alle vier passenden Wrapper, falsche Wrapper-Suffixe, nackte
  Einzelstream-Suffixe und unbekannte Signaturebytes;
- Groß-/Kleinschreibung sowie alle erlaubten Volume-Suffixformen;
- direkte DTO-Konstruktion für jede gültige Recognition-Shape und negative
  Tests für inkonsistente Suffix-, Publication-, Storage-, Outer-Compression-,
  Containerklassen- und Structural-Confirmation-Kombinationen;
- unveränderte v1-Fixtures und v1-API-Lesbarkeit;
- Wrapper-Ablehnung vor dem ersten Parserchunk und path-freie
  Repräsentationen ohne Basename.

## Folgen

- FG-A-STORAGE-FAMILY ist akzeptiert; der nächste Gate-Schritt ist der finale
  FG-A-FORMAT-LOCK.
- Publication- und Storage-Evidence bleiben gleichzeitig erhalten, ohne
  Suffix- oder Tooloutput als Signature-Authority zu verwenden.
- Bestehende v1-Aufrufer bleiben lesbar, dürfen aber keinen neuen
  Produktionslauf autorisieren.
- Die zusätzliche äußere Kompressionsachse verhindert, dass Wrapper vor
  EBAR-06 still als TAR behandelt werden.
- Der Vertrag erweitert keine Schreib-, Extraction-, Secret-, Persistenz-
  oder W10-Berechtigung.

## Nachweise

- [ADR-0038](ADR-0038-safe-archive-container-analysis.md)
- [ADR-0044](ADR-0044-archive-format-profile-measurement.md)
- [ADR-0045](ADR-0045-archive-7zip-format-lock.md)
- `src/foliotone/archive/signatures.py`
- `tests/unit/test_archive_signatures.py`
- `tests/fixtures/archive/7zip-26.02/v2/fixture-manifest.json`
- `tests/fixtures/archive/7zip-26.02/v2/expected-measurement.json`
