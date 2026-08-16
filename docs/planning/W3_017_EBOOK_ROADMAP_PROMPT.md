# Ausführungs-Prompt für die E-Book-Roadmap

Der folgende Prompt ist für einen neuen FolioTone-Thread vorgesehen. Vor der
Verwendung muss das Codex-Projekt auf einem Host mit `C:\rep` geöffnet sein.

```text
Setze die E-Book-Roadmap aus
docs\planning\W3_017_EBOOK_ROADMAP.md im aktuell geöffneten FolioTone-
Repository autonom und wellenweise um. Lies zuerst AGENTS.md sowie die dort
vorgeschriebenen Status-, Handover-, Architektur-, ADR-, Qualitäts- und
Terminologiedokumente.
Prüfe den tatsächlichen Stand von origin/main und behandle den Plan nicht als
Beleg für bereits implementierte oder bereits gemergte Arbeit.

Arbeite ausschließlich unter C:\rep. Verwende für neue Code-Wellen getrennte
Worktrees unter C:\rep\worktrees\FolioTone, Cache unter
C:\rep\cache\FolioTone, temporäre Daten unter C:\rep\tmp\FolioTone und
private Ergebnisse unter C:\rep\artifacts\FolioTone. Private Source-Pfade,
Dateinamen, Hashwerte, Sammlungsdaten, Runtime-Datenbanken, Logs, Reports,
Zähler und Secrets bleiben außerhalb von Git und dürfen nicht in PR-Text oder
Repository-Dokumentation erscheinen. Source Media bleibt read-only.

Beginne mit der ersten noch nicht nachweislich abgeschlossenen Welle E1. Nutze
gezielte lokale Tests während der Entwicklung und genau einen vollständigen
PR-CI-Gate pro konsistenter Code-Welle. Merge nur den exakten grünen Head nach
origin/main und verifiziere anschließend den kurzen Post-Merge-Vertrag.
Wende Code auf die private Runtime-Datenbank erst nach Merge, Clean-Commit-
Prüfung und Writer-Stillstand an.

Für E2 bist du nach erfolgreichem Preflight ausdrücklich autorisiert, den
eindeutig verifizierten alten ebook-hash-candidates-Prozessbaum und die davon
abhängigen obsoleten Supervisor-/Watcher-Prozesse kontrolliert zu beenden.
Beende niemals Codex, fremde Projektprozesse oder einen nicht eindeutig
zugeordneten Prozess. Mehrere PIDs gelten nicht ohne Prozessbaum- und
Commandline-Nachweis als mehrere Hash-Invocations. Prüfe vor dem Beenden, dass
der neueste ScanRun COMPLETED ist, kein Scan-Writer läuft und die gemergte
optimierte Kandidaten-Hash-Implementierung bereitsteht.

Erstelle nach Writer-Stillstand und vor Migration ein konsistentes privates
SQLite-Backup über die Backup-API und prüfe integrity_check sowie Lineage.
Starte danach einen begrenzten Canary gemäß E2. Die neue Invocation muss
bereits persistierte FILE_SHA256-Evidence überspringen. Wenn Canary,
Heartbeat, Lease, Zähler und Fencing konsistent sind, setze denselben Lauf
ohne max-items im Hintergrund fort. Beobachte Heartbeat und Fortschritt
höchstens alle fünf Minuten und melde nur Phasenwechsel, belastbaren
Fortschritt, Failure-Anstieg, Lease-Verlust, Prozessende oder BLOCKED.

Der vollständige private Sammlungslauf ist kein Entwicklungs- oder CI-Gate.
Entwickle E4, E5 und spätere book-only Wellen in isolierten Worktrees weiter,
solange sie weder den aktiven Runtime-Writer noch dessen Datenbank verändern.
Verwende für Tests ausschließlich kleine synthetische Fixtures und begrenzte
synthetische Skalierungsdatenbanken. Führe keinen vollständigen privaten Scan
nur zum Nachweis einer Codeänderung aus.

Halte die Reihenfolge und Stop-Gates des Plans ein. E4 benötigt eine eigene
ADR und Migration; implementiere keine bloße Startprüfung ohne vollständiges
Fencing. Prüfe vor E7 die dann aktuellen offiziellen Providerregeln und
verwende nur privacy-minimierte strukturierte DTOs. W9 bleibt nicht
ausführbar. W10 und jede Source-Media-Mutation bleiben blockiert.

Aktualisiere BACKLOG.md, PROJECT_STATUS.md, HANDOVER.md und relevante ADR-/
Architekturdokumente pro gemergter Welle mit ausschließlich tatsächlich
verifizierten Ergebnissen. Warte nicht auf Benutzereingaben, solange sichere
Arbeit innerhalb des dokumentierten Scopes möglich ist. Wenn ein Stop-Gate
eintritt, nimm keine riskante Annahme vor, sondern dokumentiere den konkreten
pfadfreien Blocker und arbeite an unabhängigen sicheren Wellen weiter.
```
