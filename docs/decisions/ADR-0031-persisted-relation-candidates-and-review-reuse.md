# ADR-0031: Persistierte Relation Candidates und Review-Wiederverwendung

- Status: Accepted
- Datum: 2026-08-18

## Kontext

ADR-0029 begrenzt die E-Book-Kandidatenbildung. ADR-0030 bewertet einen
kanonischen Endpoint-Paarfall mit einem versionierten Matcherprofil. Das reine
`MatcherOutcome` ist jedoch weder dauerhaft nachvollziehbar noch ein
Review-Fall. EB-06B benötigt deshalb einen insert-only Snapshot, konkrete
Evidence-Links und die Wiederverwendung des generischen append-only
Review-Cores aus ADR-0028.

Eine technische Matcher-Version darf eine fachlich unveränderte Entscheidung
nicht entwerten. Geänderte Endpoints, Relation Type, materielle Evidence, die
vollständige konkurrierende Kandidatenmenge oder die
`decision_compatibility_version` müssen dagegen einen neuen Fall erzeugen.

## Entscheidung

Alembic `0014_relation_candidates` ergänzt `relation_candidates` und
`relation_candidate_evidence`. Ein `RelationCandidate` bindet genau einen
abgeschlossenen `ScanRun`, zwei kanonisch geordnete Endpoints, Relation Type,
Matcherprofil, Confidence, Status, materiellen Evidence-Fingerprint und den
Fingerprint der vollständigen Kandidatenmenge.

Der dedizierte `SQLiteRelationCandidateStore` ist insert-only. Er berechnet
das `MatcherOutcome` aus den übergebenen persistierten Feature-Links erneut
und lehnt einen abweichenden Status, Score oder Fingerprint ab. Ein exakter
Retry liefert den vorhandenen Snapshot; eine abweichende Wiederholung unter
demselben semantischen Schlüssel ist ein Fehler. Der generische
Update-by-ID-Repositorypfad wird nicht verwendet.

Feature-Links speichern einen begrenzten Feature-Code, Zustand, materiellen
SHA-256-Fingerprint und optional eine opake Referenz auf persistierte Evidence.
Polymorphe Referenzen werden im Store innerhalb derselben Transaktion gegen
die konkrete Evidence-Tabelle geprüft. Pfade, Namen, Titel, Identifierwerte
und Tool-Payloads werden nicht in den neuen Tabellen gespeichert.

## Review und Wiederverwendung

Ein erstmaliger bibliografischer Candidate mit `REVIEW_REQUIRED` wird als
`ReviewType.MATCH_RELATION` und `ReviewCandidateKind.RELATION` in den
bestehenden Review-Core eingereiht. ACCEPT, REJECT und DEFER bleiben
append-only und optimistisch an Evidence- und Candidate-Set-Fingerprint
gebunden.

ACCEPT und REJECT dürfen nur wiederverwendet werden, wenn Endpoints, Relation
Type, Matcher-Namespace, materielle Evidence, vollständige Kandidatenmenge und
`decision_compatibility_version` exakt übereinstimmen. Die rein technische
`matcher_version` wird dabei absichtlich nicht gebunden. DEFER bleibt
reviewbar und wird nicht als fachliche Wiederverwendungsentscheidung
behandelt.

`CONFIRMED` ist weiterhin ausschließlich für technisch exakte File-Duplikate
mit gleichem vollständigem SHA-256 zulässig. EB-06B projiziert noch keine
akzeptierte Entscheidung in die generische `relations`-Tabelle und trifft
keine Keep-, Lösch- oder Konsolidierungsentscheidung.

## Transaktions- und Laufzeitgrenze

Relation Candidates werden append-only und idempotent gegen einen expliziten
abgeschlossenen Scan-Snapshot geschrieben. Sie verändern weder laufenden
Scan-, Hash- oder Analysezustand noch Source Media. Daher erwerben sie in
dieser Welle keine `ScanRootWriteLease`. Eine spätere mutable Relation-
Projektion oder ein fortsetzbarer Matching-Lauf benötigt vor Einführung einen
eigenen Ownership- und Fencing-Vertrag.

Migration und Downgrade sind kontrollierte Offline-Operationen. Der Downgrade
auf `0013` wird verweigert, sobald Relation-Candidate-Daten vorhanden sind.

## Sicherheit und Aussagegrenzen

- Gleiche Namen, Titel, Providerwerte oder einzelne Identifier bestätigen
  keine Relation automatisch.
- Tool- oder Provider-Agreement kann harte lokale Contradictions nicht
  überstimmen.
- Die neue Persistenz enthält keine privaten Pfade oder Rohwerte.
- Es gibt keinen Source-Media-Zugriff, keine Netzwerkabfrage und keine
  Dateisystemmutation.
- Dieser Slice öffnet keinen eigenen W10-Pfad; nur die getrennte
  ADR-0056-Interim-Quarantäne ist ausführbar.

## Verifikation

Synthetische Tests prüfen insert-only Idempotenz, atomaren Rollback bei
ungültigen Evidence-Referenzen, Reproduktion des Matcher-Ergebnisses,
ACCEPT-/REJECT-Wiederverwendung, nicht wiederverwendbares DEFER sowie Upgrade,
leeren Downgrade und den Datenverlustschutz der Migration `0014`.
