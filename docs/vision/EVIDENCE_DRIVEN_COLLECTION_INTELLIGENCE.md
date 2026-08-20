# Evidence-driven Collection Intelligence

**Status:** Entwurf
**Stand:** 2026-08-20
**Autorität:** strategische Produktvision, keine Architekturentscheidung und
keine Statusquelle

## Zweck und Geltungsgrenze

Dieses Dokument beschreibt eine begründete langfristige Richtung für
FolioTone. Es verdichtet Erkenntnisse aus der bisherigen E-Book-Entwicklung
und aus der nichtkanonischen Ideensammlung, entscheidet aber keine neuen
Klassen, Enums, Tabellen, Provider oder Mutationsrechte.

Für den implementierten Stand bleibt
`docs/planning/PROJECT_STATUS.md` maßgeblich. Aufgabenstatus und Reihenfolge
bestimmen `BACKLOG.md`, `IMPLEMENTATION_PLAN.md` sowie die bestehenden
E-Book- und Archive-Pläne. Akzeptierte ADRs haben bei einem Widerspruch
Vorrang. Eine Fähigkeit aus dieser Vision wird erst nach einem eigenen
Vertragsgate in Architektur, Backlog und Implementierung übernommen.

## Produktthese

FolioTone soll eine lokale, evidenzbasierte Wissens-, Abgleichs- und
Entscheidungsschicht für digitale Sammlungen werden. Das Produkt soll nicht
nur beantworten, welche Dateien vorhanden sind, sondern welche Werke,
Ausgaben, Aufnahmen, Veröffentlichungen, Repräsentationen und Ableitungen die
Sammlung enthält, wie sicher diese Aussagen sind und welche nächsten Schritte
unter den Präferenzen des Benutzers vertretbar wären.

FolioTone ist damit kein weiterer Reader, Player, Tagger, Dateimanager,
Download-Manager oder einfacher Duplicate Cleaner. Spezialisierte Werkzeuge
bleiben für Formatwissen und technische Analyse zuständig. FolioTone
orchestriert sie, erhält ihre Ergebnisse als `Evidence` und verbindet sie
mit Provenance, Domain-Identität, Review und sicheren Planungsentscheidungen.

## Gewünschte Nutzerergebnisse

Ein reifer Stand soll insbesondere folgende Fragen nachvollziehbar
beantworten:

- Was ist in der Sammlung auf Datei-, Inhalts-, Werk-, Editions-,
  Aufnahme- oder Veröffentlichungsebene vorhanden?
- Welche Objekte sind exakte Kopien, Varianten, Übersetzungen,
  Neuveröffentlichungen oder abgeleitete Repräsentationen?
- Welche Aussagen sind beobachtet, abgeleitet, extern geliefert,
  benutzerbestätigt, widersprüchlich oder noch ungeklärt?
- Welche Repräsentation erfüllt eine konkrete Benutzerpräferenz am besten,
  ohne Identität und Qualität zu vermischen?
- Welche Objekte sind neu, verschwunden, verändert, unvollständig,
  beschädigt, ungesichert oder reviewpflichtig?
- Welche FolioTone-Datensätze, externen Bibliothekskopien und Derivate gehören
  zu derselben nachvollziehbaren Lineage, auch wenn Pfad, Dateiname oder
  Dateibytes verändert wurden?
- Wie können zwei FolioTone-Systeme ausgewählte Daten austauschen oder
  fusionieren, ohne Provenance, lokale Entscheidungen oder Konflikte zu
  verlieren?
- Welche geplante Aufräum- oder Importentscheidung wäre möglich, welche
  Preconditions und Blocker gelten und wie könnte sie später kontrolliert
  rückgängig gemacht werden?

## Leitprinzipien

### Local-first und privacy-by-default

Normale Scans, Matching, Review und Suche müssen offline funktionieren.
Absolute lokale Pfade werden niemals an Online-Provider übermittelt.
Sammlungsinventare, Volltexte, Bilder, Audioinhalte und private Metadaten
bleiben ebenfalls lokal, solange nicht ein eigener ausdrücklich begrenzter
Privacy-Vertrag eine minimale strukturierte Teilabfrage erlaubt. Provider
erhalten nur die für diese konkrete Abfrage erforderlichen Felder.

### Evidence ist keine Wahrheit

