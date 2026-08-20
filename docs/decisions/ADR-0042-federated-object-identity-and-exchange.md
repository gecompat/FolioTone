# ADR-0042: Portable Objektidentität und föderierter Austausch

- Status: Proposed
- Datum: 2026-08-20

## Kontext

FolioTone verwaltet bereits opake UUID-basierte interne IDs, getrennte
`FileRecord`- und Domain-Identitäten, Provenance, Relocation Candidates,
append-only Review-Entscheidungen und read-only Calibre-Reconciliation. Diese
Verträge reichen für eine einzelne FolioTone-Persistenz aus. Sie definieren
jedoch noch nicht, wie ein Objekt nach einem Export, einer externen Kopie, der
Übernahme in eine spezialisierte Bibliothek oder dem Austausch zwischen zwei
FolioTone-Systemen wiedererkannt wird.

Pfad, Dateiname und aktueller Datei-Hash sind dafür ungeeignet. Ein Pfad kann
sich ändern. Identische Bytes können mehrere absichtlich getrennte Kopien
darstellen. Eine reine Metadatenkorrektur kann die Bytes verändern, obwohl die
fachliche Repräsentation fortbesteht. Externe Identifier wie ISBN oder
MusicBrainz-ID bezeichnen außerdem eine fachliche Ebene und nicht automatisch
eine konkrete Datei oder FolioTone-Lineage.

Ein in EPUB, Audio, Bild, PDF oder einer externen Bibliothek gespeichertes Tag
kann den Wiedererkennungsprozess unterstützen. Es ist jedoch veränderbar,
kopierbar, entfernbar oder fälschbar und darf deshalb weder alleinige
Identität noch Merge-Autorität sein. Dasselbe Problem gilt für Sidecars und
externe Custom Fields.

Mehrere FolioTone-Systeme können unabhängig dasselbe Medium erfassen,
FolioTone-Daten exportieren, replizieren oder später fusionieren. Ohne einen
expliziten Föderationsvertrag könnten dabei lokale IDs kollidieren,
unterschiedliche Objekte irrtümlich zusammenfallen, dieselbe Änderung mehrfach
importiert, Provenance verloren oder konkurrierende Entscheidungen durch einen
pauschalen Last-write-wins-Mechanismus überschrieben werden.

## Vorgeschlagene Richtung

FolioTone soll vor einem portablen Export-, Import- oder Sync-Workflow einen
medienübergreifenden Vertrag für portable Objektverweise und föderierten
Austausch erhalten. Dieser Vertrag ergänzt die vorhandenen internen IDs und
Domainmodelle; er ersetzt weder `FileRecord`, `Work`, `Edition`, `MusicWork`,
`Recording`, `Release` noch deren Matching- und Review-Verträge.

Die Richtung besitzt fünf getrennte Ebenen:

1. lokale Persistenzidentität eines konkreten FolioTone-Datensatzes;
2. portable, namespaced Referenz auf die von einem FolioTone-System erzeugte
   Datensatz-Lineage;
3. physische Datei- oder Repräsentationsidentität mit versionierter
   Fingerprint- und Derivation-Evidence;
4. fachliche Identität auf der jeweiligen Domain-Ebene;
5. Austausch-, Import- und Merge-Provenance zwischen FolioTone-Systemen.

Gleiche portable Referenz bedeutet zunächst nur, dass zwei Datensätze dieselbe
exportierte Lineage behaupten. Sie beweist weder gleiche Bytes noch dieselbe
fachliche Entität. Verschiedene portable Referenzen können durch Matching und
Review später als zusammengehörig erkannt werden, bleiben bis dahin jedoch
getrennt.

## System- und Objektverweise

Der spätere Vertrag benötigt eine dauerhafte, opake Identität für den
ausstellenden FolioTone-Knoten sowie eine portable Objekt- oder Record-Referenz.
Die konkrete URI-/URN-Syntax, UUID-Version und Persistenzform wird erst im
Frontier-Gate akzeptiert. Der Vertrag muss mindestens folgende Eigenschaften
erzwingen:

- globale Kollisionsresistenz ohne zentrale Registry;
- expliziten ausstellenden Knoten beziehungsweise Namespace;
- Entitäts- oder Record-Art, damit eine Datei nicht mit einem `Work` oder einer
  `Edition` verwechselt wird;
- stabile Lineage über Export, Import und erneuten Export;
- definierte Clone-, Restore-, Backup- und Knoten-Neuanlage-Semantik;
- keine Abhängigkeit von Hostname, Benutzername, absolutem Pfad oder
  Netzwerkerreichbarkeit.

