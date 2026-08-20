"""Synthetic contract tests for bounded, non-persistent secret candidates."""

import ast
from pathlib import Path
from typing import Any, cast

import pytest

from foliotone.archive import (
    ARCHIVE_SECRET_CANDIDATE_PROFILE,
    MAX_ATTEMPTS_PER_ARCHIVE,
    MAX_BYTES_PER_SIDECAR,
    MAX_CANDIDATE_CODEPOINTS,
    MAX_CANDIDATES,
    MAX_DECODED_CODEPOINTS,
    MAX_HTML_NODES,
    MAX_LINE_CODEPOINTS,
    MAX_LINES_PER_SIDECAR,
    MAX_SIDECAR_FILES,
    MAX_TOTAL_SIDECAR_BYTES,
    ArchiveSecretCandidateSource,
    ArchiveSecretCandidateStatus,
    ArchiveSidecar,
    ArchiveSidecarKind,
    extract_archive_secret_candidates,
)


def _sidecar(name: str, kind: ArchiveSidecarKind, data: bytes) -> tuple[ArchiveSidecar, bytes]:
    return ArchiveSidecar(name, kind), data


def _values(result: object) -> list[str]:
    return [candidate.value for candidate in result.candidates]  # type: ignore[attr-defined]


def test_marker_uri_html_password_and_deterministic_deduplication_are_bounded() -> None:
    result = extract_archive_secret_candidates(
        [
            _sidecar("z.txt", ArchiveSidecarKind.TEXT, b"password: shared\npass\nnext-value"),
            _sidecar("a.nfo", ArchiveSidecarKind.NFO, b"PW=first\npassword: shared"),
            _sidecar(
                "links.url",
                ArchiveSidecarKind.URL,
                b"[InternetShortcut]\nURL=https://invalid/?password=uri#pw=fragment",
            ),
            _sidecar(
                "page.html",
                ArchiveSidecarKind.HTML,
                b"<script>password: ignored</script><p>pwd=html</p>",
            ),
            _sidecar("PASSWORD", ArchiveSidecarKind.PASSWORD, b"# ignored\nfile-first"),
        ]
    )

    assert result.profile == ARCHIVE_SECRET_CANDIDATE_PROFILE
    assert result.status is ArchiveSecretCandidateStatus.EXTRACTED
    assert result.attempt_limit == MAX_ATTEMPTS_PER_ARCHIVE
    assert _values(result) == [
        "first",
        "shared",
        "uri",
        "fragment",
        "html",
        "file-first",
        "next-value",
    ]
    assert "shared" not in repr(result.candidates[1])
    assert "shared" not in str(result.candidates[1])
    assert result.candidates[1].source is ArchiveSecretCandidateSource.DIRECTORY_SIDECAR


@pytest.mark.parametrize(
    ("kind", "payload", "expected"),
    [
        (ArchiveSidecarKind.NFO, b"password: \x82", "é"),
        (ArchiveSidecarKind.TEXT, b"password: \x80", "€"),
        (ArchiveSidecarKind.INFO, b"\xff\xfep\x00w\x00=\x00u\x00t\x00f\x00", "utf"),
    ],
)
def test_decoder_allowlist_and_bom_precedence(
    kind: ArchiveSidecarKind, payload: bytes, expected: str
) -> None:
    suffixes = {
        ArchiveSidecarKind.NFO: ".nfo",
        ArchiveSidecarKind.TEXT: ".txt",
        ArchiveSidecarKind.INFO: ".info",
    }
    suffix = suffixes[kind]
    result = extract_archive_secret_candidates([_sidecar("hint" + suffix, kind, payload)])
    assert result.status is ArchiveSecretCandidateStatus.EXTRACTED
    assert _values(result) == [expected]


def test_unknown_decoder_is_a_fixed_finding_without_candidates() -> None:
    result = extract_archive_secret_candidates(
        [_sidecar("PASSWORD", ArchiveSidecarKind.PASSWORD, b"\xff\xfe\x81")]
    )
    assert result.status is ArchiveSecretCandidateStatus.PARSER_REJECTED
    assert result.candidates == ()

    cp1252_undefined = extract_archive_secret_candidates(
        [_sidecar("hint.txt", ArchiveSidecarKind.TEXT, b"password: \x81")]
    )
    assert cp1252_undefined.status is ArchiveSecretCandidateStatus.PARSER_REJECTED


