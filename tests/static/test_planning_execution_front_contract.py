from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNING = ROOT / "docs/planning"
BACKLOG = PLANNING / "BACKLOG.md"
STATUS = PLANNING / "PROJECT_STATUS.md"
HANDOVER = PLANNING / "HANDOVER.md"
IMPLEMENTATION = PLANNING / "IMPLEMENTATION_PLAN.md"
FUTURE_MAP = PLANNING / "FUTURE_CAPABILITY_MAP.md"
WRITE_PIPELINE = PLANNING / "EBOOK_WRITE_PIPELINE_PLAN.md"
SAFETY = ROOT / "docs/architecture/SAFETY.md"
ADR = ROOT / "docs/decisions/ADR-0058-book-collection-state-and-local-projections.md"
WRITE_AUTHORIZATION_ADR = ROOT / "docs/decisions/ADR-0061-controlled-ebook-write-development.md"
METADATA_CORRECTION_ADR = (
    ROOT / "docs/decisions/ADR-0062-non-executable-metadata-correction-plans.md"
)
METADATA_WRITE_ADR = (
    ROOT / "docs/decisions/ADR-0063-bounded-epub-title-source-metadata-writer.md"
)
METADATA_WRITE_OPERATOR_ADR = (
    ROOT / "docs/decisions/ADR-0064-metadata-write-operator-and-reconciliation.md"
)
OPERATION_RECIPE_ADR = (
    ROOT / "docs/decisions/ADR-0065-non-executable-ebook-operation-recipes.md"
)
EBOOK_RENAME_ADR = (
    ROOT / "docs/decisions/ADR-0066-bounded-ebook-file-rename.md"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backlog_has_one_canonical_next_product_slice() -> None:
    backlog = _text(BACKLOG)

    assert backlog.count("| CS-01 | DONE |") == 1
    assert backlog.count("| CS-02 | DONE |") == 1
    assert backlog.count("| CS-03 | DONE |") == 1
    assert "| NOW | `FUT-011` (`DECISION`) |" in backlog
    assert "| NEXT WAVES | keine freigegebene Implementierungswave |" in backlog
    assert "| W9-006 | DONE |" in backlog
    assert "| FG-W9-006 | DONE |" in backlog
    assert "| S-W9-006A | DONE |" in backlog
    assert "| S-W9-006B | DONE |" in backlog
    assert "| S-W9-006C | DONE |" in backlog
    assert "| W9-007 | DONE |" in backlog
    assert "| FG-W9-007 | DONE |" in backlog
    assert "| S-W9-007A | DONE |" in backlog
    assert "| S-W9-007B | DONE |" in backlog
    assert "| S-W9-007C | DONE |" in backlog
    assert "| FG-W10-RENAME | DONE |" in backlog
    assert "| S-W10-RN01 | DONE |" in backlog
    assert "| S-W10-RN02 | DONE |" in backlog
    assert "| S-W10-RN03 | DONE |" in backlog
    assert "| S-W10-RN04 | DONE |" in backlog
    assert "| FUT-011 | DECISION |" in backlog
    assert "| FG-W10-REORGANIZE | DECISION |" in backlog
    assert "| W10-005 | DONE |" in backlog
    assert "| W10-006 | DONE |" in backlog
    assert "| S-W10-MW05 | DONE |" in backlog
    assert "| OPS-001 | READY |" in backlog
    assert "Andere Planungsdokumente erläutern diese Aufgaben" in backlog


def test_book_completion_is_not_hidden_in_planned_cross_domain_rows() -> None:
    backlog = _text(BACKLOG)

    for item in range(1, 7):
        assert f"| W6-00{item} | DONE |" in backlog
    for item in range(1, 4):
        assert f"| W8-00{item} | DONE |" in backlog
    assert "| W5A-004 | DONE |" in backlog
    assert "| W5A-006 | PLANNED |" in backlog
    assert "| W6-008 | PLANNED |" in backlog
    assert "| W7-002 | DONE |" in backlog
    assert "| W7-004 | PLANNED |" in backlog


def test_collection_state_contract_is_discoverable_and_privacy_bounded() -> None:
    adr = _text(ADR)
    documentation_index = _text(ROOT / "docs/README.md")

    required = (
        "- Status: Accepted",
        "collection-state/v1",
        "collection-state-diff/v1",
        "collection-query/v1",
        "library-health/v1",
        "--private-details",
        "keinen Gesamtscore",
        "keine Source Media",
        "Music W4",
    )
    assert all(marker in adr for marker in required)
    assert "ADR-0058" in documentation_index


def test_current_planning_sources_agree_on_delivery_front() -> None:
    for path in (STATUS, HANDOVER, IMPLEMENTATION, FUTURE_MAP):
        content = _text(path)
        assert "CS-01" in content, path
        assert "CS-02" in content, path
        assert "CS-03" in content, path
        assert "W9-007" in content, path
        assert "ADR-0066" in content, path
        assert "S-W10-RN01" in content, path
        assert "S-W10-RN02" in content, path
        assert "S-W10-RN03" in content, path


def test_current_status_does_not_reintroduce_superseded_w10_claims() -> None:
    status = _text(STATUS)
    handover = _text(HANDOVER)
    stale_claims = (
        "S-W10-02 folgt",
        "jede reale W10-Ausführung einschließlich Quarantäne",
        "W10 bleibt bis zu einer späteren expliziten ADR blockiert",
        "Die aktive Archive-Welle",
    )

    for claim in stale_claims:
        assert claim not in status
        assert claim not in handover
    assert "nicht atomar" in status
    assert "FG-W10-MOVE-BACKEND" in status
    assert "Capability-Auflösung" in handover


def test_ebook_write_pipeline_is_development_authorized_and_remains_gate_bound() -> None:
    plan = _text(WRITE_PIPELINE)
    documentation_index = _text(ROOT / "docs/README.md")
    backlog = _text(BACKLOG)
    authorization_adr = _text(WRITE_AUTHORIZATION_ADR)

    required = (
        "Read-only erfassen",
        "MetadataCorrectionPlan",
        "FG-W10-METADATA-WRITE",
        "FG-W10-SIDECAR-WRITE",
        "FG-W10-EXTERNAL-LIBRARY-WRITE",
        "FG-W10-RENAME",
        "FG-W10-ARCHIVE-REWRITE",
        "REST-API und grafische Oberfläche",
        "Anfangs ist nur `E-Books` aktiv",
        "kontrollierte Entwicklung",
        "Reale Mutation bleibt an",
    )
    assert all(marker in plan for marker in required)
    assert "EBOOK_WRITE_PIPELINE_PLAN.md" in documentation_index
    assert "ADR-0061" in documentation_index
    assert "| W9-006 | DONE |" in backlog
    assert "| W9-007 | DONE |" in backlog
    assert "| FG-W10-WRITE-DEVELOPMENT | DONE |" in backlog
    assert "| FG-W10-METADATA-WRITE | DONE |" in backlog
    assert "| FG-W10-RENAME | DONE |" in backlog
    assert "| S-W10-RN01 | DONE |" in backlog
    assert "| S-W10-RN02 | DONE |" in backlog
    assert "| S-W10-RN03 | DONE |" in backlog
    assert "| S-W10-RN04 | DONE |" in backlog
    for gate in (
        "FG-W10-SIDECAR-WRITE",
        "FG-W10-EXTERNAL-LIBRARY-WRITE",
        "FG-W10-ARCHIVE-REWRITE",
    ):
        assert f"| {gate} | DECISION |" in backlog

    required_adr_markers = (
        "- Status: Accepted",
        "synthetischen",
        "kein globaler Runtime-Schalter",
        "keine gemeinsame `write-all`-Capability",
        "W9-006",
        "W10-005",
        "FG-W10-METADATA-WRITE",
        "nur die E-Book-Linie",
    )
    assert all(marker in authorization_adr for marker in required_adr_markers)


def test_metadata_correction_gate_is_reviewed_bounded_and_non_executable() -> None:
    adr = _text(METADATA_CORRECTION_ADR)
    documentation_index = _text(ROOT / "docs/README.md")
    backlog = _text(BACKLOG)

    required = (
        "- Status: Accepted",
        "metadata-correction-candidate/v1",
        "metadata-correction-plan/v1",
        "MetadataCorrectionCandidate",
        "ReviewType.METADATA_CORRECTION",
        "ReviewCandidateKind.METADATA_CORRECTION_CANDIDATE",
        "FOLIOTONE_PROJECTION",
        "SOURCE_METADATA",
        "CALIBRE_LIBRARY",
        "FULL_SHA256_MATCHES",
        "metadata-correction-verification/v1",
        "NOT_EXECUTABLE",
        "S-W9-006A",
        "S-W9-006B",
        "S-W9-006C",
    )
    assert all(marker in adr for marker in required)
    assert "ADR-0062" in documentation_index
    assert "| FG-W9-006 | DONE |" in backlog


def test_operation_recipe_gate_is_typed_private_and_non_executable() -> None:
    adr = _text(OPERATION_RECIPE_ADR)
    documentation_index = _text(ROOT / "docs/README.md")
    backlog = _text(BACKLOG)

    required = (
        "- Status: Accepted",
        "ebook-operation-recipe-candidate/v1",
        "ebook-operation-recipe-plan/v1",
        "EbookOperationRecipeCandidate",
        "EbookOperationRecipePlan",
        "FILE_RENAME",
        "FILE_REORGANIZE",
        "FILE_IMPORT",
        "FILE_EXPORT",
        "FORMAT_TRANSFORM",
        "ARCHIVE_REWRITE",
        "ReviewType.EBOOK_OPERATION_RECIPE",
        "ReviewCandidateKind.EBOOK_OPERATION_RECIPE_CANDIDATE",
        "NOT_EXECUTABLE",
        "S-W9-007A",
        "S-W9-007B",
        "S-W9-007C",
    )
    assert all(marker in adr for marker in required)
    assert "ADR-0065" in documentation_index
    assert "| FG-W9-007 | DONE |" in backlog


def test_first_ebook_file_rename_gate_is_narrow_recoverable_and_reconciled() -> None:
    adr = _text(EBOOK_RENAME_ADR)
    documentation_index = _text(ROOT / "docs/README.md")
    backlog = _text(BACKLOG)
    safety = _text(SAFETY)

    required = (
        "- Status: Accepted",
        "ebook-file-rename-linux-renameat2-noreplace/v1",
        "ebook-file-rename-dependency-scope/v1",
        "FILE_RENAME",
        "FG-W10-REORGANIZE",
        "FOLIOTONE_EBOOK_RENAME_CAPABILITIES_FILE",
        "FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE",
        "RENAME_NOREPLACE",
        "RESOLVE_BENEATH",
        "RESOLVE_NO_SYMLINKS",
        "RESOLVE_NO_MAGICLINKS",
        "RESOLVE_NO_XDEV",
        "KNOWN_NONE",
        "NOT_APPLICABLE",
        "LOCATOR_NOT_NFC",
        "CONFIRM EBOOK RENAME",
        "EBOOK_RENAME_PREPARATION",
        "EBOOK_RENAME_RUN",
        "0031_ebook_rename_operations",
        "0032_ebook_rename_reconciliation",
        "MANUAL_RECOVERY_REQUIRED",
        "EbookRenameReconciliationSnapshot",
        "S-W10-RN01",
        "S-W10-RN02",
        "S-W10-RN03",
        "S-W10-RN04",
        "keine gemeinsame `write-all`-Capability",
        "Kein Test benötigt reale E-Books",
    )
    assert all(marker in adr for marker in required)
    assert "ADR-0066" in documentation_index
    assert "| FG-W10-RENAME | DONE |" in backlog
    assert "| S-W10-RN01 | DONE |" in backlog
    assert "| S-W10-RN02 | DONE |" in backlog
    assert "| S-W10-RN03 | DONE |" in backlog
    assert "| FG-W10-REORGANIZE | DECISION |" in backlog
    assert all(
        marker in safety
        for marker in (
            "ADR-0066",
            "renameat2(RENAME_NOREPLACE)",
            "MANUAL_RECOVERY_REQUIRED",
            "FG-W10-REORGANIZE",
        )
    )


def test_first_source_metadata_writer_gate_is_narrow_and_reconciled() -> None:
    adr = _text(METADATA_WRITE_ADR)
    operator_adr = _text(METADATA_WRITE_OPERATOR_ADR)
    documentation_index = _text(ROOT / "docs/README.md")
    backlog = _text(BACKLOG)

    required = (
        "- Status: Accepted",
        "ebook-source-metadata-write/epub3-title-replace/v1",
        "target_carrier = SOURCE_METADATA",
        "genau eine Feldkorrektur `title`",
        "dcterms:modified",
        "ebook-meta-opf/2",
        "RENAME_EXCHANGE",
        "RENAME_NOREPLACE",
        "MANUAL_RECOVERY_REQUIRED",
        "S-W10-MW01",
        "S-W10-MW02",
        "S-W10-MW05",
        "operativ nicht",
        "Reale private E-Books",
    )
    assert all(marker in adr for marker in required)
    assert "ADR-0063" in documentation_index
    assert "ADR-0064" in documentation_index
    assert all(
        marker in operator_adr
        for marker in (
            "- Status: Accepted",
            "metadata-write-authorize",
            "metadata-write-execute",
            "metadata-write-recover",
            "CONFIRM METADATA WRITE",
            "metadata-write-reconciliation/v1",
            "0029_metadata_write_reconciliation",
            "VERIFIED",
            "RECOVERED",
        )
    )
    assert "| FG-W10-METADATA-WRITE | DONE |" in backlog
    assert "| S-W10-MW01 | DONE |" in backlog
    assert "| S-W10-MW02 | DONE |" in backlog
    assert "| S-W10-MW03 | DONE |" in backlog
    assert "| S-W10-MW04 | DONE |" in backlog
    assert "| S-W10-MW05 | DONE |" in backlog
    assert "| W10-006 | DONE |" in backlog
