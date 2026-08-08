# Incremental Indexing, Entity Resolution and Matching

## Indexing goals

A full initial scan may be expensive; subsequent scans must avoid unnecessary I/O and hashing.

Planned observation states:

- `NEW`
- `UNCHANGED`
- `MODIFIED`
- `MOVED`
- `RENAMED`
- `MISSING`
- `DELETED`

`MISSING` and `DELETED` are deliberately distinct. Deletion requires enough evidence that the scan root was successfully observed and the file is truly absent according to the future deletion policy.

## Planned hash/fingerprint stages

1. cheap filesystem observations such as size and timestamps;
2. quick/partial fingerprint when useful;
3. full streaming SHA-256 when required;
4. media-specific fingerprint from the relevant analyzer;
5. later perceptual/acoustic/image fingerprints where useful.

Hash/fingerprint values must be stored with algorithm and version where the representation can evolve.

## Move/rename detection

Path is not file identity. The implementation should use combinations of prior observations, size, hashes, and platform-available file identity cautiously. Platform-specific identifiers must not become the only durable identity.

## Filename/path candidate generation

Before entity resolution, filenames and directory context may emit `FieldCandidate` values such as possible author/artist, title, series, track/disc number, year, language or edition hints.

Rules:

- retain the original filename/path observation;
- emit derived candidates rather than setting canonical values;
- version parsing/normalization rules;
- support collection-specific conventions without hard-wiring them into domain models;
- do not send absolute paths to external providers.

## Entity resolution before duplicate matching

Entity resolution determines what observed values probably refer to. Duplicate matching determines what relationship exists between files/entities.

Examples:

- `Asimov, I.` -> candidate Agent `Isaac Asimov`;
- an ISBN -> candidate Edition/Work;
- an acoustic fingerprint -> candidate Recording;
- a classical catalog designation + composer -> candidate MusicWork.

Resolution evidence can come from:

- embedded metadata;
- filename/path candidates;
- local confirmed aliases;
- imported local authority datasets;
- structured online providers;
- generic web research only when separately enabled.

Equal normalized names never prove identity. Resolved external IDs are strong evidence but still retain provider/provenance.

## External lookup strategy

Large collections must not issue one online lookup per file indefinitely.

Preferred strategy:

1. use existing local canonical/resolution knowledge;
2. query local imported provider indexes/cache;
3. use online structured lookups for unresolved/high-value cases;
4. cache results;
5. use generic web research only as a controlled fallback.

Provider/query/mapping versions must be retained so stale resolution results can be identified.

## Duplicate/relation candidate generation

Never compare every item with every other item for a large collection.

Candidate blocks may use:

E-books:
- exact hashes;
- ISBN/other identifiers;
- resolved Work/Edition IDs;
- normalized author/title keys;
- series context;
- text/content fingerprint buckets;
- later cover-image fingerprint buckets.

Music:
- exact hashes;
- MusicBrainz IDs/ISRC/ISWC where present;
- resolved Agent/MusicWork/Recording/ReleaseGroup/Release IDs;
- normalized artist/title/work keys;
- duration buckets;
- classical catalog designation/composer blocks;
- audio/acoustic fingerprint buckets;
- later cover-image fingerprint buckets.

Blocking logic must be versioned/configurable where behavior can change.

## Scoring

Scoring happens only after duplicate/relation candidate generation. Rules/weights must be configurable or otherwise versioned so old decisions can be traced to the matcher behavior that produced them.

A score alone is insufficient. Persist evidence and an explanation.

Example conceptual e-book result:

```text
relation: SAME_EDITION
confidence: 0.985
status: PROBABLE

+ ISBN-13 identical                  strong positive
+ resolved author Agent identical    positive
+ title similarity high              positive
+ normalized text similarity high    strong positive
- publisher differs                  weak negative
```

Example conceptual music result:

```text
relation: SAME_RECORDING
confidence: 0.97
status: PROBABLE

+ acoustic fingerprint candidate     strong positive
+ resolved Recording ID identical    strong positive
+ duration within tolerance          positive
- release metadata differs           neutral for recording identity
```

Thresholds for automatic acceptance/review/rejection are not fixed in W0. They must be calibrated with synthetic/public test corpora and false-positive protection.

## Identity levels matter

A match must state the level at which equality/relationship is claimed.

E-books:

- exact File;
- same content;
- same Edition;
- same Work but different Edition.

Music:

- exact File/content/transcode;
- same MusicWork but different Recording;
- same Recording;
- same ReleaseGroup;
- same concrete Release.

A remaster, remix or new performance must not be collapsed merely because title/composer/album text is similar.

## Classification is supporting evidence

Classification facets can improve candidate blocking/search but generally should not be high-confidence identity proof by themselves.

Classical-specific facets such as period, work form and instrumentation are distinct from broad genre labels.

## Re-analysis

These derived components must be version-representable:

- analyzer;
- fingerprint algorithm;
- normalization rules;
- filename/path parser;
- authority/entity resolver;
- external provider mapping/import;
- classification rules;
- matcher/rules.

A later implementation should be able to determine which stored results are stale without discarding all unaffected work.
