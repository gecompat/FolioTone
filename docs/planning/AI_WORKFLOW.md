# Vendor-neutrale Wave-Orchestrierung

**Status:** verbindlich
**Geltungsbereich:** Entwicklungs-, Review-, Dokumentations- und
Betriebswellen für FolioTone

## Zweck

Eine Wave ist die kleinste zusammenhängende Änderung, die einen
dokumentierten Vertrag implementiert oder prüft und als eigener Pull Request
abgenommen werden kann. Die Orchestrierung ist unabhängig vom verwendeten
Coding-Agenten. `AGENTS.md`, Architekturentscheidungen, Backlog, Projektstatus
und lokale Nachweise bleiben die Autorität; ein Tool-Adapter darf sie nur
auffindbar machen, nicht inhaltlich ersetzen.

## Wave-Vertrag

Vor dem ersten Schreibzugriff werden festgehalten:

- Wave- oder Backlog-ID und erwartetes Ergebnis;
- verifizierter Ausgangscommit von `origin/main`;
- akzeptierte ADRs, Invarianten und Abhängigkeiten;
- erlaubte Dateien sowie ausdrückliche Ausschlüsse;
- Risikoklasse und Tier aus `MODEL_ROUTING_POLICY.md`;
- fokussierte Tests, betroffene Regressionen und vollständiger PR-Gate;
- Stopbedingungen für Scope, Architektur, Security, Privacy, W10 und
  fehlende Autorisierung.

Fehlt eine materielle Entscheidung, wird eine getrennte Gate-Wave vorbereitet.
Eine Implementierungs-Wave erfindet die Entscheidung nicht stillschweigend.

## Ablauf einer Wave

1. **Inventar:** Remote, `origin/main`, Branch, Commit, Arbeitsbaum,
   vorhandene Worktrees und betroffene Verträge read-only prüfen.
2. **Isolation:** Vorhandene Benutzerarbeit bleibt unangetastet. Eine neue
   Wave verwendet bei Bedarf einen sauberen Worktree unter
   `C:\rep\worktrees\FolioToneDev1` und einen eigenen Feature-Branch.
3. **Begrenzung:** Den kleinsten vollständigen vertikalen Slice und die
   Abnahme definieren. Modell- und Agentenwahl erfolgen pro Schritt.
4. **Implementierung:** Genau ein Implementierungsagent bearbeitet den
   stabilen Vertrag. Unverbundene Refactorings und Nachbarbereinigungen bleiben
   außerhalb des Diffs.
5. **Local-first-Prüfung:** Characterization/Reproduktion, fokussierte Tests,
   betroffene Regressionen und statische Checks nach `TEST_POLICY.md`
   ausführen. Vollständige Logs bleiben lokal.
6. **Stabiles Review:** Erst den fertigen Diff semantisch prüfen. Findings
   werden dedupliziert und nach demselben Vertrag behoben.
7. **Git-Abschluss:** Nur bestätigte Dateien stagen, einen kohärenten Commit
   erstellen, den Feature-Branch pushen und einen Pull Request gegen `main`
   verwenden. Direkte `main`-Writes und Force-Pushes sind nicht zulässig.
8. **Gate:** Genau ein vollständiger CI-Gate prüft den stabilen PR-Head.
   Gemergt wird nur dieser grün verifizierte Head. Danach wird der kurze
   Post-Merge-Vertrag geprüft.
9. **Handover:** `BACKLOG.md` und `PROJECT_STATUS.md` geben Ergebnis,
   tatsächliche Tests, offene Nachweise, Blocker und nächste Wave wieder.

## Parallelität und Delegation

Parallelität ist nur für disjunkte Dateibereiche oder unabhängige read-only
Analysen zulässig. Mehrere Agents bearbeiten nicht denselben Vertrag und
reviewen keinen noch beweglichen Diff. Jeder delegierte Auftrag enthält
Ausgangscommit, erlaubte Dateien, Tier, Stopbedingungen und lokale Checks.

Ein Agentenwechsel übergibt nur den für den nächsten Schritt erforderlichen
Kontext. Bereits lokal erzeugte Ergebnisse werden weiterverwendet; Analysen
und vollständige grüne Logs werden nicht ohne neue Evidence wiederholt.

## Tool-Unabhängigkeit

Tool-Adapter dürfen nur Discovery, Dateisyntax oder Runtime-Mapping erklären.
Sie dürfen keine zweite Definition von Architektur, Safety, Teststufen,
Modellrisiko oder Definition of Done enthalten. Bei einem Widerspruch gilt der
Root-Vertrag in `AGENTS.md` zusammen mit den dort referenzierten kanonischen
Dokumenten.

Die aktuelle Zuordnung für Codex, Copilot, Junie und Databricks Genie steht
in [`AI_TOOL_ADAPTERS.md`](AI_TOOL_ADAPTERS.md).
