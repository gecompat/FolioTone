# FolioTone und führende Spezialsysteme

**Status:** nichtkanonische strategische Analyse

**Stand:** 2026-08-26

**Geltungsgrenze:** Diese Datei ist keine Architekturentscheidung, keine
Implementierungsfreigabe und keine Änderung des kanonischen Backlogs.

## Fragestellung

Die fachlichen Ziele von FolioTone bleiben sinnvoll. Große heterogene
Sammlungen benötigen nachvollziehbare Aussagen über Bestand, Identität,
Qualität, Herkunft, Veränderungen, Redundanz und Integrität. Fraglich ist,
ob FolioTone dafür selbst das führende Fachsystem jeder Mediendomäne sein
sollte.

Für E-Books ist calibre ein umfassendes Bibliotheks-, Metadaten-,
Konvertierungs- und Bearbeitungssystem. Für Musik, Bilder und Dokumente
verteilen sich vergleichbare Aufgaben häufig auf mehrere Spezialanwendungen.
Ein eigenständiges FolioTone-Fachmodell kann deshalb Nutzen schaffen. Es kann
aber auch eine zweite konkurrierende Wahrheit, doppelte Bedienwege und
dauerhaften Integrationsaufwand erzeugen.

## Ausgangsbefund aus der calibre-Qualifikation

**Dokumentiert:** `GATE-0001` hat nicht gezeigt, dass calibre Serien nicht
verwalten oder bei einer Transformation nicht erhalten kann. Die erste
partielle OPF-Projektion ließ Serienfelder aus und konnte sie deshalb mit
`apply_null=True` entfernen. Mit einem vollständigen Metadatensnapshot blieben
Serienname, Serientyp und Position erhalten.

**Empirisch:** Das feste calibre-9.13.0-Profil scheiterte an FolioTones
Anforderung nach byteidentischer Wiederholung. calibre setzte bei den
getesteten Läufen aktuelle Werte für `dcterms:modified` und ZIP-Metadaten. Die
Outputs waren valide und fachlich verwendbar, aber nicht byteidentisch.

Dieser Befund ist kein allgemeiner calibre-Fehler. Er zeigt eine Differenz
zwischen calibres Produktverhalten und einem von FolioTone gesetzten
deterministischen Transformationsvertrag. `DEC-0002` Option A beantwortet die
Differenz technisch mit einer FolioTone-eigenen OPF-Normalisierung und
EPUB-Verpackung. Diese Lösung kann technisch funktionieren. Sie verschiebt
FolioTone jedoch weiter in die Rolle eines formatverantwortlichen Writers.

Ein positives `GATE-0002` würde die technische Eignung dieses Profils
belegen. Es würde nicht belegen, dass diese Verantwortung langfristig zu
FolioTones sinnvollster Produktrolle gehört. Technische Machbarkeit und
strategische Zweckmäßigkeit müssen getrennt bewertet werden.

## Grundproblem des gegenwärtigen Ansatzes

Die aktuelle Architektur behandelt externe Werkzeuge als austauschbare
`ToolProvider`. FolioTone übernimmt Provenance, fachliche Normalisierung,
kanonische Entscheidungen, Review, Planung und einzelne Writer. Dieser Ansatz
ist konsistent, solange FolioTone das führende Fachsystem sein soll.

Wenn dagegen calibre, beets, digiKam oder eine andere Spezialanwendung das
führende System ist, entstehen mehrere Konflikte:

- Dieselben Metadaten und Beziehungen werden in mehreren Datenbanken
  interpretiert und teilweise ausgewählt.
- Änderungen außerhalb von FolioTone erzeugen Drift und erfordern einen
  dauerhaften bidirektionalen Synchronisationsvertrag.
- FolioTone muss Fachlogik, Versionsänderungen und Sonderfälle der
  Spezialanwendungen nachvollziehen, obwohl diese Anwendungen die eigentliche
  Fachfunktion bereits besitzen.
- FolioTone-eigene Writer benötigen aufwendige Sicherheits-, Recovery- und
  Reconciliation-Ketten für Operationen, die ein Spezialsystem bereits als
  normalen Arbeitsablauf anbietet.
- Eine eigene domänenspezifische Oberfläche konkurriert mit ausgereiften
  Bedienoberflächen, ohne deren Funktionsbreite erreichen zu können.
- Die Austauschbarkeit eines `ToolProvider` ist begrenzt, wenn FolioTones
  Domainmodell und Abläufe faktisch an den Fähigkeiten eines konkreten
  Spezialprodukts ausgerichtet werden.

