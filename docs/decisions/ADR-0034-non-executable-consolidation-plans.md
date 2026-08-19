# ADR-0034: Nicht ausführbare, content-addressed `ConsolidationPlan`-Snapshots

- Status: Accepted
- Datum: 2026-08-19

## Kontext

EB-06 persistiert begrenzte `RelationCandidate`-Snapshots und bindet
bibliografische Fälle an den append-only Review-Core. EB-07 ergänzt
read-only Calibre-Ownership-, Sidecar- und Reconciliation-Evidence. Für EB-08
fehlt ein Vertrag, der bestätigte Identity, Quality Evidence, eine geprüfte
Keep Preference und zukünftige physische Absichten zusammenführt, ohne daraus
eine ausführbare Operation zu machen.

Die bestehenden Schichten dürfen dabei nicht zusammenfallen:

```text
Identity != Quality != Keep Preference != Future Operation Intent
```

Ein `RelationCandidate` auf `WORK`- oder `EDITION`-Ebene bezeichnet keine
physische Datei. Ein höher bewertetes E-Book wird nicht dadurch zum Duplicate.
Calibre-, Sidecar- und Archive-Evidence kann eine spätere Änderung blockieren,
aber nicht die Identity beweisen. W9 darf ausschließlich persistierte,
prüfbare Planungsdaten erzeugen. W10 bleibt gesperrt.

## Entscheidung

FolioTone verwendet für EB-08 das Profil `consolidation-plan/v1`, das
Keep-Preference-Profil `ebook-keep-preference/v1` und die kanonische
Serialisierung `canonical-json/v1`. Alle DTOs sind immutable, path-free und
bounded. Ein Plan ist ein insert-only Snapshot für genau einen abgeschlossenen
`ScanRun` und genau ein gerichtetes Keeper-/Candidate-Paar desselben
`ScanRoot`.

`ConsolidationPlan` trägt immer den einzigen Execution-State
`NOT_EXECUTABLE`. Auch der vollständig geprüfte Status
`APPROVED_NON_EXECUTABLE` erteilt keine Ausführungsberechtigung.

## Öffentliche Literale

### Planstatus und Execution-State

```text
ConsolidationPlanStatus
-----------------------
BLOCKED
REVIEW_REQUIRED
APPROVED_NON_EXECUTABLE

ConsolidationExecutionState
---------------------------
NOT_EXECUTABLE
```

Die Statuspriorität ist fest:

1. Mindestens ein `ConsolidationBlockerCode` ergibt `BLOCKED`.
2. Ohne Blocker, aber mit einem vorhandenen kompatiblen `ReviewItem` im Zustand
   `PENDING` oder `DEFERRED`, ergibt sich `REVIEW_REQUIRED`.
3. Nur ohne Blocker und mit allen erforderlichen kompatiblen
   `ReviewDecision`-Werten `ACCEPT` ergibt sich
   `APPROVED_NON_EXECUTABLE`.

Ein fehlender erforderlicher Review-Fall ist ein Blocker. Ein bereits
vorhandener, aber noch nicht entschiedener oder aufgeschobener Review-Fall ist
dagegen `REVIEW_REQUIRED`. `REJECT` erzeugt den zugehörigen Rejection-Blocker.

### Blocker

```text
ConsolidationBlockerCode
------------------------
IDENTITY_NOT_ACTIONABLE
IDENTITY_NOT_CONFIRMED
LINEAGE_MISMATCH
PRECONDITION_INCOMPLETE
PROTECTED_SOURCE_ROOT
QUALITY_EVIDENCE_INCOMPLETE
KEEP_PREFERENCE_UNRESOLVED
KEEP_PREFERENCE_REVIEW_MISSING
KEEP_PREFERENCE_REVIEW_REJECTED
CONSOLIDATION_REVIEW_MISSING
CONSOLIDATION_REVIEW_REJECTED
CALIBRE_RELATIONSHIP_UNKNOWN
CALIBRE_OWNERSHIP_PRESENT
SIDECAR_RELATIONSHIP_UNKNOWN
SIDECAR_DEPENDENCY_PRESENT
ARCHIVE_RELATIONSHIP_UNKNOWN
ARCHIVE_MEMBERSHIP_PRESENT
```

Blocker besitzen nur `code` und geordnete opake Evidence-Referenzen. Freitext,
Pfade, Dateinamen, Hashwerte oder private Metadatenwerte sind nicht Teil des
öffentlichen Blocker-Vertrags. Mehrere Blocker werden nach ihrem Literal und
danach nach ihren Evidence-Referenzen sortiert und dedupliziert.

### Rollen, Evidence und Abhängigkeiten

```text
ConsolidationFileRole
---------------------
KEEPER
CANDIDATE

ConsolidationEvidenceRole
-------------------------
IDENTITY
KEEPER_QUALITY
CANDIDATE_QUALITY
KEEP_PREFERENCE
DEPENDENCY
REVIEW

ConsolidationEvidenceKind
-------------------------
RELATION_CANDIDATE
RELATION_CANDIDATE_EVIDENCE
REVIEW_DECISION
FINGERPRINT
TOOL_EXECUTION
TOOL_RESULT
EBOOK_COLLECTION_ITEM
EBOOK_COLLECTION_FINDING
QUALITY_EVIDENCE
CALIBRE_SNAPSHOT
CALIBRE_FINDING
CALIBRE_FORMAT
CALIBRE_SIDECAR

ConsolidationDependencyKind
---------------------------
CALIBRE
SIDECAR
ARCHIVE

ConsolidationDependencyState
----------------------------
KNOWN_NONE
KNOWN_PRESENT
UNKNOWN
NOT_APPLICABLE
```

