# ADR-0049: Dateisystemneutrale Archive-Workspace-Capability

**Status:** Akzeptiert

**Datum:** 2026-08-20

**Geltungsbereich:** FG-A-EXTRACTION-QUOTA, S-EBAR-04Q, S-EBAR-04A und
EBAR-06

## Kontext

ADR-0048 verlangt vor einer realen Archive-Extraction einen hart begrenzten
Workspace. Das schützt vor Archiven, deren tatsächliche Ausgabe größer oder
objektreicher ist als angekündigt. Ein periodischer Verzeichnisscan ist nur
ein zusätzlicher Frühabbruch und kein alleiniger Grenzbeweis.

Diese Sicherheitsanforderung ist eine Eigenschaft des Workspace-Providers,
nicht des FolioTone-Domänenmodells. FolioTone darf deshalb weder ext4, NTFS,
XFS, btrfs noch ein anderes Dateisystem als fachliche Voraussetzung kennen.
Auch Loop-Images, Mountoptionen und Hostwerkzeuge gehören nicht in den
allgemeinen Providervertrag.

## Entscheidung

FG-A-EXTRACTION-QUOTA akzeptiert
`archive-bounded-workspace-capability/v1` als dateisystem- und
plattformneutralen Vertrag. Ein Plattformadapter darf eine Capability nur
ausgeben, wenn sein Backend die geforderten Grenzen atomar durchsetzt und der
Adapter dies mit einem separat akzeptierten, realen Konformitätsgate beweist.

Zulässige Backends können beispielsweise native Quotas, begrenzte
Container-Volumes, dedizierte Dateisysteme oder eine gleichwertige
plattformgebundene Isolation verwenden. Diese Beispiele sind keine
Allowlist. Ein Backend wird erst durch seinen eigenen geprüften Adapter und
nicht durch seinen Dateisystemnamen akzeptiert.

Der FolioTone-Kern erhält keine Mount-, Formatierungs-, Loop-, Device-,
`root`- oder `CAP_SYS_ADMIN`-Authority. Fehlt auf einer Plattform ein
akzeptierter Adapter, bleibt reale Extraction dort `TOOL_UNAVAILABLE`; es gibt
keinen unquotierten Fallback.

## Feste fachliche Grenzen

Jede ausgegebene Capability bindet mindestens:

| Achse | Fester Vertrag |
|---|---|
| Workspace-Gesamtbytes | höchstens `8_589_934_592` Bytes für Input und Output gemeinsam |
| Hostreserve | mindestens `1_073_741_824` Bytes bleiben außerhalb der Capability unverbrauchbar |
| Einzeldatei | höchstens `2_147_483_648` Bytes |
| Archive-Member | höchstens `10_000` |
| Parallelität | höchstens zwei aktive Extraction-Capabilities |
| Lebensdauer | genau ein Lease; nach Return dauerhaft ungültig |

Byte- und Objektgrenze müssen Schreibvorgänge beim Erreichen der Grenze
atomar ablehnen. Vorabprojektion, Listing-Summen, Laufzeitmonitoring und
Deadline bleiben zusätzliche Schutzschichten, ersetzen diese Eigenschaft aber
nicht. Der Adapter darf seine eigenen internen Block-, Inode-, Quota- oder
Reservewerte verwenden, solange sie die obigen fachlichen Grenzen niemals
lockern.

## Provider- und Capability-Grenze

S-EBAR-04Q definiert einen privaten `BoundedArchiveWorkspaceProvider` und eine
underscore-interne immutable Capability. Der Kern sieht ausschließlich:

- opaque Provider- und Lease-Identität;
- Compatibility- und Adapterprofil;
- fest gebundene Byte-, Einzeldatei-, Member- und Parallelitätsgrenzen;
- kurzlebige, nicht serialisierbare Handles für Input- und Outputroot;
- einen wertfreien Attestationsfingerprint;
- `AVAILABLE`, `LEASED`, `RETURNED`, `QUARANTINED` oder `UNAVAILABLE`.

Die Capability enthält keinen frei wählbaren Pfad und darf nicht kopiert,
persistiert oder nach Return wieder geöffnet werden. Private Pfade,
Dateisystem-, Device-, Mount- oder Quotaangaben dürfen weder DTO, Report,
Exception noch persistierte Archive-Evidence verlassen.

Der Lifecycle lautet:

```text
Providerzustand no-follow öffnen
    -> exklusives, generation-gefencetes Lease erwerben
    -> Backendattestation und leeren Workspace beweisen
    -> kurzlebige Capability ausgeben
    -> S-EBAR-04A erzeugt opaque Input-/Output-Jobroots
    -> Container vollständig beenden und Abwesenheit beweisen
    -> genau einen S-EBAR-06A-Consumer im geliehenen Workspace ausführen
    -> Capability für Consumerzugriff invalidieren
    -> Workspace bereinigen und Leere erneut beweisen
    -> Capability invalidieren und Lease zurückgeben
    -> erst danach provisorische Evidence freigeben
```

