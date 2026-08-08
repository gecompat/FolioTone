# Tests

Tests must validate FolioTone-owned behavior rather than re-testing third-party libraries.

Planned groups:

- `unit/` — domain rules, normalization, relation logic, matching rules, pure utilities.
- `integration/` — persistence, filesystem index behavior, analyzer adapters, migration behavior.
- `fixtures/` — only synthetic, generated, public-domain, or explicitly redistributable minimal media fixtures.

Never copy private library files, private metadata, real scan databases, or extracted content from a private collection into this repository.
