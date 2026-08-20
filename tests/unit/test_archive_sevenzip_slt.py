from __future__ import annotations

import pytest

import foliotone.archive.sevenzip_slt as slt
from foliotone.archive.sevenzip_slt import (
    ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
    ARCHIVE_7ZIP_SLT_PARSER_PROFILE,
    MAX_CHUNK_BYTES,
    MAX_CHUNKS,
    MAX_COMMENT_CODEPOINTS,
    MAX_LINE_CODEPOINTS,
    MAX_MEMBER_COUNT,
    MAX_STDOUT_BYTES,
    ArchiveSevenZipSltHeader,
    ArchiveSevenZipSltMember,
    ArchiveSevenZipSltMemberParseResult,
    ArchiveSevenZipSltParseResult,
    ArchiveSevenZipSltParseStatus,
    EphemeralArchiveComment,
    parse_archive_7zip_slt,
    parse_archive_7zip_slt_members,
)


def _v2_record(
    *, path: str = "safe.epub", encrypted: str = "-", eol: str = "\n", extra: str = ""
) -> bytes:
    lines = [
        f"Path = {path}",
        "Folder = -",
        "Size = 1",
        "Packed Size = 1",
        f"Encrypted = {encrypted}",
    ]
    if extra:
        lines.append(extra)
    return (eol.join(lines) + eol + eol).encode()


def test_member_only_v2_accepts_empty_and_exact_records_incrementally() -> None:
    empty = parse_archive_7zip_slt_members([])
    assert empty.status is ArchiveSevenZipSltParseStatus.PARSED and empty.members == ()
    source = _v2_record(path="bücher/é.epub") + _v2_record(path="safe-2.epub")
    result = parse_archive_7zip_slt_members(bytes((byte,)) for byte in source)
    assert result.profile == ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE
    assert result.status is ArchiveSevenZipSltParseStatus.PARSED and len(result.members) == 2
    assert "bücher" not in repr(result)


@pytest.mark.parametrize("split", [1, 2, 3, 7, 31])
def test_member_only_v2_accepts_lf_and_crlf_across_chunk_boundaries(split: int) -> None:
    for source in (_v2_record(path="bücher/é.epub"), _v2_record(eol="\r\n")):
        result = parse_archive_7zip_slt_members(
            source[index : index + split] for index in range(0, len(source), split)
        )
        assert result.status is ArchiveSevenZipSltParseStatus.PARSED


@pytest.mark.parametrize(
    "source",
    [
        _v2_record()[:-1],
        b"\n" + _v2_record(),
        _v2_record() + b"\n",
        _v2_record() + b"Banner\n",
        b"Banner\n\n",
        b"----------\n\n",
        b"Path = archive.7z\nType = 7z\nPhysical Size = 1\n\n----------\n",
        _v2_record().replace(b"\n", b"\r", 1),
    ],
)
def test_member_only_v2_rejects_nonmember_and_exact_blank_grammar(source: bytes) -> None:
    assert (
        parse_archive_7zip_slt_members([source]).status
        is ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
    )


@pytest.mark.parametrize("missing", ["Path", "Folder", "Size", "Packed Size", "Encrypted"])
@pytest.mark.parametrize("empty", [False, True])
def test_member_only_v2_requires_nonempty_core_fields(missing: str, empty: bool) -> None:
    lines = _v2_record().decode().splitlines()
    prefix = missing + " = "
    source_lines = [
        (prefix if empty and line.startswith(prefix) else line)
        for line in lines
        if empty or not line.startswith(prefix)
    ]
    source = ("\n".join(source_lines) + "\n\n").encode()
    assert (
        parse_archive_7zip_slt_members([source]).status
        is ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
    )


def test_member_only_v2_rejects_duplicate_unknown_and_unsafe_members() -> None:
    cases = (
        _v2_record(extra="Size = 1"),
        _v2_record(extra="Unknown = value"),
        _v2_record(path="../escape"),
        _v2_record(path="A.epub") + _v2_record(path="a.EPUB"),
        _v2_record(path="a") + _v2_record(path="a/child"),
        _v2_record(path="a/child") + _v2_record(path="a"),
    )
    for source in cases:
        assert (
            parse_archive_7zip_slt_members([source]).status
            is ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
        )


