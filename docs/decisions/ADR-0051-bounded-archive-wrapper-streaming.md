# ADR-0051: Begrenztes Streaming für äußere TAR-Kompression

- Status: Accepted
- Datum: 2026-08-21

## Kontext

Die Signaturgrenze erkennt gzip, bzip2, xz und zstd als äußere
Kompressionsformen. Bislang bleiben diese Beobachtungen absichtlich
`OUTER_COMPRESSION_ONLY`, ihre Storage Family bleibt `UNKNOWN`, und EBAR-05
startet keinen Toollauf. Die Formate sind keine verschachtelten Archive im
Sinne einer rekursiven Traversierung: Nach genau einer äußeren Dekompression
liegt ein TAR-Bytestrom vor.

Eine Zwischen-Datei für diesen TAR-Strom würde den noch ungelösten
Extraction-Workspace-Vertrag voraussetzen. Gleichzeitig genügt es nicht, den
Strom ungeprüft an `7zzs t -si -ttar` weiterzugeben. Der gepinnte 7-Zip-26.02-
Lauf akzeptiert bei einem synthetischen TAR nach den Endblöcken angehängte
Fremdbytes mit Exitcode 0. Tool-Integrity allein beweist daher keinen exakten
TAR-Rahmen.

Mit den vier öffentlichen v1-Wrapperfixtures wurde lokal gegen die exakt
gepinnten 7-Zip-26.02-Bytes verifiziert:

- `7zzs x -so` liefert für gzip, bzip2, xz und zstd jeweils 2048 Byte;
- alle vier Streams haben SHA-256
  `eadd731905c30e6e2412522a7b6b089730f3b260b5c68224b4cfb732dcf352c4`;
- die Bytes sind exakt identisch mit der gebundenen synthetischen TAR-Fixture;
- der nachgeschaltete feste `-si -ttar`-Listing- und Integrity-Lauf endet mit
  Exitcode 0;
- `-bso0 -bse0 -bsp0` ist am äußeren Lauf zwingend, damit ausschließlich
  Payloadbytes auf stdout liegen.

Das Gate muss deshalb eine begrenzte, streamingfähige und pfadfreie Pipeline
entscheiden, ohne Extraction, Persistenz oder rekursive Archivöffnung
vorwegzunehmen.

## Entscheidung

FG-A-WRAPPER-PIPELINE ist akzeptiert. Die vier äußeren Kompressionsformen
dürfen nach den unten genannten mechanischen Paketen read-only gelistet und
auf Integrität geprüft werden. Die Pipeline erzeugt niemals eine entpackte
TAR-Datei und benötigt keinen Extraction-Workspace.

Die öffentliche Source-Beobachtung bleibt unverändert:

- Recognition: `OUTER_COMPRESSION_ONLY`;
- Outer Compression: exakt `GZIP`, `BZIP2`, `XZ` oder `ZSTD`;
- Storage Family: `UNKNOWN`;
- `max_nested_depth=0`.

Erst die private, an denselben Lauf gebundene Wrapper-Evidence bestätigt den
abgeleiteten inneren Strom als TAR. Sie darf die Source-Signaturbeobachtung
nicht nachträglich zu TAR umschreiben.

## Exakte Pipeline

Ein autorisierter Wrapperfall verwendet zwei voneinander getrennte,
sequentielle Composite-Läufe:

1. äußere Dekompression, TAR-Rahmenprüfung und inneres TAR-Listing;
2. erneute äußere Dekompression, dieselbe TAR-Rahmenprüfung und innerer
   TAR-Integrity-Lauf.

Jeder Composite-Lauf besteht aus genau zwei no-shell Prozessen in getrennten
Containern. Der stdout des äußeren Prozesses wird mit fester Backpressure über
den Rahmenprüfer an stdin des inneren Prozesses weitergereicht. Der Broker
hält weder den vollständigen Rawstrom noch eine unbeschränkte Queue.

Der äußere Command ist ausschließlich:

```text
/usr/local/bin/7zzs x -so -bd -bb0 -bso0 -bse0 -bsp0 -mmt=1 -- /workspace/input/archive
```

Das innere Listing ist ausschließlich:

```text
/usr/local/bin/7zzs l -si -ttar -slt -ba -bd -bb0 -bso1 -bse0 -bsp0 -sccUTF-8
```

Das innere Integrity ist ausschließlich:

