# Future Capability Map

**Status:** Entwurf
**Stand:** 2026-08-20
**Scope:** langfristige Produktfähigkeiten und Medienlinien

## Zweck und Autorität

Diese Map ordnet die strategischen Fähigkeiten aus
`docs/vision/EVIDENCE_DRIVEN_COLLECTION_INTELLIGENCE.md` den bestehenden
Plänen zu. Sie vermeidet eine zweite Roadmap- oder Statushierarchie.

Maßgeblich bleiben:

1. `PROJECT_STATUS.md` für den implementierten Stand;
2. `BACKLOG.md` für kanonische Aufgaben und Statuswerte;
3. `IMPLEMENTATION_PLAN.md` für die W0-bis-W10-Folge;
4. `EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md` und
   `EBOOK_SPARK_WORK_PACKAGES.md` für die E-Book-Pakete;
5. `MODEL_ROUTING_POLICY.md` für Modell-, Thinking- und Agentenauswahl;
6. `EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md` für Archive;
7. akzeptierte ADRs für Architektur- und Sicherheitsverträge.

Die Einordnungen in diesem Dokument unterscheiden:

| Einordnung | Bedeutung |
|---|---|
| bestehender Plan, aktuell | durch kanonische Pläne beauftragt und laut aktueller Statusquelle in Bearbeitung |
| bestehender Plan, abhängigkeitsgebunden | durch kanonische Pläne beauftragt, aber erst nach den dort genannten Preconditions an der Reihe |
| bestehender Plan, bewusst zurückgestellt | im kanonischen Backlog vorhanden, aber noch nicht an der Reihe |
| strategischer Vorschlag, danach | begründete Fortsetzung nach dem aktiven E-Book-Endgame, noch kein Backlogstatus |
| strategischer Vorschlag, später | mögliche spätere Fähigkeit nach den genannten Preconditions |
| Forschungsfrage | benötigt Korpus, Primärquellenprüfung oder Frontier-Entscheidung |
| W10-blockiert | ausdrücklich nicht autorisierte Ausführung |

Diese Formulierungen sind Dokumentationskategorien, keine zusätzliche
Statusachse und keine öffentlichen Runtime-Literale.

## Kollisions- und Übernahmeregeln

- Eine vorhandene W-, E-, EB-, EA- oder FUT-Aufgabe wird referenziert und
  nicht unter einer neuen ID dupliziert.
- Ein neuer fachlicher Typ, Status, Enum, Persistenzvertrag oder
  Providerzugriff benötigt vor Implementierung eine ADR oder ein
  gleichwertiges im bestehenden Plan vorgesehenes Frontier-Gate.
- Eine Fähigkeit wird erst dann in `BACKLOG.md` übernommen, wenn ihr
  Nutzerergebnis, Scope, Preconditions, Privacy-Grenze, Abnahmekriterium und
  Modellwahl gemäß `MODEL_ROUTING_POLICY.md` feststehen.
- Source-Media-Mutation, Quarantäne, Purge, Retagging und
  Verzeichnisbereinigung bleiben unabhängig von dieser Map durch W10
  blockiert.
- Eine geplante Fähigkeit darf den aktiven E-Book-Endgame-Pfad nicht durch
  eine vorzeitige generische Neuarchitektur unterbrechen.

## Bezug zur aktuellen Ausgangsposition

Beim Aktualisieren dieser Map sind EB-07 und EB-08 abgeschlossen; die aktive
Arbeit liegt in der getrennten Archive-Strecke. Der genaue Paketstatus und der
jeweils nächste atomare Schritt werden hier nicht dupliziert; dafür sind
`PROJECT_STATUS.md`, `HANDOVER.md` und der Spark-Arbeitspaketkatalog
maßgeblich.

## Empfohlene Entwicklungsfolge

