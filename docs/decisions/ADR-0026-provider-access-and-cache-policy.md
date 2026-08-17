# ADR-0026: Providerzugriff und Cache-Policy sind getrennte Verträge

- Status: Accepted
- Datum: 2026-08-17

## Kontext

ADR-0009 definiert vier fachlich verschiedene Zugriffsarten für externe
Anreicherung: `OFFLINE`, `LOCAL_DATASETS`, `ONLINE_STRUCTURED` und das separat
aktivierte `ONLINE_WEB_RESEARCH`. Der erste synthetische Providervertrag bildet
dagegen `OFFLINE`, `ONLINE` und `CACHE` in einem einzelnen
`KnowledgeProviderMode` ab.

Diese Literale mischen zwei unabhängige Entscheidungen. Der Zugriffsmodus legt
fest, welche Quellen ein Provider verwenden darf. Die Cache-Policy legt fest,
ob und wann bereits gespeicherte Providerantworten gelesen oder erneuert
werden. Insbesondere ist `CACHE` keine Datenquelle, während `ONLINE` nicht
zwischen strukturierten Diensten und allgemeiner Webrecherche unterscheidet.

Es existiert noch keine persistierte Provider-Cache- oder Moduskonfiguration.
Die Umstellung benötigt deshalb keine Datenmigration, muss aber die Semantik
des bereits veröffentlichten Python-Vertrags eindeutig behandeln.

## Entscheidung

Der kanonische öffentliche Vertrag verwendet zwei Enums.

`ProviderAccessMode` besitzt exakt folgende Namen und Werte:

| Name | Wert | Bedeutung |
|---|---|---|
| `OFFLINE` | `offline` | Kein Netzwerk- oder Dataset-Zugriff; ein zulässiger vorhandener Cache darf abhängig von der Cache-Policy gelesen werden. |
| `LOCAL_DATASETS` | `local_datasets` | Ausschließlich explizit importierte lokale Provider-Datasets; kein Netzwerk. |
| `ONLINE_STRUCTURED` | `online_structured` | Ausschließlich konfigurierte strukturierte Provider-APIs oder -Dienste. |
| `ONLINE_WEB_RESEARCH` | `online_web_research` | Separat aktivierte allgemeine Webrecherche; Ergebnisse bleiben Candidate-/Evidence-only. |

`ProviderCachePolicy` besitzt exakt folgende Namen und Werte:

| Name | Wert | Bedeutung |
|---|---|---|
| `USE_IF_FRESH` | `use_if_fresh` | Ein frischer Cachetreffer darf verwendet werden. Bei Miss oder stale Cache erfolgt durch diese Policy kein Source Fetch. |
| `REFRESH_IF_STALE` | `refresh_if_stale` | Ein frischer Treffer wird verwendet; bei Miss oder stale Cache wird die durch den Access Mode erlaubte Quelle einmal abgefragt und der Cache gemäß Providerdescriptor erneuert. |
| `FORCE_REFRESH` | `force_refresh` | Ein vorhandener Cacheeintrag wird nicht als Ergebnis verwendet; die erlaubte Quelle wird einmal abgefragt und der Cache gemäß Providerdescriptor ersetzt. |
| `NO_CACHE` | `no_cache` | Cache Read und Cache Write sind deaktiviert; ausschließlich die durch den Access Mode erlaubte Quelle wird abgefragt. |

`OFFLINE` in Verbindung mit `REFRESH_IF_STALE` oder `FORCE_REFRESH` ist
ungültig, weil beide Policies einen Source Fetch verlangen. `OFFLINE` mit
`USE_IF_FRESH` ist der cache-only Vertrag. `OFFLINE` mit `NO_CACHE` ist ein
gültiger strikt lokaler Vertrag ohne externes Providerergebnis. Ein
synthetischer Testprovider darf dabei weiterhin fest eingebaute Fixture-
Evidence zurückgeben, weil er keine externe Quelle öffnet. Die übrigen
Kombinationen sind nur dann nutzbar, wenn der konkrete Providerdescriptor den
Zugriff und die Speicherung erlaubt.

Die Wahl von `ONLINE_WEB_RESEARCH` allein aktiviert keine Webrecherche. Die
bestehende separate Opt-in-Grenze aus ADR-0009 bleibt zusätzlich erforderlich.
Keine Cache-Policy kann einen durch den Access Mode oder den Providerdescriptor
verbotenen Zugriff freigeben.

