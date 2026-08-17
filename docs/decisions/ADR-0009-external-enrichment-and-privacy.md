# ADR-0009: External enrichment is provider-based, cached and privacy-bounded

- Status: Accepted
- Date: 2026-08-08

## Context

External catalogs and authority services can substantially improve identification when filenames or embedded metadata are poor. Large collections make naïve per-file online lookups inefficient, rate-limit-prone and unnecessarily privacy-sensitive.

Different providers support different access modes. Some explicitly recommend bulk datasets for large-scale use rather than treating public APIs as a bulk backend.

## Decision

External enrichment is implemented only through provider adapters with explicit operating modes:

- `OFFLINE`;
- `LOCAL_DATASETS`;
- `ONLINE_STRUCTURED`;
- `ONLINE_WEB_RESEARCH` as a separately enabled fallback.

ADR-0026 refines these access types as `ProviderAccessMode` and separates them
from the independent `ProviderCachePolicy` contract. A cache state is not an
operating mode and never expands the provider access permitted here.

Provider adapters must:

- preserve source/provenance and provider identifiers;
- use persistent local cache/index state under `/data`;
- prefer bulk/local datasets for large-scale authority indexing when the provider supports/recommends them;
- obey provider licensing, access and request constraints;
- minimize transmitted fields;
- never transmit absolute local paths;
- avoid transmitting collection-wide inventories unless explicitly configured and permitted;
- keep credentials in local configuration outside Git;
- return candidates/assertions rather than directly replacing canonical values.

Generic web research and AI inference may produce supporting candidates but cannot be the sole authoritative basis for destructive decisions.

## Consequences

- Internet access is useful but not required for every scan.
- Repeated lookups become cheaper and leak less collection context.
- Provider outages do not invalidate locally cached identity results.
- Provider-specific schemas, credentials and request logic remain outside core domain/matching code.
- A provider adapter cannot be implemented until its current access rules, licensing and cache/redistribution constraints have been reviewed and documented.
