from pathlib import Path

import pytest

from foliotone.application import (
    APPLICATION_CONTRACTS_PROFILE,
    ApplicationCommand,
    ApplicationContext,
    ApplicationError,
    EbookFixityPrivateBaselineEntryPage,
    EbookFixityPrivateBaselineEntryPageQuery,
    EbookFixityPrivateResultDetail,
    EbookFixityPrivateResultDetailQuery,
    EbookToolchainReadinessQuery,
    FolioToneApplication,
    LibraryHealthQuery,
    MediaLine,
    MediaLineDescriptor,
    MediaLineRegistry,
)
from foliotone.core import EntityId


def test_default_registry_activates_only_ebooks() -> None:
    registry = MediaLineRegistry.default()

    assert registry.profile == APPLICATION_CONTRACTS_PROFILE
    assert registry.entries == (
        MediaLineDescriptor(MediaLine.EBOOK, True),
        MediaLineDescriptor(MediaLine.MUSIC, False),
        MediaLineDescriptor(MediaLine.IMAGE, False),
    )


def test_base_command_and_query_keep_the_versioned_ebook_context() -> None:
    assert ApplicationCommand().context == ApplicationContext()
    assert LibraryHealthQuery(EntityId.new()).context == ApplicationContext()


def test_registry_rejects_missing_or_early_media_line_activation() -> None:
    with pytest.raises(ApplicationError, match="incomplete"):
        MediaLineRegistry(
            APPLICATION_CONTRACTS_PROFILE,
            (MediaLineDescriptor(MediaLine.EBOOK, True),),
        )

    with pytest.raises(ApplicationError, match="activation"):
        MediaLineRegistry(
            APPLICATION_CONTRACTS_PROFILE,
            (
                MediaLineDescriptor(MediaLine.EBOOK, True),
                MediaLineDescriptor(MediaLine.MUSIC, True),
                MediaLineDescriptor(MediaLine.IMAGE, False),
            ),
        )


def test_application_passes_the_doctor_query_to_the_adapter() -> None:
    captured: dict[str, object] = {}

    def inspector(**kwargs: object) -> object:
        captured.update(kwargs)
        return "synthetic-report"

    application = FolioToneApplication(
        media_lines=MediaLineRegistry.default(),
        toolchain_inspector=inspector,  # type: ignore[arg-type]
    )
    query = EbookToolchainReadinessQuery(
        ebook_meta_executable="ebook-meta",
        ebook_convert_executable="ebook-convert",
        calibre_debug_executable="calibre-debug",
        pdfinfo_executable="pdfinfo",
        pdftotext_executable="pdftotext",
        java_executable="java",
        epubcheck_jar=Path("epubcheck.jar"),
    )

    assert application.ebook_toolchain_readiness(query) == "synthetic-report"
    assert captured["epubcheck_jar"] == Path("epubcheck.jar")


def test_application_passes_the_health_query_to_the_persistence_port() -> None:
    snapshot_id = EntityId.new()
    baseline_id = EntityId.new()
    captured: dict[str, object] = {}

    class Reader:
        def read(self, snapshot_id: object, **kwargs: object) -> object:
            captured["snapshot_id"] = snapshot_id
            captured.update(kwargs)
            return "synthetic-health"

    application = FolioToneApplication(
        media_lines=MediaLineRegistry.default(),
        toolchain_inspector=lambda **_kwargs: None,  # type: ignore[arg-type]
    )

    assert (
        application.library_health_report(
            Reader(), LibraryHealthQuery(snapshot_id, baseline_id, sample_limit=3)
        )
        == "synthetic-health"
    )
    assert captured == {
        "snapshot_id": snapshot_id,
        "baseline_snapshot_id": baseline_id,
        "sample_limit": 3,
    }


def test_private_fixity_queries_cross_only_the_explicit_application_port() -> None:
    manifest_id = EntityId.new()
    result_id = EntityId.new()
    baseline_page = EbookFixityPrivateBaselineEntryPage(
        manifest_id=manifest_id,
        entries=(),
        next_after_ordinal=None,
    )
    captured: list[object] = []

    class Port:
        def private_fixity_baseline_entries(
            self, query: EbookFixityPrivateBaselineEntryPageQuery
        ) -> EbookFixityPrivateBaselineEntryPage:
            captured.append(query)
            return baseline_page

        def private_fixity_result_detail(
            self, query: EbookFixityPrivateResultDetailQuery
        ) -> EbookFixityPrivateResultDetail | None:
            captured.append(query)
            return None

    application = FolioToneApplication(
        media_lines=MediaLineRegistry.default(),
        toolchain_inspector=lambda **_kwargs: None,  # type: ignore[arg-type]
    )
    page_query = EbookFixityPrivateBaselineEntryPageQuery(
        manifest_id=manifest_id,
        after_ordinal=3,
        limit=4,
    )
    detail_query = EbookFixityPrivateResultDetailQuery(result_id=result_id)

    assert application.private_ebook_fixity_baseline_entries(Port(), page_query) is baseline_page  # type: ignore[arg-type]
    assert application.private_ebook_fixity_result_detail(Port(), detail_query) is None  # type: ignore[arg-type]
    assert captured == [page_query, detail_query]
