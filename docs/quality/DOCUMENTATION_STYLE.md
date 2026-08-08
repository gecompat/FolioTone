# Verbindlicher Schreibstil für Dokumentation

**Status:** verbindlich  
**Geltungsbereich:** alle neuen oder fachlich überarbeiteten Dokumentationsfreitexte in FolioTone

## Ziel

Die Dokumentation beschreibt technische und fachliche Zusammenhänge sachlich, präzise und nachvollziehbar. Sie ist so knapp wie möglich und so ausführlich wie für ein eindeutiges Verständnis erforderlich.

Ein Dokument erläutert den Zweck, die Funktionsweise, die wesentlichen Voraussetzungen, relevante Abhängigkeiten, Auswirkungen und bekannte Aussagegrenzen, soweit diese Aspekte für den beschriebenen Gegenstand relevant sind.

## Formulierung

Freitexte verwenden vollständige, grammatikalisch korrekte Sätze und logisch zusammenhängende Absätze. Technische Begriffe, Modellnamen, Statuswerte, Schnittstellen und Konfigurationswerte werden innerhalb des Repositorys konsistent verwendet.

Aussagen werden konkret formuliert. Unbestimmte Verweise wie „dies“, „normalerweise“, „problematisch“ oder „besser“ erhalten den notwendigen fachlichen Bezug, wenn er nicht aus dem unmittelbar vorhergehenden Kontext eindeutig hervorgeht.

Bei Analyse- und Matching-Verfahren werden die für die Aussage relevanten Bedingungen genannt. Dazu können Datenquelle, Provenance, Tool- oder Provider-Version, Scope, Zeitpunkt, Confidence, Heuristik, Sicherheitsgrenze und mögliche Gegenprüfung gehören.

## Zu vermeidende Ausdrucksformen

Die Dokumentation enthält keine:

- werblichen oder unbelegten Qualitätsversprechen;
- rhetorischen Ausschmückungen, Metaphern oder Floskeln ohne technischen Nutzen;
- subjektiven Wertungen ohne fachliche Begründung;
- Satzfragmente oder unverbundene Stichwortsammlungen, wenn dadurch Bedeutung verloren geht;
- erfundenen Fakten, Quellen, Kausalitäten, Abhängigkeiten oder Ausführungsergebnissen;
- scheinbar präzisen Aussagen, wenn die zugrunde liegende Information nur eine Annahme oder Heuristik ist.

Begriffe wie „einfach“, „offensichtlich“, „optimal“, „immer“, „nie“, „vollständig“ oder „zukunftssicher“ werden nur verwendet, wenn sie im beschriebenen Scope tatsächlich fachlich belegt sind.

## Tatsachen, Heuristiken und Empfehlungen

Dokumentierte Tatsachen, empirische Beobachtungen, Heuristiken, Annahmen, Empfehlungen und offene Fragen werden sprachlich getrennt.

Eine Empfehlung nennt die fachliche Begründung und die wesentlichen Auswirkungen. Eine Unsicherheit wird ausdrücklich benannt. Ein fehlender Laufzeitnachweis oder eine nicht geprüfte externe Aussage darf nicht durch eine Vermutung ersetzt werden.

Für FolioTone sind insbesondere folgende Kennzeichnungen zulässig und empfohlen, wenn eine Verwechslung sonst möglich wäre:

- **Dokumentiert:** durch einen Vertrag, eine Primärquelle oder Repositoryinhalt belegt;
- **Empirisch:** durch einen tatsächlich ausgeführten Test oder eine Messung beobachtet;
- **Heuristik:** bewusst probabilistische oder regelbasierte Ableitung;
- **Annahme:** derzeit vorausgesetzte, noch nicht belegte Aussage;
- **Empfehlung:** begründete vorgeschlagene Vorgehensweise;
- **Ungeklärt:** offene fachliche oder technische Frage.

## Listen und Tabellen

Listen und Tabellen sind sinnvoll, wenn sie Aufzählungen, Abläufe, Zuordnungen oder Vergleiche klarer darstellen als Fließtext. Überschriften und Spaltenbezeichnungen müssen die dargestellte Beziehung eindeutig benennen.

Listen und Tabellen ersetzen erklärenden Text nicht, wenn Zweck, Ursache, Abhängigkeit oder Interpretation sonst unklar bleibt.

## Erhaltung technischer Verträge

Eine redaktionelle Überarbeitung darf die fachliche Bedeutung eines bestehenden Vertrags nicht verändern. Dies gilt insbesondere für:

- Klassen-, Modell- und Feldnamen;
- Enum- und Statuswerte;
- CLI-Kommandos und Optionen;
- Konfigurationsschlüssel und Environment Variables;
- Datenbank- und Migrationsverträge;
- `RelationType`, `ToolCapability`, `ValueState` und andere öffentliche Literale;
- Provider-, Tool- und Adapter-IDs;
- Fingerprint- und Algorithmusbezeichnungen;
- Sicherheits-, Datenschutz- und W10-Grenzen;
- dokumentierte Read-only- oder Write-Verbote.

Wenn eine sprachliche Überarbeitung einen möglichen fachlichen Widerspruch sichtbar macht, wird der Widerspruch geprüft oder als offene Unsicherheit dokumentiert. Er wird nicht stillschweigend durch eine Umformulierung entschieden.

## Geschützter Lizenzblock der Root-README

Der englische und deutsche Lizenzblock am Anfang der Root-Datei `README.md` ist von allgemeinen Dokumentations-, Formatierungs- und Stiländerungen ausgenommen.

Vor jeder Bearbeitung der Root-README ist der im Zielbranch vorhandene Lizenzblock zu lesen. Wortlaut, Reihenfolge, Links, Überschriften, Listen, Hervorhebungen, Trennlinien, Zeichensetzung und Leerzeilen dieses Blocks bleiben unverändert, sofern der Benutzer nicht ausdrücklich die Änderung des Lizenzblocks beauftragt.

Die maßgebliche Lizenz ist `LICENSE.md`. Deren englische Fassung ist entsprechend dem Lizenztext die rechtlich bindende Master-Version.

## Änderungsumfang

Eine technische Änderung berechtigt nicht zu einer unverbundenen Gesamtüberarbeitung der Dokumentation. Stilkorrekturen bleiben grundsätzlich auf die sachlich betroffenen Dokumente und Abschnitte begrenzt.

Bestehende englische Dokumente werden nicht allein aufgrund der Sprachrichtlinie massenhaft übersetzt. Bei einer fachlichen Überarbeitung gelten die Regeln in `LANGUAGE_AND_TERMINOLOGY.md`.

## Prüfkriterien vor einem Commit

Vor dem Commit ist für jeden berührten Dokumentationsfreitext zu prüfen:

1. Ist der Zweck ohne inhaltsarme Einleitung erkennbar?
2. Sind Funktionsweise und wesentliche Abhängigkeiten ausreichend erklärt?
3. Sind technische Begriffe und Vertragswerte korrekt und konsistent?
4. Sind Tatsachen, Heuristiken, Annahmen, Empfehlungen und Unsicherheiten sauber getrennt?
5. Enthalten Listen und Tabellen ausreichend Kontext?
6. Wurden Floskeln, Übertreibungen, Wiederholungen und unbelegte Wertungen vermieden?
7. Bleibt der Text so knapp wie möglich, ohne erforderliche fachliche Erklärung auszulassen?
8. Wurden keine Fakten, Quellen oder Nachweise erfunden?
9. Wurde der geschützte README-Lizenzblock unverändert erhalten?