```text
/usr/local/bin/7zzs t -si -ttar -bd -bb0 -bso0 -bse0 -bsp0 -sccUTF-8 -mmt=1
```

Es gibt keine Shell, keinen Pull, kein Netzwerk, keinen Secretkanal, keinen
Output-Mount und keine zusätzlichen Argumente. Der äußere Container erhält
genau den bestehenden read-only Input-Bind-Mount; der innere Container erhält
keinen Bind-Mount und ausschließlich den Broker-stdin. Beide Container
verwenden die bereits akzeptierte Runtime-Authority, `--log-driver=none` und
dieselben Ressourcen-, User-, Capabilities-, Seccomp- und Cleanupgrenzen wie
der direkte Runner. Der innere Container muss `OpenStdin=true` und
`StdinOnce=true` attestieren; TTY bleibt aus.

## TAR-Rahmenprüfer

Der reine interne Vertrag heißt `archive-tar-stream-frame/v1`. Er ist keine
zweite Member-Metadatenquelle. Memberprojektion, Locator-Safety und Formatlock
bleiben allein beim bestehenden gelockten 7-Zip-TAR-Parser.

Der Rahmenprüfer arbeitet inkrementell in 512-Byte-Blöcken und erzwingt:

- valide TAR-Headerprüfsumme vor jeder Größeninterpretation;
- geschlossene, gebundene Zahlengrammatik und Projektgrenzen für Größe,
  Memberzahl und gesamten entpackten Strom;
- vollständige Payload- und Paddingblöcke je Header;
- mindestens zwei aufeinanderfolgende Nullblöcke als Ende;
- nach dem Ende ausschließlich weitere Nullblöcke bis zum blockgenauen EOF;
- Ablehnung partieller Blöcke, nichtnuller Nachläufe, angehängter oder
  verketteter TAR-Ströme und jeder Grenzüberschreitung.

Jedes Byte wird vor dem Weiterreichen gezählt und in einen laufenden SHA-256
aufgenommen. Der zweite Composite-Lauf muss exakt dieselbe Bytelänge und
denselben SHA-256 wie der Listing-Lauf liefern. Abweichung ist `TOOL_FAILED`;
alle Teilwerte werden verworfen.

## Status- und Abbruchmatrix

Die Pipeline startet nur bei bestätigter Signature-v2-/Suffix-/Publication-
Kompatibilität und einem der vier äußeren Literale. Mismatch, unbekannte oder
nicht gelockte Kombinationen starten keinen Prozess.

- User-Cancellation beendet beide Prozesse und bleibt snapshotlos.
- Runtime `TOOL_UNAVAILABLE`, `TIMED_OUT`, `LIMIT_EXCEEDED` und `TOOL_FAILED`
  bleibt unverändert maßgeblich.
- Ein nichtnuller Exitcode eines äußeren oder inneren Prozesses ist immer
  `TOOL_FAILED`; stderr wird begrenzt verworfen und nie als Ursachenauthority
  ausgewertet.
- TAR-Rahmen-Limit ergibt `LIMIT_EXCEEDED`; Rahmen-, Encoding- oder
  Parsergrammatikfehler ergeben `TOOL_FAILED`.
- Cleanup-, Container-Abwesenheits- oder Stream-Quieszenzfehler dominieren
  Erfolg als `TOOL_FAILED`.
- Teil-Listing, Teilhashes und Teilmember werden nie veröffentlicht.

Ein erfolgreicher Listing-Composite-Lauf und ein erfolgreicher
Integrity-Composite-Lauf bilden weiterhin genau zwei öffentliche
`ToolExecution`-Datensätze: `ARCHIVE_LISTING` und `ARCHIVE_INTEGRITY`. Die
äußeren und inneren Prozessläufe sind private, pfadfreie Unterprovenienz
derselben Composite-Ausführung. Damit bleibt der bestehende öffentliche
Provider-Sum-Type geschlossen; vier erfundene öffentliche Executions sind
nicht zulässig.

## Privacy, Lineage und Reuse

Rawbytes, stdout, stderr, TAR-Header, Locatorwerte und private Linkziele werden
weder persistiert noch geloggt, gerendert oder in Fehlertexte aufgenommen.
Zulässig sind nur feste Statusliterale, Zähler und SHA-256-Digests.

Wrapper-Reuse benötigt ein eigenes additives Profil. Es bindet mindestens:

- vollständigen Hash und Volume-Fingerprint der äußeren Sourcebytes;
- äußeres Kompressionsliteral und Signature-v2-/Suffix-Compatibility;
- Wrapper-Pipeline-, TAR-Rahmen-, Parser- und Formatlockprofile;
- Image-, Tool-, Runtime- und die drei exakten Command-Identitäten;
- innere Bytelänge und inneren SHA-256;
- die beiden Composite-Execution-Identitäten.

Der vorhandene direkte `archive-7zip-provider/v1`-Reuse-Key wird nicht
gelockert oder still erweitert. Jede Profil-, Command-, Runtime-, Tool-,
Signature-, Formatlock-, Byte- oder Hashabweichung macht Wrapper-Evidence
stale.

## Extraction- und Persistenzgrenze

Wrapper-Listing und -Integrity autorisieren keine Extraction. Es entsteht
kein S-EBAR-05A-Extraction-Handoff und `extraction_policy_status` bleibt
blockiert. S-EBAR-04A, EBAR-06, Source-Mutation, Quarantäne und W10 bleiben
unverändert gesperrt. Ein späteres Wrapper-Extraction-Gate müsste denselben
inneren Strom erneut unter einem akzeptierten harten Workspacevertrag
verarbeiten; diese ADR autorisiert das nicht.

Persistenz bleibt bis FG-A-PERSISTENCE blockiert. Dieses Gate muss Wrapper-
Composite-Provenienz, inneren Byte-/Hash-Nachweis, Stale-Regeln und die
Privacy-Allowlist ausdrücklich aufnehmen.

## Mechanische Folgepakete

Die Umsetzung erfolgt strikt in dieser Reihenfolge:

1. `S-EBAR-W01`: reiner TAR-Rahmenprüfer, feste Wrapper-/stdin-Commands und
   ausschließlich synthetische Unit-Tests;
2. `S-EBAR-W02`: bounded Duplex-Broker und Zwei-Container-Lifecycle mit Fakes
   sowie echter provisionierter Linux-Integration ohne Pull;
3. `S-EBAR-W03`: Provider-Integration und die vier öffentlichen Wrapperfixtures
   für Listing, Integrity, Hash-/Bytegleichheit, Status und No-Handoff;
4. `S-EBAR-W04`: fokussierte Abschlussprüfung und Statussynchronisierung.

Kein Paket darf den Scope des Folgepakets vorziehen. W01 führt keine Prozesse
aus, W02 kennt keine Provider-Semantik, W03 extrahiert und persistiert nichts.

## Abnahme

Mindestens nachzuweisen sind:

- die vier gebundenen Wrapperfixtures liefern denselben inneren TAR-Hash;
- jeder mögliche Chunksplit einschließlich leerer und blockübergreifender
  Chunks bleibt bounded und deterministisch;
- Headerchecksumme, Größen, Padding, zwei Nullblöcke, partielles EOF,
  nichtnuller Nachlauf und verketteter TAR werden adversarial geprüft;
- Queue-, Chunk-, Byte-, Member- und Zeitgrenzen beenden beide Prozesse;
- äußere und innere Nonzero-Exits, Cancel, Timeout, Limit, Parserfehler,
  Consumerfehler und Cleanup-Races folgen der Statusmatrix;
- Listing- und Integrity-Läufe stimmen in Länge und SHA-256 exakt überein;
- keine Rawbytes, Locatorwerte, stderr-Fragmente oder private Pfade verlassen
  die interne Grenze;
- kein Wrapper erzeugt einen Extraction-Handoff oder eine Schreiboperation;
- direkte ZIP-/RAR4-/RAR5-/7z-/TAR-Regressionen bleiben unverändert.

## Folgen

FG-A-WRAPPER-PIPELINE ist abgeschlossen. Wrapper bleiben bis zum Abschluss
von W01 bis W03 ohne produktiven Lauf; danach dürfen ausschließlich Listing
und Integrity aktiviert werden. Die negative Workspace-Entscheidung aus
ADR-0050 blockiert diese read-only Streamingstrecke nicht, weil kein
Extraction- oder Output-Workspace entsteht.

Diese ADR ersetzt für die vier äußeren Kompressionsformen die bisherige
pauschale Aussage "kein Listing-/Integrity-Lauf bis zu einem späteren Gate".
Sie ersetzt nicht die Extraction-, Secret-, Persistenz- oder
Source-Mutationsgrenzen aus ADR-0038, ADR-0039, ADR-0048 bis ADR-0050.
