# ADR-0028: Persistierte Resolution Candidates und append-only Review Core

- Status: Accepted
- Datum: 2026-08-17

## Kontext

Die lokalen E-Book-Resolver konnten bereits nicht kanonische Kandidaten für
`Agent`, `Work`, `Edition` und `Series` erzeugen. Kandidaten, ihre konkrete
Evidence und menschliche Entscheidungen waren jedoch nicht dauerhaft und
wiederverwendbar gespeichert. Ein Authority-spezifischer Entscheidungsspeicher
hätte später einen zweiten, konkurrierenden Vertrag für Classification,
Matching und Konsolidierungsplanung erzwungen.

Gleiche Namen, Titel oder Identifier sind außerdem kein allgemeiner
Identitätsbeweis. Insbesondere darf ein beliebiger Disambiguierungsstring oder
eine ISBN niemals einen Agent-Merge freigeben.

## Entscheidung

Alembic `0013_resolution_review_core` ergänzt vier additive Tabellen:

- `resolution_candidates` speichert versionierte, nicht kanonische Kandidaten
  mit Subject, Kandidatenidentität, Resolverprofil, Confidence, materiellen
  Fingerprints und Routingstatus;
- `resolution_candidate_evidence` bindet jeden Kandidaten geordnet an konkrete
  persistierte Evidence und kennzeichnet Unterstützung oder Widerspruch sowie
  die behauptete Identitätsebene;
- `review_items` bildet den begrenzten generischen Review-Fall;
- `review_decisions` speichert `ACCEPT`, `REJECT` und `DEFER` als unveränderliche
  Folge mit monotoner `sequence_no` je Item.

Die vier Tabellen verwenden einen dedizierten Store. Sie werden nicht beim
generischen `SQLiteRepository` registriert, weil dessen Update-by-ID-Vertrag
Candidate-Snapshots und append-only Decision History verletzen würde.

## Konservative Resolution Policy

Ein erstmaliger Fall ist immer `REVIEW_REQUIRED`. Gleicher normalisierter Name,
gleicher Titel, eine ISBN oder ein Provider-Treffer genügt nie für AUTO_SAFE.
AUTO_SAFE ist in diesem Slice ausschließlich die Wiederverwendung einer
früheren kompatiblen ACCEPT-Entscheidung. Eine kompatible REJECT-Entscheidung
unterdrückt die unveränderte erneute Vorlage; DEFER bleibt reviewbar.

Wiederverwendung verlangt dieselbe Subject-Identität, Kandidatenart und
-Entität, denselben Resolver-Namespace, dieselbe materielle Evidence, dieselbe
vollständige Menge konkurrierender Kandidaten und dieselbe
`decision_compatibility_version`. Rein technische Änderungen an
`resolver_version` oder `producer_version` entwerten eine Entscheidung nicht.
Eine andere Entity-Ebene, Evidence, Kandidatenmenge oder
Kompatibilitätsversion erzeugt dagegen einen neuen Review-Fall.

`evidence_fingerprint` wird aus kanonisch sortierten materiellen
Evidence-Deskriptoren berechnet. Zufällige Row-IDs, Einfügereihenfolge und
Zeitpunkte beeinflussen ihn nicht. `candidate_set_fingerprint` bindet eine
Entscheidung zusätzlich an die vollständige konkurrierende Kandidatenmenge.
Ein AUTO_SAFE-Kandidat muss auf eine konkrete kompatible ACCEPT-Decision als
Evidence verweisen.

## Identität, Evidence und Datenschutz

Agent, Work, Edition und Series bleiben getrennte Identitätsebenen. Entity-
Subjects dürfen nur auf derselben Ebene aufgelöst werden. Source Observations,
Tool Results und Value Assertions werden nicht überschrieben; Resolution und
Review erzeugen keine kanonischen Metadaten und keine Source-Media-Änderung.

Die neuen Tabellen speichern ausschließlich opake IDs, Enums, technische
Profile, Confidence, SHA-256-Digests, Reason Codes und Zeitpunkte. Reason Codes
sind allowlist-förmig begrenzt und werden nicht in `repr` ausgegeben. Pfade,
Dateinamen, Namen, Titel, Identifierwerte, Provider-Payloads und Freitextnotizen
sind nicht Bestandteil des Vertrags.

## Atomizität und Historie

Kandidat und Evidence-Links werden atomar und idempotent eingefügt. Bereits
vorhandene semantische Snapshots werden inhaltlich verglichen; widersprüchliche
Wiederholungen schlagen geschlossen fehl. Polymorphe Evidence-Referenzen
werden im Store innerhalb derselben Transaktion gegen die konkrete Tabelle
validiert.

Beim Append einer Entscheidung prüft der Store die erwartete letzte Decision,
Evidence-, Kandidatenmengen- und Kompatibilitätssnapshots. Erst danach werden
die nächste Sequenz und der neue Item-Zustand in derselben Transaktion
geschrieben. Es gibt keine Update- oder Delete-API für Decision History.
Migration 0013 verweigert ein Downgrade, solange eine ihrer vier Tabellen Daten
enthält.

## Konsequenzen und Grenzen

- Entity Resolution und Review-Reuse sind vollständig offline testbar.
- Falsch-positive Auto-Merges werden zugunsten zusätzlicher Review-Arbeit
  vermieden.
- Diese Welle implementiert keinen Provider-Cache, keinen realen Provider,
  keine Matching-Relation, keine Canonical-Projektion und keine Review-CLI.
- Music-Resolution bleibt in W4/W5A-004 geplant.
- Dieser Slice öffnet keinen eigenen W10-Pfad. Außer der getrennten
  ADR-0056-Interim-Quarantäne gibt es keine Lösch-, Verschiebe-, Rename- oder
  Retag-Ausführung.

## Verifikation

Synthetische Unit- und SQLite-Integrationstests prüfen Fingerprint-Stabilität,
Identitätsebenen, Homonym-Schutz, exakte ACCEPT-/REJECT-/DEFER-Semantik,
technische Versionskompatibilität, Stale-Fencing, atomaren Rollback,
append-only Sequenzen, bounded Keyset-Abfragen, Schema-Constraints sowie
Upgrade und geschützten Downgrade von `0012` auf `0013`.
