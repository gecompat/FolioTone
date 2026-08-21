# E-Book-Folgewelle: Archive und kontrollierte Deduplizierung

## Status und Geltungsbereich

**Status:** In Ausführung; read-only Archive-Discovery, Runtime, Formatlock,
Listing, Persistenz, Collection-Orchestrierung und die generische
Source-Dependency-Strecke bis S-EBA3-03 sind abgeschlossen. Extraction,
Member-Byte-Identity, Secrets und W10 bleiben getrennt blockiert.

**Stand:** 2026-08-21

**Scope:** Read-only Archivanalyse, lokale Passwortkandidaten, archive-aware
Matching und Review, nicht ausführbare Deduplizierungsplanung sowie eine
ausdrücklich gesperrte spätere W10-Ausführung

Diese Roadmap schließt an die E-Book-Wellen in
[`W3_017_EBOOK_ROADMAP.md`](W3_017_EBOOK_ROADMAP.md) an. Sie dokumentiert
keine bereits implementierte Archiv- oder Löschfunktion. Source Media bleibt
durch W9 read-only. Eine spätere Quarantäne-, Lösch- oder
Verzeichnisoperation erfordert zuerst eine akzeptierte W10-ADR und eine
erneute ausdrückliche Ausführungsfreigabe.

Der
[`E-Book-Endgame-Ausführungsplan`](EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md)
gruppiert EA1 bis EA10 in die Lieferpakete EB-A1 bis EB-A3. Die EA-Nummerierung,
Semantik und Statuswerte dieses Dokuments bleiben maßgeblich; insbesondere
werden EA11 und EA12 dadurch nicht freigegeben.

Das Frontier-Gate FG-A ist durch
[ADR-0038](../decisions/ADR-0038-safe-archive-container-analysis.md)
akzeptiert. Die ADR ist für Format-/Signatur-Allowlist, 7-Zip-Toolmanifest,
Statuswerte, Budgets, Memberpfade, lokale Sidecarklassen, Secret-Grenze,
Profile und Evidence Reuse verbindlich. S-EBA-01 bis S-EBA-07 setzen die
synthetischen beziehungsweise Fake-only Vorarbeiten um.

Das anschließende Frontier-Gate FG-A-RUNTIME ist durch
[ADR-0039](../decisions/ADR-0039-safe-archive-runtime-and-secret-channel.md)
akzeptiert. Es erlaubt die Entwicklung einer spezialisierten bounded
Streaming-Runtime für unverschlüsseltes Listing, Integrity und private
Testextraktion. Raw-Ausgaben werden nicht persistiert. Reale Passwortversuche
bleiben bis zum separaten FG-A-SECRET blockiert.

FG-A-IMAGE ist durch
[ADR-0040](../decisions/ADR-0040-reproducible-archive-runtime-image.md)
akzeptiert. Das Gate wählt ein projekt-eigenes `linux/amd64`-`scratch`-Image
mit festen 7zz-26.02- und Lizenzinputs, UID/GID `65532:65532`, gepinntem
Buildx-/BuildKit-Profil, reproduzierbarem Plattform-Manifest-Digest-Lock sowie
nachträglich angehängter SBOM und Provenance. S-EBAR-03 hat Rezept,
Bootstrap-Lock, SPDX, Custom-SLSA-Workflow, Toolmanifest und Command Builder
umgesetzt.

FG-A-RUNTIME-AVAILABILITY ist durch
[ADR-0041](../decisions/ADR-0041-offline-archive-runtime-availability.md)
akzeptiert und S-EBAR-03A ist umgesetzt. EBAR-04 stellt den isolierten
Docker/Linux-Streaming-Runner bereit. S-EBAR-02B hat danach das geschützte
Linux-Messmanifest erzeugt; [ADR-0045](../decisions/ADR-0045-archive-7zip-format-lock.md)
stuft es als diagnostische Happy-Path-Evidence ein und akzeptiert noch keinen
Formatlock. S-EBAR-02B2 hat die Fallmatrix und Boolklassifikation geschlossen.
[ADR-0046](../decisions/ADR-0046-archive-publication-and-storage-family.md)
entscheidet FG-A-STORAGE-FAMILY. [ADR-0047](../decisions/ADR-0047-final-archive-7zip-format-lock.md)
akzeptiert danach den finalen maschinenlesbaren Formatlock. S-EBAR-02C und
EBAR-05 sind umgesetzt. [ADR-0048](../decisions/ADR-0048-private-archive-extraction-lifecycle.md)
entscheidet vor EBAR-06 den privaten Listing-/CRC-Handoff, den Runner-owned
Workspace-Consumer-Lifecycle und die getrennte Wrappergrenze. S-EBAR-05A,
S-EBAR-06A und S-EBAR-04Q sind umgesetzt. ADR-0050 schließt
FG-A-WORKSPACE-BACKEND negativ; die Backend-Allowlist bleibt leer und reale
Extraction `TOOL_UNAVAILABLE`. `BOOTSTRAP_LOCKED` und lokales
Inspect allein bleiben keine Runtime-Authority; Public Visibility und
Source-Association werden nur beim
Provisioning beziehungsweise Refresh erneut geprüft.

