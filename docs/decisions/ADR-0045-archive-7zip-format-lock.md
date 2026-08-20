# ADR-0045: Kollisions- und Erweiterungsgate vor dem 7-Zip-Formatlock

**Status:** Akzeptiert

**Datum:** 2026-08-20

**Geltungsbereich:** S-EBAR-02B2, FG-A-STORAGE-FAMILY,
FG-A-FORMAT-LOCK, S-EBAR-02C und EBAR-05

## Kontext

[ADR-0044](ADR-0044-archive-format-profile-measurement.md) verlangt vor einem
Produktionsparser eine reale, formatgebundene Messung der 7-Zip-26.02-Ausgabe.
S-EBAR-02B hat dafür
`tests/fixtures/archive/7zip-26.02/v1/expected-measurement.json` mit Profil
`archive-7zip-format-measurement/v1` eingecheckt. Die SHA-256 dieser
Beobachtung lautet
`40a6ee8843390cee75712461495c0173d47247696800976c21cc7134ffd3b89e`.

Das Review zeigt, dass diese Messung noch keine Lockgrundlage ist:

1. Je Storage-Familie wurde nur ein erfolgreicher, unverschlüsselter
   Regular-File-Happy-Path beobachtet. Directory-, Encryption-Matrix- und
   positive Linkfälle fehlen.
2. `measure_format_profiles.py` behandelt die 7-Zip-`VT_BOOL`-Felder
   `Commented`, `Split Before` und `Split After` nicht als Boolfelder. Ihre
   beobachteten `-`-Werte wurden deshalb fälschlich als
   `TECHNICAL_NONEMPTY_DISCARDED` statt `BOOL_MINUS` klassifiziert.
3. Die bestehende `ArchiveFormatKind`-Achse vermischt Publication-Kinds
   `EPUB`, `CBZ`, `CBR` mit den tatsächlichen Storage-/Handlerfamilien. Ein CBR
   verliert dadurch beispielsweise die für ein RAR4- oder RAR5-Profil nötige
   Handleridentität.
4. Leere Linkfelder belegen nur den negativen Fall. Sie belegen weder die
   positive Linkgrammatik noch die sichere private Behandlung eines Linkziels.

Ein im ersten Review aus der Happy-Path-Messung abgeleiteter JSON-Kandidat mit
SHA-256
`fdebe71a9d95170733a95d735ecbc439324d49ab8e298042d77c862acc0d4b34`
ist deshalb ausschließlich diagnostische, nicht autoritative Review-Evidence.
Seine damalige Selbstbezeichnung `archive-7zip-format-lock/v1` ist verworfen:
Es existiert derzeit weder ein akzeptierter Produktionslock noch ein
maschinenlesbares Lockartefakt. Der Kandidat darf nicht von Runtime, Parser,
Workflow oder Tests als Lock, Golden oder Freigabe konsumiert werden.

## Entscheidung

ADR-0045 akzeptiert die nachfolgende Korrekturfolge, **nicht**
FG-A-FORMAT-LOCK. EBAR-05 bleibt gestoppt und S-EBAR-02C ist nicht startklar:

```text
S-EBAR-02B2 erweiterte und korrigierte Measurement-Evidence
    -> FG-A-STORAGE-FAMILY orthogonale Publication-/Storage-Achsen
    -> FG-A-FORMAT-LOCK finaler maschinenlesbarer Lock
    -> S-EBAR-02C formatgebundener Produktionsparser
    -> EBAR-05 reales unverschlüsseltes Listing und Integrity
```

### S-EBAR-02B2: Measurement-Erweiterung und Klassifikationskorrektur

S-EBAR-02B2 erstellt additiv
`archive-7zip-format-measurement/v2`. V1 und seine SHA-256 bleiben unverändert
als diagnostische Vorgeschichte lesbar. Erlaubt sind ausschließlich ein neuer
Fixture-/Measurement-Unterbaum
`tests/fixtures/archive/7zip-26.02/v2/**`, der bestehende lokale Messhelper,
seine fokussierten Tests und die bestehende geschützte Archive-Image-
Workflowdatei. Das Paket implementiert keinen Produktionsparser oder Provider.

