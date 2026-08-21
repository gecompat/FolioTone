# Tool-Adapter für KI-Systeme

**Status:** verbindlich für Repository-Discovery
**Stand:** 2026-08-21

## Grundsatz

`AGENTS.md` im Repository-Root ist der vendor-neutrale fachliche Vertrag.
Tool-spezifische Dateien bleiben kurze Adapter und verweisen auf diese Quelle.
Sie duplizieren weder Safety- noch Test- oder Modellregeln. Ein Tool, das den
Root-Vertrag nicht automatisch lädt, muss ihn vor einer Änderung explizit
lesen.

## Zuordnung

| System | Discovery im Repository | Adapterregel |
|---|---|---|
| OpenAI Codex | liest Root-`AGENTS.md` direkt | Kein zusätzlicher Repositoryadapter. Modellnamen werden zur Laufzeit auf `LOCAL`, `ECONOMICAL`, `BALANCED` oder `FRONTIER` abgebildet. |
| GitHub Copilot und Visual Studio Copilot | Unterstützung unterscheidet sich nach Oberfläche; `.github/copilot-instructions.md` ist der gemeinsame Repositoryadapter | Der Adapter fordert das Lesen von Root-`AGENTS.md` und der kanonischen Workflow-/Testdokumente an. |
| JetBrains Junie | priorisiert `.junie/AGENTS.md`, Root-`AGENTS.md` ist Fallback | `.junie/AGENTS.md` enthält nur den Discovery-Hinweis auf den Root-Vertrag. Das Legacyformat `.junie/guidelines.md` wird nicht neu eingeführt. |
| Databricks Genie Code | liest `AGENTS.md` und `CLAUDE.md` entlang des Workspace-Pfads | Root-`AGENTS.md` wird direkt verwendet. Workspace- oder Benutzerinstruktionen dürfen strengere lokale Vorgaben ergänzen, aber Repositoryverträge nicht abschwächen. |
| Databricks Genie Agents, früher Genie Spaces | Analytics-Agent für Unity-Catalog-Daten, kein Repository-Coding-Agent | Business-Semantik, Beispiele, SQL-Funktionen und Space-/Agent-Instruktionen werden in Databricks gepflegt. `AGENTS.md` ist dafür kein Ersatz. |

## Vendor-spezifisches Modell-Mapping

Die Adapter legen keine dauerhaften Modell-IDs fest. Vor einem Lauf wird die
aktuelle Tool- und Modellverfügbarkeit geprüft. Danach wird das günstigste
ausreichend fähige Modell innerhalb des erforderlichen Tiers gewählt.

Wenn ein System keine explizite Modellwahl oder keinen Agentenwechsel anbietet,
arbeitet es mit dem verfügbaren Modell weiter. Scope, lokale Tests,
Stopbedingungen und Safety-Grenzen bleiben trotzdem verbindlich.

## Externe Primärquellen

Die Discovery-Angaben sind zeitabhängig und müssen bei einer späteren
Adapteränderung erneut gegen die offiziellen Quellen geprüft werden:

- OpenAI Codex: <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- GitHub Copilot: <https://docs.github.com/en/copilot/reference/custom-instructions-support>
- JetBrains Junie: <https://junie.jetbrains.com/docs/guidelines-and-memory.html>
- Databricks Genie Code: <https://docs.databricks.com/aws/en/genie-code/instructions>
- Databricks Genie Agents: <https://docs.databricks.com/aws/en/genie-agents/>
