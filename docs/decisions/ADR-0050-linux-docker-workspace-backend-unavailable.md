# ADR-0050: Linux-/Docker-Workspace-Backend bleibt fail-closed unverfügbar

- Status: Accepted
- Datum: 2026-08-21

## Kontext

ADR-0049 definiert mit `archive-bounded-workspace-capability/v1` einen
dateisystemneutralen Vertrag für einen privat geliehenen Extraction-Workspace.
S-EBAR-04Q implementiert ausschließlich dessen Provider-, Lease-, Capability-,
Empty-Revalidation-, Return- und Quarantänegrenze. Die feste Adapter-Allowlist
ist absichtlich leer. FG-A-WORKSPACE-BACKEND muss deshalb entscheiden, ob für
die bestehende primäre Linux-/Docker-Runtime bereits ein konkretes Backend mit
dem vollständigen Vertrag belegbar ist.

Der notwendige Schutz besteht aus drei unabhängigen harten Achsen:

- höchstens `8589934592` Byte nutzbarer Workspace für Input und Output;
- höchstens `10000` Output-Objekte und `20000` Gesamtobjekte;
- mindestens `1073741824` Byte Reserve außerhalb der Capability.

Jede Überschreitung muss bereits beim nächsten Byte beziehungsweise Objekt
atomar scheitern. Polling, `du`, `df`, FIEMAP, ein später Scan oder Cleanup
sind Beobachtung und keine solche Budget-Authority. Zusätzlich verlangt
ADR-0048, dass der Extraction-Container vor dem synchronen Consumer bewiesen
abwesend ist, der Workspace dabei erhalten bleibt und erst danach bereinigt,
leer revalidiert und zurückgegeben wird.

FolioTone-Kern und Capability-Vertrag dürfen weder Mount-, Device-, Formatier-,
`root`- noch `CAP_SYS_ADMIN`-Authority erhalten. Ein konkreter Adapter darf
administrativ vorprovisionierte Backend-Eigenschaften nur lokal hinter seiner
eigenen Capability- und Conformance-Grenze attestieren.

## Auswertung der realistischen v1-Kandidaten

Die Primärquellen wurden am 2026-08-21 gegen den Vertrag aus ADR-0048 und
ADR-0049 ausgewertet.

| Kandidat | Belegbare Eigenschaft | Fehlender Vertragsbeweis |
|---|---|---|
| bestehender Docker-Bind-Mount auf ein Hostverzeichnis | Der Output bleibt nach Container-Entfernung für den Host-Consumer erhalten. | Docker isoliert die Kapazität eines Bind-Mounts nicht. Byte-, Objekt- und Reservegrenze sind nicht atomar erzwungen. |
| Docker-`overlay2.size` für den beschreibbaren Container-Layer | Docker dokumentiert eine Größengrenze für den beschreibbaren Layer. | Die Option ist an XFS mit `pquota` gebunden, begrenzt weder Objekte noch eine externe Reserve und passt nicht zum hostseitig erhaltenen Output-Workspace nach Container-Entfernung. |
| container-lokales oder administrativ vorprovisioniertes Host-`tmpfs` | `size`/`nr_blocks` und `nr_inodes` können Byte- und Objektgrenzen einer Mountinstanz begrenzen; ein Host-Mount könnte den Container überleben. | Ein container-lokales Mount verliert beim Unmount seine Daten. Beim Host-Mount ist `size` eine Obergrenze, keine atomar reservierte globale RAM-/Swap-Kapazität außerhalb der Capability. Damit ist der kombinierte Consumer- und Reservevertrag nicht belegt. |
| Docker-Volume mit Local-Driver und `tmpfs`-Mountoptionen | Docker kann Linux-Mountoptionen an den Local-Driver weiterreichen. | Die Lösung delegiert Mount-Authority an den Daemon; direkter Hostzugriff auf Volume-Daten ist kein unterstützter Docker-Vertrag. Der Unmount-Lebenszyklus und die fehlende Reserve brechen weiterhin den ADR-0048-Vertrag. |
| administrativ vorprovisionierte Linux-Quota | Linux-Quotas können harte Block- und Inodegrenzen je Dateisystem durchsetzen. | Setzen und Ändern der Quota benötigt privilegierte Authority. Der aktuelle Vertrag besitzt noch keinen konkreten, unprivilegiert live attestierbaren Slot-Identifier, keinen Beweis gegen Sharing oder Umgehung und keinen gebundenen Reservebeweis für denselben Backing Store. |

FIEMAP liefert nur eine momentane Extent-Abbildung und weist ausdrücklich auf
mögliche Änderungen zwischen Abfragen hin. Es beweist weder das Scheitern des
nächsten Writes noch eine Objektgrenze oder freie Reserve. Es ist daher keine
alternative Budget-Authority.

## Entscheidung

