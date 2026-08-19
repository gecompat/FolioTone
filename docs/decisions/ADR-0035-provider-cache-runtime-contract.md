# ADR-0035: Provider Cache Runtime ist key-kanonisch, freshness-getrennt und transaktional

- Status: Accepted
- Datum: 2026-08-19

## Kontext

ADR-0009 fordert providerbasierte externe Anreicherung mit persistentem Cache
unter `/data`. ADR-0026 trennt bereits `ProviderAccessMode` und
`ProviderCachePolicy`, legt aber noch nicht fest, welche Cache-Payload
persistiert wird, wie Freshness und Negative-Cache semantisch getrennt werden
oder welche Transaktionsgrenze für einen späteren Store gilt.

EB-03A benötigt genau diesen Frontier-Vertrag, bevor Spark die mechanischen
Pakete S-EB03A-01 bis S-EB03A-09 implementieren kann. Das Gate autorisiert
keinen realen Provider und keine Netzwerknutzung.

## Entscheidung

FolioTone modelliert den Provider Cache als transportnahen und
mapping-unabhängigen Source-Snapshot unter dem Profil
`provider-cache-entry/v1`.

Ein Cacheeintrag bindet exakt einen Provider-Source-Key an genau einen
transportierten oder lokal erzeugten Provider-Snapshot. Source Cache und
Mapping sind getrennt versioniert. Eine Mapping-Änderung darf daher einen
zulässigen vorhandenen Payload erneut auswerten, ohne den Source-Key zu ändern
oder einen neuen Fetch zu erzwingen.

## Öffentliche Literale

### Result-Status

```text
ProviderCacheResultStatus
-------------------------
SUCCESS
NOT_FOUND
RATE_LIMITED
TEMPORARY_FAILURE
PERMANENT_FAILURE
INVALID_RESPONSE
```

`SUCCESS` und `NOT_FOUND` sind fachliche Providerergebnisse. `RATE_LIMITED`,
`TEMPORARY_FAILURE`, `PERMANENT_FAILURE` und `INVALID_RESPONSE` sind
technische Fetch-/Transport-/Schemazustände. Sie sind niemals mit
`NOT_FOUND` gleichzusetzen.

### Payload-Kind

```text
ProviderCachePayloadKind
------------------------
NONE
RAW_RESPONSE
NORMALIZED_SOURCE_DTO
```

`NONE` ist nur zulässig, wenn der Providerdescriptor dokumentiert, dass für
den konkreten Status kein zulässiger wiederverwendbarer Payload existiert.
`RAW_RESPONSE` enthält exakt die bounded transportierte Antwortbytes.
`NORMALIZED_SOURCE_DTO` enthält eine bounded, providerinterne
Vor-Mapping-Darstellung, die für eine spätere Mapping-Reanalyse ausreicht.

Ergebnis-only Reprojektionen ohne Payload gelten als `NONE`. Sie sind für
reine Laufzeitdiagnostik erlaubt, erfüllen aber keine Mapping-Reanalyse.

### Freshness

```text
ProviderCacheFreshness
----------------------
FRESH
STALE
EXPIRED
```

FolioTone verwendet dafür die zwei Grenzen des Content-Slots:

- `content_fresh_until_at`
- `content_expires_at`

Ein Eintrag ist:

- `FRESH`, wenn `now < content_fresh_until_at`;
- `STALE`, wenn `content_fresh_until_at <= now < content_expires_at`;
- `EXPIRED`, wenn `now >= content_expires_at`.

Die Freshness-Triade bewertet ausschließlich einen vorhandenen fachlichen
Content-Slot. Für ihn sind `content_fetched_at`, `content_fresh_until_at` und
`content_expires_at` gemeinsam gesetzt und es gilt
`content_fetched_at <= content_fresh_until_at <= content_expires_at`. Fehlt ein
fachlicher Content-Slot, sind alle drei Felder `NULL` und es gibt keine
`ProviderCacheFreshness`. Technische Fehler besitzen getrennte Zeitfelder und
werden niemals durch die Freshness-Triade zu verwendbaren Inhalten.

## Kanonische Source- und Mapping-Keys

Der materielle `source_cache_key` besteht exakt aus diesen vier Komponenten:

```text
provider_id
provider_adapter_version
query_fingerprint
provider_source_version
```

Sie werden mit dem Domain-Tag `foliotone:provider-source-cache-key/v1`
kanonisch serialisiert und mit lowercase SHA-256 gehasht. Dieser Key ist die
persistierte Cache-Identität und bleibt bei einem reinen Mapping-Wechsel
unverändert.

Das kanonische Source-Objekt besitzt exakt diese Keys:

```json
{"domain":"foliotone:provider-source-cache-key/v1","provider_adapter_version":"...","provider_id":"...","provider_source_version":"...","query_fingerprint":"..."}
```

Für eine Mapping-Auswertung wird zusätzlich ein `mapping_input_key` aus genau
fünf Komponenten gebildet: den vier Source-Komponenten und
`mapping_profile_version`. Sein Domain-Tag lautet
`foliotone:provider-mapping-input-key/v1`. Er ist Provenance und
Idempotenzschlüssel der Mapping-Auswertung, aber weder Primärschlüssel noch
Lookup-Key des Source Cache.

Das kanonische Mapping-Objekt besitzt exakt die fünf Source-/Mapping-Felder
plus Domain:

```json
{"domain":"foliotone:provider-mapping-input-key/v1","mapping_profile_version":"...","provider_adapter_version":"...","provider_id":"...","provider_source_version":"...","query_fingerprint":"..."}
```

Beide Schlüssel verwenden `canonical-json/v1`: ein JSON-Objekt mit festen
Feldnamen, lexikografisch sortierten Keys, kompakten Separatoren und
UTF-8-Ausgabe ohne BOM. Alle Stringwerte werden vor der Serialisierung nach NFC
normalisiert. `null`, Floats, unbekannte Felder und implizite Stringkonvertierung
sind unzulässig. Der Fingerprint ist SHA-256 über die exakten Bytes und wird als
64-stelliges lowercase Hex gespeichert.

`query_fingerprint` stammt ausschließlich aus dem privacy-minimierten
Query-DTO. Weder absolute Pfade noch rohe Sammlungsinventare werden Teil eines
Keys. Varianten wie Dataset-Snapshot, Endpoint-Version oder Index-Stand müssen
in `provider_source_version` enthalten sein. `ProviderAccessMode` und
`ProviderCachePolicy` erweitern keinen der beiden Keys.

Der bisherige delimiterbasierte `BookKnowledgeQuery.fingerprint()`-Algorithmus
ist nicht cachefähig. S-EB03A-02 ersetzt ihn vor der ersten Cachepersistenz
durch `foliotone:book-knowledge-query/v2`: kanonisches JSON aus normalisiertem
Titel, einer stabil sortierten und deduplizierten Autorenmenge sowie stabil
sortierten und deduplizierten `(namespace, value)`-Identifierpaaren. Der Domain-
Tag liegt im festen JSON-Feld `domain` und ist materieller Bestandteil der
Hashbytes. Rohwerte bleiben ausschließlich
im ephemeren Query-DTO; persistiert und in Keys eingebettet wird nur der
64-stellige lowercase SHA-256. Da noch kein Provider Cache existiert, benötigt
dieser Versionswechsel keine Datenmigration.

## Cache-Eintrag

Ein künftiger Store persistiert mindestens diese materiellen Felder:

```text
ProviderCacheEntry
------------------
source_cache_key
provider_id
provider_adapter_version
query_fingerprint
provider_source_version
content_status
payload_kind
payload_codec
payload_bytes
payload_bytes_sha256
content_http_status
content_fetched_at
content_fresh_until_at
content_expires_at
failure_status
failure_http_status
failure_at
failure_retry_after_at
failure_expires_at
generation
content_hash
```

`generation` ist eine positive, je `source_cache_key` monoton steigende
Ganzzahl. Sie ist ausschließlich ein Fencing-/CAS-Wert und kein Bestandteil
von `content_hash`.

`content_status` ist `SUCCESS`, `NOT_FOUND` oder `NULL`. `failure_status` ist
einer der vier technischen Status oder `NULL`. Mindestens einer der beiden
Slots muss vorhanden sein. Dadurch kann ein fehlgeschlagener Refresh dauerhaft
beobachtbar und rate-limit-sicher sein, ohne den letzten fachlichen Payload zu
vernichten oder als erfolgreiches Ergebnis auszugeben.

