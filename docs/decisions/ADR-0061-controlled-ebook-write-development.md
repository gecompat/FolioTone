# ADR-0061: Kontrollierte Entwicklung der E-Book-Schreibstrecke

- Status: Accepted
- Datum: 2026-08-22

## Kontext

Die read-only E-Book-Linie ist von Scan, Analyse und Quality über Authority,
Matching und Review bis zu nicht ausführbaren Konsolidierungsplänen weitgehend
implementiert. `EBOOK_WRITE_PIPELINE_PLAN.md` beschreibt bereits die spätere
End-to-End-Schreibstrecke. Außer der engen ADR-0056-Interim-Quarantäne waren
weitere Writer jedoch als blockiert geführt, weil die ausdrückliche
Produktfreigabe für ihre Entwicklung fehlte.

Der Projekteigentümer hat am 2026-08-22 die weitere Entwicklung der
E-Book-Schreiboperationen ausdrücklich freigegeben. Diese Freigabe muss von
einer konkreten operativen Authorization getrennt bleiben: Eine allgemeine
Entwicklungsentscheidung enthält weder Plan-ID und Content Hash noch eine
lokale Capability oder den unmittelbar revalidierten Zustand einer Datei.

## Entscheidung

Die kontrollierte Entwicklung aller im kanonischen E-Book-Schreibplan
aufgeführten Operationstypen ist freigegeben. Implementierung und Tests dürfen
Verträge, Persistenz, Application-Services, CLI-Adapter und spätere REST-/UI-
Adapter ergänzen, soweit die jeweilige Wave ihre operation-spezifischen
Safety-Grenzen einhält.

Diese Entscheidung ist kein globaler Runtime-Schalter. Eine reale Mutation
ist nur zulässig, wenn für genau diesen Operationstyp gleichzeitig gilt:

1. Ein nicht ausführbarer, content-addressed Plan bindet Evidence, Review,
   Zielträger, Writerprofil, Dependencies und Post-write-Verifikation.
2. Eine eigene akzeptierte technische ADR beschreibt Revalidierung,
   Collision Handling, Fencing, Journal, Partial Failure und Recovery.
3. Der Backlog weist die konkrete Implementierungs- und Bedienkette als
   abgeschlossen aus.
4. Eine lokal aufgelöste, möglichst enge Capability erlaubt genau Root,
   Zielträger und Operation; es gibt keine gemeinsame `write-all`-Capability.
5. Eine kurzlebige, einmal verwendbare Authorization bindet den exakten Plan
   und wird unmittelbar vor der Mutation erneut geprüft.
6. Die Ausführung läuft gegen eine frische `ScanRootWriteLease`, schreibt
   append-only Audit-/Recovery-Ereignisse und verifiziert den Zielzustand.

Die Freigabe dieser ADR allein erfüllt keinen dieser sechs Nachweise. Die
aktuell einzige ausführbare Source-Media-Mutation bleibt daher die enge, durch
ADR-0056 definierte Interim-Ein-Datei-Quarantäne. Auch sie ist erst über die
noch zu vervollständigende `W10-005`-Bedienkette regulär nutzbar.

## Entwicklungs- und Testgrenze

Writer-Entwicklung verwendet ausschließlich neue synthetische Dateien und
isolierte Datenbanken beziehungsweise Workspaces unter den vorgesehenen
Testpfaden. Reale private Sammlungen, produktive Runtime-Datenbanken und
autoritative Calibre-Bibliotheken sind kein Entwicklungs- oder CI-Gate.

Die Tests dürfen den vorgesehenen Mutationstyp auf ihren synthetischen
Fixtures tatsächlich ausführen. Sie prüfen mindestens die positive
Einzelschrittfolge sowie changed-since-analysis, Collision, Fencingverlust,
Retry, Crash-/Recovery-Zustände und pfadfreie Fehler. Die vollständige lokale
Suite wird nicht pro Iteration wiederholt; der stabile PR-Head erhält genau
einen vollständigen CI-Gate.

Ein späterer Lauf gegen eine private Sammlung ist ein getrennter lokaler
Betriebsschritt. Er benötigt die im jeweiligen Operationsvertrag geforderte
Capability und Authorization und darf nicht aus dieser Entwicklungsfreigabe
abgeleitet werden.

## Operationstrennung

Die folgenden Grenzen bleiben voneinander unabhängig:

- Quarantäne;
- eingebettete Source-Metadaten;
- Sidecar Create/Update;
- Calibre oder ein anderes externes Library-System;
- Rename und Reorganisation;
- Archive-/Container-Rewrite;
- Rollback;
- Purge nach Retention;
- Empty-Directory-Cleanup.

Ein akzeptierter oder implementierter Writer öffnet keinen benachbarten
Operationstyp. Copy+Delete, Überschreiben, Cross-Volume-Fallback, freie Pfad-
oder Command-Argumente sowie stilles Symlink-/Reparse-Following bleiben ohne
eigenen belegten Vertrag verboten.

## Aktivierte Lieferfolge

`W9-006` wird als nächster regulärer E-Book-Produktslice aktiviert. Er liefert
zuerst den nicht ausführbaren `MetadataCorrectionPlan`; ein Writer darf seine
fachliche Auswahl nicht ersetzen. `W10-005` bleibt parallel als getrennte
`FRONTIER`-Wave aktiv und vervollständigt ausschließlich die vorhandene
ADR-0056-Quarantänekette.

Danach entscheidet `FG-W10-METADATA-WRITE` den ersten konkreten
Format-/Zielträgervertrag. Erst eine akzeptierte Gate-ADR aktiviert dessen
kleinsten vertikalen Writer-Slice. `W9-007` und die übrigen Writer folgen in
eigenen Waves; ihre Reihenfolge darf anhand von Produktnutzen und belegter
Recovery-Fähigkeit angepasst werden, ohne die Operationstrennung zu lockern.

REST-API und grafische Oberfläche bleiben bis FUT-011 und einer eigenen
Produktoberflächen-ADR zurückgestellt. Eine spätere Oberfläche verwendet
dieselben Application-Verträge und kann keine zusätzliche Mutation Authority
erzeugen. E-Books, Musik, Bilder und weitere Linien erhalten getrennte
Einstiege und Capability-Sets; diese ADR aktiviert nur die E-Book-Linie.

## Folgen

- Die fehlende Owner-Freigabe ist kein Blocker mehr. Die operation-spezifischen
  technischen Gates wechseln von `BLOCKED` zu `DECISION`, solange ihre ADR
  noch offen ist.
- `W9-006` wechselt von `PLANNED` zu `NEXT`; `W10-005` bleibt `READY`.
- Implementierung mit synthetischen Fixtures darf vor einer operativen
  Freigabe erfolgen, sofern die Wave beim fehlenden technischen Vertrag
  fail-closed bleibt.
- Es entsteht kein globaler Write-Modus und keine Berechtigung, reale private
  Daten ohne konkrete Capability, Authorization und Revalidierung zu ändern.
- Music, Bilder, Federation und eine neue Produktoberfläche werden nicht
  aktiviert.