Eine Evidence-Referenz besteht aus `kind`, `ref_id`, `role` und einem
materiellen SHA-256-Fingerprint. Zufällige Child-Row-IDs, Zeitpunkte und
private Werte werden nicht als materieller Fingerprint verwendet. Ein Plan
enthält höchstens 1.024 Evidence-Referenzen.

`NOT_APPLICABLE` ist nur zulässig, wenn der jeweilige Adaptervertrag beweist,
dass die Beziehung für den konkreten File-Typ nicht existieren kann. Das
Fehlen einer implementierten Archive- oder Calibre-Abfrage ist `UNKNOWN`,
nicht `NOT_APPLICABLE`. Für den Candidate blockieren `KNOWN_PRESENT` und
`UNKNOWN` bei allen drei Dependency-Arten. Für den Keeper blockiert `UNKNOWN`;
`KNOWN_PRESENT` bleibt als zu erhaltende Dependency und spätere
Unchanged-Precondition sichtbar. Bis eine Archive-Welle diese Aussage
erzeugen kann, ist `ARCHIVE=UNKNOWN` daher ein bewusster Blocker, aber kein
technischer Fehler der EB-08-Plananlage.

### Future Operation Intents

```text
ConsolidationIntentCode
-----------------------
KEEP
QUARANTINE
VERIFY
ROLLBACK
PURGE
CALIBRE_RECONCILE
SIDECAR_RECONCILE
ARCHIVE_RECONCILE
EMPTY_DIRECTORY_REVIEW
```

Diese Literale sind Beschreibungen einer möglichen späteren W10-Sequenz. Sie
enthalten keine Zielpfade, Befehle, Retention-Fristen oder ausführbaren
Parameter. `KEEP` adressiert ausschließlich den Keeper. Alle anderen Intents
adressieren den Candidate oder dessen bekannte Dependencies. `PURGE` und
`EMPTY_DIRECTORY_REVIEW` bleiben selbst in einem akzeptierten W9-Plan nur
Dokumentationsabsichten.

## Identity-, Keeper- und Candidate-Grenze

### Actionable Identity in v1

`consolidation-plan/v1` akzeptiert als actionable Identity ausschließlich
einen persistierten `RelationCandidate` mit:

- `relation_type=EXACT_DUPLICATE`;
- `left_kind=FILE` und `right_kind=FILE`;
- `status=CONFIRMED`;
- einem abgeschlossenen `source_scan_run_id`;
- `FILE_SHA256_EQUAL` als reproduzierter materieller Evidence;
- zwei verschiedenen, kanonisch geordneten `FileRecord`-IDs desselben
  `ScanRoot`.

Der Identity-Snapshot enthält `relation_candidate_id`, Relation Type,
kanonische File-Endpoints, Matcher-/Decision-Compatibility-Version,
`evidence_fingerprint`, `candidate_set_fingerprint` und Status. Die
Relation-Endpoints bleiben ungeordnet hinsichtlich Keep Preference.

Ein akzeptierter `SAME_EDITION`- oder `SAME_WORK`-Review bestätigt eine
bibliografische Relation, liefert aber keine physische File-Identity und keine
Keeper-Richtung. Solche Relation Candidates erzeugen
`IDENTITY_NOT_ACTIONABLE`. `REVIEW_REQUIRED` oder `REJECTED` erzeugt in v1
`IDENTITY_NOT_CONFIRMED`. Spätere File-level Identity-Arten benötigen eine
neue Plan- und Decision-Compatibility-Version.

### Gerichtete Rollen

Keeper und Candidate sind zwei verschiedene `FileRecord`-IDs und müssen exakt
die beiden File-Endpoints des Identity-Snapshots bilden. Genau eine ID ist
`KEEPER`, die andere `CANDIDATE`. Die Rollen werden ausschließlich durch ein
eindeutiges `KeepPreferenceOutcome` und dessen kompatible ACCEPT-Entscheidung
gerichtet. Lexikografische ID-Reihenfolge, Pfad, Dateiname oder
Einfügereihenfolge darf keine Keep Preference festlegen.

Die Rollen der zwei `ConsolidationQualityEvidence`-Referenzen sind innerhalb
des `KeepPreferenceOutcome` statusabhängige Slots. Bei `PREFERRED` bezeichnen
`KEEPER` und `CANDIDATE` die echte gerichtete Entscheidung. Bei `TIED` oder
`BLOCKED` bezeichnet `KEEPER` ausschließlich den kanonischen linken und
`CANDIDATE` ausschließlich den kanonischen rechten Vergleichsslot. Diese
Slotbelegung autorisiert keine Richtung; `keeper_file_id` und
`candidate_file_id` bleiben in beiden Zuständen leer. Nur `PREFERRED` mit
kompatibler `ACCEPT`-Entscheidung darf gerichtete Endpoints, Candidate,
Intents oder gerichtete Preconditions erzeugen.

Der Keeper bezeichnet die Repräsentation, deren Fortbestand eine zukünftige
Ausführung zuerst erneut beweisen müsste. Der Candidate bezeichnet nur den
möglichen Gegenstand späterer W10-Intents. Er ist kein Löschauftrag und wird
in W9 nicht geöffnet, verschoben, umbenannt, kopiert oder entfernt.

## Keep Preference

### Persistierbare Quality-Evidence-Projektion