`payload_codec` ist ein bounded technischer Identifier wie
`json/raw-response` oder `json/provider-dto`. Er ist bei `payload_kind=NONE`
`NULL`. `payload_bytes_sha256` bindet den gespeicherten Payload; `content_hash`
bindet alle materiellen Felder einschließlich beider Status-Slots,
Payload-Digest, HTTP-Status und Zeitgrenzen, aber ohne die ableitbaren Felder
`source_cache_key`, `generation` und `content_hash` selbst. Der Hash verwendet
die Domain `foliotone:provider-cache-content/v1` in einer festen
`canonical-json/v1`-Hülle; rohe Payloadbytes werden darin nur durch Länge und
SHA-256 repräsentiert. Zeitpunkte werden ausschließlich als UTC mit sechs
Nachkommastellen und `Z` serialisiert; naive Zeitpunkte werden abgelehnt.

Der Cache speichert keine absoluten Pfade, Secrets oder Rohanfragen.

## Payload-Regel je Provider

Jeder reale Providerdescriptor muss vor der Implementierung dokumentieren:

1. welcher `ProviderCachePayloadKind` für `SUCCESS` zulässig ist;
2. ob `NOT_FOUND` einen Payload benötigt oder `NONE` verwendet;
3. ob technische Fehlerzustände persistiert werden dürfen;
4. welche bounded Größen- und Codec-Grenzen gelten;
5. ob Lizenz- oder Zugriffsvorgaben `RAW_RESPONSE` verbieten.

Ohne diese explizite Descriptor-Regel darf ein Provider nicht an EB-03A oder
EB-03B teilnehmen.

Unabhängig vom Providerdescriptor gelten folgende v1-Invarianten:

- `content_status=SUCCESS` benötigt einen Payload ungleich `NONE`;
- `content_status=NOT_FOUND` darf gemäß Descriptor `NONE` oder einen zulässigen Payload
  besitzen;
- `content_status=NULL` verlangt `payload_kind=NONE` und vollständig `NULL`
  Content-Payload- und Content-Zeitfelder;
- `payload_kind=NONE` verlangt `payload_codec=NULL`, `payload_bytes=NULL` und
  `payload_bytes_sha256=NULL`;
- ein Payload ungleich `NONE` verlangt einen nichtleeren Codec, bounded Bytes
  und deren exakt passenden SHA-256;
- der Failure-Slot enthält keine Payloadbytes; bounded technische Responsebytes
  dürfen nur in einem getrennten privaten Diagnoseartefakt mit eigener
  Descriptor- und Retention-Regel liegen;
- `failure_status=NULL` verlangt vollständig leere Failure-Felder;
- ein gesetzter Failure-Status verlangt `failure_at` und
  `failure_expires_at` mit `failure_at <= failure_expires_at`.

## TTL-, Freshness- und Negative-Cache-Regeln

### Positive Ergebnisse

`SUCCESS` erhält providerdefinierte `content_fresh_until_at`- und
`content_expires_at`-Werte.
Ein `FRESH`-Treffer darf bei `USE_IF_FRESH` und `REFRESH_IF_STALE` direkt
verwendet werden.

### Negative Ergebnisse

`NOT_FOUND` darf persistiert werden, aber nur mit einer ausdrücklich kürzeren
negativen TTL als ein stabiler positiver Treffer desselben Providers.

`NOT_FOUND` darf:

- `FRESH` als legitimer negativer Treffer sein;
- `STALE` oder `EXPIRED` werden und danach gemäß Cache-Policy einen Refresh
  verlangen;
- niemals aus `RATE_LIMITED`, `TEMPORARY_FAILURE`, `PERMANENT_FAILURE` oder
  `INVALID_RESPONSE` umgedeutet werden.

### Technische Fehlerzustände

`RATE_LIMITED`, `TEMPORARY_FAILURE`, `PERMANENT_FAILURE` und
`INVALID_RESPONSE` dürfen persistiert werden, wenn der Providerdescriptor dies
dokumentiert. Sie sind jedoch niemals ein verwendbares inhaltliches
Anreicherungsergebnis.

