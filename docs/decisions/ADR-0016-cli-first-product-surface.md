# ADR-0016: CLI als anfängliche Produktoberfläche

- Status: Accepted
- Datum: 2026-08-14

## Kontext

FolioTone benötigt zunächst belastbare End-to-End-Vertical-Slices für Indexierung, Tool-Orchestrierung, E-Book- und Musikanalyse, Entity Resolution, Matching und Review. Eine parallele Web-API, Desktop-Oberfläche oder Dashboard-Schicht würde zusätzliche öffentliche Verträge, Zustandsmodelle, Security-Flächen und Wartungsaufwand einführen, bevor die fachlichen Workflows stabil sind.

Der Benutzer hat die anfängliche Produktoberfläche ausdrücklich auf die CLI begrenzt. Das langfristige `Library Health`-Dashboard bleibt eine mögliche Erweiterung, ist aber kein Bestandteil der aktiven W3-Planung.

## Entscheidung

FolioTone wird zunächst ausschließlich über die CLI bedient.

- Die CLI bleibt ein dünner Adapter zu Anwendungs- und Core-Verträgen.
- Domain-Logik importiert keine CLI-Implementierung.
- W3 und die folgenden frühen Vertical Slices ergänzen CLI-Kommandos nur für read-only Analyse- und Review-nahe Workflows innerhalb der jeweils aktiven Sicherheitsgrenze.
- Eine Web-API, Desktop-Oberfläche oder ein Dashboard wird nicht nebenläufig als zweite Produktoberfläche aufgebaut.
- Ein späterer UI- oder Service-Scope verwendet dieselben Anwendungs- und Core-Verträge und benötigt eine ausdrückliche neue Scope- oder Architekturentscheidung.

Diese Entscheidung verändert weder den analysis-only Produktmodus noch die W10-Sicherheitsgrenze.

## Konsequenzen

- Die ersten E-Book- und Musik-Vertical-Slices können sich auf fachliche Verträge, ToolProvider-Evidence, Persistenz und reproduzierbare CLI-Ausführung konzentrieren.
- CLI-Ausgaben benötigen klare Fehler- und Exit-Code-Semantik; maschinenlesbare Ausgabeformate werden pro Workflow eingeführt, wenn ein konkreter Automationsbedarf besteht.
- Es entsteht vorerst kein HTTP-Server, kein Browser-Frontend und keine Desktop-GUI-Abhängigkeit.
- `Library Health` bleibt als spätere Produktoberfläche möglich, ohne die aktuelle Komponenten- und Dependency-Richtung zu ändern.
