# Öffentliche 7-Zip-26.02-Format-Fixtures

Dieser Ordner enthält ausschließlich kleine öffentliche oder synthetische
Fixtures für `archive-7zip-format-measurement/v1`. Er enthält keine Daten aus
einer Sammlung. `expected-measurement.json` ist eine beobachtete, wertfreie
Messung mit dem gelockten Linux-Image, kein akzeptierter Formatlock und kein
Produktionsparservertrag.

## Synthetische Fixtures

Generatorprofil: `archive-7zip-format-fixture-generator/v1`.

Der öffentliche Payload `payload.txt` hat SHA-256
`d2faf79a1bfbcf71cc687beeffd81e83959b751ed2f5d580f51bd3f126c80589`
und den festen Änderungszeitpunkt `2026-06-25T00:00:00Z`. ZIP, 7z und TAR
wurden zweimal mit dem exakt gelockten 7zzs-26.02-Linux-Image erzeugt:

```text
7zzs a -tzip zip.zip payload.txt
7zzs a -t7z seven-z.7z payload.txt
7zzs a -ttar tar.tar payload.txt
```

Beide Läufe waren byteidentisch. gzip, bzip2 und xz wurden aus den
hashgebundenen TAR-Bytes mit Python 3.12 und ausschließlich der Standardbibliothek
erzeugt: `gzip.compress(..., compresslevel=9, mtime=0)`,
`bz2.compress(..., compresslevel=9)` und
`lzma.compress(..., format=lzma.FORMAT_XZ, preset=9)`.

Das gelockte 7zzs kann zstd lesen, aber nicht schreiben. Das zstd-Fixture ist
deshalb ein deterministischer Single-Segment-Frame mit genau einem
unkomprimierten letzten Block gemäß RFC 8878. Sein Inhalt sind exakt dieselben
hashgebundenen TAR-Bytes. Zwei unabhängige Erzeugungen waren byteidentisch und
das gelockte 7zzs hat den Frame erfolgreich als äußeren Stream gelesen.

Die exakten Fixture-SHA-256 stehen in `fixture-manifest.json`; der Messhelper
akzeptiert keine abweichenden Bytes oder Pfade.

## RAR-Fixtures und Lizenz

Die beiden RAR-Dateien und die drei Begleittexte stammen als unveränderte
Git-Blobs aus `ssokolow/rar-test-files`, Commit
`16b785c2b1b504e99fc307676e5369a26d3ce060`:

- `build/testfile.rar3.rar`, Git-Blob
  `2a88586fe4bbfc269de6a20dcd05503d21731369`;
- `build/testfile.rar5.rar`, Git-Blob
  `c6bfec6dfa535e73e3a5cb45db2f466c27dfaf70`;
- `LICENSE.cc0`, Git-Blob `6ca207ef004cb69d03041e7e5c288a2be4968045`;
- `LICENSE.md`, Git-Blob `80f0f70e4906710cf39035fbc1f23598c50b0c54`;
- `README.md`, Git-Blob `d8a765f557655e57dd69baf0b5ada2dade4c5781`.

Quelle: https://github.com/ssokolow/rar-test-files. Die eingecheckten
Upstream-Texte dokumentieren die rechtmäßige Erzeugung und Redistribution der
nicht selbstextrahierenden Testarchive sowie CC0 für die selbst geschaffenen
Inhalte. `.gitattributes` verhindert jede Zeilenendungsänderung an diesen
hashgebundenen Rohblobs.
