"""Pure, bounded Open Library response normalisation (ADR-0036)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from foliotone.adapters.openlibrary.query import OpenLibraryRequest, OpenLibraryRouteKind
from foliotone.enrichment.provider_cache_contracts import ProviderCacheResultStatus

PROFILE: Final = "openlibrary-source-record/v2"
PAYLOAD_CODEC: Final = "json/openlibrary-source-dto-v2"
MAX_NORMALIZED_BYTES: Final = 262_144
MAX_INPUT_BYTES: Final = 524_288
MAX_RECORDS: Final = 20
MAX_VALUES: Final = 32
MAX_FINDINGS: Final = 32
_OLID = re.compile(r"^OL[0-9]+(?P<kind>[MWA])$")
_I10 = re.compile(r"^[0-9]{9}[0-9X]$")
_I13 = re.compile(r"^[0-9]{13}$")
_OCLC = re.compile(r"^[0-9]{1,16}$")
_LCCN = re.compile(r"^[A-Za-z0-9-]{1,32}$")


class OpenLibrarySourceStatus(StrEnum):
    SUCCESS = ProviderCacheResultStatus.SUCCESS.value
    NOT_FOUND = ProviderCacheResultStatus.NOT_FOUND.value
    INVALID_RESPONSE = ProviderCacheResultStatus.INVALID_RESPONSE.value


class OpenLibrarySourceFinding(StrEnum):
    INVALID_RESPONSE = "INVALID_RESPONSE"
    MALFORMED_SEARCH_RECORD = "MALFORMED_SEARCH_RECORD"
    MALFORMED_LEGACY_RECORD = "MALFORMED_LEGACY_RECORD"
    MALFORMED_SEARCH_EDITION = "MALFORMED_SEARCH_EDITION"
    SEARCH_EDITIONS_TRUNCATED = "SEARCH_EDITIONS_TRUNCATED"


def _text(v: object, n: int) -> str:
    if not isinstance(v, str):
        raise ValueError("string")
    v = unicodedata.normalize("NFC", v)
    if len(v) > n:
        raise ValueError("bound")
    return v


def _optional(v: object, n: int) -> str | None:
    return None if v is None else _text(v, n)


def _olid(v: object, k: str) -> str | None:
    if not isinstance(v, str):
        return None
    v = unicodedata.normalize("NFC", v)
    prefixes = {"W": "/works/", "M": "/books/", "A": "/authors/"}
    if v.startswith("/"):
        if not v.startswith(prefixes[k]):
            return None
        v = v[len(prefixes[k]) :]
    v = v.upper()
    m = _OLID.fullmatch(v)
    return v if m and m.group("kind") == k and len(v) <= 64 else None


def _need_olid(v: object, k: str) -> str:
    v = _olid(v, k)
    if v is None:
        raise ValueError("olid")
    return v


def _isbn10(v: str) -> bool:
    return (
        bool(_I10.fullmatch(v))
        and sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(v)) % 11 == 0
    )


def _isbn13(v: str) -> bool:
    return (
        bool(_I13.fullmatch(v))
        and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(v)) % 10 == 0
    )


def _tuple(v: object, n: int, check: Callable[[str], bool] | None = None) -> tuple[str, ...]:
    if not isinstance(v, (list, tuple)) or len(v) > MAX_VALUES:
        raise ValueError("list")
    out = tuple(_text(x, n) for x in v)
    if out != tuple(sorted(set(out))) or (check is not None and any(not check(x) for x in out)):
        raise ValueError("list values")
    return out


def _parsed_text(v: object, n: int) -> tuple[str | None, bool]:
    if v is None:
        return None, False
    if not isinstance(v, str):
        raise ValueError("field")
    v = unicodedata.normalize("NFC", v)
    return (None, True) if len(v) > n else (v, False)


def _parsed_list(
    v: object, n: int, check: Callable[[str], bool] | None = None
) -> tuple[tuple[str, ...], bool]:
    if v is None:
        return (), False
    if not isinstance(v, list):
        raise ValueError("list")
    cut = len(v) > MAX_VALUES
    out = []
    for x in v[:MAX_VALUES]:
        s, c = _parsed_text(x, n)
        cut |= c
        if s is not None and (check is None or check(s)):
            out.append(s)
        elif s is not None:
            cut = True
    return tuple(sorted(set(out))), cut


def _refs(v: object, k: str) -> tuple[tuple[str, ...], bool]:
    if v is None:
        return (), False
    if not isinstance(v, list):
        raise ValueError("refs")
    cut = len(v) > MAX_VALUES
    out = []
    for x in v[:MAX_VALUES]:
        o = _olid(x, k)
        cut |= o is None
        if o:
            out.append(o)
    return tuple(sorted(set(out))), cut


def _authors(v: object) -> tuple[tuple[str, ...], bool]:
    if v is None:
        return (), False
    if not isinstance(v, list):
        raise ValueError("authors")
    return _refs(
        [
            (
                (x.get("author", x)).get("key")
                if isinstance(x, dict) and isinstance(x.get("author", x), dict)
                else x
            )
            for x in v
        ],
        "A",
    )


@dataclass(frozen=True, slots=True)
class WorkSourceRecord:
    work_olid: str
    title: str | None
    first_publish_year: str | None
    author_refs: tuple[str, ...]
    subjects: tuple[str, ...]
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_olid", _need_olid(self.work_olid, "W"))
        object.__setattr__(self, "title", _optional(self.title, 512))
        object.__setattr__(self, "first_publish_year", _optional(self.first_publish_year, 64))
        object.__setattr__(
            self, "author_refs", _tuple(self.author_refs, 64, lambda x: _olid(x, "A") == x)
        )
        object.__setattr__(self, "subjects", _tuple(self.subjects, 256))
        if type(self.truncated) is not bool:
            raise ValueError("truncated")

    def as_payload(self) -> dict[str, object]:
        return {
            "work_olid": self.work_olid,
            "title": self.title,
            "first_publish_year": self.first_publish_year,
            "author_refs": list(self.author_refs),
            "subjects": list(self.subjects),
            "truncated": self.truncated,
        }

    def __repr__(self) -> str:
        return "WorkSourceRecord(<redacted>)"


@dataclass(frozen=True, slots=True)
class EditionSourceRecord:
    edition_olid: str | None
    work_refs: tuple[str, ...]
    title: str | None
    subtitle: str | None
    publish_date: str | None
    publishers: tuple[str, ...]
    languages: tuple[str, ...]
    isbn10: tuple[str, ...]
    isbn13: tuple[str, ...]
    oclc: tuple[str, ...]
    lccn: tuple[str, ...]
    author_refs: tuple[str, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if self.edition_olid is not None:
            object.__setattr__(self, "edition_olid", _need_olid(self.edition_olid, "M"))
        object.__setattr__(
            self, "work_refs", _tuple(self.work_refs, 64, lambda x: _olid(x, "W") == x)
        )
        for f, n in (("title", 512), ("subtitle", 512), ("publish_date", 64)):
            object.__setattr__(self, f, _optional(getattr(self, f), n))
        for f, n, c in (
            ("publishers", 256, None),
            ("languages", 64, None),
            ("isbn10", 64, _isbn10),
            ("isbn13", 64, _isbn13),
            ("oclc", 64, lambda x: bool(_OCLC.fullmatch(x))),
            ("lccn", 64, lambda x: bool(_LCCN.fullmatch(x))),
            ("author_refs", 64, lambda x: _olid(x, "A") == x),
        ):
            object.__setattr__(self, f, _tuple(getattr(self, f), n, c))
        if type(self.truncated) is not bool:
            raise ValueError("truncated")
        if self.edition_olid is None and not (self.isbn10 or self.isbn13):
            raise ValueError("edition identity")

    def as_payload(self) -> dict[str, object]:
        return {
            "edition_olid": self.edition_olid,
            "work_refs": list(self.work_refs),
            "title": self.title,
            "subtitle": self.subtitle,
            "publish_date": self.publish_date,
            "publishers": list(self.publishers),
            "languages": list(self.languages),
            "isbn10": list(self.isbn10),
            "isbn13": list(self.isbn13),
            "oclc": list(self.oclc),
            "lccn": list(self.lccn),
            "author_refs": list(self.author_refs),
            "truncated": self.truncated,
        }

    def __repr__(self) -> str:
        return "EditionSourceRecord(<redacted>)"


@dataclass(frozen=True, slots=True)
class AuthorSourceRecord:
    author_olid: str
    name: str | None
    alternate_names: tuple[str, ...]
    birth_date: str | None
    death_date: str | None
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "author_olid", _need_olid(self.author_olid, "A"))
        object.__setattr__(self, "name", _optional(self.name, 512))
        object.__setattr__(self, "alternate_names", _tuple(self.alternate_names, 512))
        object.__setattr__(self, "birth_date", _optional(self.birth_date, 64))
        object.__setattr__(self, "death_date", _optional(self.death_date, 64))
        if type(self.truncated) is not bool:
            raise ValueError("truncated")

    def as_payload(self) -> dict[str, object]:
        return {
            "author_olid": self.author_olid,
            "name": self.name,
            "alternate_names": list(self.alternate_names),
            "birth_date": self.birth_date,
            "death_date": self.death_date,
            "truncated": self.truncated,
        }

    def __repr__(self) -> str:
        return "AuthorSourceRecord(<redacted>)"


@dataclass(frozen=True, slots=True)
class SearchSourceRecord:
    work: WorkSourceRecord | None
    editions: tuple[EditionSourceRecord, ...]
    truncated: bool
    contributor_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.work is not None and not isinstance(self.work, WorkSourceRecord):
            raise ValueError("work")
        e = tuple(self.editions)
        if (
            not e
            and self.work is None
            or len(e) > MAX_VALUES
            or any(not isinstance(x, EditionSourceRecord) for x in e)
            or _stable(e) != list(e)
        ):
            raise ValueError("editions")
        object.__setattr__(self, "editions", e)
        names = tuple(self.contributor_names)
        if len(names) > MAX_VALUES or any(
            not isinstance(x, str)
            or not x
            or unicodedata.normalize("NFC", x) != x
            or len(x) > 512
            for x in names
        ) or names != tuple(sorted(set(names))):
            raise ValueError("contributor_names")
        object.__setattr__(self, "contributor_names", names)
        if type(self.truncated) is not bool:
            raise ValueError("truncated")

    def as_payload(self) -> dict[str, object]:
        return {
            "work": self.work.as_payload() if self.work else None,
            "editions": [x.as_payload() for x in self.editions],
            "contributor_names": list(self.contributor_names),
            "truncated": self.truncated,
        }

    def __repr__(self) -> str:
        return "SearchSourceRecord(<redacted>)"


SourceRecord = WorkSourceRecord | EditionSourceRecord | AuthorSourceRecord | SearchSourceRecord


def _key(x: SourceRecord) -> tuple[str, str]:
    if isinstance(x, WorkSourceRecord):
        return "W", x.work_olid
    if isinstance(x, AuthorSourceRecord):
        return "A", x.author_olid
    if isinstance(x, EditionSourceRecord):
        return "M", x.edition_olid or "|".join(x.isbn10 + x.isbn13)
    return (
        ("S", x.work.work_olid)
        if x.work
        else ("S", "|".join((e.edition_olid or "|".join(e.isbn10 + e.isbn13)) for e in x.editions))
    )


def _stable(xs: Sequence[SourceRecord]) -> list[SourceRecord]:
    d: dict[tuple[str, str], SourceRecord] = {}
    for x in xs:
        b = json.dumps(
            x.as_payload(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
        p = d.get(_key(x))
        if (
            p is None
            or b
            < json.dumps(
                p.as_payload(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ):
            d[_key(x)] = x
    return [d[k] for k in sorted(d)]


@dataclass(frozen=True, slots=True)
class OpenLibrarySourceEnvelope:
    endpoint_kind: str
    records: tuple[SourceRecord, ...]
    result_count: int
    pagination_offset: int
    pagination_complete: bool

    def __post_init__(self) -> None:
        allowed = {
            "EDITION": EditionSourceRecord,
            "WORK": WorkSourceRecord,
            "AUTHOR": AuthorSourceRecord,
            "LEGACY_IDENTIFIER": EditionSourceRecord,
            "SEARCH": SearchSourceRecord,
        }
        r = tuple(self.records)
        if (
            self.endpoint_kind not in allowed
            or not r
            or len(r) > MAX_RECORDS
            or any(not isinstance(x, allowed[self.endpoint_kind]) for x in r)
            or _stable(r) != list(r)
        ):
            raise ValueError("envelope records")
        if (
            type(self.result_count) is not int
            or self.result_count < 0
            or type(self.pagination_offset) is not int
            or self.pagination_offset < 0
            or type(self.pagination_complete) is not bool
            or (self.endpoint_kind != "SEARCH" and self.pagination_offset != 0)
            or (self.endpoint_kind == "SEARCH" and self.pagination_offset not in (0, 10))
            or (
                self.endpoint_kind != "SEARCH"
                and (
                    self.result_count != 1
                    or self.pagination_offset != 0
                    or not self.pagination_complete
                )
            )
        ):
            raise ValueError("envelope bounds")
        object.__setattr__(self, "records", r)

    def as_payload(self) -> dict[str, object]:
        return {
            "profile": PROFILE,
            "endpoint_kind": self.endpoint_kind,
            "records": [x.as_payload() for x in self.records],
            "result_count": self.result_count,
            "pagination_offset": self.pagination_offset,
            "pagination_complete": self.pagination_complete,
        }

    def __repr__(self) -> str:
        return "OpenLibrarySourceEnvelope(<redacted>)"


def _canonical_payload_bytes(envelope: OpenLibrarySourceEnvelope) -> bytes:
    return json.dumps(
        envelope.as_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class OpenLibrarySourceParseResult:
    status: OpenLibrarySourceStatus
    payload: OpenLibrarySourceEnvelope | None
    payload_bytes: bytes | None
    findings: tuple[OpenLibrarySourceFinding, ...] = ()

    def __post_init__(self) -> None:
        s = OpenLibrarySourceStatus(self.status)
        f = tuple(OpenLibrarySourceFinding(x) for x in self.findings)
        canonical = (
            _canonical_payload_bytes(self.payload)
            if isinstance(self.payload, OpenLibrarySourceEnvelope)
            else None
        )
        if (
            len(f) > MAX_FINDINGS
            or (
                s is OpenLibrarySourceStatus.SUCCESS
                and (
                    not isinstance(self.payload, OpenLibrarySourceEnvelope)
                    or type(self.payload_bytes) is not bytes
                    or self.payload_bytes != canonical
                    or len(self.payload_bytes) > MAX_NORMALIZED_BYTES
                )
            )
            or (
                s is not OpenLibrarySourceStatus.SUCCESS
                and (self.payload is not None or self.payload_bytes is not None)
            )
            or (
                s is OpenLibrarySourceStatus.INVALID_RESPONSE
                and not any(
                    item
                    in {
                        OpenLibrarySourceFinding.INVALID_RESPONSE,
                        OpenLibrarySourceFinding.MALFORMED_SEARCH_RECORD,
                        OpenLibrarySourceFinding.MALFORMED_LEGACY_RECORD,
                        OpenLibrarySourceFinding.MALFORMED_SEARCH_EDITION,
                    }
                    for item in f
                )
            )
        ):
            raise ValueError("result")
        object.__setattr__(self, "status", s)
        object.__setattr__(self, "findings", f)

    def __repr__(self) -> str:
        state = "present" if self.payload else "none"
        return f"OpenLibrarySourceParseResult(status={self.status.value!r}, payload={state})"


def _work(v: dict[str, object]) -> WorkSourceRecord | None:
    o = _olid(v.get("key"), "W")
    if not o:
        return None
    a, c1 = _parsed_text(v.get("title"), 512)
    year_value = v.get("first_publish_year", v.get("first_publish_date"))
    y: str | None
    if type(year_value) is int:
        y, c2 = str(year_value), False
    else:
        y, c2 = _parsed_text(year_value, 64)
    r, c3 = _refs(v.get("author_key"), "A") if "author_key" in v else _authors(v.get("authors"))
    s, c4 = _parsed_list(v.get("subjects"), 256)
    return WorkSourceRecord(o, a, y, r, s, c1 or c2 or c3 or c4)


def _edition(v: object, allow_isbn_only: bool) -> EditionSourceRecord | None:
    if not isinstance(v, dict):
        return None
    o = _olid(v.get("key"), "M")
    a, c1 = _parsed_text(v.get("title"), 512)
    b, c2 = _parsed_text(v.get("subtitle"), 512)
    d, c3 = _parsed_text(v.get("publish_date"), 64)
    p, c4 = _parsed_list(v.get("publishers"), 256)
    lr = v.get("languages")
    languages, c5 = _parsed_list(
        [x.get("key") if isinstance(x, dict) else x for x in lr] if isinstance(lr, list) else lr, 64
    )
    i10, c6 = _parsed_list(v.get("isbn_10"), 64, _isbn10)
    i13, c7 = _parsed_list(v.get("isbn_13", v.get("isbn")), 64, _isbn13)
    oc, c8 = _parsed_list(v.get("oclc_numbers"), 64, lambda x: bool(_OCLC.fullmatch(x)))
    lc, c9 = _parsed_list(v.get("lccn"), 64, lambda x: bool(_LCCN.fullmatch(x)))
    wr = v.get("works")
    w, c10 = _refs(
        [x.get("key") if isinstance(x, dict) else x for x in wr] if isinstance(wr, list) else wr,
        "W",
    )
    ar, c11 = _authors(v.get("authors"))
    if not o and (not allow_isbn_only or not (i10 or i13)):
        return None
    return EditionSourceRecord(
        o,
        w,
        a,
        b,
        d,
        p,
        languages,
        i10,
        i13,
        oc,
        lc,
        ar,
        any((c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11)),
    )


def _author(v: dict[str, object]) -> AuthorSourceRecord | None:
    o = _olid(v.get("key"), "A")
    if not o:
        return None
    n, c1 = _parsed_text(v.get("name"), 512)
    a, c2 = _parsed_list(v.get("alternate_names"), 512)
    b, c3 = _parsed_text(v.get("birth_date"), 64)
    d, c4 = _parsed_text(v.get("death_date"), 64)
    return AuthorSourceRecord(o, n, a, b, d, c1 or c2 or c3 or c4)


def _path(path: str, k: str) -> str:
    m = re.fullmatch(rf"/(?:works|books|authors)/(OL[0-9]+{k})\.json", path)
    if not m:
        raise ValueError("path")
    return m.group(1)


def _search(v: object) -> tuple[SearchSourceRecord | None, list[OpenLibrarySourceFinding]]:
    if not isinstance(v, dict):
        return None, []
    w = _work(
        {
            "key": v.get("key"),
            "title": v.get("title"),
            "first_publish_year": v.get("first_publish_year"),
            "author_key": v.get("author_key", []),
        }
    )
    c = v.get("editions")
    docs = c.get("docs", []) if isinstance(c, dict) else []
    if not isinstance(docs, list):
        return None, []
    author_name = v.get("author_name")
    if author_name is not None and not isinstance(author_name, list):
        return None, []
    names: list[str] = []
    name_cut = isinstance(author_name, list) and len(author_name) > MAX_VALUES
    for raw_name in (author_name[:MAX_VALUES] if isinstance(author_name, list) else []):
        if not isinstance(raw_name, str):
            name_cut = True
            continue
        name = unicodedata.normalize("NFC", raw_name)
        if not name or len(name) > 512:
            name_cut = True
            continue
        names.append(name)
    f = [OpenLibrarySourceFinding.SEARCH_EDITIONS_TRUNCATED] if len(docs) > MAX_VALUES else []
    e: list[EditionSourceRecord] = []
    for raw in docs[:MAX_VALUES]:
        x = _edition(raw, True)
        if x is None:
            f.append(OpenLibrarySourceFinding.MALFORMED_SEARCH_EDITION)
        else:
            e.append(x)
    e = [x for x in _stable(e) if isinstance(x, EditionSourceRecord)]
    return (
        (None, f)
        if w is None and not e
        else (
            SearchSourceRecord(
                w,
                tuple(e),
                len(docs) > MAX_VALUES or name_cut or any(x.truncated for x in e),
                tuple(sorted(set(names))),
            ),
            f,
        )
    )


def _invalid(
    f: tuple[OpenLibrarySourceFinding, ...] = (OpenLibrarySourceFinding.INVALID_RESPONSE,),
) -> OpenLibrarySourceParseResult:
    return OpenLibrarySourceParseResult(
        OpenLibrarySourceStatus.INVALID_RESPONSE, None, None, f[:MAX_FINDINGS]
    )


def parse_openlibrary_source(
    data: bytes, request: OpenLibraryRequest
) -> OpenLibrarySourceParseResult:
    if (
        type(data) is not bytes
        or len(data) > MAX_INPUT_BYTES
        or not isinstance(request, OpenLibraryRequest)
    ):
        return _invalid()
    try:
        root = json.loads(
            data.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
        if not isinstance(root, dict):
            raise ValueError()
        k = request.route_kind
        if not root and k is not OpenLibraryRouteKind.SEARCH:
            return OpenLibrarySourceParseResult(OpenLibrarySourceStatus.NOT_FOUND, None, None)
        f: list[OpenLibrarySourceFinding] = []
        records: list[SourceRecord]
        count = 0
        off = 0
        complete = True
        endpoint = ""
        if k is OpenLibraryRouteKind.WORK:
            work = _work(root)
            records = (
                [work] if work is not None and work.work_olid == _path(request.path, "W") else []
            )
        elif k in (OpenLibraryRouteKind.EDITION, OpenLibraryRouteKind.ISBN):
            edition = _edition(root, False)
            expected = request.path.removeprefix("/isbn/").removesuffix(".json")
            ok = edition is not None and (
                edition.edition_olid == _path(request.path, "M")
                if k is OpenLibraryRouteKind.EDITION
                else expected in edition.isbn10 + edition.isbn13
            )
            records = [edition] if ok and edition is not None else []
        elif k is OpenLibraryRouteKind.AUTHOR:
            author = _author(root)
            records = (
                [author]
                if author is not None and author.author_olid == _path(request.path, "A")
                else []
            )
        elif k is OpenLibraryRouteKind.LEGACY_IDENTIFIER:
            key = dict(request.query).get("bibkeys")
            legacy = (
                _edition(root.get(key), False)
                if isinstance(key, str) and set(root) == {key}
                else None
            )
            records = [legacy] if legacy is not None else []
            f = [] if legacy is not None else [OpenLibrarySourceFinding.MALFORMED_LEGACY_RECORD]
        else:
            docs = root.get("docs")
            a = root.get("numFound")
            b = root.get("num_found")
            off = root.get("start", 0)
            expect = dict(request.query).get("offset")
            if (
                not isinstance(docs, list)
                or len(docs) > MAX_RECORDS
                or a is not None
                and b is not None
                and a != b
            ):
                raise ValueError()
            count_value = a if a is not None else b
            if (
                type(count_value) is not int
                or count_value < 0
                or type(off) is not int
                or expect not in {"0", "10"}
                or off != int(expect)
                or count_value < off + len(docs)
            ):
                raise ValueError()
            count = int(count_value)
            rs: list[SearchSourceRecord] = []
            for x in docs:
                search_record, ff = _search(x)
                f.extend(ff)
                if search_record is None:
                    f.append(OpenLibrarySourceFinding.MALFORMED_SEARCH_RECORD)
                else:
                    rs.append(search_record)
            records = _stable(rs)
            endpoint = "SEARCH"
            complete = off + len(docs) >= count
        if k is not OpenLibraryRouteKind.SEARCH:
            count, off, complete = 1, 0, True
            endpoint = "EDITION" if k is OpenLibraryRouteKind.ISBN else k.value
        if not records:
            if k is OpenLibraryRouteKind.SEARCH and count == 0:
                return OpenLibrarySourceParseResult(
                    OpenLibrarySourceStatus.NOT_FOUND, None, None, tuple(f[:MAX_FINDINGS])
                )
            return _invalid(tuple(f) or (OpenLibrarySourceFinding.INVALID_RESPONSE,))
        env = OpenLibrarySourceEnvelope(endpoint, tuple(records), count, off, complete)
        raw = _canonical_payload_bytes(env)
        return (
            _invalid()
            if len(raw) > MAX_NORMALIZED_BYTES
            else OpenLibrarySourceParseResult(
                OpenLibrarySourceStatus.SUCCESS, env, raw, tuple(f[:MAX_FINDINGS])
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError):
        return _invalid()


__all__ = [
    "AuthorSourceRecord",
    "EditionSourceRecord",
    "MAX_NORMALIZED_BYTES",
    "OpenLibrarySourceEnvelope",
    "OpenLibrarySourceFinding",
    "OpenLibrarySourceParseResult",
    "OpenLibrarySourceStatus",
    "PROFILE",
    "PAYLOAD_CODEC",
    "SearchSourceRecord",
    "WorkSourceRecord",
    "parse_openlibrary_source",
]