Der bisherige Aufbau ist deshalb nicht grundsätzlich falsch. Er ist für eine
andere Rollenannahme optimiert als die nun formulierte Zielrichtung.

## Führende Systeme nach Fähigkeit

Ein einziges führendes System pro Mediendomäne ist häufig keine tragfähige
Abstraktion. Die Führung sollte je Fähigkeit und Datenklasse betrachtet
werden.

| Bereich | Mögliche führende Spezialisten | Typische fachliche Führung |
|---|---|---|
| E-Books | calibre, EPUBCheck | Bibliothek, Metadatenpflege, Konvertierung, Editor beziehungsweise Formatvalidierung |
| Musik | beets, MusicBrainz Picard, MusicBrainz, FFmpeg, Chromaprint | Bibliotheksorganisation, Tagging, Authority-Daten, technische Analyse und Fingerprinting |
| Bilder und RAW | digiKam, darktable, Immich, ExifTool | Katalog und Metadaten, RAW-Entwicklung, Bereitstellung sowie Metadatenbearbeitung |
| Scans und Dokumente | Paperless-ngx und Formatwerkzeuge | Dokumentverwaltung, OCR, Volltext, Klassifikation und Versionen |
| Preservation und Backup | dafür spezialisierte Backup- und Fixity-Werkzeuge | Replikation, Aufbewahrung, Wiederherstellung und technische Integritätsprüfung |

Die Produkte besitzen unterschiedliche Autoritäten. darktable führt zum
Beispiel seine Bearbeitungshistorie in Datenbank und XMP-Sidecars. digiKam kann
standardisierte XMP-Sidecars einlesen und schreiben. Immich unterstützt nur
einen Teil der XMP-Felder und behandelt externe Bibliotheken abhängig von der
Mount- und Sidecar-Konfiguration anders. Die Annahme einer einheitlichen
Bilddomänen-Wahrheit würde diese Unterschiede verdecken.

**Empfehlung:** Eine spätere Architektur sollte Autorität explizit je
Fähigkeit, Datenklasse und Installation beschreiben. Autorität darf weder aus
dem Medientyp noch aus der bloßen Verfügbarkeit eines Adapters abgeleitet
werden.

## Mögliche Zukunftsmodelle

### Modell 1: FolioTone als führendes kanonisches Fachsystem

FolioTone behält sein umfassendes Domainmodell, trifft kanonische
Entscheidungen und führt zunehmend eigene Writer aus. Spezialwerkzeuge liefern
Evidence oder technische Teilfunktionen.

Dieses Modell ermöglicht ein stark einheitliches medienübergreifendes Modell.
Es verursacht zugleich hohe Implementierungs- und Wartungskosten. Es erzeugt
bei parallel genutzten Spezialbibliotheken ein dauerhaftes Dual-Master-Problem.
Es entspricht nicht der neuen Ausgangsthese.

### Modell 2: FolioTone als föderierte unterstützende Schicht

Spezialsysteme bleiben innerhalb ihrer erklärten Fähigkeiten führend.
FolioTone beobachtet ihre Zustände über dokumentierte Schnittstellen, verbindet
Referenzen, bewahrt Provenance und Historie, erkennt Widersprüche und erzeugt
systemübergreifende Zustands- und Entscheidungssichten.

FolioTone besitzt weiterhin eine Datenbank. Diese Datenbank ist jedoch das
führende System nur für FolioTone-eigene Tatsachen: erfasste Beobachtungen,
Provenance, Abgleichsbeziehungen, Snapshot-Historie, Reviewentscheidungen,
Prüfergebnisse und Auditnachweise. Sie ist keine zweite operative
Calibre-, Musik-, Bild- oder Dokumentbibliothek.

Dieses Modell erhält den medienübergreifenden Nutzen, reduziert aber
fachliche Doppelentwicklung. Es benötigt präzise Adapter- und
Autoritätsverträge. Es ist das derzeit plausibelste Zukunftsbild.

### Modell 3: FolioTone als Sammlung einzelner Plugins

FolioTone wird auf Erweiterungen innerhalb der jeweiligen Spezialsysteme
reduziert. Ein calibre-Plugin, ein beets-Plugin und weitere Erweiterungen
arbeiten weitgehend unabhängig.

Dieses Modell integriert sich eng in vorhandene Bedienabläufe und minimiert
eine konkurrierende Oberfläche. Es verliert jedoch einen großen Teil des
medienübergreifenden Zustands, der gemeinsamen Provenance und der unabhängigen
Integritäts- und Verlaufssicht. Plugins sind ein sinnvoller Integrationsweg,
aber kein ausreichendes Gesamtmodell für die ursprünglichen FolioTone-Ziele.

