# ADR-0033: Read-only `calibredb`-Library-Reconciliation

- Status: Accepted
- Datum: 2026-08-18

## Kontext

EB-07 vergleicht einen abgeschlossenen FolioTone-Scan mit einer konfigurierten
calibre-Bibliothek. `calibredb` stellt dafür maschinenlesbare Leseoperationen
bereit, kann dieselbe Bibliothek jedoch auch verändern, Formate exportieren und
Metadaten in Dateien schreiben. Eine generische Subcommand- oder
Optionsweitergabe würde deshalb die W10-Sicherheitsgrenze verletzen.

Calibre-Datensätze, ihre Metadaten und ihre Dateizuordnungen sind Evidence.
Sie ersetzen weder `FileRecord`, `Work`, `Edition`, `Agent` noch eine
FolioTone-Entscheidung. Die numerische calibre-ID ist nur innerhalb der
konfigurierten Bibliothek und des erfassten Snapshots aussagekräftig.

Die Entscheidung beruht auf der offiziellen calibre-9.13.0-Dokumentation für
`calibredb`. Diese dokumentiert `list --for-machine` als JSON-Ausgabe,
`show_metadata --as-opf` als OPF-Ausgabe und `list_categories --csv` als
CSV-Ausgabe. Dieselbe Dokumentation beschreibt unter anderem `add`, `remove`,
`add_format`, `remove_format`, `set_metadata`, `export`, `restore_database`,
`backup_metadata` und `embed_metadata` als schreibende oder exportierende
Operationen.

## Toolmanifest und feste Command Shapes

Der Adapter besitzt genau ein Manifest:

| Feld | Wert |
|---|---|
| Provider-ID | `calibre-library` |
| Adapter-Version | `calibredb-library/1` |
| Capability | `LIBRARY_READ` |
| Executable | `calibredb` |
| akzeptierte Exitcodes | ausschließlich `0` |
| minimale calibre-Version | `9.10.0` |
| Versionsermittlung | ausschließlich `calibredb --version` |
| Source-Verhalten | read-only |

Unbekannte Versionsausgaben und ältere Versionen werden vor dem Öffnen der
Bibliothek abgewiesen. `CALIBRE_CONFIG_DIRECTORY` zeigt auf ein privates,
leeres Tool-Workspace-Verzeichnis. Remote Content Server, `--username`,
`--password`, `--timeout` als frei wählbare Option und URL-Werte für
`--library-path` sind in `calibredb-library/1` nicht zulässig. Der
Bibliothekspfad stammt ausschließlich aus lokaler Runtime-Konfiguration und
wird weder persistiert noch ausgegeben.

Der öffentliche Adapter nimmt keine Argumentliste, kein Subcommand und keinen
Suchausdruck entgegen. Er erzeugt ausschließlich die folgenden Shapes; `N`
ist eine intern validierte positive Ganzzahl, `I` eine nichtnegative calibre-ID
und `P` der lokal konfigurierte Bibliothekspfad:

```text
calibredb --version

calibredb list --library-path P --for-machine
  --fields authors,author_sort,cover,formats,identifiers,isbn,languages,last_modified,pubdate,publisher,series,series_index,size,tags,timestamp,title,uuid
  --prefix __FOLIOTONE_CALIBRE_ROOT__ --sort-by id --ascending
  --search id:>I --limit N

calibredb search --library-path P --limit 2 id:=I

calibredb show_metadata --library-path P --as-opf I

calibredb list_categories --library-path P --csv --dialect unix
  --categories authors,series,tags,languages,publisher
```

Die Inventory-Seite verwendet ausschließlich den intern erzeugten Ausdruck
`id:>I`; die Exact-ID-Prüfung ausschließlich `id:=I`. Eine Seite enthält
höchstens 500 Records. Der Prozess setzt pro Aufruf ein Timeout von 120
Sekunden. Maximale stdout-Größen sind 64 MiB für `list`, 1 MiB für `search`,
4 MiB je `show_metadata` und 16 MiB für `list_categories`. stderr wird wie in
der bestehenden Tool-Runtime begrenzt und nicht als fachliche Evidence
interpretiert. Überschrittene Grenzen, malformed JSON/CSV/XML, doppelte oder
nicht streng steigende IDs und ein anderer Exitcode machen die jeweilige
Erfassung ungültig.