Die Phasen sind eine strategische Abhängigkeitsskizze für noch nicht
kanonisierte Fähigkeiten. Innerhalb bereits geplanter Arbeit setzen sie
weder Paketstatus noch Ausführungsreihenfolge.

### Phase 0: E-Book-Endgame abschließen

**Einordnung:** bestehender Plan, aktuell

Alle noch offenen E-Book- und Archive-Pakete werden ausschließlich nach der
Abhängigkeits- und Statusfolge der maßgeblichen Pläne fortgesetzt. Diese Map
öffnet abgeschlossene EB-Pakete nicht erneut und ordnet die aktive Archive-
Strecke nicht neu.

Die Archive-Strecke folgt ihrer eigenen EA-/EB-A-Zuordnung. W3-018 bis
W3-022 decken nur Discovery, Inventory, Listing und Member-Evidence ab;
EB-A2 und EB-A3 umfassen zusätzlich die in W5B, W6 und W9 zugeordneten
Secret-, Matching- und Planungsaufgaben. W10 bleibt unverändert blockiert.

Diese Phase wird nicht zugunsten einer neuen Medienlinie abgebrochen.

### Querschnittsgate: Portable Identität und föderierter Austausch

**Einordnung:** strategischer Vorschlag, danach; Kennzeichnungs-Writes
W10-blockiert

Vor einem portablen Export-/Importvertrag, einer Bibliotheks-Synchronisation
oder der Fusion mehrerer FolioTone-Systeme muss
[ADR-0042](../decisions/ADR-0042-federated-object-identity-and-exchange.md)
entschieden werden. Das Gate führt keinen universellen `Asset`-Typ ein und
ordnet die laufende E-Book-/Archive-Strecke nicht neu.

Empfohlene Reihenfolge:

1. Grenze zwischen lokaler `EntityId`, portabler Datensatz-Lineage,
   physischer Datei-/Repräsentationsidentität und Domain-Identität festlegen;
2. dauerhafte Knotenidentität sowie Clone-, Backup-, Restore- und
   Neuanlage-Semantik definieren;
3. versioniertes, bounded und idempotentes Offline-Austauschpaket mit
   Content-Digests, Provenance und Privacy-Grenzen festlegen;
4. Merge-, Conflict-, Trust- und Decision-Compatibility-Regeln ohne
   pauschales Last-write-wins definieren;
5. read-only Kennzeichnungsträger für OPF, XMP, Audio-Metadaten, externe
   Library-Felder und Sidecars bewerten;
6. jedes Schreiben einer Kennzeichnung oder externen Library-Änderung in ein
   getrenntes W10-Gate verweisen.

Dieses Querschnittsgate ist Voraussetzung für portablen Datenaustausch und
Multi-Instanz-Fusion. Es blockiert nicht die lokale book-only
`CollectionState`-Projektion oder den vorhandenen read-only
Calibre-Reconciliation-Vertrag.

### Phase 1: Produktprojektionen über der E-Book-Evidence

**Einordnung:** strategischer Vorschlag, danach

Empfohlene Reihenfolge:

1. `CollectionState` v1 als rebuildbare book-only Projektion;
2. Snapshot-Diff für zwei abgeschlossene Zustände;
3. validierter Query-AST und lokale Metadata-FTS-Suche;
4. mehrdimensionale `Library Health`-Sicht;
5. Content-Index-Policy nach Root, Medienrolle, Feld und Sensitivitätsklasse;
6. sichere lokale Freitextsuche über denselben Query-AST.

Die Phase liefert unmittelbaren Nutzerwert aus der vorhandenen Evidence,
bevor eine neue Medienanalyse aufgebaut wird.

### Phase 2: Präferenzen, Inbox und Preservation Planning

**Einordnung:** strategischer Vorschlag, danach

Auf EB-08 aufbauend:

1. lokale Preference Profiles;
2. versionierte Policy und erklärbare Best-Representation-Empfehlung;
3. Inbox-`ScanRoot` und nicht ausführbare Importplanung;
4. Root-/Replica-Rollen;
5. Fixity- und Backup-Reconciliation;
6. Restore-Evidence als separate spätere Fähigkeit.

