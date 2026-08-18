# FolioTone Glossar

Dieses Glossar definiert die kanonischen fachlichen Kernbegriffe des Projekts. Es ersetzt keine ausführliche Architektur- oder Modelldokumentation, verhindert aber, dass verschiedene Dokumente oder KI-Systeme für dasselbe Konzept unterschiedliche Bezeichnungen einführen.

| Kanonischer Begriff | Bedeutung in FolioTone | Zu vermeidende Ersatzbegriffe |
|---|---|---|
| `Agent` | Identität einer Person, Gruppe oder Organisation, die über Rollen mit Werken, Editionen, Aufnahmen oder Veröffentlichungen verbunden wird. | AuthorEntity, ArtistEntity, PersonRecord |
| `AgentName` | Eine konkrete Namensform eines `Agent`, beispielsweise kanonischer Name, Alias, Pseudonym, Sortierform oder `credited_as`. | AuthorNameEntity, ArtistAliasRecord |
| `ExternalIdentifier` | Namespaced Identifier aus einem externen Katalog oder Provider. Er ist Evidenz und keine FolioTone-interne Identität. | ExternalId als unqualifizierter Sammelbegriff |
| `Work` | Abstraktes Buchwerk unabhängig von einer konkreten Ausgabe. | BookWork, Titelobjekt |
| `Edition` | Konkrete Buchausgabe oder editionsbezogene Manifestation eines `Work`. | BookVersion, AusgabeEntity |
| `Series` | Buch- oder Werkreihe, deren Zugehörigkeit getrennt über `SeriesMembership` modelliert wird. | BookCollection als Synonym ohne Definition |
| `MusicWork` | Abstraktes musikalisches Werk oder eine Komposition, unabhängig von einer konkreten Aufnahme. | SongEntity, CompositionRecord |
| `Recording` | Konkrete aufgezeichnete Darbietung eines musikalischen Inhalts. | Track, Song, AudioFile |
| `ReleaseGroup` | Logische Gruppe eng zusammengehöriger Musikveröffentlichungen. | AlbumGroup |
| `Release` | Konkrete Musikveröffentlichung, beispielsweise eine bestimmte Ausgabe eines Albums. | Album als technischer Identitätstyp |
| `ReleaseRecording` | Zuordnung eines `Recording` zu einer Position innerhalb eines `Release`. | TrackEntity |
| `FileRecord` | Aktueller FolioTone-Datensatz für eine physische Datei innerhalb eines `ScanRoot`. | MediaObject |
| `FileObservation` | Tatsächlich beobachteter Dateizustand in einem konkreten `ScanRun`. | FileSnapshot ohne definierten Vertrag |
| `FileScanEvent` | Klassifizierte Veränderung oder Abwesenheitsinformation eines Files in einem `ScanRun`. | FileStatusChange als paralleler technischer Vertrag |
| `FileRelocationCandidate` | Evidenzbehafteter Kandidat, dass ein erstmals `MISSING` gewordener und ein im selben Scan `NEW` beobachteter `FileRecord` einen Move-/Rename-Zusammenhang haben könnten. Die beiden File-Identitäten bleiben getrennt. | MoveRecord, RenameResult, bestätigte File-Identität |
| `ScanRoot` | Logische Quelle einer Sammlung. Der tatsächliche Hostpfad bleibt Runtime-Konfiguration. | LibraryPath als persistierte Identität |
| `ScanRun` | Eine nachvollziehbare Ausführung eines Scans für einen `ScanRoot`. | ScanSession, ScanJob ohne definierten Vertrag |
| `Provenance` | Nachweis, woher eine Beobachtung, Aussage oder Ableitung stammt und in welchem Kontext sie entstanden ist. | SourceInfo als unstrukturierter Ersatz |
| `Evidence` | Nachvollziehbare Evidenz, die eine Relation oder Entscheidung unterstützt oder ihr widerspricht. Evidence ist nicht automatisch ein Beweis. | Proof, Beweis |
| `ValueAssertion` | Aussage über einen Wert mit Zustand und Provenance, ohne den beobachteten Rohwert zu überschreiben. | CanonicalMetadata als Sammelersatz |
| `Entity Resolution` | Verfahren zur Bestimmung, welche beobachteten Namen, IDs oder Kandidaten dieselbe reale Entität repräsentieren. | Duplicate Matching für Personenidentität |
| `Matching` | Bewertung einer möglichen Beziehung zwischen bereits geeigneten Kandidaten, beispielsweise `SAME_EDITION` oder `SAME_RECORDING`. | Entity Resolution als Synonym |
| `Relation` | Typisierte Beziehung zwischen zwei FolioTone-Entitäten mit Status und Confidence. | DuplicateFlag |
| `Fingerprint` | Versionierte technische Signatur eines Files, Inhalts oder Audioinhalts. | Hash als Oberbegriff für alle Fingerprints |
| `ToolProvider` | Austauschbarer Adapter zu einer dokumentierten Automationsschnittstelle eines spezialisierten externen Werkzeugs. | Tool Plugin, Tool-Anbieter-Engine |
| `ToolExecution` | Eine konkrete, auditierbare Ausführung eines `ToolProvider` mit Tool-, Adapter-, Input- und Konfigurationsidentität. | ToolRun ohne Vertrag |
| `ToolResult` | Normalisiertes strukturiertes Ergebnis einer `ToolExecution`. | ToolMetadata als allgemeiner Ersatz |
| `FieldCandidate` | Nicht kanonischer Feldwert aus Parsing, Metadaten oder anderer Ableitung mit nachvollziehbarer Quelle, Version und Confidence. | CanonicalField, bestätigter Metadatenwert |
| `ResolutionCandidate` | Persistierter, versionierter und nicht kanonischer Vorschlag, ein Subject einer vorhandenen Agent-, Work-, Edition- oder Series-Identität zuzuordnen. Materielle Evidence und die vollständige konkurrierende Kandidatenmenge sind per Fingerprint gebunden. | Auto-Merge, kanonische Zuordnung |
| `ResolutionEvidenceLink` | Konkreter Provenance-Link eines `ResolutionCandidate` auf persistierte unterstützende oder widersprechende Evidence mit expliziter behaupteter Identitätsebene. | Beweis, unreferenzierte Erklärung |
| `ReviewItem` | Persistierter, begrenzter und optimistisch gefenceter fachlicher Prüffall. | UI-Zeile, mutable Entscheidung |
| `ReviewDecision` | Append-only ACCEPT-, REJECT- oder DEFER-Entscheidung mit monotoner Sequenz und gebundenen Evidence-/Candidate-Set-Snapshots. | überschreibbarer Reviewstatus |
| `EbookMetadataCandidate` | Provider-neutraler E-Book-Feldkandidat, der als `ToolResult` an die exakte `ToolExecution` und `FileObservation` gebunden wird. Gruppierte Feldpfade erhalten Zusammenhänge etwa zwischen Identifier-Namespace/-Wert, Contributor-Feldern oder Series-Name/-Position. | BookMetadata als kanonische Wahrheit |
| `EbookQualityAssessment` | Versionierte, mehrdimensionale Projektion begrenzter E-Book-Evidence für eine `FileObservation`. Sie trennt unvollständige Analyse von Review- und Maßnahmenbefunden, verwendet keinen skalaren Score und trifft keine Identitätsentscheidung. | QualityScore, DuplicateVerdict |
| `EbookComparisonOutcome` | Versionierter read-only Vergleich persistierter Datei-, Text-, Metadaten-, Struktur- und Cover-Evidence zweier exakter `FileObservation`-IDs. Er trennt Dimensionszustand von Evidence-Coverage und erzeugt keine `Relation` oder Identitätsentscheidung. | DuplicateResult, MatchVerdict |
| `EbookCollectionRun` | Persistierter, fortsetzbarer Analyse-Lauf über einen unveränderlichen Plan aktueller E-Book-`FileObservation`-Datensätze aus genau einem abgeschlossenen `ScanRun`. Er speichert Lifecycle, Profile, Workergrenze und Lease, aber keine Sammlungspfade oder Metadatenwerte. | Collection Scan als Synonym, globale Dateiliste |
| `EbookCollectionItem` | Persistierter Arbeits- und Ergebnisstatus genau einer geplanten `FileObservation` innerhalb eines `EbookCollectionRun`, einschließlich Versuchszahl und begrenzter Analyse-/Quality-Zusammenfassung. | File Job ohne Snapshot-Bezug, MatchResult |
| `EbookCollectionReportSnapshot` | Read-only Projektion eines persistierten, nicht mehr aktiven `EbookCollectionRun` mit vollständigen Summen sowie begrenzten Review-Items und technischen Duplicate-/Varianten-Kandidaten. Sie öffnet keine Source Media und erzeugt keine Identitätsentscheidung. | Library Report als kanonische Wahrheit, MatchResult |
| `EbookCollectionCandidateGroup` | Begrenzte technische Review-Gruppe auf Basis gleicher vollständiger Datei-Hashes oder gleicher normalisierter Textfingerprints bei unterschiedlichen Datei-Hashes. Sie ist keine `Relation` und kein Duplicate-Verdict. | Duplicate Group als bestätigte Identität |
| `CandidateBlock` | Begrenzte, versionierte und path-freie Gruppierung aktueller Observations anhand eines domain-separierten Key-Fingerprints. Sie reduziert den Suchraum, bestätigt aber keine Identität und wird in EB-05 nicht persistiert. | Duplicate-Gruppe als bestätigte Relation, globale Paarliste |
| `RelationContract` | Book-only Vertrag für zulässige Endpoint-Ebene, Identity-Effekt und mindestens erforderliche Evidence-Codes eines `RelationType`. Er erzeugt weder Score noch persistierte `Relation`. | Match-Ergebnis, automatische Relation |
| `MatcherProfile` | Versionierter, relation-spezifischer Vertrag für zulässige Features, Gewichte, harte Contradictions und Decision Compatibility. Seine Confidence ist keine universelle Wahrscheinlichkeit. | globaler Duplicate Score, unveränderliche Wahrheit |
| `MatcherOutcome` | Reines, path-freies Scoring-Ergebnis für zwei kanonisch geordnete Endpoints mit Status, Confidence, materiellem Evidence-Fingerprint und begrenzter Explanation. Es ist noch keine persistierte `Relation`. | bestätigte Relation, Löschentscheidung |
| `RelationCandidate` | Insert-only Snapshot eines reproduzierten `MatcherOutcome` für einen abgeschlossenen Scan mit kanonischen Endpoints sowie gebundenen Evidence- und Candidate-Set-Fingerprints. Er ist noch keine persistierte `Relation`. | Duplicate-Verdict, Löschentscheidung |
| `RelationCandidateEvidenceLink` | Konkreter, begrenzter Feature-Link eines `RelationCandidate` mit materiellem Fingerprint und optionaler opaker Referenz auf persistierte Evidence. | Rohmetadatenkopie, unreferenzierte Erklärung |
| `EbookCandidateHashRun` | Persistierter, rootweit geleaster und gefenceter Lauf zur selektiven Vollhash-Bestätigung aktueller Quick-Duplikatkandidaten. Er speichert nur Source-Scan-Bezug, Phase, Heartbeat-/Lease-Zeitpunkte und Zähler, aber keine Pfade, Dateinamen oder Hashwerte. | ungeschützter Hash-Job, Fingerprint als Laufstatus |
| `ScanRootWriteLease` | Dauerhafter, rootweiter Besitz- und Fencing-Vertrag für genau einen legitimen Scanner-, Hash- oder E-Book-Analyse-Writer. Eine monotone Fence-Epoch blockiert stale Besitzer auch bei wiederverwendeter Owner-ID oder Tokenfolge. | SQLite-Lock, per-Run-Lease, verteiltes Lock |
| `ToolArtifact` | Persistiertes Runtime-Artefakt einer `ToolExecution`, beispielsweise stdout, stderr oder ein Report. | LogFile als allgemeiner Ersatz |
| `SecretProvider` | Austauschbare lokale Grenze, die geheimes Material außerhalb normaler Persistenz, Logs und Reports hält und FolioTone ausschließlich opake versionierte Secret Handles bereitstellt. | Passwortspalte, Klartextpasswort im ToolResult |
| `Knowledge Provider` | Externe strukturierte Wissensquelle wie MusicBrainz, Open Library, GND oder Wikidata. | ToolProvider, wenn keine Toolausführung erfolgt |
| `ClassificationAssertion` | Provenance-behaftete Zuordnung einer Klassifikationsdimension zu einem Wert. | GenreField als alleinige Klassifikation |
| `Review Queue` | Menge unsicherer oder entscheidungsbedürftiger Fälle für menschliche Prüfung. | ManualFixList |
| `ConsolidationPlan` | Nicht ausführbarer Plan einer möglichen späteren Konsolidierung. | DeletePlan, CleanupScript |
| `Library Health` | Zusammengefasste Bewertung des Sammlungszustands anhand mehrerer unabhängiger Analysebereiche. | Quality Score, wenn nur eine einzelne Dimension gemeint ist |