def test_member_only_v2_preserves_only_bounded_optional_projection() -> None:
    result = parse_archive_7zip_slt_members(
        [_v2_record(extra="Symbolic Link = private-target")]
    )
    assert result.status is ArchiveSevenZipSltParseStatus.PARSED
    assert result.members[0].symbolic_link is True
    assert "private-target" not in repr(result)


def test_member_only_v2_bom_controls_and_iterable_errors_are_fixed() -> None:
    assert (
        parse_archive_7zip_slt_members([b"\xef\xbb\xbf" + _v2_record()]).status
        is ArchiveSevenZipSltParseStatus.PARSED
    )
    assert (
        parse_archive_7zip_slt_members([_v2_record() + b"\xef\xbb\xbf"]).status
        is ArchiveSevenZipSltParseStatus.ENCODING_REJECTED
    )
    for control in (b"\x00", b"\x1f", b"\x7f", "\u0080".encode()):
        assert (
            parse_archive_7zip_slt_members([_v2_record().replace(b"safe.epub", control)]).status
            is ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
        )
    assert (
        parse_archive_7zip_slt_members([_v2_record().replace(b"safe.epub", b"\x80")]).status
        is ArchiveSevenZipSltParseStatus.ENCODING_REJECTED
    )

    def failing_chunks() -> object:
        yield _v2_record()[:10]
        raise RuntimeError("private-path-and-secret")

    result = parse_archive_7zip_slt_members(failing_chunks())  # type: ignore[arg-type]
    assert result.status is ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
    assert "private" not in repr(result)