Diese Phase bleibt zunächst book-only beziehungsweise technisch
rootbezogen. Die Resultate bleiben Recommendations und Pläne und
autorisieren keine Mutation. Eine medienübergreifende Generalisierung der
Domain-Projektionen und Preference Policy erfolgt erst nach der
Musik-Revalidierung.

### Phase 3: Musik als zweite vollständige Domäne

**Einordnung:** bestehender Plan, bewusst zurückgestellt

Die Folge innerhalb W4 bleibt:

1. technische Audio-/Container-Evidence über ffprobe;
2. versionierter Acoustic Fingerprint über Chromaprint/`fpcalc`;
3. lokale Tool- und strukturierte Provider-Evidence;
4. Music-Authority-Resolution;
5. begrenztes Matching über `MusicWork`, `Recording`,
   `ReleaseRecording`, `Release` und `ReleaseGroup`;
6. Review und Revalidierung des book-only `CollectionState`-Entwurfs;
7. bei Bedarf eine additive, versionierte medienübergreifende Projektion.

Erst der Abschluss dieses Vertical Slice belegt, welche E-Book-Verträge
tatsächlich medienübergreifend sind.

### Phase 4: Publikations- und Spoken-Audio-Profile

**Einordnung:** strategischer Vorschlag, später

- Hörbücher testen die Verbindung zwischen `Work`, Sprache/Übersetzung,
  Narration, Recording, Release und Kapitelreihenfolge.
- Comics und Manga testen Publikationscontainer, Page Sequence,
  Creator-Rollen und Serien-/Issue-Ordnung.
- CBZ und CBR verwenden den Archive-Core, bleiben aber
  Publikationsrepräsentationen und keine entbehrlichen Verpackungen.

Vor dieser Phase ist ein Frontier-Gate für die Identitätsebenen erforderlich.

### Phase 5: Bilder als dritte unabhängige Domäne

**Einordnung:** strategischer Vorschlag, später

Ein begrenzter Image-MVP umfasst:

1. Signatur- und technische Pixel-Evidence;
2. EXIF/IPTC/XMP/ICC-Beobachtungen;
3. exakte Kopien;
4. konservative Candidates für dieselbe Aufnahme beziehungsweise eine
   Ableitung;
5. Review und Quality-Dimensionen;
6. Projektion in Suche und `CollectionState`.

GPS bleibt separat gesperrt, bis ein Privacy-Gate die Speicherung und
Ausgabe definiert. Gesichtserkennung ist nicht Teil des MVP.

### Phase 6: Genau eine weitere große Domäne

**Einordnung:** Forschungsfrage

Nach E-Books, Musik und Bildern wird anhand realer Sammlungserfordernisse
entweder Video oder allgemeine Dokumente als nächster Spike gewählt. Beide
gleichzeitig zu beginnen würde Privacy-, Parser-, Provider- und
Korpusentscheidungen unnötig koppeln.

### Phase 7: Oberflächen und kontrollierte Ausführung

**Einordnung:** Forschungsfrage; ausführende Teile W10-blockiert

API, MCP, Web- oder Desktop-Oberfläche und ein Watcher/Daemon folgen erst,
wenn Query-, Policy-, Review- und Plan-Application-Verträge stabil sind.
Die CLI bleibt bis dahin Referenzadapter.

Eine ausführende Ebene ist davon getrennt. W10 benötigt eine eigene
Sicherheitsentscheidung und darf nicht aus einem UI- oder API-Bedarf
abgeleitet werden.

## Capability-Matrix

