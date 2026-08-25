# DEC-0001: Book-only Fixity Monitoring mit expliziter Baseline

- Status: Accepted
- Datum: 2026-08-25
- Artefakt: `urn:uuid:01a037f5-a629-7026-8df2-78faaa6b73c2`
- Umsetzung: `WI-0003`

## Kontext

Persistierte `FILE_SHA256`-Fingerprints belegen die Bytes einer bestimmten
`FileObservation` und unterstützen Duplicate Evidence. Sie sind keine
akzeptierte, zeitübergreifende Fixity-Baseline. `Library Health` kann fehlende
oder widersprüchliche Full-SHA-256-Evidence anzeigen, behauptet aber weder
Bit Rot noch eine Ursache für eine Änderung.

FolioTone benötigt deshalb einen getrennten, ausschließlich lesenden
Fixity-Vertrag. Eine unerwartete Byteänderung ist ein überprüfbarer Befund,
aber keine Kausalitäts-, Identity- oder Mutationsentscheidung.

## Entscheidung

`WI-0003` implementiert die Profile:

```text
ebook-fixity-baseline/v1
ebook-fixity-verification/v1
ebook-fixity-decision/v1
```

Eine Baseline gilt für genau einen als E-Book-Root registrierten `ScanRoot`.
Ihre Erstellung bindet den neuesten abgeschlossenen `ScanRun` und alle darin
aktuell `PRESENT` beobachteten regulären Dateien. Jeder Baseline-Eintrag bindet
opaque File-/Observation-Identität, erwartete Größe, vollständigen SHA-256 und
einen privaten relativen Locator. Absolute Pfade werden weder persistiert noch
projiziert.

Der Baseline-Draft streamt jede Datei vollständig und verwendet weder Größe
und Modified-Zeitpunkt noch einen bereits persistierten Fingerprint als
aktuellen Bytebeweis. Der Draft ist höchstens 15 Minuten gültig. Er wird erst
durch die exakte, begrenzte und nicht geloggte Eingabe

```text
ACCEPT FIXITY BASELINE <manifest-id>
```

aktiviert. Der Klartext wird verworfen; ein Baseline-Draft, seine Aktivierung
und spätere Entscheidungen bleiben append-only. Es gibt keinen impliziten
Trust-on-first-use und keinen Root-weiten Reset einer bestehenden Baseline.

## Verifikation und Entscheidungen

Eine Verifikation liest sämtliche gebundenen Bytes erneut. Pro Eintrag sind
genau diese fachlichen Ergebnisse zulässig:

```text
VERIFIED
UNEXPECTED_BYTE_CHANGE
MISSING
UNBASELINED
UNREADABLE
SOURCE_CHANGED_DURING_RUN
```

Ein nicht erreichbarer oder unvollständig lesbarer Root, ein laufender
`ScanRun`, verlorenes Fencing oder ein unsicherer Locator beendet den Lauf
fail-closed. Ein solcher Lauf darf keine falschen `MISSING`-Findings und keine
teilweise als vollständig dargestellte Verifikation erzeugen.

Spätere erwartete Änderungen werden nur einzeln entschieden:

```text
ACCEPT_CURRENT
RETIRE_MISSING
```

`ACCEPT_CURRENT` erzeugt für genau eine geänderte oder neue Datei einen neuen
erwarteten Bytezustand. `RETIRE_MISSING` bestätigt genau eine erwartete
Entfernung. Beide Entscheidungen benötigen eine aktuelle Review-Lineage und
ersetzen weder Identity Evidence noch eine W10-Authorization. Bulk-Accept,
automatische Akzeptanz und Root-weite Reinitialisierung sind nicht Teil von
Version 1.

## Festgelegter Verifikations- und Reviewvertrag

Der Verifikationslauf bindet den neuesten `ScanRun` insgesamt für den
betroffenen, gefenceten E-Book-`ScanRoot`; dieser Lauf muss `COMPLETED` sein.
Ein neuerer `RUNNING`-, `FAILED`- oder `INTERRUPTED`-Lauf blockiert den Start,
statt auf einen älteren Snapshot zurückzufallen. Der gebundene Snapshot und
der zu Laufbeginn aktive erwartete Zustand bleiben für den gesamten Lauf
unverändert.

