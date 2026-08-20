# E-Book-Folgewelle: Archive und kontrollierte Deduplizierung

## Status und Geltungsbereich

**Status:** Geplant

**Stand:** 2026-08-17

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
Profile und Evidence Reuse verbindlich. Sie implementiert noch keine reale
Toolausführung, Persistenz oder Extraktion.

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

**Status:** Gate durch ADR-0038 akzeptiert; mechanische S-EBA-Pakete offen.

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

**Ziel:** Archive werden ohne dauerhafte Extraktion technisch bewertet.

Schutzgrenzen umfassen Mitgliederzahl, Gesamtgröße, Einzelgröße,
Kompressionsverhältnis, Verschachtelung, Pfadlänge, Laufzeit und
stdout/stderr-Artefaktgröße. Abgewiesen werden Traversal, absolute Pfade,
Gerätepfade, Alternate Data Streams, Symlinks, Reparse-Point-Ziele,
Hardlinks, FIFOs, Sockets, Devices und normalisierte Zielkollisionen. Die
exakten v1-Grenzen stehen in ADR-0038; `max_nested_depth=0` verhindert in der
ersten Runtime jede automatische Nested-Verarbeitung.

### EA5 — Private Testextraktion

**Ziel:** Ein technisch zulässiges Archiv kann in einem ephemeren privaten
Workspace vollständig geprüft werden.

Die Source bleibt read-only. Jedes Mitglied wird gestreamt gehasht; erwartete
und extrahierte Mitglieder, Größen und CRC-/Toolbefunde müssen konsistent
sein. Fehler, Passwortbedarf, fehlende Volumes oder Limits erzeugen einen
terminalen technischen Befund, aber keine Source-Operation. Der Workspace
wird nach sicherer Artifact-Übernahme bereinigt. Diese reale Runtime beginnt
erst nach S-EBA-01 bis S-EBA-07 und einem weiteren Frontier-Gate; die
7-Zip-CLI darf kein Secret über `-p` erhalten.

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
