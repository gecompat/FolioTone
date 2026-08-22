# Ausführungsauftrag für die aktuelle FolioTone-Wave

Der Dateiname bleibt für bestehende Links erhalten. Die historische E1- bis
E12-Fortsetzung ist abgeschlossen; dieser Auftrag startet keine alte Welle und
setzt keinen eigenen Status.

```text
Arbeite im FolioTone-Repository ausschließlich an genau einer atomaren Aufgabe
aus der kanonischen Ausführungsfront am Anfang von
docs/planning/BACKLOG.md.

Lies zuerst AGENTS.md und die dort vorgeschriebenen Status-, Handover-,
Architektur-, ADR-, Qualitäts- und Terminologiedokumente. Prüfe origin/main,
Branch, Commit, Dirty State, vorhandene Worktrees und die Voraussetzungen der
gewählten Backlog-ID. Ein Planungsdokument ist kein Implementierungsnachweis.

Arbeite ausschließlich unter C:\rep. Verwende einen frischen Worktree unter
C:\rep\worktrees\FolioToneDev1. Cache, Temp und Ergebnisse liegen in den
dafür vorgesehenen C:\rep-Verzeichnissen. Private Source-Pfade, Dateinamen,
Hashwerte, Sammlungsdaten, Runtime-Datenbanken, Logs, Reports, Zähler und
Secrets bleiben außerhalb von Git. Tests verwenden ausschließlich
synthetische Daten.

Für CS-01 bis CS-03 gelten ADR-0058, CLI-only, read-only Source Media,
insert-only Snapshots, bounded Keyset-Reads und das explizite
--private-details-Ausgabeprofil. Implementiere keine Music-, Federation-,
Content-Volltext-, API-, MCP-, UI- oder W10-Funktion im selben Pull Request.

Für W10-005 gelten ADR-0056 und FRONTIER. Erlaubt ist ausschließlich die
Bedien- und Recoverykette der vorhandenen Interim-Ein-Datei-Quarantäne. Keine
neuen Mutationstypen, kein Copy+Delete, kein Cross-Volume-Fallback, keine
atomare No-Replace-Behauptung, keine Pfade in argv oder öffentlichen Reports.
Die zweite Bestätigung läuft ausschließlich über nicht geloggtes stdin.

Wähle pro Schritt den Tier aus MODEL_ROUTING_POLICY.md. Führe fokussierte
Tests, betroffene Regressionen, statische Checks und genau einen vollständigen
PR-CI-Gate am stabilen Head aus. Aktualisiere BACKLOG.md und PROJECT_STATUS.md
nur mit tatsächlich verifizierten Ergebnissen. Stoppe ohne riskante Annahme,
wenn Scope, Architektur, Security, Privacy, W10 oder Autorisierung unklar sind.
```
