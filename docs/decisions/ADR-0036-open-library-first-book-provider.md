# ADR-0036: Open Library ist der erste begrenzte reale Book Provider

- Status: Accepted
- Datum: 2026-08-19
- Ergänzt: 2026-08-20

## Kontext

EB-03A implementiert den providerneutralen Cache- und Runtime-Vertrag aus
ADR-0035. FG-03B muss vor einem realen Adapter festlegen, welche öffentliche
Quelle, Endpoints, Queryfelder, DTOs, Betriebsgrenzen und Lizenzfolgen Spark
mechanisch umsetzen darf.

Die Open-Library-Dokumentation beschreibt getrennte `Work`-, `Edition`- und
`Author`-Records, direkte JSON-Endpunkte, einen Search-Endpunkt und monatliche
Dumps. Die [Usage Guidelines](https://openlibrary.org/developers/api) verlangen
low-volume/high-value Nutzung, Caching und einen identifizierenden
`User-Agent`. Sie verbieten HTML-Scraping und API-Bulk-Harvesting. Die
[Licensing-Seite](https://openlibrary.org/developers/licensing) erklärt, dass
Internet Archive keine neuen Rechte an Datenbankinhalten beansprucht, weist
aber ausdrücklich auf mögliche bestehende Rechte einzelner Beiträge und
Jurisdiktionen hin. Daraus folgt keine pauschale Erlaubnis, Rohantworten oder
einen abgeleiteten Gesamtkatalog weiterzuverbreiten.

## Entscheidung

Open Library bleibt der erste reale Book Provider. Der kanonische
`provider_id` lautet `openlibrary`. Der Adapter ist ein optionaler
`ONLINE_STRUCTURED`-Provider für gezielte bibliografische Lookups. Er ist kein
Backend für Collection-Scans und kein allgemeiner Authority-Mirror.

Die Freigabe stützt sich nicht auf die in den Usage Guidelines genannte
Priorisierung von Open-Source-Projekten. FolioTone erfüllt für diesen Slice die
entscheidenden Betriebsgrenzen durch ausdrücklich konfigurierte,
niedrigvolumige und nutzerbezogene Lookup-Aufrufe, privaten Cache und die
strikte Bulk-Sperre. Sollte das Produkt zu einem hochfrequenten oder
kommerziellen Provider-Backend werden, gilt diese ADR nicht als ausreichende
Freigabe; vor weiterer Nutzung ist Open Library zu kontaktieren und ein neues
Gate erforderlich.

Die festen Versionswerte des um den Contributor-Vertrag ergänzten Adapters
lauten:

```text
provider_adapter_version = openlibrary-book-adapter/v2
provider_source_version = openlibrary-web-api-docs-2026-08-20
mapping_profile_version = openlibrary-book-mapping/v2
normalized_source_profile = openlibrary-source-record/v2
payload_codec = json/openlibrary-source-dto-v2
```

Eine Änderung an Endpoint-Shapes, erlaubten Feldern, Identifiernormalisierung,
DTO-Semantik oder Mapping erhöht die betroffene Version. Open Library stellt
keine versionierte API-Semver bereit; deshalb bindet
`provider_source_version` die geprüfte Dokumentationsbasis und Endpoint-
Allowlist an dieses Datum.

Die v2-Erhöhung ist erforderlich, weil die erste Parser-/Mapper-Umsetzung den
angeforderten Search-Wert `author_name` verwarf und dadurch den Vertrag von
S-EB03B-05 für Contributor ohne `OL<number>A`-Referenz nicht erfüllen konnte.
`openlibrary-source-record/v1` und `json/openlibrary-source-dto-v1` werden
nicht als v2 interpretiert oder in-place umgeschrieben. Der Wechsel von
`provider_adapter_version` trennt gemäß ADR-0035 auch den `source_cache_key`;
`openlibrary-book-mapping/v2` erzeugt einen getrennten `mapping_input_key`.
Query-Reihenfolge, HTTP-Shapes, Transportgrenzen und TTLs ändern sich nicht.

## Freigegebene Query-Reihenfolge

Pro `BookKnowledgeQuery` wird die erste vorhandene gültige Identifierklasse in
dieser Reihenfolge verwendet. Eine Invocation fragt genau diese eine
Identifierklasse ab; `NOT_FOUND` schaltet nicht im selben Aufruf auf einen
schwächeren oder disclosure-reicheren Schlüssel weiter. Ein späterer Aufruf
darf nach ausdrücklicher Planung die nächste Klasse wählen.

1. `openlibrary.edition` mit exakt einem `OL<number>M`;
2. `openlibrary.work` mit exakt einem `OL<number>W`;
3. `isbn13` als 13 Ziffern nach Entfernen von ASCII-Bindestrichen und
   ASCII-Leerzeichen;
4. `isbn10` als neun Ziffern plus Ziffer oder `X`;
5. `oclc` als 1 bis 16 ASCII-Ziffern;
6. `lccn` als 1 bis 32 ASCII-Buchstaben, Ziffern oder Bindestriche;
7. normalisierter `title` plus genau ein bereits lokal aufgelöster Author-Name.

Mehrere Werte derselben Klasse werden nach NFC-Normalisierung dedupliziert und
lexikografisch sortiert. Pro Klasse wird höchstens der erste Wert abgefragt.
Nur Titel, mehrere nicht aufgelöste Author-Namen und freie Suchstrings lösen
keinen automatischen Online-Aufruf aus. Der Titel-Author-Fallback erhält ein
adapterspezifisches `OpenLibraryResolvedAuthorQuery` mit `title`, genau einem
`resolved_author_name` und der opaken ID der akzeptierten lokalen
Resolution-Entscheidung; nur Titel und Author-Name verlassen den Prozess. Die
lokale Decision-ID wird weder übertragen noch Teil des Source-Payloads.
`openlibrary.author` ist kein primärer Book-Lookup; ein `Author`-Record darf nur
über eine bereits in einem freigegebenen Book-Ergebnis enthaltene
`OL<number>A`-Referenz nachgeladen werden.

Titel und Author-Name sind jeweils höchstens 512 Unicode-Codepoints lang. Der
Fallback lehnt NUL, CR/LF, `://`, `file:`, `..`, `/`, `\`, einen
ASCII-Drive-Prefix wie `C:` sowie die case-insensitiven Endungen `.epub`,
`.mobi`, `.azw`, `.azw3` und `.pdf` ab. Die Ablehnung ist ein path-freier
lokaler Validierungsfehler und startet keinen Transport.

## Freigegebene HTTP-Shapes

Der Transport verwendet ausschließlich `GET`, HTTPS, Host
`openlibrary.org`, Port 443 und die folgenden Shapes. Queryparameter werden
RFC-3986-konform kodiert und in der angegebenen Reihenfolge erzeugt.

| Zweck | Exaktes Shape |
|---|---|
| `Edition` per OLID | `/books/{edition_olid}.json` |
| `Work` per OLID | `/works/{work_olid}.json` |
| `Author` per referenzierter OLID | `/authors/{author_olid}.json` |
| `Edition` per ISBN | `/isbn/{isbn}.json` |
| OCLC/LCCN per dokumentierter Books API | `/api/books?bibkeys={KIND}:{value}&jscmd=data&format=json` |
| Titel plus Author | `/search.json?title={title}&author={author}&fields={field_allowlist}&limit=10&offset={offset}` |

`KIND` ist ausschließlich `OCLC` oder `LCCN`. Die generische Books API ist in
der [offiziellen Book-API-Dokumentation](https://openlibrary.org/dev/docs/api/books)
als Legacy-Endpunkt und Search als bevorzugter Mehrfachzugriff gekennzeichnet.
Sie bleibt für v1 nur für OCLC/LCCN erlaubt, weil dieselbe Primärquelle diese
Identifier ausdrücklich unterstützt. Eine Entfernung, Umleitung oder
inkompatible Änderung erzeugt `PERMANENT_FAILURE` und stoppt diese Route; der
Adapter weicht nicht auf HTML, undokumentierte Solr-Felder oder den Read API
aus.

Die Search-`field_allowlist` ist exakt die kommaseparierte Folge:

```text
key,title,author_key,author_name,first_publish_year,edition_count,
editions,editions.key,editions.title,editions.subtitle,
editions.isbn,editions.language,editions.publisher,editions.publish_date
```

Der tatsächliche Parameterwert enthält keine Zeilenumbrüche. `fields=*`,
`availability`, freie `q`-Ausdrücke, Sortierung und Search-Facets sind
verboten. Die [Search-API-Dokumentation](https://openlibrary.org/dev/docs/api/search)
warnt, dass das vollständige Schema nicht stabil garantiert ist; der Parser
akzeptiert deshalb nur die Allowlist und behandelt jedes Feld als optional.

Die Allowlist folgt dem allgemeinen `fields`-Verfahren und dem dokumentierten
`editions.*`-Verfahren der Search API. Das von der Dokumentation verlinkte
[offizielle Work-Search-Schema](https://github.com/internetarchive/openlibrary/blob/master/openlibrary/plugins/worksearch/schemes/works.py)
trägt die ausgewählten Work- und Edition-Felder. `editions.author_key` und
`editions.author_name` sind nicht freigegeben, weil das aktuelle Schema diese
duplizierten Edition-Author-Felder ausdrücklich deaktiviert und aus dem
Edition-Field-Set ausschließt.

Search beginnt mit `offset=0`. Eine zweite Seite mit `offset=10` ist exakt dann
zulässig, wenn `numFound` oder `num_found` größer als `10` ist und Seite 1
keinen Search-Doc enthält, der sowohl ein syntaktisch gültiges Work-OLID als
auch mindestens ein syntaktisch gültiges eingebettetes Edition-OLID oder ISBN
besitzt. Sobald ein solcher Doc vorhanden ist oder die Trefferzahl höchstens
zehn beträgt, stoppt die Route nach Seite 1. Es gibt höchstens zwei Seiten und
damit höchstens 20 Search-Docs je Queryroute. Direkte Record- und
Books-API-Shapes besitzen keine Pagination. Die dokumentierten Endpoints
`/works/{id}/editions.json` und `/authors/{id}/works.json` werden in v1 nicht
verwendet, weil sie für den begrenzten Vertical Slice unnötige Fan-out-
Abfragen erzeugen würden.

## Transport- und Lastgrenzen

Der Adapter verwendet diese unveränderlichen v1-Grenzen:

| Grenze | Wert |
|---|---|
| DNS-/Connect-Timeout | 3 Sekunden |
| Gesamtzeit je HTTP-Versuch einschließlich Body Read | 10 Sekunden |
| Redirects | 0; jeder `3xx`-Status ist `PERMANENT_FAILURE` |
| maximale transportierte Response | 524.288 Byte |
| maximale normalisierte Cache-Payload | 262.144 Byte |
| Concurrency/parallele Open-Library-Requests | 1 |
| Mindestabstand zwischen Requeststarts | 1 Sekunde |
| automatische Wiederholungen im selben Aufruf | 0 |
| maximale Requests je Queryroute | 2 |

Der User-Agent ist obligatorisch und hat das Shape:

```text
FolioTone/{application_version} (+https://github.com/gecompat/FolioTone; mailto:{contact_email})
```

`contact_email` ist eine explizite lokale Runtime-Konfiguration, kein Secret,
wird aber weder in Git noch Cache, Provenance, Fehlertext oder Report
persistiert. Ohne syntaktisch gültige Kontaktadresse ist
`ONLINE_STRUCTURED` für diesen Provider nicht startfähig. Diese lokale
Begrenzung bleibt unter den offiziell dokumentierten drei Requests pro
Sekunde für identifizierte Clients und vermeidet die nicht identifizierte
Rate. Ein Deployment darf genau einen online aktiven Open-Library-Transport
betreiben; mehrere Prozesse benötigen vor Freigabe einen eigenen
prozessübergreifenden Rate-Limit-Vertrag. Verteilte IP-Nutzung ist verboten.

Das Zwei-Request-Budget gilt separat pro ausgewählter Queryroute. Search darf
beide Requests ausschließlich für die oben definierte Pagination verwenden
und darf danach keinen `Author`-Fetch auslösen. Eine direkte `Work`- oder
`Edition`-Route verwendet einen Request für den Record und darf höchstens
einen darin syntaktisch gültig referenzierten `Author` als zweiten Request
laden. ISBN sowie OCLC/LCCN gelten als direkte `Edition`-Routen mit derselben
Grenze. Ein weiterer Author, ein Route-Fallback oder ein anderer Fan-out ist
innerhalb derselben Queryroute verboten.

## HTTP-, Retry-After- und Fehlerklassifikation

Der Adapter folgt keinen Redirects und führt keine automatische Wiederholung
aus. Er klassifiziert exakt:

| Beobachtung | `ProviderCacheResultStatus` |
|---|---|
| valide `200`-Antwort mit mindestens einem zulässigen Record | `SUCCESS` |
| direkte `404`-Antwort, leeres Books-API-Objekt oder valide Search-Antwort ohne Docs | `NOT_FOUND` |
| `429` | `RATE_LIMITED` |
| Timeout, DNS-/Connect-Fehler, `408`, `425` oder `500` bis `599` | `TEMPORARY_FAILURE` |
| `400`, `401`, `403`, `405`, `410` oder jeder `3xx`-Status | `PERMANENT_FAILURE` |
| anderer HTTP-Status, falscher Content-Type, ungültiges UTF-8/JSON, falsche Topologie, Oversize oder überschrittene Page-Grenze | `INVALID_RESPONSE` |

Bei `429` wird `Retry-After` als nichtnegative ganzzahlige Sekunden oder als
HTTP-Date gemäß RFC 9110 gelesen. Ein Zeitpunkt in der Vergangenheit wird wie
null Sekunden behandelt. Fehlt der Header oder ist er ungültig, gilt 60
Sekunden. Ein Wert über 86.400 Sekunden wird auf 86.400 Sekunden begrenzt und
der Fehlertext enthält nur den festen Code `RETRY_AFTER_CAPPED`. Die Runtime
schläft nicht; `failure_retry_after_at` verhindert bis zu diesem Zeitpunkt
einen Fetch gemäß ADR-0035.

Fehlertexte enthalten ausschließlich feste Codes, Endpoint-Kind,
HTTP-Status und bounded Zähler. URL, Queryparameter, Header, Responsebody,
Titel, Author, Identifierwert, Pfad und Dateiname erscheinen nicht darin.

## Cache Payload, Codec und Zeitgrenzen

`SUCCESS` verwendet ausschließlich
`ProviderCachePayloadKind.NORMALIZED_SOURCE_DTO` mit Codec
`json/openlibrary-source-dto-v2`. Transportierte Rohbytes werden nach
erfolgreicher Validierung verworfen und niemals im Provider Cache oder einem
Diagnoseartefakt persistiert. `NOT_FOUND` verwendet
`ProviderCachePayloadKind.NONE`. Technische Fehler dürfen als Failure-Slot
ohne Payload persistiert werden.

Die festen TTLs lauten:

| Status | Freshness | Ablauf/Failure-TTL |
|---|---|---|
| `SUCCESS` | 30 Tage | 180 Tage |
| `NOT_FOUND` | 6 Stunden | 24 Stunden |
| `RATE_LIMITED` | nicht anwendbar | Maximum aus `failure_retry_after_at` und 1 Stunde, höchstens 24 Stunden |
| `TEMPORARY_FAILURE` | nicht anwendbar | 5 Minuten |
| `PERMANENT_FAILURE` | nicht anwendbar | 24 Stunden |
| `INVALID_RESPONSE` | nicht anwendbar | 1 Stunde |

Alle positiven, negativen und technischen TTLs sowie die 180-Tage-Retention
sind konservative FolioTone-Policies. Sie sind weder veröffentlichte
Open-Library-Grenzen noch eine Cache-Control-, Lizenz- oder Rechtefreigabe.
Ein Eintrag ist nach 180 Tagen nicht mehr verwendbar und wird durch die bounded
Retention aus ADR-0035 löschbar. Es gibt kein Stale-on-error.

## Normalisierte Source-DTOs

Die Cache-Hülle `openlibrary-source-record/v2` enthält ausschließlich:

```text
profile
endpoint_kind
records
result_count
pagination_offset
pagination_complete
```

`endpoint_kind` ist genau `EDITION`, `WORK`, `AUTHOR`, `LEGACY_IDENTIFIER`
oder `SEARCH`. Alle sechs Hüllenfelder sind immer vorhanden. `records` ist ein
JSON-Array, `result_count` und `pagination_offset` sind nichtnegative Integer
und `pagination_complete` ist Boolean. `pagination_offset` ist außerhalb von
Search immer `0`.

Records werden nach ihrem Open-Library-Key sortiert und dedupliziert. Jeder
String ist NFC-normalisiert; unbekannte Felder werden verworfen. Fehlende
skalare Werte sind JSON-`null`, fehlende Listen sind leere Arrays. Pro Liste
werden höchstens 32 Werte behalten, bei Search höchstens 20 Records. Kürzung
wird durch den immer vorhandenen booleschen `truncated`-Wert am Record
sichtbar. Die Serialisierung verwendet `canonical-json/v1` aus ADR-0035.

Die festen Stringgrenzen lauten:

| Feldklasse | Grenze in Unicode-Codepoints |
|---|---|
| OLID und namespaced Identifierwert | 64 |
| Titel, Subtitle, Name und Alternate Name | 512 |
| Publisher und Subject | 256 |
| Publish-, Birth- und Death-Date | 64 |

Ein Pflicht-OLID außerhalb des dokumentierten `OL<number>W`, `OL<number>M`
oder `OL<number>A`-Patterns macht den Record malformed. Ein optionaler Text
über der Grenze wird verworfen und setzt `truncated=true`; er wird nicht still
abgeschnitten.

Ein `Work`-Record enthält höchstens:

```text
work_olid, title, first_publish_year, author_refs, subjects, truncated
```

Ein `Edition`-Record enthält höchstens:

```text
edition_olid, work_refs, title, subtitle, publish_date, publishers,
languages, isbn10, isbn13, oclc, lccn, author_refs, truncated
```

Ein `Author`-Record enthält höchstens:

```text
author_olid, name, alternate_names, birth_date, death_date, truncated
```

Search-Records behalten `Work`- und eingebettete `Edition`-Teile getrennt.
Zusätzlich besitzt jeder `SearchSourceRecord` genau das Feld
`contributor_names`. Das JSON-Feld ist immer vorhanden und enthält ein Array
aus höchstens 32 eigenständigen Namenskandidaten aus dem Top-Level-Search-Feld
`author_name`. Ein fehlendes oder `null`-wertiges `author_name` wird zu `[]`;
ein anderer Topologie-Typ macht den Search-Record malformed. Jeder Eintrag
wird nach NFC normalisiert, muss danach nichtleer sein und darf höchstens 512
Unicode-Codepoints besitzen. Leere, typfalsche oder zu lange Einträge werden
verworfen und setzen `truncated=true`; mehr als 32 Eingänge werden nach dem
32. Eingang verworfen und setzen ebenfalls `truncated=true`. Die behaltenen
Werte werden nach exaktem NFC-String dedupliziert und lexikografisch nach
Unicode-Codepoints sortiert. Groß-/Kleinschreibung, Interpunktion,
Diakritika und Schreibweise bleiben erhalten.

`contributor_names` und `WorkSourceRecord.author_refs` sind unabhängige
Mengen. Die offizielle Search-Dokumentation zeigt `author_name` und
`author_key`, garantiert aber weder gleiche Länge noch positionsgleiche
Identität und bezeichnet das Search-Schema ausdrücklich als nicht stabil
garantiert. Der Adapter zippt, paart oder ergänzt diese Arrays daher nicht.
Direkte `WorkSourceRecord`- und `EditionSourceRecord`-DTOs bleiben ref-only;
Namen gelangen dort ausschließlich über einen separat geladenen
`AuthorSourceRecord` hinein.

Beschreibung, Bio, Excerpts, Volltext, Inhaltsverzeichnis, Coverbytes/-URLs,
Internet-Archive-Identifier, Availability, Lending-Status, Ratings,
Reading-Logs, Nutzerlisten, Source-Records, Änderungsverlauf und beliebige
externe Links werden weder normalisiert noch gecacht.

## Mapping in FolioTone

- `/works/OL…W` wird ausschließlich `EntityKind.WORK` und einem
  `openlibrary.work`-`ExternalIdentifier` zugeordnet.
- `/books/OL…M` wird ausschließlich `EntityKind.EDITION` und einem
  `openlibrary.edition`-`ExternalIdentifier` zugeordnet.
- `works`-Referenzen einer Edition erzeugen Work-Kandidaten und Evidence-
  Links; sie machen die Edition nicht selbst zum `Work`.
- `/authors/OL…A` erzeugt ausschließlich einen externen Agent-Kandidaten mit
  `openlibrary.author`-Identifier. Gleicher Name, Alias oder gleiche
  Schreibweise bestätigt keine lokale `Agent`-Identität.
- Ein `AuthorSourceRecord` erzeugt genau einen OLID-gebundenen externen
  Agent-Kandidaten. Sein `name` bleibt `source_field=name`; jeder Wert aus
  `alternate_names` bleibt eine eigene Assertion mit
  `source_field=alternate_names`. Exakte NFC-Duplikate werden je Source-Feld
  dedupliziert; `name` und Alias werden nicht allein wegen Wertgleichheit zu
  einer lokalen Identitätsbestätigung zusammengezogen.
- Jeder Wert aus `SearchSourceRecord.contributor_names` erzeugt einen
  ungebundenen Agent-Namenskandidaten mit `candidate_kind=AGENT`,
  `source_field=author_name`, `ValueState.EXTERNAL`, `confidence=null` und der
  vollständigen Provider-/Source-/Adapter-/Source-Profil-/Mapping-Provenance.
  Der Kandidat besitzt weder lokale `EntityId`/`target_ref` noch
  `openlibrary.author`-Identifier. Seine `source_record_refs` sind die
  deduplizierten providerseitigen Identitätsrefs desselben Search-Records.
  Sie werden zuerst nach der festen Kategorie `openlibrary.work`,
  `openlibrary.edition`, `isbn10`, `isbn13` und innerhalb einer Kategorie
  lexikografisch sortiert. Enthalten sind der vorhandene
  `openlibrary.work:OL…W`-Ref und zusätzlich vorhandene
  `openlibrary.edition:OL…M`-, `isbn10:`- oder `isbn13:`-Refs. Das Feld ist
  nichtleer, wird jedoch niemals als Agent-Identität interpretiert.
- OLID-gebundene Author-Kandidaten und ungebundene Search-Namenskandidaten
  bleiben auch bei gleichem Namen getrennt. Ohne eine separat beobachtete
  `AuthorSourceRecord`-Zuordnung oder eine spätere lokale
  Entity-Resolution-Entscheidung wird keine Verbindung erzeugt. Verschiedene
  `source_record_refs` erhalten getrennte Kandidaten, damit Homonyme und
  widersprüchliche Search-Docs nicht kollabieren.
- ISBN, OCLC und LCCN bleiben namespaced Edition-Identifier. Ein Identifier-
  Treffer darf einen Kandidaten stärken, aber keine erstmalige Resolution
  automatisch `USER_CONFIRMED` oder `CANONICAL` machen.
- Titel, Publisher, Datum, Sprache, Subjects und Namen werden einzelne
  `BookKnowledgeDTO`-Evidence mit `ValueState.EXTERNAL`, exaktem
  `source_field`, Provider-, Source-, Adapter- und Mapping-Version.
- Search-Relevanz ist keine FolioTone-Confidence. Der Adapter setzt aus einer
  Resultposition keine automatische Identity-Confidence oder Relation ab.

Agent-Kandidaten werden deterministisch nach Kandidatenart,
`source_record_refs`, OLID-Namespace/-Wert, `source_field` und exaktem
NFC-Namenswert sortiert. Dedupliziert wird nur bei vollständig gleichem
Schlüssel; casefold-ähnliche Namen, Aliase, Homonyme und Konflikte bleiben
getrennt. Kein Provider-Kandidat setzt `USER_CONFIRMED`, `CANONICAL`, eine
automatische Resolution oder einen lokalen Alias.

Namen und Identifier dürfen nur im privaten normalisierten Cache und in der
expliziten Evidence-Projektion vorkommen. `repr` von Source-Records,
Namenskandidaten, Mapping-Ergebnissen und Exceptions bleibt wertfrei
redigiert; Fehler, Logs und Reports enthalten weder Namen noch
`source_record_refs`. Die bestehende Grenze von 262.144 Byte für die
normalisierte Hülle bleibt unverändert.

Sparse Records sind valide, wenn ein syntaktisch gültiger OLID-Key und die zur
Entity-Ebene erforderliche Struktur vorhanden sind. Ein einzelner malformed
Record wird mit festem Finding verworfen; wenn danach kein valider Record
bleibt, lautet der gesamte Status `INVALID_RESPONSE`, nicht `NOT_FOUND`.

## Lizenz, Attribution, Retention und Redistribution

Open Library fordert in den Usage Guidelines Caching. Dieses Gate erlaubt
daher die private interne Speicherung der oben definierten normalisierten
Minimal-DTOs zur Anfragevermeidung und Mapping-Reanalyse. Es leitet aus der
Licensing-Seite keine Rechte an einzelnen Beiträgen ab.

Für v1 gelten deshalb zusätzlich:

- Rohantworten, Open-Library-Dumps und abgeleitete Kataloginventare werden
  nicht in Git, Testfixtures, öffentliche Artefakte oder verteilbare Exporte
  aufgenommen.
- Testfixtures sind vollständig handgeschriebene synthetische JSON-Strukturen;
  reale Titel, Personen, IDs, Beschreibungen oder kopierte Vollantworten sind
  verboten.
- Provider-Evidence behält `provider_id=openlibrary`, den konkreten OLID-Key
  und den Fetchzeitpunkt. Eine nutzersichtbare Detaildarstellung nennt
  „Open Library“ und verlinkt ausschließlich auf
  `https://openlibrary.org{record_key}`.
- Der private Cache wird spätestens nach den oben definierten 180 Tagen
  erneuerungs- oder löschbar. Eine dauerhafte öffentliche Redistribution ist
  nicht freigegeben.
- Jede spätere Redistribution, Dump-Auslieferung, Cover-/Volltextnutzung oder
  Übernahme zusätzlicher Felder benötigt eine erneute Terms-/Lizenzprüfung und
  ein eigenes Gate.

Die [Internet-Archive-Nutzungsbedingungen](https://archive.org/about/terms)
werden für v1 nicht als Erlaubnisgrundlage benötigt: Der Adapter ruft keine
Archive.org-Inhalte, Availability-, Lending-, Cover- oder Volltextendpoints
auf. Das bloße Vorhandensein solcher URLs oder IDs in einer Antwort führt zu
deren Verwerfung.

## Bulk-vs.-API-Grenze

Die Web API darf nur für explizit angeforderte, niedrigvolumige
Einzelauflösung verwendet werden. Sie darf nicht aus einem Scan- oder
Collection-Loop automatisch je Datei aufgerufen werden. Hunderte
Einzelabfragen, HTML-Scraping, Collection-Inventarübertragung und Traffic-
Verteilung über mehrere IPs sind verboten.

Mehr als 100 geplante Open-Library-Lookups in einem Lauf oder ein wiederholter
Bestand von mehr als 1.000 ungelösten Records stoppt den Onlinepfad mit
`BULK_DATASET_REQUIRED`. Beide Schwellen sind konservative FolioTone-Policies,
keine von Open Library veröffentlichte Rate-, Bulk- oder Rechtefreigabe. Die
Welle darf diese Grenze nicht durch Batching umgehen. Für diesen Umfang ist gemäß
[Open Library Data Dumps](https://openlibrary.org/developers/dumps) ein
separater `LOCAL_DATASETS`-Import der monatlichen Works-, Editions- und
Authors-Dumps zu planen. API-Cache und Dataset-Importzustand bleiben getrennt.

## Verbotene Pfade und Datenflüsse

Der Adapter darf niemals senden, persistieren oder in Fehlern ausgeben:

- absolute oder relative lokale Pfade;
- Dateinamen, Verzeichnisnamen oder ScanRoot-Strukturen;
- rohe OPF-/Calibre-Felder außerhalb der freigegebenen Querywerte;
- collection-weite Identifier-, Titel- oder Author-Inventare;
- freie Suchstrings, Beschreibungen, Excerpts oder extrahierten Inhalt;
- Secrets, Tokens, Cookies oder Nutzerkonten;
- HTML-, Edit-, Import-, Save-, Lists-, Reading-Log-, Search-inside-, Covers-,
  Availability-, Lending- oder Archive.org-Endpunkte.

Der Transport besitzt keine frei ergänzbaren Pfade, Queryparameter, Header
oder Hostnamen. Ein lokaler Pfad-/Filename-Sentinel in einem Querywert führt
vor dem Transport zu einer path-freien Validierungsablehnung.

## Offline- und Testgrenze

Alle EB-03B-Tests verwenden ausschließlich handgeschriebene synthetische
Fixtures, Fake Clock, Fake Transport und Socket-/HTTP-Fail-fast-Sentinels. Es
gibt keinen Live-Netzwerktest, keine DNS-Auflösung und keine reale
Open-Library-Antwort im Repository. `OFFLINE` bleibt cache-only oder liefert
kein externes Ergebnis gemäß ADR-0026 und ADR-0035.

Ein späterer realer Smoke ist eine getrennt autorisierte lokale
Betriebsprüfung mit expliziter Konfiguration, identifizierendem User-Agent und
privatem Cache. Sein Ergebnis ändert keinen Repositorystatus und wird nicht
versioniert.

## Konsequenzen

- FG-03B ist mit dem v2-Contributor-Vertrag akzeptiert. Vor S-EB03B-05 wird
  zuerst das begrenzte Parser-Addendum S-EB03B-03A umgesetzt; S-EB03B-05
  implementiert danach ausschließlich die festgelegte Mapping-Projektion.
- S-EB03B-03A erhöht Adapter-, Provider-Source-, normalisiertes Source-Profil
  und Codec. Das bestehende ref-only `openlibrary-book-mapping/v1` bleibt bis
  zur Implementierung der Name-only-Projektion gültig; erst S-EB03B-05 erhöht
  das Mappingprofil auf `openlibrary-book-mapping/v2`.
- S-EB03B-03A stoppt, wenn `author_name` nicht ohne Positionsannahme,
  Profilvermischung oder Erweiterung der Search-Allowlist bewahrt werden kann.
  S-EB03B-05 stoppt, wenn ein Name-only-Kandidat eine lokale Agent-ID, eine
  OLID-Zuordnung oder eine automatische Resolution benötigen würde.
- Open Library bleibt erster realer Book Provider, aber nicht Bulk-Backend oder
  kanonische Wahrheit.
- GND/DNB bleibt der vorgesehene zweite spezialisierte Authority Provider;
  Wikidata bleibt ergänzend.
- Das Gate ändert weder Produktionscode noch Schema, Runtimekonfiguration,
  Netzwerkzustand oder private Daten.
- W10 und alle Source-Media-Mutationen bleiben gesperrt.
