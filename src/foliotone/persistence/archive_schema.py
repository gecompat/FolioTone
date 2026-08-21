"""Immutable archive evidence schema from ADR-0052."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata


def _sha256(table: str, column: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_{table}_{column}_sha256",
    )


archive_observations = Table(
    "archive_observations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("observed_at", DATETIME, nullable=False),
    Column("archive_full_sha256", Text, nullable=False),
    Column("archive_content_fingerprint", Text, nullable=False),
    Column("volume_group_fingerprint", Text, nullable=False),
    Column("signature_profile", Text, nullable=False),
    Column("compatibility_profile", Text, nullable=False),
    Column("container_class", ENUM, nullable=False),
    Column("suffix_kind", ENUM, nullable=False),
    Column("publication_kind", ENUM, nullable=False),
    Column("storage_family", ENUM, nullable=False),
    Column("outer_compression_kind", ENUM, nullable=False),
    Column("recognition_status", ENUM, nullable=False),
    Column("inspected_bytes", Integer, nullable=False),
    Column("structural_confirmation_required", Boolean, nullable=False),
    Column("provider_profile", Text, nullable=False),
    Column("runner_profile", Text, nullable=False),
    Column("parser_profile", Text, nullable=False),
    Column("parser_status", ENUM),
    Column("format_case_kind", ENUM),
    Column("format_lock_profile", Text, nullable=False),
    Column("format_lock_sha256", Text, nullable=False),
    Column("listing_profile", Text, nullable=False),
    Column("integrity_profile", Text, nullable=False),
    Column("extraction_profile", Text, nullable=False),
    Column("safety_profile", Text, nullable=False),
    Column("secret_version", Text, nullable=False),
    Column("listing_status", ENUM, nullable=False),
    Column("encryption_status", ENUM, nullable=False),
    Column("integrity_status", ENUM, nullable=False),
    Column("extraction_status", ENUM, nullable=False),
    Column("password_attempt_status", ENUM, nullable=False),
    Column("extraction_policy_status", ENUM, nullable=False),
    Column("member_count", Integer, nullable=False),
    Column("writer_owner_kind", ENUM, nullable=False),
    Column("writer_owner_run_id", ID, nullable=False),
    Column("writer_fence_epoch", Integer, nullable=False),
    CheckConstraint("profile = 'archive-observation/v1'", name="ck_archive_observations_profile"),
    CheckConstraint(
        "signature_profile = 'archive-signature-observer/v2' "
        "AND compatibility_profile = 'archive-publication-storage-compatibility/v1' "
        "AND parser_profile = 'archive-7zip-slt-parser/v3' "
        "AND format_lock_profile = 'archive-7zip-format-lock/v1' "
        "AND listing_profile = 'archive-listing/v1' "
        "AND integrity_profile = 'archive-integrity/v1' "
        "AND extraction_profile = 'archive-extraction/v1' "
        "AND safety_profile = 'archive-safety-policy/v1' "
        "AND secret_version = 'NONE'",
        name="ck_archive_observations_v1_profiles",
    ),
    CheckConstraint(
        "format_lock_sha256 = "
        "'4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061'",
        name="ck_archive_observations_format_lock",
    ),
    CheckConstraint(
        "container_class IN ('PUBLICATION_CONTAINER','GENERIC_ARCHIVE',"
        "'UNSUPPORTED_CONTAINER','UNKNOWN_CONTAINER')",
        name="ck_archive_observations_container_class",
    ),
    CheckConstraint(
        "suffix_kind IN ('EPUB','CBZ','CBR','ZIP','RAR','SEVEN_Z','TAR',"
        "'TAR_GZIP','TAR_BZIP2','TAR_XZ','TAR_ZSTD','UNSUPPORTED','OTHER')",
        name="ck_archive_observations_suffix_kind",
    ),
    CheckConstraint(
        "publication_kind IN ('NONE','EPUB','CBZ','CBR')",
        name="ck_archive_observations_publication_kind",
    ),
    CheckConstraint(
        "storage_family IN ('ZIP','RAR4','RAR5','SEVEN_Z','TAR','UNKNOWN')",
        name="ck_archive_observations_storage_family",
    ),
    CheckConstraint(
        "outer_compression_kind IN ('NONE','GZIP','BZIP2','XZ','ZSTD')",
        name="ck_archive_observations_outer_compression",
    ),
    CheckConstraint(
        "recognition_status IN ('MATCHED','SIGNATURE_SUFFIX_MISMATCH',"
        "'OUTER_COMPRESSION_ONLY','UNSUPPORTED_FORMAT','UNKNOWN_SIGNATURE')",
        name="ck_archive_observations_recognition_status",
    ),
    CheckConstraint(
        "inspected_bytes BETWEEN 0 AND 512 "
        "AND structural_confirmation_required IN (0,1)",
        name="ck_archive_observations_signature_shape",
    ),
    CheckConstraint(
        "(listing_status = 'NOT_ATTEMPTED' AND parser_status IS NULL "
        "AND format_case_kind IS NULL) OR (listing_status <> 'NOT_ATTEMPTED' "
        "AND parser_status IN "
        "('PARSED','LIMIT_EXCEEDED','ENCODING_REJECTED','GRAMMAR_REJECTED') "
        "AND ((parser_status = 'PARSED' AND format_case_kind IS NOT NULL AND format_case_kind IN "
        "('PLAINTEXT_REGULAR','DIRECTORY','ALL_ENCRYPTED','MIXED','SYMBOLIC_LINK','HARD_LINK')) "
        "OR (parser_status <> 'PARSED' AND format_case_kind IS NULL)))",
        name="ck_archive_observations_parser_shape",
    ),
    CheckConstraint(
        "(provider_profile = 'archive-7zip-provider/v1' "
        "AND runner_profile = 'archive-linux-container-runner/v1' "
        "AND recognition_status <> 'OUTER_COMPRESSION_ONLY') OR "
        "(provider_profile = 'archive-7zip-wrapper-provider/v1' "
        "AND runner_profile = 'archive-wrapper-container-runner/v1' "
        "AND storage_family = 'UNKNOWN' "
        "AND outer_compression_kind IN ('GZIP','BZIP2','XZ','ZSTD') "
        "AND recognition_status = 'OUTER_COMPRESSION_ONLY')",
        name="ck_archive_observations_provider_shape",
    ),
    CheckConstraint(
        "listing_status IN ('NOT_ATTEMPTED','LISTED','PASSWORD_REQUIRED',"
        "'UNSUPPORTED_FORMAT','UNSUPPORTED_METHOD','MISSING_VOLUME','CORRUPT',"
        "'LIMIT_EXCEEDED','TIMED_OUT','TOOL_UNAVAILABLE','TOOL_FAILED','POLICY_REJECTED')",
        name="ck_archive_observations_listing_status",
    ),
    CheckConstraint(
        "encryption_status IN ('NONE','DATA_ENCRYPTED','HEADERS_ENCRYPTED','MIXED','UNKNOWN')",
        name="ck_archive_observations_encryption_status",
    ),
    CheckConstraint(
        "integrity_status IN ('NOT_TESTED','PASSED','PASSWORD_REQUIRED',"
        "'UNSUPPORTED_METHOD','CORRUPT','LIMIT_EXCEEDED','TIMED_OUT',"
        "'TOOL_UNAVAILABLE','TOOL_FAILED','POLICY_REJECTED')",
        name="ck_archive_observations_integrity_status",
    ),
    CheckConstraint(
        "extraction_status = 'NOT_ATTEMPTED'",
        name="ck_archive_observations_extraction_status",
    ),
    CheckConstraint(
        "password_attempt_status IN ('NOT_ATTEMPTED','SECURE_CHANNEL_UNAVAILABLE')",
        name="ck_archive_observations_password_status",
    ),
    CheckConstraint(
        "extraction_policy_status IN ('ACCEPTED','POLICY_REJECTED','LIMIT_EXCEEDED')",
        name="ck_archive_observations_policy_status",
    ),
    CheckConstraint(
        "member_count BETWEEN 0 AND 10000",
        name="ck_archive_observations_member_count",
    ),
    CheckConstraint(
        "writer_owner_kind IN "
        "('EBOOK_ANALYSIS','EBOOK_COLLECTION_RUN','ARCHIVE_COLLECTION_RUN') "
        "AND writer_fence_epoch > 0",
        name="ck_archive_observations_writer",
    ),
    CheckConstraint(
        "(listing_status = 'LISTED' AND encryption_status IN ('NONE','DATA_ENCRYPTED','MIXED')) "
        "OR (listing_status <> 'LISTED' AND member_count = 0 AND encryption_status = 'UNKNOWN' "
        "AND integrity_status = 'NOT_TESTED')",
        name="ck_archive_observations_listing_shape",
    ),
    CheckConstraint(
        "(listing_status <> 'LISTED') OR "
        "(encryption_status = 'NONE' AND password_attempt_status = 'NOT_ATTEMPTED' "
        "AND integrity_status <> 'NOT_TESTED') OR "
        "(encryption_status IN ('DATA_ENCRYPTED','MIXED') "
        "AND password_attempt_status = 'SECURE_CHANNEL_UNAVAILABLE' "
        "AND integrity_status = 'NOT_TESTED' AND extraction_policy_status <> 'ACCEPTED')",
        name="ck_archive_observations_listed_shape",
    ),
    _sha256("archive_observations", "content_hash"),
    _sha256("archive_observations", "archive_full_sha256"),
    _sha256("archive_observations", "archive_content_fingerprint"),
    _sha256("archive_observations", "volume_group_fingerprint"),
    _sha256("archive_observations", "format_lock_sha256"),
    UniqueConstraint("content_hash", name="uq_archive_observations_content_hash"),
)


archive_observation_sources = Table(
    "archive_observation_sources",
    metadata,
    Column(
        "archive_observation_id",
        ID,
        ForeignKey("archive_observations.id"),
        primary_key=True,
    ),
    Column("source_ordinal", Integer, primary_key=True),
    Column("file_observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("source_full_sha256", Text, nullable=False),
    Column("source_size_bytes", Integer, nullable=False),
    Column("staging_name", Text, nullable=False),
    CheckConstraint(
        "source_ordinal BETWEEN 0 AND 255",
        name="ck_archive_observation_sources_ordinal",
    ),
    CheckConstraint(
        "source_size_bytes >= 0",
        name="ck_archive_observation_sources_size",
    ),
    CheckConstraint(
        "length(staging_name) BETWEEN 7 AND 32 "
        "AND lower(substr(staging_name, 1, 7)) = 'archive' "
        "AND staging_name NOT GLOB '*[^A-Za-z0-9.]*'",
        name="ck_archive_observation_sources_staging_name",
    ),
    _sha256("archive_observation_sources", "source_full_sha256"),
    UniqueConstraint(
        "archive_observation_id",
        "file_observation_id",
        name="uq_archive_observation_sources_file",
    ),
    UniqueConstraint(
        "archive_observation_id",
        "staging_name",
        name="uq_archive_observation_sources_staging_name",
    ),
)


archive_observation_executions = Table(
    "archive_observation_executions",
    metadata,
    Column(
        "archive_observation_id",
        ID,
        ForeignKey("archive_observations.id"),
        primary_key=True,
    ),
    Column("execution_role", ENUM, primary_key=True),
    Column("tool_execution_id", ID, ForeignKey("tool_executions.id"), nullable=False),
    CheckConstraint(
        "execution_role IN ('LISTING','INTEGRITY','EXTRACTION')",
        name="ck_archive_observation_executions_role",
    ),
    UniqueConstraint(
        "archive_observation_id",
        "tool_execution_id",
        name="uq_archive_observation_executions_tool",
    ),
)


archive_member_observations = Table(
    "archive_member_observations",
    metadata,
    Column(
        "archive_observation_id",
        ID,
        ForeignKey("archive_observations.id"),
        primary_key=True,
    ),
    Column("member_ordinal", Integer, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("member_identity", Text, nullable=False),
    Column("member_path_safe", Text, nullable=False),
    Column("member_kind", ENUM, nullable=False),
    Column("declared_compressed_bytes", Integer),
    Column("declared_uncompressed_bytes", Integer),
    Column("observed_uncompressed_bytes", Integer),
    Column("member_sha256", Text),
    Column("crc_status", ENUM, nullable=False),
    Column("encryption_status", ENUM, nullable=False),
    Column("listing_profile", Text, nullable=False),
    Column("extraction_profile", Text, nullable=False),
    Column("safety_profile", Text, nullable=False),
    Column("secret_version", Text, nullable=False),
    CheckConstraint("member_ordinal BETWEEN 0 AND 9999", name="ck_archive_members_ordinal"),
    CheckConstraint(
        "profile = 'archive-member-observation/v1' "
        "AND listing_profile = 'archive-listing/v1' "
        "AND extraction_profile = 'archive-extraction/v1' "
        "AND safety_profile = 'archive-safety-policy/v1' "
        "AND secret_version = 'NONE'",
        name="ck_archive_members_profiles",
    ),
    CheckConstraint(
        "member_kind IN ('REGULAR_FILE','DIRECTORY','SYMLINK','HARDLINK',"
        "'REPARSE_POINT','FIFO','SOCKET','BLOCK_DEVICE','CHARACTER_DEVICE','UNKNOWN')",
        name="ck_archive_members_kind",
    ),
    CheckConstraint(
        "length(member_path_safe) BETWEEN 1 AND 1024 "
        "AND length(CAST(member_path_safe AS BLOB)) <= 4096",
        name="ck_archive_members_path_bound",
    ),
    CheckConstraint(
        "(declared_compressed_bytes IS NULL OR declared_compressed_bytes BETWEEN 0 AND 2147483648) "
        "AND (declared_uncompressed_bytes IS NULL "
        "OR declared_uncompressed_bytes BETWEEN 0 AND 2147483648) "
        "AND (observed_uncompressed_bytes IS NULL "
        "OR observed_uncompressed_bytes BETWEEN 0 AND 2147483648)",
        name="ck_archive_members_sizes",
    ),
    CheckConstraint(
        "crc_status IN ('NOT_AVAILABLE','NOT_TESTED','MATCHED','MISMATCHED')",
        name="ck_archive_members_crc_status",
    ),
    CheckConstraint(
        "encryption_status IN ('NONE','DATA_ENCRYPTED')",
        name="ck_archive_members_encryption_status",
    ),
    CheckConstraint(
        "observed_uncompressed_bytes IS NULL AND member_sha256 IS NULL",
        name="ck_archive_members_extraction_absent",
    ),
    _sha256("archive_member_observations", "member_identity"),
    CheckConstraint(
        "member_sha256 IS NULL OR "
        "(length(member_sha256) = 64 AND member_sha256 NOT GLOB '*[^0-9a-f]*')",
        name="ck_archive_members_optional_sha256",
    ),
    UniqueConstraint(
        "archive_observation_id",
        "member_identity",
        name="uq_archive_members_identity",
    ),
)


archive_wrapper_lineage = Table(
    "archive_wrapper_lineage",
    metadata,
    Column(
        "archive_observation_id",
        ID,
        ForeignKey("archive_observations.id"),
        primary_key=True,
    ),
    Column("profile", Text, nullable=False),
    Column("inner_storage_family", ENUM, nullable=False),
    Column("inner_stream_size_bytes", Integer),
    Column("inner_stream_sha256", Text),
    Column("frame_profile", Text, nullable=False),
    Column("wrapper_runner_profile", Text, nullable=False),
    Column("image_reference", Text, nullable=False),
    Column("wrapper_command_identity", Text, nullable=False),
    Column("listing_command_identity", Text, nullable=False),
    Column("integrity_command_identity", Text, nullable=False),
    CheckConstraint(
        "profile = 'archive-7zip-wrapper-provider/v1' "
        "AND inner_storage_family = 'TAR' "
        "AND frame_profile = 'archive-tar-stream-frame/v1' "
        "AND wrapper_runner_profile = 'archive-wrapper-container-runner/v1'",
        name="ck_archive_wrapper_lineage_profiles",
    ),
    CheckConstraint(
        "(inner_stream_size_bytes IS NULL AND inner_stream_sha256 IS NULL) OR "
        "(inner_stream_size_bytes BETWEEN 1024 AND 8589934592 "
        "AND inner_stream_sha256 IS NOT NULL)",
        name="ck_archive_wrapper_lineage_size",
    ),
    CheckConstraint(
        "image_reference = 'ghcr.io/gecompat/foliotone-archive-7zip@"
        "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287'",
        name="ck_archive_wrapper_lineage_image",
    ),
    _sha256("archive_wrapper_lineage", "inner_stream_sha256"),
    _sha256("archive_wrapper_lineage", "wrapper_command_identity"),
    _sha256("archive_wrapper_lineage", "listing_command_identity"),
    _sha256("archive_wrapper_lineage", "integrity_command_identity"),
)


ARCHIVE_EVIDENCE_TABLES = (
    archive_observations,
    archive_observation_sources,
    archive_observation_executions,
    archive_member_observations,
    archive_wrapper_lineage,
)