Dateisystembeobachtungen, Parserwerte, Toolergebnisse, Katalogdaten,
Fingerprints und Benutzerentscheidungen bleiben unterscheidbar. Kein einzelnes
Tool, kein Provider und keine KI-Ausgabe wird allein zur kanonischen Wahrheit.
Widersprüche werden erhalten und erklärt.

### Identitätsebenen bleiben explizit

Ein gleicher Hash, Titel, Name oder Identifier beantwortet nicht automatisch
dieselbe fachliche Frage. Dateiidentität, Inhaltsgleichheit, `Work`,
`Edition`, `MusicWork`, `Recording`, `ReleaseGroup` und `Release`
bleiben getrennte Ebenen. Dateipräsenz und Sammlungsvorkommen sind davon
getrennte Beobachtungen; sie beweisen weder fachliche Identität noch Eigentum
oder ein Nutzungsrecht. Neue Domänen erhalten eigene Identitätsverträge.

### Versioniert, reproduzierbar und begrenzt

Jede relevante Ableitung bindet sich an Input-Lineage, Tool-, Parser-,
Algorithmus-, Profil- und Konfigurationsversion. Verarbeitung bleibt
inkrementell, speicherbegrenzt und fortsetzbar. Collection-weite
All-vs-all-Suchen und unbeschränkte Ergebnislisten sind ausgeschlossen.

### Spezialisten orchestrieren

FolioTone implementiert native Logik dort, wo Domainverträge, Provenance,
Safety oder nachgewiesene Funktionslücken dies erfordern. Es baut calibre,
FFmpeg, ExifTool, beets, EPUBCheck oder Archivwerkzeuge nicht nach.

### Entscheidungen sind erklärbar und überprüfbar

Eine Empfehlung nennt die verwendete Evidence, Contradictions,
Profilversion, Präferenzen und Blocker. Review-Entscheidungen bleiben
append-only und werden nur bei semantisch kompatiblen Fällen wiederverwendet.

### Source Media bleibt bis W10 read-only

Die Kette bis W9 endet bei nicht ausführbaren Plänen. Ein späterer
Write-Pfad benötigt eine eigene akzeptierte ADR, frische Preconditions,
Fencing, Quarantäne, Verifikation, Audit und einen belastbaren
Wiederherstellungsvertrag. Ein Scan löst keine Extraktion, Verschiebung,
Metadatenänderung oder Löschung aus.

## Schichtenmodell

Die empfohlene Produktkette lautet:

```text
FileObservation
  -> Evidence + Provenance
  -> Domain Identity + Relations
  -> CollectionState
  -> Query
  -> User Policy
  -> Review / Decision
  -> nicht ausführbarer Plan
  -> später separat autorisierte Ausführung
```

`CollectionState`, Query, Policy, `Representation`, `Expression` und
`Derivation` sind in diesem Dokument Fähigkeits- beziehungsweise
Arbeitsbegriffe, noch keine akzeptierten öffentlichen Typen. Sie dürfen nicht
ohne ADR und Korpusbelege in das Domain Model übernommen werden. Dasselbe gilt
für alle beispielhaften PascalCase- oder GROSSBUCHSTABEN-Bezeichnungen, die
nicht bereits in Code oder akzeptierten ADRs definiert sind; sie sind keine
neuen Runtime-Literale.

## Gemeinsamer Kern und domänenspezifische Modelle

Medienübergreifend sinnvoll sind:

- `ScanRoot`, `ScanRun`, `FileRecord`, `FileObservation` und
  Präsenzhistorie;
- Dateisignatur, Container-/Member-Bezug, Sidecar, Dependency und Ownership;
- immutable `Evidence`, `ValueAssertion`, `Provenance`,
  `ExternalIdentifier` und versionierte `Fingerprint`-Werte;
- `Agent`, `AgentName` und typisierte Rollen beziehungsweise Credits;
- `RelationCandidate`, bestätigte `Relation`, `ReviewItem` und
  append-only `ReviewDecision`;
- `ToolProvider`, `Knowledge Provider`, Quality Findings und
  Classification Assertions;
- Snapshot-, Query-, Preference-, Policy- und Planungsprotokolle, sobald ihre
  jeweiligen Verträge akzeptiert sind.

Domänenspezifisch bleiben mindestens:

- Identitätsstufen und erlaubte Relations;
- Rollen und Identifier-Namensräume;
- Blocking-, Matching- und Confidence-Regeln;
- technische Qualitätsdimensionen;
- Provider-Mappings und Pflichtfelder;
- Accessibility-, Schutz- und Integritätsbefunde.