## Planungsentscheidung

Archive werden nicht pauschal als Verpackung behandelt, die nach einer
Extraktion entbehrlich ist. EPUB, CBR und CBZ sind selbst
Publikationscontainer; ZIP, RAR oder 7z können Sammlungen, mehrteilige
Releases, Backups oder Softwarepakete enthalten. FolioTone muss deshalb
zunächst Containerart, Mitglieder, Integrität, Verschlüsselung, Provenance und
Beziehung zu bereits indexierten Dateien feststellen.

Die Deduplizierung trennt vier Aussagen:

1. `FILE_SHA256` bestätigt bytegleiche physische Dateien.
2. Matching und Review bestimmen, welche Kopien beziehungsweise
   Repräsentationen fachlich zusammengehören.
3. Eine Keep-Präferenz bewertet Speicherort, Calibre-Zugehörigkeit,
   Begleitdateien und Quality-Evidence getrennt von der Identität.
4. Erst ein ausdrücklich autorisierter W10-Executor darf einen geprüften Plan
   über Quarantäne, Verifikation und spätere Löschung ausführen.

## Verbindliche Grenzen

- Archive werden während normaler Scans weder automatisch extrahiert noch
  gelöscht.
- Read-only Listing, Integritätstest und Passwortprüfung laufen gegen eine
  unveränderte Source oder eine private gestagte Kopie.
- Extraktion erfolgt ausschließlich in einen begrenzten privaten Workspace
  außerhalb des Source Root.
- Archivmitglieder werden niemals ausgeführt. Symlinks, Reparse Points,
  absolute Pfade und Traversalziele werden abgewiesen.
- Passwörter erscheinen weder in Git, SQLite-Klartext, CLI-Argumenten,
  stdout/stderr, `ToolResult`, normalen Logs noch Reportartefakten.
- Lokale Passwortkandidaten haben Vorrang vor jeder Netzwerkanfrage.
- Online-Recherche ist ein separater, standardmäßig deaktivierter Vorgang und
  kein Seiteneffekt von Scan, Resume, Hashing oder Collection-Analyse.
- Absolute oder relative Sammlungspfade sowie rohe private Dateinamen werden
  nicht an Online-Provider übertragen.
- Ein externer Treffer ist Evidence und darf weder Extraktion noch
  Deduplizierung oder Löschung allein autorisieren.
- CBR, CBZ und EPUB werden als Publikationscontainer erhalten, solange keine
  bestätigte andere fachliche Entscheidung vorliegt.
- Calibre-verwaltete Dateien werden durch W9 nur read-only abgeglichen. Eine
  spätere Mutation darf nicht als direkte Dateisystemlöschung an Calibre
  vorbei erfolgen.

## Zielmodell der Verarbeitung

```text
Filesystem Discovery
  -> Archiv-/Containererkennung
  -> read-only Listing und Integrität
  -> PASSWORD_REQUIRED oder ohne Passwort lesbar
  -> lokale Passwortkandidaten
  -> optional separat aktivierte Online-Kandidaten
  -> begrenzte private Testextraktion
  -> Member-Evidence und Hashes
  -> Entity Resolution / Matching / Review
  -> nicht ausführbarer ConsolidationPlan
  -> zukünftige W10-ADR
  -> Quarantäne
  -> Verifikation / Rollbackfenster
  -> optionaler Purge
  -> getrennte Leer-Verzeichnis-Prüfung
```

## Lokale Passwortkandidaten

Die erste Passwortquelle ist ein versionierter lokaler Kandidatenparser. Er
darf Kandidaten ausschließlich aus begrenzten, expliziten Quellen ableiten:

1. einem vom Benutzer bereitgestellten Secret Handle;
2. bereits bestätigten lokalen Secret Handles für dieselbe Archive-/Release-
   Identität;