@pytest.mark.parametrize(
    "sidecars",
    [
        [
            _sidecar(f"{index}.txt", ArchiveSidecarKind.TEXT, b"pw=x")
            for index in range(MAX_SIDECAR_FILES + 1)
        ],
        [_sidecar("a.txt", ArchiveSidecarKind.TEXT, b"x" * (MAX_BYTES_PER_SIDECAR + 1))],
        [
            _sidecar("a.txt", ArchiveSidecarKind.TEXT, b"x" * MAX_BYTES_PER_SIDECAR)
            for _ in range(5)
        ],
        [_sidecar("a.txt", ArchiveSidecarKind.TEXT, b"x" * (MAX_DECODED_CODEPOINTS + 1))],
        [_sidecar("a.txt", ArchiveSidecarKind.TEXT, (b"x\n" * (MAX_LINES_PER_SIDECAR + 1)))],
        [_sidecar("a.txt", ArchiveSidecarKind.TEXT, b"x" * (MAX_LINE_CODEPOINTS + 1))],
        [_sidecar("a.html", ArchiveSidecarKind.HTML, b"<b></b>" * (MAX_HTML_NODES + 1))],
    ],
)
def test_all_input_budgets_reject_without_candidates(
    sidecars: list[tuple[ArchiveSidecar, bytes]],
) -> None:
    result = extract_archive_secret_candidates(sidecars)
    assert result.status is ArchiveSecretCandidateStatus.LIMIT_EXCEEDED
    assert result.candidates == ()


def test_candidate_and_uri_limits_and_64_candidate_bound() -> None:
    oversized = "x" * (MAX_CANDIDATE_CODEPOINTS + 1)
    allowed = b"\n".join(f"pw={index}".encode() for index in range(MAX_CANDIDATES))
    result = extract_archive_secret_candidates(
        [
            _sidecar("a.url", ArchiveSidecarKind.URL, ("https://x/?pw=" + oversized).encode()),
            _sidecar("b.txt", ArchiveSidecarKind.TEXT, allowed),
        ]
    )
    assert result.status is ArchiveSecretCandidateStatus.EXTRACTED
    assert len(result.candidates) == MAX_CANDIDATES
    assert oversized not in _values(result)

    overflow = b"\n".join(f"pw={index}".encode() for index in range(MAX_CANDIDATES + 1))
    rejected = extract_archive_secret_candidates(
        [_sidecar("b.txt", ArchiveSidecarKind.TEXT, overflow)]
    )
    assert rejected.status is ArchiveSecretCandidateStatus.LIMIT_EXCEEDED
    assert rejected.candidates == ()


def test_only_one_password_class_sidecar_gets_its_first_material_line() -> None:
    single = extract_archive_secret_candidates(
        [_sidecar("PASS", ArchiveSidecarKind.PASSWORD, b"not-a-marker")]
    )
    assert _values(single) == ["not-a-marker"]

    ambiguous = extract_archive_secret_candidates(
        [
            _sidecar("PASS", ArchiveSidecarKind.PASSWORD, b"not-a-candidate"),
            _sidecar("PASSWORD", ArchiveSidecarKind.PASSWORD, b"also-not-a-candidate"),
        ]
    )
    assert ambiguous.status is ArchiveSecretCandidateStatus.EXTRACTED
    assert ambiguous.candidates == ()


def test_malformed_input_shape_is_policy_rejected() -> None:
    malformed = cast(Any, ["not-a-sidecar-pair"])
    result = extract_archive_secret_candidates(malformed)
    assert result.status is ArchiveSecretCandidateStatus.POLICY_REJECTED


def test_static_contract_has_no_io_network_tools_or_combination_paths() -> None:
    source = Path(__file__).parents[2] / "src" / "foliotone" / "archive" / "secret_candidates.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {"os", "pathlib", "socket", "subprocess", "requests"}
    assert MAX_TOTAL_SIDECAR_BYTES == 1_048_576
