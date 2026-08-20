# ADR-0040: Reproduzierbares 7zzs-Runtime-Image und attestierte Result-Identität

- Status: Accepted
- Datum: 2026-08-20

## Kontext

ADR-0039 erlaubt für die primäre Docker/Linux-Runtime ausschließlich ein
lokal vorhandenes, per Digest adressiertes Image. Vor S-EBAR-03 waren jedoch
weder Bezugsmodell und Root-Filesystem noch die Identitäts-, Lizenz- und
Attestationsregeln festgelegt. Ein beliebiges operator-provided Image würde
diese Entscheidungen auf jeden Host verlagern und die durch
`archive-linux-container-runner/v1` verlangte reproduzierbare Toolidentität
aufheben.

Die offizielle 7-Zip-Downloadseite verweist für Linux x86-64 auf das Release-
Artefakt `7z2602-linux-x64.tar.xz`. Das offizielle GitHub-Release veröffentlicht
dafür den SHA-256-Wert
`41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e`.
Der Release-Tag `26.02` ist ein Lightweight Tag auf Commit
`f9d78aff31a5f2521ae7ddbdc97c4a8855808959`; der Commit ist nach dem
GitHub-Verifikationsstatus unsigned. Das Release enthält kein `.asc`-, `.sig`-
oder vergleichbares Signaturartefakt. Die publizierte Checksumme fixiert damit
die Bytes, bildet aber keinen vom Release-Kanal unabhängigen kryptografischen
Herkunftsnachweis.

Ein Result-Image-Digest kann vor dem erstmaligen Build des noch nicht
implementierten Repositoryrezepts nicht verantwortbar angegeben werden. Das
Gate darf keinen hypothetischen Digest erfinden. Es benötigt deshalb einen
zweistufigen Build- und Lockvertrag, der S-EBAR-03 mechanisch ausführbar macht
und bis zum belegten Resultat geschlossen bleibt.

## Entscheidung

FolioTone pflegt ein projekt-eigenes, reproduzierbares Image-Rezept für genau
`linux/amd64`. Das Runtime-Image heißt
`ghcr.io/gecompat/foliotone-archive-7zip`. Tags sind nur menschlich lesbare
Releasehinweise; `archive-linux-container-runner/v1` akzeptiert ausschließlich
die Form `ghcr.io/gecompat/foliotone-archive-7zip@sha256:<64 lowercase hex>`.

Das Image verwendet den reservierten Dockerfile-Ausgangspunkt `FROM scratch`.
`scratch` ist kein pullbares Image und besitzt deshalb absichtlich keinen
Base-Manifest-Digest. Der Base-Vertrag lautet exakt:

```text
base_kind = SCRATCH
base_reference = scratch
base_digest = NONE
platform = linux/amd64
```

`NONE` ist hier keine offene Identität, sondern die festgelegte Eigenschaft
des leeren Docker-Build-Ausgangspunkts. Jede andere `FROM`-Referenz, jeder
Build- oder Runtime-Stage aus einem pullbaren Image und jede weitere Plattform
benötigen ein neues Gate mit gepinntem Base-Digest.

Das Image enthält ausschließlich:

```text
/usr/local/bin/7zzs
/usr/share/licenses/7zip/License.txt
/usr/share/licenses/7zip/copying.txt
/usr/share/licenses/7zip/unRarLicense.txt
/usr/share/doc/7zip/readme.txt
/usr/share/src/7zip/7z2602-src.tar.xz
```

Daneben existieren nur die erforderlichen Parent-Verzeichnisse sowie die
leeren Mountziele `/workspace/input` und `/workspace/output`. EBAR-04 mountet
ausschließlich das geprüfte Staging auf `/workspace/input` read-only und den
getrennten Output-Workspace auf `/workspace/output` read-write. Vor dem Start
muss der Backend-Preflight die in ADR-0039 festgelegte container-sichtbare
Ownership-/Modusmatrix (`65532:65532`, Input-Verzeichnisse `0500`, Input-
Dateien `0400`, Output-Root `0700`) sowie Link-/Reparse-Freiheit belegen. Kann
die Bind-Mount-Projektion das nicht beweisen, bleibt das Backend
`TOOL_UNAVAILABLE`.

