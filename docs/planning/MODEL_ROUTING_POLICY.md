# Modell- und Agenten-Routing

**Status:** Verbindlich

**Stand:** 2026-08-18

**Geltungsbereich:** KI-unterstützte Entwicklungs-, Review-, Planungs- und
Betriebsaufgaben für FolioTone

## Zweck und Autorität

Diese Richtlinie legt die repositoryweite Auswahl von Modell, Thinking-Stufe
und Agenteneinsatz fest. Sie minimiert Ressourcenverbrauch, ohne die für
Domain-, Persistenz-, Privacy- und Sicherheitsverträge erforderliche Qualität
abzusenken.

Wellen- und paketbezogene Pläne dürfen strengere Grenzen festlegen. Sie dürfen
ein hier als Frontier- oder Security-Aufgabe eingestuftes Vorhaben jedoch nicht
an ein schwächeres Modell delegieren. Bei einem Widerspruch gilt die höhere
Risikoeinstufung.

Die Modellverfügbarkeit, Kontingente und Abrechnung sind Runtime-Eigenschaften
und keine Produktverträge. Für die aktuelle Entwicklungsumgebung gilt als
Budgetannahme, dass 5.3 Codex Spark ein separates Kontingent besitzt. Deshalb
wird dieses Kontingent für geeignete atomare Coding-Pakete bevorzugt. Exakte
API-Listenpreise werden hier nicht festgeschrieben, weil sie weder den
Codex-Credits entsprechen noch dauerhaft stabil sind.

## Entscheidungsfolge

Vor dem Start einer Aufgabe bestimmt der koordinierende Task in dieser
Reihenfolge:

1. ob eine Architektur-, Sicherheits-, Privacy-, Datenverlust- oder
   Autorisierungsentscheidung offen ist;
2. ob alle fachlichen Verträge bereits akzeptiert und die erlaubten Dateien
   sowie Abnahmetests begrenzt sind;
3. ob die Aufgabe mehrere Schichten integriert oder einen ungeklärten Fehler
   diagnostiziert;
4. ob sie nur read-only Status, Recherche, mechanische Prüfung oder
   Dokumentationspflege umfasst;
5. ob ein Agent einen wirklich unabhängigen, konkreten Teilauftrag übernehmen
   kann.

Eine offene Frontier-Frage wird zuerst mit dem dafür vorgesehenen Modell
entschieden. Erst danach darf ein kleineres Modell die mechanische Umsetzung
übernehmen.

## Technische Modell-IDs

Delegations- und Ausführungsaufträge verwenden die folgenden Modell-IDs, sofern
die jeweilige Codex-Laufzeit sie anbietet:

| Anzeigename | Modell-ID |
|---|---|
| 5.6 Sol | `gpt-5.6-sol` |
| 5.6 Terra | `gpt-5.6-terra` |
| 5.6 Luna | `gpt-5.6-luna` |
| 5.5 | `gpt-5.5` |
| 5.4 | `gpt-5.4` |
| 5.4 Mini | `gpt-5.4-mini` |
| 5.3 Codex Spark | `gpt-5.3-codex-spark` |

## Modellmatrix

| Aufgabenklasse | Bevorzugtes Modell | Thinking | Typische Beispiele |
|---|---|---|---|
| Atomare Implementierung bei vollständig festgelegtem Vertrag | 5.3 Codex Spark | `high`; `medium` nur für reine Dokumentation oder Characterization-Tests | DTOs, Parser, feste Adapter, Reporter, CLI, fokussierte Tests, exakt spezifizierte Migration |
| Read-only Status und mechanische Prüfung | 5.6 Luna | `low` oder `medium` | Heartbeat, PR-/CI-Status, Branch-Inventar, Linkprüfung, begrenzte Suche, Diff-Zusammenfassung |
| Mechanisches Coding ohne Spark-Verfügbarkeit | 5.4 Mini | `medium`, selten `high` | kleine Refactorings, Testergänzungen, feste Mapper und Adapter |
| Gewöhnliche Integration und komplexere Diagnose | 5.6 Terra | `medium`; `high` nur bei begründetem Qualitätsbedarf | Store plus Workflow, mehrere Module, reproduzierbarer Bugfix, bestehende Verträge zusammenführen |
| Frontier-Vertrag und kritische Architektur | 5.6 Sol | `medium` für begrenzte Gates, `high` für kritische Verträge | neue Domainmodelle, Identity Resolution, Matching Policy, Privacy, Persistenzgrenzen |
| Adversarial oder nebenläufigkeitskritische Arbeit | 5.6 Sol | `high`, ausnahmsweise `xhigh` | Lease/Fencing, stale Takeover, Secret Handling, Archive-Sandbox, atomare Writes |
| W10 oder bestätigte irreversible Datenverlustgefahr | 5.6 Sol | `max` | Mutationsvertrag, Quarantäne/Purge/Undo, bestätigter datenverlustrelevanter Defekt |

5.4 und 5.5 sind keine Standardziele für neue Aufgaben. 5.4 dient als Ersatz
für Terra und 5.5 als Ersatz für Sol, wenn das bevorzugte Modell nicht
verfügbar ist und die unten festgelegte Fallback-Grenze dies zulässt.