Die Pseudowurzel `__FOLIOTONE_CALIBRE_ROOT__` ersetzt den absoluten
Bibliothekspfad in `formats`. Der Parser akzeptiert ausschließlich Pfade unter
dieser Pseudowurzel, normalisiert sie relativ und lehnt absolute Pfade,
Traversal, Device Paths, Alternate Data Streams und Root Escape ab. Rohes
stdout bleibt ein privates Runtime-Artefakt außerhalb von Git und erscheint
nicht in CLI- oder Fehlerausgaben.

Alle anderen Subcommands und jede zusätzliche Option schlagen geschlossen
fehl. Dies gilt insbesondere für `add`, `remove`, `add_format`,
`remove_format`, `set_metadata`, `set_custom`, `add_custom_column`,
`remove_custom_column`, `saved_searches add`, `saved_searches remove`,
`embed_metadata`, `backup_metadata`, `restore_database`, `export`, `catalog`,
`clone`, `fts_index enable`, `fts_index disable` und `fts_index reindex`.
Auch `check_library` ist in v1 nicht freigegeben, weil die eigene begrenzte
Reconciliation die benötigten Finding-Verträge liefert und keine zweite,
versionsabhängige Reportschnittstelle benötigt.

## Snapshot- und Lineage-Vertrag

Ein `CalibreLibrarySnapshot` bindet sich an genau einen `ScanRoot`, dessen
explizit neuesten abgeschlossenen EBOOK-`ScanRun`, das Adapterprofil
`calibre-library-snapshot/v1`, Tool- und Parser-Version, einen opaken
Bibliotheks-Identitätsdigest sowie Start-, Abschluss- und Statuszeitpunkt.
Der Digest wird aus einer Runtime-Konfigurations-ID und nicht aus dem
physischen Pfad gebildet. Nur `COMPLETED`-Snapshots dürfen Reconciliation-
Findings speisen.

Die Inventory-Seiten werden per calibre-ID keyset-paginiert. Vor und nach den
einzelnen OPF-Abfragen wird dieselbe vollständige, begrenzte Inventory-
Projektion erfasst. Ein kanonischer Digest über ID, UUID, `last_modified`,
Formattypen und relative Formatpfade muss identisch sein. Andernfalls endet der
Snapshot als `INVALIDATED`; seine Teil-Evidence bleibt auditierbar, wird aber
nicht reconciled. Diese Prüfung ist eine Konsistenzgrenze des Adapters und
keine Sperre gegen externe calibre-Schreibprozesse.

Der Workflow hält für seine FolioTone-seitigen Tool-, Snapshot- und Evidence-
Writes eine bestehende `EBOOK_ANALYSIS`-`ScanRoot`-Write-Lease. Jeder kurze
Commit wird gemäß ADR-0027 gefencet; Toolausführung und Parserarbeit halten
keine lange SQLite-Transaktion offen. Ein Lease-Keeper deckt lange Snapshot-
Erfassungen ab. Die Lease schützt nicht die externe calibre-Datenbank.

## Immutable Evidence

Die v1-Domainmodelle unterscheiden:

- `CalibreLibraryRecordSnapshot`: Snapshot-ID, calibre-Record-ID, UUID als
  Evidence, technische Zeit-/Metadatenfingerprints und bounded Metadatenfelder;
- `CalibreLibraryFormatSnapshot`: Record-Snapshot-ID, Formatlabel, relative
  Locator-Evidence, deklarierte Größe und optional zugeordnete
  `FileObservation`;
- `CalibreLibrarySidecarSnapshot`: Record-Snapshot-ID, Sidecar-Art, relative
  Locator-Evidence und optional zugeordnete `FileObservation`;
- `CalibreReconciliationFinding`: fester Finding-Code, Snapshot-/Record-/
  Observation-Referenzen, Evidence-Referenzen und Reviewbedarf;
- `CalibreReconciliationFindingRef`: geordnete, typisierte Referenz eines
  Findings auf einen Record, ein Format, ein Sidecar, eine `FileObservation`
  oder konkrete persistierte Evidence.

Absolute Pfade, Bibliothekswurzeln und Hostnamen sind in diesen DTOs verboten.
Relative Locator dürfen nur in der privaten Persistenz und internen
Reconciliation verwendet werden. Öffentliche Status- und Report-DTOs enthalten
nur opake IDs, feste Labels, Statuswerte und Zähler. UUIDs, Titel, Autoren,
Identifierwerte, relative Locator und materielle Fingerprints werden dort
nicht ausgegeben.