#### Erzeugungs- und Provenienzvertrag

Die synthetischen unverschlüsselten v2-Fixtures müssen aus festen öffentlichen
Sourcebytes mit gebundener SHA-256 zweimal unabhängig byteidentisch entstehen.
Ihr Generatorprofil bindet den relativen Namen, einen festen Arbeitsordner,
die vollständige Eingabereihenfolge, Dateimodus und Attribute, `TZ=UTC`,
`-mmt=1` sowie Format, Methode, Kompressions- und Zeitoptionen explizit. Ein
fester `SOURCE_DATE_EPOCH` ist nur Eingabe für das Staging: Nach der letzten
Dateisystemmutation setzt der Generator daraus den Änderungszeitpunkt; er
verlässt sich nicht darauf, dass 7-Zip die Environment Variable auswertet.
Creation- und Access-Zeit werden mit `-mtc=off` und `-mta=off` ausgeschlossen.
Das Profil muss entweder den festen Änderungszeitpunkt mit `-mtm=on` schreiben
oder ihn mit `-mtm=off` vollständig ausschließen. Ein rekursiv vom
Dateisystem gelieferter, ungeordneter Input ist keine Generator-Authority.

Dieser Zweilaufvertrag gilt nicht für die Datenverschlüsselungsfälle von ZIP
und `SEVEN_Z`. Der gepinnte 7-Zip-26.02-Quellstand erzeugt bei ZIP entweder
einen zufälligen traditionellen Crypto-Header oder bei AES ein zufälliges
Salt. Der 7z-AES-Encoder erzeugt einen zufälligen Initialisierungsvektor. Die
Ausgabe ist deshalb auch bei identischen Sourcebytes, Metadaten, Optionen und
Reihenfolge absichtlich nicht byteidentisch reproduzierbar. Der 7z-Startheader
enthält keine eigene Uhrzeit oder Zufallsquelle; abweichende Offsets und CRCs
sind nur Folge der randomisierten verschlüsselten Daten und Coder Properties.

Eine ZIP-/7z-Zelle `ALL_ENCRYPTED` oder `MIXED` darf dennoch `MEASURED`
erhalten, aber nur mit einmalig kuratierten, eingecheckten öffentlichen
synthetischen Fixturebytes. Gebunden werden mindestens:

- Fixture-SHA-256 und eine ausdrückliche Redistributionserklärung;
- exakter Image-Manifest-Digest, 7-Zip-Version und Generatorprofil;
- kanonisches schreibendes Generator-Command-Profil mit eigener SHA-256 über
  alle festen, nicht geheimen Argumentbytes;
- feste öffentliche Sourcebytes und deren SHA-256;
- Arbeitsordner-, Namens-, Reihenfolge-, Modus-, Attribut-, Zeit-, Methoden-,
  Kompressions- und Threadingvertrag;
- vollständige feste Generation Shape einschließlich Verschlüsselungsmethode;
- ein reviewtes, festes, ausdrücklich nicht geheimes öffentliches
  Fixture-Passwort, das ausschließlich bei der einmaligen Erzeugung verwendet
  wird.

Das öffentliche Fixture-Passwort ist weder `SecretHandle` noch Nachweis eines
sicheren Secret-Kanals. Es darf nur im isolierten Kuratorenlauf zur
Fixture-Erzeugung an das schreibende 7-Zip-Kommando übergeben werden. Runtime,
Messhelper und geschützter Measurement-Workflow übergeben kein Passwort über
argv, Environment, stdin oder einen anderen Kanal. Sie führen ausschließlich
das bereits gebundene passwortlose `l -slt` aus, regenerieren die
verschlüsselten Fixtures nicht und vergleichen zwei Messungen derselben Bytes.
Ein Produktions-Passwortversuch, Integrity-Lauf oder Secretgebrauch wird
daraus nicht freigegeben.

