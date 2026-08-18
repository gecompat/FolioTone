# ADR-0030: Versionierte E-Book-Matcherprofile und konservatives Review-Routing

- Status: Accepted
- Datum: 2026-08-18

## Kontext

ADR-0029 begrenzt den Suchraum und fixiert die book-only Relation Contracts.
Ein Candidate Block ist jedoch noch keine Relation. EB-06 muss aus bereits
persistierter Evidence nachvollziehbare Vorschläge erzeugen, ohne einen
universellen Score, eine unkalibrierte automatische bibliografische
Bestätigung oder eine zweite Evidence-Auswertung neben
`ebook-comparison/v1` einzuführen.

Die bestehenden `MatchStatus`-Literale bleiben verbindlich. Confidence ist
eine profilspezifische Heuristik und keine empirisch kalibrierte
Wahrscheinlichkeit. Provider- oder Tool-Übereinstimmung darf starke
widersprechende lokale Evidence nicht überstimmen.

## Entscheidung

Jeder unterstützte `RelationType` besitzt ein eigenes unveränderliches
`MatcherProfile` mit:

- festem Namen und Version;
- eigener Feature-Allowlist;
- profilspezifischen ganzzahligen Gewichten;
- ausdrücklich benannten harten Contradictions;
- einer getrennten `decision_compatibility_version`.

EB-06A führt zunächst Profile für `EXACT_DUPLICATE`, `SAME_EDITION` und
`SAME_WORK` ein. Ein Scorer akzeptiert ausschließlich bereits begrenzte,
kanonisch sortierte Features. Er führt keine collection-weite Suche aus,
öffnet keine Source Media und persistiert weder `Relation` noch Review-Daten.

Ein Feature enthält nur einen stabilen Code, `PRESENT` oder `ABSENT`, einen
materiellen SHA-256-Fingerprint und begrenzte opake Evidence-IDs. Der
materielle Fingerprint bindet die inhaltliche Semantik; zufällige Row-IDs,
Zeitpunkte, Pfade, Titel, Namen und Identifierwerte beeinflussen den
Matcher-Evidence-Fingerprint nicht.

## Status- und Confirmation-Regel

`EXACT_DUPLICATE` darf nur dann automatisch `CONFIRMED` werden, wenn ein
vollständiger `FILE_SHA256`-Gleichheitsnachweis vorhanden ist. Ein
unterschiedlicher vollständiger File-Hash verwirft diesen Relation Candidate.

Erstmalige bibliografische Kandidaten für `SAME_EDITION` und `SAME_WORK`
bleiben unabhängig von ihrer Confidence `REVIEW_REQUIRED`. EB-06A aktiviert
keine automatische bibliografische Confirmation. Eine spätere Aktivierung
verlangt ein neues Decision-Compatibility-Profil und null bekannte False
Positives im kontrollierten adversarial Korpus.

Harte Contradictions führen zu `REJECTED`. Für `SAME_EDITION` sind dies
insbesondere widersprüchliche bestätigte Edition-Resolution, ausdrücklich
widersprüchliche Edition-Identifier oder materiell widersprüchlicher Inhalt.
Ein bloß anderer normalisierter Text-Hash ist noch kein materieller
Inhaltswiderspruch. Für `SAME_WORK` ist eine widersprüchliche bestätigte
Work-Resolution hart; abweichende Sprache, Titel oder Text können dagegen
eine Übersetzung beziehungsweise andere Edition desselben Work beschreiben
und bleiben weiche Contradictions.

## Confidence und Explanation

Confidence wird je Profil aus dem Verhältnis vorhandener unterstützender
Gewichte zu allen tatsächlich bewerteten Gewichten berechnet. `ABSENT`
bedeutet unbekannt beziehungsweise nicht verfügbar und fließt nicht als
negative Evidence ein. Der Wert ist nur innerhalb desselben Matcherprofils
vergleichbar.

Die Explanation enthält ausschließlich Feature-Code, Effekt, Profilgewicht
und Anzahl der Evidence-Referenzen. Materielle Werte und private Pfade werden
nicht ausgegeben. Ein kanonischer Evidence-Fingerprint bindet Relation Type,
Matcherprofil, Decision Compatibility sowie sortierte Feature-Codes,
-Zustände und materielle Fingerprints.

## Persistenz- und Review-Grenze

EB-06A definiert reine Ergebnisse. Persistierte Relation Candidates,
Explanation-Links, idempotente Wiederverwendung und generisches
Matching-Review folgen in einer separaten additiven EB-06B-Welle. Eine
`Relation` darf erst aus einer nach dem künftigen Vertrag akzeptierten oder
technisch zulässig bestätigten Candidate-Entscheidung entstehen.

EB-02-Review-Historie bleibt append-only. Eine Wiederverwendung verlangt
später dieselben Endpoints, denselben Relation Type, denselben materiellen
Evidence-Fingerprint und dieselbe `decision_compatibility_version`. Eine rein
technische Matcher-Version darf bei unveränderter Kompatibilitätsversion
keine erneute Benutzerentscheidung erzwingen.

## Sicherheit und Aussagegrenzen

- Keine Source-Media-, Calibre- oder Dateisystemmutation wird eingeführt.
- Classification, Cover-Ähnlichkeit, Provider Agreement und einzelne
  Metadatenfelder bleiben allein unzureichende Identity Evidence.
- Der Slice verwendet ausschließlich synthetische Tests und kein Netzwerk.
- W10 bleibt unverändert blockiert.

## Verifikation

Deterministische Unit-Tests prüfen exakte Hash-Confirmation, harte
Contradictions, unvermeidbares Review erstmaliger bibliografischer Kandidaten,
Übersetzungsfälle, kanonische Endpoint-Reihenfolge, bounded/path-freie
Explanation sowie Fingerprint-Stabilität gegenüber Row-ID-Wechseln.
