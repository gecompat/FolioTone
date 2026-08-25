# Ausführungsplan für die nächste E-Book-Entwicklung

**Status:** verankert

**Stand:** 2026-08-25

**Plananker:** `WI-0002`

## Zweck und Ausführungsfront

Dieser Plan ordnet die nach `S-FUT11-04` aktivierte E-Book-Fortsetzung. Nur
`BACKLOG.md` bestimmt den aktuellen Status. Der Plan erzeugt keine zweite
Ausführungsachse und autorisiert keine W10-Operation.

Die verbindliche Reihenfolge lautet:

1. `WI-0003` (`FUT-009`) implementiert book-only Fixity Monitoring nach
   `DEC-0001` und ist die einzige `NEXT`-Wave.
2. `GATE-0001` qualifiziert danach das deterministische EPUB-3-zu-EPUB-3-
   Transformationsprofil und entscheidet, ob `DEC-0002` akzeptiert werden kann.
3. `WI-0004` (`FUT-008`) bleibt bis zu diesem positiven Gate blockiert und
   liefert anschließend die Transformationskette in kleinen Pull Requests.

`FUT-002` ist durch EPUBCheck, `ebook-quality/v1` und die getrennte
Struktur-/Format-Risk-Projektion bereits umgesetzt und wird im Backlog
reconciliiert. Music, Images, Remote-/Mehrbenutzerbetrieb und MCP werden durch
diese Folge nicht aktiviert.

## WI-0003 — Fixity Monitoring

| Slice | Ergebnis | Tier | Lokale Abnahme |
|---|---|---|---|
| Baseline | Immutable Baseline-Drafts, 15-Minuten-Aktivierung, insert-only Persistenz und echte SQLite-read-only Projektion für genau einen E-Book-`ScanRoot`. | `FRONTIER` für Vertrag/Persistenz, danach `ECONOMICAL` | DTO-/Serializer-, Migrations-, Store-, Privacy-, Lease- und Hash-Streaming-Tests. |
| Verifikation | Frische Full-SHA-256-Verifikation, feste Ergebniswerte und append-only Einzelentscheidungen ohne falsche Missing-Befunde. | `BALANCED` | Root-Ausfall, laufender Scan, Source-Drift, Leaseverlust, unreadable, changed/new/missing und Idempotenz. |
| Surface | Manuelle persistente Jobs, CLI, Application-Ports, REST und Browser mit `REVIEW`-Reauthentisierung. | `BALANCED` | Application-, CLI-, API-, CSRF-, Idempotency-, Cursor-, Privacy-, Worker- und UI-Verträge. |

Jeder Slice verwendet höchstens zwei Hash-Worker, ausschließlich synthetische
Fixtures und einen eigenen Branch/Worktree/PR. Weder Baseline noch
Verifikation verwendet W10, Netzwerk oder Source Writes.

## GATE-0001 und WI-0004 — EPUB-Transformation

`GATE-0001` ist eine `FRONTIER`-Wave. Es prüft das gelockte Toolchain-Image
lokal und netzlos mit synthetischen EPUBs. Nur ein dokumentierter positiver
Byte-Reproduzierbarkeits-, Security-, Lizenz- und Automationsnachweis darf
`DEC-0002` auf `Accepted` und `WI-0004` auf `READY` setzen.

Bei positivem Gate folgt `WI-0004` in dieser Reihenfolge:

| Slice | Ergebnis | Tier | Stopbedingung |
|---|---|---|---|
| Planvertrag | Transform-spezifischer, reviewter Metadaten-Snapshot und vollständige W9-Outputbindung ohne Executor. | `FRONTIER` | Ungeklärte Wertlineage, Preserved Fields oder Schema-/Reviewmigration. |
| Dry Run | Privates netzloses Staging mit festem ToolProvider und unabhängiger Outputverifikation. | `BALANCED` | Abweichender Hash, schlechtere EPUBCheck-Evidence oder nicht erhaltene Inhalte. |
| Authority | Capability, höchstens 15 Minuten gültige Authorization, insert-only Run/Eventjournal, rootübergreifendes Lease/Fencing und read-only Status. | `FRONTIER` | Ungeklärte Lease-Reihenfolge, Collision-, no-follow-, fsync- oder Recovery-Semantik. |
| Publish/CLI | Exakter Replay, Target-absent/no-replace-Publish, Einzelbestätigung, Recovery, Folgescan und Reconciliation. | `FRONTIER` | Source-Drift, Zielkollision, Leaseverlust oder uneindeutiger physischer Zustand. |
| Surface | Bounded Batch-Preparation sowie Einzelreview/-publish über Jobs, REST und Browser. | `BALANCED` | Capability oder Source-/Output-Mount im Webprozess, Bulk-Accept oder automatische W10-Wiederholung. |

## Post-Merge-Blocker-Audit

Unmittelbar nach dem Merge von `WI-0002` wird `origin/main` erneut verifiziert.
Ein read-only Audit klassifiziert anschließend jede offene E-Book-Funktion als
`bereits erfüllt`, `ausführungsbereit`, `Entscheidung erforderlich`,
`technisch blockiert` oder `bewusst außerhalb des Produktscopes`.

Der Audit umfasst mindestens Series-Completeness, Backup-/Replica-Fixity,
Transformationsqualifikation, Import/Export/Reorganisation, Sidecar- und
externe Library-Writes, Archive-Rewrite, Archive-Secretkanal,
Archive-Member-Byte-Identity, Quarantäne-Backend-Härtung, Rollback/Retention/
Purge, Empty-Directory-Cleanup sowie fehlende Produktoberflächen für
Titelwriter, Quarantäne und spätere Writer. Eine neue Architektur-, Privacy-,
Lizenz-, Security- oder W10-Entscheidung wird nicht geraten, sondern mit
konkreter Evidence und sicheren Optionen zur Entscheidung vorgelegt.

## Git- und Testvertrag

Jeder Slice beginnt am frisch verifizierten `origin/main` in einem isolierten
Worktree. Fokussierte Tests und betroffene Regressionen laufen vor statischen
Checks; der stabile PR-Head erhält genau einen vollständigen CI-Gate. Merge ist
nur als Zwei-Eltern-Merge-Commit zulässig. Danach werden `origin/main`,
Post-Merge-Contract, `BACKLOG.md` und `PROJECT_STATUS.md` erneut geprüft.
