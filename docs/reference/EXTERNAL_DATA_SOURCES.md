# External Data Sources Registry

This registry records external knowledge sources that may help FolioTone resolve identities, enrich metadata, classify content or generate stronger matching evidence.

A listed source is a **candidate knowledge provider**, not an unconditional dependency. Specialist executable software belongs in `EXTERNAL_TOOLS.md`.

Before implementation, confirm current API/data access rules, licensing, attribution, rate limits, data quality and operational requirements.

## General source policy

Preferred order for high-volume processing:

1. existing local FolioTone knowledge/cache;
2. locally imported provider datasets where permitted and practical;
3. structured provider APIs for targeted lookups;
4. generic web research only as a controlled fallback.

External information is evidence. Provider data must retain provenance and must not overwrite observed source metadata.

Never transmit absolute local paths, private collection inventories or unnecessary raw filenames to external services.

## Books and authority data

### Open Library

Purpose:

- author candidates;
- Works and Editions;
- identifiers and bibliographic metadata;
- cover references where useful.

Access strategy:

- targeted, low-volume real-time lookups through documented APIs;
- prefer official monthly data dumps for bulk import/index construction;
- cache provider results.

Official references:

- https://openlibrary.org/developers
- https://openlibrary.org/developers/api
- https://openlibrary.org/data

Implementation note:

Open Library explicitly distinguishes low-volume API use from bulk access and recommends data dumps rather than treating the API as a bulk backend. A FolioTone-wide author/work authority index should therefore evaluate local dump ingestion rather than issuing one online request per file.

### GND / Deutsche Nationalbibliothek

Purpose:

- authority identities for persons;
- corporate bodies/organizations;
- works and subjects;
- stable GND identifiers;
- aliases/structured authority relationships where available.

Access strategy:

- evaluate GND Linked Data, Entity Facts and available bulk/retrieval services;
- cache stable identifiers and normalized projections locally;
- use GND especially as a high-value authority source for German-language collections.

Official references:

- https://sta.dnb.de/doc/GND
- https://www.dnb.de/DE/Professionell/Metadatendienste/Datenbezug/LDS/lds_node.html
- https://www.dnb.de/DE/Professionell/Metadatendienste/metadatendienste_node.html

Implementation note:

The official GND documentation describes stable identifiers for represented entities and provides the GND data under CC0 1.0. Terms must still be rechecked when implementing a concrete access path.

### Wikidata

Purpose:

- cross-domain entity resolution;
- aliases and multilingual labels;
- cross-identifiers linking authority systems;
- dates, relationships and classification hints;
- fallback enrichment when specialist catalogs disagree or lack an entity.

Access strategy:

- targeted SPARQL/API queries;
- consider local subsets/dumps only if scale justifies the operational cost;
- never treat a Wikidata name match alone as identity proof.

Official references:

- https://www.wikidata.org/wiki/Wikidata:Data_access
- https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service

Implementation note:

Structured Wikidata data is published under CC0. Provider mappings and query logic must nevertheless be versioned because statements and external identifiers change over time.

## Music data

### MusicBrainz

Purpose:

- Artists and aliases;
- Works/compositions;
- Recordings;
- Release Groups;
- Releases;
- labels and identifiers;
- relationship/credit information;
- classical work hierarchies and role relationships.

Access strategy:

- targeted Web Service lookups for interactive/small-scale enrichment;
- evaluate official database dumps/local replication for large-scale authority indexing;
- persist MBIDs as namespaced external identifiers;
- cache normalized projections rather than repeatedly retrieving the same entity.

Official references:

- https://musicbrainz.org/doc/Developer_Resources
- https://musicbrainz.org/doc/MusicBrainz_Database
- https://musicbrainz.org/doc/MusicBrainz_Database/Download
- https://musicbrainz.org/doc/Work
- https://musicbrainz.org/doc/Release_Group
- https://musicbrainz.org/doc/Release
- https://musicbrainz.org/doc/Style/Classical/Works

