# Synthetische `calibredb`-Library-Fixtures v1

Diese Fixtures bilden den read-only Vertrag aus ADR-0033 ohne reale
calibre-Bibliothek ab. Alle Namen, IDs, Metadaten, Pfade und Hashwerte sind
synthetisch. Die Pseudowurzel `__FOLIOTONE_CALIBRE_ROOT__` ersetzt den lokalen
Bibliothekspfad bereits in der simulierten Toolausgabe.

`cases_a_g/` enthält eine streng nach calibre-ID sortierte JSON-Seite, eine
leere Abschlussseite, eine Exact-ID-Suchausgabe, Kategorie-CSV, zwei
OPF-Ausgaben und Ground Truth für die Fälle A bis G. `empty/` modelliert eine
leere Bibliothek. `malformed/` enthält absichtlich ungültige oder semantisch
unzulässige Ausgaben. Diese dürfen nie als erfolgreiche Evidence gelten.

Die Fixtures autorisieren keine freie Command-Zusammensetzung, keine
Source-Media-Änderung und keine mutierende calibre-Operation.
