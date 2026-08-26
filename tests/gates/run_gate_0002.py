"""Run the pure GATE-0002 A/A and replay checks on two calibre outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from foliotone.ebook_transform import (
    CanonicalEpubProfile,
    MetadataDisposition,
    MetadataProvenance,
    TransformMetadataField,
    TransformMetadataSnapshot,
    canonicalize_epub3,
    inspect_epub3,
    verify_canonical_epub3,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-a", required=True, type=Path)
    parser.add_argument("--raw-b", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    snapshot = _load_snapshot(args.snapshot)
    profile = _load_profile(args.profile)
    source = args.source.read_bytes()
    raw_a = args.raw_a.read_bytes()
    raw_b = args.raw_b.read_bytes()
    if raw_a == raw_b:
        raise ValueError("fresh calibre outputs unexpectedly have identical raw bytes")
    _verify_source_preservation(source, raw_a, snapshot, profile)
    _verify_source_preservation(source, raw_b, snapshot, profile)
    result_a = canonicalize_epub3(raw_a, snapshot, profile)
    result_b = canonicalize_epub3(raw_b, snapshot, profile)
    if result_a.epub_bytes != result_b.epub_bytes:
        raise ValueError("canonical A/A outputs differ")
    replay = verify_canonical_epub3(result_a.epub_bytes, snapshot, profile)
    if replay.epub_bytes != result_a.epub_bytes:
        raise ValueError("canonical replay differs")
    _verify_source_preservation(source, result_a.epub_bytes, snapshot, profile)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "canonical-a.epub").write_bytes(result_a.epub_bytes)
    (args.output_dir / "canonical-b.epub").write_bytes(result_b.epub_bytes)
    (args.output_dir / "canonical-replay.epub").write_bytes(replay.epub_bytes)
    print(
        json.dumps(
            {
                "canonical_sha256": result_a.sha256,
                "canonical_size_bytes": result_a.size_bytes,
                "member_count": len(result_a.members),
                "package_document_sha256": result_a.package_document_sha256,
                "profile_sha256": result_a.profile_sha256,
                "replay_sha256": replay.sha256,
                "snapshot_sha256": result_a.snapshot_sha256,
                "source_sha256": inspect_epub3(source, profile).source_sha256,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _verify_source_preservation(
    source: bytes,
    candidate: bytes,
    snapshot: TransformMetadataSnapshot,
    profile: CanonicalEpubProfile,
) -> None:
    source_inspection = inspect_epub3(source, profile)
    candidate_inspection = inspect_epub3(candidate, profile)
    if candidate_inspection.metadata_by_key != snapshot.values_by_key:
        raise ValueError("candidate metadata differs from complete snapshot")
    for field in snapshot.fields:
        source_values = source_inspection.metadata_by_key[field.key]
        if field.disposition is MetadataDisposition.PRESERVE and source_values != field.values:
            raise ValueError("preserved source metadata differs from snapshot")
        if field.disposition is MetadataDisposition.OBSERVED_ABSENT and source_values:
            raise ValueError("observed-absent metadata exists in source")
    if source_inspection.package_member_name != candidate_inspection.package_member_name:
        raise ValueError("package member changed")
    if (
        source_inspection.package_structure_sha256
        != candidate_inspection.package_structure_sha256
    ):
        raise ValueError("package structure changed")
    source_members = {item.name: item.content_sha256 for item in source_inspection.members}
    candidate_members = {
        item.name: item.content_sha256 for item in candidate_inspection.members
    }
    if set(source_members) != set(candidate_members):
        raise ValueError("archive member inventory changed")
    package_name = source_inspection.package_member_name
    if any(
        source_hash != candidate_members[name]
        for name, source_hash in source_members.items()
        if name != package_name
    ):
        raise ValueError("preserved source payload changed")


def _load_snapshot(path: Path) -> TransformMetadataSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TransformMetadataSnapshot(
        fields=tuple(
            TransformMetadataField(
                key=item["key"],
                values=tuple(item["values"]),
                provenance=MetadataProvenance(item["provenance"]),
                disposition=MetadataDisposition(item["disposition"]),
                review_reference=item["review_reference"],
            )
            for item in payload["fields"]
        ),
        technical_modified_utc=payload["technical_modified_utc"],
        technical_delta_allowlist=tuple(payload["technical_delta_allowlist"]),
        profile=payload["profile"],
    )


def _load_profile(path: Path) -> CanonicalEpubProfile:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    payload["zip_datetime"] = tuple(payload["zip_datetime"])
    return CanonicalEpubProfile(**payload)


if __name__ == "__main__":
    raise SystemExit(main())
