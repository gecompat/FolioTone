# ADR-0044: Reale Formatprofile vor dem Archive-Provider

**Status:** Akzeptiert

**Datum:** 2026-08-20

**Geltungsbereich:** S-EBAR-02B, FG-A-FORMAT-LOCK, S-EBAR-02C und EBAR-05

## Kontext

ADR-0043 führte den inkrementellen Member-only-Parser
`archive-7zip-slt-parser/v2` ein. Sein generisches Pflichtfeldset war bewusst
durch reale Golden-Fixtures aller freigegebenen Formatfamilien zu prüfen. Diese
Prüfung hat vor dem Merge von EBAR-05 erwartungsgemäß den Stop-Zustand
ausgelöst.

Eine kontrollierte Vorvermessung mit 7-Zip 26.02 unter Windows ergab für alle
neun vorgesehenen Familien `GRAMMAR_REJECTED`. Sie ist nur diagnostisch, weil
alle normativen Golden-Werte aus dem gelockten Linux-Image stammen müssen. Die
Abweichungen sind dennoch strukturell und nicht betriebssystemspezifisch
wegzuerklären:

| Familie | Beobachtete Abweichung vom Parser v2 |
|---|---|
| ZIP | zusätzliches leeres Memberfeld `Comment` |
| RAR4 | zusätzliche Felder wie `Commented` und Split-Marker |
| RAR5 | zusätzliche Felder; leere Linkfelder dürfen nicht als Link gelten |
| 7z | `Folder` fehlt bei einem regulären Member |
| TAR | `Encrypted` fehlt; weitere TAR-spezifische Felder sind vorhanden |
| gzip-TAR | Listing beschreibt zunächst den äußeren komprimierten Stream |
| bzip2-TAR | äußeres Stream-Listing ohne vollständige Memberfelder |
| xz-TAR | äußeres Stream-Listing ohne vollständige Memberfelder |
| zstd-TAR | äußeres Stream-Listing ohne vollständige Memberfelder |

Der Parser v2 ist damit weiterhin ein gültiger, begrenzter synthetischer
Vertrag, aber kein freigegebenes Produktionsprofil. Ein Provider darf ihn nicht
für reale 7-Zip-Ausgabe verwenden.

Diese ADR ersetzt ausschließlich die Aussagen aus ADR-0043, wonach Parser v2
bereits das reale generische Produktionsprofil bildet und EBAR-05 alle neun
Familien unmittelbar als Membercontainer abnimmt. Statusvorrang, Exitcode-,
stderr-, Cancellation-, Privacy- und Raw-Discard-Regeln aus ADR-0043 bleiben
unverändert. Die Format-Allowlist aus ADR-0038 bleibt ebenfalls erhalten; ihre
Familien werden lediglich in sichere Auswertungsphasen getrennt.

RAR kann mit dem freigegebenen 7-Zip-Binary nicht erzeugt werden. Eigene
RAR-Writer oder nachgebaute proprietäre Kompression sind ausgeschlossen. Für
die Vermessung werden deshalb zwei kleine, ausdrücklich als rechtmäßig
redistribuierbar veröffentlichte Fixtures aus `ssokolow/rar-test-files`
verwendet. Quelle ist Commit
`16b785c2b1b504e99fc307676e5369a26d3ce060`. Der Legacy-Name `rar3` bezeichnet
hier die von RAR 3.93 erzeugte Familie mit der vor RAR 5 verwendeten
RAR-4.x-Signatur; er wird im Formatlock nicht still mit RAR 5 vermischt:

- Legacy-RAR `build/testfile.rar3.rar`, 98 Byte,
  SHA-256 `dce342bc0c2852fcaa36a03da5e55abb7dd69c045bbd812faebebc1a3844f5a4`;
- RAR5 `build/testfile.rar5.rar`, 82 Byte,
  SHA-256 `a546b39c1aa42669543ef81f5ec8c4ef49fc7c2e5b8d08ab10549e919996e1a4`.