Das Image enthält keine Shell, keinen Paketmanager, keine CA-Zertifikate, keinen
Loader und keine FolioTone-Source. `7zzs` hat Modus `0555`; die vier Texte haben
Modus `0444`. Alle Dateien gehören numerisch `0:0`. Das Image setzt exakt
`USER 65532:65532`, `WORKDIR /workspace` und den JSON-Entrypoint
`["/usr/local/bin/7zzs"]`. Das Dockerfile enthält keine `ENV`-Instruction und
kein `CMD`. BuildKit erzeugt dennoch deterministisch genau den folgenden
einzigen Eintrag in `Config.Env`:

```text
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
```

Dieser Eintrag ist Teil der gelockten OCI-Konfiguration; ein fehlender,
zusätzlicher oder abweichender `Config.Env`-Eintrag ist ungültig. Die Runtime
verwendet weiterhin das read-only Root-Filesystem und stellt Schreibraum nur
durch den von ADR-0039 erlaubten Output-Mount bereit.

Das v1-Dockerfile enthält ohne Syntax-Frontend-Direktive exakt:

```dockerfile
FROM scratch
ADD rootfs.tar /
LABEL org.opencontainers.image.source="https://github.com/gecompat/FolioTone"
USER 65532:65532
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/7zzs"]
```

Der Vorbereitungsschritt erzeugt `rootfs.tar` deterministisch aus genau den
sechs freigegebenen Dateien, ihren Parent-Verzeichnissen und den beiden leeren
Mountzielen.
Tar-Reihenfolge ist bytelexikografisch, numerische Owner sind `0:0`, User- und
Group-Namen sind leer, Zeitstempel sind `1782345600`, reguläre Dateien haben
die oben festgelegten Modi und Verzeichnisse Modus `0555`. PAX-Header,
Extended Attributes, ACLs, Links, Devices und weitere Metadaten sind verboten.
`rootfs.tar` ist der einzige Dateiinput des netzwerklosen Docker-Builds; Lock,
SBOM, Git-Metadaten und heruntergeladene Archive liegen nicht im Buildkontext.

## Gemessener OCI-Outputvertrag

**Empirisch:** Der zweimalige Offline-Bootstrap mit den in diesem ADR
festgelegten Inputs und `archive-image-build/v1` ergab die nachfolgend
gebundene OCI-Struktur. Diese Werte präzisieren den vorhandenen Rezeptvertrag;
sie machen das Image nicht runtimeverfügbar und ersetzen keine der späteren
Publikations- oder Verifikationsbedingungen.

Das OCI-Layout enthält genau einen `linux/amd64`-Descriptor mit genau der
einzigen Annotation
`org.opencontainers.image.created=2026-06-25T00:00:00Z`. Sein Manifest lautet
exakt:

```text
sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287
```

und hat Größe `838` Byte. Das Manifest referenziert genau die folgende
Konfiguration:

```text
sha256:6158a13f41ad2915237fc917abb28a7be373abf060402988898cd85bcd565b9f
```

mit Größe `1185` Byte sowie genau zwei Layer in dieser Reihenfolge:

| Reihenfolge | Compressed Layer Digest | Gzip-Größe | Uncompressed `diff_id` | Uncompressed-Inhalt |
|---|---|---:|---|---|
| 1 | `sha256:ab909aa86586a73ab10913d9662146ae2442e5ce4b74842b54f0984dd18aad4f` | `3298569` Byte | `sha256:b2af5e745f24985c459fd49b2191807b36364540d53d472db3620e0b4cfc024e` | der oben festgelegte `rootfs.tar`-Inhalt |
| 2 | `sha256:4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1` | `32` Byte | `sha256:5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef` | der von `WORKDIR /workspace` erzeugte leere Layer: unkomprimiert exakt `1024` Nullbytes und keine Tar-Member |

Die Image-Config besitzt ausschließlich die OCI-Top-Level-Felder
`architecture`, `os`, `created`, `config`, `rootfs` und `history`.
`architecture=amd64`, `os=linux` und
`created=2026-06-25T00:00:00Z` sind fest. `config` enthält ausschließlich
`User=65532:65532`, `Entrypoint=["/usr/local/bin/7zzs"]`,
`WorkingDir=/workspace`, den oben festgelegten singleton `Env`-Eintrag und
das Source-Label `org.opencontainers.image.source=https://github.com/gecompat/FolioTone`.
`Cmd` ist nicht gesetzt. `rootfs.type=layers` und seine zwei `diff_ids` müssen
genau den Tabellenwerten in derselben Reihenfolge entsprechen.

