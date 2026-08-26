# Synthetische Fixture fuer GATE-0002

Diese Quelle definiert das vollstaendige, rein synthetische Profil
`ebook-transform-gate-0002-input/v1`. Der Generator schreibt Eingangs-EPUB,
vollstaendigen reviewten OPF-Snapshot und abgeleitete Testausgaben nur in ein
pytest-Tempverzeichnis oder nach `C:\rep\tmp\FolioToneDev1\gate-0002`.
Erzeugte EPUBs, Toollogs und EPUBCheck-Berichte werden nicht eingecheckt.

Die Werte enthalten keine privaten Medien, Pfade oder Sammlungsmetadaten. Das
Profil ist ausschliesslich ein Qualifikationskandidat. Es erteilt keine Writer-,
Publish- oder W10-Autorisierung und oeffnet weder Source Media noch eine
Calibre-Bibliothek.

Vor jedem calibre-Aufruf muss dieselbe bounded Byte-Pruefung laufen, die auch
den untrusted Zwischenoutput erneut prueft. Insbesondere erreichen
`calibre:user_metadata`-Payloads, Links, Traversal, ZIP64, Encryption und
Ressourcenbomben den externen Prozess nicht.
