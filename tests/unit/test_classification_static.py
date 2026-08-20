"""Static safety boundary for the classification-only CLI summary."""

from pathlib import Path


def test_classification_report_source_contains_no_identity_or_mutation_authority() -> None:
    root = Path(__file__).parents[2] / "src" / "foliotone"
    cli = (root / "cli" / "main.py").read_text(encoding="utf-8")
    start = cli.index("def _run_ebook_classification_report")
    end = cli.index("def _run_ebook_inventory_report", start)
    sources = (
        cli[start:end],
        (root / "workflows" / "classification.py").read_text(encoding="utf-8"),
        (root / "classification" / "projection.py").read_text(encoding="utf-8"),
    )
    function = "\n".join(sources).lower()
    for forbidden in (
        "relationcandidate",
        "identitydecision",
        "confirm_identity",
        "write_metadata",
        "quarantine",
        "rename",
        "unlink",
        "os.remove",
    ):
        assert forbidden not in function
