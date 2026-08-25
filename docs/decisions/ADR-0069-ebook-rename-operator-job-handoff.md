# ADR-0069: Gebundene Jobübergabe für den E-Book-Rename

- Status: Accepted
- Datum: 2026-08-24

## Kontext

ADR-0067 trennt `surface-api` und `operator-worker`. Der Webprozess besitzt
weder Source-Media-Mount noch W10-Capability-Datei. Nur der netzlose
`operator-worker` darf den durch ADR-0066 begrenzten Same-Parent-
`FILE_RENAME` ausführen.

Der bestehende CLI-Weg prüft die exakte zweite Bestätigung
`CONFIRM EBOOK RENAME <Authorization-ID>` und ruft anschließend den
`EbookRenameOperatorService` im selben Prozess auf. Für die Browseroberfläche
muss diese Bestätigung eine Prozessgrenze überqueren. Der Klartext darf laut
ADR-0067 weder persistiert noch in einen `ApplicationJob`-Envelope geschrieben
werden. Eine generische Command-Payload oder ein direkter Executor-Aufruf aus
dem Webprozess würde die Prozess- und W10-Grenzen verletzen.

## Entscheidung

`S-FUT11-04` führt ausschließlich den operation-spezifischen Vertrag
`ebook-rename-operator-job/v1` ein. `AUTHORIZE`, `EXECUTE` und `RECOVER` sind
getrennte feste Command-Profile. Der Job enthält keine freie Commandzeile,
keinen Pfad, keinen Locator, keinen Basename, keine Capability-Inhalte und
keine generische JSON-Payload.

Die API akzeptiert die Raw Confirmation ausschließlich im begrenzten JSON-
Body des `EXECUTE`-Requests. Sie prüft den Text mit dem vorhandenen Vertrag
`ebook-file-rename-confirmation/v1` gegen die exakte immutable
`EbookRenameAuthorizationSnapshot`. Danach wird der Klartext verworfen. Er
erscheint weder in Persistenz, Job-Envelope, Audit, Log, URL, Fehlerantwort
noch Response.

Persistiert wird ausschließlich der bereits definierte domänengetrennte
Confirmation-Digest zusammen mit:

- Command-Profil und `ApplicationJob`-ID;
- Plan-ID und vollständigem Plan-Content-Hash;
- Authorization-ID für `EXECUTE`;
- Capability-ID als opaque Binder;
- Run-ID für `RECOVER`;
- Actor-, Idempotency-, Erzeugungs- und Fencing-Bindern aus ADR-0067.

Eine additive operation-spezifische Tabelle speichert den immutable
Command-Binder. Ein getrenntes insert-only Result bindet höchstens die
erzeugte Authorization- oder Run-ID und den festen Outcome an den Job. Form-
und Immutability-Constraints verhindern unzulässige Feldkombinationen,
Update, Delete und eine Umdeutung des Command-Profils.

Proposal, Review und Plan erhalten vor ihrer fachlichen Mutation einen
separaten actor-, Command- und semantisch-inputgebundenen Receipt-Binder. Ein
gleicher Key liefert nach Abschluss die gespeicherte pfadfreie Antwort; ein
abweichender Input wird abgewiesen. Ein noch nicht abgeschlossener Binder
bleibt fail-closed und verhindert insbesondere einen zweiten append-only
Review-Entscheid. Der Binder speichert weder Raw Confirmation noch Locator.

## Worker- und W10-Vertrag

Der `operator-worker` besitzt eine feste Allowlist genau dieser drei Profile.
Er löst Capability- und Dependency-Scope-Konfiguration ausschließlich in
seinem Prozess auf. Vor `EXECUTE` rekonstruiert er aus der exakten
Authorization den erwarteten Confirmation-Digest und vergleicht ihn in
konstanter Zeit mit dem Job-Binder.

Ein passender Digest öffnet allein keine Mutation. Gleichzeitig erforderlich
bleiben:

1. der aktive, auf `OPERATE` begrenzte und höchstens 15 Minuten gültige Grant;
2. die vorhandene gültige One-use-W10-Authorization;
3. exakte Plan-, Plan-Content-Hash- und Capability-Binder;
4. eine frische Joblease und das autoritative `ScanRootWriteLease`-/W10-Fence;
5. alle ADR-0066-Revalidierungen, das Journal, die unmittelbare physische
   Verifikation, der Folgescan und die Reconciliation.