Die Baseline-Aktivierung mit ihren exakten Entries bildet die initiale
Erwartungsrevision `0`; sie benötigt keinen nachträglichen Rewrite. Jede
spätere Einzelentscheidung erhöht eine rootlokale Revisionssequenz genau um
eins und verkettet ihren Digest mit Aktivierung und Vorgänger. Ein
Verifikationslauf bindet Revisionsnummer und -Digest, nicht nur eine
veränderliche Projektion des neuesten Zustands.

Die Ergebnismenge ist genau die Vereinigung aus allen im gebundenen Snapshot
aktuellen `PRESENT`-Dateien und allen dort nicht mehr `PRESENT` vorhandenen,
aktiven Erwartungen. Eine `PRESENT`-Datei ohne aktive Erwartung ist
`UNBASELINED`. Eine aktive Erwartung ohne `PRESENT`-Datei im Snapshot ist
`MISSING`. Dateien, die erst nach dem gebundenen Scan entstehen, liegen
außerhalb dieses Laufs und werden erst nach einem neuen abgeschlossenen Scan
sichtbar. Die Verifikation startet weder einen Scan noch eine eigene
Filesystem-Discovery.

`UNREADABLE` bezeichnet genau eine bekannte reguläre Datei, deren aktueller
relativer Locator innerhalb eines ansonsten vollständig erreichbaren Roots
sicher aufgelöst wurde, deren Bytes aber nicht vollständig gelesen werden
konnten. `SOURCE_CHANGED_DURING_RUN` bezeichnet eine während des frischen
Reads veränderte einzelne Source. Kann der Root selbst nicht sicher geöffnet
oder seine Snapshot-Coverage nicht hergestellt werden, geht das Fencing
verloren oder ist ein Locator unsicher, endet dagegen der gesamte Lauf
`FAILED`. Ein solcher Lauf darf keine falschen `MISSING`-Ergebnisse erzeugen.
Partielle Ergebnisse bleiben ausschließlich unter diesem immutable
fehlgeschlagenen Lauf nachvollziehbar und sind keine Review-Candidates. Nur
ein Lauf mit exakt einem Ergebnis für jedes Element der gebundenen
Vereinigungsmenge wird `COMPLETED`.

Die vorhandene generische append-only Review-Domäne wird um die feste Paarung
`ReviewType.FIXITY_EXPECTATION` und
`ReviewCandidateKind.FIXITY_RESULT` erweitert; es entsteht kein zweiter
Fixity-Review-Ledger. Das Review-Subject ist genau
`EntityKind.FILE` mit der betroffenen `file_id`. `candidate_id` bezeichnet
genau ein immutable persistiertes Ergebnis eines `COMPLETED`-
`FixityVerificationRun`; die Candidate-Menge besteht ausschließlich aus
diesem Ergebnis. Das Kompatibilitätsprofil ist exakt
`ebook-fixity-decision/v1`.

### Kanonische Fingerprints

Alle folgenden Payloads verwenden `canonical-json/v1` und werden als UTF-8
mit SHA-256 gehasht. Die genannten Felder sind geschlossen: kein Feld darf
ergänzt oder ausgelassen werden. Nicht vorhandene fachliche Werte werden als
JSON-`null` codiert; IDs, Enums und Digests sind Strings, Bytegrößen und
Revisionsnummern JSON-Integer. Eine semantische Änderung benötigt ein neues
Profil.

Der `result_content_digest` bindet exakt dieses Objekt:

```text
profile = ebook-fixity-result/v1
result_type
file_id
expected = {observation_id, size_bytes, sha256, relative_locator}
current = {observation_id, size_bytes, sha256, relative_locator}
failure_code
```

Die beiden Zustandsobjekte sind immer vorhanden; jedes ihrer Felder kann
`null` sein. Ein privater relativer Locator fließt nur in diesen internen
Digest ein und wird nicht im Fingerprint-Payload oder in einer
Standardprojektion offengelegt.

Der `evidence_fingerprint` bindet exakt dieses Objekt:

```text
profile = ebook-fixity-evidence-fingerprint/v1
review_type = FIXITY_EXPECTATION
subject_kind = FILE
subject_id = <file_id>
scan_root_id
baseline_activation_id
expectation_revision_no
expectation_revision_digest
scan_run_id
verification_run_id
verification_run_content_digest
result_id
result_content_digest
decision_compatibility_version = ebook-fixity-decision/v1
```

Der `candidate_set_fingerprint` bindet exakt dieses Objekt:

```text
profile = ebook-fixity-candidate-set-fingerprint/v1
candidate_kind = FIXITY_RESULT
candidates = [{result_id, result_content_digest}]
decision_compatibility_version = ebook-fixity-decision/v1
```

`candidates` enthält genau dieses eine Element. Der technische
`producer_version` wird entsprechend ADR-0028/ADR-0031 gespeichert, aber nicht
in diese Reuse-Fingerprints aufgenommen; eine semantische Änderung muss das
Kompatibilitätsprofil erhöhen. Eine neue Verifikation, eine geänderte aktive
Erwartung oder eine Abweichung eines genannten Binders macht die alte
Review-Lineage unbrauchbar. Nur die neueste, exakt kompatible generische
`ACCEPT`-Decision darf eine fachliche Einzelentscheidung autorisieren;
`REJECT` und `DEFER` ändern keinen erwarteten Zustand.

`ACCEPT_CURRENT` ist ausschließlich für `UNEXPECTED_BYTE_CHANGE` und
`UNBASELINED` zulässig und übernimmt die frisch beobachtete Größe, den
Full-SHA-256, die Observation-Identität und den privaten relativen Locator des
Ergebnisses. `RETIRE_MISSING` ist ausschließlich für `MISSING` zulässig und
erzeugt einen Tombstone für genau eine aktive Erwartung. `VERIFIED`,
`UNREADABLE` und `SOURCE_CHANGED_DURING_RUN` sind keine
Entscheidungs-Candidates. Jede erfolgreiche fachliche Entscheidung ergänzt
genau eine neue append-only Erwartungsrevision. Exakt gleiche Retries sind
idempotent; ein abweichender Retry mit derselben Idempotenzidentität wird
abgewiesen. Bulk-Accept, automatische Akzeptanz und Root-weite
Reinitialisierung bleiben ausgeschlossen.

Der nächste Slice ergänzt dafür eine additive Persistenzmigration mit
immutable Verifikationsläufen, gapless Events, Ergebnissen und
Erwartungsrevisionen, erweitert die geschlossenen generischen Review-Literale
und ergänzt den Lease-Owner `EBOOK_FIXITY_VERIFICATION`. Er enthält noch keine
Application-, CLI-, REST- oder Browserpfade.

## Prozess- und Privacy-Grenze

Baseline und Verifikation laufen ausschließlich als manuell gestartete,
persistente `ApplicationJob`-Profile im `analysis-worker`. Ein eigener
rootweiter Lease-Owner fenced Scan, Hash-, Analyse- und Fixity-Writer
gegeneinander. Es laufen höchstens zwei Hash-Worker; Reads und Persistenz sind
streaming- beziehungsweise keyset-basiert und bounded.

CLI und Browser verwenden dieselben Application-Verträge. Standardprojektionen
enthalten keine Pfade, relativen Locator, Hashwerte oder privaten
Metadatenwerte. Relative Locator sind ausschließlich unter `/api/v1/private`
mit `PRIVATE_READ` und `Cache-Control: no-store` sichtbar. Baseline-Aktivierung,
`ACCEPT_CURRENT` und `RETIRE_MISSING` benötigen Passwort-Reauthentisierung,
einen höchstens 15 Minuten gültigen `REVIEW`-Grant, CSRF und
`Idempotency-Key`. `OPERATE`, W10-Capabilities, Source Writes, Netzwerkzugriff,
automatische Nach-Scan-Starts und Zeitplanung bleiben ausgeschlossen.

## Liefergrenze

`WI-0003` wird in getrennten Pull Requests geliefert: zuerst immutable
Baseline-Verträge und Persistenz, danach Verifikation und Einzelentscheidungen,
zuletzt Application-/CLI-/REST-/Browser-Surface. Backup-/Replica-Vergleich,
Restore, automatische Planung und Source-Mutation benötigen eigene spätere
Entscheidungen.
