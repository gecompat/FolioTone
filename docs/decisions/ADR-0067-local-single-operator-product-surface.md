# ADR-0067: Lokale Einzelbenutzer-Produktoberfläche mit REST-API und Browser-UI

- Status: Accepted
- Datum: 2026-08-23

## Kontext

ADR-0016 begrenzt die anfängliche Produktoberfläche auf die CLI und verlangt
für jeden späteren UI- oder Service-Scope eine eigene Architekturentscheidung.
Inzwischen sind die book-only Produktprojektionen `CollectionState`, lokale
Suche und `Library Health` umgesetzt. Für die E-Book-Linie existieren außerdem
drei voneinander getrennte, operativ vollständige W10-Ketten: die enge
ADR-0056-Interim-Quarantäne, der EPUB-3-Titelwriter aus ADR-0063/ADR-0064 und
der Same-Parent-`FILE_RENAME` aus ADR-0066.

FUT-011 muss entscheiden, wie diese und die übrigen read-only Funktionen über
eine REST-API und grafische Oberfläche erreichbar werden, ohne CLI-Logik zu
duplizieren, private Sammlungsdaten offenzulegen oder aus einer Oberfläche
neue Mutation Authority abzuleiten. Die erste Auslieferung ist ausdrücklich
für genau einen lokalen Benutzer vorgesehen. Music, Bilder und weitere Linien
sollen später eigene fachliche Einstiege erhalten, dürfen aber nicht durch
eine vorzeitige universelle Mediendomäne vorweggenommen werden.

## Entscheidung

FolioTone erhält die versionierte Produktoberfläche
`local-single-operator/v1`. Sie besteht aus einer lokalen, same-origin
ausgelieferten Browser-UI, einer REST-API unter `/api/v1`, adapterneutralen
`ApplicationCommand`-/`ApplicationQuery`-Verträgen sowie getrennten passiven
Workern. Die CLI bleibt unterstützt und verwendet schrittweise dieselben
Application-Verträge.

Die Umsetzung erfolgt ausschließlich über die vier in dieser ADR festgelegten
Waves `S-FUT11-01` bis `S-FUT11-04`. Die Annahme dieser ADR implementiert noch
keinen HTTP-Server, Benutzer, Worker und kein UI-Control.

## Application-Grenze

CLI, HTTP-Adapter und Worker dürfen keine voneinander abweichende Domainlogik
besitzen. Die neue Application-Grenze stellt versionierte, immutable Request-,
Result- und Fehlerverträge bereit und komponiert die vorhandenen Services aus
`foliotone.workflows`. Sie importiert weder HTTP- noch UI-Frameworktypen und
keine konkrete Persistenzimplementierung.

Die Umstellung erfolgt inkrementell. Bestehende Workflows werden nicht in
einem unbeschränkten Refactor verschoben. Jeder Slice beweist mindestens einen
fachlichen Weg über zwei Adapter, bevor weitere Commands oder Queries
übernommen werden. CLI-Ausgabe- und Exit-Code-Verträge bleiben dabei erhalten.

Ein `ApplicationCommand` kann einen dauerhaften Job anlegen, besitzt dadurch
aber weder Source-Media-Write-Authority noch eine W10-Authorization. Eine
`ApplicationQuery` liest nur die für ihre Projektion erlaubte Persistenz. Die
Composition Root stellt Abhängigkeiten bereit; Domain- und Workflowcode
importieren weder CLI noch REST noch Frontend.

## Medienlinien und Navigation

Eine kleine Registry beschreibt stabile Medienlinien-IDs, Anzeigenamen,
Aktivierungszustand, read-only Capabilities und freigegebene
Operations-Capabilities. In `local-single-operator/v1` ist ausschließlich
`EBOOK` aktiv. `MUSIC` und `IMAGE` besitzen getrennte, als nicht aktiviert
erkennbare Navigationseinstiege, aber keine vorgetäuschten fachlichen
Endpunkte oder Datenmodelle.

Die gemeinsame Shell enthält mindestens:

- Übersicht und `Library Health`;
- E-Books mit Scan/Readiness, Bestand/Suche, Analyse/Quality,
  Metadaten/Authority/Classification, Duplicate-/Varianten-Evidence, Review,
  Plänen sowie getrennten Operation-/Recovery-Ansichten;
