# ADR-0047: Finaler 7-Zip-Formatlock

**Status:** Akzeptiert

**Datum:** 2026-08-20

**Geltungsbereich:** FG-A-FORMAT-LOCK, S-EBAR-02C und EBAR-05

## Kontext

[ADR-0045](ADR-0045-archive-7zip-format-lock.md) ließ den finalen Formatlock
offen, bis sowohl die vollständige Measurement-v2-Matrix als auch die
orthogonale Storage-Family-Authority entschieden sind. S-EBAR-02B2 bindet nun
40 direkte Storage-Family-/Fallzellen und 21 wertfreie Records im Profil
`archive-7zip-format-measurement/v2`. [ADR-0046](ADR-0046-archive-publication-and-storage-family.md)
entscheidet dazu `archive-signature-observer/v2` und
`archive-publication-storage-compatibility/v1`.

Ein Produktionsparser darf aus diesen Quellen keine lockerere Grammatik
ableiten. Ebenso darf ein Workflow den reviewten Acceptance-Lock nicht aus
einer neuen Messung erzeugen oder bei Drift aktualisieren.

## Entscheidung

FolioTone akzeptiert `archive-7zip-format-lock/v1` als endgültige Authority
für S-EBAR-02C und EBAR-05. Die kanonischen Artefakte sind:

- `packaging/archive/7zip-26.02/archive-format.lock.json`;
- `packaging/archive/7zip-26.02/archive-format.lock.sha256`.

Der Lock ist ASCII-kompatibles kanonisches JSON mit sortierten Schlüsseln,
kompakten Separatoren und genau einem abschließenden LF. Sein SHA-256 lautet
`4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061`.
Das Digestfeld liegt ausschließlich in der getrennten Digestdatei und ist
nicht Teil des gehashten Payloads.

### Gebundene Identitäten

Der Lock bindet exakt:

- Measurement-Profil `archive-7zip-format-measurement/v2` und SHA-256
  `da01ed9108a5ea63097cd1894aa4fbb264f658d65a833e8db3cb526180f2d266`;
- Fixture-Profil `archive-7zip-format-fixtures/v2`, Fixture-Manifest-,
  Matrix-, deterministische und kuratierte Provenienz-SHA-256;
- 7-Zip `26.02`, Image-Manifest-Digest, Commandprofil und Command-SHA-256;
- Signaturprofil `archive-signature-observer/v2`;
- Compatibility `archive-publication-storage-compatibility/v1`;
- jede gemessene Fixture-ID und Fixture-SHA-256.

Jede Änderung einer dieser Identitäten macht den Lock stale. Ein neuer
Acceptance-Lock benötigt Review, eine neue ADR und bei semantischer Änderung
eine neue Profil- oder Compatibility-Version.

### Capability- und Recordvertrag

Der Lock enthält genau 40 disjunkte Zellen aus fünf direkten Storage-Familien
`ZIP`, `RAR4`, `RAR5`, `SEVEN_Z`, `TAR` und acht Fällen. Jede Zelle trägt genau
eine Disposition:

- `MEASURED` besitzt die exakte Fixturebindung und eine oder mehrere
  geordnete Recordprojektionen;
- `FORMAT_UNSUPPORTED` besitzt ausschließlich den gepinnten
  Primärquellennachweis und keine Recordprojektion;
- `EVIDENCE_UNAVAILABLE` besitzt ausschließlich die begründete
  Evidence-Grenze und keine Recordprojektion.

Ein Record bindet jede Feldposition mit Name, Value Class und genau einer
Behandlung:

- `REQUIRED`: das Feld und seine nichtleere kanonische Value Class sind
  erforderlich;
- `EMPTY`: das Feld ist erforderlich und muss byteleer bleiben;
- `DISCARD`: das Feld ist erforderlich, wird grammatisch klassifiziert und
  sein Wert wird unmittelbar verworfen.

`optional_fields` ist in v1 für jede Zelle leer. Ein fehlendes, zusätzliches,
vertauschtes, dupliziertes oder anders klassifiziertes Feld ist kein optionaler
Drift, sondern ein fail-closed Profilfehler. Private Locator-, Linkziel- und
sonstige Discardwerte gelangen weder in DTO, Finding, Log, Digest noch
Artefakt.

