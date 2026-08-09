# ADR-0014: Konservative Move-/Rename-Kandidaten statt impliziter File-Identität

- Status: Accepted
- Datum: 2026-08-09

## Kontext

Ein Pfad ist keine dauerhafte Dateiidentität. Wenn in einem erfolgreichen Scan ein bisher bekannter Pfad erstmals fehlt und gleichzeitig ein neuer Pfad erscheint, kann dies durch Verschieben oder Umbenennen entstanden sein. Dieselbe Beobachtung kann jedoch auch durch Kopieren, Duplizieren, Wiederherstellen oder andere Dateisystemvorgänge entstehen.

FolioTone darf deshalb aus einem identischen Hash nicht unmittelbar ableiten, dass zwei `FileRecord`-Datensätze dieselbe physische Datei darstellen. Die W2-Erkennung muss Kandidaten erzeugen, ohne die spätere Matching- oder Review-Entscheidung vorwegzunehmen und ohne Source Media zu verändern.

## Entscheidung

W2 persistiert mögliche Pfadverlagerungen als `FileRelocationCandidate`. Ein Kandidat verbindet zwei weiterhin getrennte `FileRecord`-Identitäten:

- `source_file_id` bezeichnet den bisher bekannten, in diesem Scan erstmals `MISSING` gewordenen Datensatz;
- `target_file_id` bezeichnet einen im selben Scan als `NEW` beobachteten Datensatz;
- Source und Target behalten ihre normalen Scan-Zustände. Es findet kein Merge und keine Identitätsumschreibung statt.

Die Kandidatensuche ist auf denselben `ScanRoot` und denselben erfolgreichen Scan beschränkt. Als Source werden nur Datensätze verwendet, deren aktuelle Abwesenheitsserie mit diesem Scan beginnt (`consecutive_missing_scans == 1`). Ältere `MISSING`-Datensätze werden nicht nachträglich mit später auftauchenden Dateien verbunden.

## Fingerprint Blocking

Kandidaten werden nicht durch globales all-vs-all erzeugt. Source und Target müssen einen bereits persistierten, versionierten File-Fingerprint teilen. W2 berücksichtigt zunächst:

- `FILE_SHA256`;
- `QUICK_FILE`.

Der Kandidat speichert die IDs der beiden konkreten `Fingerprint`-Datensätze sowie Fingerprint-Art, Algorithmus und Algorithmusversion. Der Hashwert selbst muss deshalb nicht redundant in den Kandidaten kopiert werden.

Wenn für dasselbe Source/Target-Paar sowohl `FILE_SHA256` als auch `QUICK_FILE` übereinstimmen, wird `FILE_SHA256` als stärkere technische Evidence gespeichert. Auch ein identischer vollständiger SHA-256 beweist jedoch nur identischen Dateiinhalt und nicht, ob die Datei verschoben oder kopiert wurde.

## Mehrdeutigkeit

Ein Fingerprint-Block erzeugt nur dann einen `FileRelocationCandidate`, wenn er im aktuellen Source-/Target-Scope genau eine Source und genau ein Target enthält. One-to-many-, many-to-one- und many-to-many-Konstellationen werden nicht automatisch aufgelöst.

Diese Einschränkung schützt insbesondere Sammlungen mit echten identischen Duplikaten davor, dass eine beliebige Kopie als vermeintliche Pfadverlagerung ausgewählt wird. Mehrdeutige Fälle können später durch zusätzliche Evidence oder das Matching-/Review-System behandelt werden.

## Kandidatenart

Die Pfadform wird getrennt von der Identitätsfrage klassifiziert:

- `RENAMED`: Parent-Pfad gleich, Dateiname verschieden;
- `MOVED`: Dateiname gleich, Parent-Pfad verschieden;
- `MOVED_AND_RENAMED`: Parent-Pfad und Dateiname verschieden.

Diese Werte beschreiben nur die Form des beobachteten Pfadwechsels innerhalb eines Kandidaten. Sie bestätigen nicht, dass tatsächlich ein Dateisystem-Move oder Rename ausgeführt wurde.

## Konsequenzen

- `NEW` und `MISSING` bleiben die auditierbaren `FileScanEvent`-Zustände der beiden getrennten `FileRecord`-Datensätze.
- `FileRelocationCandidate` ist zusätzliche Evidence und kein `Relation`- oder Matching-Ergebnis.
- Dateien ohne geeignete persistierte Fingerprints erzeugen keinen Relocation-Kandidaten.
- Mehrdeutige identische Dateien erzeugen keinen automatisch ausgewählten Kandidaten.
- Die Erkennung bleibt inkrementell und hash-blocked statt collection-weitem all-vs-all.
- W0 bis W9 erhalten weiterhin keine Source-Media-Move-/Rename-/Delete-Funktion.
