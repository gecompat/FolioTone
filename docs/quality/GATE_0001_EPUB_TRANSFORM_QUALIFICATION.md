# GATE-0001: Qualifikation des EPUB-Transformationsprofils

- Status: `DONE`
- Ergebnis: `FAIL_EXACT_REPRODUCIBILITY`
- Datum: 2026-08-25
- Artefakt: `GATE-0001`
- geprüfter Kandidat: calibre 9.13.0, `ebook-polish --opf`

## Zweck und Grenze

Das Gate prüfte ausschließlich ein festes EPUB-3-zu-EPUB-3-Profil mit dem
synthetischen `ebook-transform-gate-input/v1`. Es öffnete keine
W10-Capability, veränderte keine Source Media und implementierte keinen
Writer. Ein einziger Unterschied bei vollständiger Bytelänge oder SHA-256
reicht gemäß `DEC-0002` für ein negatives Ergebnis.

Die Generatorquelle und das erwartete Eingangsmanifest liegen unter
`tests/fixtures/ebook_transform/gate-0001/`. Erzeugte EPUBs, vollständige
Toollogs und rohe EPUBCheck-Berichte bleiben außerhalb von Git in einem
aufgabenspezifischen lokalen Tempverzeichnis.

## Festes Charakterisierungsprofil

Das lokal gebaute gelockte Image hatte die unveränderliche Image-ID
`sha256:392fe0e6f3316b1dbc988fef55cb6a6c34137436ae62275e43f5d0a9e29270c7`.
Es enthielt calibre 9.13.0 und EPUBCheck 5.3.0. Der Transformationsprozess
erhielt ausschließlich diese Argumente:

```text
/opt/calibre/ebook-polish
--opf /input/reviewed-metadata.opf
/input/source.epub
/work/output.epub
```

Beide Läufe verwendeten ein frisches Outputverzeichnis, read-only Rootfs und
Input, `--pull=never`, `--network=none`, `--cap-drop=ALL`,
`no-new-privileges`, 512 MiB RAM, eine CPU, 256 PIDs, 256 offene Dateien und
ein 128-MiB-`tmpfs`. Fest gesetzt waren `TZ=UTC`, `LC_ALL=C.UTF-8`,
`LANG=C.UTF-8`, `HOME`, `TMPDIR`, `CALIBRE_CONFIG_DIRECTORY`,
`CALIBRE_ALLOW_PYTHON_TEMPLATES=0`, `QT_QPA_PLATFORM=offscreen`,
`PYTHONHASHSEED=0` und `SOURCE_DATE_EPOCH=1787652000`. Weder Shell noch freie
Tooloptionen oder geerbte Hostkonfiguration waren Teil des Profils.

## Empirischer Nachweis

Der feste Input hatte SHA-256
`adfb26f4a3548821485e8a1da1bfdbc60b8485d349eb971cbc347974d07edd28`
bei 2.699 Bytes. Die reviewte OPF-Projektion hatte SHA-256
`56efe6165190163bd5ac548b30820f028420eac6d43297e5e699806393e97c3a`
bei 788 Bytes. Sie enthielt neben dem geänderten Titel ausdrücklich auch die
reviewten Contributor- und Serienwerte. Zwischen den zwei frischen
Containerläufen lagen mehr als drei Sekunden.

| Lauf | Output-Bytes | vollständiger SHA-256 | EPUBCheck 5.3.0 |
|---|---:|---|---|
| A | 1.860 | `3ed15c4e60fa5a9de358954c2e483c11a7ee3670e702763aacdf71caa98c1843` | 0 Fatal, 0 Error, 0 Warning |
| B | 1.861 | `f653e477d6ab5688573e51716b308efc9b9f8194029805dbaef588524a9f7e5b` | 0 Fatal, 0 Error, 0 Warning |

Die Quelle blieb bytegleich. Die Outputs hatten weder dieselbe Länge noch
denselben vollständigen SHA-256. Kapitel, Navigation, Cover, Containerdatei
und ihre Zeitstempel waren in beiden Outputs jeweils bytegleich. Die
OPF-Inhalte unterschieden sich beim von calibre neu gesetzten
`dcterms:modified`; auch die ZIP-Zeitstempel von `mimetype` und OPF folgten der
realen Laufzeit. Die vollständig projizierten Serienwerte blieben in beiden
Outputs als `belongs-to-collection`, `collection-type=series` und
`group-position=1` erhalten.

