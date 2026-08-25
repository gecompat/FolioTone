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