FG-A-WORKSPACE-BACKEND ist als negative, fail-closed Entscheidung
abgeschlossen. Derzeit wird kein Linux-/Docker-Backend für
`archive-bounded-workspace-capability/v1` akzeptiert. Insbesondere werden
weder ein Host-Bind-Mount, ein Docker-Layer, `tmpfs` noch eine nicht näher
attestierte Linux-Quota in die Adapter-Allowlist aufgenommen.

Die bestehende feste Allowlist in `quota_slots.py` bleibt leer. Der neutrale
Provider kann deshalb keine reale Capability ausgeben. S-EBAR-04A, EBAR-06
und jede reale Extraction bleiben `TOOL_UNAVAILABLE`; Listing und Integrity
des bestehenden `archive-linux-container-runner/v1` werden dadurch nicht
erweitert oder zurückgenommen.

Diese Entscheidung macht weder ext4, NTFS, Btrfs, XFS noch FIEMAP zu einer
FolioTone-Voraussetzung. Ein späterer Plattformadapter darf eine konkrete
Dateisystem-, Quota- oder Extent-Eigenschaft lokal nutzen, wenn sein eigenes
Frontier-Gate genau diese Backendidentität, Provisionierung, Live-Attestation
und Conformance bindet. Der FolioTone-Kern konsumiert weiterhin nur die
neutrale Capability.

## Späteres Revalidation-Gate

Ein neues `FG-A-WORKSPACE-BACKEND-REVALIDATION` darf erst beginnen, wenn ein
konkreter administrativ vorprovisionierter Backendkandidat und ein echter
Linux-/Docker-Conformancehost verfügbar sind. Das Gate ist erneut docs-only und
autorisiert selbst keine Implementierung. Es muss mindestens mechanisch
belegbare Antworten für folgende Punkte liefern:

1. unverwechselbare Backend-, Backing-Store-, Slot- und Provisioningidentität;
2. unprivilegierte Live-Attestation unmittelbar vor Lease, Toolstart, Consumer,
   Cleanup und Return;
3. atomare Hardlimits für Byte- und Objektzahl sowie den Beweis der separaten
   Reserve am selben Backing Store;
4. Ausschluss von Sharing, Hardlinks, Symlinks, Reparse Points, Devices,
   Nested Mounts, Reflink-/Snapshot-/Sparse-Umgehungen und fremden Writern;
5. Erhalt desselben privaten Workspace nach bewiesener Container-Abwesenheit
   bis zum synchronen Consumer sowie sichere Invalidierung danach;
6. Crash-, Stale-Lease-, Cleanup-, Empty-Revalidation-, Return- und
   Quarantäneverhalten ohne automatische Wiederverwendung;
7. einen realen Positivtest sowie Einzelmutation jeder Attestation und
   Grenzwerttests für das nächste Byte und Objekt.

Ein administrativ vorbereiteter Mount oder eine Quota kann Teil der lokalen
Trust-Grenze sein. FolioTone darf sie weder erzeugen noch verändern. Ein
Adapter muss jede unerwartete Eigenschaft, fehlende Lesbarkeit oder
Identitätsabweichung geschlossen mit `TOOL_UNAVAILABLE` beziehungsweise bei
bereits geliehenem Slot mit Quarantäne beantworten.

## Aufgabenklasse und Modellrouting

FG-A-WORKSPACE-BACKEND und eine spätere Revalidation sind
Frontier-/Security-Vertragsarbeit mit Risikoklasse hoch. Vorgesehen ist
5.6 Sol mit Thinking `high`. 5.5 ist nur zulässiger Fallback, wenn keine neue
Filesystem-, Quota-, Mount-, Device-, Trust-Root- oder Runtime-Authority
entschieden wird und das fail-closed Ergebnis unverändert bleibt. Spark,
Luna, Terra und ein niedrigeres Thinking-Level sind für die Backendannahme
nicht zulässig.

## Exakte Dateibereiche

FG-A-WORKSPACE-BACKEND ändert oder erzeugt ausschließlich:

```text
docs/decisions/ADR-0050-linux-docker-workspace-backend-unavailable.md
docs/architecture/SAFETY.md
docs/reference/EXTERNAL_TOOLS.md
docs/planning/PROJECT_STATUS.md
docs/planning/HANDOVER.md
docs/planning/BACKLOG.md
docs/planning/EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md
docs/planning/EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md
docs/planning/EBOOK_SPARK_WORK_PACKAGES.md
```

Das spätere Gate darf ausschließlich folgende Dateien ändern oder anlegen:

```text
docs/decisions/ADR-<nächste-freie-Nummer>-<konkretes-backend>.md
docs/architecture/SAFETY.md
docs/reference/EXTERNAL_TOOLS.md
docs/planning/PROJECT_STATUS.md
docs/planning/HANDOVER.md
docs/planning/BACKLOG.md
docs/planning/EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md
docs/planning/EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md
docs/planning/EBOOK_SPARK_WORK_PACKAGES.md
```