Der Upstream erklärt die Fixtures als mit einer lizenzierten RAR-Version
erzeugt, rechtmäßig redistribuierbar und gibt die selbst geschaffenen Inhalte
unter CC0 frei. S-EBAR-02B bindet und reproduziert deshalb zusätzlich
`LICENSE.cc0` mit SHA-256
`7179683e8000e6bdc9bbc60d85edf0a4ac8e76f951857f54fcb775d5886f1309`,
`LICENSE.md` mit SHA-256
`64d97b29bc28614947511c5cf1872962a274945903ef2984acdbf455e281ceb1`
und `README.md` mit SHA-256
`9dd19d40540bbcfce35ca76001e44eeaf003ed66bebe02006841096929e9dd89`.
Jede Abweichung oder fehlende Redistribution-Aussage stoppt das Paket.

Alle weiteren Fixtures des v1-Korpus enthalten entweder ausschließlich einen
fest definierten synthetischen Payload und werden deterministisch erzeugt oder
stammen aus einer separat hash- und lizenzgebundenen redistribuierbaren Quelle.
Dies gilt insbesondere, falls das gelockte Binary einen Wrapper wie zstd nicht
erzeugen kann. Kein Fixture stammt aus einer privaten Sammlung; eine neue
externe Fixturequelle ist ohne dokumentierte Redistribution und Sol-Review
unzulässig. Für die intrinsisch randomisierten verschlüsselten ZIP-/7z-Zellen
des additiven v2-Korpus gilt ausschließlich die enge Ausnahme aus ADR-0045.

## Entscheidung

### 1. Dreistufiges Gate vor EBAR-05

EBAR-05 bleibt gestoppt, bis diese Reihenfolge abgeschlossen ist:

1. `S-EBAR-02B` legt den minimalen Fixturekorpus, Quellen, Lizenzen, SHA-256,
   Generatorprofile und einen nicht überspringbaren Messjob für das exakt
   gelockte Linux-Image an. Der Job erzeugt ausschließlich das unten
   geschlossene normalisierte Messmanifest; niemals Locatorwerte oder
   Raw-stdout/stderr.
2. `FG-A-FORMAT-LOCK` prüft den beobachteten Manifest-Diff und akzeptiert die
   exakten formatgebundenen Pflicht-, optionalen, leeren und verworfenen Felder.
   Es entscheidet außerdem die äußeren Streamprofile für gzip, bzip2, xz und
   zstd. Ohne dieses Review wird kein Produktionsparser erweitert.
3. `S-EBAR-02C` implementiert die akzeptierten Profile additiv. Parser v1 und
   v2 bleiben lesbar, werden aber nicht als reale Providerprofile ausgegeben.

Erst danach wird EBAR-05 fortgesetzt.

### 2. Direkte Container und komprimierte Streams bleiben getrennt

ZIP, RAR4, RAR5, 7z und TAR sind direkte Containerfamilien. Ein
formatgebundener Parser darf Pflichtfelder nur anhand bereits bestätigter
Signatur-/Format-Evidence auswählen. Freies Erraten aus Dateiendung, Pfad,
stdout oder stderr ist verboten.

gzip, bzip2, xz und zstd sind in diesem Vertrag äußere komprimierte Streams.
Bis EBAR-06 führt EBAR-05 für sie keinen produktiven 7-Zip-Listing- oder
Integrity-Lauf aus. Bestätigte Wrapper-Signatur ergibt exakt
`OUTER_COMPRESSION_ONLY`, Listing `NOT_ATTEMPTED` ohne Execution-ID, Integrity
`NOT_TESTED` ohne Execution-ID, Encryption `UNKNOWN`, keine
`ArchiveMemberObservation` und eine blockierte Extraction Policy.

Ein erfolgreiches äußeres Listing wäre noch kein TAR-Memberlisting. Eine
zweistufige Auswertung benötigt eine private, begrenzte Dekompression, erneute
Signaturprüfung des inneren Objekts und danach dessen formatgebundenes Listing.
Diese Schreib- und Workspacegrenze gehört zu EBAR-06. Für diese Phase ersetzt
ADR-0044 die Aussage aus ADR-0038, wonach bereits das unmittelbare Listing den
inneren TAR-Container bestätigt; die Format-Allowlist selbst bleibt erhalten.

### 3. Leere technische Felder und private Werte