`failure_retry_after_at` ist nur für `RATE_LIMITED` zulässig. Wenn es gesetzt
ist, gilt
`failure_at <= failure_retry_after_at <= failure_expires_at`. Solange
`now < failure_retry_after_at`
ist, unterdrücken `REFRESH_IF_STALE` und `FORCE_REFRESH` einen weiteren Fetch
und liefern den technischen Rate-Limit-Status. Andere Fehlerzustände dürfen
keinen impliziten erfolgreichen Cache-Treffer erzeugen.

## Runtime-Verhalten relativ zu `ProviderCachePolicy`

### `NO_CACHE`

- kein Cache Read;
- kein Cache Write;
- genau ein erlaubter Source Fetch oder bei `OFFLINE` kein Providerergebnis.

### `USE_IF_FRESH`

- Cache Read ist erlaubt;
- nur `FRESH`e Einträge mit `SUCCESS` oder `NOT_FOUND` sind verwendbare
  Ergebnisse;
- Ohne frischen Content lösen `MISS`, `STALE`, `EXPIRED` und ein Failure-Slot
  selbst keinen Fetch aus.

### `REFRESH_IF_STALE`

- `FRESH`e `SUCCESS`-/`NOT_FOUND`-Einträge werden direkt verwendet;
- Ein aktives `failure_retry_after_at` unterdrückt den Fetch. Andernfalls führen
  `MISS`, `STALE`, `EXPIRED` oder ein Failure-Slot zu genau einem durch den
  Access Mode erlaubten Fetch;
- das neue Ergebnis ersetzt den bisherigen Eintrag atomar.

### `FORCE_REFRESH`

- vorhandene Cacheeinträge werden nicht als Ergebnis verwendet;
- außerhalb eines noch aktiven `failure_retry_after_at` wird genau ein erlaubter Fetch
  ausgeführt;
- der neue Snapshot ersetzt den bisherigen Eintrag atomar.

### Refresh-Fehler und Stale-on-error

v1 besitzt bewusst kein Stale-on-error-Fallback. Scheitert ein Refresh
technisch, wird ein vorhandener `STALE`- oder `EXPIRED`-Inhalt nicht als
erfolgreiches Providerergebnis ausgegeben.

Ein vorhandener fachlicher `SUCCESS`-/`NOT_FOUND`-Snapshot wird durch einen
technischen Fehler nicht überschrieben. Der CAS-Write behält den Content-Slot
unverändert und ersetzt ausschließlich den Failure-Slot. Der alte Content darf
weiterhin für Provenance und eine spätere zulässige Mapping-Reanalyse erhalten
bleiben, wird im fehlgeschlagenen Refresh-Aufruf aber nicht als Ergebnis
verwendet. Ein erfolgreicher Fetch ersetzt den Content-Slot und leert den
Failure-Slot atomar. Die Runtime gibt bei einem Refresh-Fehler den technischen
Status zurück; sie verschleiert ihn nicht durch alte Inhalte.

### `OFFLINE`

ADR-0026 bleibt maßgeblich:

- `OFFLINE + USE_IF_FRESH` ist cache-only;
- `OFFLINE + NO_CACHE` liefert kein externes Providerergebnis;
- `OFFLINE + REFRESH_IF_STALE` und `OFFLINE + FORCE_REFRESH` bleiben ungültig.

Der Offline-Test muss technisch beweisen, dass weder Socket- noch HTTP-Zugriff
stattfindet.

## Mapping-Reanalyse

Wenn ein Cacheeintrag `payload_kind` ungleich `NONE` besitzt, darf eine spätere
Mapping-Version denselben Payload über den unveränderten `source_cache_key`
erneut auswerten. Sie erzeugt dafür einen neuen `mapping_input_key`, ohne einen
Fetch auszuführen. Die Runtime erhöht ausschließlich die Mapping-Auswertung,
nicht den Transportzähler. EB-03A persistiert noch kein gemapptes
Providerergebnis im Source Cache. Die gewählte `ProviderCachePolicy` bleibt
maßgeblich; Mapping-Reanalyse darf einen `EXPIRED`-Content-Slot nicht als
verwendbaren Cachetreffer aufwerten.