Ein universelles `Asset`-God-Object wird nicht vorab eingeführt. Erst die
Erfahrung aus E-Books, Musik und einer dritten unabhängigen Domäne soll zeigen,
welche gemeinsamen Konzepte tatsächlich stabil sind. Ein graphförmiges
Fachmodell erfordert ebenfalls keine Graphdatenbank. SQLite bleibt zunächst
System of Record; Such- oder Graphsichten wären rebuildbare Projektionen.

## Portable Objektidentität und föderierter Austausch

FolioTone soll ausgewählte Datensätze später medienübergreifend transportieren
und zwischen mehreren FolioTone-Systemen nachvollziehbar abgleichen können.
Diese Fähigkeit benötigt eine portable Referenz auf die von einem System
erzeugte Datensatz-Lineage sowie eine dauerhafte Knotenidentität. Die portable
Referenz ergänzt die lokale `EntityId`; sie ersetzt weder File- noch
Domain-Identität.

Ein Pfad, Dateiname, aktueller Datei-Hash oder externer Katalog-Identifier ist
keine ausreichende portable Identität. Derselbe Hash kann mehrere getrennte
Kopien beschreiben. Eine Metadatenkorrektur kann den Hash verändern. ISBN,
MusicBrainz-ID oder vergleichbare Identifier adressieren fachliche Ebenen und
nicht automatisch eine konkrete Datei beziehungsweise deren FolioTone-
Lineage.

Eine in OPF, XMP, Audio-Metadaten, einem externen Custom Field oder einem
Sidecar gespeicherte FolioTone-Referenz kann den Kontext transportieren. Sie
bleibt veränderbare Evidence und darf einen Merge nicht allein autorisieren.
Die FolioTone-Persistenz und ein versioniertes, bounded Austauschpaket bleiben
die maßgeblichen Träger. Das Lesen einer vorhandenen Kennzeichnung kann später
read-only erfolgen; jedes Einbetten oder Aktualisieren in Source Media oder
einer externen Bibliothek bleibt W10-blockiert.

Ein föderierter Austausch muss mindestens:

- ausstellenden Knoten, Objekt-/Record-Art, stabile Referenz und
  Profilversion binden;
- Observation-, Assertion-, Evidence-, Relation- und Review-Provenance
  erhalten;
- offline, scope-begrenzt, privacy-geprüft und idempotent importierbar sein;
- unabhängig erzeugte Referenzen als Matching-/Review-Fall behandeln;
- konkurrierende Revisionen und lokale Entscheidungen getrennt erhalten;
- ohne Last-write-wins allein nach Wall-Clock-Zeit auskommen;
- Clone-, Backup-, Restore-, Replay-, Widerrufs- und Trust-Grenzen ausdrücklich
  definieren.

Die Richtung setzt weder Event Sourcing noch CRDTs, Echtzeit-Synchronisation
oder eine zentrale Registry voraus. Signatur, Verschlüsselung, Transport und
Vertrauen sind separate Verträge. [ADR-0042](../decisions/ADR-0042-federated-object-identity-and-exchange.md)
beschreibt das vorgeschlagene Frontier-Gate; sie ist noch keine akzeptierte
Architekturentscheidung.

Eine Dateiendung bestimmt keine exklusive Medienlinie. Ein PDF kann
E-Book, Comic oder allgemeines Dokument sein; M4A und Opus können Musik oder
Hörbuch enthalten; ein Bild kann eigenständiges Foto, Scan, Comicseite, Cover
oder Artwork-Sidecar sein. Domain-Routing verwendet Signatur, Struktur,
Kontext und Evidence. Dieselbe physische Observation darf mehrere fachliche
Rollen oder Domain-Kontexte tragen, ohne deshalb mehrfach dieselbe Datei zu
erfinden.

## Priorisierte Medienstrategie

### 1. E-Books und Publikationscontainer

Die E-Book-Linie wird ohne Richtungswechsel fertiggestellt. Der aktuelle
Scope umfasst EPUB, MOBI, AZW, AZW3 und PDF sowie anschließend die bereits
geplante Archive-/Sidecar-Strecke. CBZ und CBR sind
Publikationscontainer und dürfen nicht allein wegen ihrer ZIP-/RAR-Technik
wie entbehrliche Verpackungsarchive behandelt werden.