Keep Preference verwendet nicht ein flüchtiges `EbookQualityAssessment` und
nicht nur den aggregierten String `ebook_collection_items.quality_status`.
Der bestehende Item-Datensatz speichert die fünf einzelnen
`EbookQualityDimensionStatus`-Werte nicht. Migration `0016` ergänzt deshalb
die minimale immutable Projektion `ConsolidationQualityEvidence` unter dem
Profil `consolidation-quality-evidence/v1`.

```text
ConsolidationQualityEvidence
----------------------------
id
profile
collection_run_id
collection_item_id
observation_id
scan_root_id
source_scan_run_id
collection_profile
analysis_profile
quality_profile
format_label
item_status
aggregate_quality_status
dimensions
item_executions
findings
assessment_fingerprint
created_at
```

Die Projektion ist nur aus einem terminalen `EbookCollectionRun` mit Status
`COMPLETED` oder `COMPLETED_WITH_FAILURES` und einem zugehörigen terminalen
`EbookCollectionItem` mit Status `SUCCEEDED`, `PARTIAL_FAILURE` oder `FAILED`
zulässig. `ERROR` besitzt keine Quality-Projektion und erzeugt
`QUALITY_EVIDENCE_INCOMPLETE`. `collection_profile` ist in v1 exakt
`ebook-collection-analysis/v1`, `analysis_profile` exakt
`ebook-analysis-workflow/v3` und `quality_profile` exakt `ebook-quality/v1`.

`dimensions` enthält genau die kanonische Reihenfolge `METADATA`, `TEXT`,
`COVER`, `STRUCTURE`, `FORMAT_RISK` mit je einem vorhandenen
`EbookQualityDimensionStatus`. Der Builder rehydriert ausschließlich die
persistierten, durch `ebook_collection_item_executions` gebundenen Tool-
Ergebnisse und führt die reine Projektion `ebook-quality/v1` erneut aus. Er
öffnet keine Source Media. Stimmen deren Aggregate, Findings oder
Execution-Referenzen nicht mit dem terminalen Item überein, wird kein Snapshot
persistiert.

`item_executions` wird lückenlos nach
`ebook_collection_item_executions.ordinal` serialisiert und enthält
`step_name`, `disposition` und `execution_id`. Seine Anzahl muss
`reused_step_count + executed_step_count` entsprechen. `findings` wird
lückenlos nach `ebook_collection_findings.ordinal` serialisiert und enthält
`code`, `dimension`, `severity` sowie die nach
`ebook_collection_finding_executions.ordinal` geordneten `execution_id`-
Werte. `finding_count` muss der vollständigen Finding-Menge entsprechen; jede
Finding-Execution muss auch eine Item-Execution desselben Items sein.

`assessment_fingerprint` ist der lowercase SHA-256 über kanonische
`canonical-json/v1`-Bytes mit dem Domain-Tag
`foliotone:consolidation-quality-evidence/v1` und allen materiellen Feldern
außer `id`, `created_at` und `assessment_fingerprint`. Damit bindet er Item,
Run, Observation, Scan-Lineage, alle drei Profile, Format, Item-/Quality-
Status, die fünf Dimensionszustände sowie die vollständigen geordneten
Execution- und Finding-Projektionen.

Keeper und Candidate benötigen je genau einen solchen Snapshot. Beide
`collection_run_id`-Werte dürfen verschieden sein, aber beide Runs müssen
denselben `scan_root_id` und exakt den `source_scan_run_id` des Plans besitzen.
Das jeweilige `collection_item_id` muss dieselbe `observation_id` wie der
zugehörige Plan-Endpoint besitzen. Ein Snapshot aus einem älteren oder anderen
Scan erzeugt `LINEAGE_MISMATCH` und darf nicht als Quality Evidence verwendet
werden.

Das reine `KeepPreferenceOutcome` verwendet folgende Literale:

```text
KeepPreferenceStatus
--------------------
PREFERRED
TIED
BLOCKED

KeepPreferenceReasonCode
------------------------
FEWER_INCOMPLETE_DIMENSIONS
FEWER_ACTION_REQUIRED_DIMENSIONS
FEWER_REVIEW_DIMENSIONS
PREFERRED_FORMAT
SIZE_TIE_BREAKER
TIED
HARD_CONSTRAINT

SizeTieBreakerPolicy
--------------------
DISABLED
PREFER_SMALLER
PREFER_LARGER
```

Das Outcome enthält `preference_id`, Profil und Version, die beiden
kanonischen File-/Observation-Paare, optional gerichtete Keeper-/Candidate-IDs,
Reason Codes, Konfigurationsfingerprint, Evidence-Fingerprint und geordnete
Quality-Evidence-Referenzen sowie `candidate_set_fingerprint`. Der Candidate-
Set-Fingerprint bindet die zwei möglichen gerichteten File-Paare, Profil,
Konfigurationsfingerprint und beide Assessment-Fingerprints in kanonischer
Reihenfolge. `PREFERRED` verlangt genau eine Richtung; `TIED` und `BLOCKED`
dürfen keine Richtung enthalten. Ihre geordneten Quality-Referenzen bleiben
als kanonische linke/rechte Vergleichsslots erhalten und dürfen weder als
Keeper-Entscheidung noch als Review-Freigabe interpretiert werden.

Die Bewertung erfolgt in fester Reihenfolge:

1. Hard Constraints werden geprüft. Ein geschützter Root, unvollständige
   Lineage, fehlende Full-Hash-Evidence oder blockierende Dependency erzeugt
   `BLOCKED`.
2. Für beide exakten `FileObservation`-IDs werden Assessments desselben
   `ebook-quality/v1`-Profils verglichen. Zuerst gewinnt die geringere Zahl
   `INCOMPLETE`, danach `ACTION_REQUIRED`, danach `REVIEW`. `OK` und
   `NOT_APPLICABLE` werden nicht in einen skalaren Quality Score umgerechnet.