Metadaten bleiben als beobachtete calibre-Evidence erhalten. Sie dürfen weder
kanonische Entity-Felder noch eingebettete Metadaten überschreiben. Ein
`CalibreLibraryRecordSnapshot` ist kein `Work` und keine `Edition`.

## Ownership- und Sidecar-Regel

Ein Format gehört nur dann zu einem calibre-Record, wenn es in dessen
`formats`-Projektion vorkommt und der normalisierte relative Locator exakt auf
eine aktuelle `FileObservation` des gebundenen `ScanRun` zeigt. Ein vorhandener
vollständiger `FILE_SHA256` darf eine abweichende Locator-Zuordnung als
zusätzliche Evidence stützen; Dateiname, Verzeichnisname, Titel, Autor oder
calibre-ID im Ordnernamen reichen allein nicht aus.

Sidecars werden ausschließlich innerhalb des eindeutig durch ein gemapptes
Format bestimmten Record-Verzeichnisses und aus dem gebundenen Scan-Snapshot
klassifiziert. Es wird keine zusätzliche Source-Rekursion gestartet. Feste
Arten sind:

- `METADATA_OPF` für exakt `metadata.opf`;
- `COVER` für exakt `cover.jpg`;
- `EXTRA_DATA` für vorhandene Dateien unter dem direkten Unterbaum `data/`;
- `KNOWN_SIDECAR` für später explizit versioniert freigegebene Namen;
- `UNKNOWN_SIDECAR` für andere indexierte Dateien im Record-Verzeichnis.

`UNKNOWN_SIDECAR`, eine mehrdeutige Record-Verzeichniszuordnung oder eine
Sidecar-Evidence ohne eindeutig zugeordneten Record bleibt ein Blocker für
eine spätere Keep Preference. EB-07 öffnet oder verändert Sidecar-Inhalte
nicht.

## Reconciliation-Fälle A bis G

Die Finding-Codes und ihre Aussagegrenzen sind fest:

| Fall | Finding-Code | Vertrag |
|---|---|---|
| A | `FILESYSTEM_ONLY` | Aktuelle unterstützte E-Book-Observation ohne Calibre-Formatzuordnung. |
| B | `CALIBRE_RECORD_WITHOUT_FILE` | Record ohne zuordenbare aktuelle Format-Observation; kein Löschurteil. |
| C | `CALIBRE_DUPLICATE_RECORD_CANDIDATE` | Verschiedene Records besitzen Formate mit gleichem vollständigem `FILE_SHA256`; Review Candidate, keine bestätigte Dublette. |
| D | `CALIBRE_MULTI_FORMAT_RECORD` | Ein Record besitzt mehrere zugeordnete Formate; Ownership Evidence und ausdrücklich kein Duplicate-Finding. |
| E | `CALIBRE_METADATA_CONFLICT` | Calibre- und eingebettete Evidence widersprechen sich in demselben Feld; keine Korrektur. |
| F | `CALIBRE_AUTHORITY_CONFLICT` | Calibre-Contributor-Evidence widerspricht einer aufgelösten Agent-Zuordnung; generisches `ReviewItem`, keine automatische Bestätigung. |
| G | `CALIBRE_SIDECAR_DEPENDENCY` | Record-gebundene Sidecar- oder Extra-Data-Evidence; unbekannte oder mehrdeutige Abhängigkeiten bleiben explizit. |

Ein Record mit EPUB, PDF und MOBI erzeugt Fall D, nicht allein dadurch Fall C.
Fall C benötigt zwei verschiedene calibre-Records und gleiche vollständige
Bytes. Metadaten-, Titel-, Autoren-, Identifier- oder normalisierte
Textgleichheit genügt dafür nicht.

## Persistenzgrenze für S-EB07-06

