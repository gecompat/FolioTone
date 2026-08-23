# Begrenzter EPUB-Titelwriter

Diese Anleitung gilt ausschließlich für
`ebook-source-metadata-write/epub3-title-replace/v1`. Das Profil ersetzt in
genau einem reviewten EPUB-3-Plan genau einen `title`-Wert. Es ist keine
allgemeine Metadaten-, Reparatur-, Batch-, Calibre-, Sidecar-, Rename- oder
Archiv-Schreibschnittstelle.

Der Standard-Compose-Betrieb bindet Source Media weiterhin read-only ein und
öffnet diesen Writer nicht. Ein Operator muss den engen Schreibzugriff lokal
und bewusst bereitstellen. FolioTone installiert während Authorize, Execute,
Recover oder Status keine Werkzeuge und verwendet keinen Netzwerkzugriff.

## Voraussetzungen

Vor `metadata-write-authorize` müssen alle folgenden Bedingungen erfüllt sein:

- Linux x86_64 mit glibc und eine unterstützte lokale ext-, Btrfs-, tmpfs- oder
  XFS-Instanz;
- ein bereits persistierter, aktueller und reviewter
  `MetadataCorrectionPlan` für exakt das feste Profil;
- dieselbe reguläre Source-Datei, Observation und derselbe vollständige
  SHA-256 wie im Plan;
- EPUBCheck-5.3.0- und EPUB-3-Conformance-Evidence für denselben Input;
- die gelockte E-Book-Toolchain mit `ebook-meta`, `ebook-convert`,
  `calibre-debug`, Java und `epubcheck.jar`;
- eine beschreibbare Runtime-Datenbank und ein vorhandener owner-only
  Stagingordner;
- eine owner-only Capability-Konfiguration sowie disjunkte Source- und
  Recoveryordner derselben Filesysteminstanz;
- ein exklusiver FolioTone-Operator für denselben `ScanRoot`.

Authorize schlägt fail-closed fehl, wenn eine dieser Bedingungen nicht
beweisbar ist. Es erzeugt dann weder Authorization noch Run und mutiert die
Source nicht.

## Runtime-Konfiguration

Die Bedienkommandos nehmen keine Datenbank- oder Dateipfade als Argumente an.
Der lokale Prozess erhält stattdessen diese Runtime-Konfiguration:

| Variable | Bedeutung | Standard |
|---|---|---|
| `FOLIOTONE_DATABASE` | Beschreibbare Runtime-SQLite-Datenbank; Status öffnet sie strikt read-only. | `/data/foliotone.db` |
| `FOLIOTONE_METADATA_WRITE_STAGE_ROOT` | Vorhandener, kanonischer, owner-only Stagingordner außerhalb von Source und Recovery. | `/data/foliotone-metadata-write-stage` |
| `FOLIOTONE_METADATA_WRITE_CAPABILITIES_FILE` | Absolute Datei mit der privaten Capability-Zuordnung. | keiner |
| `FOLIOTONE_EBOOK_META` | Fester `ebook-meta`-Executable. | `ebook-meta` |
| `FOLIOTONE_EBOOK_CONVERT` | Fester `ebook-convert`-Executable. | `ebook-convert` |
| `FOLIOTONE_CALIBRE_DEBUG` | Fester `calibre-debug`-Executable. | `calibre-debug` |
| `FOLIOTONE_JAVA` | Fester Java-Executable. | `java` |
| `FOLIOTONE_EPUBCHECK_JAR` | Lokaler EPUBCheck-JAR. | `epubcheck.jar` |

Die Capability-Datei ist eine reguläre POSIX-Datei des aktuellen Users mit
Mode `0600`, genau einem Hardlink und ohne Symlink-/Reparse-Komponenten. Sie
ist auf 64 KiB und 128 Einträge begrenzt. Ein syntaktisches Beispiel mit
rein fiktiven IDs und Containerpfaden lautet:

```json
{
  "capabilities": [
    {
      "metadata_write_capability_id": "10000000-0000-0000-0000-000000000001",
      "scan_root_id": "20000000-0000-0000-0000-000000000001",
      "scan_root_directory": "/operator/source",
      "recovery_directory": "/operator/recovery",
      "writer_profile": "ebook-source-metadata-write/epub3-title-replace/v1"
    }
  ]
}
```

Alle Source- und Recoveryordner der Datei müssen paarweise disjunkt sein. Der
Source- und Recoveryordner eines Eintrags müssen auf derselben
Filesysteminstanz liegen. Der Runtimeprozess benötigt Schreibzugriff nur auf
die konkret gemounteten Capability-Bereiche, Staging und Datenbank. Ein
pauschal beschreibbares Collection-Mount ist nicht vorgesehen.

## Bedienfolge

Die Platzhalter stehen für opaque Werte aus der lokalen Plan- und
Capability-Verwaltung. Shell-History enthält damit keine Pfade oder
Metadatenwerte, aber Plan- und Authorization-IDs; sie ist entsprechend privat
zu behandeln.

```text
foliotone metadata-write-authorize \
  --plan-id <Plan-ID> \
  --plan-content-hash <64-stelliger-kleingeschriebener-SHA-256> \
  --capability-id <Capability-ID> \
  --output json
```

Die ausgegebene Authorization ist höchstens 15 Minuten gültig. Execute muss
dieselben Binder plus die Authorization-ID erhalten:

```text
foliotone metadata-write-execute \
  --plan-id <Plan-ID> \
  --plan-content-hash <Plan-Content-Hash> \
  --capability-id <Capability-ID> \
  --authorization-id <Authorization-ID> \
  --output json
```

Das Kommando schreibt den einzig zulässigen Bestätigungssatz auf `stderr` und
liest genau eine begrenzte Zeile von `stdin`:

```text
CONFIRM METADATA WRITE <Authorization-ID>
```

Der Satz darf weder als Argument noch als Environment-Variable übergeben
werden. Abweichende Groß-/Kleinschreibung, zusätzliche Zeichen oder eine
andere Authorization-ID erzeugen keinen Run.

Nach dem Exchange verifiziert der Operator die tatsächlich geschriebene
Source, bewahrt das Original im Recoverybereich, führt einen neuen
inkrementellen Vollscan mit einem Worker aus und baut `CollectionState` neu.
Nur eine passende immutable Reconciliation schließt den Run als `VERIFIED`.
Sie startet keine unbeschränkte automatische Neuanalyse; ältere Evidence wird
gemäß `CollectionState` als `CURRENT`, `STALE`, `UNSCOPED` oder `MISSING`
projiziert.

## Status und Recovery

Status greift weder auf Source Media zu noch migriert er die Datenbank:

```text
foliotone metadata-write-status --run-id <Run-ID> --output json
```

Ein Retry von Execute darf nur denselben, noch sicher fortsetzbaren Run
fortsetzen. Meldet Execute `RECOVERY_REQUIRED`, wird ausschließlich der
gebundene Recovery-Pfad aufgerufen:

```text
foliotone metadata-write-recover \
  --plan-id <Plan-ID> \
  --plan-content-hash <Plan-Content-Hash> \
  --capability-id <Capability-ID> \
  --authorization-id <Authorization-ID> \
  --output json
```

Recovery mutiert nur exakt bekannte Hashverteilungen derselben bereits
autorisierten Operation. Eine uneindeutige physische Verteilung endet ohne
weitere Mutation bei `MANUAL_RECOVERY_REQUIRED`. Nach Wiederherstellung des
Originals folgt derselbe Scan-/`CollectionState`-Abschluss mit Outcome
`RECOVERED`; daraus entsteht kein `VERIFIED`.

`VERIFIED` ist für diese Authorization irreversibel. Rollback, Purge und
Retention bleiben eigene, nicht durch diese Anleitung freigegebene
Operationen. Recovery- und Stagingartefakte werden nicht automatisch
gelöscht.