3. Nur bei Gleichstand gilt die explizit konfigurierte, vollständig
   fingerprinted Formatpräferenz. Ein nicht gelistetes Format besitzt keine
   implizite Rangfolge.
4. Nur bei weiterem Gleichstand darf die explizite
   `SizeTieBreakerPolicy` angewendet werden. `DISABLED` ist der Default.
5. Bleibt Gleichstand, lautet das Ergebnis `TIED`; weder File-ID noch Pfad
   entscheidet.

`QUALITY_EVIDENCE_INCOMPLETE` bezeichnet eine fehlende, fremde oder mit der
Observation-Lineage inkompatible Quality-Projektion. Der fachliche
`EbookQualityStatus.INCOMPLETE` ist dagegen ein gültiges, negativ geranktes
Bewertungsergebnis und löst diesen Blocker nicht allein aus.

Quality Evidence bestimmt niemals Identity. Eine Keep Preference ist erst
verwendbar, wenn ein `ReviewItem` mit `review_type=KEEP_PREFERENCE`,
`candidate_kind=KEEP_PREFERENCE`, passendem Preference-Snapshot und einer
kompatiblen neuesten `ACCEPT`-Decision vorliegt. Der Producer heißt
`ebook-keep-preference`, Version `1`, Decision Compatibility
`ebook-keep-preference-decision/v1`.

Die technische Review-Bindung führt keinen neuen `EntityKind` ein:

```text
review_type = KEEP_PREFERENCE
subject_kind = FILE
subject_id = kanonisch kleinerer File-Endpoint des RelationCandidate
candidate_kind = KEEP_PREFERENCE
candidate_id = consolidation_keep_preferences.id
```

Der dedizierte Store löst `candidate_id` polymorph gegen
`consolidation_keep_preferences` auf. Er verlangt `status=PREFERRED`, Profil
`ebook-keep-preference/v1`, exakt dieselben kanonischen File-/Observation-
Endpoints, gerichteten Keeper-/Candidate-IDs, Quality-Assessment-IDs sowie
Konfigurations-, Evidence- und Candidate-Set-Fingerprints. Die Fingerprints
des `ReviewItem` und der neuesten Decision müssen exakt den beiden
Preference-Fingerprints entsprechen. Eine bloße vorhandene UUID genügt nicht.

## Konsolidierungs-Candidate und Review

Um einen zirkulären Hash zwischen Plan und Review zu vermeiden, wird vor dem
Plan ein immutable `ConsolidationCandidate` erzeugt. Er enthält:

- `candidate_id`;
- `profile=ebook-consolidation-candidate/v1`;
- Identity- und Keep-Preference-Fingerprint;
- gerichtete Keeper-/Candidate-IDs;
- den kanonischen Dependency- und Precondition-Fingerprint;
- die vollständige Menge vorgesehener Intent-Literale;
- einen materiellen `evidence_fingerprint` und
  `candidate_set_fingerprint`.

Der generische Review-Core referenziert diesen Snapshot mit
`review_type=CONSOLIDATION_CANDIDATE` und
`candidate_kind=CONSOLIDATION_CANDIDATE`. Der Producer heißt
`ebook-consolidation-candidate`, Version `1`, Decision Compatibility
`ebook-consolidation-candidate-decision/v1`. Erst eine kompatible neueste
`ACCEPT`-Decision erfüllt den Planvertrag. Dadurch referenziert der finale
Plan vorhandene Review-Snapshots; kein Review muss den späteren Plan-Hash
selbst referenzieren.

Auch diese Review-Bindung verwendet ausschließlich vorhandene Literale:

```text
review_type = CONSOLIDATION_CANDIDATE
subject_kind = FILE
subject_id = candidate_file_id
candidate_kind = CONSOLIDATION_CANDIDATE
candidate_id = consolidation_candidates.id
```

Der Store löst `candidate_id` polymorph gegen `consolidation_candidates` auf
und vergleicht Profil, Scan-Lineage, Relation-Candidate-ID und -Fingerprint,
Keep-Preference-ID und -Fingerprint, gerichtete Endpoints, Dependency- und
Precondition-Fingerprint, vollständige Intent-Menge sowie Evidence- und
Candidate-Set-Fingerprint. Review-Item und neueste Decision müssen dieselben
Evidence-, Candidate-Set- und Decision-Compatibility-Fingerprints tragen.

`DEFER` bleibt reviewbar. `REJECT` blockiert den Plan. Eine technische
Producer-Version allein entwertet keine Entscheidung; andere Endpoints,
Identity-, Preference-, Dependency-, Intent- oder materielle
Evidence-Fingerprints erzeugen einen neuen Review-Fall.

Der finale Plan projiziert Review-Zustände mit diesen Literalen:

```text
ConsolidationReviewState
------------------------
MISSING
PENDING
DEFERRED
ACCEPTED
REJECTED
STALE
```

Ein `ConsolidationReviewSnapshot` enthält `review_type`, `state`, optional
`review_item_id`, optional `decision_id` und `decision_sequence_no` sowie
Producer-, Decision-Compatibility-, Evidence- und Candidate-Set-Fingerprint.
`ACCEPTED` und `REJECTED` verlangen die neueste kompatible Decision;
`PENDING`, `DEFERRED` und `STALE` dürfen keine ältere Decision als wirksam
darstellen. In v1 enthält `required_reviews` genau einen
`KEEP_PREFERENCE`- und einen `CONSOLIDATION_CANDIDATE`-Snapshot.