### Modell 4: Greenfield-Neuentwurf

Ein Greenfield-Neuentwurf beginnt nicht mit dem aktuellen Domainmodell,
sondern mit den führenden Spezialsystemen, ihren Schnittstellen und den
verbleibenden systemübergreifenden Nutzerfragen. Nur dafür notwendige
FolioTone-Konzepte werden neu eingeführt.

Dieser Weg kann wesentlich kleiner und klarer werden. Er kann aber auch
bereits gelöste Probleme erneut erzeugen und belastbare Bestandteile
verwerfen. Ein Greenfield-Neuentwurf ist gerechtfertigt, wenn sich die
Annahmen eines kanonischen FolioTone-Fachsystems nicht ohne grundlegende
Komplexität aus dem bestehenden Kern entfernen lassen.

## Bewertung der Modelle

| Kriterium | Kanonisches Fachsystem | Föderierte Schicht | Plugin-Sammlung | Greenfield föderiert |
|---|---:|---:|---:|---:|
| Nutzung bestehender Spezialsysteme | mittel | hoch | sehr hoch | hoch |
| Medienübergreifender Nutzen | hoch | hoch | niedrig | hoch |
| Gefahr konkurrierender Wahrheiten | hoch | niedrig bis mittel | niedrig | niedrig bis mittel |
| Eigene Fachlogik und Writer | sehr hoch | begrenzt | niedrig | begrenzt |
| Integrationsaufwand | hoch | hoch | mittel | zunächst hoch |
| Erhalt bestehender FolioTone-Arbeit | hoch | mittel bis hoch | niedrig | offen |
| Langfristige Wartungsbreite | sehr hoch | mittel | verteilt | mittel |

Die Matrix ist eine qualitative Empfehlung und keine Messung. Sie zeigt, dass
ein Greenfield-Neuentwurf und eine evolutionäre Neuausrichtung dasselbe
föderierte Zielbild verfolgen können. Die Entscheidung zwischen beiden Wegen
sollte erst nach begrenzten Prototypen fallen.

## Vorgeschlagenes Zukunftsbild

FolioTone beobachtet und verbindet führende Spezialsysteme. Es bewahrt
Herkunft und zeitlichen Verlauf ihrer Aussagen, erkennt systemübergreifende
Widersprüche und Lücken und unterstützt nachvollziehbare Entscheidungen. Es
übernimmt keine fachliche Hauptfunktion, die ein geeignetes Spezialsystem
bereits zuverlässig besitzt.

Der logische Ablauf lautet:

```text
Dateien, Bibliotheken, Sidecars, Backups und Spezialdienste
                           |
                           v
              versionierte Beobachtungen
                           |
                           v
           Provenance und systemübergreifende Links
                           |
                           v
       Bestand, Verlauf, Integrität, Drift und Konflikte
                           |
                           v
        Empfehlungen, Übergaben und spätere Verifikation
```

FolioTone führt in diesem Bild nur dort, wo die Aufgabe ihrem Wesen nach
systemübergreifend ist:

- Vergleich mehrerer Bibliotheken, Dateibestände und Backups;
- Nachweis, woher eine Aussage oder Änderung stammt;
- Historie und Diff eines heterogenen Sammlungszustands;
- Fixity, Coverage und erkennbare Integritätslücken über Systemgrenzen;
- Verbindung externer Objektidentitäten ohne deren Umdeutung;
- Erkennung von Drift, Konflikten und veralteten Projektionen;
- nachvollziehbare Review- und Entscheidungsverläufe;
- Verifikation, ob eine an ein Spezialsystem übergebene Änderung das
  erwartete Ergebnis hatte.

Die spezialisierten Systeme führen ihre eigenen Bibliotheks-, Tagging-,
Bearbeitungs-, Konvertierungs- und Organisationsabläufe. Ob FolioTone eine
Änderung nur vorschlägt, als Übergabepaket bereitstellt, über eine offizielle
Schnittstelle auslöst oder in einer nachgewiesenen Lücke selbst ausführt,
bleibt eine spätere Entscheidung je Fähigkeit. Direkte FolioTone-Writer wären
in diesem Zukunftsbild begründungsbedürftige Ausnahmen und keine normale
Fortsetzung jeder Analysefunktion.

## Einordnung der bestehenden Implementierung