`MIXED` verwendet für ZIP und 7z genau eine gebundene zweistufige Shape: Ein
neues Archiv erhält zuerst das Klartext-Datenmember und danach in einem
separaten Update das verschlüsselte Datenmember. Namen, Stufenreihenfolge und
Optionen sind fest. 7z-Datenverschlüsselung setzt in beiden
Verschlüsselungsfällen explizit `-mhe=off`; Header-Verschlüsselung gehört nicht
zu dieser Matrix. Ein gepatchter oder anderweitig gesetzter Zufallsgenerator,
ein fester Crypto-Seed und eine Abweichung vom gepinnten 7-Zip-Binary sind als
Reproduzierbarkeitsabkürzung verboten.

Fehlt für eine verschlüsselte Zelle auch nur ein Bestandteil dieser
Erzeugungs-, Sicherheits-, Hash-, Image-, Tool-, Shape- oder
Redistributionsprovenienz, lautet ihre Disposition `EVIDENCE_UNAVAILABLE`.
Eine zufällige Zweiterzeugung darf weder den eingecheckten Hash aktualisieren
noch als Drift des gebundenen Fixtures umgedeutet werden.

Die Boolklassifikation muss mindestens `Commented`, `Split Before` und
`Split After` in die feste `VT_BOOL`-Menge aufnehmen. Nur `+` und `-` sind
zulässig und werden als `BOOL_PLUS` beziehungsweise `BOOL_MINUS` gemessen;
leer oder jeder andere Wert ist fail-closed. Positive `Symbolic Link`,
`Hard Link` und `Copy Link`-Werte werden als private, sofort verworfene Werte
klassifiziert; kein Linkziel gelangt in Manifest, Digest, Log oder Artefakt.

Für jede direkte Storage-Familie `ZIP`, `RAR4`, `RAR5`, `SEVEN_Z` und `TAR`
muss jede Zelle der folgenden Matrix geschlossen disponiert werden:

| Fallachse | ZIP | RAR4 | RAR5 | SEVEN_Z | TAR |
|---|---|---|---|---|---|
| unverschlüsseltes Regular File | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |
| unverschlüsseltes Directory | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |
| ausschließlich verschlüsselte Datenmember | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |
| gemischte Klartext-/verschlüsselte Datenmember | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |
| verschlüsseltes Directory neben Klartextdaten | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |
| positiver Symbolic-Link-Fall | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |
| positiver Hard-Link-Fall | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |
| positiver Copy-Link-Fall | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich | Disposition erforderlich |

`Disposition erforderlich` darf genau eines bedeuten:

- `MEASURED`: rechtmäßig und sicher erzeugte oder redistribuierbare,
  hashgebundene Fixturebytes wurden mit dem gepinnten Runtimevertrag gemessen;
- `FORMAT_UNSUPPORTED`: eine gepinnte Handler-/Formatspezifikation belegt,
  dass die Kombination nicht darstellbar ist;
- `EVIDENCE_UNAVAILABLE`: Recht, sichere Erzeugbarkeit oder belastbare
  Primärevidence ist nicht belegbar.

Ein bloß fehlendes Fixture, ein Skip oder eine Annahme ist keine Disposition.
`FORMAT_UNSUPPORTED` und `EVIDENCE_UNAVAILABLE` erzeugen keine synthetische
Feldfolge. Sie werden format- und fallgebunden als fail-closed Capability-
Grenze in den späteren Lock übernommen. Die EBAR-05-Abnahme darf dann nur die
explizit gemessenen Kombinationen als unterstützt behaupten; alle anderen
enden vor einer fachlichen Statusableitung geschlossen.

Die vier äußeren gzip-, bzip2-, xz- und zstd-Streams werden in v2 erneut als
Driftbeobachtung gebunden. Sie bleiben bis EBAR-06
`OUTER_COMPRESSION_ONLY`, ohne produktiven Listing-/Integrity-Provider und
ohne Member-Evidence.

### FG-A-STORAGE-FAMILY: orthogonale Routingachsen