Die Joblease ersetzt keine dieser Bedingungen. Nach einer möglichen
irreversiblen Grenze wird ein abgelaufener oder verlorener Job nicht erneut
als neuer Execute-Job ausgeführt. Der Worker setzt ausschließlich denselben
W10-Run fort oder verweist auf dessen Status-/Recoveryweg.

## API- und Prozessgrenzen

`surface-api` darf Proposal, Private Preview, Review und Plan über die
gemeinsame Application-Grenze bedienen und Operator-Jobs anlegen. Für
`Proposal` darf er ausschließlich die bereits durch ADR-0066 definierte,
owner-only geschützte `FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE` lesend
auflösen. Die Datei enthält keine Collection-Pfade, Capabilities oder freien
Befehle; der bestehende Resolver prüft Größe, reguläre Datei, Linkfreiheit,
Owner und Modus fail-closed. Diese Ausnahme gilt weder für Capability- noch
Source-Media-Konfiguration und nicht für Authorize, Execute oder Recover.
Der `operator-worker` löst denselben Scope bei Authorize erneut auf; fehlende,
mehrdeutige oder materiell abweichende Scope-Lineage blockiert die
Autorisierung. Authorize, Execute und Recover werden niemals im API-Prozess
ausgeführt.

Der `surface-api` und der `analysis-worker` behalten read-only beziehungsweise
keinen Source-Media-Mount und erhalten keine Rename-Capability-Datei. Nur der
`operator-worker` erhält `network=none`, die owner-geschützte Rename- und
Dependency-Scope-Konfiguration sowie den für ADR-0066 erforderlichen engsten
beschreibbaren Mount. Das Compose-Profil verlangt dafür ohne Default
`FOLIOTONE_EBOOK_RENAME_WRITABLE_ROOT`; der Startoperator setzt ihn auf genau
den in der einen Capability gebundenen `ScanRoot`, nie auf eine Sammlung oder
einen übergeordneten Medienpfad. Ein anderer Mount ist eine fail-closed
Startkonfigurationsabweichung, keine Ausführungsoption.

## Aussagegrenze

Der Confirmation-Digest ist eine immutable Bindung und ein Auditnachweis,
kein Secret und keine unabhängige kryptografische Benutzerunterschrift. Ein
Angreifer, der den API-Prozess und dessen Schreibzugriff auf die lokale
Jobpersistenz vollständig kontrolliert, kann die Behauptung einer erfolgten
UI-Bestätigung nachbilden. Die weiterhin getrennte Capability-Auflösung,
W10-Authorization, Revalidierung, Fencing, Verifikation und Recovery begrenzen
den ausführbaren Scope auf den bereits reviewten einen Rename, beweisen aber
nicht unabhängig die menschliche Eingabe.

Soll ein späteres Threat Model auch einen vollständig kompromittierten
Webprozess als nicht vertrauenswürdigen Freigabevermittler behandeln, ist vor
der Implementierung ein getrenntes owner-lokales Out-of-band- oder IPC-
Freigabeprotokoll durch eine neue ADR zu entscheiden. Dieser stärkere Vertrag
ist nicht Bestandteil von `local-single-operator/v1`.

## Folgen

- `S-FUT11-04` kann ohne persistierte Raw Confirmation und ohne direkten
  Sourcezugriff des Webprozesses implementiert werden.
- Der bestehende CLI-Vertrag bleibt unverändert und verwendet weiterhin die
  exakte nicht geloggte `stdin`-Bestätigung.
- Ein allgemeiner Operator-Command, eine freie Payload, automatische W10-
  Retries und weitere Writer bleiben unzulässig.
- Titelwrite, Quarantäne und alle anderen Operationen benötigen weiterhin
  getrennte Produktoberflächen-Waves.

## Verwandte Entscheidungen

- `ADR-0027-scan-root-write-lease-and-fencing.md`
- `ADR-0065-non-executable-ebook-operation-recipes.md`
- `ADR-0066-bounded-ebook-file-rename.md`
- `ADR-0067-local-single-operator-product-surface.md`
