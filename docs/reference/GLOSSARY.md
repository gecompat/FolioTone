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
| `EbookMetadataCandidate` | Provider-neutraler E-Book-Feldkandidat, der als `ToolResult` an die exakte `ToolExecution` und `FileObservation` gebunden wird. Gruppierte Feldpfade erhalten Zusammenhänge etwa zwischen Identifier-Namespace/-Wert, Contributor-Feldern oder Series-Name/-Position. | BookMetadata als kanonische Wahrheit |
| `ToolArtifact` | Persistiertes Runtime-Artefakt einer `ToolExecution`, beispielsweise stdout, stderr oder ein Report. | LogFile als allgemeiner Ersatz |
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