Nur `MEASURED` darf einen Parserlauf und in EBAR-05 einen Listinglauf
autorisieren. `FORMAT_UNSUPPORTED`, `EVIDENCE_UNAVAILABLE`, unbekannte
Storage-Familie, unbekannter Fall oder Identitätsdrift enden vor dem ersten
Chunkverbrauch ohne fachliche Ableitung.

### Directory-, Link- und Verschlüsselungssemantik

Directory-, Encryption- und Linkstatus werden ausschließlich aus einer exakt
passenden `MEASURED`-Zelle und deren gelockten Feldklassen abgeleitet.
Insbesondere autorisiert ein positiver privater Linkwert nur die konservative
Link-/Policyprojektion; der Wert selbst bleibt verworfen.

Bei `ALL_ENCRYPTED` und `MIXED` bleiben die Member listenbar, aber EBAR-05
startet weder Integrity noch Passwortübergabe. Header-Verschlüsselung ist
nicht Teil des Locks. Nicht gemessene RAR-, Link- oder Encryptionfälle bleiben
geschlossen und werden nicht aus benachbarten Profilen interpoliert.

### Äußere Kompressionsformen

Die vier Messbeobachtungen für gzip, bzip2, xz und zstd sind vollständig im
Lock gebunden, tragen jedoch ausnahmslos:

- Storage Family `UNKNOWN`;
- Disposition `OUTER_COMPRESSION_ONLY`;
- `runtime_authorized=false`.

Sie autorisieren vor EBAR-06 weder Produktionsparser noch Listing, Integrity
oder Member-Evidence.

### Verify-only-Gate

`packaging/archive/7zip-26.02/verify_format_lock.py` ist ein reiner,
netzwerkfreier Verifier. Er rekonstruiert die erwartete Projektion nur im
Speicher aus den eingecheckten Measurement-/Fixtureartefakten und vergleicht
sie bytegenau mit Lock und Digest. Er besitzt keinen Schreib-, Update- oder
Acceptance-Modus.

Der geschützte Archive-Image-Workflow führt nach zwei identischen realen
Measurement-v2-Läufen zusätzlich diesen Verifier aus. Weder Messhelper,
Verifier noch Workflow dürfen Lock oder Digest erzeugen, ersetzen oder bei
Abweichung aktualisieren.

## Paketgrenzen

FG-A-FORMAT-LOCK ändert ausschließlich diese ADR, die maschinenlesbaren
Lockartefakte, den reinen Verifier, dessen fokussierten Test, den bestehenden
verify-only Workflow und konsistente Planungs-/Safety-/Tooldokumentation. Es
ändert keinen Runtime-, Parser-, Provider-, Runner-, Persistence-, Wrapper-,
Extraction- oder Secretcode.

S-EBAR-02C ist damit startklar und bleibt auf den in ADR-0046 festgelegten
Produktionsscope beschränkt. EBAR-05 bleibt bis zum erfolgreichen Abschluss
von S-EBAR-02C blockiert.

## Folgen

- FG-A-FORMAT-LOCK ist abgeschlossen.
- Der verworfene v1-Vorabkandidat aus ADR-0045 bleibt nicht autoritativ.
- S-EBAR-02C ist der nächste Archive-Schritt.
- Unterstützung wird nur durch neue reviewte Evidence erweitert, niemals
  durch stilles Lockern oder Workflow-Regeneration.

## Nachweise

- [ADR-0043](ADR-0043-archive-machine-output-and-status-classification.md)
- [ADR-0044](ADR-0044-archive-format-profile-measurement.md)
- [ADR-0045](ADR-0045-archive-7zip-format-lock.md)
- [ADR-0046](ADR-0046-archive-publication-and-storage-family.md)
- `tests/fixtures/archive/7zip-26.02/v2/fixture-manifest.json`
- `tests/fixtures/archive/7zip-26.02/v2/expected-measurement.json`
- `packaging/archive/7zip-26.02/archive-format.lock.json`
- `packaging/archive/7zip-26.02/archive-format.lock.sha256`