Vor einer breiten Medienausdehnung sollen Calibre-Reconciliation,
book-only Review, Keep Preference und der nicht ausführbare
`ConsolidationPlan` belastbar sein. Danach liefern `CollectionState`,
sichere Suche und Preference Policy den ersten direkt nutzbaren
Produktlayer über der vorhandenen Evidence.

### 2. Musik

Musik ist die nächste vollständige eigenständige Domäne. Relevante Formate
sind zunächst FLAC, MP3, M4A mit AAC oder ALAC, OGG, Opus, WAV und AIFF.
Das bestehende Modell erhält `MusicWork`, `Recording`, `ReleaseGroup`,
`Release` und die Many-to-many-Zuordnung `ReleaseRecording`: Ein
`Release` gehört fachlich zu einem `ReleaseGroup`, während dieselbe
`Recording` über `ReleaseRecording` auf mehreren Releases erscheinen kann.
Technische Tags und Acoustic Fingerprints dürfen diese Ebenen nicht
zusammenfassen.

### 3. Hörbücher und Spoken Publications

Hörbücher bilden eine geeignete Brücke zwischen Buch- und Audioverträgen.
Ein späterer Pilot soll literarisches Werk, Sprache oder Übersetzung,
gekürzte beziehungsweise ungekürzte Fassung, Narration, Edition oder
Veröffentlichung, Kapitelreihenfolge, Audio-Repräsentation und physische
Datei trennen. Navigation, Accessibility-Metadaten und ergänzende Ressourcen
gehören zur Evidence. Ausgangsformate sind M4B, MP3, M4A und Opus.

### 4. Comics und Manga

Comics sind ein publikationsnahes Profil mit Series, Volume, Issue,
Story Arc, Creator-Rollen, Leserichtung und geordneter Page Sequence.
EPUB Fixed Layout, PDF, CBZ und CBR gehören in denselben fachlichen
Vergleich, ohne Archive- und Publikationsidentität zu verwechseln.
`ComicInfo.xml` wäre Evidence und keine kanonische Wahrheit.

Das spätere Frontier-Gate muss mindestens Reprint oder neue Edition,
Variant Cover, Übersetzung gegenüber Scanlation, einzelne Stories in
mehreren Issues, Collected Edition beziehungsweise Omnibus sowie
Digitalausgabe gegenüber Scan derselben Druckausgabe unterscheiden.

### 5. Bilder, Fotos und Scans

Bilder sind die erste wirklich unabhängige dritte Domäne und damit ein
geeigneter Test für Original-, Capture-, Derivative- und
Representation-Semantik. Ein erster Scope umfasst JPEG, PNG, TIFF, WebP,
HEIF/AVIF und ausgewählte RAW-Formate. Er beginnt mit exakten Kopien,
technischen Eigenschaften und konservativen perceptual oder derivative
Candidates. Gesichtserkennung und automatische Personenidentifikation sind
nicht Teil des Anfangsscopes.

Cross-Domain-Derivationen bleiben sichtbar: Scan-Seiten können zu OCR-Text,
PDF und EPUB führen; ein RAW kann über einen Edit zu mehreren Exporten werden;
eine Coverdatei kann Calibre-Sidecar und zugleich Image-Evidence sein. Source
und Derivative sind dadurch weder automatisch identisch noch entbehrliche
Duplikate.

### 6. Allgemeine Dokumente

PDF, DOCX, ODT, RTF, HTML, Markdown und Text können später als eigene
Dokumentdomäne folgen. Volltext, OCR, Signaturen, Makros und eingebettete
Anhänge erhöhen Datenschutz- und Parserrisiken. Die Domäne wird deshalb
nach Root, Medienrolle, Feld und Sensitivitätsklasse opt-in und nicht als
beiläufige Erweiterung der E-Book-Analyse eingeführt.

### 7. Video

MP4, MKV, MOV und WebM werden zunächst nur technisch betrachtet:
Container, Streams, Codecs, Laufzeit, Auflösung, Framerate, HDR,
Audiospuren, Untertitel und Kapitel. Inhaltliche Film-/Serienidentität und
perceptual Video Matching folgen erst nach einer eigenen Domain- und
Providerentscheidung.

Accessibility- und Stream-Evidence soll später Text- beziehungsweise
Subtitle-Tracks für Captions, SDH oder Forced Subtitles, Audio-Tracks für
Audio Description und Video- beziehungsweise Visual-Tracks für
Sign-Language-Inhalte unterscheiden, ohne diese Arbeitsbegriffe hier als
Literale festzulegen.

