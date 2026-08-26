# DEC-0002: Deterministische EPUB-Transformation in einen getrennten Output-Root

- Status: Accepted
- Datum: 2026-08-26
- Artefakt: `urn:uuid:01a037f5-a7ed-7ca5-9663-152268a2b2b9`
- negatives Charakterisierungsgate: `GATE-0001`
- positives Folgegate: `GATE-0002`
- geplante Umsetzung: `WI-0004`

## Kontext

ADR-0065 und W9-007 liefern bereits immutable, content-addressed und dauerhaft
`NOT_EXECUTABLE` bleibende Rezepte für `FORMAT_TRANSFORM`. Sie entscheiden
weder einen konkreten ToolProvider noch eine W10-Capability, einen ausführbaren
Befehl oder die Veröffentlichung erzeugter Dateien.

Für eine ausführbare Transformation sind Reproduzierbarkeit, Metadatenumfang,
Tool- und Containeridentität, Output-Root, Collision Handling, Fencing,
Verifikation und Recovery gemeinsam zu entscheiden. Ein vorhandener
read-only calibre-Adapter oder der EPUB-Titelwriter darf nicht stillschweigend
zum allgemeinen Transformationsbackend erweitert werden.

## Akzeptierter Produktvertrag

Version 1 verarbeitet genau eine EPUB-3-Primärquelle und erzeugt eine neue
normalisierte EPUB-3-Ableitung. Die Quelle bleibt bytegleich. Das Ziel liegt in
einem getrennten, verwalteten E-Book-Output-`ScanRoot`; derselbe Source-Slot,
ein Source-Replacement und ein bereits vorhandenes Ziel sind unzulässig.

Die Ableitung darf ausschließlich Metadatenwerte einbetten, deren Auswahl
durch aktuelle kompatible Review-Evidence als `CANONICAL` oder
`USER_CONFIRMED` gebunden ist. Der Transformationsvertrag benötigt dafür einen
eigenen immutable Metadaten-Snapshot. Nicht ausgewählte Felder, normalisierter
Text, Lesereihenfolge und Cover-Evidence müssen im festgelegten
Äquivalenzprofil erhalten bleiben. Ein Tool-Exitcode allein ist kein
Erfolgsnachweis.

Dry Run und Replay müssen bei identischem Input, Toolchain-Image,
Tool-/Adapterversion und Konfigurationsfingerprint exakt dieselbe Bytelänge und
denselben vollständigen SHA-256 erzeugen. Diese Byte-Reproduzierbarkeit ist
eine harte Voraussetzung des vorhandenen W9-Outputvertrags und wird nicht auf
eine ungefähre semantische Gleichheit abgeschwächt.

## GATE-0001

`GATE-0001` qualifiziert vor jeder Writerimplementierung genau ein festes
Transformationsprofil mit ausschließlich synthetischen EPUB-Fixtures. calibre
9.13.0 aus dem gelockten E-Book-Toolchain-Image ist der erste Kandidat, aber
nicht vorab akzeptiert. Das Gate prüft mindestens:

- wiederholte byteidentische Ergebnisse in getrennten frischen, netzlosen
  Containerläufen;
- feste Command Shape ohne freie Optionen, Shell oder Host-Environment;
- Input-/Output-, Zeit-, Locale-, Image-, Tool-, Adapter- und
  Konfigurationsbindung;
- aktuelle offizielle Maintenance-, Automations-, Lizenz- und
  Security-Bedingungen;
- Ressourcenlimits, private Workspace-Grenze und bösartige EPUB-Fixtures;
- EPUBCheck-, Metadaten-, Text-, Lesereihenfolge-, Cover- und
  Preserved-Field-Verifikation.

Scheitert die exakte Reproduzierbarkeit, bleibt `WI-0004` blockiert. Dann
benötigt eine FolioTone-eigene kanonische
EPUB-Verpackungsstufe oder ein anderer ToolProvider eine neue dokumentierte
Bewertung; das Gate wählt keine unbewiesene Alternative.