| Fähigkeit | Nutzerergebnis | Einordnung | Bestehende Zuordnung | Nächste Entscheidung |
|---|---|---|---|---|
| Calibre Reconciliation | Calibre- und Dateisystemzustand read-only vergleichen | bestehender Plan, aktuell | EB-07, W8, ADR-0033 | verbleibende Pakete gemäß Spark-Katalog |
| Keep Preference und Plan | bevorzugte Repräsentation und Blocker ohne Ausführung | bestehender Plan, abhängigkeitsgebunden | FG-08, EB-08, W9 | Frontier-Vertrag nach EB-07 |
| Archive Discovery/Inventory | Container, Volumes, Sidecars, Members und Integrität nachvollziehen | bestehender Plan, abhängigkeitsgebunden | W3-018 bis W3-022; EB-A1 und Teile von EB-A2 | bestehende Archive-Gates |
| Archive Matching/Planung | Secret-, Member-, Matching- und Planungs-Evidence verbinden | bestehender Plan, abhängigkeitsgebunden | W5B-011, W6-007, W9-004/W9-005; EB-A2/EB-A3 | bestehende Archive-Gates |
| Provider Cache/Book Provider | externe Evidence kontrolliert und offline wiederverwendbar machen | bestehender Plan, abhängigkeitsgebunden | EB-03A/B, W5B | vorhandene Provider-Gates |
| Classification Projection | widersprüchliche Facets getrennt und rebuildbar projizieren | bestehender Plan, abhängigkeitsgebunden | EB-04, W5C | FG-04 und Spark-Pakete |
| `CollectionState` | physische Beobachtungen, bestätigte Identitäten und offene Candidates getrennt verstehen | strategischer Vorschlag, danach | neu; Reports und Scan-Lineage sind Vorarbeit | Frontier-ADR und book-only v1 |
| Portable Identität und föderierter Austausch | Datensatz-Lineage über externe Kopien sowie zwischen FolioTone-Systemen nachvollziehen und konfliktbewusst fusionieren | strategischer Vorschlag, danach; Writes W10-blockiert | FUT-010, ADR-0011, ADR-0014 und ADR-0042 Proposed | FG-FED-IDENTITY, FG-FED-BUNDLE, FG-FED-MERGE und FG-FED-CARRIER |
| Snapshot Diff | Veränderungen zwischen zwei konsistenten Zuständen erklären | strategischer Vorschlag, danach | W2-Lineage ist Vorarbeit; keine direkte Backlogaufgabe | CollectionState-Vertrag |
| Sichere freie Suche | Metadaten und später Content lokal durchsuchen | strategischer Vorschlag, danach | neu | Query-AST, FTS und Privacy-ADR |
| Preference Policy | Empfehlungen anhand expliziter Nutzerpräferenzen erzeugen | strategischer Vorschlag, danach | EB-08 teilweise | Profil-, Versionierungs- und Explanation-Vertrag |
| Inbox und Importplanung | neue Objekte gegen den Bestand prüfen | strategischer Vorschlag, danach | neu | eigener Root-/Plan-Vertrag |
| Acquisition/Desired Set | vorhandene Erwerbskandidaten und Lücken gegenüber einem expliziten Sollbestand erkennen | strategischer Vorschlag, später | FUT-007 teilweise | Sollbestand-, Provider- und Rechte-Evidence |
| Library Health | unabhängige Zustandsdimensionen zusammenfassen | bestehender Plan, bewusst zurückgestellt | FUT-006 | CollectionState und Quality-Evidence |
| Fixity/Backup-Reconciliation | unerwartete Änderungen und Replica-Lücken erkennen | bestehender Plan, bewusst zurückgestellt | FUT-009 teilweise | Root-Rollen und Restore-Evidence |
| Music Vertical Slice | Musik auf Work-/Recording-/Release-Ebene verstehen | bestehender Plan, bewusst zurückgestellt | W4, W5, W6, W7 | nach reifer E-Book-Linie |
| Hörbücher | Buch- und Audioidentität verbinden | strategischer Vorschlag, später | neu | Frontier-Gate für Narration/Edition/Recording |
| Comics/Manga | Issues, Page Sequence und Publikationscontainer verstehen | strategischer Vorschlag, später | Archive-Pfad teilweise | Frontier-Gate für Comic-Identität |
| Bilder/Scans | Originale, Captures und Ableitungen unterscheiden | strategischer Vorschlag, später | FUT-001 teilweise | Image-Domain- und Privacy-ADR |
| Podcasts/Radio/Audio Drama | Spoken-Audio-Serien und Episoden verstehen | Forschungsfrage | neu | Domain- und Feed-Evidence-Gate |
| Dokumente | revisions-, OCR- und accessibility-bezogene Evidence | Forschungsfrage | PDF-Basis und FUT-002 teilweise | Content-Privacy- und Parser-Gate |
| Video | technische und später fachliche audiovisuelle Evidence | Forschungsfrage | keine kanonische Welle | Tool-/Domain-/Provider-Gate |
| Confidence-Kalibrierung | profilgebundene Scores an geprüfter Ground Truth bewerten | Forschungsfrage | FUT-005 berührt Review-Lernen | relationstypbezogener Korpus und Eval-Vertrag |
| KI-Query/Explanation | natürliche Sprache sicher übersetzen und Evidence erklären | Forschungsfrage | keine | gleicher Query-AST; keine Decision Authority |
| API/MCP/UI | stabile Application-Verträge außerhalb der CLI anbieten | Forschungsfrage | ADR-0016 stellt zurück | neue Produktoberflächen-ADR |
| kontrollierte Mutation | geprüfte Pläne entsprechend ihrer Reversibilitätsklasse ausführen | W10-blockiert | W10 | ausdrückliche W10-ADR und Benutzerfreigabe |