- System mit Tool-Readiness, Capabilities, Jobs und Audit;
- getrennte inaktive Einstiege für Musik und Bilder.

Gemeinsame Infrastruktur umfasst Navigation, Authentisierung, Jobs, Audit und
Designsystem. `Work`/`Edition`, `MusicWork`/`Recording`/`Release` und spätere
Bildidentitäten bleiben fachlich getrennt. Diese ADR führt keinen
universellen `Asset`-Typ ein.

Die erste UI ist desktop-orientiert und responsiv. Sichtbare Texte sind
deutsch; Frontendtexte verwenden von Beginn an stabile Translation Keys,
damit eine weitere Sprache später keine fachlichen API-Verträge ändert.

## Lokales Deployment und Prozessgrenzen

Der öffentlich erreichbare Endpunkt des v1-Profils bindet ausschließlich an
eine explizite Loopback-Adresse. Ein nativer Prozess akzeptiert keine
Wildcard-, LAN- oder öffentliche Bindung. Für Docker oder Podman darf ein
ausdrücklich aktivierter Containeradapter nur innerhalb eines erkannten,
isolierten Container-Network-Namespace auf `0.0.0.0` hören, wenn Compose den
Port fest auf `127.0.0.1` des Hosts veröffentlicht. Die Application-
Konfiguration, Host- und Origin-Allowlist bleiben dabei auf der lokalen
same-origin Adresse; Proxy-Header bleiben unvertraut. Der Adapter wird
außerhalb eines erkannten Containers fail-closed abgelehnt. Diese technische
Portübergabe öffnet weder LAN- noch Remotebetrieb.

Das Deployment trennt mindestens drei Rollen:

1. `surface-api` liefert UI und REST aus, verwaltet Auth-/Session-/Jobzustand
   und besitzt keinen Source-Media-Mount sowie keine W10-Capability-Datei.
2. `analysis-worker` pollt die dauerhafte Jobqueue, erhält Source Media nur
   read-only und führt ausschließlich freigegebene Scan-, Analyse- und
   Projektions-Commands aus.
3. `operator-worker` besitzt keine eingehende Netzwerkschnittstelle, läuft im
   v1-Profil mit `network=none` und kann ausschließlich ausdrücklich
   registrierte W10-Commands konsumieren. Nur dieser Prozess darf für genau
   den jeweiligen Operationsvertrag die private Capability-Konfiguration und
   den erforderlichen beschreibbaren Source-Mount erhalten.

Alle drei Prozesse verwenden owner-geschützte Runtime-Konfiguration und
Persistenz außerhalb von Git. Der lokale Betrieb darf sie als getrennte
Prozesse oder Container starten; ihre Sicherheitsrollen dürfen nicht zu einem
Webprozess mit allgemeinem Source-Schreibzugriff zusammenfallen.

Das read-only Compose-Basisprofil darf ohne Writer-Konfiguration startbar sein.
Der `operator-worker` wird nur über ein separates operation-spezifisches
Overlay ergänzt, das ohne exakte Dependency-Scope-Datei, Capability-Datei und
autorisierten schreibbaren `ScanRoot` bereits bei der Compose-Auswertung
fail-closed endet.

Die Browser-UI wird als versionierter statischer Build vom `surface-api`
same-origin ausgeliefert. Die Laufzeit lädt keine Skripte, Fonts, Analytics
oder andere Assets von externen Hosts. Ein Build-Tool ist keine zusätzliche
Produktionsruntime.

Ein späterer Remote- oder Mehrbenutzerbetrieb benötigt eine neue ADR mit TLS,
Secure-Cookie-, Trusted-Proxy-, Benutzerverwaltungs-, Rollen-, Rate-Limit-,
Backup- und Betriebsvertrag. Die lokale ADR darf dafür nicht durch einen
Konfigurationsschalter aufgeweitet werden.

## Erstbenutzer, Benutzername und Passwort

Es gibt in v1 genau ein lokales Konto. Ein leerer Benutzerbestand zeigt in der
UI nur `SETUP_REQUIRED`; der erste Webbesucher darf sich nicht ohne lokalen
Besitznachweis zum Administrator machen.

