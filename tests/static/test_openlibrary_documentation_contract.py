"""Static closure checks for the bounded Open Library provider contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/reference/EXTERNAL_DATA_SOURCES.md"
STATUS = ROOT / "docs/planning/PROJECT_STATUS.md"
BACKLOG = ROOT / "docs/planning/BACKLOG.md"
ADR = ROOT / "docs/decisions/ADR-0036-open-library-first-book-provider.md"


def test_openlibrary_registry_records_current_bounded_provider_policy() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    required = (
        "Stand der Open-Library-Bewertung: 2026-08-20",
        "keine Cover-, Availability-, Lending- oder Archive.org-Inhalte",
        "nur private normalisierte Minimal-DTOs",
        "maximal 180 Tagen Retention",
        "Ab mehr als 100 geplanten\nLookups je Lauf oder mehr als 1.000",
        "separater `LOCAL_DATASETS`-Import",
        "Rohantworten, reale Response-Fixtures",
    )
    for phrase in required:
        assert phrase in text


def test_openlibrary_registry_does_not_present_cover_data_as_provider_scope() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    purpose = text.split("### Open Library", 1)[1].split("Access strategy:", 1)[0]
    assert "cover references where useful" not in purpose
    assert "keine Cover-, Availability-, Lending- oder Archive.org-Inhalte" in purpose


def test_openlibrary_status_and_backlog_are_synchronized() -> None:
    status = STATUS.read_text(encoding="utf-8")
    backlog = BACKLOG.read_text(encoding="utf-8")
    assert "EB-03B DONE" in status
    assert "S-EB03B-01 bis S-EB03B-08 abgeschlossen" in status
    assert "| W5B-007 | DONE |" in backlog
    assert "| W5B-008 | DONE |" in backlog
    assert "| W5B-007 | NEXT |" not in backlog


def test_openlibrary_adr_keeps_bulk_and_privacy_boundaries_explicit() -> None:
    text = ADR.read_text(encoding="utf-8")
    for phrase in (
        "BULK_DATASET_REQUIRED",
        "Mehr als 100 geplante Open-Library-Lookups",
        "mehr als 1.000 ungelösten Records",
        "absolute oder relative lokale Pfade",
        "Rohantworten",
        "Archive.org",
        "Cover",
        "Availability",
        "nicht freigegeben",
    ):
        assert phrase in text
