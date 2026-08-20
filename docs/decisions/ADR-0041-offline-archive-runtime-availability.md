# ADR-0041: Offline prüfbare Verfügbarkeit des Archive-Runtime-Images

- Status: Accepted
- Datum: 2026-08-20

## Kontext

ADR-0040 und S-EBAR-03 binden das reproduzierbare
`linux/amd64`-Runtime-Image an den Plattform-Manifest-Digest
`sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287`.
Der Repository-Lock besitzt den Status `BOOTSTRAP_LOCKED`; der geschützte
Workflow kann das identische Manifest publizieren und ein Custom-SLSA-v1-
Predicate sowie eine SPDX-2.3-Attestation anhängen.

`archive_7zip_runtime_availability()` bleibt trotzdem absichtlich
`TOOL_UNAVAILABLE`. Der Bootstrap-Lock beweist Reproduzierbarkeit, nicht die
geschützte Publikation, Attestation oder lokale Provisionierung. Ein lokales
`docker image inspect` beweist weder die akzeptierte Release-Lineage noch die
Custom-SLSA- und SPDX-Attestations. EBAR-04 darf diese beiden Teilbefunde daher
nicht zu einer Runtime-Authority zusammensetzen.

GitHub dokumentiert die Offline-Verifikation von Artifact Attestations über
lokale Bundles, `trusted_root.jsonl` und `gh attestation verify`. Das
Trust-Root-Material besitzt keine eingebaute Ablaufzeit. Offline kann außerdem
keine nach dem letzten Import erfolgte Revocation erkannt werden. Das lokale
GitHub-CLI-Binary ist im FolioTone-Rezept weder versions- noch
digestgebunden. Ein ungeprüftes System-`gh` als Runtime-Verifier würde deshalb
lediglich eine neue, rekursive Tool- und Trust-Root-Lücke eröffnen.

Die Runtime benötigt folglich einen kleineren Vertrag: Eine kontrollierte
Online-Provisionierung sammelt und prüft die externen Fakten genau einmal.
Danach autorisiert eine reviewte FolioTone-Releasequelle exakt diese Evidence.
Jeder Archive-Lauf kann die akzeptierten Bytes und die lokale Imageidentität
ohne Netzwerk erneut kryptografisch prüfen.

## Entscheidung

FG-A-RUNTIME-AVAILABILITY ist akzeptiert. Vor EBAR-04 wird das eigenständige
Paket `S-EBAR-03A` eingefügt. Es implementiert den Release-Acceptance-,
Provisioning- und Offline-Verifikationsvertrag dieses Dokuments vollständig.
Bis dieses Paket abgeschlossen und eine konkrete Releasegeneration explizit
provisioniert ist, bleibt `archive-linux-container-runner/v1`
`TOOL_UNAVAILABLE`.

Die Runtime-Trust-Root ist ein mit Review in die vertrauenswürdige FolioTone-
Source übernommener `archive-runtime-release/v1`-Record. Weder ein Boolean im
Bootstrap-Lock noch eine ungeprüfte Runtime-Signaturprüfung autorisiert die
Ausführung. Die aufgenommenen Attestation-Bundles und das Trust-Root-Snapshot
bleiben durch SHA-256 unveränderlich an den Record gebunden und auditierbar.
Ihre kryptografische GitHub-/Sigstore-Prüfung gehört zum kontrollierten
Provisioning und Release Review, nicht zu jedem Archive-Lauf.

Ein eigener kryptografischer Runtime-Verifier mit `gh`, Sigstore oder einer
Cryptography-Bibliothek ist durch diese ADR nicht autorisiert. Soll er später
die reviewte FolioTone-Source als Trust-Root ersetzen oder ergänzen, benötigt
er zuerst ein separates Frontier-Gate für exakte Version, Distributionsbytes,
Digest, Lizenz, eigene Provenance, Trust-Root-Akquisition und Updatevertrag.

## Autoritätskette

Die zulässige Kette lautet:

```text
geschützter main-Publish und GitHub Artifact Attestations
    -> kontrollierte Online-Prüfung und Evidence-Akquisition
    -> reviewter archive-runtime-release/v1 in vertrauenswürdiger FolioTone-Source
    -> explizite lokale Erstprovisionierung mit immutable Runtime-State
    -> pro Lauf: Offline-Evidence-, OCI- und Docker-Store-Revalidierung
    -> AVAILABLE oder fail-closed TOOL_UNAVAILABLE
```

Nicht zulässig ist:

```text
BOOTSTRAP_LOCKED + docker image inspect -> AVAILABLE
```

Auch ein erfolgreiches lokales `7zzs i` ist nur eine spätere Toolprobe und
keine Supply-Chain-Authority.

## Geschlossener Release-Acceptance-Record

`archive-runtime-release/v1` ist kanonisches UTF-8-JSON mit lexikografisch
sortierten Objektschlüsseln, finalem LF, ohne absolute Pfade und ohne
Credentials. Unbekannte, fehlende, doppelte oder falsch typisierte Felder sind
ungültig. Der Record enthält exakt folgende Bindungen; die hier eingerückten
Gruppen sind geschlossene JSON-Objekte mit den genannten Feldnamen:

```text
profile = archive-runtime-release/v1
state = RELEASE_ACCEPTED
generation = positive monotone integer
release_id = domain-separierter SHA-256 des kanonischen Records ohne release_id
accepted_at = UTC
offline_not_after = UTC, höchstens 90 Tage nach accepted_at

repository = gecompat/FolioTone
repository_id = 1328118830
repository_owner_id = 48807214
repository_commit = beobachteter finaler 40-stelliger lowercase Commit
source_ref = refs/heads/main
workflow_path = .github/workflows/archive-image.yml
workflow_ref = refs/heads/main
workflow_invocation_id = exakter geschützter Run und Attempt
runner_environment = github-hosted
oidc_issuer = https://token.actions.githubusercontent.com
signer_workflow = gecompat/FolioTone/.github/workflows/archive-image.yml
signer_digest = repository_commit
deny_self_hosted_runners = true

action_identities:
  actions/attest = daf44fb950173508f38bd2406030372c1d1162b1
  actions/attest-sbom = 4651f806c01d8637787e274ac3bdf724ef169f34
  actions/checkout = 11bd71901bbe5b1630ceea73d27597364c9af683
  actions/setup-python = a26af69be951a213d495a4c3e4e4022e16d87065

image_repository = ghcr.io/gecompat/foliotone-archive-7zip
platform = linux/amd64
runtime_platform_manifest_digest = sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287
runtime_platform_manifest_size_bytes = 838
runtime_config_digest = sha256:6158a13f41ad2915237fc917abb28a7be373abf060402988898cd85bcd565b9f
runtime_config_size_bytes = 1185
runtime_rootfs_layer_digest = sha256:ab909aa86586a73ab10913d9662146ae2442e5ce4b74842b54f0984dd18aad4f
runtime_rootfs_layer_size_bytes = 3298569
runtime_rootfs_diff_id = sha256:b2af5e745f24985c459fd49b2191807b36364540d53d472db3620e0b4cfc024e
runtime_workdir_layer_digest = sha256:4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1
runtime_workdir_layer_size_bytes = 32
runtime_workdir_diff_id = sha256:5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef

archive_image_lock_sha256 = 6fe5a1bc5f2f247d00ee47b75f3d8405a0aa99567ebc2e1a9b556fc7c3782db1
archive_image_spdx_sha256 = ce32dada7227c05e147280404b3d0ce0304eba5e6e085c644f7ac4cb0ddf5a9f
custom_slsa_predicate_type = https://slsa.dev/provenance/v1
custom_slsa_bundle_sha256
custom_slsa_statement_sha256
custom_slsa_predicate_sha256
custom_slsa_certificate_sha256
custom_slsa_verified_timestamp
spdx_predicate_type = https://spdx.dev/Document/v2.3
spdx_bundle_sha256
spdx_statement_sha256
spdx_certificate_sha256
spdx_verified_timestamp
trusted_root_snapshot_sha256
revocation_policy_profile = archive-runtime-revocations/v1
minimum_revocation_generation
```

Noch nicht beobachtete Commit-, Invocation-, Bundle-, Statement-, Predicate-
oder Trust-Root-Digests werden nicht erfunden. Ein Pending-, Null-, Platzhalter-
oder `UNVERIFIED`-Wert kann niemals `RELEASE_ACCEPTED` sein.

## Verbindliche Attestation- und Identity-Claims

Die kontrollierte Acceptance prüft für Custom SLSA und SPDX jeweils genau
einen für die Releasegeneration ausgewählten, kryptografisch verifizierten
GitHub-Attestation-Bundle. Mehrere gefundene Bundles werden nicht still
zusammengeführt; der ausgewählte Bundle-Digest steht im Record.

Für beide Attestations müssen Zertifikat und Verifikationspolicy mindestens
folgende Identity binden:

```text
OIDC issuer = https://token.actions.githubusercontent.com
repository = gecompat/FolioTone
source ref = refs/heads/main
source digest = repository_commit
signer workflow = gecompat/FolioTone/.github/workflows/archive-image.yml
signer digest = repository_commit
self-hosted runner = forbidden
subject name = ghcr.io/gecompat/foliotone-archive-7zip
subject digest = runtime_platform_manifest_digest
```

Das Custom-Predicate verwendet exakt
`https://slsa.dev/provenance/v1`. Sein
`buildDefinition.buildType` ist
`https://actions.github.io/buildtypes/workflow/v1`.
`externalParameters.workflow` bindet Repository, `refs/heads/main` und den
Workflowpfad. `internalParameters.github` bindet `push`, die beiden numerischen
Repository-IDs und `github-hosted`. `runDetails.builder.id` bindet denselben
Workflow auf `refs/heads/main`; `runDetails.metadata.invocationId` bindet den
ausgewählten Run und Attempt. Der erste `resolvedDependencies`-Eintrag bindet
`git+https://github.com/gecompat/FolioTone@refs/heads/main` an
`repository_commit`.

Die Action-Identitäten bleiben exakt:

```text
actions/attest = daf44fb950173508f38bd2406030372c1d1162b1
actions/attest-sbom = 4651f806c01d8637787e274ac3bdf724ef169f34
actions/checkout = 11bd71901bbe5b1630ceea73d27597364c9af683
actions/setup-python = a26af69be951a213d495a4c3e4e4022e16d87065
```

`internalParameters.archiveImage`, Builderidentitäten, Lock-, Dockerfile-,
RootFS-, SBOM-, Upstream- und Lizenzidentitäten sowie die geordneten Manifest-,
Config-, Layer- und `diff_id`-Byproducts müssen vollständig dem Lock und
ADR-0040 entsprechen. Ein Feldvergleich nur des Subjects oder Predicate-Typs
reicht nicht.

Die SPDX-Attestation verwendet exakt
`https://spdx.dev/Document/v2.3`. Ihr Predicate ist byteinhaltlich die durch
`archive_image_spdx_sha256` gebundene `archive-image.spdx.json`; Subject und
Zertifikatsidentity entsprechen der Custom-SLSA-Attestation.

## Kontrollierte Online-Provisionierung

Provisionierung ist ein expliziter administrativer Vorgang und kein
Seiteneffekt eines Scans, Resumes oder Archive-Jobs. Sie darf Netzwerk
verwenden und muss vor Erstellung des lokalen Runtime-State mindestens:

1. den `RELEASE_ACCEPTED`-Record und alle gebundenen Evidence-Dateien gegen
   ihre SHA-256-Werte und die geschlossene Semantik prüfen;
2. das Manifest ausschließlich per exaktem Digest beziehen und den
   Registry-Body, Medientyp, Größe, Config und beide Layer prüfen;
3. Public Visibility und Source-Association mit `gecompat/FolioTone` prüfen;
4. Custom-SLSA- und SPDX-Attestation gegen die oben genannten Zertifikats-,
   Workflow-, Source-, Subject- und Predicate-Claims prüfen;
5. Bundle- und Trust-Root-Bytes unverändert übernehmen und hashen;
6. das Image unter seiner Digestreferenz lokal laden, ohne Tag als Authority;
7. das lokale OCI-Layout mit dem bestehenden strikten Inspector vollständig
   revalidieren;
8. Docker Image-ID, Config und `RootFS.Layers` gegen dieselbe Identität prüfen;
9. die aktuelle Revocation-Generation prüfen;
10. den lokalen Runtime-State erst danach atomar neu anlegen.

Der GitHub-CLI-Output darf als unterstützende Provisioning-Evidence dienen,
aber ein ungepinntes `gh` ist nicht die akzeptierende Authority. Der reviewte
Release-Record in der vertrauenswürdigen FolioTone-Source autorisiert die exakt
gehashten Evidence-Bytes. Provisioning speichert weder Token noch
Authorization-Header, Docker-Credentials, Raw-API-Antworten oder private Pfade
im Record.

## Lokaler Runtime-State und Administratorgrenze

Der nicht versionierte Runtime-State liegt unter einem explizit
konfigurierten privaten Trust-State-Root außerhalb jedes `ScanRoot`. Er wird
bei der Erstprovisionierung mit neuem privaten Verzeichnis atomar erzeugt und
enthält nur:

```text
profile = archive-runtime-local-state/v1
release_id
release_generation
release_record_sha256
highest_revocation_generation
provisioned_at
highest_observed_utc
runtime_platform_manifest_digest
runtime_config_digest
ordered_rootfs_diff_ids
```

Fehlender, beschädigter, unvollständiger oder bereits vorhandener
uneindeutiger Erstprovisionierungs-State ist `TOOL_UNAVAILABLE`. Ein Refresh
schreibt eine neue Generation zunächst vollständig, fsynct Datei und Parent
und ersetzt danach den vorherigen State atomar. Partielle Zustände werden nie
akzeptiert.

Jeder Availability-Preflight hält eine exklusive State-Sperre. Eine kleinere
Release- oder Revocation-Generation als der höchste lokal beobachtete Wert ist
ein Rollback und damit `TOOL_UNAVAILABLE`. Liegt die aktuelle UTC mehr als
300 Sekunden vor `highest_observed_utc`, gilt dies ebenfalls als Clock
Rollback. Nach erfolgreicher Prüfung wird `highest_observed_utc` monoton und
atomar fortgeschrieben.

Diese Regeln behaupten keinen Schutz gegen einen lokalen Administrator, der
Programm, Image-Store, Clock und gesamten Trust-State gemeinsam manipuliert
oder zurücksetzt. Der lokale Administrator ist eine ausdrückliche Trust-
Grenze. Es gibt in v1 keinen TPM-, Secure-Boot-, Remote-Attestation- oder
Hardware-Antirollback-Nachweis.

## Per-Run-Offline-Verifikation

Jeder Containerstart ruft den Availability-Preflight erneut auf. Der
Preflight muss technisch ohne DNS, Socket, Registry, GitHub API, Credentials,
Cookies oder Docker Pull funktionieren. Er akzeptiert nur:

- den geschlossenen `RELEASE_ACCEPTED`-Record;
- die exakt gehashten Custom-SLSA-, SPDX- und Trust-Root-Evidence-Dateien;
- einen gültigen, nicht abgelaufenen lokalen State derselben Generation;
- eine nicht rückläufige lokale Revocation-Policy ohne Treffer;
- das lokal provisionierte OCI-Layout mit der vollständigen Manifest-,
  Config-, Layer-, `diff_id`-, History-, File- und RootFS-Prüfung aus
  ADR-0040;
- das lokal vorhandene Docker-Image unter
  `ghcr.io/gecompat/foliotone-archive-7zip@sha256:26c9c2...a8287`.

Die lokale Docker-Prüfung verlangt mindestens:

```text
RepoDigest enthält exakt die erwartete Digestreferenz als Startreferenz
Id = runtime_config_digest
Architecture = amd64
Os = linux
Config.User = 65532:65532
Config.Entrypoint = [/usr/local/bin/7zzs]
Config.WorkingDir = /workspace
Config.Env = [PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin]
Config.Labels = {org.opencontainers.image.source: https://github.com/gecompat/FolioTone}
Config.Cmd = null
RootFS.Type = layers
RootFS.Layers = [runtime_rootfs_diff_id, runtime_workdir_diff_id]
```

Tags, `docker pull`, Registry-Resultate, ein anderer Image-Name, ein bloßer
`RepoDigest`, eine allein passende Config oder ein allein passendes RootFS
genügen nicht. Der strikte lokale OCI-Inspector bindet zusätzlich den
Manifestdigest, die komprimierten Layerdigests und -größen, die Configgröße,
History, das leere `WORKDIR`-Layer und den vollständigen allowlist-basierten
RootFS-Inhalt. Docker Inspect bindet diesen geprüften Content an das tatsächlich
vom Runner auswählbare lokale Image.

Public Visibility und Source-Association werden nicht bei jedem Lauf erneut
abgerufen. Sie sind Distributions- und Provisioning-Gates, keine Eigenschaft
der bereits provisionierten lokalen Bytes. Ein Per-Run-Netzwerkzwang würde den
local-first- und `network=none`-Vertrag ohne zusätzliche Laufzeitsicherheit für
das lokale Image verletzen.

## Rotation, Revocation und Offline-Fenster

Eine Releasegeneration ist höchstens 90 Tage offline gültig. Vor
`offline_not_after` muss ein kontrollierter Refresh Public/Source-Association,
Attestations, Trust-Root-Snapshot und Revocation-Policy erneut prüfen. Das
Trust-Root-Snapshot besitzt trotz fehlender eingebauter Expiry nur innerhalb
dieses FolioTone-Fensters Gültigkeit.