Eine aus einem Backup geklonte Runtime darf nicht stillschweigend zwei aktive
Schreibknoten mit derselben Knotenidentität erzeugen. Ob ein Restore dieselbe
Knoten-Lineage fortsetzt oder eine neue Knotenidentität mit einem
`derived_from`-Bezug erhält, muss als expliziter administrativer Vorgang
festgelegt werden.

## Portable Kennzeichnung

Die FolioTone-Persistenz und ein versioniertes Austauschpaket bleiben die
maßgeblichen Träger des Zuordnungsvertrags. Eine eingebettete Kennzeichnung oder
ein Sidecar ist redundante Transport-Evidence und Wiedererkennungshilfe.

Ein späteres Kennzeichnungsprofil muss mindestens portable Referenz,
Profilversion, ausstellenden Knoten und einen Bindungsfingerprint enthalten. Es
darf keine privaten absoluten Pfade, Klartext-Secrets, vollständigen
Sammlungsinventare oder ungeprüfte kanonische Metadaten transportieren.

Formatadapter dürfen die Kennzeichnung nur über dokumentierte Namespaces oder
Felder lesen. Beispiele für später zu prüfende Träger sind OPF-Metadaten, XMP,
benutzerdefinierte Audiofelder, externe Bibliotheksfelder und Sidecars. Diese
Beispiele akzeptieren noch kein Feldschema und keine Write-Schnittstelle.

Das Lesen und Validieren vorhandener Kennzeichnungen kann in einem eigenen
read-only Gate vor W10 erfolgen. Das erstmalige Einbetten, Aktualisieren oder
Entfernen einer Kennzeichnung in Source Media sowie das Setzen eines
Calibre-/beets-/anderen Toolfeldes ist eine Mutation und bleibt W10-blockiert.

## Austauschpaket und Import

Ein Austauschpaket muss versioniert, begrenzt, offline prüfbar und
idempotent importierbar sein. Es soll nur explizit ausgewählte Datensätze und
ihre erforderliche Lineage enthalten. Mindestens zu binden sind:

- Paketprofil, Export-ID und ausstellender Knoten;
- Objekt-/Record-Referenzen und deren Typen;
- unveränderliche Observation-, Assertion-, Evidence-, Review- oder
  Relation-Snapshots mit ihren vorhandenen Profilversionen;
- Ursprungs- und Exportprovenance;
- Abhängigkeiten und Elternbezüge in kanonischer Reihenfolge;
- materielle Content-Digests für Paket und Einträge;
- feste Größen-, Mengen-, Tiefen- und Referenzgrenzen.

Der Import schreibt keine Source Media und aktiviert keine externe
Toolmutation. Unbekannte Profile, fehlende Abhängigkeiten, ungültige Digests,
doppelte widersprüchliche Einträge, Zyklen außerhalb einer ausdrücklich
erlaubten Relationsform oder Grenzüberschreitungen schlagen geschlossen fehl.
Ein identischer erneuter Import darf keine zweite fachlich wirksame Änderung
erzeugen.

Signatur, Verschlüsselung, Transport und Knotenvertrauen sind getrennte
Verträge. Ein valider Digest beweist Integrität gegen die Paketbytes, aber
nicht die Vertrauenswürdigkeit des Ausstellers. Netzwerk-Synchronisation wird
durch dieses Proposal nicht vorausgesetzt; ein lokaler Datei- oder
Datenträgeraustausch muss vollständig funktionieren können.

## Merge- und Konfliktgrenze

Föderierter Import ist kein Datenbank-Merge und keine automatische Auswahl
einer kanonischen Wahrheit. Importierte Beobachtungen, Assertions und
Entscheidungen behalten ihren Ursprung. Eine fremde `USER_CONFIRMED`-
Entscheidung wird ohne eine explizite lokale Trust- und Decision-Compatibility-
Policy nicht zu einer lokalen Bestätigung.

Der spätere Merge-Vertrag muss mindestens unterscheiden:

- Wiederholung desselben bereits importierten Snapshots;
- neue kompatible Revision derselben exportierten Lineage;
- konkurrierende Änderungen derselben Lineage;
- unabhängig erzeugte Referenzen mit möglicher gleicher Datei- oder
  Domain-Identität;
- Kopie, Repräsentation, Derivation und tatsächliche fachliche Identität;
- lokale und importierte Review- oder Canonical-Entscheidungen.