## Finale DTO-Struktur

`ConsolidationPlan` besteht aus folgenden unveränderlichen Bestandteilen:

```text
ConsolidationPlan
-----------------
id
profile
plan_version
serializer_version
scan_root_id
source_scan_run_id
identity
keeper
candidate
keep_preference
consolidation_candidate
dependencies
quality_evidence
required_reviews
preconditions
future_operation_intents
blockers
status
execution_state
content_hash
created_at
```

`id` und `created_at` sind Persistenzidentität beziehungsweise
Auditzeitpunkt. Sie gehören nicht zum content-addressed Payload. Alle übrigen
Felder außer `content_hash` werden kanonisch serialisiert. `profile` ist exakt
`consolidation-plan/v1`, `plan_version` exakt `1`, `serializer_version` exakt
`canonical-json/v1` und `execution_state` exakt `NOT_EXECUTABLE`.

`consolidation_candidate` ist ein materieller
`ConsolidationCandidateSnapshot` mit `candidate_id`, Profil, Scan-Root/-Run,
Relation-Candidate-ID und -Fingerprint, Keep-Preference-ID und -Fingerprint,
gerichteten Keeper-/Candidate-IDs, Dependency- und Precondition-Fingerprint,
vollständigen Intents sowie Evidence- und Candidate-Set-Fingerprint. Er ist
Bestandteil des finalen DTO und des Hash-Payloads. Ein abweichender
persistierter `consolidation_candidates`-Datensatz kann daher nicht nur über
eine Foreign-Key-Prüfung akzeptiert werden.

`quality_evidence` enthält genau zwei nach `ConsolidationFileRole` geordnete
`ConsolidationQualityEvidenceSnapshot`-Referenzen. Jede Referenz enthält
Quality-Evidence-ID, Rolle, Collection-Run/-Item, Observation, Scan-Lineage,
die drei Profile, `format_label` und `assessment_fingerprint`. Die
Execution-, Finding- und Dimensionsprojektion wird im Plan nicht dupliziert;
deren vollständige Materialität ist durch den erneut validierten
`assessment_fingerprint` gebunden.

### File Endpoint Snapshot

Keeper und Candidate verwenden jeweils:

```text
ConsolidationFileEndpoint
-------------------------
role
file_id
observation_id
scan_root_id
source_scan_run_id
expected_presence_state
expected_full_sha256
expected_size_bytes
expected_modified_at
expected_observed_at
format_label
```

`expected_presence_state` ist in v1 ausschließlich `PRESENT`.
`expected_full_sha256` ist ein lowercase SHA-256 aus `FILE_SHA256` mit
Algorithmus `sha256` und Version `1`; ein Quick Fingerprint ist unzulässig.
Die beiden Hashwerte müssen bei `EXACT_DUPLICATE` gleich sein. `format_label`
ist in v1 exakt eines der Literale `EPUB`, `MOBI`, `AZW`, `AZW3` oder `PDF`
und enthält keinen Locator. Es muss exakt `format_name` des gebundenen
terminalen `EbookCollectionItem` im zugehörigen
`ConsolidationQualityEvidence`-Snapshot entsprechen. Suffixableitung,
Calibre-Formatlabel oder freie Strings dürfen diesen Wert nicht ersetzen.

Der im Endgame-Plan verwendete Begriff „observation generation“ ist kein
neues Integerfeld. Die Generation wird durch die Kombination aus
`source_scan_run_id` und der exakten `FileObservation.id` repräsentiert. Eine
zusätzliche parallele Generationsnummer wird nicht eingeführt.

## Preconditions

Jeder Plan enthält genau eine geordnete
`ConsolidationFilePreconditionSnapshot` je Rolle und drei geordnete
Dependency-Snapshots je Rolle. Die File-Precondition besteht aus den Feldern
des Endpoint-Snapshots und den folgenden erforderlichen Checks:

```text
ConsolidationPreconditionCode
-----------------------------
FILE_RECORD_UNCHANGED
FILE_OBSERVATION_CURRENT
PRESENCE_IS_PRESENT
FULL_SHA256_MATCHES
SIZE_MATCHES
MODIFIED_AT_MATCHES
KEEPER_READABLE
CALIBRE_RELATIONSHIP_UNCHANGED
SIDECAR_RELATIONSHIP_UNCHANGED
ARCHIVE_RELATIONSHIP_UNCHANGED
REVIEW_APPROVALS_UNCHANGED
```

`KEEPER_READABLE` gilt nur für den Keeper. Alle anderen File-Checks gelten für
beide Rollen. Die drei Relationship-Checks binden jeweils Dependency Kind,
State, Snapshot-/Evidence-Referenzen und materiellen Fingerprint. Der
Review-Check bindet Review-Item-ID, neueste Decision-ID, Sequenz,
Decision-Compatibility-, Evidence- und Candidate-Set-Fingerprint.

W9 bewertet diese Checks nicht gegen das aktuelle Dateisystem. Es speichert
die erwarteten Werte. Eine mögliche W10-Ausführung müsste alle Checks direkt
vor jeder einzelnen Mutation erneut gegen dieselbe logische Quelle prüfen.
Eine Abweichung dürfte niemals durch einen anderen Plan oder einen älteren
Review überstimmt werden.

## Kanonische Serialisierung und `content_hash`

`canonical-json/v1` verwendet folgende Regeln:

1. Der Hash-Payload ist ein JSON-Objekt mit dem Domain-Tag
   `foliotone:consolidation-plan/v1` und allen oben als materiell benannten
   Planfeldern einschließlich `consolidation_candidate` und der beiden
   Quality-Evidence-Snapshot-Referenzen. `id`, `created_at` und
   `content_hash` fehlen.