`history` enthält exakt fünf Einträge in Dockerfile-Reihenfolge für `ADD`,
`LABEL`, `USER`, `WORKDIR` und `ENTRYPOINT`. Jeder Eintrag ist auf
`2026-06-25T00:00:00Z` datiert. Nur `ADD` und `WORKDIR` sind Layer-erzeugende
Einträge und korrespondieren in dieser Reihenfolge mit den zwei
`rootfs.diff_ids`; `LABEL`, `USER` und `ENTRYPOINT` sind als leere
History-Schritte markiert. Zusätzliche History-Einträge, eine abweichende
Reihenfolge oder eine andere Zuordnung von Layern zu Schritten ist ungültig.

Der SHA-256-Wert des exportierten OCI-Tars
`b9e2ac16ee11b316dc79311158669e789798bec208add4316ca1408702860fda` ist
zulässige Auditinformation für diesen Bootstraplauf. Er ist weder
Runtime-Identität noch Lock-, Registry- oder Verfügbarkeitsnachweis; dafür
bleibt ausschließlich der Plattform-Manifest-Digest maßgeblich.

Vor dem Build muss S-EBAR-03 das Tar-Member `7zzs` mit Größe `3763320` Byte und
SHA-256 `20df89e993594c1bb7686f125dabe1acc56c109fb1d9b40435ea5fcbc1ca3453`
als unverändertes Linux-x86-64-ELF `ET_EXEC` prüfen. `PT_INTERP`, `PT_DYNAMIC`,
`DT_NEEDED`, Links sowie alle nicht regulären Artefakte werden
fail-closed abweisen. Dadurch ist belegt, dass das Binärobjekt ohne weitere
Runtime-Dateien im `scratch`-Image lauffähig sein kann. Eine Abweichung stoppt
S-EBAR-03; sie darf nicht durch die Wahl eines Distribution-Base-Images
repariert werden.

## Upstream- und Build-Inputs

Der einzige ausführbare Input für `archive-7zip-image/v1` ist:

| Feld | Exakter Wert |
|---|---|
| Version | `26.02` |
| Plattform | `linux/amd64` beziehungsweise Upstream `linux-x64` |
| URL | `https://github.com/ip7z/7zip/releases/download/26.02/7z2602-linux-x64.tar.xz` |
| Archivgröße | `1571416` Byte |
| Archiv-SHA-256 | `41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e` |
| Release-Tag-Commit | `f9d78aff31a5f2521ae7ddbdc97c4a8855808959` |
| Signaturstatus | `UNSIGNED_UPSTREAM_RELEASE` |
| Ausführbares Tar-Member | `7zzs` |
| Ausführbares Member-Größe | `3763320` Byte |
| Ausführbares Member-SHA-256 | `20df89e993594c1bb7686f125dabe1acc56c109fb1d9b40435ea5fcbc1ca3453` |
| `SOURCE_DATE_EPOCH` | `1782345600` |

Der Build lädt den Upstream-Tarball nicht in einer Dockerfile-Instruction.
Ein Vorbereitungsschritt lädt ihn über die feste HTTPS-URL, prüft zuerst
Größe und SHA-256 und liest danach ausschließlich die exakt erwarteten
regulären Member. Absolute Pfade, Traversal, Links, Devices, doppelte
normalisierte Namen oder zusätzliche als Buildinput ausgewählte Member werden
abgewiesen. Der eigentliche Docker-Build läuft ohne Netzwerk und erhält nur
den bereits geprüften minimalen Buildkontext.

Der Builder ist ebenfalls Teil der reproduzierbaren Eingabe. S-EBAR-03
verwendet exakt:

| Builderfeld | Exakter Wert |
|---|---|
| Buildx | `v0.36.1` |
| Linux-amd64-Asset | `https://github.com/docker/buildx/releases/download/v0.36.1/buildx-v0.36.1.linux-amd64` |
| Assetgröße | `65302690` Byte |
| Asset-SHA-256 | `48af8a397ebd60178778bf63611dbcebe5f5e7a9be90eb9147b24b9587455778` |
| BuildKit | `v0.32.2` |
| Builder-Image | `moby/buildkit@sha256:28a898719c18a33f4e8000685287fa36fd0dd9560c6440227d3a732d79bb41d8` |
| erwartetes `linux/amd64`-Manifest | `sha256:040d34121c27906c4ff9ac152a30d52bf2c5d328d3bb748916bb3d2743c02528` |