Der owner-geschützte lokale Befehl `foliotone auth-bootstrap` erzeugt mit
einem CSPRNG einen einmaligen Bootstrap-Code mit mindestens 128 Bit Entropie.
Der Klartext wird genau einmal am lokalen Terminal ausgegeben und gelangt
weder in URL, argv, Environment, Log, Audit noch Persistenz. Gespeichert
werden nur domänengetrennter Digest, Erzeugungs-/Ablaufzeit, Versuchszähler
und Verbrauchszustand. Der Code gilt höchstens 15 Minuten, besitzt eine harte
Versuchsgrenze und wird beim erfolgreichen atomaren Anlegen des ersten Kontos
verbraucht. Ein lokaler Launcher darf diesen expliziten Befehl vor dem Öffnen
des Browsers ausführen; der HTTP-Dienst erzeugt oder veröffentlicht den Code
nicht selbst.

Der Setup-Dialog verlangt Bootstrap-Code, Benutzername und Passwort. Der
Benutzername umfasst 3 bis 64 Unicode-Codepoints, besitzt keine Steuerzeichen
oder führenden beziehungsweise abschließenden Leerzeichen und wird in
Originalform gespeichert. Ein zusätzlicher versionierter `NFKC`- plus
`casefold()`-Key erzwingt Eindeutigkeit. Das erste Konto erhält die lokale
Administratorrolle; v1 enthält keine weitere Benutzeranlage.

Passwörter:

- besitzen 15 bis 1.024 Unicode-Codepoints und höchstens 4.096 UTF-8-Bytes;
- erlauben Leerzeichen, Unicode und Einfügen aus einem Passwortmanager;
- verwenden keine zusätzlichen Groß-/Kleinbuchstaben-, Ziffern- oder
  Sonderzeichenregeln und keinen periodischen Wechselzwang;
- werden gegen eine kleine lokale Liste häufig verwendeter beziehungsweise
  kompromittierter Werte geprüft, ohne dafür eine Netzwerkanfrage zu senden;
- werden vor Längenprüfung und Hashing ausschließlich nach Unicode `NFC`
  normalisiert, niemals getrimmt oder per `casefold()` verändert;
- werden vollständig und ohne stille Kürzung verarbeitet;
- werden ausschließlich als gesalzener Argon2id-Hash mit gespeicherter
  Parameter- und Profilversion persistiert.

Die exakten Argon2id-Kosten werden in `S-FUT11-02` auf der unterstützten
Laufzeit so festgelegt, dass sie mindestens die dann aktuelle OWASP-Untergrenze
erfüllen und lokal gemessen ausreichend gegen Online- und Offline-Raten
schützen. Tests verwenden einen ausdrücklich getrennten Testparameter-Satz;
dieser ist kein Produktionsfallback.

`foliotone auth-reset` ist der einzige v1-Recoveryweg für ein vergessenes
Passwort. Der lokale, owner-geschützte Befehl nimmt das neue Passwort verdeckt
über TTY beziehungsweise begrenztes `stdin`, niemals über argv oder
Environment. Ein Reset widerruft alle Sessions, Operator-Grants und offenen
Bootstrap-/Reset-Tokens. Sicherheitsfragen, Passwort-Hints und E-Mail-Recovery
existieren nicht.

## Sessions und Autorisierung

Nach erfolgreicher Anmeldung erzeugt der Server eine opaque, vollständig
zufällige Session-ID mit mindestens 128 Bit Entropie. Nur ihr Digest wird
serverseitig gespeichert. Der Browser erhält sie ausschließlich als
nicht persistentes, host-only Cookie mit `HttpOnly`, `SameSite=Strict`,
`Path=/` und ohne `Domain`; Authentisierungstoken werden nicht in
`localStorage` oder `sessionStorage` gespeichert. Bei TLS ist `Secure`
verpflichtend. Das reine Loopback-HTTP-Profil dokumentiert die verbleibende
lokale Transportgrenze und darf nie auf eine nicht lokale Adresse erweitert
werden.