Vor dem finalen Formatlock akzeptiert ein separates Docs-only-Frontier-Gate
einen versionierten Storage-Family-Vertrag. Er muss mindestens folgende
orthogonale Achsen festlegen:

- Publication Kind: `NONE`, `EPUB`, `CBZ`, `CBR`;
- direkte Storage Family: `ZIP`, `RAR4`, `RAR5`, `SEVEN_Z`, `TAR`, andernfalls
  `UNKNOWN`.

ZIP-signierte EPUB-/CBZ-Kandidaten behalten Publication Kind `EPUB`
beziehungsweise `CBZ` und Storage Family `ZIP`. Ein CBR-Kandidat behält
Publication Kind `CBR`, während die Signatur unabhängig Storage Family `RAR4`
oder `RAR5` setzt. Generische Archive verwenden Publication Kind `NONE`.
Suffix, Publication Kind, Containerklasse oder 7-Zip-Output dürfen die
Storage-Familie nicht überschreiben oder erraten. Ein Widerspruch bleibt
Evidence und fail-closed.

Äußere Kompressionssignaturen erhalten vor EBAR-06 keine innere Storage Family
`TAR`; sie bleiben `OUTER_COMPRESSION_ONLY` mit direkter Storage Family
`UNKNOWN`. Erst private begrenzte Dekompression und erneute Signaturprüfung
dürfen später `TAR` setzen.

Das Gate bestimmt Compatibility, DTO-/Profilversionen und die Migration der
bisherigen `ArchiveFormatKind`-Lesepfade. Bis es akzeptiert ist, darf weder ein
Lock noch S-EBAR-02C allein aus `ArchiveFormatKind` ein Produktionsprofil
wählen.

### Finaler FG-A-FORMAT-LOCK

Erst nach akzeptierter Measurement-v2- und Storage-Family-Evidence entscheidet
ein weiteres Docs-only-Frontier-Gate den endgültigen
`archive-7zip-format-lock/v1`. Dessen Acceptance erfordert mindestens:

- exakte geordnete Pflicht-, optionale, leere und verworfene Feld-/Value-
  Class-Folgen je gemessener Storage-Family-/Fall-Kombination;
- explizite fail-closed Capability-Einträge für jede nicht gemessene
  Matrixzelle;
- Link-, Directory-, Encryption-, Empty-, Discard-, Compatibility- und Stale-
  Semantik mit Mess- oder gepinntem Primärquellennachweis;
- das eingecheckte maschinenlesbare Artefakt
  `packaging/archive/7zip-26.02/archive-format.lock.json` und dessen getrennte
  Digestdatei `packaging/archive/7zip-26.02/archive-format.lock.sha256`;
- einen geschützten `verify-only`-Workflowcheck, der Measurement-, Storage-
  Family-, Tool-, Image-, Command-, Fixture- und Lockidentitäten verifiziert.

Der Workflow darf weder Lockartefakt noch Digest aus einer Messung generieren,
aktualisieren oder bei Drift akzeptieren. Eine Änderung benötigt Review, ein
neues ADR und bei Vertragsänderung neue Profilversionen.

### S-EBAR-02C und EBAR-05

S-EBAR-02C darf erst nach beiden akzeptierten Frontier-Gates beginnen. Sein
vorläufiger Dateiscope umfasst ausschließlich
`src/foliotone/archive/signatures.py`,
`src/foliotone/archive/sevenzip_slt.py`,
`src/foliotone/archive/sevenzip.py` sowie die bestehenden fokussierten
Signatur-, Parser- und Command-Tests. Der endgültige Lock darf diesen Scope
weiter verengen.

S-EBAR-02C implementiert Publication-/Storage-Routing und den final gelockten
Parser additiv. Für die vier Wrapper testet es ausschließlich die Ablehnung
**vor dem Verbrauch des ersten Parserchunks**. Ein No-Provider-Call-Test gehört
zu EBAR-05, weil S-EBAR-02C keinen Provider implementiert. Provider-, Runner-,
Lifecycle-, Persistenz-, Wrapper-Dekompressions-, Extraction- und Secret-Code
bleiben außerhalb des Pakets.