Code, Tests, Workflows, Packaging, Runtime-State, Konfiguration und private
Fixtures sind im Revalidation-Gate ausgeschlossen. Erst eine akzeptierte
Backend-ADR darf ein nachfolgendes, separat reviewtes mechanisches
Plattformpaket mit exakten Produktions- und Testdateien autorisieren.

## Checks und Abnahme

Dieses Gate und das Revalidation-Gate führen ausschließlich aus:

- fokussierte bestehende Dokumentationsvertragstests;
- Linkprüfung der neu aufgenommenen Primärquellen und ADR-Verweise;
- strukturierte Widerspruchssuche nach Backend-Allowlist,
  `TOOL_UNAVAILABLE`, S-EBAR-04A, EBAR-06, Mount-/Device-/Root-Authority und
  Dateisystemneutralität;
- `git diff --check` und einen Diff-Allowlist-Nachweis für exakt den oben
  genannten Dateibereich.

Es startet weder Container noch Archivtool, führt keine Runtime-, Workflow-
oder Full-Gate-Ausführung aus und verändert keine Source-, Device-, Mount-,
Quota- oder Runtime-Daten.

## Stopbedingungen

Dieses Gate und das Revalidation-Gate stoppen ohne Backendannahme bei
mindestens einem der folgenden Befunde:

- eine Byte-, Objekt- oder Reserveachse beruht nur auf Polling oder Messung;
- Live-Attestation benötigt zur normalen Laufzeit `root`,
  `CAP_SYS_ADMIN`, Device- oder Mountzugriff für FolioTone;
- Backend oder Slot kann geteilt, umgehbar, nach Capability-Invalidierung
  weiterverwendet oder unbemerkt neu konfiguriert werden;
- Container-Abwesenheit, Consumer-Erhalt, Cleanup, leere Revalidierung,
  Return oder Quarantäne sind nicht in derselben Lifecycle-Kette beweisbar;
- ein positives Ergebnis existiert nur als Fake, Mock, Dokumentbehauptung
  oder privilegierter Einmallauf statt auf dem echten Conformancehost;
- die Lösung macht ein konkretes Dateisystem oder FIEMAP zur allgemeinen
  Projekt- oder Kernvoraussetzung;
- der notwendige Patch überschreitet den docs-only-Dateibereich oder zieht
  S-EBAR-04A, EBAR-06, W10, Secrets, Persistenz oder Source-Mutation vor.

Bei einem Stop bleibt die Allowlist leer und der Zustand
`TOOL_UNAVAILABLE`; ein Teilnachweis wird nicht als Backendfreigabe
umgedeutet.

## Nicht autorisiert

Diese ADR autorisiert nicht:

- ein mechanisches Backend-, S-EBAR-04A- oder EBAR-06-Paket;
- einen Container-, Archivtool-, Mount-, Quota-, Device- oder Workflowlauf;
- das Erzeugen, Formatieren, Mounten oder Umkonfigurieren eines Dateisystems;
- `root`, Linux-Capabilities, einen privilegierten Container oder Hostdevices;
- Source-Mutation, W10, Secrets, Persistenz oder Wrapper-Extraction;
- eine lokale Backend-Allowlist außerhalb eines akzeptierten Folgegates.

## Konsequenzen

- Der neutrale Capability-Vertrag bleibt implementiert und
  dateisystemunabhängig, behauptet aber kein reales Backend.
- Die Sicherheitslücke wird nicht durch Polling, Docker-Konfiguration oder
  einen unvollständigen Quota-Befund kaschiert.
- Ein administrativ vorprovisionierter Kandidat kann später gezielt und lokal
  geprüft werden, ohne den FolioTone-Kern an sein Dateisystem zu binden.
- Bis dahin bleiben S-EBAR-04A und EBAR-06 bewusst blockiert.

## Primärquellen

- Linux-Quota-Subsystem, Block-/Inode-Hardlimits und Capability-Ausnahme:
  https://docs.kernel.org/filesystems/quota.html
- Linux `quotactl(2)`, Abfrage- und Konfigurationsprivilegien:
  https://man7.org/linux/man-pages/man2/quotactl.2.html
- Linux `tmpfs`, `size`, `nr_inodes`, Remount und Datenverlust beim Unmount:
  https://docs.kernel.org/filesystems/tmpfs.html
- Linux FIEMAP, beobachtete Extents und Änderung zwischen Abfragen:
  https://docs.kernel.org/filesystems/fiemap.html
- Docker-Daemon, `overlay2.size` nur mit XFS-`pquota`:
  https://docs.docker.com/reference/cli/dockerd/
- Docker Volume Create, an den Local-Driver weitergereichte Mountoptionen:
  https://docs.docker.com/reference/cli/docker/volume/create/
- Docker Storage, Bind-Mount-, Volume-, Writable-Layer- und tmpfs-Lifecycle:
  https://docs.docker.com/engine/storage/