Eine neue Generation ist erforderlich bei Änderung von:

- Manifest-, Config-, Layer- oder RootFS-Identität;
- Repository-Commit, Workflow, Source Ref oder Invocation;
- Action-, Buildx-, BuildKit-, Rezept-, Lock- oder SBOM-Identität;
- ausgewähltem Attestation-Bundle oder Trust-Root-Snapshot;
- Releaseprofil, Claimschema oder Offline-Fenster;
- Revocation-Policy, soweit sie die Generation betrifft.

`archive-runtime-revocations/v1` ist geschlossenes, reviewtes JSON mit
monotoner Generation und sortierten Denylists für `release_id`, Manifestdigest,
Repository-Commit und Bundle-Digests. Jeder Treffer sperrt die Runtime sofort.
Eine niedrigere Policygeneration als bereits lokal beobachtet ist ebenfalls
gesperrt.

Ein vollständig offline gebliebener Host kann eine nach seinem letzten
Refresh extern veröffentlichte Revocation nicht kennen. Dieses Restrisiko ist
bis zum `offline_not_after` ausdrücklich begrenzt und wird nicht als aktuelle
Revocation-Prüfung dargestellt. Nach Ablauf, bei Clock Rollback oder ohne
frische importierte Policy endet die Availability fail-closed.

## Fail-closed-Semantik

Der öffentliche Resultvertrag bleibt unverändert:

```text
AVAILABLE
TOOL_UNAVAILABLE
```

Nur die vollständig erfolgreiche Verbindung aller Schichten erzeugt
`AVAILABLE` und die exakte Digestreferenz. Jeder andere Zustand liefert
`TOOL_UNAVAILABLE`, startet keinen Container und versucht weder Pull noch
Online-Reparatur. Interne secret- und pathfreie Diagnosecodes dürfen exakt
folgende Werte verwenden:

```text
RELEASE_NOT_ACCEPTED
RELEASE_EXPIRED
LOCAL_STATE_MISSING
LOCAL_STATE_INVALID
GENERATION_ROLLBACK
CLOCK_ROLLBACK
REVOKED
EVIDENCE_MISMATCH
OCI_LAYOUT_MISMATCH
IMAGE_NOT_PRESENT
IMAGE_INSPECT_MISMATCH
STATE_UPDATE_FAILED
```

Ein unbekannter Fehler wird zu `LOCAL_STATE_INVALID` oder
`EVIDENCE_MISMATCH` normalisiert; Raw-Tool-, Registry- oder Pfadtexte gelangen
nicht in öffentliche DTOs oder Logs.

## Paketgrenze vor EBAR-04

`S-EBAR-03A` ist eine Security- und Supply-Chain-Integration. Routing:
5.6 Sol mit Thinking `high`; zulässiger Fallback ist 5.5 nur, wenn keine neue
Trust-Root-, Signatur-, Rotation- oder Runtime-Authority-Entscheidung entsteht.
Spark, Luna und Terra sind für die Implementierung nicht zulässig. Eine offene
Verifier-Supply-Chain oder ein Bedarf an echter Runtime-Signaturprüfung stoppt
das Paket und erzeugt ein neues Frontier-Gate.

Nur folgende Dateien dürfen geändert oder angelegt werden:

```text
packaging/archive/7zip-26.02/archive-runtime-release.json
packaging/archive/7zip-26.02/archive-runtime-revocations.json
packaging/archive/7zip-26.02/archive-runtime-evidence/custom-slsa.jsonl
packaging/archive/7zip-26.02/archive-runtime-evidence/spdx.jsonl
packaging/archive/7zip-26.02/archive-runtime-evidence/trusted_root.jsonl
packaging/archive/7zip-26.02/supply_chain_evidence.py
.github/workflows/archive-image.yml
src/foliotone/archive/sevenzip.py
tests/unit/test_archive_sevenzip.py
tests/integration/test_archive_image_packaging.py
```

Der lokale provisionierte OCI-Store und Runtime-State sind Test-/Betriebsdaten
außerhalb Git. S-EBAR-03A darf keine Runner-, Sandbox-, Staging-, Listing-,
Integrity-, Extraction-, Secret-, Persistenz- oder W10-Implementierung
vorziehen.

## Tests und Abnahme

S-EBAR-03A benötigt mindestens:

- Golden Tests für den geschlossenen Record, `release_id` und alle exakten
  Manifest-, Config-, Layer-, SLSA-, SPDX-, Workflow- und Action-Claims;
