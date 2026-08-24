# Registrierung dauerhafter Planungsartefakte

**Status:** verbindlich
**Geltungsbereich:** ab `WI-0001` neu angelegte, dauerhafte Planungs-, Governance-, Gate-, Risiko-, Betriebs-, Release- und Testartefakte. Domänen- und Laufzeitidentitäten von FolioTone gehören nicht zu diesem Scope.

## Authority und Adoption

FolioTone verwendet für seinen bestehenden ID-Bestand den Modus `PRESERVE`: historische IDs wie `W3-017`, `S-FUT11-03`, `FG-*`, `ADR-0068` und `OPS-001` bleiben unverändert und lesbar. Es gibt keine implizite Migration und keine Umdeutung ihrer bisherigen Syntax.

Für neue dauerhafte Planungsartefakte gilt ab `WI-0001` `ADOPT_FORWARD`. Ihre kanonische Identität besteht aus einer unveränderlichen `artifact_uid` als UUIDv7-URN und einer projektlokalen menschlichen Referenz `<PREFIX>-<SEQUENCE>`. Wave, Status, Priorität, Owner, Phase, Pfad und Milestone sind Metadaten; sie ändern die Identität nicht. Git-Commit-IDs bezeichnen Revisionen, nicht das logische Artefakt.

Die alleinige Registration Authority für diesen neuen Referenzscope ist die versionierte Registry [`artifact_registry.json`](artifact_registry.json). Sie ist für Menschen und KI identisch. Einzelne Artefakte liegen unter [`artifacts/`](artifacts/); ihre `human_ref` muss exakt auf die zugehörige Registry-Zuordnung zeigen. Alte FolioTone-ID-Scopes werden dadurch weder beansprucht noch ersetzt.

## Zuteilung

Die optionale Foundation-Capability `artifact-registration-clients` ist explizit installiert. Die gleichwertigen Python- und PowerShell-Clients unter `.ai/foundation/reference_clients/` sind die zugelassenen Clients für die Registry. Sie implementieren die Foundation-Operationen `init`, `new`, `register`, `resolve` und `validate`; ihre Übernahme macht Python nicht zur Voraussetzung für Menschen.

`DEFERRED` ist der Standard für parallele Branches, Offline-Arbeit oder unklare Serialisierung: zuerst entsteht nur die UUIDv7-URN, die finale `human_ref` wird erst durch die Authority am serialisierten Integrationspunkt vergeben. Ein temporärer Text ist keine veröffentlichte stabile Referenz.

`DIRECT` ist nur zulässig, wenn der zuständige Orchestrator die Zuteilung serialisiert: aktuelles `origin/main`, keine gleichzeitig laufende Allocation im selben Scope, exklusiv gesperrte Registry und erwartete `registry_revision`. Der Commit-/PR-Integrator prüft die Registry erneut; bei Abweichung, Konflikt oder unklarer Parallelität wird nicht geraten, sondern auf `DEFERRED` zurückgefallen oder die Registry-Auflösung vorbereitet. Reservierte Lücken werden nicht wiederverwendet.

Die aktuelle Wave nutzt `DIRECT`, weil dieser Chat der ausdrücklich beauftragte alleinige Orchestrator ist, der Ausgangscommit verifiziert wurde und keine überlappende Registry-Allocation vorlag.

## Metadaten und Beziehungen

Jede neue Artefaktdatei enthält mindestens die Felder des Foundation-Schemas: `artifact_uid`, `human_ref`, `kind`, `title` und `registration_state`. FolioTone ergänzt bei Bedarf `status`, `metadata`, `aliases`, `external_refs` und `relations`.

`metadata` enthält zum Beispiel `wave`, Risikoklasse, Tier und fachlichen Scope. Abhängigkeiten, Umsetzung, Verifikation, Supersession und Elternschaft werden als getypte `relations` modelliert. Historische oder externe IDs werden als Alias beziehungsweise externe Referenz bewahrt. Weder eine ID noch der Besitz einer Registry-Datei ist eine Autorisierung für W10, Mutation, Freigabe oder Löschung.

## Betrieb und Prüfung

Vor dem Anlegen eines dauerhaften Planungsartefakts ist diese Datei zusammen mit `.ai/foundation/PERSISTENT_IDENTITY_POLICY.md` und `.ai/foundation/ARTIFACT_REGISTRATION_POLICY.md` zu lesen. Die Root-`AGENTS.md` verweist auf diesen Einstieg.

Die statischen Verträge prüfen Registry, Schema, eindeutige Zuordnung, registrierte Referenz und die Discovery-Kette. Der Foundation-Validator prüft zusätzlich nur `FOUNDATION_INTEGRITY`. Tatsächliche konkurrierende Allocation, GitHub-PR-Serialisierung und Recovery bleiben `RUNTIME_EMPIRICAL`-Nachweise und werden nicht durch einen grünen Schema-/Static-Test behauptet.
