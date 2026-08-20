# Kosten- und kontexteffiziente Entwicklung

**Status:** verbindlich
**Geltungsbereich:** lokale Entwicklung, Agentenarbeit, Tests, Reviews und CI-Wellen

## Ziel

FolioTone minimiert LLM-Kontext, Agenten-Turns und wiederholte Rechenarbeit, ohne
fachliche, sicherheitsbezogene oder migrationsbezogene Nachweise zu schwächen.
Deterministische lokale Programme werten vollständige Repository-, Test- und
Laufzeitdaten aus. An ein Modell werden nur die Informationen übergeben, die für
die nächste Entscheidung oder Änderung erforderlich sind.

Kostenreduktion ist kein Grund, notwendige Tests auszulassen. Sie bestimmt, wann
ein Test ausgeführt wird, wie Ergebnisse lokal aggregiert werden und welches
Modell den nächsten begrenzten Arbeitsschritt bearbeitet.

## Local-first-Auswertung

Folgende Daten werden grundsätzlich zuerst lokal und deterministisch ausgewertet:

- geänderte Dateien, Imports, Aufrufer und betroffene Tests;
- Test-Counts, Laufzeiten, Exitcodes und wiederholte Fehlersignaturen;
- vollständige pytest-, Ruff-, Mypy-, Git- und CI-Logs;
- Diff-, Schema-, Migrations-, Index- und statische Vertragsprüfungen;
- bekannte plattformspezifische Abweichungen;
- Branch-, Commit-, PR- und CI-Status.

Vollständige Logs bleiben in einem nicht versionierten Pfad unter
`C:\rep\artifacts\FolioTone`. Ein lokaler Parser oder ein knappes
Shell-/Python-Programm erzeugt daraus eine begrenzte Zusammenfassung. Die
Zusammenfassung enthält höchstens:

- ausgeführtes Test- oder Prüfprofil;
- Anzahl erfolgreicher, fehlgeschlagener, übersprungener und abgebrochener Fälle;
- Gesamtlaufzeit und auffällige Dauergruppen;
- neue, deduplizierte Fehlersignaturen;
- je neuer Fehlersignatur einen kleinen relevanten Ausschnitt;
- Pfad des privaten vollständigen Artefakts, wenn eine spätere lokale Prüfung
  erforderlich ist.

Ein vollständiger Trace, eine lange Liste grüner Tests oder wiederholte Instanzen
derselben Fehlersignatur werden nicht in den Modellkontext übernommen. Wenn die
lokale Klassifikation nicht ausreicht, wird nur der kleinste zusätzliche Ausschnitt
geladen, der die offene Diagnosefrage beantworten kann.

## Teststufen

Eine Entwicklungswelle verwendet die folgenden Stufen in dieser Reihenfolge:

1. **Characterization oder Reproduktion:** genau der kleinste Test, der den
   Ausgangsfehler oder bestehenden Vertrag belegt.
2. **Fokussierter Test:** Tests der unmittelbar geänderten Einheit oder des
   betroffenen Stores beziehungsweise Workflows.
3. **Betroffene Regression:** lokal bestimmte direkte und relevante indirekte
   Verbraucher der Änderung.
4. **Statische Checks:** Ruff, Mypy und `git diff --check` nur im notwendigen
   Scope; repositoryweit, wenn ein öffentlicher oder geteilter Vertrag betroffen
   ist.
5. **Vollständiger Gate:** genau einmal für den stabilen PR-Stand. Nach einem
   reinen Dokumentationsfix wird er nur erneut ausgeführt, wenn der Fix den Gate-
   oder CI-Vertrag selbst berührt.

Ein während der Implementierung unveränderter grüner Test wird nicht ohne
begründete Abhängigkeitswirkung erneut ausgeführt. Bekannte Fehler werden nicht
still ignoriert; sie werden einmal klassifiziert und im vollständigen Gate erneut
bewertet. Zwischenläufe geben sie nur dann erneut aus, wenn die aktuelle Änderung
ihren Codepfad berührt.

Während der Diagnose gelten standardmäßig knappe pytest-Ausgaben, beispielsweise
`-q --tb=short --maxfail=1`. Vollständige Traces werden lokal gespeichert und nur
bei einer neuen Fehlerklasse gezielt gelesen.