## Ergebnis von GATE-0001

`GATE-0001` wurde am 2026-08-25 mit calibre 9.13.0 und dem festen
`ebook-polish --opf`-Profil abgeschlossen. Zwei frische, netzlose und zeitlich
getrennte Containerläufe erzeugten unterschiedliche Bytelängen und SHA-256.
calibre setzte jeweils die reale UTC-Zeit in `dcterms:modified` und in
ZIP-Zeitstempel. Die vollständige OPF-Projektion erhielt Serienname, -typ und
-position in beiden Outputs; eine partielle Projektion wäre wegen der
`apply_null=True`-Semantik keine zulässige Preserve-/Patch-Schnittstelle.
Beide Outputs waren EPUBCheck-konform, was die fehlende Bytegleichheit nicht
aufhebt. Der vollständige Nachweis steht in
[`GATE_0001_EPUB_TRANSFORM_QUALIFICATION.md`](../quality/GATE_0001_EPUB_TRANSFORM_QUALIFICATION.md).

`WI-0004` bleibt deshalb `BLOCKED`. `GATE-0001` hat keine der möglichen
Folgerichtungen freigegeben.

## Entscheidung für Option A

Der Projekteigentümer hat am 2026-08-26 Option A ausdrücklich freigegeben.
calibre 9.13.0 bleibt die fest profilierte Transformationsstufe und erhält
immer einen vollständigen, immutable gebundenen Transformations-
Metadaten-Snapshot. Dieser trennt reviewte neue oder ersetzte Werte im Zustand
`CANONICAL` oder `USER_CONFIRMED` von unverändert zu erhaltenden Source-Werten
mit ihrer `OBSERVED`-/`EXTERNAL`-Provenance und Preserve-Obligation. Eine
partielle OPF-Projektion ist wegen der belegten `apply_null=True`-Semantik
unzulässig. Unbekannte oder nicht verlustfrei repräsentierbare Felder
blockieren. Der von calibre erzeugte Output wird anschließend ausschließlich
im privaten Transformations-Workspace durch eine FolioTone-eigene kanonische
OPF-Normalisierung und EPUB-Verpackung verarbeitet.

Die kanonische Stufe ist keine zweite Metadatenauswahl. Ihre technische
Metadaten-Delta-Allowlist enthält genau `dcterms:modified`; dessen Wert wird
vor dem Toollauf immutable im Snapshot gebunden und nie aus der realen
Laufzeit erzeugt. Alle weiteren Metadatenänderungen müssen reviewte
Snapshotwerte sein, alle übrigen OPF-Werte und Payload-Inhalte müssen erhalten
bleiben. Die Stufe darf nur diese Bindungen und das in `GATE-0002` gelockte
Serialisierungs- und Verpackungsprofil abbilden.
Zeitwerte, XML-Serialisierung, Entry-Reihenfolge, Kompression, ZIP-Header,
Flags, Attribute, Extra Fields und Kommentare dürfen weder von realer Laufzeit
noch Hostzustand oder freier Toolkonfiguration abhängen. Dasselbe Eingangs-EPUB,
derselbe Snapshot und dieselbe vollständige Profilidentität müssen bei Dry Run,
frischem Replay und idempotenter erneuter Normalisierung exakt dieselbe
Bytelänge und denselben vollständigen SHA-256 erzeugen.

calibres Zwischenoutput bleibt untrusted `ToolProvider`-Output. Die native
Stufe muss ihn erneut bounded, no-follow und ohne naive Extraktion prüfen.
FolioTone übernimmt oder importiert keine GPL-calibre-Interna; calibre bleibt
ein getrennt aufgerufener externer Prozess. Eine Veröffentlichung des lokal
gebauten Toolchain-Images bleibt außerhalb dieser Entscheidung und benötigt
weiterhin eine eigene Lizenz- und Supply-Chain-Prüfung.