Ein Provider ohne zulässigen Payload für Reanalyse darf EB-03B nur nutzen,
wenn seine Dokumentation ausdrücklich erklärt, warum Mapping-Reanalyse
fachlich nicht benötigt wird.

## Transaktionsgrenze

Ein späterer Cache-Store arbeitet source-key-orientiert und atomar:

1. Elternzeile und optionaler Payload werden in einer SQLite-Transaktion
   geschrieben oder ersetzt.
2. Ein Reader sieht niemals einen Elternsatz ohne den zugehörigen Payload und
   niemals einen neuen Payload ohne die zugehörige Elternzeile.
3. Ein Replace hinterlässt entweder vollständig den alten oder vollständig den
   neuen Snapshot.
4. Dieselbe Source-Key-Kombination mit abweichendem Payload wird als
   vollständiger Replace behandelt, nicht als zweite parallele Version.

`get(source_cache_key)` liefert Snapshot und `generation`. Ein Writer verwendet
`compare_and_replace(entry, expected_generation)`. Bei einem Miss ist die
erwartete Generation `0`; genau ein konkurrierender Insert darf Generation `1`
erzeugen. Ein Replace verwendet die gelesene positive Generation und erhöht sie
exakt um eins. Die bedingte Generation-Prüfung, Eltern-/Payload-Schreiboperation
und Kapazitätsprüfung liegen in derselben SQLite-Transaktion. Ein CAS-Verlust
rollt vollständig zurück und liefert den inzwischen aktuellen Gewinner; ein
älterer langsamer Fetch darf ihn nicht überschreiben.

Ein optionales In-Process-Singleflight darf doppelte Fetches reduzieren, ist
aber keine Korrektheitsgrenze. Es wird keine SQLite-Transaktion während eines
Netzwerkzugriffs, Mappings oder Parserlaufs offen gehalten. Das Gate benötigt
keinen globalen Cross-Key-Lease-Vertrag.

## Bounded Retention und Kapazität

Jede Cache-Instanz besitzt eine validierte `ProviderCacheLimits`-Konfiguration
mit mindestens:

```text
max_entry_payload_bytes
max_entries_total
max_payload_bytes_total
expired_prune_batch_size
```

Alle Grenzen sind positive Ganzzahlen und müssen beim Store-Aufbau explizit
vorliegen; v1 besitzt keinen unbegrenzten Default. Payloadbytes werden vor
Beginn einer Write-Transaktion gegen das Einzellimit geprüft. Innerhalb der
Transaktion darf
der Store höchstens `expired_prune_batch_size` Einträge entfernen, bei denen
jeder vorhandene Content- und Failure-Slot abgelaufen ist. `retention_until_at`
ist dafür das Maximum der vorhandenen `content_expires_at`- und
`failure_expires_at`-Werte. Die stabile Reihenfolge lautet
`(retention_until_at, source_cache_key)`. Danach prüft der Store Anzahl und
Gesamtpayloadbytes einschließlich des
beabsichtigten Replaces. Reicht die Kapazität weiterhin nicht aus, schlägt der
Write pfadfrei mit `CACHE_CAPACITY_EXCEEDED` fehl und verändert weder Cache noch
Generation.

v1 besitzt keine stille LRU-Verdrängung von `FRESH`en oder `STALE`n Einträgen
und schreibt bei Reads keinen Last-access-Zeitpunkt. Dadurch bleiben Retention,
Tests und konkurrierende Writes deterministisch. Cachedateien und Payloads
liegen ausschließlich im privaten Runtime-Bereich unter `/data`, nie in Git
oder öffentlichen Reports.

## Konsequenzen

- FG-03A legt Cache-Payload, getrennte Source-/Mapping-Keys, Freshness,
  Negative-Cache, generation-gefencetes CAS und bounded Retention verbindlich
  fest.
- S-EB03A-01 bis S-EB03A-09 können jetzt mechanisch gegen einen festen Vertrag
  implementiert werden.
- Reale Provider bleiben bis FG-03B und EB-03B getrennt.
- W10, Privacy-Grenzen und der synthetische Offline-Standard aus ADR-0009 und
  ADR-0026 bleiben unverändert.