Implementation note:

MusicBrainz explicitly models Artists, Works, Recordings, Release Groups, Releases and relationships. FolioTone should map provider data into its own domain concepts rather than exposing MusicBrainz schema objects throughout the core.

A local MusicBrainz server/mirror is an infrastructure/tool deployment option documented separately in `EXTERNAL_TOOLS.md`; the MusicBrainz data model/service remains the knowledge source.

### AcoustID

Purpose:

- identify audio using an acoustic fingerprint;
- generate Recording candidates even when filenames and tags are poor;
- bridge fingerprints to MusicBrainz metadata where returned by the service.

Access strategy:

- calculate Chromaprint fingerprints locally through the Chromaprint/`fpcalc` ToolProvider documented in `EXTERNAL_TOOLS.md`;
- send only the minimum fingerprint/duration/lookup fields required by the configured AcoustID operation;
- cache lookup results;
- preserve lookup score/provider result as evidence, not as automatic proof;
- keep API credentials outside Git.

Official references:

- https://acoustid.org/webservice
- https://acoustid.org/license

Implementation note:

Chromaprint and AcoustID are deliberately separated in FolioTone architecture: Chromaprint is local specialist processing; AcoustID is an external knowledge lookup service. One AcoustID lookup can still be ambiguous; downstream entity resolution/matching must retain provider score and alternatives.

## Provider classes to research later

The following are useful candidates but require a dedicated current licensing/access/coverage review before a concrete adapter is implemented:

### Archiv-Passwortkandidaten

Der vom Benutzer genannte Name `Newzcrabber` muss zunächst einer konkreten,
aktuell betriebenen Quelle mit dokumentierter Automationsschnittstelle
zugeordnet werden. FolioTone nimmt weder Produktidentität noch Eignung vor
dieser Prüfung an. Zusätzlich können geeignete Usenet-/NZB-Metadatenquellen
bewertet werden, sofern ihre aktuellen Bedingungen und Schnittstellen eine
rechtmäßige, privacy-bounded Nutzung erlauben.

Ein späterer Adapter ist separat zu aktivieren, überträgt keine absoluten oder
relativen Sammlungspfade und bevorzugt strukturierte Release-/NZB-Identifier
gegenüber rohen Dateinamen. Antworten erzeugen ausschließlich
Provenance-behaftete Passwortkandidaten hinter einem lokalen Secret Handle.
Passwortmaterial erscheint nicht in Provider Cache, Logs, Reports oder Git.
Ohne stabile dokumentierte Schnittstelle wird eine begründete
Nichtintegration festgehalten.

### Bibliographic / authority

- VIAF;
- ISNI;
- Library of Congress authority/catalog services;
- national library catalogs beyond GND/DNB;
- Google Books;
- Crossref where DOI-bearing publications are relevant;
- Internet Archive/Open Library adjacent services.

### Music / release metadata

- Cover Art Archive;
- Discogs;
- other label/catalog/discography sources with suitable terms and APIs.

### Classification / vocabularies

- controlled subject vocabularies exposed through GND or linked mappings;
- library classification systems where licensing permits;
- MusicBrainz genres/tags as one evidence source;
- Wikidata classes/relationships as supplementary evidence.

## Source evaluation checklist

Before adding a provider adapter, document:

- provider purpose and authoritative scope;
- stable identifiers available;
- API vs. bulk/download access;
- request/rate constraints;
- license/terms and attribution requirements;
- permitted caching/redistribution;
- freshness/update model;
- multilingual/alias coverage;
- data quality limitations;
- privacy implications of submitted lookup fields;
- behavior when provider is offline/unavailable;
- how provider records map into FolioTone assertions without overwriting observations.

## Operational principle

A large collection must not depend on successful internet access for every scan. External knowledge should progressively build a persistent local authority/enrichment cache or local imported index so repeated analyses become cheaper, faster and less privacy-sensitive.
