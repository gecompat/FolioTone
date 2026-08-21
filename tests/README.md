# Tests

Tests must validate FolioTone-owned behavior rather than re-testing third-party libraries.
Test selection, local paths, evidence and the full pull-request gate follow
[`docs/quality/TEST_POLICY.md`](../docs/quality/TEST_POLICY.md).

Planned groups:

- `unit/` — domain rules, normalization, relation logic, matching rules, pure utilities.
- `integration/` — persistence, filesystem index behavior, analyzer adapters, migration behavior.
- `fixtures/` — only synthetic, generated, public-domain, or explicitly redistributable minimal media fixtures.

Never copy private library files, private metadata, real scan databases, or extracted content from a private collection into this repository.

## E-Book-Vergleichs-Fixtures

Der versionierte, vollständig synthetische Korpus unter
`fixtures/ebook_comparison/v1/` enthält maschinenlesbare Ground Truth für
byte-identische Dateien, geänderte Metadaten, dieselbe `Edition`, eine andere
`Edition`/Übersetzung und Tool-Disagreement. Seine Container-Dateien sind
bewusst keine echten EPUB-/MOBI-Dateien; sie halten Datei- und
Text-Fingerprint-Evidence unabhängig von Drittanbieterparsern reproduzierbar.

`unit/test_ebook_comparison_fixtures.py` prüft Schema-Version, sichere relative
Pfade, deklarierte SHA-256-Werte, den produktiven
`EBOOK_NORMALIZED_TEXT`-Vertrag, bibliografische Identitätsebenen und die
Erhaltung widersprüchlicher versionsgebundener Tool-Werte ohne Kanonisierung.