Die bounded OCF-/ZIP-/XML-Prüfungen und Streamingmuster des vorhandenen
EPUB-Titelwriters dürfen als technische Bausteine wiederverwendet oder
extrahiert werden. Seine `SOURCE_METADATA`-Plan-, Capability-, Authorization-,
Executor-, `renameat2`- und Recovery-Authority wird nicht übernommen. Option A
schreibt weder die Source noch eine Calibre-Bibliothek und erzeugt durch diese
Entscheidung keine allgemeine Container-, Metadata-Write- oder W10-Capability.

## GATE-0002

[`GATE-0002`](../quality/GATE_0002_EPUB_TRANSFORM_QUALIFICATION_PLAN.md)
qualifiziert das kombinierte Profil vor jeder `WI-0004`-Implementierung. Das
Gate implementiert und prüft nur den reinen Output-Kandidaten mit synthetischen
EPUBs in frischen netzlosen Workspaces. Es bindet die konkrete
Normalisierungs-, Serializer-, ZIP-, Runtime-, Tool-, Adapter- und
Konfigurationsidentität und prüft mindestens:

- zwei voneinander unabhängige frische Läufe mit byteidentischem Ergebnis und
  eine idempotente erneute Normalisierung desselben calibre-Outputs;
- vollständige Snapshot-Projektion einschließlich Contributor- und
  Serienwerten, getrennte Review-/Preserve-Lineage sowie fail-closed Ablehnung
  partieller oder nicht verlustfrei repräsentierbarer Felder;
- feste OPF-/ZIP-Kanonisierung ohne reale Zeit-, Locale-, Host-, Dateisystem-
  oder freie Environment-Einflüsse;
- EPUBCheck-Konformität und unabhängigen Erhalt von Text, Lesereihenfolge,
  Navigation, Cover, Nicht-Zielfeldern und unkomprimierten Nutzdaten;
- bounded OCF-/ZIP-/XML-Grenzen, Malicious Fixtures, Ressourcenlimits sowie
  aktuelle Tool-, Security-, Lizenz- und Automationsbedingungen.

Nur ein positives, dokumentiertes Ergebnis darf `WI-0004` auf `READY` setzen.
Ein negatives oder unvollständiges Gate lässt `WI-0004` `BLOCKED`; es gibt
keinen Fallback auf semantische Gleichheit, einen anderen `ToolProvider` oder
eine Source-Mutation.

## Geplante W10-Kette

Nach einem akzeptierten Gate entstehen getrennte Waves für den erweiterten
W9-Transformations- und Metadaten-Snapshot, privaten Dry Run, immutable
Preparation/Authorization/Run/Event-Persistenz, eine enge Input-/Output-
Capability, rootübergreifendes Lease/Fencing, netzlosen Replay und
Target-absent/no-follow/no-replace-Publish.

Eine höchstens 15 Minuten gültige Authorization und eine exakte, nicht
geloggte Einzelbestätigung binden genau einen Output. Bounded Batch darf
ausschließlich Vorschau- und Dry-run-Jobs sammeln; Review, Authorization und
Publish bleiben pro Datei. Recovery darf private Stagingdaten verwerfen, einen
bereits exakt veröffentlichten Output reconciliieren oder einen fehlenden
Output erneut erzeugen. Ein abweichender vorhandener Output endet ohne
Mutation bei `MANUAL_REVIEW`. Delete, Overwrite, Purge, Source-Rewrite und
automatischer Batch-Publish bleiben ausgeschlossen.

CLI wird vor der Job-/REST-/Browser-Adaptierung geliefert. Der `surface-api`
erhält weder Source-/Output-Mount noch Capability; nur der netzlose
`operator-worker` darf nach Revalidierung die operation-spezifische Capability
auflösen. Weder die Annahme dieser Entscheidung noch `GATE-0001` erteilt eine
W10-Authorization; es besteht weiterhin keine W10-Authorization. `GATE-0002`
muss positiv abgeschlossen sein, bevor die
getrennten `WI-0004`-Waves beginnen dürfen; operative Authority entsteht erst
in der später vollständig implementierten und geprüften
operation-spezifischen Kette.
