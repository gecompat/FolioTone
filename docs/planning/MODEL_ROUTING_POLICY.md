# Kosten- und qualitätsbewusstes Modell- und Agenten-Routing

**Status:** verbindlich
**Stand:** 2026-08-21
**Geltungsbereich:** KI-unterstützte Entwicklungs-, Review-, Planungs- und
Betriebsaufgaben für FolioTone

## Zweck und Autorität

Diese Richtlinie wählt für jeden Arbeitsschritt die günstigste verfügbare
Ausführungsform, die dessen Qualitäts-, Zuverlässigkeits- und
Sicherheitsanforderungen voraussichtlich erfüllt. Die Einstufung ist
vendor-neutral. Produktnamen, konkrete Modell-IDs, Kontingente und Preise sind
veränderliche Runtime-Eigenschaften und kein Repositoryvertrag.

Wellen- und paketbezogene Pläne dürfen strengere Grenzen festlegen. Sie
dürfen eine Aufgabe jedoch nicht unter die repositoryweite Risikoklasse
abstufen. Datenschutz, Safety, Autorisierung und die W10-Sperre haben Vorrang
vor Kosten- oder Geschwindigkeitszielen.

## Verbindliche Tiers

| Tier | Einsatzgrenze | Typische Arbeit |
|---|---|---|
| `LOCAL` | Kein generatives Modell ist für die Entscheidung erforderlich. Lokale, deterministische Werkzeuge können das Ergebnis vollständig erzeugen oder prüfen. | Suche, Formatierung, Testausführung, Logaggregation, Counts, Diff- und Linkprüfung, Branch-/CI-Status |
| `ECONOMICAL` | Vertrag, Dateiscope und Abnahme sind eindeutig; Fehler sind lokal und billig erkennbar. | kleine Dokumentationsänderung, Characterization Test, fester DTO/Mapper/Parser, begrenztes Refactoring, Statuszusammenfassung |
| `BALANCED` | Mehrere bestehende Verträge oder Schichten müssen integriert werden, oder eine reproduzierbare Ursache ist noch zu diagnostizieren. | Store plus Workflow, schichtübergreifender Bugfix, bestehende Regeln konsistent zusammenführen, semantisches Review |
| `FRONTIER` | Eine neue oder kritische Architektur-, Security-, Privacy-, Nebenläufigkeits-, Identitäts-, Persistenz- oder Datenverlustfrage ist offen. | Lease/Fencing, Secret Handling, Archive-Sandbox, Matching-/Identity-Vertrag, W10, irreversible oder autorisierungsrelevante Entscheidung |

`LOCAL` ist kein kleines Sprachmodell, sondern die bevorzugte Ausführung
durch vorhandene Programme und reproduzierbare Checks. Ein Modell erhält nur
die lokal aggregierte Evidence, die für den nächsten nichtdeterministischen
Schritt erforderlich ist.

## Entscheidungsfolge pro Arbeitsschritt

Der koordinierende Task entscheidet vor jedem abgegrenzten Schritt:

1. Kann ein lokales deterministisches Werkzeug den Schritt vollständig
   ausführen oder prüfen? Dann gilt `LOCAL`.
2. Sind Vertrag, Dateien, Negativfälle und Abnahme eindeutig begrenzt? Dann
   gilt in der Regel `ECONOMICAL`.
3. Müssen mehrere bestehende Schichten integriert oder widersprüchliche
   Befunde diagnostiziert werden? Dann gilt mindestens `BALANCED`.
4. Ist eine Architektur-, Security-, Privacy-, Nebenläufigkeits-, W10- oder
   realistische Datenverlustfrage offen? Dann gilt `FRONTIER`.
5. Kann ein wirklich unabhängiger, konkret prüfbarer Teilauftrag delegiert
   werden, ohne Kontext und Koordination zu duplizieren?

Eine offene `FRONTIER`-Frage wird zuerst entschieden. Erst danach darf ein
kleineres Tier die mechanische Umsetzung übernehmen. Nach jedem schwierigen
Schritt wird die verbleibende Arbeit neu eingestuft; eine einmalige Eskalation
bindet die restliche Welle nicht an das teurere Tier.

## Auswahl innerhalb eines Tiers

Der jeweilige Tool-Adapter oder die Laufzeit ordnet dem Tier ein aktuell
verfügbares Modell und, falls unterstützt, einen Reasoning-/Thinking-Aufwand
zu. Dabei gelten folgende Regeln:

- das günstigste Modell verwenden, das den Tier-Vertrag nachweislich erfüllt;
- vorhandene separate oder günstigere Kontingente für `ECONOMICAL`-Arbeit
  bevorzugen;
- Modellnamen und Preise vor einer kostenrelevanten Runtime-Konfiguration
  aktuell prüfen, nicht im Repository festschreiben;
- dieselben lokalen Abnahmetests für alle Anbieter verwenden;
- keine Berechtigung, kein Dateiscope und keine Safety-Grenze aus einer
  Modellwahl ableiten;
- bei fehlender Modellwahlfunktion mit dem verfügbaren Modell weiterarbeiten
  und den Scope weiterhin nach diesen Tiers begrenzen.

Wenn die Laufzeit Reasoning-/Thinking-Stufen anbietet, ist ein niedriger
Aufwand für Status- und Inventararbeit, ein mittlerer Aufwand für normale
Integration und ein hoher Aufwand für kritische Verträge angemessen. Die
konkreten Bezeichner sind Adapterdetails. Die höchste verfügbare Stufe bleibt
W10 und bestätigter realistischer Gefahr irreversiblen Datenverlusts
vorbehalten.

## Eskalation und Rückkehr

Eine Eskalation erfolgt, wenn mindestens eine Bedingung eintritt:

- das aktuelle Tier liefert wiederholt keine ausreichende Lösung;
- eine wesentliche Unsicherheit kann nicht lokal oder im aktuellen Tier
  aufgelöst werden;
- die notwendige Kontextmenge oder fachliche Tiefe übersteigt den begrenzten
  Auftrag;
- ein Fehler könnte erhebliche Kosten, Datenverlust oder ein
  Sicherheitsproblem verursachen;
- während der Umsetzung wird eine zuvor nicht entschiedene Architektur-,
  Privacy-, Security- oder Autorisierungsfrage sichtbar.

Nach der Entscheidung wird der nächste mechanische Schritt wieder auf
`LOCAL` oder `ECONOMICAL` zurückgestuft, sofern dessen Vertrag dies erlaubt.
Eine Eskalation erweitert niemals den genehmigten Scope. Fehlt eine
Benutzerentscheidung oder Autorisierung, stoppt die Arbeit unabhängig vom
Tier.

## Agenteneinsatz

Eine Wave besitzt genau einen aktiven Implementierungsagenten. Zusätzliche
Agents sind nur für konkrete, begrenzte und unabhängig prüfbare Teilaufgaben
zulässig. Parallelität ist auf disjunkte Dateibereiche oder unabhängige
read-only Analysen begrenzt.

Delegationsaufträge enthalten nur:

- Ausgangscommit und erlaubte Dateien;
- akzeptierten Vertrag und relevante Abhängigkeiten;
- Tier, Stopbedingungen und konkrete Checks;
- bereits lokal aggregierte Findings.

Ein semantisches Review beginnt erst bei stabilem Diff. Mehrere Agents
analysieren oder bearbeiten nicht gleichzeitig denselben beweglichen Vertrag.

## Fallback bei Kapazität oder Verfügbarkeit

Ein Kapazitätsfehler führt nicht zu unbegrenzten Wiederholungen.

1. Innerhalb desselben Tiers wird ein anderes ausreichend fähiges Modell
   verwendet.
2. `ECONOMICAL` darf auf `BALANCED` eskalieren, wenn der Vertrag feststeht und
   die Mehrkosten begründet sind.
3. `BALANCED` darf auf `FRONTIER` eskalieren, wenn die Diagnose oder das Risiko
   dies verlangt.
4. Eine `FRONTIER`-Aufgabe wird nicht auf ein niedrigeres Tier abgesenkt, nur
   weil das vorgesehene Modell nicht verfügbar ist.
5. W10, irreversible Datenverlustgefahr oder eine nicht delegierbare
   Security-Entscheidung wartet auf eine ausreichend fähige Laufzeit oder
   wird als blockiert dokumentiert.

## Vertrag für neue Wellen und Pakete

Jedes neue Frontier-Gate und jedes neue atomare Arbeitspaket dokumentiert vor
Ausführung mindestens:

1. Aufgaben- und Risikoklasse;
2. erforderliches Tier;
3. akzeptierten Vertrag oder vorausgehendes Gate;
4. erlaubte Dateien und explizite Ausschlüsse;
5. fokussierte Checks und vollständigen PR-CI-Gate;
6. Stopbedingungen für Architektur, Security, Privacy, W10 und fehlende
   Autorisierung.

Fehlen diese Angaben, darf eine Wave nur read-only untersucht und für ein
Gate vorbereitet werden. Sie darf nicht mit einer geschätzten Modellwahl
implementiert werden.

## Legacy-Zuordnung bestehender Pläne

Bestehende akzeptierte ADRs und der historisch benannte
`EBOOK_SPARK_WORK_PACKAGES.md` enthalten konkrete Codex-Modellnamen. Diese
Angaben bleiben als historische Ausführungsnotizen lesbar, sind für neue
Läufe aber nicht mehr normativ. Sie werden wie folgt interpretiert:

| Historische Bezeichnung | Vendor-neutrale Einstufung |
|---|---|
| Spark, Mini oder Luna für klar begrenzte Arbeit | `ECONOMICAL` |
| Luna für reine lokale Status-/Logarbeit | zuerst `LOCAL`, sonst `ECONOMICAL` |
| Terra | `BALANCED` |
| Sol oder ein ausdrückliches Frontier-/Security-Gate | `FRONTIER` |

Die sachliche Risikoklasse hat Vorrang vor dieser Übersetzung. Ein historisch
als kleines Paket bezeichneter Task wird zu `FRONTIER`, sobald eine kritische
Frage offen ist.

## Aktuelle FolioTone-Zuordnung

- Status-, CI-, Link- und Mergeprüfungen beginnen mit `LOCAL`.
- Vollständig spezifizierte atomare Pakete verwenden `ECONOMICAL`.
- Gewöhnliche schichtübergreifende Integration und schwierige, aber
  nichtkritische Diagnose verwenden `BALANCED`.
- Neue Medienidentitäten, Matching, Persistenzgrenzen, Archive-Security,
  Secret Handling, Lease/Fencing und W10 benötigen `FRONTIER`.
- ADR-0061 erlaubt die getrennte Entwicklung weiterer E-Book-Writer mit
  synthetischen Fixtures. Jede Gate- und Writer-Wave bleibt `FRONTIER`; diese
  Richtlinie erweitert weder ihren Operationstyp noch die reale Runtime-
  Authority. Aktuell ist nur die enge ADR-0056-Interim-Quarantäne als
  Source-Media-Mutation technisch akzeptiert.

Testauswahl, lokale Evidence und der einmalige vollständige PR-Gate folgen
[`TEST_POLICY.md`](../quality/TEST_POLICY.md). Kontext- und Logkosten folgen
[`COST_EFFICIENT_DEVELOPMENT.md`](../quality/COST_EFFICIENT_DEVELOPMENT.md).