3. ZIP-/RAR-Kommentaren und anderen vom Listing-Tool ausgewiesenen
   Containerkommentaren;
4. gleichnamigen oder im direkten Verzeichnis liegenden `.nfo`, `.txt`,
   `.diz`, `.info`, `.url`, `.html`, `.htm`, `.sfv` und extensionless
   `README`-/`PASSWORD`-Dateien;
5. einer ausdrücklich konfigurierten lokalen Passwortliste.

Der Parser verwendet feste Größen-, Zeilen- und Kandidatengrenzen sowie eine
versionierte Regel-Allowlist für Markierungen wie `password`, `passwort`,
`pass`, `pw` oder URI-Hinweise. Er darf keine unbeschränkte Freitextsuche,
keinen Brute-Force-Angriff und keine kombinatorische Generierung aus privaten
Dateinamen durchführen.

Persistiert werden nur Kandidatenquelle, Parser-Version, Rang,
Prüfzeitpunkt, Ergebnisstatus und ein opaker Secret Handle. Das geheime
Material liegt hinter einer austauschbaren lokalen `SecretProvider`-Grenze.
Ein erfolgreicher Kandidat kann für exakt dieselbe versionierte
Archive-/Release-Identität wiederverwendet werden; eine Änderung von Archiv,
Parserprofil oder Secret-Version macht die Entscheidung stale.

## Online-Passwortrecherche

Der vom Benutzer genannte Name `Newzcrabber` ist derzeit keine bestätigte
Provideridentität mit belegter stabiler Automationsschnittstelle. Die spätere
Research-Welle muss zuerst klären, welches konkrete Produkt beziehungsweise
welcher Dienst gemeint ist. Sie bewertet außerdem geeignete Alternativen, zum
Beispiel dokumentierte Usenet-/NZB-Metadatenquellen, ohne eine Integration
vorwegzunehmen.

Ein Online-Adapter ist nur zulässig, wenn aktuelle Primärdokumentation eine
stabile und rechtlich nutzbare Schnittstelle belegt. Reverse Engineering
einer GUI oder eines privaten Webendpoints ist ausgeschlossen. Der Vertrag
muss mindestens festlegen:

- explizites Opt-in und getrennten Betriebsmodus;
- Provider- und Credential-Konfiguration außerhalb von Git;
- privacy-minimiertes Query-DTO ohne Pfade oder collection-weites Inventar;
- bevorzugt Release-/NZB-Identifier statt roher Dateinamen;
- Rate Limits, Cache, Terms, Lizenz und Attribution;
- begrenzte Kandidatenantwort ohne Passwortausgabe in Logs oder Reports;
- Provenance, Fetch-Zeitpunkt und Provider-/Adapter-Version;
- Offline- und Provider-Ausfallverhalten ohne Einfluss auf normale Scans.

## Entwicklungswellen

### EA1 — Archivscope und Toolbewertung

**Status:** Durch ADR-0038 und S-EBA-01 bis S-EBA-07 abgeschlossen.

**Ziel:** Unterstützte Container und eine sichere read-only Toolchain sind
verbindlich entschieden.

Umfang:

- Signatur- und Suffixmatrix für ZIP, RAR, 7z, CBR, CBZ, TAR und
  komprimierte TAR-Varianten;
- Mehrteil-Erkennung für RAR- und 7z-Volumes;
- 7-Zip 26.02 als optionaler Baseline-`ToolProvider` nur für die festen
  unverschlüsselten read-only Shapes aus ADR-0038; libarchive/bsdtar bleibt
  geprüft und zurückgestellt;
- Lizenz-, Redistributions-, Version-, Exitcode-, Passwort- und
  Container-Sicherheitsbewertung;
- Entscheidung, welche Formate Publikationscontainer bleiben und welche nur
  als generische Archive gelten;
- akzeptierte ADR für Archive-Evidence, Secret-Grenze und
  Extraktionssandbox.

Abnahme:

- keine Source-Media-Write-Capability;
- mindestens ein synthetisches Fixture je unterstützter Containerklasse;
- `ToolProvider`-Reuse statt nativer Dekompression;
- verschlüsselte Runtime bleibt `SECURE_CHANNEL_UNAVAILABLE`, solange ein
  separates Frontier-Gate keinen sicheren Helper-/Pipe-Vertrag belegt.

### EA2 — Read-only Archiv- und Sidecar-Inventar