Die bloße Anwesenheit eines optionalen Feldnamens beweist keinen Zustand.
Insbesondere bedeuten leere `Symbolic Link`-/`Hard Link`-Werte keinen Link.
Feldwerte mit potenziell privaten Locators, Kommentaren, Benutzer-/Gruppennamen
oder Linkzielen werden während des inkrementellen Parsens sofort verworfen.
Nur ein akzeptiertes Formatprofil darf aus exakt definierter Leer-/Nichtleer-
oder Bool-Grammatik einen festen technischen Status ableiten.

Unbekannte Felder, unbekannte Kombinationen und jede Abweichung vom gelockten
Manifest bleiben fail-closed. Ein neues 7-Zip-, Parser- oder Formatprofil macht
die entsprechende abgeleitete Evidence stale.

### 4. Geschlossenes Messmanifest und Formatlock

Das kanonische Messmanifest hat das Profil
`archive-7zip-format-measurement/v1` und genau diese Materialklassen:

- gelockter Image-Manifest-Digest, Toolversion und Command-Profil/-Digest;
- Fixture-ID, öffentliche Fixture-SHA-256 und bereits bestätigte
  Signatur-/Formatfamilie;
- Exitcode, Recordrolle (`DIRECT_MEMBER` oder `OUTER_STREAM`) und kanonischer
  Recordordinal;
- je Record die beobachtete Feldreihenfolge aus Feldname und genau einem festen
  Value-Class-Literal.

Die v1-Value-Class-Literale sind `EMPTY`, `BOOL_PLUS`, `BOOL_MINUS`,
`CANONICAL_UINT`, `CRC32`, `TIMESTAMP`, `PRIVATE_LOCATOR_DISCARDED`,
`PRIVATE_NONEMPTY_DISCARDED` und `TECHNICAL_NONEMPTY_DISCARDED`. Ein Wert, ein
Locator, Rawoutput oder dessen Digest darf nie im Manifest, Artefakt, Log oder
PR erscheinen. SHA-256 ist ausschließlich über öffentliche Fixturebytes,
Image-/Command-Identitäten und die kanonischen normalisierten Manifestbytes
zulässig.

Eine einzelne Happy-Fixture macht kein Feld optional. Jede spätere Pflicht-,
Optional-, Leer- oder Discard-Regel benötigt beobachtete Recordabdeckung oder
exakt gepinnte 7-Zip-26.02-Source-Evidence. Nicht belegte Regeln bleiben
unaccepted und fail-closed.

FG-A-FORMAT-LOCK schreibt danach ein separates reviewtes
`archive-7zip-format-lock/v1` mit eigenem kanonischen SHA-256 fest. Der
geschützte Workflow verifiziert diesen Lock nur; er darf Acceptance weder neu
erzeugen noch bei abweichender Ausgabe aktualisieren. S-EBAR-02C konsumiert
exakt diesen Lock.

### 5. Golden-Gate und Skip-Regel

Lokale Tests dürfen auf nicht unterstützten Hosts deterministisch skippen. Der
PR ist jedoch erst mergefähig, wenn genau ein geschützter Linux-Gate-Lauf alle
Fixturefamilien mit dem gelockten Image-Digest ausgeführt und das geschlossene
Messmanifest bestätigt hat. Ein ausschließlich übersprungener PR ist rot.

Der Messjob hat kein Netzwerk, keinen Pull-Fallback und keinen Zugriff auf
private ScanRoots. RAR-Fixtures und Lizenztext liegen eingecheckt und
hashgebunden vor. Im v1-Korpus werden alle anderen Archive aus dem
eingecheckten synthetischen Payload oder aus ebenfalls hashgebundenen,
redistribuierbaren Fixtures erzeugt. Der v2-Messjob regeneriert die in
ADR-0045 eng begrenzten verschlüsselten ZIP-/7z-Fixtures ausdrücklich nicht.

## Folgen

- Der aktuelle EBAR-05-Draft wird nicht gemergt und nach S-EBAR-02C gegen das
  neue Profil überarbeitet.
- Parser v2 wird nicht still gelockert. Reale Formatunterschiede bleiben
  sichtbar und versioniert.
- Komprimierte TAR-Wrapper werden nicht fälschlich als direkt gelistete
  Container behandelt.
- Das zusätzliche Gate kostet einen kleinen PR, verhindert aber fehlerhafte
  Member-, Link-, Safety- und Provenienz-Evidence in allen späteren Wellen.