2. Feldnamen entsprechen exakt den DTO-Feldnamen. Enums werden durch ihre
   Literale, `EntityId` durch seine kanonische lowercase Stringform und
   Zeitpunkte als UTC-RFC-3339 mit sechs Nachkommastellen und `Z` dargestellt.
3. Alle Strings werden vor der Serialisierung nach Unicode NFC normalisiert.
   Nicht endliche Zahlen, Floats und freie Maps mit nicht festgelegten Keys
   sind verboten. Größen und Ordnungszahlen sind JSON-Integer.
4. Objektschlüssel werden lexikografisch sortiert. JSON wird mit UTF-8,
   `ensure_ascii=false`, ohne Whitespace und mit den Separatoren `,` und `:`
   kodiert.
5. Mengen werden vor der Serialisierung zu Listen mit festem Schlüssel
   sortiert: Evidence nach `(role, kind, ref_id, material_fingerprint)`,
   Dependencies nach `(file_role, kind)`, Reviews nach
   `(review_type, review_item_id)`, Preconditions nach
   `(file_role, code)`, Intents nach `(ordinal, code, file_role)` und Blocker
   nach `(code, evidence_refs)`. Doppelte semantische Einträge sind ungültig.
6. `content_hash` ist der lowercase SHA-256-Hexdigest exakt dieser UTF-8-Bytes.

Gleiche materielle Inputs und dieselbe Planversion erzeugen damit dieselben
Bytes und denselben Hash. Änderungen an Relation, FileObservation,
Full-Hash-, Quality-, Preference-, Dependency-, Review-, Precondition- oder
Intent-Snapshots erzeugen einen anderen Hash. Eine andere `id` oder ein
anderer `created_at`-Zeitpunkt ändert den Hash nicht.

Der öffentliche Reporter darf den Payload nicht vollständig ausgeben. Er
zeigt ausschließlich Plan-ID, Profil, Status, Execution-State, Content Hash,
opake Keeper-/Candidate-IDs sowie Counts und Blocker-Literale. Absolute und
relative Pfade, materielle Fingerprints, private Metadaten und Calibre-Locator
bleiben verborgen.

## Persistenzschema für S-EB08-06

Die additive Migration `0016_consolidation_plans` folgt auf
`0015_calibre_library_reconciliation`. Sie legt eine separate Datei
`persistence/consolidation_schema.py` an. Das Schema ist insert-only und
enthält:

```text
consolidation_quality_evidence
--------------------------------
id PK
profile
collection_run_id FK ebook_collection_runs
collection_item_id FK ebook_collection_items
observation_id FK file_observations
scan_root_id FK scan_roots
source_scan_run_id FK scan_runs
collection_profile
analysis_profile
quality_profile
format_label
item_status
aggregate_quality_status
metadata_status
text_status
cover_status
structure_status
format_risk_status
assessment_fingerprint
created_at

consolidation_keep_preferences
--------------------------------
id PK
profile
profile_version
left_file_id FK file_records
left_observation_id FK file_observations
right_file_id FK file_records
right_observation_id FK file_observations
left_quality_evidence_id FK consolidation_quality_evidence
right_quality_evidence_id FK consolidation_quality_evidence
status
keeper_file_id NULL/FK file_records
candidate_file_id NULL/FK file_records
configuration_fingerprint
evidence_fingerprint
candidate_set_fingerprint
created_at

consolidation_keep_preference_reasons
-------------------------------------
preference_id FK consolidation_keep_preferences
ordinal
code

consolidation_keep_preference_evidence
--------------------------------------
preference_id FK consolidation_keep_preferences
ordinal
role
kind
ref_id
material_fingerprint

consolidation_candidates
------------------------
id PK
profile
scan_root_id FK scan_roots
source_scan_run_id FK scan_runs
relation_candidate_id FK relation_candidates
relation_fingerprint
keep_preference_id FK consolidation_keep_preferences
keep_preference_fingerprint
keeper_file_id FK file_records
candidate_file_id FK file_records
dependency_fingerprint
precondition_fingerprint
evidence_fingerprint
candidate_set_fingerprint
created_at

consolidation_candidate_intents
-------------------------------
consolidation_candidate_id FK consolidation_candidates
ordinal
code
file_role

consolidation_plans
-------------------
id PK
profile
plan_version
serializer_version
scan_root_id FK scan_roots
source_scan_run_id FK scan_runs
relation_candidate_id FK relation_candidates
keep_preference_id FK consolidation_keep_preferences
consolidation_candidate_id FK consolidation_candidates
keeper_file_id FK file_records
keeper_observation_id FK file_observations
candidate_file_id FK file_records
candidate_observation_id FK file_observations
status
execution_state
content_hash
created_at

consolidation_plan_evidence
consolidation_plan_dependencies
consolidation_plan_reviews
consolidation_plan_preconditions
consolidation_plan_intents
consolidation_plan_blockers
```

`consolidation_quality_evidence` kopiert Item-Executions und Findings nicht in
eine zweite Historie. `collection_item_id` bindet die bereits vorhandenen,
lückenlos geordneten Zeilen aus `ebook_collection_item_executions`,
`ebook_collection_findings` und `ebook_collection_finding_executions`;
`assessment_fingerprint` bindet deren vollständige kanonische Projektion.
Die fünf Dimensionsstatus werden zusätzlich gespeichert, weil sie im
bisherigen Collection-Schema fehlen und für die feste Keep-Preference-
Reihenfolge benötigt werden. Der Store behandelt den Snapshot als immutable
und lehnt denselben Item-/Profil-Schlüssel mit einem anderen Fingerprint ab.