### Wahrscheinlich wiederverwendbar

- inkrementelle Dateibeobachtung und versionierte `FileObservation`;
- Hashing, Fixity, `CollectionState`, Zustandsdifferenzen und `Library Health`;
- Provenance-, Evidence- und `ToolExecution`-Verträge;
- begrenzte, versionierte Adapterausführung und Datenschutzgrenzen;
- read-only Reconciliation externer Bibliotheken;
- Review-, Audit- und Reverification-Konzepte;
- Privacy-, Fencing- und changed-since-analysis-Grundsätze;
- synthetische Testkorpora und reproduzierbare Integrationsprüfungen.

Diese Bestandteile beantworten systemübergreifende Fragen und sind nicht an
FolioTone als führendes Fachsystem gebunden.

### Grundsätzlich neu zu bewerten

- FolioTone-eigene Auswahl kanonischer Fachmetadaten neben dem führenden
  Spezialsystem;
- Domainmodelle, die eine vollständige zweite Bibliothekssemantik abbilden;
- eigene Formattransformation und EPUB-Verpackung als dauerhafte
  Produktverantwortung;
- Writer für Metadaten, Rename, Reorganisation oder Bibliotheksänderungen,
  die ein Spezialsystem bereits fachlich beherrscht;
- eine universelle Bedienoberfläche für Aufgaben, die in den
  Spezialanwendungen besser bedienbar sind;
- Integrationen, die private interne Datenbankschemata statt stabiler
  dokumentierter Schnittstellen voraussetzen;
- die Annahme, ein `ToolProvider` sei austauschbar, obwohl FolioTones Ablauf
  seine konkrete Semantik benötigt.

Die vorhandenen W10-Verträge sind nicht wertlos. Ihre Sicherheits- und
Verifikationsprinzipien können für systemübergreifende Übergaben und
Ausnahmen weiterverwendet werden. Ihr Umfang ist jedoch kein Argument dafür,
dass FolioTone die jeweilige Fachoperation selbst besitzen sollte.

## Kriterien für Evolution oder Greenfield

Eine evolutionäre Neuausrichtung ist vorzuziehen, wenn die
systemübergreifenden Bestandteile aus dem aktuellen Kern gelöst werden können,
ohne das bestehende kanonische Fach- und Writer-Modell weiterzuführen. Dabei
bleibt die belegte Funktion erhalten und die Produktrolle ändert sich.

Ein Greenfield-Neuentwurf ist vorzuziehen, wenn mindestens einer der folgenden
Befunde durch einen Prototyp bestätigt wird:

- Der bestehende Kern setzt an vielen Schichtgrenzen eine FolioTone-kanonische
  Fachwahrheit voraus.
- Adapter können ohne umfangreiche interne Projektionen keine nützlichen
  systemübergreifenden Aussagen liefern.
- Das Entfernen eigener Writer und Speziallogik ist komplexer als ein kleiner
  neuer Beobachtungs- und Reconciliation-Kern.
- Die heutige Oberfläche und Persistenz können die unterstützende Rolle nur
  durch dauerhafte Kompatibilitätsschichten abbilden.
- Ein kleiner Greenfield-Prototyp beantwortet dieselben Nutzerfragen mit
  wesentlich weniger eigener Fachlogik und weniger synchronisiertem Zustand.

Der vorhandene Codeumfang ist bei dieser Entscheidung weder positiver noch
negativer Selbstzweck. Maßgeblich sind künftiger Nutzen, Verständlichkeit,
Wartungsbreite und Konfliktrisiko.

## Erkenntnisexperimente vor einer Architekturentscheidung

### 1. calibre als führendes E-Book-System

Ein read-only Prototyp verwendet ausschließlich dokumentierte calibre-
Schnittstellen und erstellt eine kleine FolioTone-Sicht auf Bestand, Drift,
Fixity und externe Referenzen. Er trifft keine eigene Metadatenauswahl und
führt keinen Writer aus. Geprüft wird, welche eigenständigen Nutzerfragen
danach noch sinnvoll beantwortet werden.

### 2. Gegenprobe mit Musik und Bildern

Je ein kleiner Musik- und Bildfall prüft, ob das Modell mehr als eine
calibre-spezifische Lösung ist. Die Gegenprobe muss mehrere Spezialisten mit
unterschiedlichen Autoritäten berücksichtigen, beispielsweise beets und
Picard beziehungsweise digiKam, darktable und Immich.

### 3. Konflikt- und Round-trip-Probe