### 8. Podcasts, Radio und Audio Drama

Spoken-Audio-Serien außerhalb von Hörbüchern bleiben ein späteres
Forschungsprofil. Mögliche Ebenen sind Feed oder Series, Episode Work,
Recording beziehungsweise Edit, Distribution Item und Datei. Feed-GUIDs und
andere Distribution-Metadaten sind Evidence und keine dauerhafte
FolioTone-Identität.

### Vorläufig nicht als Medienlinie

ZIP, RAR, 7z und TAR sind Container. OPF, NFO, CUE, Playlists, Untertitel,
Cover und Checksummendateien sind Sidecars oder Dependencies. Software,
Games, Executables, Disk Images, E-Mail-/Chatarchive und reine
Streaming-Entitlements bleiben außerhalb der geplanten fachlichen
Medienlinien; ihre Dateien dürfen höchstens im generischen Inventar
erscheinen.

## Kandidaten für spezialisierte Werkzeuge

Die bestehenden Registries
`docs/reference/EXTERNAL_TOOLS.md` und
`docs/reference/EXTERNAL_DATA_SOURCES.md` bleiben maßgeblich. Für neue
Medienlinien sind derzeit folgende nichtbindende Prüfpfade sinnvoll:

- Musik, Hörbuch und Video: ffprobe für technische Evidence sowie
  Chromaprint/`fpcalc` für versionierte Audiofingerprints;
- Bilder: ExifTool für read-only Metadaten und Pillow oder libvips für
  begrenzte technische beziehungsweise perceptual Pixelanalyse;
- Comics: der bestehende Archive-Core plus ein begrenzter
  `ComicInfo.xml`-Parser;
- Matroska-Video: ffprobe zuerst, gegebenenfalls MKVToolNix Identify als
  ergänzender Spezialist;
- Dokumente: Poppler und qpdf für PDF; Apache Tika höchstens als
  Discovery-/Fallback-Sensor; OCRmyPDF oder Tesseract nur für private
  abgeleitete Outputs.

Vor jeder Integration werden Primärdokumentation, Lizenz,
Automationsschnittstelle, Security, Maintenance und feste read-only Shapes
aktuell geprüft. Diese Liste akzeptiert weder ein Tool noch eine Version.

## Zu sammelnde Informationen

### Medienübergreifende Baseline

| Bereich | Zu erhaltende Information |
|---|---|
| Physischer Bestand | logischer Root, privater relativer Locator, Präsenz- und Änderungshistorie, Größe und Dateizeiten |
| Technische Identität | Signatur statt bloßer Extension, Quick- und Full-Hash, Container, Member und Sidecar-Bezug |
| Technische Eigenschaften | Format- und Codec-Version, Struktur, Streams, Seiten, Dauer, Abmessungen und relevante Formatrisiken |
| Integrität | Parser-/Toolstatus, Korruptionsbefunde, Fixity und später Restore-Evidence |
| Metadaten | rohe Beobachtungen, normalisierte Candidates, externe Assertions und benutzerbestätigte Werte getrennt |
| Fachliche Identität | Domain-Ebene, Rollen, externe Identifier, Relations, Contradictions und Confidence-Kontext |
| Provenance | Quelle, Tool, Provider, Parser, Algorithmus, Profil, Konfiguration, Zeitpunkt und Input-Lineage |
| Qualität | mehrere unabhängige Dimensionen, Coverage, Accessibility und Schutzbefunde ohne universellen Score |
| Besitz und Abhängigkeit | Root-Rolle, Replica-/Backup-Bezug, Container, Sidecars, Ownership und Derivation |
| Entscheidung | Review-Historie, Präferenzprofil, angewandte Policy, Recommendation, Plan und Preconditions |
| Datenschutz | Sensitivitätsklasse, erlaubte lokale Indizes, Providerfreigabe und Artefakt-Retention |

Relative Locator, Rohwerte und Content können intern erforderlich sein, sind
aber nicht automatisch für öffentliche DTOs oder Reports geeignet.

### E-Books

Zu erhalten sind Titel und Untertitel, Sprache und Script, Edition Statement,
Verlag und Imprint, Publikationsdatum, ISBN und weitere Identifier,
Contributors mit Rollen, Series und Position, Inhalts- beziehungsweise
Lesereihenfolge, Textfingerprint, Cover, eingebettete Ressourcen, Fonts,
Reflow- oder Fixed-Layout-Eigenschaft, Strukturvalidität, Accessibility sowie
erkannte Protection oder DRM. DRM wird erkannt, nicht umgangen.