Das Buildx-Asset wird vor jeder Ausführung auf Größe und SHA-256 geprüft. Ein
isolierter `docker-container`-Builder wird mit genau dem per OCI-Index-Digest
adressierten BuildKit-Image erzeugt. Sein Inspect-Ergebnis muss BuildKit
`v0.32.2` und für `linux/amd64` genau den oben festgelegten Child-Manifest-
Digest ausweisen. Tagauflösung, ein bereits vorhandener ungeprüfter Builder
oder eine andere Plattform sind unzulässig. Kann S-EBAR-03 diese Identitäten
nicht mechanisch belegen, wird kein Lock geschrieben und die Runtime bleibt
`TOOL_UNAVAILABLE`.

Jeder Bootstrap-, Gate- und Post-Merge-Verifikationsbuild verwendet Profil
`archive-image-build/v1`: Prozess-Environment und Buildargument setzen
`SOURCE_DATE_EPOCH=1782345600`; Buildx erhält genau eine Plattform
`--platform linux/amd64`, `--network none`, `--no-cache`,
`--provenance=false`, `--sbom=false` und
`--output type=oci,dest=<neue-private-OCI-Datei>,oci-mediatypes=true,compression=gzip,force-compression=true,rewrite-timestamp=true`.
Die vier Exportereinstellungen sind fester Bestandteil des Profils und gelten
unverändert auch für den späteren Registry-Publish. Das feste Builderobjekt und
der feste Buildkontext werden explizit angegeben. Es gibt weder Push noch Load
in dieser Buildphase. Aus `index.json` des OCI-Layouts wird genau ein
nicht-attestierendes `linux/amd64`-Manifest verlangt. Verglichen und gelockt
wird dessen Plattform-Manifest-Digest, nicht der Hash der OCI-Tar-Datei, ein
Tag oder ein attestationsabhängiger äußerer Index. Zusätzliche Plattform- oder
Attestationsmanifeste machen den Build ungültig.

Die semantisch bindende Invocation ist:

```text
SOURCE_DATE_EPOCH=1782345600
docker buildx build --builder <isolierter-v1-builder> \
  --platform linux/amd64 --network none --no-cache \
  --provenance=false --sbom=false \
  --build-arg SOURCE_DATE_EPOCH=1782345600 \
  --output type=oci,dest=<neue-private-OCI-Datei>,oci-mediatypes=true,compression=gzip,force-compression=true,rewrite-timestamp=true \
  <minimaler-geprüfter-Buildkontext>
```

Die einmalige, hashgeprüfte Builder-/Input-Akquisition darf vor diesem Aufruf
Netzwerk verwenden. Beide Reproduzierbarkeitsläufe selbst beginnen erst nach
lokaler Identitätsprüfung und haben für Dockerfile-Instructions
`--network none`; das Rezept darf nichts nachladen.

Erst nachdem der Post-Merge-Verifikationsbuild den Lock reproduziert hat, darf
derselbe geschützte Job einmal mit unverändertem Builder, Kontext,
Environment, Buildargumenten, Plattform-, Netzwerk-, Cache- und
Attestationsflags publizieren. Ausschließlich der Output wird ersetzt durch
`--output type=image,name=ghcr.io/gecompat/foliotone-archive-7zip:26.02-foliotone-v1,push=true,oci-mediatypes=true,compression=gzip,force-compression=true,rewrite-timestamp=true`.
Auch dieser Publishbuild setzt `--provenance=false --sbom=false`. Der Tag ist
nur ein Veröffentlichungshinweis. Die nachfolgende Registryprüfung muss im
gepushten Single-Platform-Ergebnis exakt denselben gelockten
`linux/amd64`-Plattform-Manifest-Digest finden; ein abweichender äußerer Index
oder eine durch andere Medientyp-, Kompressions- oder Timestamp-Einstellungen
erzeugte Manifestidentität darf nie als Runtimeidentität übernommen werden.

Die Binärdistribution liefert `License.txt` und `readme.txt` als eigene,
unveränderte Tar-Member. `copying.txt` und `unRarLicense.txt` stammen weiter
unverändert aus dem offiziellen `26.02`-Source-Tag. Die erwarteten Bytes lauten:

| Datei | Feste Raw-URL unter `26.02` | SHA-256 |
|---|---|---|
| Tar-Member `License.txt` | `7z2602-linux-x64.tar.xz` | Größe `6029` Byte; SHA-256 `1790374e5352329cedb46ee3808930a88e9ca2f08b82b10fcf5cf605d2c301b1` |
| `DOC/copying.txt` | `https://raw.githubusercontent.com/ip7z/7zip/26.02/DOC/copying.txt` | `dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551` |
| `DOC/unRarLicense.txt` | `https://raw.githubusercontent.com/ip7z/7zip/26.02/DOC/unRarLicense.txt` | `17bd9fa4399092c777536fff045b41df76ec9d2ac4c9b8e7345d3b8b6ccc7976` |
| Tar-Member `readme.txt` | `7z2602-linux-x64.tar.xz` | Größe `3863` Byte; SHA-256 `c3ecf1b8f38631d6ef8a35048e80da77b31cf292a42b3e8793afd44bf4f001b0` |

S-EBAR-03 darf diese vier Dateien im Repository unter
`packaging/archive/7zip-26.02/licenses/` spiegeln, muss Byteidentität und
Hashes aber gegen den festen Upstream-Tag prüfen. Der zugehörige Source-
Tarball wird ebenfalls aus demselben offiziellen Release geladen, vor jeder
weiteren Verarbeitung geprüft und unverändert in das Image kopiert:

| Feld | Exakter Wert |
|---|---|
| URL | `https://github.com/ip7z/7zip/releases/download/26.02/7z2602-src.tar.xz` |
| Größe | `1543480` Byte |
| SHA-256 | `cf967c98bca02a4b8b16375f441825a8e141362f14be1969bbec8e1ca0bff9dd` |

## Lizenz und Redistribution

Das Image verteilt das unveränderte offizielle Binärobjekt. Die offizielle
Lizenz nennt GNU LGPL 2.1 oder später als Hauptlizenz, BSD-2-Clause- und
BSD-3-Clause-Anteile sowie die unRAR-Einschränkung. Sie erlaubt Nutzung und
Redistribution und verlangt bei Binärredistribution die zugehörigen
Lizenzinformationen. Deshalb werden die oben genannten vier unveränderten
Texte und der vollständige zugehörige Source-Tarball im Image mitgeliefert,
Source-Tag und Source-Tarball-Identität in SBOM/Provenance angegeben und der
RAR-Code weder verändert noch zur Reimplementierung eines RAR-Kompressors
verwendet.

Das Image darf als öffentliches GHCR-Package veröffentlicht werden, sofern
alle Lizenzdateien, SBOM und Provenance vorhanden sind. Die feste OCI-Source-
Annotation im Dockerfile verbindet das Package mit
`https://github.com/gecompat/FolioTone`. Da ein erstmals veröffentlichtes
GHCR-Package standardmäßig privat ist, muss ein geschützter Repository-Owner-
Setupschritt das Package explizit auf `public` stellen und die Source-
Association mit diesem Repository verifizieren. Bis dahin ist auch ein
erfolgreich gepushtes Manifest nicht runtimeverfügbar. Fehlt eine dieser
Bedingungen oder ändert sich die Upstream-Lizenz, wird nicht freigegeben und
die Runtime bleibt `TOOL_UNAVAILABLE`.

## Zweistufiger Result-Digest- und Lockvertrag

S-EBAR-03 legt folgende Dateien an:

```text
packaging/archive/7zip-26.02/Dockerfile
packaging/archive/7zip-26.02/archive-image.lock.json
packaging/archive/7zip-26.02/archive-image.spdx.json
packaging/archive/7zip-26.02/licenses/*
```

`archive-image.lock.json` verwendet Profil `archive-image-lock/v1` und bindet
mindestens Recipe-Profil, Plattform, alle oben genannten URLs und Hashes,
den eindeutig benannten `executable_member_name`, die
`executable_member_size_bytes` und den `executable_member_sha256` von `7zzs`,
die beiden eindeutig benannten `binary_tar_license_*`- und
`binary_tar_readme_*`-Felder, UID/GID, `SOURCE_DATE_EPOCH`,
Buildx-Version, Assetgröße und Asset-SHA-256, BuildKit-Version, Builder-OCI-
Index-Digest und erwarteten `linux/amd64`-Child-Digest, das feste
`archive-image-build/v1`-Aufrufprofil einschließlich
`oci-mediatypes=true`, `compression=gzip`, `force-compression=true` und
`rewrite-timestamp=true`, den SHA-256 von Dockerfile und
`rootfs.tar`, Runtime-Plattform-Manifest-Digest sowie SBOM-Digest. Private
Pfade, Credentials,
Runnernamen, Repository-Commits und volatile Tags sind verboten. Der
Repository-Commit wird erst in der nicht zyklischen externen Provenance an
Lock- und Result-Digest gebunden.