Die Plan-Child-Tabellen verwenden folgende Spalten:

```text
consolidation_plan_evidence
---------------------------
plan_id FK consolidation_plans
ordinal
role
kind
ref_id
material_fingerprint

consolidation_plan_dependencies
-------------------------------
plan_id FK consolidation_plans
ordinal
file_role
kind
state
snapshot_kind NULL
snapshot_id NULL
material_fingerprint

consolidation_plan_reviews
--------------------------
plan_id FK consolidation_plans
ordinal
review_type
state
review_item_id NULL/FK review_items
decision_id NULL/FK review_decisions
decision_sequence_no NULL
producer_name
producer_version
decision_compatibility_version
evidence_fingerprint
candidate_set_fingerprint

consolidation_plan_preconditions
--------------------------------
plan_id FK consolidation_plans
ordinal
file_role
code
expected_file_id FK file_records
expected_observation_id FK file_observations
expected_scan_root_id FK scan_roots
expected_scan_run_id FK scan_runs
expected_presence_state
expected_full_sha256
expected_size_bytes
expected_modified_at
expected_observed_at
dependency_kind NULL
dependency_state NULL
dependency_fingerprint NULL
review_item_id NULL
review_decision_id NULL

consolidation_plan_intents
--------------------------
plan_id FK consolidation_plans
ordinal
code
file_role

consolidation_plan_blockers
---------------------------
plan_id FK consolidation_plans
ordinal
code

consolidation_plan_blocker_evidence
----------------------------------
plan_id FK consolidation_plans
blocker_ordinal
evidence_ordinal
evidence_plan_ordinal
```

Die Child-Tabellen speichern eine bei null beginnende lückenlose Ordnungszahl.
Preconditions speichern erwartete Werte in Spalten, nicht als beliebiges JSON.
Optionale Spalten sind nur für den dazu passenden Precondition-, Dependency-
oder Review-Typ gesetzt; Schema-Checks erzwingen diese Sum Types. Evidence-,
Dependency- und Review-Referenzen bleiben polymorph, soweit kein eindeutiger
SQL-Fremdschlüssel möglich ist. Der dedizierte Store validiert Typ, Existenz
und Lineage in derselben Transaktion. Ein Plan enthält höchstens 1.024
Evidence-, 6 Dependency-, 16 Review-, 32 Precondition-, 16 Intent- und 32
Blocker-Zeilen. Jeder Blocker darf höchstens 64 geordnete Verweise auf bereits
vorhandene Plan-Evidence besitzen.

Schema-Checks erzwingen mindestens:

- die exakten Profil-, Status-, Execution-State-, Rollen- und Blocker-Literale;
- `format_label IN ('EPUB','MOBI','AZW','AZW3','PDF')` in Endpoint- und
  Quality-Snapshots;
- `item_status IN ('SUCCEEDED','PARTIAL_FAILURE','FAILED')`,
  `aggregate_quality_status IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE')`
  und für jede Dimension
  `IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE','NOT_APPLICABLE')`;
- die exakten v1-Profile `consolidation-quality-evidence/v1`,
  `ebook-collection-analysis/v1`, `ebook-analysis-workflow/v3` und
  `ebook-quality/v1`;
- verschiedene Keeper-/Candidate-IDs und verschiedene Observation-IDs;
- `PRESENT`, nichtnegative Größen und lowercase 64-stellige SHA-256-Werte;
- `execution_state='NOT_EXECUTABLE'`;
- lückenlose eindeutige Child-Ordnungen;
- `UNIQUE(profile, content_hash)`;
- `UNIQUE(collection_item_id, profile, quality_profile)` für den immutable
  Quality-Snapshot;
- `UNIQUE` für den vollständigen semantischen Candidate-Snapshot.

Der Store serialisiert den eingehenden DTO erneut und vergleicht den
berechneten Hash vor jedem Insert. Er validiert den abgeschlossenen Scan,
File-/Observation-/Root-Lineage, die Relation-Endpoints, vollständige
SHA-256-Evidence, beide terminalen Collection-Items und Runs, ihre Profile,
geordneten Execution-/Finding-Projektionen, Quality-/Dependency-Referenzen
sowie die neueste kompatible Review-Decision. Er verlangt für beide Quality-
Snapshots denselben `source_scan_run_id` wie im Plan und löst beide Review-
`candidate_id`-Werte nach den oben definierten technischen Tabellen und
Fingerprints auf. Ein exakter Retry liefert den bestehenden Snapshot.
Derselbe semantische Schlüssel mit abweichendem Payload schlägt geschlossen
fehl. Der generische Update-by-ID-Repositorypfad wird nicht verwendet.
Downgrade wird verweigert, solange eine der neuen Tabellen Daten enthält.

Die Planung bindet sich an einen terminalen Snapshot und verändert keinen
bestehenden rootbezogenen Zustand. Deshalb führt EB-08 keine neue
`ScanRootWriteOwnerKind` ein und erwirbt keine Root-Lease. Plan und alle
Child-Zeilen werden in einer kurzen SQLite-Transaktion geschrieben. Ein später
begonnener Scan ändert den alten Plan nicht; seine Preconditions machen die
alte Generation für jede zukünftige Ausführung erneut prüfpflichtig.

## Non-Execution- und W10-Grenze

`foliotone.consolidation` darf in W9 nur enthalten:

- immutable DTOs und Enum-Verträge;
- reine Builder, Comparatoren, Validatoren und Serializer;
- insert-only Planpersistenz;
- einen read-only Reporter und eine read-only CLI-Projektion.