### Musik

Zu erhalten sind rohe Tags, MusicBrainz- und weitere Identifier, ISRC, ISWC,
Barcode und Katalogbezeichnungen, Contributors und Instrumente, Medium-,
Disc- und Track-Reihenfolge, Codec, Sample Rate, Bit Depth, Kanäle, Bitrate,
Dauer, Acoustic Fingerprint, ReplayGain- oder Loudness-Evidence, Artwork sowie
Live-, Remix-, Remaster- und Release-Varianten.

### Hörbücher

Zu erhalten sind die Verknüpfung zum Buchwerk, Erzähler und Cast, Sprache und
Übersetzung, gekürzt oder ungekürzt, Produktion und Publisher, Gesamt- und
Teildauer, Kapitel- beziehungsweise Segmentreihenfolge, ergänzende Ressourcen
und technische Audioqualität. Reading Order, Navigation und vorhandene
Accessibility-Metadaten bleiben als getrennte Evidence erhalten.

### Comics

Zu erhalten sind Series, Volume, Issue, Issue Count, Story Arc und
Lesereihenfolge, Writer-, Penciller-, Inker-, Colorist-, Letterer- und
Cover-Artist-Rollen, Publisher, Sprache, Identifier, Page Sequence,
Page-Typen, Abmessungen, Cover, Leserichtung, Navigation und
Scanlation-Evidence.

### Bilder

Zu erhalten sind EXIF-, IPTC-, XMP-, ICC- und gegebenenfalls signierte
Provenance-Beobachtungen, Capture-Zeit, Gerät, Linse, Belichtung,
Orientierung, Abmessungen, Bit Depth, Farbraum, RAW-/Original-/Edit-/
Export-Beziehungen sowie exakte und perceptual Fingerprints. GPS ist
hochsensitiv und benötigt eine separate Freigabe.

### Dokumente

Zu erhalten sind Titel, Autoren, Revision, Datum und Identifier,
Seitanzahl, Sprache, Text- und OCR-Coverage, Struktur, Fonts,
Accessibility, Signaturen, Verschlüsselung, Makros und Anhänge. Volltext wird
nur lokal und nach expliziter Freigabe für Root, Medienrolle, Feld und
Sensitivitätsklasse indexiert.

### Video

Zu erhalten sind Container, Video-, Audio-, Untertitel- und Datenspuren,
Codecs und Profile, Auflösung, Framerate, HDR- und Farbinformation,
Audiolayout, Sprachen, Kapitel, Attachments, Laufzeit und technische
Integrität. Caption-/SDH-/Forced-Subtitles-Rollen gehören zu Text- oder
Subtitle-Tracks, Audio Description zu Audio-Tracks und Sign-Language-Inhalte
zu Video- oder Visual-Tracks. Inhaltliche Fingerprints benötigen einen
späteren versionierten Vertrag.

### Archive

Zu erhalten sind Signatur und Containerklasse, Volume-Zusammenhang,
Memberliste, Memberpfade, deklarierte und tatsächliche Größen,
Checksummen, Verschlüsselungs- und Passwortstatus, Korruptionsbefunde,
Extraktions-Lineage und Budgetbefunde. Klartextpasswörter werden nicht
persistiert; FolioTone verwendet ausschließlich opake Secret Handles.

## CollectionState, Suche und zeitliche Sicht

Ein künftiger `CollectionState` soll eine rebuildbare, versionierte
Projektion mit drei strikt getrennten Sichten sein:

1. physisch beobachtete Dateien, Presence und technische Evidence;
2. bestätigte beziehungsweise effektiv akzeptierte Domain-Identitäten und
   Relations;
3. ungeklärte Candidates, Contradictions und Reviewbedarf.

Ein ungeklärter Candidate darf nicht als vorhandenes `Work`, `Edition`
oder `Release` gezählt werden. Der Zustand soll außerdem zeigen:

- eindeutige, redundante, problematische, bevorzugte und reviewpflichtige
  Zustände innerhalb der jeweiligen Sicht;
- Root- und Storage-Rollen sowie Replica- und Backup-Coverage;
- fehlende Analysis oder Evidence;
- Unterschiede zwischen zwei abgeschlossenen Snapshots.