Nach zwei gleichen Bootstrap-Builds hat die Lockdatei exakt den Status
`BOOTSTRAP_LOCKED`. In diesem Zustand bindet sie zusätzlich die gemessene
Plattform-Manifest-, Config- und beide Layer-Identitäten einschließlich
Descriptorgrößen sowie die zwei geordneten `diff_ids` aus dem OCI-Outputvertrag.
Der Audit-Tar-Hash darf zusätzlich dokumentiert werden, darf aber nicht als
Ersatz- oder Runtimeidentität verwendet werden. Die gleichzeitig erzeugte
`archive-image.spdx.json` benennt den gelockten Plattform-Manifest-Digest und
den Status `BOOTSTRAP_LOCKED`; sie ist Supply-Chain-Evidence, keine
Verfügbarkeitsbehauptung.

Der Packaging-Inspector prüft für dieses Profil nicht nur die allgemeine
OCI-Syntax, sondern exakt den Einzel-Descriptor, Manifest- und Config-Digest
mit Größen, beide geordneten Layer-/`diff_id`-Paare, den singleton
`Config.Env`-Wert, die fünfteilige History und den leeren zweiten
`WORKDIR`-Layer. Eine Abweichung verhindert das Schreiben oder Akzeptieren
eines `BOOTSTRAP_LOCKED`-Locks.

Die zwei Stufen sind:

1. **Bootstrap und Reproduzierbarkeit:** S-EBAR-03 erzeugt den geprüften
   Buildkontext, baut mit `archive-image-build/v1` zweimal mit identischen
   festen Inputs und verlangt den identischen, im OCI-Outputvertrag gebundenen
   `linux/amd64`-Plattform-Manifest-Digest. Erst dieser beobachtete Digest wird
   mit Status `BOOTSTRAP_LOCKED` in die Lockdatei übernommen. Der Digest ist
   ein Messergebnis, keine neue Architekturentscheidung und keine Runtime-
   Availability- oder Post-Publish-Proof.
2. **Publikation und Attestation:** Der finale PR-Gate baut erneut gegen die
   Lockdatei. Nach dem Merge baut ein geschützter `main`-Workflow nochmals,
   verweigert jede Digestabweichung, publiziert exakt dieses Manifest nach
   GHCR und hängt erst danach SBOM- und Build-Provenance-Attestations an den
   bereits gelockten Runtime-Plattform-Manifest-Digest. Inline-Attestations
   sind in jedem Runtime-Image-Build verboten und dürfen dessen Identität
   nicht verändern. Erst wenn das Package öffentlich und source-associated
   ist und ein anonymer Manifest-by-Digest-Abruf den gelockten Digest bestätigt,
   darf der Digest in einem Runtime-Manifest als verfügbar gelten.

Ein fehlender, `null` gesetzter, andersformatiger oder nicht reproduzierbarer
Result-Digest ist kein teilweise brauchbarer Zustand. S-EBAR-03 und jede
Runtime melden dann `TOOL_UNAVAILABLE`. Tags wie `latest` oder
`26.02-foliotone-v1` dürfen niemals die Digestprüfung ersetzen.

## SBOM und Provenance

Die deterministische SPDX-2.3-SBOM benennt mindestens das Runtime-Image,
7-Zip 26.02, den SHA-256 des Upstream-Tarballs und des extrahierten `7zzs`, die
vier Lizenzklassifikationen beziehungsweise LicenseRefs und die vier
mitgelieferten Lizenz-/Hinweisdateien sowie den vollständigen Source-Tarball.
Ein Scannerfund darf ergänzt werden, ersetzt diese explizite
Komponentenbeschreibung im `scratch`-Image aber nicht.

