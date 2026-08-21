"""Focused contracts for bounded archive collection execution."""

from dataclasses import replace
from pathlib import Path

import pytest

from foliotone.archive.process_runner import CancellationProbe
from foliotone.archive.sevenzip_slt import ArchiveSevenZipFormatCase
from foliotone.archive.signatures import observe_archive_signature_v2
from foliotone.core import ArchiveCollectionItem, ArchiveCollectionItemSource, EntityId
from foliotone.persistence.archive_collection import (
    ArchiveCollectionWorkItem,
    _ArchiveCollectionResolvedSource,
)
from foliotone.workflows.archive_collection import (
    ArchiveCollectionExecutionError,
    _compatibility,
    _hash_source,
    _revalidate_material,
    execute_archive_collection_invocation,
)


class _Cancellation:
    def __init__(self, value: bool = False) -> None:
        self.value = value

    def is_set(self) -> bool:
        return self.value


def _work_item(payload: bytes) -> tuple[ArchiveCollectionWorkItem, str]:
    import hashlib

    run_id = EntityId.parse("00000000-0000-0000-0000-000000000901")
    item_id = EntityId.parse("00000000-0000-0000-0000-000000000902")
    observation_id = EntityId.parse("00000000-0000-0000-0000-000000000903")
    digest = hashlib.sha256(payload).hexdigest()
    item = ArchiveCollectionItem(
        item_id,
        run_id,
        observation_id,
        0,
        observe_archive_signature_v2("synthetic.zip", payload),
    )
    source = ArchiveCollectionItemSource(
        run_id, item_id, 0, observation_id, digest, len(payload), "archive"
    )
    return ArchiveCollectionWorkItem(item, (source,)), digest


def test_revalidation_binds_hash_signature_and_private_locator(tmp_path: Path) -> None:
    payload = b"PK\x03\x04data"
    source = tmp_path / "synthetic.zip"
    source.write_bytes(payload)
    work_item, digest = _work_item(payload)
    resolved = (
        _ArchiveCollectionResolvedSource(work_item.sources[0], "synthetic.zip"),
    )

    material = _revalidate_material(
        resolved, work_item, tmp_path, _Cancellation()
    )

    assert material.reuse_key.archive_full_sha256 == digest
    assert material.signature == work_item.item.signature
    assert "synthetic.zip" not in repr(material)


def test_revalidation_rejects_hash_or_signature_drift(tmp_path: Path) -> None:
    payload = b"PK\x03\x04data"
    source = tmp_path / "synthetic.zip"
    source.write_bytes(payload)
    work_item, _ = _work_item(payload)
    resolved = (
        _ArchiveCollectionResolvedSource(
            replace(work_item.sources[0], full_sha256="a" * 64),
            "synthetic.zip",
        ),
    )
    with pytest.raises(ArchiveCollectionExecutionError, match="revalidation"):
        _revalidate_material(resolved, work_item, tmp_path, _Cancellation())


def test_hash_source_honours_cancellation_and_size_bound(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    with pytest.raises(RuntimeError):
        _hash_source(source, 7, _Cancellation(True))
    with pytest.raises(ArchiveCollectionExecutionError, match="revalidation"):
        _hash_source(source, 8, _Cancellation())


@pytest.mark.parametrize("case", tuple(ArchiveSevenZipFormatCase))
def test_direct_reuse_compatibility_is_exact(case: ArchiveSevenZipFormatCase) -> None:
    signature = observe_archive_signature_v2("synthetic.zip", b"PK\x03\x04")
    compatibility = _compatibility(signature, case)
    assert compatibility.signature is signature
    assert compatibility.format_case_kind == case.value
    assert compatibility.wrapper_image_reference is None


def test_wrapper_reuse_compatibility_binds_all_command_identities() -> None:
    signature = observe_archive_signature_v2("synthetic.tar.gz", b"\x1f\x8b")
    compatibility = _compatibility(
        signature, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR
    )
    assert compatibility.provider_profile == "archive-7zip-wrapper-provider/v1"
    assert compatibility.wrapper_image_reference is not None
    assert compatibility.wrapper_command_identity is not None
    assert compatibility.listing_command_identity is not None
    assert compatibility.integrity_command_identity is not None


def test_public_executor_rejects_injected_authority(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collection store"):
        execute_archive_collection_invocation(  # type: ignore[arg-type]
            object(),
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            EntityId.new(),
            "opaque-token",
            tmp_path,
            max_items=1,
            now=lambda: pytest.fail("must not execute"),
        )


def test_cancellation_probe_contract_is_structural() -> None:
    probe: CancellationProbe = _Cancellation()
    assert not probe.is_set()