Cleanup-, Attestations-, Leere-, Return- oder Container-Abwesenheitsfehler
verwerfen jede Evidence, liefern `TOOL_FAILED` und quarantänisieren das Lease.
Ein stale oder unbekannter Zustand wird nie automatisch wiederverwendet.

## Adaptervertrag

Jeder produktive Adapter benötigt vor Freigabe einen eigenen kleinen
Entscheidungs- und Konformitätsnachweis. Dieser muss die konkrete
Plattformtechnik kapseln und mindestens beweisen:

- atomare Ablehnung des nächsten Bytes und des nächsten Objekts an der Grenze;
- gleichzeitig laufende Jobs können weder Grenze noch Hostreserve teilen oder
  umgehen;
- keine Links, Reparse Points, Devices, Nested Mounts oder fremde Roots können
  in den Workspace eingeschleust werden;
- Crash, stale Lease, nicht leerer Return und jede Attestationsmutation führen
  zu Quarantäne;
- Cleanup und Return lassen keine weiterverwendbare Capability zurück;
- der FolioTone-Prozess benötigt keine privilegierten Hostoperationen;
- private Materialbytes und Locator erscheinen weder in Logs noch im
  Konformitätsreport.

Ein Adapter darf backendbezogene Details intern prüfen. Diese Details werden
nicht Teil der öffentlichen Archive-Verträge und nicht zur Voraussetzung für
andere Plattformadapter.

## Paketfolge

S-EBAR-04Q implementiert zunächst ausschließlich die neutrale
Provider-/Capability-, Lease-, Return- und Quarantänelogik mit begrenzten
Fakes. Ein reales Backend wird in einem eigenen Paket
`S-EBAR-04Q-<PLATFORM>` implementiert und durch dessen nicht überspringbares
Konformitätsgate freigegeben. Erst danach dürfen S-EBAR-04A und EBAR-06 auf
dieser Plattform reale Extraction ausführen.

Die neutrale Dateigrenze lautet:

```text
src/foliotone/archive/quota_slots.py
tests/unit/test_archive_quota_slots.py
docs/architecture/SAFETY.md
docs/reference/EXTERNAL_TOOLS.md
docs/planning/BACKLOG.md
docs/planning/PROJECT_STATUS.md
```

Ein Plattformpaket erhält erst in seinem eigenen Gate eine konkrete
Integrationstestdatei und die minimal erforderliche Adapterdatei. ADR-0049
autorisiert noch keinen solchen Adapter und keine privilegierte
Provisionierung.

## Status und Stopbedingungen

Bis ein reales Adaptergate erfolgreich ist, bleibt Extraction
`TOOL_UNAVAILABLE`. Die Implementierung stoppt bei:

- einem nur periodisch erkannten statt atomar verhinderten Gesamtüberlauf;
- einer vom Kern verlangten Dateisystem- oder Mountannahme;
- erforderlicher Runtime-Ausführung privilegierter Hostwerkzeuge;
- einem unquotierten oder gemeinsam überbuchbaren Fallback;
- einer überlebenden, serialisierbaren oder pfadbasiert wiederöffnenden
  Capability;
- automatischer Wiederverwendung unsicherer oder stale Leases;
- nicht beweisbarer Cleanup-, Container-Abwesenheits- oder Returnreihenfolge.

## Supersession

ADR-0049 konkretisiert ADR-0048 ausschließlich durch die neutrale
Workspace-Capability. Es entscheidet bewusst kein Hostdateisystem. Die
Lifecycle-, Status-, Privacy-, Wrapper-, Secret- und W10-Grenzen aus
ADR-0048 bleiben unverändert.

## Folgen

- FolioTone bleibt unabhängig vom Hostdateisystem.
- Sicherheitsgrenzen werden als Fähigkeiten geprüft, nicht aus einem
  Dateisystemnamen abgeleitet.
- Weitere Plattformadapter können ohne Änderung des Domänenvertrags ergänzt
  werden.
- Die neutrale S-EBAR-04Q-Welle kann fortgesetzt werden; reale Extraction
  bleibt bis zum ersten erfolgreichen Adaptergate gesperrt.
- Es werden keine 8-GiB-Testdaten in Git oder den Modellkontext übernommen;
  Konformitätstests werten lokal nur Grenzen und feste Statuscodes aus.

## Primärquellen

- Linux Kernel, Quota-Hardlimits für Speicher und Inodes:
  https://docs.kernel.org/filesystems/quota.html
- Microsoft, NTFS-Datenträgerkontingente:
  https://learn.microsoft.com/windows-server/storage/fsrm/quota-management
- Docker, Storage Driver und schreibbare Container-Layer:
  https://docs.docker.com/engine/storage/drivers/