## Thinking-Regel

- `low` ist Status-, Inventar- und Routineprüfungen vorbehalten.
- `medium` ist der Standard für normale Analyse, Integration und begrenzte
  Frontier-Gates.
- `high` wird verwendet, wenn ein öffentlicher Vertrag, mehrere Schichten,
  schwer reproduzierbare Fehler oder relevante Negativfälle betroffen sind.
- `xhigh` wird nur für Nebenläufigkeit, Identity-/Matching-Grenzen,
  adversarial Input, Secret Handling oder vergleichbare kritische
  Risikoklassen verwendet.
- `max` bleibt W10 und bestätigter realistischer Gefahr irreversiblen
  Datenverlusts vorbehalten.

Eine höhere Thinking-Stufe erweitert niemals Scope oder Berechtigung. Wenn
eine Aufgabe eine neue Entscheidung oder Autorisierung benötigt, stoppt sie
unabhängig vom Modell.

## Agenteneinsatz

Ein Agent wird nur eingesetzt, wenn der Teilauftrag konkret, begrenzt und
unabhängig prüfbar ist. Einfache sequenzielle Aufgaben werden direkt erledigt,
weil Delegation zusätzlichen Kontext- und Koordinationsverbrauch erzeugt.

Für delegierte Arbeit gelten folgende Regeln:

- genau ein Implementierungsagent je atomarem Paket;
- Parallelität nur bei disjunkten Dateibereichen oder unabhängigen read-only
  Analysen;
- kein paralleles Implementieren und Editieren derselben Verträge;
- ein knapper Auftrag mit Ausgangscommit, Abhängigkeiten, erlaubten Dateien,
  Stopbedingungen und konkreten Checks anstelle unnötiger Chat-Historie;
- ein zweiter Frontier-Agent nur für eine tatsächlich unabhängige kritische
  Prüfung;
- fokussierte lokale Checks während der Arbeit und genau ein vollständiger
  PR-CI-Gate je konsistenter Welle.

Ein nachfolgender Review verwendet Luna oder 5.4 Mini für mechanische
Prüfungen, Terra für semantische Integration und Sol nur für die kritischen
Risikoklassen der Modellmatrix.

## Kapazitäts- und Fallback-Regel

Ein Kapazitätsfehler wird nicht in einer unbegrenzten Wiederholungsschleife
behandelt. Zulässige Fallbacks sind:

| Ausgangsmodell | Fallbackfolge | Grenze |
|---|---|---|
| 5.3 Codex Spark | 5.4 Mini, danach 5.6 Terra | nur bei bereits vollständig festgelegtem Vertrag |
| 5.6 Luna | 5.4 Mini, danach 5.6 Terra | Thinking nicht unnötig erhöhen |
| 5.6 Terra | 5.4 | gleiche Aufgaben- und Thinking-Klasse beibehalten |
| 5.6 Sol | 5.5 | nicht für W10 oder bestätigte Datenverlustgefahr |

Für W10, irreversible Datenverlustgefahr oder eine nicht delegierbare
Security-Entscheidung wird nicht auf ein niedriger eingestuftes Modell
ausgewichen. Die Aufgabe wartet auf das erforderliche Modell oder wird als
blockiert gemeldet.

## Vertrag für neue Wellen und Pakete

Jedes neue Frontier-Gate und jedes neue atomare Arbeitspaket dokumentiert vor
Ausführung mindestens:

1. Aufgabenklasse und Risikoklasse;
2. bevorzugtes Modell und Thinking-Stufe;
3. zulässigen Fallback;
4. akzeptierten Vertrag oder vorausgehendes Gate;
5. erlaubte Dateien und explizite Ausschlüsse;
6. fokussierte Checks und vollständigen PR-CI-Gate;
7. Stopbedingungen für Architektur, Security, Privacy, W10 und fehlende
   Autorisierung.

Fehlen diese Angaben, darf eine zukünftige Welle nur read-only untersucht und
für ein Frontier-Gate vorbereitet werden. Sie darf nicht stillschweigend mit
einer geschätzten Modellwahl implementiert werden.

## Aktuelle FolioTone-Zuordnung

- Die verbleibenden atomaren EB-07- und späteren freigegebenen Spark-Pakete
  verwenden 5.3 Codex Spark mit `high`.
- Status-, CI- und Merge-Prüfungen verwenden grundsätzlich 5.6 Luna.
- FG-08 und vergleichbare begrenzte Produktverträge beginnen mit 5.6 Sol
  `medium` und eskalieren nur anhand der Thinking-Regel.
- Reale Archive-Extraktion, Secret-Übergabe und Prozessisolation verwenden
  5.6 Sol `high`; adversarial Sicherheitslücken können `xhigh` rechtfertigen.
- Neue Medienidentitäten, `CollectionState`, Query-AST und Content-Privacy
  benötigen zuerst ein Frontier-Gate. Die anschließenden mechanischen Pakete
  werden erneut auf Spark-Tauglichkeit zerlegt.
- Jede Source-Media-Mutation bleibt durch W10 blockiert und wird durch diese
  Richtlinie nicht autorisiert.