Das Package darf weder Source Media öffnen noch `os.remove`, `os.unlink`,
`os.rename`, `os.replace`, entsprechende `pathlib`-Methoden, `shutil.move`,
`shutil.rmtree`, Shell-/Subprocess-Ausführung oder mutierende Calibre-
Capabilities importieren oder aufrufen. Es gibt keine generische Command-,
Path- oder Callback-Passthrough-API. Namen wie `execute`, `apply`, `delete`,
`move`, `rename`, `quarantine` oder `purge` dürfen nicht als öffentliche
ausführende Methoden eingeführt werden.

S-EB08-09 prüft diese Grenze statisch für das vollständige
`foliotone.consolidation`-Package und negativ gegen mutierende Calibre-
Subcommands sowie Shell-Löschbefehle. Der Test ergänzt Verhaltensnachweise;
er ist nicht die einzige Sicherheitsgrenze.

Eine spätere W10-ADR darf bestehende Planzeilen nicht durch Umdeutung von
`NOT_EXECUTABLE` ausführbar machen. Sie benötigt einen neuen, separat
persistierten Execution-Authorization-Vertrag, frische Preconditions, eigene
Lease-/Fencing-, Collision-, Rollback- und Recovery-Semantik sowie eine
ausdrückliche Benutzerfreigabe. Ohne diese akzeptierte ADR bleibt jeder
Planstatus nicht ausführbar.

## Zuordnung zu S-EB08-01 bis S-EB08-09

| Paket | Durch dieses Gate festgelegter Vertrag |
|---|---|
| S-EB08-01 | DTO-Struktur einschließlich `ConsolidationQualityEvidence` und materiellem `ConsolidationCandidateSnapshot`, Rollen, Status und Blocker. |
| S-EB08-02 | `canonical-json/v1`, Candidate-/Quality-Materialität, Sortierung, Ausschlüsse und SHA-256-`content_hash`. |
| S-EB08-03 | File-, Generation-, Full-Hash-, Presence-, Size-, Modified-, Format-/Collection-Item- und Review-Preconditions. |
| S-EB08-04 | Root-, Review-, Calibre-, Sidecar-, Archive- und Lineage-Blocker. |
| S-EB08-05 | `ebook-keep-preference/v1`, persistierte Quality-Projektion, feste Vergleichsreihenfolge und exakte Review-Bindung. |
| S-EB08-06 | Migration `0016` einschließlich minimalem Quality-Snapshot, separate Schemadatei, insert-only Store und Idempotenz. |
| S-EB08-07 | v1-actionable Identity, materielle Candidate-Komposition, Review-Auflösung und Statuspriorität. |
| S-EB08-08 | Path-free Reporter mit ausschließlich sicheren IDs, Literalen und Counts. |
| S-EB08-09 | Statisches Mutationsverbot und unveränderte W10-Sperre. |

## Konsequenzen und Grenzen

- EB-08 kann exakte File-Duplikate deterministisch planen, ohne eine
  bibliografische Relation in physische Identity umzudeuten.
- Gleiche Inputs erzeugen einen idempotent wiederverwendbaren Plan; geänderte
  materielle Evidence oder Reviews erzeugen einen neuen Snapshot.
- Fehlende Archive-, Sidecar- oder Calibre-Kenntnis bleibt ausdrücklich
  sichtbar und kann keinen scheinbar freigegebenen Plan erzeugen.
- Die v1-Keep-Preference bleibt erklärbar und verwendet keinen universellen
  Quality Score.
- Diese ADR implementiert keine DTOs, Migration, Persistenz, CLI oder Runtime.
  S-EB08-01 bis S-EB08-09 bleiben eigenständige Implementierungspakete.
- Eine kanonische `Relation`-Projektion, archive-aware File-Identity und jede
  W10-Ausführung bleiben außerhalb dieses Gates.

## Verifikation

Die Folgepakete verwenden ausschließlich synthetische Daten. Golden-Value-
Tests prüfen Unicode, Zeitpunkte, Reihenfolge, Hashänderungen und Ausschlüsse.
Unit- und Integrationstests prüfen ungültige Endpoint-Richtungen, nicht
actionable bibliografische Relationen, Quality-/Identity-Trennung, alle
Blocker und vollständige Preconditions. Zusätzliche Pflichtfälle prüfen:

- beide Quality-Snapshots gegen denselben Plan-`source_scan_run_id`, terminale
  Run-/Item-Status, exakte Profile, vollständige geordnete Findings und
  Executions sowie feste `assessment_fingerprint`-Golden Values;
- Ablehnung fehlender Dimensionsdaten, inkonsistenter Item-Zähler und eines
  Item-Formats außerhalb von beziehungsweise abweichend zu
  `EPUB`/`MOBI`/`AZW`/`AZW3`/`PDF`;
- exakte `subject_kind`-/`subject_id`-/`candidate_id`-Auflösung beider
  Review-Typen sowie Ablehnung einer existierenden, aber semantisch fremden
  Candidate-ID oder eines abweichenden Fingerprints;
- Änderung des finalen `content_hash`, sobald sich ein materielles Feld des
  `ConsolidationCandidateSnapshot` ändert.

Review-Reuse, insert-only Idempotenz, atomarer Rollback, Migration und
path-free Reports bleiben ebenfalls Pflicht. Der statische Non-Execution-Test
prüft das gesamte Package. Reale Sammlungen, Source-Writes, Calibre-Writes,
Archive-Extraktion und Live-Netzwerkzugriff sind kein Teil des EB-08-Gates.