Session-IDs werden bei Login, Passwort-Reauthentisierung und Privilegwechsel
rotiert. Inaktivitäts- und absolute Ablaufgrenzen werden serverseitig
erzwungen; Logout, Passwortreset und Deaktivierung widerrufen die Session
sofort. Login-, Bootstrap- und Reauthentisierungsversuche besitzen persistente,
begrenzte Rate Limits mit Backoff, aber keine unbegrenzt wirksame
Kontosperrung.

State-changing Requests verwenden keine `GET`-Methode. Sie benötigen eine
sessiongebundene CSRF-Protection, exakte Origin-/Host-Prüfung und einen
JSON-Content-Type. CORS ist im v1-Profil nicht aktiviert. Fehlt ein für die
Anfrage notwendiger Security Header oder Binder, endet die Anfrage
fail-closed.

Die erste Rolle besitzt intern getrennte Scopes für `READ`, `PRIVATE_READ`,
`REVIEW`, `OPERATE` und `ADMIN`. Das einzige lokale Administratorkonto erhält
alle Scopes, aber jeder Endpoint prüft weiterhin den engsten Scope. Dadurch
kann ein späteres Rollenmodell ergänzt werden, ohne read-only und mutierende
Authority nachträglich auseinanderbrechen zu müssen.

## Private- und Operator-Modus

Normale API- und UI-Projektionen bleiben pfad-, locator-, metadatawert-,
hash-, secret- und capabilityfrei. Private Werte werden nicht durch einen
Query-Schalter auf Standardendpunkten freigegeben.

Für private Ansichten oder einen schreibenden Ablauf muss der Benutzer sein
Passwort erneut eingeben. Erfolgreiche Reauthentisierung rotiert die Session
und erzeugt serverseitig einen höchstens 15 Minuten gültigen, auf die konkrete
Scopeklasse begrenzten `OperatorGrant`. Ein `OperatorGrant` ist weder eine
W10-Capability noch eine `EbookRenameAuthorizationSnapshot`,
`MetadataWriteAuthorizationSnapshot` oder
`QuarantineAuthorizationSnapshot`.

Private Projektionen liegen unter einem getrennten `/api/v1/private`-Zweig,
verwenden `Cache-Control: no-store` und geben höchstens ScanRoot-relative
Locator aus. Absolute Hostpfade, Capability-Inhalte, Secrets, rohe Inhalte
und vollständige Collection-Exporte bleiben auch dort ausgeschlossen.
Private Werte erscheinen nicht in URLs, Jobs, Auditdetails oder allgemeinen
Fehlern.

## REST- und Fehlervertrag

Die öffentliche v1-Fläche liegt unter `/api/v1`. Fachliche E-Book-Ressourcen
liegen unter `/api/v1/ebooks`; System-, Session-, Job- und Registry-Ressourcen
bleiben getrennt. Nicht aktivierte Medienlinien werden nur durch die Registry
beschrieben und erhalten keine leeren fachlichen CRUD-Endpunkte.

Der Vertrag verwendet eine bei der Implementierung gepinnte OpenAPI-3.1-
Patchversion. Das erzeugte Schema ist ein versioniertes Testartefakt; ein
unbeabsichtigter Breaking Change bricht den Contract-Test. Framework- oder
ORM-Schemas definieren weder Domainmodell noch Persistenzvertrag.

Mit Ausnahme einer minimalen Health-/Versionsauskunft und des nur bei leerem
Benutzerbestand aktiven Setup-Handshakes benötigt jeder Endpoint eine gültige
Session und den engsten Scope. UI und API setzen eine feste Content Security
Policy ohne Inline-Script oder `eval`, `frame-ancestors 'none'`,
`X-Content-Type-Options: nosniff` und `Referrer-Policy: no-referrer`. Externe
CDNs und Analytics sind im v1-Profil nicht zulässig.

Weitere Regeln:

- Listen verwenden opaque Keyset-Cursor, eine Defaultgröße von 50 und ein
  hartes Maximum von 100; collection-weite ungebundene Antworten existieren
  nicht.
- Request Bodies sind standardmäßig auf 1 MiB begrenzt; fachlich kleinere
  Grenzen gelten zusätzlich.
- Commands benötigen einen bounded `Idempotency-Key`. Derselbe Actor, Command
  und semantische Input erzeugen denselben Job beziehungsweise dasselbe
  Ergebnis; ein Key mit anderem Input wird abgewiesen.