EBAR-05 akzeptiert eine Storage-Family-/Fall-Kombination nur, wenn der finale
Lock sie mit `MEASURED` Evidence freigibt. Bei `FORMAT_UNSUPPORTED`,
`EVIDENCE_UNAVAILABLE`, unbekanntem Routing oder Lockdrift startet es keinen
Listing-/Integrity-Lauf und leitet weder Member-, Link-, Directory-,
Encryption- noch Integrity-Evidence ab.

## Compatibility und Superseding

Diese ADR supersediert die Annahme aus ADR-0044, dass das Happy-Path-
Measurement v1 unmittelbar für FG-A-FORMAT-LOCK genügt. Sie supersediert auch
alle im aktuellen Branch formulierten Aussagen, FG-A-FORMAT-LOCK sei bereits
abgeschlossen oder S-EBAR-02C sei startklar.

Sie supersediert außerdem ADR-0044s allgemeine Pflicht zur byteidentischen
synthetischen Neuerzeugung ausschließlich für die verschlüsselten ZIP-/7z-
Zellen `ALL_ENCRYPTED` und `MIXED` des v2-Korpus. Der gesamte v1-Korpus und
alle übrigen synthetisch erzeugten v2-Fixtures behalten die deterministische
Zweilaufpflicht. Die Ausnahme erlaubt nur die oben definierten einmalig
kuratierten und hashgebundenen Bytes; sie lockert weder Mess-, Privacy-,
Redistributions- noch Runtimegrenzen.

ADR-0043-Statusvorrang, stderr-/Exitcode-Grenzen, Raw-Discard und byteleere
Archive bleiben unverändert. ADR-0038/ADR-0039 behalten Format-Allowlist,
Secret-Sperre, Sandbox, Reuse, Persistenz und W10-Grenzen. Die neue Storage-
Achse präzisiert das Routing, ohne Publication-Kinds umzudeuten. Für Wrapper
bleibt ADR-0044 bis EBAR-06 maßgeblich.

## Folgen

- ADR-0045 ist akzeptiert; FG-A-FORMAT-LOCK ist ausdrücklich noch offen.
- S-EBAR-02B bleibt als diagnostische Happy-Path-Messung erhalten. Der nächste
  Schritt ist S-EBAR-02B2, nicht S-EBAR-02C.
- Der SHA-256 `fdebe71...` bezeichnet nur den verworfenen Vorabkandidaten und
  ist keine Runtime- oder Acceptance-Authority.
- Fehlende rechtmäßige oder sichere Evidence verkleinert die spätere
  EBAR-05-Unterstützung; sie wird niemals durch erfundene Fixtures oder
  Feldprofile ersetzt.
- Kryptographisch randomisierte ZIP-/7z-Fixtures werden im geschützten Gate
  nur als eingecheckte hashgebundene Bytes erneut vermessen und niemals
  regeneriert; ihr öffentliches Fixture-Passwort ist keine Secret- oder
  Runtimefreigabe.
- S-EBAR-02C und EBAR-05 bleiben bis zur vollständigen Gatefolge blockiert.

## Nachweise

- [ADR-0043](ADR-0043-archive-machine-output-and-status-classification.md)
- [ADR-0044](ADR-0044-archive-format-profile-measurement.md)
- `tests/fixtures/archive/7zip-26.02/v1/fixture-manifest.json`
- `tests/fixtures/archive/7zip-26.02/v1/expected-measurement.json`
- `tests/fixtures/archive/7zip-26.02/v1/README.md`
- `packaging/archive/7zip-26.02/measure_format_profiles.py`
- gepinnte 7-Zip-26.02-Quellen: `CPP/7zip/Crypto/ZipCrypto.cpp`,
  `CPP/7zip/Crypto/WzAes.cpp`, `CPP/7zip/Crypto/7zAes.cpp`,
  `CPP/7zip/Crypto/RandGen.cpp`, `CPP/7zip/Archive/7z/7zOut.cpp`