Ein synthetischer Fall ändert denselben Wert in zwei Systemen. Geprüft wird,
ob FolioTone den Konflikt erkennen, erklären und nach einer fachlichen
Entscheidung verifizieren kann, ohne still eine neue Wahrheit zu erfinden.

### 4. Evolution gegen Greenfield

Die gleiche kleine Nutzerfrage wird einmal durch Extraktion aus dem
bestehenden Kern und einmal durch einen minimalen Greenfield-Prototyp
beantwortet. Verglichen werden eigener Zustand, notwendige Fachlogik,
Abhängigkeit von instabilen Schnittstellen, Testaufwand und erkennbare
Dual-Master-Risiken.

Diese Experimente entscheiden noch kein Schreibmodell. Sie liefern die
Evidence für die spätere Entscheidung.

## Offene Fragen

- Welche konkreten Alltagsfragen soll FolioTone beantworten, die das führende
  Spezialsystem nicht beantwortet?
- Welche Autorität besitzt ein Spezialsystem je Datenklasse und Fähigkeit?
- Welche FolioTone-Daten sind eigene dauerhafte Tatsachen und welche nur
  rebuildbare Projektionen fremder Zustände?
- Muss FolioTone eine medienübergreifende stabile Objektidentität besitzen,
  oder reichen versionierte Links zwischen externen Identitäten?
- Welche dokumentierten Schnittstellen sind stabil genug für eine dauerhafte
  Integration?
- Wann genügt eine Empfehlung oder ein Übergabepaket, und wann entsteht ein
  begründeter eigener Ausführungspfad?
- Welche bestehende Funktion liefert nach der Rollenänderung noch messbaren
  Nutzerwert?
- Welche Funktionen sollten bis zur Grundsatzentscheidung nicht weiter
  ausgebaut werden?

## Gesamteinschätzung

Die groben Ziele von FolioTone bleiben tragfähig. Die Evidence-, Provenance-,
Verlaufs-, Integritäts- und Reconciliation-Idee besitzt eigenständigen Wert.
Der gegenwärtige Aufbau geht jedoch in Teilen zu weit in Richtung eines
zweiten führenden Fachsystems und eigener spezialisierter Writer.

Das sauberste Zukunftsbild ist derzeit eine föderierte unterstützende Schicht
um führende Spezialsysteme. FolioTone wäre nicht das bessere calibre, beets,
digiKam, darktable, Immich oder Paperless-ngx. FolioTone würde sichtbar
machen, wie deren Zustände zusammenhängen, wo sie sich widersprechen, was sich
verändert hat und ob eine Entscheidung oder Änderung nachvollziehbar und
verifiziert ist.

Ob dieses Ziel durch eine starke Reduktion des bestehenden Systems oder durch
einen Greenfield-Neuentwurf erreicht wird, ist offen. Diese Entscheidung
sollte nicht aus dem bisherigen Aufwand, sondern aus den beschriebenen
Erkenntnisexperimenten abgeleitet werden.

## Geprüfte Primärquellen

Die folgenden veränderlichen externen Aussagen wurden am 2026-08-26 anhand
offizieller Dokumentation eingeordnet:

- [calibre: `calibredb`](https://manual.calibre-ebook.com/generated/en/calibredb.html)
- [calibre: `ebook-polish`](https://manual.calibre-ebook.com/generated/en/ebook-polish.html)
- [beets: Einstieg und Bibliotheksmodi](https://docs.beets.io/en/latest/guides/main.html)
- [beets: Plugins](https://docs.beets.io/en/latest/plugins/index.html)
- [MusicBrainz Picard: Scripting](https://picard-docs.musicbrainz.org/en/latest/config/options_scripting.html)
- [digiKam: Datenbank und XMP-Interoperabilität](https://docs.digikam.org/en/getting_started/database_intro.html)
- [darktable: Sidecar-Dateien und Datenbankautorität](https://docs.darktable.org/usermanual/development/en/overview/sidecar-files/sidecar/)
- [Immich: XMP-Sidecars](https://docs.immich.app/features/xmp-sidecars/)
- [Immich: externe Bibliotheken](https://docs.immich.app/features/libraries/)
- [Paperless-ngx: REST API](https://docs.paperless-ngx.com/api/)

Repositoryinterne Grundlage sind insbesondere `GATE-0001`, `DEC-0002`,
`ADR-0010`, die aktuelle Produktvision, die `Future Capability Map` und die
implementierten Reconciliation-, `CollectionState`-, Fixity- und W10-Verträge
auf `origin/main` `6b8aaf9`.