- Langlaufende Scans, Analysen, Builds und Operator-Commands sind dauerhafte
  `ApplicationJob`-Ressourcen. v1 verwendet Status-Polling; WebSockets oder
  Server-Sent Events sind keine Voraussetzung.
- Fehler verwenden `application/problem+json` nach RFC 9457 mit stabilen
  FolioTone-Fehlercodes. Stacktraces, SQL, private Werte, Pfade,
  Commandzeilen, Tokens und Capability-Details werden nicht ausgegeben.
- Response- und Logfelder verwenden feste Allowlists. Correlation- und Job-ID
  sind opaque und enthalten keine fachlichen oder privaten Werte.

## Dauerhafte Jobs und Worker-Fencing

Die Jobqueue liegt in der lokalen Persistenz und ist nach Prozessneustart
fortsetzbar. Ein immutable Command-Envelope bindet Actor, Commandprofil,
Input-Digest, Idempotency-Key, Erzeugungszeit und die minimal notwendigen
opaque Referenzen. Passwort, Bootstrap-/Reset-Code, Raw Confirmation,
absolute oder relative Locator und Metadatenwerte gehören nicht in den
Envelope.

Ein Worker beansprucht einen Job über Lease, Heartbeat und monotones Fencing.
Jobevent und fachliche Persistenz werden soweit möglich atomar geschrieben;
die bestehenden `ScanRootWriteLease`- und W10-Fences bleiben autoritativ und
werden nicht durch eine Joblease ersetzt. Der UI-Status unterscheidet
mindestens wartend, aktiv, erfolgreich, technisch fehlgeschlagen, abgebrochen
und recoverypflichtig.

Ein abgelaufener Worker-Lease erzeugt sichtbare Diagnose. Read-only,
nachweislich idempotente Jobs dürfen nach dem in ihrer Commanddefinition
festgelegten Vertrag wieder aufgenommen werden. Ein W10-Job wird nach einer
möglichen irreversiblen Grenze niemals still erneut ausgeführt; er wechselt
in den operation-spezifischen Status-/Recoveryweg. Der dauerhaft laufende
Worker ist deshalb kein Auto-Recovery-Schalter.

## Threat Model und Restgrenzen

Der v1-Vertrag begrenzt insbesondere First-Visitor-Takeover, Session-
Fixation, CSRF, DNS-Rebinding über fremde Hostwerte, versehentliche LAN-
Exposition, doppelte Commandannahme, stale Worker und einen direkten
Source-Write aus einem kompromittierten Webprozess. W10 bleibt zusätzlich
durch seine eigenen Capability-, Authorization-, Fencing-, Journal- und
Recoveryverträge geschützt.

Nicht gelöst werden ein kompromittierter oder administrativ kontrollierter
Host, Malware beziehungsweise bösartige Browser-Erweiterungen im lokalen
Benutzerkontext, ein externer Prozess mit eigener Source-Schreibauthority oder
die Beobachtung des Loopback-HTTP-Verkehrs durch einen privilegierten lokalen
Angreifer. Deshalb darf dieses Profil keine nicht lokale Adresse bedienen.
Ein Remoteprofil muss TLS und die übrigen in dieser ADR zurückgestellten
Betriebsverträge neu entscheiden.

## Audit

Authentisierung, Bootstrap/Reset, Sessionwiderruf, Reauthentisierung,
Scopeprüfung, Jobannahme/-abschluss und jede W10-Anforderung erzeugen
append-only Auditereignisse. Audit speichert Actor-ID, Ereignistyp,
Entscheidung, Correlation-/Job-/Run-ID, feste Finding-Codes und Zeitpunkte,
aber keine Passwörter, Codes, Sessionwerte, CSRF-Werte, Confirmation-Texte,
Pfade, Locator, Metadatenwerte, Hashes oder Capability-Inhalte.

Audit ist keine W10-Journalersetzung. Die operation-spezifischen append-only
Events bleiben der alleinige Nachweis für Authorization, physische Ausführung,
Verifikation und Recovery.

## Schreibende UI-Grenze

`S-FUT11-04` öffnet als ersten und einzigen GUI-Writer den bereits vollständig
implementierten Same-Parent-`FILE_RENAME` aus ADR-0066. Proposal, private
Preview, Review, Plan, Authorize, Execute, Status und Recovery rufen dieselben
Application-Services und Profile wie die CLI auf.

