# Local-first-Teststrategie

**Status:** verbindlich
**Geltungsbereich:** lokale Entwicklung, Dokumentation, Reviews und CI-Wellen

## Ziel

Tests liefern den kleinstmöglichen reproduzierbaren Nachweis für den
aktuellen Schritt und am stabilen Pull-Request-Head genau einen vollständigen
Gate. Kostenreduktion darf keine erforderliche Prüfung entfernen. Sie
verhindert doppelte Läufe, hält Laufzeitdaten lokal und trennt schnelle
Diagnose von vollständiger Abnahme.

## Teststufen

Eine Wave verwendet die folgenden Stufen in dieser Reihenfolge:

1. **Characterization oder Reproduktion:** Der kleinste Test belegt den
   Ausgangsfehler oder bestehenden Vertrag.
2. **Fokussierter Test:** Tests der unmittelbar geänderten Einheit, des
   Stores, Workflows oder Dokuments.
3. **Betroffene Regression:** Lokal bestimmte direkte und relevante indirekte
   Verbraucher der Änderung.
4. **Statische Checks:** Ruff, Mypy, Dokumentationsverträge und
   `git diff --check` im notwendigen Scope; repositoryweit bei einem
   öffentlichen oder geteilten Vertrag.
5. **Vollständiger Gate:** Genau einmal für den stabilen PR-Head über die
   vorhandene CI. Nach einem reinen Dokumentationsfix wird er nur erneut
   ausgeführt, wenn der Fix den Gate- oder CI-Vertrag selbst berührt.

Ein unveränderter grüner Test wird nicht ohne begründete
Abhängigkeitswirkung erneut ausgeführt. Bekannte Fehler werden einmal
klassifiziert und im vollständigen Gate erneut bewertet; sie werden nicht
still ignoriert.

## Standardprofile

| Profil | Zweck | Typische Befehle |
|---|---|---|
| Dokumentation | Links, Vertragsstrings, Whitespace und betroffene statische Regeln | `pytest -q tests/static/test_documentation_contracts.py`, `git diff --check` |
| Python fokussiert | kleinster betroffener Test mit knapper Diagnose | `pytest -q --tb=short --maxfail=1 <testpfad>` |
| Statisch betroffen | geänderte Python-Dateien und geteilter Vertrag | `ruff check <scope>`, `mypy src/foliotone` bei geteilten Typverträgen |
| Repository lokal | stabiler Stand, wenn lokal erforderlich und wirtschaftlich | `ruff check .`, `mypy src/foliotone`, `pytest` |
| PR-CI | kanonischer vollständiger Gate | Install, Ruff, Mypy, Pytest, Docker-Build, Migration und Smoke-Tests gemäß `CI_WORKFLOW.md` |

Die tatsächliche Testauswahl richtet sich nach dem Diff. Ein
Dokumentationsprofil ist kein Ersatz für Code- oder Migrationsprüfungen,
wenn sich das Verhalten geändert hat.

## Testdaten und lokale Pfade

- Tests verwenden ausschließlich synthetische, generierte, Public-Domain-
  oder ausdrücklich redistributierbare minimale Fixtures.
- Reale Collection-Daten, private Metadaten, Runtime-Datenbanken und Secrets
  gelangen weder in Tests noch in Git oder CI.
- Lokale Windows-Läufe setzen `TEMP` und `TMP` oder `pytest --basetemp` auf
  einen neuen aufgabenspezifischen Pfad unter `C:\rep\tmp\FolioToneDev1`.
- Ein vorhandener Basistemp-Pfad wird nicht wiederverwendet oder automatisch
  gelöscht.
- Vollständige Logs und private Testartefakte liegen außerhalb von Git unter
  `C:\rep\artifacts\FolioToneDev1`.

## SQLite-Testdatenbanken

Tests gegen den aktuellen Schema-Head erzeugen einmal pro Testsession und
Prozess eine vollständig migrierte, danach unveränderte Template-Datenbank.
Jeder Test erhält eine eigene beschreibbare Dateikopie. Echte
Migrationstests beginnen weiterhin mit einer leeren Datenbank oder der
ausdrücklich geprüften Vorrevision und führen die reale Migrationskette aus.

Kein Test teilt eine beschreibbare Datenbank mit einem anderen Test. Die
Template-Datei wird vor und nach der Session auf Unverändertheit geprüft.
Parallelisierung wird erst nach dieser Entkopplung mit begrenzter Workerzahl
gemessen.

## Evidence und Aussagen

Ein Abschlussbericht nennt nur tatsächlich ausgeführte Prüfungen mit Scope,
Ergebnis und bei Bedarf Laufzeit. Ein nicht ausgeführter Gate wird als offen
benannt. Grüne Ergebnisse eines anderen Commits, einer anderen Plattform oder
eines historischen PRs gelten nicht als Nachweis für den aktuellen Head.

Vollständige Logs werden nach
[`COST_EFFICIENT_DEVELOPMENT.md`](COST_EFFICIENT_DEVELOPMENT.md) lokal
aggregiert. In Modellkontext, Commit- oder PR-Text gelangen nur deduplizierte
Findings und die für eine Entscheidung notwendigen Ausschnitte.
