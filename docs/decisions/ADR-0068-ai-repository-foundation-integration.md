# ADR-0068: Semantische Integration der AI Repository Foundation 1.2.0

- Status: Accepted
- Datum: 2026-08-23

## Kontext

FolioTone besitzt bereits ein umfangreiches, projektspezifisches Governance-
System. Das Root-`AGENTS.md` erschließt Projektstatus, Handover, Backlog,
Wave-, Modell-, Test-, Dokumentations-, Architektur-, Privacy- und
Safety-Verträge. Die dünnen Adapter für Copilot und Junie verweisen auf
diesen kanonischen Einstieg; Codex und Databricks Genie Code lesen ihn
direkt.

AI Repository Foundation `1.2.0` ergänzt eine anbieterneutrale allgemeine
Mindestbaseline für Projektarbeit. Ihre Integrationsrichtlinie verlangt für
bestehende Repositorys einen semantischen Abgleich statt einer mechanischen
Normalisierung. Die Regeln des Zielprojekts bleiben für Projektfakten und
bewusst strengere Grenzen autoritativ.

Bewertet wurde der Foundation-Stand
`28e0e071fef421528d106676c99234d48be08b6b`. Die Root-Lizenz und der
geschützte zweisprachige README-Lizenzblock von FolioTone dürfen durch die
Integration nicht verändert werden.

## Entscheidung

Die in `foundation/manifest.json` für den Core-Scope freigegebenen Regeln
werden unter `.ai/foundation/` übernommen. Der verwaltete
`AI_REPOSITORY_FOUNDATION`-Discovery-Block wird in das bestehende Root-
`AGENTS.md` eingefügt. Foundation-Adapter werden nicht installiert:
FolioTone behält seine bereits dünnen, projektspezifisch geprüften Adapter
und deren Rückverweis auf das Root-`AGENTS.md`.

Die vollständige MIT-Attribution der Foundation liegt ausschließlich in
`.ai/foundation/AI_REPOSITORY_FOUNDATION_NOTICE.md`. Sie ändert weder
`LICENSE.md` noch den Lizenzvertrag oder den geschützten Lizenzblock von
FolioTone.

Der semantische Abgleich ergibt:

| Bereich | Klasse | Autoritative Auslegung |
|---|---|---|
| Root-Discovery und namespacete Baseline | `COMPLEMENTARY` | Der Foundation-Block erschließt die allgemeine Baseline; die vorhandene FolioTone-Lesereihenfolge erschließt weiterhin alle Projektverträge. |
| Projekt-, Domain-, Privacy- und W10-Regeln | `PROJECT_STRONGER` | FolioTone behält seine engeren Regeln für private Mediendaten, synthetische Fixtures, Source-Media-Mutation, Capabilities, Recovery und pfadfreie Ausgaben. |
| Arbeits- und Autorisierungsgrenzen | `PROJECT_STRONGER` | Die Foundation vermeidet unnötige Bestätigungen; FolioTones explizite Pfad-, Git-, Destructive-Action- und W10-Grenzen bleiben verbindlich. |
| Modell-Routing | `EQUIVALENT` und `PROJECT_STRONGER` | Beide verwenden `LOCAL`, `ECONOMICAL`, `BALANCED` und `FRONTIER`; FolioTones Wave- und Risikozuordnung bleibt die detailliertere Authority. |
| Validierung | `COMPLEMENTARY` | Der Foundation-Validator prüft nur `FOUNDATION_INTEGRITY`; FolioTones statische, semantische, testbezogene und empirische Gates bleiben zusätzlich erforderlich. |
| Tool-Adapter | `EQUIVALENT` | Die vorhandenen Adapter sind bereits dünn und definieren keine parallele Governance; sie werden nicht ersetzt. |
| Attribution und Third-Party-Regeln | `COMPLEMENTARY` | Der namespacete MIT-Hinweis erfüllt die Foundation-Attribution, ohne die FolioTone-Lizenz zu ändern. |

Es liegt kein `FOUNDATION_REQUIRED_CONFLICT`, `TARGET_INTERNAL_CONFLICT`,
`ORPHANED_AUTHORITY` oder `ADAPTER_GOVERNANCE_MISPLACED` vor. Ein späteres
Foundation-Update wird erneut anhand der
`SEMANTIC_INTEGRATION_POLICY.md` bewertet; die Core-Dateien werden nicht
ungeprüft automatisch überschrieben.

## Validierung

Die Integration erhält target-seitige statische Verträge für Version,
Dateiinventar, Root-Discovery und Attribution. Zusätzlich wird der
Foundation-Validator im Scope `FOUNDATION_INTEGRITY` ausgeführt. Die
vorhandenen FolioTone-Dokumentationsverträge und `git diff --check` bleiben
Pflicht. Ein repository-only Fresh-Agent-Transfer ohne vorherigen Chatkontext
bleibt ein separater manueller semantischer Nachweis und wird bis zu seiner
Ausführung als `pending manual validation` ausgewiesen.

## Folgen

- Allgemeine Arbeits-, Sicherheits-, Privacy-, Evidenz-, Lizenz- und
  Dependency-Regeln sind versioniert und über den Root-Einstieg auffindbar.
- Strengere FolioTone-Verträge werden nicht abgeschwächt oder dupliziert.
- Die Produktfront bleibt `S-FUT11-01`; diese Governance-Integration
  implementiert keine Runtime-Fähigkeit und autorisiert keine zusätzliche
  Source-Media-Mutation.
- Foundation- und Projektvalidierung bleiben getrennte Nachweisbereiche.