Vor Execute sind gleichzeitig erforderlich:

1. ein aktiver `OPERATE`-Grant nach Passwort-Reauthentisierung;
2. die vorhandene höchstens 15 Minuten gültige One-use-W10-Authorization;
3. die exakt eingegebene aktionsspezifische Bestätigung
   `CONFIRM EBOOK RENAME <Authorization-ID>`;
4. ein frischer Job- und `ScanRootWriteLease`-/W10-Fence-Vertrag im
   `operator-worker`.

Die Raw Confirmation wird weder persistiert noch in den Job-Envelope
geschrieben. Ein Klick, ein allgemeiner Operator-Modus oder ein API-
Idempotency-Key ersetzt keine dieser Bedingungen. Das UI darf keine
zusätzliche Targetauswahl während Authorize oder Execute einführen.

EPUB-Titelwrite und Interim-Quarantäne erhalten erst in späteren, jeweils
eigenen Produktoberflächen-Waves Controls. Ihre vorhandenen CLI- und W10-
Verträge bleiben unverändert. Sidecar-, Calibre-/externe-Library-,
Reorganisations-, Archive-, Rollback-, Purge- und Cleanup-Operationen bleiben
ohne akzeptierten technischen Vertrag oder vollständige Kette vollständig
unerreichbar.

## Lieferfolge

### S-FUT11-01 — Application Surface Contracts

Der erste Slice ergänzt die adapterneutralen Command-/Query-/Context-/Error-
Verträge, die Media-Line-Registry und eine Composition Root über vorhandenen
Workflows. Er führt mindestens Tool-/Format-Readiness und `Library Health` als
erste read-only E-Book-Queries über die gemeinsame Grenze und stellt die
betroffenen CLI-Wege ohne Ausgabeänderung darauf um.

Ausgeschlossen bleiben HTTP-/Frontend-/Auth-Abhängigkeiten, Migrationen,
Jobs, Worker und Source-Media-Mutation. Die Wave ist `BALANCED`; eine
unerwartete Domain- oder Securityentscheidung stoppt sie für ein
`FRONTIER`-Review.

### S-FUT11-02 — Lokale Auth-, API- und Worker-Basis

Der zweite Slice evaluiert und pinnt einen gepflegten Python-ASGI-/OpenAPI-
Stack sowie die Argon2id-Implementierung gegen offizielle Dokumentation,
Lizenz und Security-Hinweise. Er implementiert additive Auth-, Session-,
Bootstrap-/Reset-, Grant-, Audit-, Job-, Event- und Lease-Persistenz,
`auth-bootstrap`, `auth-reset`, Login/Logout/Reauthentisierung, die
loopback-only `/api/v1`-Shell, OpenAPI-Contract-Tests und die drei
Prozessrollen. Der `operator-worker` besitzt in dieser Wave keine registrierte
W10-Capability und kann keine Source-Mutation ausführen.

Die Wave ist `FRONTIER`. Sie stoppt, wenn Loopback-Fencing,
Session-/CSRF-Schutz, Passwortspeicherung, SQLite-Job-Fencing oder die
Trennung von API-, Analyse- und Operatorprozess nicht nachweisbar ist.

### S-FUT11-03 — Read-only E-Book-Oberfläche

Der dritte Slice liefert die deutschsprachige responsive Shell und die
read-only E-Book-Wege für Scan/Status, Tool-/Format-Readiness,
CollectionState, Suche, `Library Health`, Analyse-/Quality-Coverage,
Duplicate-/Varianten-Evidence, Review-Queues und nicht ausführbare Pläne.
Langlaufende Commands verwenden Jobs; Listen verwenden Keyset-Pagination.
Private relative Locator benötigen den getrennten zeitbegrenzten
`PRIVATE_READ`-Grant und `no-store`-Endpunkte.

Musik und Bilder bleiben als getrennte nicht aktivierte Einstiege sichtbar.
Es gibt in dieser Wave keine W10-Route und kein schreibendes Control. Die Wave
ist `BALANCED`; jeder Bedarf an Source-Zugriff im API-Prozess oder an
unbegrenzten beziehungsweise private Daten ausgebenden Responses ist ein
Stop-Grund.