Ein `CollectionState` überschreibt keine Roh-Evidence und wird nicht zur
zweiten kanonischen Datenbank.

Freier Suchtext gehört ausdrücklich zur Zielrichtung. Die sichere
Verarbeitung lautet:

```text
Benutzereingabe
  -> deterministischer Parser oder optionaler lokaler Sprachadapter
  -> validierter Query-AST
  -> parameterisierte SQLite-/FTS-Abfrage
  -> begrenztes, erklärbares Ergebnis
```

Freitext wird niemals als rohe Shell-, SQL- oder `calibredb`-Argumentfolge
weitergereicht. Der erste Suchumfang soll lokale Metadaten, feste Filter und
Facetten abdecken. Inhaltsvolltext, OCR-Text und sensitive Bildmetadaten
werden nur durch eine explizite Content-Index-Policy nach Root, Medienrolle,
Feld und Sensitivitätsklasse aufgenommen. Der spätere Vertrag regelt auch
Retention, Purge, Backup, Export und Rebuild des lokalen Index. Suchtext und
Query-Historie gelten als sensitive Runtime-Daten. Suchergebnisse
unterscheiden beobachtete, abgeleitete, externe,
benutzerbestätigte und policy-empfohlene Aussagen.

## Qualität, Präferenzen und Best Representation

Identität, Qualität, Präferenz und physische Operation bleiben vier getrennte
Entscheidungen. Eine `Best Representation` ist kein universeller
Dateiscore. Die Empfehlung soll aus folgenden Bausteinen entstehen:

1. harten Constraints und Blockern;
2. domänenspezifischen Qualitätsdimensionen;
3. expliziten Benutzerpräferenzen;
4. einer versionierten Policy;
5. Pareto-Vergleich oder nachvollziehbaren Tie-Breakern.

Dateigröße ist höchstens ein Tie-Breaker. Ein EPUB ist nicht für jeden Zweck
besser als ein PDF, und eine verlustfreie Audiodatei ist nicht in jeder
Storage-Rolle automatisch die bevorzugte Repräsentation.

`Library Health` soll ebenfalls mehrere unabhängige Dimensionen zeigen:
Integrität, Metadata Coverage, unresolved identities, Duplicate Candidates,
Completeness, Backup-/Fixity-Zustand und potenziellen Speichergewinn. Ein
Roll-up wäre höchstens eine benutzerdefinierte Projektion und darf die
Einzeldimensionen nicht verdecken.

## Inbox, Backup und Preservation

Ein späterer Inbox-Workflow analysiert neue Objekte zunächst gegen den
bestehenden `CollectionState`. Illustrative Ergebnisse wären hinzufügen,
beibehalten, ersetzen oder reviewen. Sie sind keine hier definierten
Runtime-Literale und bleiben nicht ausführbare Empfehlungen, bis ein eigener
Importvertrag und gegebenenfalls W10-Rechte existieren.

Backup-Vollständigkeit wird nicht aus Dateizahlen abgeleitet. Erforderlich
sind mindestens Inhaltsidentität, Root- beziehungsweise Replica-Rolle,
Snapshotfrische, Fixity und später tatsächliche Restore-Evidence. Ein
Backup-Werkzeug bleibt dabei Evidence Source und nicht die
FolioTone-Datenbank.

Acquisition Intelligence darf beantworten, ob ein vorgeschlagenes Objekt
bereits vorhanden oder wahrscheinlich redundant ist. Die Frage, was in einer
Sammlung fehlt, ist nur gegenüber einem ausdrücklich definierten Sollbestand
oder einer externen Katalog-Evidence zulässig; sie kann nicht aus dem
Istbestand allein abgeleitet werden. Erwerbsrechte, Lizenzen und
Nutzungsnachweise wären separate private Assertions.

## Empirische Confidence-Kalibrierung

Bestehende Confidence-Werte sind nicht nachträglich als Wahrscheinlichkeiten
zu interpretieren. Eine spätere Kalibrierung benötigt ausreichend
benutzergeprüfte, versionierte Ground-Truth-Fälle, getrennte Trainings- und
Evaluationsmengen sowie domänen- und relationstypbezogene Auswertung.
Benutzerpräferenzen sind dabei keine Ground Truth für bibliografische oder
inhaltliche Identität. Ohne diesen Nachweis bleiben Confidence-Werte
profilgebundene Entscheidungshilfen.

## Rolle von KI

KI kann später:

