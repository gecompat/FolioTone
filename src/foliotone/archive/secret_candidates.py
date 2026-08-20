"""Pure, bounded extraction of ephemeral archive secret candidates.

This module deliberately accepts already supplied bytes only.  It does not
open sidecars, inspect archive names, invoke tools, or try candidate values.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from html.parser import HTMLParser
from itertools import islice
from typing import Final
from urllib.parse import parse_qsl, urlsplit

from foliotone.archive.sidecars import ArchiveSidecar, ArchiveSidecarKind

ARCHIVE_SECRET_CANDIDATE_PROFILE: Final = "archive-secret-candidate/v1"
MAX_SIDECAR_FILES: Final = 32
MAX_BYTES_PER_SIDECAR: Final = 262_144
MAX_TOTAL_SIDECAR_BYTES: Final = 1_048_576
MAX_DECODED_CODEPOINTS: Final = 1_048_576
MAX_LINES_PER_SIDECAR: Final = 4_096
MAX_LINE_CODEPOINTS: Final = 4_096
MAX_HTML_NODES: Final = 10_000
MAX_URI_CODEPOINTS: Final = 4_096
MAX_CANDIDATES: Final = 64
MAX_ATTEMPTS_PER_ARCHIVE: Final = 16
MAX_CANDIDATE_CODEPOINTS: Final = 256
MAX_CANDIDATE_UTF8_BYTES: Final = 1_024


class ArchiveSecretCandidateStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    PARSER_REJECTED = "PARSER_REJECTED"
    POLICY_REJECTED = "POLICY_REJECTED"


class ArchiveSecretCandidateRule(StrEnum):
    MARKER_VALUE = "MARKER_VALUE"
    MARKER_NEXT_LINE = "MARKER_NEXT_LINE"
    URI_VALUE = "URI_VALUE"
    PASSWORD_FIRST_LINE = "PASSWORD_FIRST_LINE"


class ArchiveSecretCandidateSource(StrEnum):
    USER_HANDLE = "USER_HANDLE"
    CONFIRMED_LOCAL_HANDLE = "CONFIRMED_LOCAL_HANDLE"
    ARCHIVE_COMMENT = "ARCHIVE_COMMENT"
    SAME_BASENAME_SIDECAR = "SAME_BASENAME_SIDECAR"
    DIRECTORY_SIDECAR = "DIRECTORY_SIDECAR"
    LOCAL_PASSWORD_LIST = "LOCAL_PASSWORD_LIST"


@dataclass(frozen=True, slots=True)
class ArchiveSecretCandidate:
    """An in-memory candidate whose material is deliberately redacted in text forms."""

    sidecar_kind: ArchiveSidecarKind
    rule: ArchiveSecretCandidateRule
    value: str = field(repr=False)
    source: ArchiveSecretCandidateSource = ArchiveSecretCandidateSource.DIRECTORY_SIDECAR

    def __post_init__(self) -> None:
        if not isinstance(self.sidecar_kind, ArchiveSidecarKind):
            raise ValueError("sidecar_kind must be ArchiveSidecarKind")
        if not isinstance(self.rule, ArchiveSecretCandidateRule):
            raise ValueError("rule must be ArchiveSecretCandidateRule")
        if not _is_candidate_value(self.value):
            raise ValueError("candidate material exceeds the bounded contract")
        if self.source is not ArchiveSecretCandidateSource.DIRECTORY_SIDECAR:
            raise ValueError("sidecar extraction requires DIRECTORY_SIDECAR source")

    def __str__(self) -> str:
        return (
            "ArchiveSecretCandidate("
            f"source={self.source.value!r}, sidecar_kind={self.sidecar_kind.value!r}, "
            "redacted=True)"
        )


@dataclass(frozen=True, slots=True)
class ArchiveSecretCandidateExtraction:
    profile: str
    status: ArchiveSecretCandidateStatus
    candidates: tuple[ArchiveSecretCandidate, ...] = ()
    attempt_limit: int = MAX_ATTEMPTS_PER_ARCHIVE

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_SECRET_CANDIDATE_PROFILE:
            raise ValueError("unsupported archive secret candidate profile")
        if not isinstance(self.status, ArchiveSecretCandidateStatus):
            raise ValueError("status must be ArchiveSecretCandidateStatus")
        if not isinstance(self.candidates, tuple) or len(self.candidates) > MAX_CANDIDATES:
            raise ValueError("candidates exceed the bounded contract")
        if any(not isinstance(item, ArchiveSecretCandidate) for item in self.candidates):
            raise ValueError("candidates must contain ArchiveSecretCandidate values")
        if len({item.value for item in self.candidates}) != len(self.candidates):
            raise ValueError("candidate material must be exactly deduplicated")
        if self.attempt_limit != MAX_ATTEMPTS_PER_ARCHIVE:
            raise ValueError("attempt_limit must use the fixed archive bound")
        if self.status is not ArchiveSecretCandidateStatus.EXTRACTED and self.candidates:
            raise ValueError("failed extraction cannot expose candidates")


_MARKERS: Final = ("password", "passwort", "kennwort", "pass", "pwd", "pw")
_MARKER_VALUE = re.compile(
    r"(?i)(?<![\w])(?:password|passwort|kennwort|pass|pwd|pw)(?![\w])\s*[:=]\s*(.+)$"
)
_MARKER_ONLY = re.compile(r"(?i)^\s*(?:password|passwort|kennwort|pass|pwd|pw)(?![\w])\s*[:=]?\s*$")
_LEGACY_CP437: Final = frozenset(
    {ArchiveSidecarKind.NFO, ArchiveSidecarKind.DIZ, ArchiveSidecarKind.SFV}
)
_LEGACY_CP1252: Final = frozenset(
    {
        ArchiveSidecarKind.TEXT,
        ArchiveSidecarKind.INFO,
        ArchiveSidecarKind.URL,
        ArchiveSidecarKind.HTML,
        ArchiveSidecarKind.README,
        ArchiveSidecarKind.PASSWORD,
    }
)
_RULE_ORDER: Final = {
    ArchiveSecretCandidateRule.MARKER_VALUE: 0,
    ArchiveSecretCandidateRule.MARKER_NEXT_LINE: 1,
    ArchiveSecretCandidateRule.URI_VALUE: 2,
    ArchiveSecretCandidateRule.PASSWORD_FIRST_LINE: 3,
}


def extract_archive_secret_candidates(
    sidecars: Iterable[tuple[ArchiveSidecar, bytes]],
) -> ArchiveSecretCandidateExtraction:
    """Extract only allowed local hints from supplied, bounded sidecar bytes.

    The returned values are ephemeral.  This parser exposes no serialization,
    filesystem, network, subprocess, guessing, or candidate-combination API.
    """

    supplied = tuple(islice(sidecars, MAX_SIDECAR_FILES + 1))
    if len(supplied) > MAX_SIDECAR_FILES:
        return _failed(ArchiveSecretCandidateStatus.LIMIT_EXCEEDED)
    if any(not isinstance(item, tuple) or len(item) != 2 for item in supplied):
        return _failed(ArchiveSecretCandidateStatus.POLICY_REJECTED)
    typed_supplied = tuple((item[0], item[1]) for item in supplied)
    if any(
        not isinstance(sidecar, ArchiveSidecar) or not isinstance(data, bytes)
        for sidecar, data in typed_supplied
    ):
        return _failed(ArchiveSecretCandidateStatus.POLICY_REJECTED)
    if any(len(data) > MAX_BYTES_PER_SIDECAR for _, data in typed_supplied):
        return _failed(ArchiveSecretCandidateStatus.LIMIT_EXCEEDED)
    if sum(len(data) for _, data in typed_supplied) > MAX_TOTAL_SIDECAR_BYTES:
        return _failed(ArchiveSecretCandidateStatus.LIMIT_EXCEEDED)

    password_files = sum(
        sidecar.kind is ArchiveSidecarKind.PASSWORD for sidecar, _ in typed_supplied
    )
    decoded_total = 0
    discovered: list[tuple[str, int, int, ArchiveSecretCandidate]] = []
    for sidecar, data in typed_supplied:
        text = _decode(sidecar.kind, data)
        if text is None:
            return _failed(ArchiveSecretCandidateStatus.PARSER_REJECTED)
        decoded_total += len(text)
        if decoded_total > MAX_DECODED_CODEPOINTS:
            return _failed(ArchiveSecretCandidateStatus.LIMIT_EXCEEDED)
        parsed = _parse_sidecar(sidecar, text, password_files == 1)
        if parsed is None:
            return _failed(ArchiveSecretCandidateStatus.LIMIT_EXCEEDED)
        for ordinal, candidate in enumerate(parsed):
            discovered.append(
                (
                    sidecar.basename.casefold(),
                    _RULE_ORDER[candidate.rule],
                    ordinal,
                    candidate,
                )
            )

    ordered = sorted(discovered, key=lambda item: item[:-1])
    unique: list[ArchiveSecretCandidate] = []
    materials: set[str] = set()
    for *_, candidate in ordered:
        if candidate.value not in materials:
            materials.add(candidate.value)
            unique.append(candidate)
        if len(unique) > MAX_CANDIDATES:
            return _failed(ArchiveSecretCandidateStatus.LIMIT_EXCEEDED)
    return ArchiveSecretCandidateExtraction(
        ARCHIVE_SECRET_CANDIDATE_PROFILE,
        ArchiveSecretCandidateStatus.EXTRACTED,
        tuple(unique),
    )


def _failed(status: ArchiveSecretCandidateStatus) -> ArchiveSecretCandidateExtraction:
    return ArchiveSecretCandidateExtraction(ARCHIVE_SECRET_CANDIDATE_PROFILE, status)


def _decode(kind: ArchiveSidecarKind, data: bytes) -> str | None:
    try:
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig")
        if data.startswith(b"\xff\xfe"):
            return data.decode("utf-16")
        if data.startswith(b"\xfe\xff"):
            return data.decode("utf-16")
        return data.decode("utf-8")
    except UnicodeDecodeError:
        if data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            return None
        try:
            if kind in _LEGACY_CP437:
                return data.decode("cp437")
            if kind in _LEGACY_CP1252:
                return data.decode("cp1252")
        except UnicodeDecodeError:
            return None
    return None


def _parse_sidecar(
    sidecar: ArchiveSidecar, text: str, allow_password_line: bool
) -> tuple[ArchiveSecretCandidate, ...] | None:
    if sidecar.kind is ArchiveSidecarKind.HTML:
        parser = _BoundedHtmlText()
        try:
            parser.feed(text)
            parser.close()
        except _HtmlLimitExceeded:
            return None
        lines: list[str] | tuple[str, ...] = parser.lines
        uri_values = parser.uris
    else:
        lines = text.splitlines()
        uri_values = (
            tuple(_url_file_value(line) for line in lines)
            if sidecar.kind is ArchiveSidecarKind.URL
            else ()
        )
    if len(lines) > MAX_LINES_PER_SIDECAR or any(len(line) > MAX_LINE_CODEPOINTS for line in lines):
        return None

    marker_lines = (
        tuple(line for line in lines if not urlsplit(_url_file_value(line)).scheme)
        if sidecar.kind is ArchiveSidecarKind.URL
        else lines
    )
    found = list(_marker_candidates(sidecar.kind, marker_lines))
    for uri in uri_values:
        found.extend(_uri_candidates(sidecar.kind, uri))
    if allow_password_line and sidecar.kind is ArchiveSidecarKind.PASSWORD:
        first = next((line.strip() for line in lines if _is_material_line(line)), None)
        if first is not None and _is_candidate_value(first):
            found.append(
                ArchiveSecretCandidate(
                    sidecar.kind, ArchiveSecretCandidateRule.PASSWORD_FIRST_LINE, first
                )
            )
    return tuple(found)


def _marker_candidates(
    kind: ArchiveSidecarKind, lines: list[str] | tuple[str, ...]
) -> tuple[ArchiveSecretCandidate, ...]:
    found: list[ArchiveSecretCandidate] = []
    for index, line in enumerate(lines):
        value_match = _MARKER_VALUE.search(line)
        if value_match is not None:
            value = value_match.group(1).strip()
            if _is_candidate_value(value):
                found.append(
                    ArchiveSecretCandidate(kind, ArchiveSecretCandidateRule.MARKER_VALUE, value)
                )
            continue
        if _MARKER_ONLY.fullmatch(line) is not None:
            following = next((item.strip() for item in lines[index + 1 :] if item.strip()), None)
            if following is not None and _is_candidate_value(following):
                found.append(
                    ArchiveSecretCandidate(
                        kind, ArchiveSecretCandidateRule.MARKER_NEXT_LINE, following
                    )
                )
    return tuple(found)


def _uri_candidates(kind: ArchiveSidecarKind, uri: str) -> tuple[ArchiveSecretCandidate, ...]:
    if len(uri) > MAX_URI_CODEPOINTS:
        return ()
    parsed = urlsplit(uri)
    pairs = (
        *parse_qsl(parsed.query, keep_blank_values=True),
        *parse_qsl(parsed.fragment, keep_blank_values=True),
    )
    return tuple(
        ArchiveSecretCandidate(kind, ArchiveSecretCandidateRule.URI_VALUE, value)
        for name, value in pairs
        if name.casefold() in _MARKERS and _is_candidate_value(value)
    )


def _is_candidate_value(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_CANDIDATE_CODEPOINTS:
        return False
    try:
        return len(value.encode("utf-8")) <= MAX_CANDIDATE_UTF8_BYTES
    except UnicodeEncodeError:
        return False


def _is_material_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith(("#", ";", "//"))


class _BoundedHtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.node_count = 0
        self._ignored_depth = 0
        self._lines: list[str] = []
        self._uris: list[str] = []

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple("".join(self._lines).splitlines())

    @property
    def uris(self) -> tuple[str, ...]:
        return tuple(self._uris)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count_node()
        if tag.casefold() in {"script", "style"}:
            self._ignored_depth += 1
        if self._ignored_depth == 0:
            self._uris.extend(
                value
                for name, value in attrs
                if value is not None and name.casefold() in {"href", "src", "action"}
            )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        self._count_node()
        if tag.casefold() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        self._count_node()
        if self._ignored_depth == 0:
            self._lines.append(data)

    def _count_node(self) -> None:
        self.node_count += 1
        if self.node_count > MAX_HTML_NODES:
            raise _HtmlLimitExceeded


class _HtmlLimitExceeded(Exception):
    pass


def _url_file_value(line: str) -> str:
    stripped = line.strip()
    if stripped.casefold().startswith("url="):
        return stripped[4:].strip()
    return stripped