**Status:** Teilweise vorbereitet. Signatur-, Volume-, Sidecar- und Fake-
Listing-Verträge sind vorhanden; Persistenz, Collection-Orchestrierung und
pfadfreier Runtimebericht bleiben offen.

**Ziel:** Archive und Begleitdateien werden inkrementell beobachtbar, ohne
Mitglieder zu extrahieren.

Umfang:

- signature-first Containererkennung mit Suffixabweichungs-Evidence;
- versionierte Archivbeobachtung mit Größe, Quick-/Full-Hash, Volumegruppe,
  Verschlüsselungsindikator und Listingstatus;
- begrenztes Verzeichnismanifest für Metadaten-, Cover-, NFO-, Text-,
  Checksum-, Archiv- und weitere E-Book-Formate;
- Zustände für fehlende Volumes, beschädigte Header, unbekannte Methode und
  Passwortanforderung;
- Resume, Heartbeat, Lease und pfadfreie Summen für große Bestände.

### EA3 — Lokaler Passwortkandidatenparser

**Status:** Der bounded Parser und `SecretHandle`-Vertrag sind durch S-EBA-04
und S-EBA-05 umgesetzt. Die reale Übergabe an einen Prozess bleibt bis
FG-A-SECRET gesperrt.

**Ziel:** Wahrscheinliche Passwörter werden lokal und geheimniswahrend
ermittelt.

Umfang:

- begrenzte Decoder für UTF-8 und explizit evaluierte Legacy-Zeichensätze;
- Parser für Containerkommentar, NFO, Text, DIZ, INFO, URL, HTML, SFV und
  extensionless Hinweise;
- deterministische Rangfolge, Deduplizierung und Maximalzahl von Kandidaten;
- `SecretProvider`-Handle statt Klartextpersistenz;
- nur statusbasierte Logs wie `PASSWORD_REQUIRED`, `CANDIDATE_ACCEPTED` oder
  `NO_LOCAL_CANDIDATE`;
- kein Brute Force und keine Ausgabe des Kandidatenmaterials.

### EA4 — Begrenztes Listing und Integritätstest

**Status:** FG-A-RUNTIME, FG-A-IMAGE und FG-A-RUNTIME-AVAILABILITY sind durch
ADR-0039, ADR-0040 beziehungsweise ADR-0041 akzeptiert. S-EBAR-01 bis
S-EBAR-03A, EBAR-04, S-EBAR-02A, S-EBAR-02B und S-EBAR-02B2 sind umgesetzt. Die reale
Golden-Prüfung von Parser v2 löste den vorgesehenen Stop aus. ADR-0045 hält
FG-A-FORMAT-LOCK wegen unvollständiger Fallmatrix, falscher Boolklassifikation
und kollidierender Publication-/Storage-Achse offen. ADR-0046 trennt
Publication, direkte Storage-Familie und äußere Kompression; der nächste
Schritt ist der finale FG-A-FORMAT-LOCK.

**Ziel:** Archive werden ohne dauerhafte Extraktion technisch bewertet.

Schutzgrenzen umfassen Mitgliederzahl, Gesamtgröße, Einzelgröße,
Kompressionsverhältnis, Verschachtelung, Pfadlänge, Laufzeit und
stdout/stderr-Artefaktgröße. Abgewiesen werden Traversal, absolute Pfade,
Gerätepfade, Alternate Data Streams, Symlinks, Reparse-Point-Ziele,
Hardlinks, FIFOs, Sockets, Devices und normalisierte Zielkollisionen. Die
exakten v1-Grenzen stehen in ADR-0038; `max_nested_depth=0` verhindert in der
ersten Runtime jede automatische Nested-Verarbeitung.

### EA5 — Private Testextraktion

**Status:** Der Grundvertrag ist durch ADR-0039 akzeptiert. ADR-0048 hat die
Handoff-, Quota- und Runner-Lifecycle-Lücken geordnet. S-EBAR-05A und
S-EBAR-06A sind abgeschlossen. ADR-0049 entscheidet FG-A-EXTRACTION-QUOTA als
dateisystemneutrale Workspace-Capability; S-EBAR-04Q ist umgesetzt.
[ADR-0050](../decisions/ADR-0050-linux-docker-workspace-backend-unavailable.md)
akzeptiert noch kein reales Plattformbackend. S-EBAR-04A und EBAR-06 bleiben
bis zu einem erfolgreichen Revalidation-Gate `TOOL_UNAVAILABLE`.
Passwortgeschützte Extraktion bleibt unabhängig davon blockiert.