## Wichtige Abgrenzungen

`Work` und `Edition` sind unterschiedliche Identitätsebenen. Zwei Dateien können dasselbe `Work`, aber unterschiedliche `Edition`-Entitäten repräsentieren.

`MusicWork`, `Recording`, `ReleaseGroup`, `Release` und `FileRecord` sind ebenfalls unterschiedliche Ebenen. Ein identisches `MusicWork` bedeutet nicht automatisch dieselbe Aufnahme oder Veröffentlichung.

`Entity Resolution` und `Matching` sind getrennte Aufgaben. Die Frage, ob „Asimov, I.“ dieselbe Person wie „Isaac Asimov“ bezeichnet, ist eine Entity-Resolution-Frage. Die Frage, ob zwei EPUB-Dateien dieselbe Edition repräsentieren, gehört zum Matching.

Ein `FileRelocationCandidate` ist ebenfalls kein Matching-Ergebnis und keine bestätigte File-Identität. Auch identische vollständige Datei-Hashes können zwei getrennte Kopien beschreiben.

`Evidence` beschreibt nachvollziehbare Unterstützung für eine Aussage. Eine einzelne Evidenzquelle darf insbesondere bei destruktiven Folgeschritten nicht als alleiniger Beweis behandelt werden.

## Pflege

Ein neuer kanonischer Fachbegriff wird nur eingeführt, wenn er ein tatsächlich neues Konzept bezeichnet oder eine bestehende Bezeichnung fachlich ersetzt. Vertragsänderungen werden nicht als rein redaktionelle Glossaränderungen durchgeführt.