S-EB00-02 stellt zusätzlich die reine Funktion
`provider_policy_from_legacy(mode)` bereit. Sie akzeptiert ausschließlich einen
`KnowledgeProviderMode` und gibt das exakt zugehörige
`tuple[ProviderAccessMode, ProviderCachePolicy]` aus der nachstehenden Tabelle
zurück. Die reine Funktion `validate_provider_policy(access_mode,
cache_policy)` prüft die oben definierten ungültigen `OFFLINE`-Kombinationen
und erzeugt bei falschen Typen oder Kombinationen einen path-freien
`ValueError`. Beide Funktionen liegen in `foliotone.enrichment.contracts`;
nur `provider_policy_from_legacy` sowie die beiden neuen Enums werden aus
`foliotone.enrichment` re-exportiert.

## Legacy-Abbildung und Deprecation

`KnowledgeProviderMode` ist ab Annahme dieser ADR deprecated. Während EB-00
bleibt der Typ importierbar, damit jeder Spark-Pull-Request auf einem grünen
`main` aufbauen kann. Neue Produktionssignaturen, Defaults oder persistierte
Felder dürfen ihn nicht verwenden.

Die einzige zulässige Legacy-Abbildung lautet:

| Legacy-Wert | `ProviderAccessMode` | `ProviderCachePolicy` |
|---|---|---|
| `OFFLINE` / `offline` | `OFFLINE` | `NO_CACHE` |
| `ONLINE` / `online` | `ONLINE_STRUCTURED` | `NO_CACHE` |
| `CACHE` / `cache` | `OFFLINE` | `USE_IF_FRESH` |

Diese Abbildung erhält die bisher ausdrückbare Absicht: kein externer Zugriff,
strukturierter Onlinezugriff ohne implementierten Cache beziehungsweise
cache-only. Es gibt keine allgemeine Rückabbildung, weil die neuen Dimensionen
mehr Zustände ausdrücken. Nur die drei Tabellenzeilen dürften bei einem
ausdrücklich angeforderten Legacy-Export zurückgegeben werden.

Bis S-EB00-03 bleibt `KnowledgeProviderMode` als dokumentierter
Kompatibilitätstyp vorhanden. S-EB00-03 migriert alle in-repo Descriptor-,
Response- und Provider-Signaturen auf `access_mode` und `cache_policy` sowie
alle Produktionsaufrufe auf die neuen Enums. Die kanonischen Felder des
Descriptors heißen `default_access_mode` und `default_cache_policy`; die des
Response-DTOs heißen `access_mode` und `cache_policy`. Der Legacy-Typ bleibt
danach importierbar und darf nur noch als Input von
`provider_policy_from_legacy()` verwendet werden. Es wird keine Runtime-Warnung
erzeugt, die CLI-, Test- oder Reportausgaben verändern könnte. Seine endgültige
Entfernung erfordert eine spätere ausdrücklich versionierte öffentliche
Vertragsänderung.

Neue maschinenlesbare DTOs und Persistenzfelder verwenden ausschließlich
`access_mode` und `cache_policy`. Ein Feld `mode` oder ein Legacy-Literal wird
nicht neu persistiert. Sollte vor der Codeumstellung entgegen dem aktuellen
Repositorybefund eine persistierte Legacy-Konfiguration entdeckt werden,
stoppt das betroffene Spark-Paket; eine explizite Migration muss dann separat
entschieden werden.

## Umsetzungsschnitt

FG-00 entscheidet nur den Vertrag. Die Implementierung bleibt in den vier
einzeln gemergten Spark-Paketen:

1. S-EB00-01 fixiert das Legacy-Verhalten durch Characterization Tests.
2. S-EB00-02 führt die beiden neuen Enums und den Legacy-Konverter additiv ein.
3. S-EB00-03 migriert Descriptor, Response und synthetischen Provider.
4. S-EB00-04 gleicht Dokumentation und Status erst nach erfolgreicher
   Codeverifikation ab.

Der Provider Cache, seine Persistenz und seine Runtime-Semantik über die hier
definierten Policy-Zustände hinaus gehören weiterhin zu EB-03A. FG-00 bindet
keinen realen Provider an und autorisiert keinen Netzwerkzugriff.

## Konsequenzen

- Offline-, Dataset-, strukturierter Online- und Webzugriff bleiben fachlich
  unterscheidbar und prüfbar.
- Cache-Nutzung kann unabhängig von der Quelle konfiguriert und getestet
  werden.
- Der alte `CACHE`-Wert wird ohne stillschweigende Bedeutungsänderung auf einen
  cache-only Vertrag abgebildet.
- Neue Persistenz und Reports erhalten keine mehrdeutigen Legacy-Literale.
- W5B-001 bleibt bis zum Abschluss von S-EB00-01 bis S-EB00-04 `NEXT`.
- ADR-0009, seine Privacy-Grenzen und die W10-Sperre bleiben unverändert.