FG-A-WRAPPER-PIPELINE ist durch
[ADR-0051](../decisions/ADR-0051-bounded-archive-wrapper-streaming.md)
unabhängig davon entschieden. Die Folge S-EBAR-W01 bis S-EBAR-W04 erlaubt
nur bounded Listing und Integrity der vier äußeren TAR-Kompressionsformen.
Sie ist abgeschlossen und erzeugt keine Zwischen-Datei, keinen
Extraction-Handoff und keinen Write.

FG-A-PERSISTENCE ist durch
[ADR-0052](../decisions/ADR-0052-immutable-archive-evidence-persistence.md)
abgeschlossen. S-EBAR-07 implementiert ausschließlich
die additive Migration `0019_archive_evidence` und den dedizierten
insert-only Store. Das Paket persistiert direkte und Wrapper-Listing-Evidence,
autorisiert aber keine Extraction oder Source-Mutation.

**Ziel:** Ein technisch zulässiges Archiv kann in einem ephemeren privaten
Workspace vollständig geprüft werden.

Die Source bleibt read-only. Jedes Mitglied wird gestreamt gehasht; erwartete
und extrahierte Mitglieder, Größen und CRC-/Toolbefunde müssen konsistent
sein. Der Runner beweist die Container-Abwesenheit vor der synchronen
Workspace-Revalidierung und bleibt alleinige Cleanup-Authority. Vorläufige
Member-Evidence wird erst nach erfolgreichem Cleanup, leerer Slot-
Revalidierung und Return freigegeben; unsichere Slots werden quarantänisiert.
Fehler,
Passwortbedarf, fehlende Volumes oder Limits erzeugen einen terminalen
technischen Befund, aber keine Source-Operation. S-EBAR-05A bewahrt die
privaten Locator-/CRC-Werte desselben EBAR-05-Laufs; S-EBAR-06A stellt den
reinen internen Validator bereit. ADR-0049 akzeptiert als harten
Workspace-Cap eine dateisystemneutrale Capability. S-EBAR-04Q implementiert
danach den neutralen Provider-, Lease-, Capability-, Return- und
Quarantänevertrag. ADR-0050 weist die aktuell untersuchten Linux-/Docker-
Kandidaten fail-closed ab; die Allowlist bleibt leer. Erst ein späteres
erfolgreiches Backend-Revalidation-Gate darf ein mechanisches Plattformpaket
autorisieren. Danach stellt S-EBAR-04A den bounded Consumer-Lifecycle bereit;
erst anschließend beginnt EBAR-06 für direkte
unverschlüsselte `MEASURED`-Fälle. Die 7-Zip-CLI darf kein Secret über `-p`
erhalten.

## FG-A-RUNTIME-Folgepakete und Modellrouting

Die vollständigen Dateigrenzen und Stopbedingungen stehen im
[`Spark-Arbeitspaketkatalog`](EBOOK_SPARK_WORK_PACKAGES.md). Die Reihenfolge
lautet:

```text
S-EBAR-01 Execution-DTOs
    -> S-EBAR-02 Streamingparser
    -> FG-A-IMAGE Supply-Chain- und Packagingentscheidung
    -> S-EBAR-03 Gatewerte, Toolmanifest und Command Builder
    -> FG-A-RUNTIME-AVAILABILITY Release-Authority-Entscheidung
    -> S-EBAR-03A Acceptance, Provisioning und Offline-Availability
    -> EBAR-04 isolierter Docker/Linux-Streaming-Runner
    -> S-EBAR-02A Member-only-Parser v2 für den festen -ba-SLT-Stream
    -> S-EBAR-02B hashgebundener Formatkorpus und Linux-Messmanifest
    -> S-EBAR-02B2 korrigierte und erweiterte Measurement-Matrix
    -> FG-A-STORAGE-FAMILY orthogonales Publication-/Storage-Routing
    -> FG-A-FORMAT-LOCK finaler maschinenlesbarer Lock
    -> S-EBAR-02C formatgebundene Produktionsparser
    -> EBAR-05 unverschlüsseltes Listing und Integrity
    -> FG-A-EXTRACTION-LIFECYCLE privater Handoff und Runner-Lifecycle
    -> S-EBAR-05A privater Listing-/CRC-Handoff
    -> S-EBAR-06A reiner interner Extraction-Validator
    -> FG-A-EXTRACTION-QUOTA neutrale harte Workspace-Capability
    -> S-EBAR-04Q neutraler Provider-/Lease-Vertrag
    -> FG-A-WORKSPACE-BACKEND negative fail-closed Entscheidung
    -> FG-A-WORKSPACE-BACKEND-REVALIDATION erst mit realem Kandidaten/Host
    -> <PLATTFORMPAKET> erst nach akzeptierter Backend-ADR
    -> S-EBAR-04A privater Workspace-Consumer-Lifecycle, derzeit blockiert
    -> EBAR-06 direkte private Extraction-Sandbox, derzeit blockiert
    -> FG-A-WRAPPER-PIPELINE durch ADR-0051 entschieden
    -> S-EBAR-W01 TAR-Rahmen und feste Commands, abgeschlossen
    -> S-EBAR-W02 bounded Duplex-Containerbroker, abgeschlossen
    -> S-EBAR-W03 read-only Wrapper-Provider, abgeschlossen
    -> S-EBAR-W04 fokussierter Wrapper-Abschluss, abgeschlossen
    -> FG-A-PERSISTENCE Schema-, Reuse- und Writer-Gate, abgeschlossen
    -> S-EBAR-07 Persistenz, abgeschlossen
    -> FG-A-COLLECTION-ORCHESTRATION Vertragsgate, abgeschlossen
    -> S-EBAR-08A Models/Schema/Store, abgeschlossen
    -> S-EBAR-08B Plan, abgeschlossen -> 08C Ausführung, abgeschlossen -> 08D Status, abgeschlossen
    -> EBAR-09 Abschluss und EB-A3-Übergang, abgeschlossen
    -> FG-A3-MATCHING Source-/Member-Grenze, durch ADR-0054 abgeschlossen
    -> S-EBA3-01 reiner Source-Dependency-Vertrag, abgeschlossen
    -> S-EBA3-02 bounded Query/Store, abgeschlossen
    -> S-EBA3-03 nicht ausführbare Planintegration, abgeschlossen
    -> FG-A3-MEMBER-BYTE, bis vollständige Member-SHA-256 blockiert
```

Die mechanischen S-EBAR-Pakete verwenden das im Spark-Katalog jeweils
festgelegte Routing. FG-A-IMAGE und FG-A-RUNTIME-AVAILABILITY wurden als
Frontier-Gates abgeschlossen; S-EBAR-03 bis S-EBAR-03A, EBAR-04,
S-EBAR-02A, S-EBAR-02B und S-EBAR-02B2 sind umgesetzt.
FG-A-STORAGE-FAMILY verwendet 5.6 Sol `high`; der finale Formatlock behält
dasselbe Frontier-Routing.
Docker/Linux-Streaming-Runner und Extraction-Sandbox verwenden
5.6 Sol mit Thinking `high`. Nur FG-A-SECRET verwendet 5.6 Sol mit Thinking
`xhigh` und besitzt kein niedriger eingestuftes Fallback. Status-, CI- und
Mergeprüfungen verwenden 5.6 Luna.

`archive-linux-container-runner/v1` ist der erste freigegebene Backendvertrag.
Er mountet niemals die tatsächliche Source, sondern nur eine vollhashgeprüfte
opaque Stagingkopie read-only und einen getrennten privaten Output-Workspace
read-write. Native Windows-Ausführung meldet bis zum akzeptierten
`FG-A-WINDOWS-SANDBOX` `TOOL_UNAVAILABLE`; Job Objects allein isolieren
Netzwerk und Filesystem nicht.

### EA6 — Archivmitglied-Evidence und Wiederverwendung

**Ziel:** Extrahierte Mitglieder können mit bereits indexierten physischen
Dateien verglichen werden, ohne als dauerhafte Source-Dateien vorgetäuscht zu
werden.

Member-Evidence behält Archiv-, Volume-, Member-, ToolExecution- und
Extraktionsprofil-Provenance. Unveränderte Archive verwenden exakte Listing-
und Member-Hash-Evidence wieder. Geänderte Archive, Tools, Adapter,
Passwort-Secret-Versionen oder Limits invalidieren nur die betroffenen
Ableitungen.

### EA7 — Separat aktivierbare Passwortprovider

**Ziel:** Erst nach lokaler Ausschöpfung können konfigurierte Onlinequellen
begrenzte Passwortkandidaten liefern.