def test_member_only_v2_enforces_chunk_stream_and_line_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        parse_archive_7zip_slt_members([b"x" * (MAX_CHUNK_BYTES + 1)]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    monkeypatch.setattr(slt, "MAX_CHUNKS", 2)
    assert (
        parse_archive_7zip_slt_members([b"", b"", b""]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    monkeypatch.setattr(slt, "MAX_STDOUT_BYTES", 3)
    assert (
        parse_archive_7zip_slt_members([b"Path"]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    monkeypatch.setattr(slt, "MAX_STDOUT_BYTES", MAX_STDOUT_BYTES)
    monkeypatch.setattr(slt, "MAX_CHUNKS", MAX_CHUNKS)
    assert (
        parse_archive_7zip_slt_members([b"x" * (MAX_LINE_CODEPOINTS + 1) + b"\n"]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    utf8_oversized_line = _v2_record(extra="Method = " + "\u20ac" * 4087)
    assert (
        parse_archive_7zip_slt_members([utf8_oversized_line]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )


def test_member_only_v2_result_enforces_direct_invariants() -> None:
    member = _member(locator="private/title.epub")
    valid = ArchiveSevenZipSltMemberParseResult(
        ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
        ArchiveSevenZipSltParseStatus.PARSED,
        (member,),
    )
    assert "private/title.epub" not in repr(valid)
    invalid_constructors = (
        lambda: ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE, "PARSED", ()  # type: ignore[arg-type]
        ),
        lambda: ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            [],  # type: ignore[arg-type]
        ),
        lambda: ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            (object(),),  # type: ignore[arg-type]
        ),
        lambda: ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            (_member(locator="A.epub"), _member(locator="a.EPUB")),
        ),
        lambda: ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            (_member(locator="a/child"), _member(locator="a")),
        ),
        lambda: ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            (member,) * (MAX_MEMBER_COUNT + 1),
        ),
        lambda: ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
            (member,),
        ),
    )
    for constructor in invalid_constructors:
        with pytest.raises(ValueError):
            constructor()


def _listing(*, comment: str = "", member_path: str = "books/a.epub") -> bytes:
    header_comment = f"Comment = {comment}\n" if comment else ""
    return (
        "Path = archive.7z\n"
        "Type = 7z\n"
        "Physical Size = 12\n"
        f"{header_comment}"
        "\n"
        "----------\n"
        f"Path = {member_path}\n"
        "Folder = -\n"
        "Size = 10\n"
        "Packed Size = 8\n"
        "Encrypted = -\n"
    ).encode()


def test_chunk_boundaries_and_private_values_are_preserved_only_in_private_dtos() -> None:
    source = _listing(comment="do-not-render", member_path="private/title.epub")
    result = parse_archive_7zip_slt(bytes((byte,)) for byte in source)

    assert result.profile == ARCHIVE_7ZIP_SLT_PARSER_PROFILE
    assert result.status is ArchiveSevenZipSltParseStatus.PARSED
    assert result.header is not None
    assert result.header.archive_type == "7z"
    assert result.members[0].declared_uncompressed_bytes == 10
    assert result.comment is not None
    assert "private/title.epub" not in repr(result)
    assert "do-not-render" not in repr(result)
    assert "do-not-render" not in str(result.comment)


@pytest.mark.parametrize("split", [1, 2, 3, 4])
def test_utf8_and_crlf_boundaries_are_independent_of_chunks(split: int) -> None:
    source = _listing(member_path="bücher/é.epub").replace(b"\n", b"\r\n")
    result = parse_archive_7zip_slt(
        source[index : index + split] for index in range(0, len(source), split)
    )
    assert result.status is ArchiveSevenZipSltParseStatus.PARSED


@pytest.mark.parametrize(
    "chunks,status",
    [
        ([b"\xff"], ArchiveSevenZipSltParseStatus.ENCODING_REJECTED),
        ([_listing().replace(b"\n", b"\r", 1)], ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED),
        (
            [_listing().replace(b"Type = 7z", b"Type = 7z\x00")],
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
        ),
        ([_listing()[:-1]], ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED),
        (
            [_listing().replace(b"Size = 10", b"Unknown = 1")],
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
        ),
        (
            [_listing().replace(b"Size = 10", b"Size = 10\nSize = 10")],
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
        ),
        ([_listing(member_path="../escape")], ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED),
    ],
)
def test_rejections_are_fixed_and_drop_all_values(
    chunks: list[bytes], status: ArchiveSevenZipSltParseStatus
) -> None:
    result = parse_archive_7zip_slt(chunks)
    assert result.status is status
    assert result.header is None
    assert result.members == ()
    assert result.comment is None


def test_bom_is_accepted_only_once_at_start() -> None:
    assert (
        parse_archive_7zip_slt([b"\xef\xbb\xbf" + _listing()]).status
        is ArchiveSevenZipSltParseStatus.PARSED
    )
    assert (
        parse_archive_7zip_slt([_listing() + b"\xef\xbb\xbf"]).status
        is ArchiveSevenZipSltParseStatus.ENCODING_REJECTED
    )


def test_boundaries_reject_oversized_chunks_streams_lines_and_comments() -> None:
    assert (
        parse_archive_7zip_slt([b"x" * (MAX_CHUNK_BYTES + 1)]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    assert (
        parse_archive_7zip_slt([b""] * (MAX_CHUNKS + 1)).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    assert (
        parse_archive_7zip_slt([b"x" * (MAX_STDOUT_BYTES + 1)]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    assert (
        parse_archive_7zip_slt([b"x" * (MAX_LINE_CODEPOINTS + 1) + b"\n"]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )
    assert (
        parse_archive_7zip_slt([_listing(comment="x" * (MAX_COMMENT_CODEPOINTS + 1))]).status
        is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
    )


def test_unsafe_presence_fields_are_boolean_projected_and_values_discarded() -> None:
    source = _listing().replace(
        b"Encrypted = -\n",
        (
            b"Encrypted = -\nSymbolic Link = private-target\n"
            b"User = private-user\nAlternate Stream = +\n"
        ),
    )
    result = parse_archive_7zip_slt([source])

    assert result.status is ArchiveSevenZipSltParseStatus.PARSED
    member = result.members[0]
    assert (member.symbolic_link, member.user_present, member.alternate_stream) == (
        True,
        True,
        True,
    )
    assert "private-target" not in repr(result)
    assert "private-user" not in repr(result)


def test_header_characteristics_and_type_are_projected_without_raw_repr_leaks() -> None:
    source = _listing().replace(
        b"Type = 7z\n",
        b"Type = private-type\nCharacteristics = private-characteristics\n",
    )
    result = parse_archive_7zip_slt([source])

    assert result.status is ArchiveSevenZipSltParseStatus.PARSED
    assert result.header is not None
    assert result.header.characteristics_present is True
    assert result.header.archive_type == "private-type"
    assert "private-type" not in repr(result)
    assert "private-characteristics" not in repr(result)


def test_colliding_and_parent_child_member_paths_fail_closed() -> None:
    second = _listing(member_path="a/child").split(b"----------\n", 1)[1]
    source = _listing(member_path="a") + b"\n" + second
    assert parse_archive_7zip_slt([source]).status is ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED


def _member(**changes: object) -> ArchiveSevenZipSltMember:
    values: dict[str, object] = {
        "locator": "safe/book.epub",
        "is_directory": False,
        "declared_uncompressed_bytes": 10,
        "declared_compressed_bytes": 8,
        "encrypted": False,
        "crc32": None,
        "symbolic_link": False,
        "hard_link": False,
        "user_present": False,
        "group_present": False,
        "characteristics_present": False,
        "alternate_stream": False,
        "anti_item": False,
    }
    values.update(changes)
    return ArchiveSevenZipSltMember(**values)  # type: ignore[arg-type]


def test_public_dtos_enforce_bounds_types_and_sum_type_invariants() -> None:
    with pytest.raises(ValueError, match="comment violates"):
        EphemeralArchiveComment("x" * (MAX_COMMENT_CODEPOINTS + 1))
    with pytest.raises(ValueError, match="archive type violates"):
        ArchiveSevenZipSltHeader("private", "", 1)
    with pytest.raises(ValueError, match="physical_size violates"):
        ArchiveSevenZipSltHeader("private", "7z", True)
    with pytest.raises(ValueError, match="member locator violates"):
        _member(locator="../escape")
    with pytest.raises(ValueError, match="encrypted must be bool"):
        _member(encrypted=1)
    with pytest.raises(ValueError, match="crc32 violates"):
        _member(crc32="abcdef12")

    header = ArchiveSevenZipSltHeader("private", "7z", 1)
    with pytest.raises(ValueError, match="members must contain"):
        ArchiveSevenZipSltParseResult(
            ARCHIVE_7ZIP_SLT_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            header,
            (object(),),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="distinct and safe"):
        ArchiveSevenZipSltParseResult(
            ARCHIVE_7ZIP_SLT_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            header,
            (_member(locator="A.epub"), _member(locator="a.EPUB")),
        )
    with pytest.raises(ValueError, match="failed result"):
        ArchiveSevenZipSltParseResult(
            ARCHIVE_7ZIP_SLT_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
            members=[],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: EphemeralArchiveComment(" secret "),
        lambda: EphemeralArchiveComment("\ufeffsecret"),
        lambda: ArchiveSevenZipSltHeader(" private", "7z", 1),
        lambda: ArchiveSevenZipSltHeader("private", "7z\ufeff", 1),
    ],
)
def test_public_private_text_dtos_reject_whitespace_and_bom(constructor: object) -> None:
    with pytest.raises(ValueError):
        constructor()  # type: ignore[operator]


def test_iterable_exception_is_reduced_to_fixed_path_free_status() -> None:
    private_text = "C:/private/title.epub secret-material"

    def failing_chunks() -> object:
        yield _listing()[:12]
        raise ValueError(private_text)

    result = parse_archive_7zip_slt(failing_chunks())  # type: ignore[arg-type]
    assert result.status is ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
    assert private_text not in repr(result)