Migration `0015_calibre_library_reconciliation` folgt auf `0014` und ergänzt
eine separate Schemadatei `persistence/calibre_library_schema.py` mit den
Tabellen `calibre_library_snapshots`, `calibre_library_records`,
`calibre_library_formats`, `calibre_library_sidecars`,
`calibre_reconciliation_findings` und
`calibre_reconciliation_finding_refs`. Die zusätzliche Referenztabelle ist
erforderlich, weil insbesondere die Fälle C, D und G mehrere Records, Formate,
Sidecars oder Evidence-Datensätze referenzieren können. Eine JSON-Liste in der
Finding-Zeile würde Typvalidierung, begrenzte Abfragen und referenzielle
Konsistenz verschlechtern.

`CalibreReconciliationFinding` enthält Snapshot-ID, Finding-Code,
`finding_fingerprint`, `review_required` und Erstellungszeitpunkt. Der
semantische Idempotenzschlüssel ist
`(snapshot_id, code, finding_fingerprint)`. Der Fingerprint entsteht aus dem
Finding-Code und den kanonisch sortierten materiellen Referenzdeskriptoren.

Jede `CalibreReconciliationFindingRef` enthält Finding-ID, eine bei null
beginnende lückenlose Ordnungszahl, `ref_kind`, `ref_id`, `role` und einen
materiellen Fingerprint. Zulässige `ref_kind`-Werte sind
`CALIBRE_RECORD`, `CALIBRE_FORMAT`, `CALIBRE_SIDECAR`, `FILE_OBSERVATION`,
`VALUE_ASSERTION`, `FINGERPRINT`, `TOOL_RESULT`, `RESOLUTION_CANDIDATE` und
`REVIEW_ITEM`. Zulässige Rollen sind `PRIMARY`, `RELATED`, `SUPPORTING`,
`CONTRADICTING` und `REVIEW`. Die Referenz-ID ist bewusst polymorph und besitzt
keinen einzelnen SQL-Fremdschlüssel. Der dedizierte Store validiert innerhalb
derselben Transaktion Typ, Existenz, Snapshot-/Scan-Lineage und zulässige
Finding-Code-/Referenz-Kombinationen. Die Finding-ID besitzt einen normalen
Fremdschlüssel auf `calibre_reconciliation_findings`.

Snapshots sind insert-only. Record-, Format-, Sidecar- und
Finding-Wiederholungen sind nur innerhalb desselben Snapshots über semantische
Composite Keys idempotent; unterschiedliche Snapshots bleiben getrennt
nachvollziehbar. Findings besitzen mindestens eine und höchstens 256
Referenzen. Ein Retry mit demselben semantischen Schlüssel und abweichendem
Payload schlägt geschlossen fehl.

Konkrete Snapshot-/Record-Beziehungen verwenden Fremdschlüssel. Polymorphe
Observation-, Evidence- und Review-Referenzen werden im dedizierten Store in
derselben Transaktion typ- und existenzvalidiert. Die neuen Modelle werden
nicht beim generischen Update-by-ID-Repository registriert. Es entsteht kein
Unique-Index auf generischen Fingerprintwerten.

## Konsequenzen und Grenzen

- EB-07 kann Calibre-/Filesystem-Abweichungen reproduzierbar und read-only
  erfassen, ohne Calibre zur kanonischen Datenbank zu machen.
- Eine Bibliothek, die sich während der Erfassung ändert, liefert keinen
  freigegebenen Reconciliation-Snapshot.
- Remote Content Server, Credentials und Netzwerkzugriff bleiben in v1
  gesperrt.
- Archive, Extraktion, Keep Preference und `ConsolidationPlan` sind nicht Teil
  dieses Gates.
- Keine Operation löscht, verschiebt, exportiert, schreibt oder korrigiert
  Source Media, calibre-Metadaten, Sidecars oder Verzeichnisse. W10 bleibt
  gesperrt.

## Verifikation

Die Folgepakete verwenden ausschließlich synthetische JSON-, CSV- und
OPF-Fixtures. Unit- und Integrationstests prüfen die exakten positiven Shapes,
sämtliche negativen Subcommands, Output-/Timeoutgrenzen, Path Traversal,
Snapshot-Invalidierung, Lease-Verlust, idempotente Persistenz, Fälle A bis G,
Multi-Format-Abgrenzung, path-freie Reports sowie unveränderte Source- und
calibre-Fixtures. Reale Bibliotheken und Live-Netzwerkzugriffe sind kein
Bestandteil des CI-Gates.

## Primärquellen

- https://manual.calibre-ebook.com/en/generated/en/calibredb.html
- https://manual.calibre-ebook.com/en/db_api.html