Wall-Clock-Zeit oder „zuletzt geschrieben“ darf keinen materiellen Konflikt
allein entscheiden. Konflikte bleiben als getrennte Evidence oder Review-Fälle
erhalten. Ein automatischer Merge ist nur für exakt idempotente oder durch eine
später akzeptierte, versionierte und deterministische Compatibility-Regel
belegte Fälle zulässig. Ein vollständiges Event-Sourcing- oder CRDT-Modell wird
durch dieses Proposal nicht vorentschieden.

## Kein universelles Asset-God-Object

Die portable Referenzschicht ist ein Austausch- und Lineage-Vertrag. Sie führt
nicht vorzeitig einen universellen fachlichen `Asset`-Typ ein. Die fachlichen
Identitätsebenen bleiben domänenspezifisch. Erfahrungen aus E-Books, Musik und
einer dritten unabhängigen Domäne bestimmen weiterhin, welche
Representation-, Derivation- oder Replica-Konzepte tatsächlich gemeinsam
stabil sind.

## Sicherheits- und Datenschutzgrenze

Vor einem akzeptierten Implementierungsgate sind mindestens folgende Risiken
zu entscheiden und synthetisch zu prüfen:

- gefälschte oder kopierte eingebettete Kennzeichnungen;
- Knoten-ID-Klon nach Backup oder Runtime-Kopie;
- Paket-Replay, widersprüchliche Duplikate und Reference Substitution;
- Package Bombs, übertiefe Graphen und unbeschränkte Transitivität;
- private Pfade, Metadatenwerte oder Inhalte in Exporten und Fehlerausgaben;
- Downgrade auf ältere Profil- oder Decision-Compatibility-Versionen;
- Vertrauen, Widerruf, Signatur und optionaler verschlüsselter Transport;
- Löschung, Tombstones und deren Bedeutung bei partiellen Exporten.

Der Default bleibt local-first und offline. Exporte sind explizit, scope-
begrenzt und privacy-geprüft. Ein Import darf keine Source-Pfade anlegen,
Dateien verschieben, Metadaten schreiben oder externe Bibliotheken verändern.

## Planungsfolge

Die vorgeschlagene Umsetzung wird nicht in einem Paket vorgezogen. Vor Code
sind mindestens folgende Gates erforderlich:

1. `FG-FED-IDENTITY`: Entitätsgrenze, Knoten-/Objektreferenz, Clone-/Restore-
   Semantik und synthetischer Kollisionskorpus;
2. `FG-FED-BUNDLE`: kanonisches bounded Austauschformat, Content-Digests,
   Referenzintegrität, Privacy und idempotenter read-only Import;
3. `FG-FED-MERGE`: Revision-, Conflict-, Trust- und
   Decision-Compatibility-Regeln ohne pauschales Last-write-wins;
4. `FG-FED-CARRIER`: read-only Erkennung format- und toolbezogener
   Kennzeichnungsträger sowie Sidecar-Fallback;
5. ein getrenntes W10-Gate für jedes Schreiben einer Kennzeichnung oder
   synchronisierte Änderung in Source Media beziehungsweise externen
   Bibliotheken.

Die ersten vier Gates dürfen ausschließlich FolioTone-Persistenz,
synthetische Pakete und unveränderte Fixtures verwenden. Reale
Sammlungsfusionen und Live-Synchronisation sind keine CI-Gates.

## Konsequenzen

- Externe Verschiebungen und Bibliothekskopien können später über mehrere
  Evidence-Arten wiedererkannt werden, ohne einen Pfad oder Hash zur alleinigen
  Identität zu erklären.
- Zwei FolioTone-Systeme erhalten eine definierte Grundlage für Austausch und
  Fusion, ohne ihre lokalen Entscheidungen stillschweigend zu überschreiben.
- Calibre, beets und andere Spezialbibliotheken bleiben Adapter und keine
  FolioTone-Identitätsautorität.
- Die bestehende read-only E-Book-, Archive- und W10-Planungsfolge wird nicht
  umgeordnet.
- Zusätzliche Persistenz-, Export-, Import-, Trust- und Review-Verträge sind
  erforderlich, bevor eine Implementierung begonnen werden darf.

## Nicht autorisiert

Dieses Proposal autorisiert nicht:

- neue öffentliche Runtime-Literale oder Datenbanktabellen;
- das Einbetten oder Ändern von Tags, XMP, OPF, Audiofeldern oder Sidecars;
- Calibre-, beets-, Picard- oder andere externe Library-Writes;
- automatisches Zusammenführen gleicher Hashes oder ähnlicher Metadaten;
- Netzwerk-Synchronisation, Daemon, API, MCP oder neue UI;
- Source-Media-Mutation oder eine W10-Ausführung.