## Medienabdeckung

Die Formatspalten sind Startpunkte für Analyzer und keine exklusive
Klassifikation. Ein PDF, M4A oder Bild kann mehrere fachliche Rollen tragen;
Domain-Zuordnung erfolgt über Signatur, Struktur, Kontext und Evidence.

| Medienlinie | Frühe Formate | Identitätsebenen im ersten Slice | Besondere Evidence |
|---|---|---|---|
| E-Books | EPUB, MOBI, AZW, AZW3, PDF | `Work`, `Edition`, Repräsentation, Datei | Text, Struktur, Cover, Identifier, Calibre Ownership |
| Comics/Manga | EPUB Fixed Layout, PDF, CBZ, CBR | Series, Volume, Issue, Page Sequence, Repräsentation | `ComicInfo.xml`, Creator-Rollen, Leserichtung |
| Musik | FLAC, MP3, M4A, OGG, Opus, WAV, AIFF | `MusicWork`, `Recording`, `ReleaseRecording`, `Release`, `ReleaseGroup`, Datei | Acoustic Fingerprint, Trackordnung, Credits, technische Audioqualität |
| Hörbücher | M4B, MP3, M4A, Opus | Work, Fassung, Narration, Edition/Release, Kapitel, Datei | Narrator, abridged, Reading Order, Dauer |
| Bilder | JPEG, PNG, TIFF, WebP, HEIF/AVIF, ausgewählte RAW | Capture, Original, Derivative, Repräsentation, Datei | EXIF/IPTC/XMP/ICC, perceptual Fingerprint, GPS separat |
| Dokumente | PDF, DOCX, ODT, RTF, HTML, Markdown, Text | Document Work, Revision/Edition, Rendition, Datei | Text/OCR, Signaturen, Anhänge, Accessibility |
| Video | MP4, MKV, MOV, WebM | Audiovisual Work, Cut/Edit, Release, Stream/Repräsentation, Datei | Streams, HDR, Untertitel, Kapitel, spätere Fingerprints |
| Podcasts/Radio/Audio Drama | MP3, M4A, Opus | Feed/Series, Episode Work, Recording/Edit, Distribution Item, Datei | Feed-GUID, Episode-Reihenfolge, Credits, Distribution-Evidence |