Die Welle beginnt mit der Identitäts- und Schnittstellenklärung für
`Newzcrabber` sowie einer aktuellen Providerbewertung. Ohne geeignete
dokumentierte Schnittstelle endet die Welle mit einer begründeten
Nichtintegration. Online-Ergebnisse bleiben `EXTERNAL` Evidence und
verwenden dieselbe Secret-Handle-Grenze wie lokale Kandidaten.

### EA8 — Archive-aware Matching und Review

**Ziel:** Bytegleiche Archivmitglieder, physische Dateien,
Publikationscontainer und fachliche Editionen werden auf der richtigen Ebene
verglichen.

Die Welle trennt exakte Memberbytes, identische Containerbytes, gleiche
`Edition`, unterschiedliche Ausgabe, Formatvariante und reine
Qualitätsvariante. Ein Online-Passworttreffer oder gleicher Name reicht für
keine Relation. Unsichere Fälle gehen in die `Review Queue`.

ADR-0054 teilt diese Welle fail-closed. Bereits jetzt kann ein generisches
direktes, mehrteiliges oder Wrapper-Archive seine physische Source-Datei als
`ARCHIVE=KNOWN_PRESENT`-Dependency belegen. Publication Container bleiben
normale physische Medien und werden nicht allein wegen ZIP-/RAR-Struktur als
entbehrliche Verpackung behandelt. Member-/File- und Member-/Member-Identity
bleiben ohne vollständige Member-SHA-256 `UNKNOWN`; CRC, Größe, Locator und
Wrapper-Inner-Hash genügen nicht. S-EBA3-01 bis S-EBA3-03 implementieren nur
die Source-Dependency-Strecke. FG-A3-MEMBER-BYTE bleibt separat blockiert.

### EA9 — Calibre-, Sidecar- und Keep-Präferenz

**Ziel:** Eine spätere Deduplizierung kennt den Besitz- und
Abhängigkeitskontext jedes Kandidaten.

Read-only Calibre-Reconciliation identifiziert Bibliotheksrecords, Formate,
`metadata.opf`, Cover und weitere Sidecars. Keep-Präferenz verwendet
bestätigte Identitätsrelationen, Speicherortschutz, Calibre-Zugehörigkeit,
Begleitdateien und Quality-Evidence. Sie bleibt eine von der
Duplicate-Identität getrennte, reviewbare Entscheidung.

### EA10 — Vollständiger nicht ausführbarer Deduplizierungsplan

**Ziel:** W9 erzeugt einen restartfähigen `ConsolidationPlan`, der keine
Filesystemoperation ausführen kann.

Der Plan enthält mindestens:

- genau bezeichnete Keep- und Kandidatenobjekte über interne IDs;
- erwartete SHA-256-, Größen-, Zeit- und Root-Lineage;
- Begründung, Evidence und Reviewentscheidung;
- Calibre-/Sidecar-/Archiv-/Volume-Abhängigkeiten;
- erwartete Speicherersparnis;
- geplante Quarantäne-, Verifikations-, Rollback-, Purge- und optionale
  Empty-Directory-Schritte;
- explizite Preconditions und Blocker;
- inhaltsadressierte Planversion und unveränderliche Operationreihenfolge.

### EA11 — W10-Entscheidung und Quarantäne-Executor

**Status:** Blockiert bis zu einer neuen akzeptierten ADR.

Eine spätere ADR muss Source-Autorisierung, Approvalmodell, Root-Lease,
Fencing, changed-since-analysis-Prüfung, Crash-Recovery, Quarantäneort,
Cross-Volume-Semantik, Calibre-Write-Grenze, Rollback und Audit festlegen.

Der erste Executor darf ausschließlich revalidierte Kandidaten in eine
wiederherstellbare Quarantäne verschieben. Vor jeder Operation werden
Kandidat und mindestens ein verbleibender Keeper erneut vollständig gehasht.
Fingerprint-, Fortschritts- und Journalwrites werden mit der Operation
restartfähig verknüpft. Ein stale Besitzer darf nach Lease-Verlust keine
weitere Mutation ausführen.

### EA12 — Verifikation, Verzeichnisbereinigung und Purge

**Status:** Blockiert bis EA11, erfolgreichem Pilot und erneuter Freigabe.

Nach Quarantäne folgen ein inkrementeller Scan, Keeper-Lesetest,
Calibre-Konsistenzprüfung und ein konfiguriertes Rollbackfenster. Ein Purge ist
eine getrennt genehmigte Operation.

