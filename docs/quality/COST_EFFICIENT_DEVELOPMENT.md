# Kosten- und kontexteffiziente Entwicklung

**Status:** verbindlich
**Geltungsbereich:** lokale Entwicklung, Agentenarbeit, Tests, Reviews und CI-Wellen

## Ziel

FolioTone minimiert Modellkontext, Agenten-Turns und wiederholte Rechenarbeit,
ohne fachliche, sicherheitsbezogene oder migrationsbezogene Nachweise zu
schwächen. Deterministische lokale Programme werten vollständige
Repository-, Test- und Laufzeitdaten aus. Ein Modell erhält nur die
Informationen, die für die nächste Entscheidung oder Änderung erforderlich
sind.

Die verbindlichen Teststufen und Gates stehen in
[`TEST_POLICY.md`](TEST_POLICY.md). Die Modell- und Agenteneinstufung steht in
[`MODEL_ROUTING_POLICY.md`](../planning/MODEL_ROUTING_POLICY.md).

## Local-first-Auswertung

Folgende Daten werden zuerst lokal und deterministisch ausgewertet:

- geänderte Dateien, Imports, Aufrufer und betroffene Tests;
- Test-Counts, Laufzeiten, Exitcodes und wiederholte Fehlersignaturen;
- vollständige Pytest-, Ruff-, Mypy-, Git- und CI-Logs;
- Diff-, Schema-, Migrations-, Index- und statische Vertragsprüfungen;
- bekannte plattformspezifische Abweichungen;
- Branch-, Commit-, PR- und CI-Status.

Vollständige Logs bleiben in einem nicht versionierten Pfad unter
`C:\rep\artifacts\FolioToneDev1`. Ein lokaler Parser oder ein knappes Skript
erzeugt daraus eine begrenzte Zusammenfassung mit:

- ausgeführtem Test- oder Prüfprofil;
- Anzahl erfolgreicher, fehlgeschlagener, übersprungener und abgebrochener
  Fälle;
- Gesamtlaufzeit und auffälligen Dauergruppen;
- neuen, deduplizierten Fehlersignaturen;
- je neuer Fehlersignatur einem kleinen relevanten Ausschnitt;
- Pfad des privaten vollständigen Artefakts, wenn eine spätere lokale
  Prüfung erforderlich ist.

Vollständige Traces, lange Listen grüner Tests und wiederholte Instanzen
derselben Fehlersignatur werden nicht in den Modellkontext übernommen. Wenn
die lokale Klassifikation nicht ausreicht, wird nur der kleinste zusätzliche
Ausschnitt geladen, der die offene Diagnosefrage beantworten kann.

## Agenten- und Modellkoordination

Eine atomare Wave besitzt genau einen aktiven Implementierungsagenten. Ein
Review beginnt erst mit stabilem Diff und konkreten Abnahmekriterien. Mehrere
Agents analysieren denselben beweglichen Diff nicht wiederholt.

Delegationskontext enthält nur:

- Ausgangscommit und erlaubte Dateien;
- akzeptierten Vertrag und relevante Abhängigkeiten;
- Tier, konkrete Tests und Stopbedingungen;
- bereits lokal aggregierte Findings.

Mechanische Schritte verwenden `LOCAL` oder das günstigste ausreichende
Modell im Tier `ECONOMICAL`. Eine Eskalation erfolgt nur bei einer konkret
benannten Integrations-, Architektur-, Security-, Privacy-,
Nebenläufigkeits- oder Datenverlustfrage. Nach deren Klärung wird der
nächste Schritt erneut eingestuft.

## Abbruch- und Eskalationsregeln

Ein Lauf wird nicht durch wiederholtes Polling oder identische Wiederholungen
verlängert. Bei einem Fehler gilt:

1. lokal deduplizieren und klassifizieren;
2. genau einen kleinsten reproduzierenden Fall ausführen;
3. nur die neue relevante Evidence an das Modell geben;
4. nach dem Fix fokussiert prüfen;
5. den vollständigen Gate erst am stabilen Wave-Ende ausführen.

Eine Wiederholung benötigt einen geänderten Input, eine geänderte
Implementierung, eine andere Plattformannahme oder eine ausdrückliche
Flake-/Stabilitätsmessung.

## Wave-Bericht

Der Abschluss einer Wave nennt knapp:

- geänderten Scope und erforderliches Tier;
- lokal ausgeführte fokussierte und betroffene Prüfungen;
- vollständigen Gate mit Commit- oder PR-Bezug;
- gemessene Laufzeiten vor und nach einer Performanceänderung;
- verbleibende neue Fehler oder bewusst nicht erneut ausgeführte bekannte
  unveränderte Fehler;
- private Artefaktpfade nur in lokaler Betriebsübergabe, niemals in
  öffentlichen DTOs oder versionierten Laufzeitberichten.
