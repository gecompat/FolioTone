# ADR-0032: Begrenzter Offline-E-Book-Matching-Workflow

- Status: Accepted
- Datum: 2026-08-18

## Kontext

ADR-0029 stellt begrenzte Candidate Blocks bereit. ADR-0030 definiert die
relation-spezifischen Matcherprofile, ADR-0031 persistiert deren Ergebnisse
und bindet sie an den append-only Review-Core. Für den Abschluss von EB-06
fehlt ein dünner Workflow, der diese Verträge ohne Source-Media-Zugriff und
ohne collection-weite Paarbildung zusammensetzt.

## Entscheidung

`EbookMatchingService` arbeitet ausschließlich auf einem expliziten neuesten
abgeschlossenen `ScanRun`. Er liest höchstens die konfigurierten Block-,
Member- und Candidate-Grenzen und unterstützt in v1 genau drei sichere
Projektionen:

- `FILE_SHA256` erzeugt `EXACT_DUPLICATE` auf File-Ebene. Große exakte Gruppen
  werden vom kanonischen Repräsentanten zu den übrigen bounded Members
  verbunden und nicht quadratisch expandiert.
- `EDITION_IDENTIFIER` erzeugt `SAME_EDITION` nur zwischen unterschiedlichen
  bereits aufgelösten Edition-Identitäten. Der Fall bleibt
  `REVIEW_REQUIRED`.
- `AGENT_TITLE` erzeugt `SAME_WORK` nur zwischen unterschiedlichen bereits
  aufgelösten Work-Identitäten. Der Fall bleibt `REVIEW_REQUIRED`.

`RESOLVED_EDITION` und `RESOLVED_WORK` gruppieren Beobachtungen, die bereits
auf dieselbe Identität zeigen, und erzeugen deshalb keine Self-Relation.
`TEXT_FINGERPRINT` und `SERIES_CONTEXT` bleiben Supporting Evidence und werden
in v1 nicht allein zu einer Relation erweitert.

Der Workflow öffnet keine Source-Datei. Er verwendet ausschließlich
persistierte, konkrete Evidence-IDs, reproduziert das Matchergebnis im
insert-only Store und setzt bei einem Candidate-Limit den Zustand
`truncated`. Wiederholungen bleiben idempotent. Eine kompatible frühere
ACCEPT-/REJECT-Entscheidung wird wiederverwendet; andernfalls entsteht genau
ein passender Review-Fall. DEFER bleibt in der Queue.

## CLI-Vertrag

`ebook-match` führt den begrenzten Workflow aus. Exitcode `0` bedeutet, dass
alle im Snapshot gefundenen Candidates innerhalb der Grenzen verarbeitet
wurden; `3` bedeutet einen sicheren bounded Zwischenstand; `2` bezeichnet
einen path-freien Vertrags- oder Persistenzfehler; `130` bleibt
`KeyboardInterrupt` vorbehalten.

`ebook-match-review-list` öffnet SQLite strikt read-only und gibt nur opake
IDs, Relation Type, Status, Confidence, Matcherversion und aggregierte
Feature-Codes/-Zähler aus. Rohwerte, Pfade, Dateinamen, Identifier und
materielle Fingerprints werden nicht ausgegeben.

`ebook-match-review-decide` hängt ACCEPT, REJECT oder DEFER an. Der Aufruf muss
die erwartete letzte Decision-ID oder ausdrücklich `NONE` angeben. Item-
Snapshot, Sequenz und Historie werden atomar optimistisch gefencet.

## Kalibrierungsgrenze

Das kontrollierte adversariale Korpus bestätigt weiterhin ausschließlich
gleiche vollständige SHA-256-Bytes automatisch. Für `SAME_EDITION` und
`SAME_WORK` bleibt automatische Confirmation deaktiviert. Eine spätere
Aktivierung benötigt eine neue Decision-Compatibility-Version und null
bekannte False Positives im erweiterten Korpus.

## Sicherheit und Aussagegrenzen

- Es wird keine `Relation`-Projektion und keine Keep-Präferenz erzeugt.
- Source Media, Calibre und private Runtime-Artefakte bleiben unverändert.
- Der Workflow verwendet kein Netzwerk und keinen Knowledge Provider.
- W10, Quarantäne, Löschung und sonstige Konsolidierung bleiben blockiert.
- Music-Matching bleibt eine spätere eigene Welle.

## Verifikation

Synthetische End-to-End-Tests prüfen repräsentantenbasierte exakte Gruppen,
Idempotenz, bibliografisches Review, path-freie Explanation, optimistisches
Decide und kompatible Entscheidungswiederverwendung. Die bestehenden
adversarial Scoring- und Blocking-Regressionen bleiben Bestandteil des Gates.