Leere Verzeichnisse werden ausschließlich bottom-up und separat geplant. Ein
Verzeichnis ist nur zulässig, wenn es innerhalb des autorisierten Roots liegt,
kein Root, Symlink oder Reparse Point ist, nach aktueller erneuter Auflistung
weder Dateien noch Unterverzeichnisse enthält und keine Calibre-, Archiv-,
Sidecar- oder Schutzbeziehung besitzt. Der Plan protokolliert entfernte
relative Verzeichnisse so, dass ihre Struktur bei einem Rollback rekonstruiert
werden kann.

## Teststrategie

Die Entwicklung benötigt keinen privaten Gesamtlauf als Funktionsgate.

| Ebene | Pflichtfälle |
|---|---|
| Unit | Signatur, Volumengruppierung, Pfadvalidierung, Passwortparser, Secret-Redaction, Planinvarianten |
| Integration | ZIP/RAR/7z/CBR/CBZ, verschlüsselt/unverschlüsselt, fehlendes Volume, falsches Passwort, CRC-Fehler, Nested Archive, Traversal, Symlink |
| Crash/Resume | Abbruch während Listing, Hash, Extraktion, Quarantäne, Verifikation und Rollback |
| Konkurrenz | genau ein Root-Writer, stale Fencing und keine Mutation nach Lease-Verlust |
| Calibre | mehrere Formate, `metadata.opf`, Cover, Duplicate-Record und bibliotheksfremde Kopie |
| Deduplizierung | mindestens ein Keeper, geänderte Datei, Hardlink, Cross-Volume, Sidecars, nur scheinbar leeres Verzeichnis |
| Privacy | kein Passwort, Pfad, privater Dateiname oder Querymaterial in CLI, Logs, DB-Feldern, Reports, Git oder CI |
| Pilot | synthetische Sammlung, danach begrenzter lokaler Spiegel-Canary; die autoritative Source erst nach separater Freigabe |

Zeit- und Größenlimits werden über injizierbare Testuhren, künstliche Streams
und kleine synthetische Archive geprüft. Testfixtures enthalten keine realen
Passwörter oder privaten Releaseinformationen.

## Betriebsreihenfolge einer späteren Aufräumaktion

1. abgeschlossenen und unveränderten Source-Scan fixieren;
2. Archive und Sidecars vollständig read-only inventarisieren;
3. offene Quick-Kandidaten mit vollständigem SHA-256 bestätigen;
4. lokale Archivpasswortkandidaten und technische Archivevidence erzeugen;
5. Entity Resolution, Matching und Review abschließen;
6. Calibre- und Sidecar-Abhängigkeiten read-only abgleichen;
7. nicht ausführbaren Deduplizierungsplan erzeugen und prüfen;
8. W10-Autorisierung und Planapproval separat bestätigen;
9. einen kleinen synthetischen und anschließend lokalen Spiegel-Canary in
   Quarantäne ausführen;
10. Rescan, Keeper- und Calibre-Prüfung sowie Rollbacktest durchführen;
11. begrenzte Wellen mit Heartbeat und Audit fortsetzen;
12. erst nach Ablauf der Aufbewahrungsfrist einen separaten Purge genehmigen;
13. leere Verzeichnisse zuletzt und mit eigener Freigabe behandeln.

## Abnahmekriterien der Gesamtstrecke

Die Strecke ist erst abgeschlossen, wenn:

1. Archive, Volumes, Sidecars und Publikationscontainer signature-first und
   inkrementell inventarisiert werden;
2. Passwortkandidaten lokal, begrenzt, versioniert und ohne Secret-Leakage
   verarbeitet werden;
3. optionales Online-Research privacy-bounded, provenance-behaftet und vom
   normalen Scan getrennt ist;
4. Archivevidence und physische Dateien auf der richtigen Identitätsebene
   verglichen werden;
5. Calibre- und Sidecar-Abhängigkeiten vor jeder Keep-/Remove-Präferenz
   bekannt sind;
6. W9 ausschließlich nicht ausführbare, revalidierbare Pläne erzeugt;
7. W10 nur nach akzeptierter ADR, Approval und changed-since-analysis-
   Revalidierung aktivierbar ist;
8. Quarantäne, Restart, Rollback, Purge und Empty-Directory-Cleanup getrennte
   auditierbare Zustände besitzen;
9. kein Fehlerpfad alle bestätigten Kopien eines Objekts entfernen kann;
10. private Daten, Passwörter und Runtime-Berichte außerhalb von Git und CI
    bleiben.
