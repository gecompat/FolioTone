# Synthetische Open-Library-Fixtures v1

Diese Fixtures sind vollständig handgeschriebene JSON-Strukturen für
S-EB03B-01 und ADR-0036. Sie verwenden synthetische Werte in den öffentlich
dokumentierten API-Shapes; keine Antwort wurde von einem Provider kopiert oder
aus einer Sammlung abgeleitet.

Die Dateien decken direkte Work-, Edition- und Author-Ergebnisse, ISBN-,
OCLC-/LCCN-Lookups, ein leeres Ergebnis, Sparse Data, eine ungültige JSON-
Antwort sowie die begrenzte Search-Pagination ab. `search_page_1_requires_page_2`
hat mehr als zehn Treffer, aber kein Dokument mit einem gültigen Work-Key und
eingebettetem Edition-Key oder ISBN. Deshalb korreliert es mit
`search_page_2`. `search_page_1_stop` und `search_page_1_stop_isbn_only` enthalten
dagegen einen starken Treffer (einmal mit Edition-Key, einmal nur mit ISBN)
und dürfen trotz hoher Trefferzahl keine zweite Seite anfordern.

Die Fixtures enthalten keine lokalen Pfade, Dateinamen, Scanstrukturen,
Sammlungsinventare, Dumps, Rohantworten oder privaten Metadaten. Sie sind nicht
für Netzwerk-, Produktions- oder Persistenztests bestimmt.