calibre kann damit Serien verwalten. `ebook-polish --opf` ist jedoch keine
partielle Patch-Schnittstelle: Der Quellstand wendet die eingelesene
Metadatenprojektion mit `apply_null=True` an, sodass ausgelassene Werte wie
eine nicht projizierte Serie gelöscht würden. Das korrigierte Gate verwendet
deshalb einen vollständigen Snapshot. Es scheitert ausschließlich an der
harten Byte-Reproduzierbarkeit; EPUBCheck-Konformität ändert dieses Ergebnis
nicht.

## Offizielle Tool-, Security- und Lizenzprüfung

calibre 9.13.0 ist ein aktuell gepflegter, signierter Release. Die offizielle
CLI-Dokumentation beschreibt die Aktualisierung aus einer OPF-Datei mit
getrenntem Output. Der Quellstand 9.13.0 belegt zusätzlich die
`apply_null=True`-Semantik und bestätigt die beobachteten Ursachen: EPUB-3-
Commits setzen `dcterms:modified` aus der aktuellen UTC-Zeit, das Repacking
garantiert keine kanonische Sortierung und ZIP-Einträge übernehmen Dateizeiten
und Hostattribute.

Die neuere Advisory `GHSA-4f7g-rjfp-hmvx` betrifft calibre bis einschließlich
9.11.0 und ist ab 9.12.0 behoben. Deshalb wurde die gemeinsame
FolioTone-Sicherheitsuntergrenze in dieser Wave von 9.10.0 auf 9.12.0 erhöht;
das geprüfte 9.13.0 liegt darüber. Die Containergrenzen bleiben trotzdem
erforderlich, weil die Sperre für Python-Templates bei älteren Versionen
umgangen werden konnte.

calibre steht unter GPL-3.0 und enthält weitere komponentenspezifische
Lizenzhinweise. Dieses Gate bewertete ausschließlich lokalen Build und lokale
Ausführung. Es autorisiert keine Veröffentlichung eines vorgebauten Images;
dafür bleiben Corresponding Source, Notices, SBOM und komponentenspezifische
Pflichten getrennt zu prüfen. EPUBCheck 5.3.0 bleibt der unabhängige
Strukturvalidator, belegt aber weder Byte-Reproduzierbarkeit noch
Metadatenerhalt.

Primärquellen:

- https://calibre-ebook.com/whats-new
- https://github.com/kovidgoyal/calibre/releases/tag/v9.13.0
- https://manual.calibre-ebook.com/generated/en/ebook-polish.html
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/oeb/polish/main.py#L141-L149
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/oeb/polish/container.py#L1274-L1301
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/metadata/opf3.py#L604-L618
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/tweak.py#L62-L76
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/utils/zipfile.py#L1190-L1210
- https://github.com/kovidgoyal/calibre/security/advisories/GHSA-4f7g-rjfp-hmvx
- https://github.com/kovidgoyal/calibre/security/advisories/GHSA-2j4m-2q7x-2c47
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/LICENSE
- https://github.com/kovidgoyal/calibre/blob/v9.13.0/COPYRIGHT
- https://www.w3.org/publishing/epubcheck/releases/

## Ergebnis und offene Entscheidung

`GATE-0001` ist abgeschlossen, aber negativ. `DEC-0002` bleibt `Proposed`,
`WI-0004` bleibt `BLOCKED`, und es existiert weiterhin keine allgemeine
EPUB-Transformationsoperation. Wegen des harten Frühabbruchs wurden die
umfangreiche Malicious-Fixture- und Ressourcenrandmatrix sowie eine positive
Publish-Sandbox nicht als bestanden behauptet; sie sind erst gegen einen
neuen Kandidaten sinnvoll.

Vor weiterer Implementierung ist innerhalb von `DEC-0002` eine der folgenden
Richtungen ausdrücklich zu entscheiden und anschließend in einem neuen Gate
zu qualifizieren:

1. calibre nur als Transformationsstufe verwenden und danach eine
   FolioTone-eigene kanonische OPF-Normalisierung und EPUB-Verpackung anwenden;
2. die reviewten OPF-Werte mit einem neuen begrenzten FolioTone-Writer patchen
   und das gesamte EPUB anschließend kanonisch verpacken;
3. einen anderen dokumentierten ToolProvider bewerten.

Keine dieser Alternativen ist durch `GATE-0001` vorab ausgewählt oder
autorisiert.
