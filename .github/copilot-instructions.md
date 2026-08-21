# GitHub and Visual Studio Copilot discovery adapter

Diese Datei enthält keine eigenständigen Projektregeln. Lies vor jeder
Analyse oder Änderung die Root-Datei [`AGENTS.md`](../AGENTS.md) und die dort
für den aktuellen Scope referenzierten kanonischen Dokumente.

Insbesondere gelten:

- Wave-Orchestrierung: [`AI_WORKFLOW.md`](../docs/planning/AI_WORKFLOW.md)
- Modell-Tiers: [`MODEL_ROUTING_POLICY.md`](../docs/planning/MODEL_ROUTING_POLICY.md)
- Local-first-Tests: [`TEST_POLICY.md`](../docs/quality/TEST_POLICY.md)
- Dokumentationsstil: [`DOCUMENTATION_STYLE.md`](../docs/quality/DOCUMENTATION_STYLE.md)
- Sprache und Terminologie: [`LANGUAGE_AND_TERMINOLOGY.md`](../docs/quality/LANGUAGE_AND_TERMINOLOGY.md)
- Fachbegriffe: [`GLOSSARY.md`](../docs/reference/GLOSSARY.md)

Verwende die Tiers `LOCAL`, `ECONOMICAL`, `BALANCED` und `FRONTIER` und bilde
sie erst in der aktuellen Copilot-Oberfläche auf ein verfügbares Modell ab.
Dieser Adapter darf den Root-Vertrag, Safety, Privacy, W10, den geschützten
Root-README-Lizenzblock oder die Git-Regeln weder ersetzen noch abschwächen.
Der Lizenzblock bleibt unverändert, sofern der Benutzer nicht ausdrücklich
seine Änderung beauftragt.