## SQLite-Testdatenbanken

Tests gegen den aktuellen Schema-Head erzeugen nicht für jeden Test die gesamte
Alembic-Migrationskette neu. Stattdessen gilt:

- pytest erzeugt einmal pro Testsession und Prozess eine vollständig migrierte,
  danach unveränderte Template-Datenbank;
- jeder Test erhält eine eigene beschreibbare Dateikopie dieser Template-
  Datenbank;
- kein Test teilt eine beschreibbare Datenbank mit einem anderen Test;
- echte Migrationstests beginnen weiterhin mit einer leeren Datenbank oder der
  ausdrücklich geprüften Vorrevision und führen die reale Migrationskette aus;
- die Template-Datei wird vor und nach der Session auf Unverändertheit geprüft;
- Parallelisierung erfolgt erst nach dieser Entkopplung und wird mit einer
  begrenzten Workerzahl gemessen, statt pauschal alle Fälle gleichzeitig zu
  starten.
- Lokale Windows-Läufe setzen `TEMP` und `TMP` oder `pytest --basetemp` auf
  einen aufgabenspezifischen, neuen Pfad unter `C:\rep\tmp\FolioTone`. Damit
  liegen auch die kopierten SQLite-Testdatenbanken im kontrollierten
  Entwicklungsbereich. Ein vorhandener Basistemp-Pfad wird nicht
  wiederverwendet oder automatisch gelöscht.

Damit bleiben Isolation, Reihenfolgeunabhängigkeit und Parallelfähigkeit erhalten,
während wiederholter identischer DDL-Aufbau entfällt.

## Agenten- und Modellkoordination

Eine atomare Welle besitzt genau einen aktiven Implementierungsagenten. Ein Review
beginnt erst mit einem stabilen Diff und konkreten Abnahmekriterien. Mehrere Agents
analysieren denselben beweglichen Diff nicht wiederholt.

Delegationskontext enthält nur:

- Ausgangscommit und erlaubte Dateien;
- akzeptierten Vertrag und relevante Abhängigkeiten;
- konkrete Tests und Stopbedingungen;
- bereits lokal aggregierte Findings.

Lange Chat-Historien, vollständige grüne Logs und unverbundene Repositorytexte
werden nicht weitergereicht. Mechanische Pakete verwenden das günstigste gemäß
`MODEL_ROUTING_POLICY.md` zulässige Modell. Eine Eskalation auf ein stärkeres
Modell erfolgt nur bei einer konkret benannten Architektur-, Sicherheits-,
Privacy-, Nebenläufigkeits- oder Datenverlustfrage. Nach deren Klärung wird wieder
auf das günstigere zulässige Modell zurückgeschaltet.

## Abbruch- und Eskalationsregeln

Ein Lauf wird nicht durch wiederholtes Polling oder identische Wiederholungen
verlängert. Bei einem Fehler gilt:

1. lokal deduplizieren und klassifizieren;
2. genau einen kleinsten reproduzierenden Fall ausführen;
3. nur die neue relevante Evidence an das Modell geben;
4. nach dem Fix fokussiert prüfen;
5. den vollständigen Gate erst am stabilen Wellenende ausführen.

Wenn eine Prüfung ohne neue Evidence erneut dasselbe Ergebnis liefert, wird sie
nicht wiederholt. Eine Wiederholung benötigt einen konkret geänderten Input, eine
geänderte Implementierung, eine andere Plattformannahme oder eine ausdrückliche
Flake-/Stabilitätsmessung.

## Wellenbericht

Der Abschluss einer Welle nennt knapp:

- geänderten Scope und verwendetes Modell;
- lokal ausgeführte fokussierte und betroffene Prüfungen;
- vollständigen Gate mit Commit- oder PR-Bezug;
- gemessene Laufzeiten vor und nach einer Performanceänderung;
- verbleibende neue Fehler oder bewusst nicht erneut ausgeführte bekannte
  unveränderte Fehler;
- private Artefaktpfade nur in lokaler Betriebsübergabe, niemals in öffentlichen
  DTOs oder versionierten Laufzeitberichten.