Die Identitätsebenen für Hörbuch, Comic, Bild, Dokument, Video und Podcast
sowie die hier beschreibend verwendeten Begriffe `Repräsentation`,
Capture, Original, Derivative, Rendition und Distribution Item sind
Arbeitsbegriffe. Sie werden erst durch die jeweiligen Frontier-ADRs
kanonisch.

## Gemeinsamer Information Contract

Jede neue Medienlinie muss vor Implementierung mindestens festlegen:

1. Source-Signatur und erlaubte Formate;
2. Datei-, Inhalts- und Domain-Identitätsebenen sowie zulässige
   Mehrfachrollen derselben Observation;
3. relevante Container-, Member-, Sidecar- und Derivation-Beziehungen;
4. rohe, normalisierte, externe und benutzerbestätigte Evidence;
5. Tool-/Provider-Manifest, Versionen, Grenzen und Fehlersemantik;
6. Blocking- und Matching-False-Positive-Grenzen;
7. Quality-, Integrity- und Accessibility-Dimensionen;
8. Privacy-Klasse, Provider-Minimierung und Artefakt-Retention;
9. bounded Query-, Persistenz- und Restart-Vertrag;
10. Review-, Reuse-, Staleness- und Explanation-Regeln;
11. synthetischen Korpus und adversarial Negativfälle;
12. ausdrücklichen Nachweis unveränderter Source Media.
13. bei portablen Daten die ausstellende Knoten-/Objekt-Lineage,
    Exchange-Provenance, Idempotenz, Conflict- und Trust-Grenzen.

## Erforderliche Frontier-Entscheidungen

Die folgenden Fragen werden nicht in Spark-Paketen vorentschieden:

- `CollectionState`-Lineage und Rebuild-Semantik;
- Query-AST, FTS-Projektion, Limits, Content-Index-Privacy sowie
  Retention, Backup, Purge und Query-History;
- Preference Profile, Policy und Best-Representation-Erklärung;
- additive `Expression`-/`Representation`-/`Derivation`-Semantik;
- portable Knoten-/Objektreferenzen, Austauschpaket, Clone-/Restore-Vertrag,
  Trust, Replay-Schutz und deterministische Konfliktbehandlung;
- Root-/Replica-/Backup-/Restore-Modell;
- Hörbuch- und Comic-Identitätsebenen;
- Image-Sensitivität und Derivative Matching;
- empirische Confidence-Kalibrierung aus versionierter Review-Ground-Truth;
- API-/MCP-/UI-Application-Vertrag;
- jede W10-Mutations-, Quarantäne-, Rollback- und Purge-Semantik.

## Kriterien für eine Backlog-Übernahme

Ein strategischer Vorschlag oder eine Forschungsfrage wird nur übernommen,
wenn:

- ein konkretes Nutzerergebnis und ein begrenzter erster Slice benannt sind;
- keine vorhandene W-/EB-/EA-/FUT-Aufgabe dupliziert wird;
- Domain- und Evidence-Grenzen kollisionsfrei sind;
- Privacy-, Security- und W10-Auswirkungen feststehen;
- aktuelle externe Primärquellen für Tools und Provider geprüft wurden;
- ein vollständig synthetischer Testkorpus und Abbruchbedingungen existieren;
- Modellwahl und atomare PR-Pakete dokumentiert sind;
- `BACKLOG.md`, Status und gegebenenfalls ADR konsistent aktualisiert werden.

## Pflege

Die Map wird bei einer tatsächlichen Übernahme oder Ablehnung aktualisiert.
Zeitgebundene Produkt-, Provider- oder Toolaussagen werden nicht ungeprüft aus
der Roh-Ideensammlung übernommen. Ein Vorschlag bleibt Entwurf, bis sein
Vertrag in den maßgeblichen Dokumenten ausdrücklich akzeptiert wurde.