- natürliche Sprache in denselben validierten Query-AST übersetzen;
- vorhandene Evidence, Contradictions und Recommendations verständlich
  erklären;
- Review-Fälle priorisieren oder Forschungsfragen vorschlagen.

KI darf nicht:

- ungebundene Rohdaten als Wahrheit ausgeben;
- Identität oder Confidence ohne versionierten Vertrag erfinden;
- Tool- oder Provider-Allowlisten umgehen;
- allein eine Relation bestätigen oder eine Mutation autorisieren.

## Datenschutz- und Sicherheitsklassen

Eine spätere ADR soll Sensitivitätsklassen und erlaubte Flüsse definieren.
Mindestens zu unterscheiden sind öffentlich bibliografische Daten,
sammlungsprivate Metadaten, private Inhalte sowie hochsensitive Daten wie GPS,
Biometrie oder persönliche Dokumente. Die konkreten Literalwerte sind hier
absichtlich nicht festgelegt.

Lokale Parser und lokale Analyse-Tools arbeiten standardmäßig ohne Netzwerk,
mit festen Command Shapes und in isolierten begrenzten Workspaces.
Ein netzfähiger `ToolProvider` oder `Knowledge Provider` benötigt einen
eigenen ausdrücklichen Access-, Privacy- und Cache-Vertrag. Signaturprüfung,
Timeouts, Output-, Member-, Tiefen- und Dekompressionslimits gehören zum
jeweiligen Adaptervertrag. Raw Artifacts bleiben privat und versioniert; eine
allgemeine Retention-, Purge- und Backup-Policy benötigt ein eigenes
zukünftiges Gate.

## Nichtziele

Die Vision autorisiert nicht:

- Calibre oder einen anderen Toolkatalog als kanonische Datenbank;
- freie Command-Passthrough-APIs;
- eine sofortige Graphdatenbank, Suchserver- oder Microservice-Architektur;
- einen universellen Quality Score;
- Gesichtserkennung oder Cloud-Vision als Default;
- automatische Archive-Extraktion oder Source-Bereinigung während des Scans;
- Web-API, Desktop-UI, MCP oder Daemon vor stabilen Application-Verträgen;
- Source-Media-Mutationen vor einem eigenen W10-Gate.

## Erfolgskriterien

Die Richtung ist erfolgreich umgesetzt, wenn:

- ein Nutzer den aktuellen und historischen Sammlungszustand ohne private
  Pfadleaks verstehen kann;
- jede nichttriviale Aussage auf konkrete versionierte Evidence zurückführt;
- exakte Kopie, gleiche Edition, gleiches Work und bessere Repräsentation
  getrennt beantwortet werden;
- freie lokale Suche begrenzt, sicher und erklärbar funktioniert;
- Review und Benutzerpräferenzen erhalten bleiben, ohne Rohdaten zu
  überschreiben;
- ausgewählte Datensätze zwischen FolioTone-Systemen idempotent ausgetauscht
  und Konflikte ohne Verlust ihrer Ursprungsprovenance nachvollzogen werden
  können;
- neue Medien eine gemeinsame Infrastruktur nutzen, ohne ihre
  Identitätsmodelle zu verlieren;
- jeder mögliche Write-Schritt vor der Ausführung erneut validiert,
  auditierbar und entsprechend seiner Reversibilitätsklasse abgesichert ist.

## Offene Architekturfragen

Vor einer kanonischen Umsetzung benötigen insbesondere folgende Themen eigene
Frontier-Entscheidungen:

- Definition und Rebuild-Vertrag von `CollectionState`;
- Query-AST, lokale FTS-Projektion und Content-Index-Privacy;
- Preference-/Policy-Modell und Best-Representation-Erklärung;
- mögliche additive `Expression`-, `Representation`- und
  `Derivation`-Konzepte;
- portable Knoten-/Objektreferenzen, Austauschpaket, Clone-/Restore-Semantik,
  Trust und deterministische Konfliktbehandlung für mehrere FolioTone-Systeme;
- Hörbuch- und Comic-Identität;
- Bild-Sensitivität, Derivation und perceptual Matching;
- Replica-, Backup- und Restore-Evidence;
- spätere API-/UI-/MCP-Oberflächen;
- jede W10-Mutations- und Reversibilitätsklasse.

Die empfohlene Reihenfolge und die Zuordnung zu vorhandenen Plänen stehen in
`docs/planning/FUTURE_CAPABILITY_MAP.md`.