Die Provenance ist ein deterministisches SLSA-v1-Custom-Predicate für dieses
Profil. Es bindet mindestens Repository und finalen Commit, Workflow und
vollständig commit-gepinnte Action-Identitäten, Recipe-/Lock-/SBOM-Digests,
`SOURCE_DATE_EPOCH`, Plattform, Upstream-URLs und -Hashes, die
Executable- und Lizenzidentitäten, Buildx-/BuildKit-Identitäten sowie
Plattform-Manifest-, Config- und geordnete Layer-Identitäten. Der geschützte
Workflow erzeugt und publiziert dieses Predicate mit einer vollständig
commit-gepinnten `actions/attest`-Action. Er prüft nach der Attestation exakt
den Predicate-Inhalt gegen Lock, SBOM und publiziertes Ergebnis. Die generische
GitHub-Build-Provenance darf zusätzlich existieren, ersetzt das Custom-
Predicate aber nicht: `actions/attest-build-provenance` allein enthält nicht
alle für dieses Profil verpflichtenden Bindungen. Public Buildjobs erhalten
keine Secrets außer dem kurzlebigen, minimal berechtigten GitHub-Token des
geschützten Publishjobs. Maximal detaillierte Provenance ist nur zulässig,
wenn ihr Buildkontext und ihre Parameter nachweislich ausschließlich
öffentliche, nicht geheime Werte enthalten.

## CI- und Betriebsgrenzen

Public PR CI darf das offizielle, fest gehashte Artefakt laden, den sicheren
Vorbereitungsschritt ausführen, ELF-/Datei-/Lizenzprüfungen durchführen, das
Image zweimal lokal bauen und Imagekonfiguration, Lock und SBOM prüfen. PRs
dürfen weder Packages pushen noch einen Registry-Token erhalten. Actions und
Builder-Images werden durch vollständige Commit- beziehungsweise
Manifest-Digests gepinnt.

Nur ein geschützter Post-Merge-Workflow auf `main` erhält `packages:write`,
`id-token:write` und `attestations:write`. Er publiziert nur bei exakter
Lockübereinstimmung. Ein Publish aus Forks, Pull Requests, Tags ohne
geschützten Workflow oder manuell veränderten Buildinputs ist verboten. Der
Workflow publiziert das Custom-Predicate ausschließlich mit einer vollständig
commit-gepinnten `actions/attest`-Action und verifiziert anschließend dessen
vollständigen Inhalt gegen die in diesem ADR genannten Pflichtwerte; eine
Standard-`actions/attest-build-provenance`-Attestation genügt nicht.

Nach Publish und dem geschützten Owner-Setup erfolgt aus einem neuen minimalen
Prozess ohne Benutzer- oder Registry-Credentials, Cookies oder Docker-Config
ein anonymer Registry-v2-Manifestabruf der Referenz
`ghcr.io/gecompat/foliotone-archive-7zip@sha256:<locked-platform-digest>`.
Anonym bedeutet hierbei nicht das Verbot des standardkonformen Bearer-Flows:
Der Prozess darf genau eine begrenzte erste `401`-Challenge akzeptieren, deren
`realm` exakt `https://ghcr.io/token`, deren `service` exakt `ghcr.io` und
deren `scope` exakt
`repository:gecompat/foliotone-archive-7zip:pull` ist. Er ruft den Token
credentialfrei und begrenzt über diese Challenge ab und verwendet den
ephemeren Bearer ausschließlich in diesem frischen Prozess für den exakten
Manifest-by-Digest-`GET`. Token, Authorization-Header und Antworten werden
weder geloggt noch persistiert; GitHub-Token-, Credential- oder anderer
Fallback ist verboten. Der Erfolg verlangt außerdem exakten
`Docker-Content-Digest`, `Content-Length=838`, Descriptorgröße `838` und den
erlaubten Manifest-Medientyp. HTTP-Erfolg, zurückgemeldeter Digest, öffentliche
Sichtbarkeit und Source-Association mit `gecompat/FolioTone` müssen
übereinstimmen; andernfalls bleibt der Status `TOOL_UNAVAILABLE`.

Adversarial Archive-Ausführungen, private Extraction-Fixtures und lokale
Collection-Canaries gehören nicht in den Image-Publishjob. Sie laufen in den
späteren Paketen ausschließlich mit synthetischen oder privaten lokalen
Fixtures unter `C:\rep\tmp\FolioTone` und `C:\rep\artifacts\FolioTone`; Raw-
Ausgaben und Runtime-Berichte werden nicht hochgeladen. Öffentliche Tests
dürfen später kleine rein synthetische Archive ausführen, sofern sie keine
Secrets, privaten Pfade oder Raw-Ausgaben als Artefakt publizieren.

## Update- und Kompatibilitätsregel