- Einzelmutation jedes Authority-Felds sowie jedes Bundle-/Evidence-Bytes;
- Ablehnung von Pending-, Platzhalter-, unbekannten und mehrfachen
  Attestations;
- Erstprovisionierung, atomaren Refresh und simulierten Abbruch vor jedem
  Replace-Schritt;
- missing/corrupt/partial State, backward Release-/Revocation-Generation,
  Clock Rollback, Ablaufgrenzen und Denylist-Treffer;
- vollständige lokale OCI- und Docker-Inspect-Matrix einschließlich falscher
  Manifest-, Config-, Layer-, `diff_id`-, Env-, User-, Entrypoint-, Label-,
  History- und RootFS-Werte;
- einen harten Netzwerksperrtest, der beweist, dass der Per-Run-Preflight
  weder DNS, Socket, Registry, GitHub API noch Pull verwendet;
- den Negativnachweis, dass `BOOTSTRAP_LOCKED`, lokales Inspect oder `7zzs i`
  einzeln und gemeinsam ohne Acceptance-Record und lokalen State nie
  `AVAILABLE` ergeben;
- feste path- und secretfreie Fehlercodes sowie keine Raw-Evidence-Ausgabe;
- gezielte Unit-/Integrationstests, Ruff, Mypy und `git diff --check`.

Die Welle führt keinen vollständigen PR-CI-Gate aus, solange der Acceptance-
Record nicht mit tatsächlich beobachteten Bundle-, Commit-, Invocation- und
Trust-Root-Digests geschlossen werden kann. Ein fehlender externer Befund wird
nicht durch ein Testfixture oder einen manuellen Boolean ersetzt.

EBAR-04 darf erst beginnen, wenn S-EBAR-03A auf `origin/main` vollständig
gemergt, eine Releasegeneration explizit provisionierbar und der positive
Offline-Availability-Test sowie alle Negativfälle grün sind.

## Nicht autorisiert

Diese ADR autorisiert nicht:

- einen Container- oder Archivtoolstart in der Gate-Welle;
- `docker pull` oder Registryzugriff während eines Archive-Laufs;
- ein ungepinntes `gh`, Sigstore oder eine Kryptobibliothek als Runtime-
  Trust-Root;
- automatische Akzeptanz eines Workflowoutputs ohne reviewed Release-Record;
- ein Offline-Fenster über 90 Tage oder die Behauptung aktueller Revocation
  ohne Refresh;
- Passwortübergabe, Source-Media-Mounts, Source-Mutation, Archive-Persistenz,
  W10 oder Native-Windows-Sandboxing.

## Konsequenzen

- `BOOTSTRAP_LOCKED` bleibt korrekt auf Reproduzierbarkeit begrenzt.
- Public/Source-Association und GitHub-Attestations werden einmal kontrolliert
  provisioniert und blockieren normale Offline-Archive-Läufe nicht durch
  Netzwerkabhängigkeit.
- Custom SLSA, SPDX, Workflowidentity und lokale OCI-/Docker-Identität bleiben
  an eine einzige reviewte Releasegeneration gebunden.
- Rotation und lokale Revocation sind fail-closed; die unvermeidbare Grenze
  externer Revocation im Offline-Betrieb ist ausdrücklich dokumentiert.
- EBAR-04 erhält erstmals eine implementierbare Availability-Precondition,
  darf sie aber nicht selbst abschwächen oder ersetzen.

## Primärquellen

- GitHub, Offline-Verifikation von Artifact Attestations:
  https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline
- GitHub CLI, `gh attestation verify` einschließlich Identity- und Offline-
  Flags:
  https://cli.github.com/manual/gh_attestation_verify
- GitHub CLI, `gh attestation download`:
  https://cli.github.com/manual/gh_attestation_download
- GitHub CLI, `gh attestation trusted-root`:
  https://cli.github.com/manual/gh_attestation_trusted-root
- GitHub Packages, Sichtbarkeit und Zugriff:
  https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility
- GitHub Packages, Source-Association:
  https://docs.github.com/en/packages/learn-github-packages/connecting-a-repository-to-a-package
- Docker Image Inspect:
  https://docs.docker.com/reference/cli/docker/image/inspect/
- OCI Image Manifest:
  https://github.com/opencontainers/image-spec/blob/main/manifest.md
- OCI Image Configuration:
  https://github.com/opencontainers/image-spec/blob/main/config.md