### S-FUT11-04 — Same-Parent-Rename als erster GUI-Writer

Der vierte Slice adaptiert ausschließlich ADR-0066 einschließlich Proposal,
Preview, Review, Plan, Authorize, exakter Bestätigung, Execute, Status,
Recovery, Folgescan, `CollectionState` und Reconciliation. Nur der getrennte
`operator-worker` löst die owner-only Capability auf und erhält den dafür
notwendigen beschreibbaren Mount. API und UI behalten keinen Source-Mount.

Die Wave ist `FRONTIER`. Sie stoppt bei jeder semantischen Abweichung von den
bestehenden ADR-0066-Profilen, breiterer Capability, fehlender
Reauthentisierung, persistierter Raw Confirmation, stiller Wiederholung nach
der irreversiblen Grenze oder unvollständigem Recovery-/Reconciliationweg.

## Ressourcenschonende Verifikation

Jede Implementierungswave verwendet ausschließlich kleine synthetische
Fixtures und temporäre SQLite-Datenbanken beziehungsweise Filesysteme unter
den vorgesehenen Testpfaden. Lokale Prüfungen beginnen mit den neuen Unit-,
Contract-, Security-, Migration-, Privacy- und Adapterfällen sowie direkt
betroffenen Regressionen. Browser-E2E wird auf die geänderten Kernwege
begrenzt. Reale E-Books, private Runtime-Daten, Docker und externe Provider
sind kein Entwicklungs-Gate, sofern die konkrete Wave sie nicht für einen
bereits dokumentierten Konformitätsnachweis benötigt.

Pro stabiler PR-Wave läuft genau ein vollständiger CI-Gate. Ein fehlgeschlagener
Gate wird anhand neuer Fehlersignaturen gezielt diagnostiziert; vollständige
lokale Suiten werden nicht pro Iteration wiederholt.

## Nicht autorisiert

Diese ADR autorisiert nicht:

- Remote-/LAN-/öffentlichen oder Mehrbenutzerbetrieb;
- OAuth, SSO, E-Mail-Recovery oder Benutzer-Self-Service;
- MCP, WebSockets, Server-Sent Events oder eine native Desktop-Anwendung;
- fachliche Music-, Image- oder weitere Medienendpunkte;
- absolute Pfadausgabe oder vollständige private Collection-Exporte;
- eine neue oder verbreiterte W10-Capability;
- automatische W10-Retries, Batchwrites oder stilles Recovery;
- Controls für EPUB-Titelwrite, Quarantäne oder andere Writer vor ihrer
  jeweils eigenen Produktoberflächen-Wave.

## Geprüfte Leitquellen

Die Security- und API-Entscheidung wurde am 2026-08-23 gegen folgende
aktuelle Leitquellen geprüft:

- NIST SP 800-63B, Password Authenticators:
  https://pages.nist.gov/800-63-4/sp800-63b.html#passwordver
- OWASP Password Storage Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- OWASP Authentication Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- OWASP Session Management Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- OWASP Cross-Site Request Forgery Prevention Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- OpenAPI Specification:
  https://spec.openapis.org/oas/
- RFC 9457, Problem Details for HTTP APIs:
  https://www.rfc-editor.org/rfc/rfc9457.html

## Folgen

- FUT-011 ist entschieden und `S-FUT11-01` wird der nächste reguläre
  Produkt-Slice.
- Die aktuelle ausführbare Produktoberfläche bleibt bis zur jeweiligen
  Implementierungswave die CLI; die ADR behauptet keinen bereits vorhandenen
  Server oder Browserclient.
- Lokaler Einzelbenutzerbetrieb erhält einen migrationsfähigen Security-
  Vertrag, ohne einen unbegrenzten Remote- oder Mehrbenutzerscope
  vorzutäuschen.
- Weitere Medienlinien können dieselbe Shell-, Auth-, Job- und Audit-
  Infrastruktur verwenden, behalten aber eigene Domainmodelle, Routen und
  Capabilities.
- Die erste schreibende Browser-Wave kann nur den bereits vollständig
  gefenceten Same-Parent-Rename erreichen. Alle anderen Writer bleiben
  unabhängig geschlossen.