Das Profil `archive-7zip-image/v1` ist an 7-Zip 26.02, `linux/amd64`,
`scratch`, alle Inputhashes, die festen Imagepfade, UID/GID und den
Result-Digest gebunden. Ein Upstream-Release, Rebuild, Builderwechsel,
Lizenzwechsel, anderer Signaturstatus, Plattformwechsel oder inhaltliches
Rezeptupdate erzeugt ein neues Imageprofil und eine neue Lockidentität. Ein
bewegliches Releaseasset oder Tag wird nie still akzeptiert.

Vor einem Update werden offizielle Download-, Release-, Lizenz- und
Security-Informationen erneut geprüft. Eine neue Version wird zunächst mit
den EBAR-05-Fixtures und dem SLT-Parservertrag validiert. Alte Digests bleiben
für bestehende Evidence nachvollziehbar, werden aber nicht automatisch für
neue Jobs gewählt.

## Nicht autorisiert

Dieses Gate autorisiert nicht:

- den Start eines Containers oder Archivtools in dieser Gate-Welle;
- einen Lauf ohne fixierten und attestierten Result-Digest;
- eine andere Architektur oder ein Distribution-Base-Image;
- Passwörter, `-p`, Netzwerkzugriff der Runtime oder zusätzliche Tools im Image;
- Source-Media-Mounts, Source-Mutation, Persistenzmigration oder W10;
- das Hochladen privater Fixtures, Archive, Raw-Ausgaben oder Runtimeberichte.

## Konsequenzen

- S-EBAR-03 besitzt alle fachlichen Werte für Rezept, Packaging und
  Verifikation; der noch unbekannte Result-Digest wird mechanisch durch den
  zweifachen reproduzierbaren Bootstrap-Build ermittelt.
- Bis Lock, Post-Merge-Publikation, öffentliche/source-associated
  Packagekonfiguration, anonyme Digestverifikation und Attestation erfolgreich
  sind, bleibt `archive-linux-container-runner/v1` `TOOL_UNAVAILABLE`.
- Das `scratch`-Image reduziert Runtime-Inhalt und Angriffsfläche, verlangt
  aber den expliziten statischen ELF-Nachweis.
- Der fehlende unabhängige Upstream-Signaturnachweis bleibt sichtbar und wird
  nicht durch die FolioTone-Build-Attestation umgedeutet.

## Primärquellen

- 7-Zip 26.02 Download und Linux-x64-Artefakt:
  https://www.7-zip.org/download.html
- Offizielles 7-Zip-26.02-Release mit Asset-Digests:
  https://github.com/ip7z/7zip/releases/tag/26.02
- Offizieller 7-Zip-26.02-Source-Tag:
  https://github.com/ip7z/7zip/tree/26.02
- 7-Zip-Lizenz und Redistribution:
  https://www.7-zip.org/license.txt
- Source-Lizenz des Tags 26.02:
  https://github.com/ip7z/7zip/blob/26.02/DOC/License.txt
- Source-README mit Linux-Build- und Lizenzhinweisen:
  https://github.com/ip7z/7zip/blob/26.02/DOC/readme.txt
- Docker `scratch` als reservierter leerer Build-Ausgangspunkt:
  https://docs.docker.com/build/building/base-images/
- Dockerfile-Referenz, numerische `USER`-/`COPY`-Identitäten und
  Digest-Referenzen:
  https://docs.docker.com/reference/dockerfile/
- Reproduzierbare Builds und `SOURCE_DATE_EPOCH`:
  https://docs.docker.com/build/ci/github-actions/reproducible-builds/
- Docker SBOM- und Provenance-Attestations:
  https://docs.docker.com/build/metadata/attestations/
- Offizielles Docker-Buildx-v0.36.1-Release:
  https://github.com/docker/buildx/releases/tag/v0.36.1
- Offizielles Moby-BuildKit-v0.32.2-Release und Builder-Image:
  https://github.com/moby/buildkit/releases/tag/v0.32.2
- Offizieller Docker-Hub-Tag des Moby-BuildKit-Builder-Images:
  https://hub.docker.com/r/moby/buildkit/tags?name=v0.32.2
- Buildx-Buildflags und OCI-Output:
  https://docs.docker.com/reference/cli/docker/buildx/build/
- GitHub Artifact Attestations für Container und SBOM:
  https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- GitHub-Package-Sichtbarkeit und anonyme Public-Pulls:
  https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility
- GitHub-Source-Association eines Container-Packages:
  https://docs.github.com/en/packages/learn-github-packages/connecting-a-repository-to-a-package
