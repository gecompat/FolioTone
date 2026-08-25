from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.adapters.calibre.metadata import (
    CALIBRE_CONFIG_IDENTITY,
    CALIBRE_METADATA_RESULT,
    CALIBRE_OPF_ARTIFACT,
    MAX_OPF_BYTES,
    CalibreMetadataAnalyzer,
    CalibreMetadataError,
    calibre_version_policy,
    parse_calibre_opf,
    project_calibre_opf,
)
from foliotone.analyzers.ebook import (
    EBOOK_METADATA_CANDIDATE_PROFILE,
    EBOOK_METADATA_CANDIDATE_RESULT,
    resolve_observed_file,
)
from foliotone.core import (
    Agent,
    Edition,
    EntityId,
    FileObservation,
    Series,
    ToolCapability,
    ToolExecutionStatus,
    Work,
)
from foliotone.persistence import create_sqlite_engine, repository
from foliotone.tooling import ToolArtifact, ToolExecution, ToolResult
from foliotone.tooling.runtime import LocalCommand, ToolRunOutcome

pytestmark = pytest.mark.usefixtures("head_database")

NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
SAMPLE_OPF = b"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         version="2.0">
  <metadata>
    <dc:title>  The   Example  </dc:title>
    <dc:creator xmlns:opf="http://www.idpf.org/2007/opf"
                opf:role="aut" opf:file-as="Author, Ada">
      Ada Author
    </dc:creator>
    <dc:contributor xmlns:opf="http://www.idpf.org/2007/opf"
                    opf:role="trl" opf:file-as="Translator, Tina">
      Tina Translator
    </dc:contributor>
    <dc:identifier xmlns:opf="http://www.idpf.org/2007/opf" opf:scheme="ISBN">
      9780000000001
    </dc:identifier>
    <dc:language>en</dc:language>
    <dc:publisher>Example Press</dc:publisher>
    <dc:date>2026-08-14</dc:date>
    <dc:subject>Testing</dc:subject>
    <meta name="calibre:series" content="Example Series" />
    <meta name="calibre:series_index" content="2" />
  </metadata>
</package>
"""
SAMPLE_OPF3 = b"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         version="3.0">
  <metadata>
    <dc:title id="title">The Refined Example</dc:title>
    <meta refines="#title" property="file-as">Refined Example, The</meta>
    <dc:creator id="creator-1">Ada Author</dc:creator>
    <meta refines="#creator-1" property="role" scheme="marc:relators">aut</meta>
    <meta refines="#creator-1" property="file-as">Author, Ada</meta>
    <dc:contributor id="contributor-1">Ed Editor</dc:contributor>
    <meta refines="#contributor-1" property="role" scheme="marc:relators">edt</meta>
    <dc:contributor id="contributor-2">Unmapped Person</dc:contributor>
    <meta refines="#contributor-2" property="role" scheme="custom:roles">aut</meta>
    <dc:identifier id="identifier-1">9780000000002</dc:identifier>
    <meta refines="#identifier-1" property="identifier-type"
          scheme="onix:codelist5">15</meta>
    <dc:identifier>urn:isbn:9780000000003</dc:identifier>
    <dc:identifier id="identifier-3">provider-local-id</dc:identifier>
    <meta refines="#identifier-3" property="identifier-type"
          scheme="custom:identifiers">work</meta>
    <dc:language>de</dc:language>
    <dc:publisher>Refined Press</dc:publisher>
    <dc:date>2026-08-14</dc:date>
    <dc:description>A refined description.</dc:description>
    <dc:rights>CC0</dc:rights>
    <dc:type>Text</dc:type>
    <meta property="belongs-to-collection" id="collection-1">Refined Series</meta>
    <meta refines="#collection-1" property="collection-type">series</meta>
    <meta refines="#collection-1" property="group-position">1.5</meta>
  </metadata>
</package>
"""


@pytest.mark.parametrize(
    ("version", "accepted"),
    (
        ("ebook-meta (calibre 9.13.0)", True),
        ("calibre 9.12", True),
        ("calibre 9.11.0", False),
        ("ebook-meta (calibre 9.9.105)", False),
        ("calibre 8.16.2", False),
        ("unexpected output", False),
    ),
)
def test_calibre_version_policy_enforces_security_floor(version: str, accepted: bool) -> None:
    error = calibre_version_policy(version)
    assert (error is None) is accepted


def test_calibre_opf_parser_preserves_raw_values_and_provenance() -> None:
    execution_id = EntityId.new()
    observation_id = EntityId.new()

    results = parse_calibre_opf(
        SAMPLE_OPF,
        execution_id=execution_id,
        observation_id=observation_id,
    )

    assert [(result.key, result.value) for result in results] == [
        ("title", "The Example"),
        ("creator:aut", "Ada Author"),
        ("creator_file_as:aut", "Author, Ada"),
        ("contributor:trl", "Tina Translator"),
        ("contributor_file_as:trl", "Translator, Tina"),
        ("identifier:isbn", "9780000000001"),
        ("language", "en"),
        ("publisher", "Example Press"),
        ("date", "2026-08-14"),
        ("subject", "Testing"),
        ("series", "Example Series"),
        ("series_index", "2"),
    ]
    assert {result.result_type for result in results} == {CALIBRE_METADATA_RESULT}
    assert {result.execution_id for result in results} == {execution_id}
    assert {result.target_id for result in results} == {observation_id}


def test_opf2_projection_groups_contributors_identifiers_and_series_candidates() -> None:
    execution_id = EntityId.new()
    observation_id = EntityId.new()

    projection = project_calibre_opf(
        SAMPLE_OPF,
        execution_id=execution_id,
        observation_id=observation_id,
    )
    candidates = {candidate.key: candidate for candidate in projection.candidates}

    assert candidates["title"].value == "The Example"
    assert candidates["contributor.1.name"].value == "Ada Author"
    assert candidates["contributor.1.source_element"].value == "creator"
    assert candidates["contributor.1.source_role"].value == "aut"
    assert candidates["contributor.1.role"].value == "author"
    assert candidates["contributor.1.sort_name"].value == "Author, Ada"
    assert candidates["contributor.2.name"].value == "Tina Translator"
    assert candidates["contributor.2.role"].value == "translator"
    assert candidates["identifier.1.value"].value == "9780000000001"
    assert candidates["identifier.1.source_namespace"].value == "ISBN"
    assert candidates["identifier.1.namespace"].value == "isbn"
    assert candidates["language"].value == "en"
    assert candidates["publisher"].value == "Example Press"
    assert candidates["publication_date"].value == "2026-08-14"
    assert candidates["series.1.name"].value == "Example Series"
    assert candidates["series.1.position"].value == "2"
    assert {candidate.result_type for candidate in projection.candidates} == {
        EBOOK_METADATA_CANDIDATE_RESULT
    }
    assert {candidate.execution_id for candidate in projection.candidates} == {execution_id}
    assert {candidate.target_id for candidate in projection.candidates} == {observation_id}
    assert {candidate.confidence for candidate in projection.candidates} == {1.0}
    assert all(
        candidate.explanation is not None
        and EBOOK_METADATA_CANDIDATE_PROFILE in candidate.explanation
        and "not canonical metadata" in candidate.explanation
        for candidate in projection.candidates
    )


def test_opf3_projection_honors_refinements_without_guessing_custom_roles() -> None:
    projection = project_calibre_opf(
        SAMPLE_OPF3,
        execution_id=EntityId.new(),
        observation_id=EntityId.new(),
    )
    observations = [(result.key, result.value) for result in projection.observations]
    candidates = {candidate.key: candidate.value for candidate in projection.candidates}

    assert ("creator:aut", "Ada Author") in observations
    assert ("creator_file_as:aut", "Author, Ada") in observations
    assert ("contributor:edt", "Ed Editor") in observations
    assert ("identifier:15", "9780000000002") in observations
    assert ("series", "Refined Series") in observations
    assert ("series_index", "1.5") in observations
    assert candidates["title_sort"] == "Refined Example, The"
    assert candidates["contributor.1.role"] == "author"
    assert candidates["contributor.1.source_role_scheme"] == "marc:relators"
    assert candidates["contributor.2.role"] == "editor"
    assert candidates["contributor.3.source_role"] == "aut"
    assert candidates["contributor.3.source_role_scheme"] == "custom:roles"
    assert "contributor.3.role" not in candidates
    assert candidates["identifier.1.namespace"] == "isbn"
    assert candidates["identifier.1.source_namespace_scheme"] == "onix:codelist5"
    assert candidates["identifier.2.namespace"] == "isbn"
    assert candidates["identifier.3.source_namespace"] == "work"
    assert candidates["identifier.3.source_namespace_scheme"] == "custom:identifiers"
    assert "identifier.3.namespace" not in candidates
    assert candidates["description"] == "A refined description."
    assert candidates["rights"] == "CC0"
    assert candidates["type"] == "Text"
    assert candidates["series.1.name"] == "Refined Series"
    assert candidates["series.1.position"] == "1.5"


@pytest.mark.parametrize(
    ("source_role", "candidate_role"),
    (
        ("aut", "author"),
        ("bkp", "book_producer"),
        ("ctb", "contributor"),
        ("edt", "editor"),
        ("ill", "illustrator"),
        ("nrt", "narrator"),
        ("oth", "other"),
        ("trl", "translator"),
    ),
)
def test_opf2_projection_maps_supported_marc_relator_roles(
    source_role: str,
    candidate_role: str,
) -> None:
    opf = f"""<package xmlns:dc="http://purl.org/dc/elements/1.1/"
                         xmlns:opf="http://www.idpf.org/2007/opf">
      <metadata><dc:contributor opf:role="{source_role}">Person</dc:contributor></metadata>
    </package>""".encode()

    projection = project_calibre_opf(
        opf,
        execution_id=EntityId.new(),
        observation_id=EntityId.new(),
    )

    assert (
        next(
            candidate.value
            for candidate in projection.candidates
            if candidate.key == "contributor.1.role"
        )
        == candidate_role
    )


@pytest.mark.parametrize(
    ("data", "message"),
    (
        (b"<not-package />", "unexpected root"),
        (b"<package>", "well-formed"),
        (b"\xff", "valid UTF-8"),
        (
            b"<!DOCTYPE package [<!ENTITY x 'unsafe'>]><package><metadata /></package>",
            "forbidden",
        ),
    ),
)
def test_calibre_opf_parser_rejects_unsafe_or_invalid_xml(data: bytes, message: str) -> None:
    with pytest.raises(CalibreMetadataError, match=message):
        parse_calibre_opf(
            data,
            execution_id=EntityId.new(),
            observation_id=EntityId.new(),
        )


def test_calibre_opf_parser_rejects_oversized_documents() -> None:
    with pytest.raises(CalibreMetadataError, match="size limit"):
        parse_calibre_opf(
            b"x" * (MAX_OPF_BYTES + 1),
            execution_id=EntityId.new(),
            observation_id=EntityId.new(),
        )


class RecordingRuntime:
    def __init__(self, execution: ToolExecution, opf: bytes) -> None:
        self.command: LocalCommand | None = None
        self.input_identity: str | None = None
        self.config_identity: str | None = None
        self.opf = opf
        artifact = ToolArtifact(
            id=EntityId.new(),
            execution_id=execution.id,
            artifact_type=CALIBRE_OPF_ARTIFACT,
            relative_path="synthetic/metadata.opf",
            size_bytes=len(opf),
            sha256="0" * 64,
        )
        self.outcome = ToolRunOutcome(execution, (artifact,), "", "")

    def execute_local(
        self,
        _descriptor: object,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        self.command = command
        self.input_identity = input_identity
        self.config_identity = config_identity
        return self.outcome

    def read_artifact_bytes(self, _artifact: ToolArtifact, *, max_bytes: int) -> bytes:
        assert max_bytes == MAX_OPF_BYTES
        return self.opf


@pytest.mark.parametrize(
    "relative_path",
    (
        "books/example.epub",
        "books/example.mobi",
        "books/example.azw",
        "books/example.azw3",
    ),
)
def test_analyzer_exposes_only_read_only_command_shape_and_persists_results(
    tmp_path: Path,
    relative_path: str,
) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="calibre",
        tool_version="ebook-meta (calibre 9.13.0)",
        adapter_version="ebook-meta-opf/2",
        capability=ToolCapability.READ_METADATA,
        input_identity="file-observation:synthetic",
        config_identity=CALIBRE_CONFIG_IDENTITY,
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )
    repository(engine, ToolExecution).save(execution)
    fake_runtime = RecordingRuntime(execution, SAMPLE_OPF)

    source_root = tmp_path / "media"
    source_file = source_root.joinpath(*relative_path.split("/"))
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"synthetic ebook")
    stat = source_file.stat()
    observation = FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path=relative_path,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        observed_at=NOW,
    )

    analyzer = CalibreMetadataAnalyzer(engine, fake_runtime, executable="ebook-meta-test")  # type: ignore[arg-type]
    outcome = analyzer.analyze(source_root, observation)

    assert fake_runtime.command is not None
    assert fake_runtime.command.args == (
        str(resolve_observed_file(source_root, observation)),
        "--to-opf",
        "metadata.opf",
    )
    assert fake_runtime.command.workspace_environment == {
        "CALIBRE_CONFIG_DIRECTORY": "calibre-config"
    }
    assert fake_runtime.command.environment == {"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"}
    assert fake_runtime.command.outputs[0].artifact_type == CALIBRE_OPF_ARTIFACT
    assert fake_runtime.command.version_policy is calibre_version_policy
    assert fake_runtime.input_identity == f"file-observation:{observation.id}"
    assert fake_runtime.config_identity == CALIBRE_CONFIG_IDENTITY
    assert outcome.candidates
    assert set(outcome.all_results) == set(repository(engine, ToolResult).list_all())
    assert {result.execution_id for result in outcome.all_results} == {execution.id}
    assert {result.target_id for result in outcome.all_results} == {observation.id}
    assert repository(engine, Agent).list_all() == []
    assert repository(engine, Work).list_all() == []
    assert repository(engine, Edition).list_all() == []
    assert repository(engine, Series).list_all() == []


def test_analyzer_rejects_changed_source_before_invoking_calibre(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="calibre",
        tool_version="ebook-meta (calibre 9.13.0)",
        adapter_version="ebook-meta-opf/2",
        capability=ToolCapability.READ_METADATA,
        input_identity="file-observation:synthetic",
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
    )
    fake_runtime = RecordingRuntime(execution, SAMPLE_OPF)
    source_root = tmp_path / "media"
    source_root.mkdir()
    source_file = source_root / "book.epub"
    source_file.write_bytes(b"changed")
    observation = FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path="book.epub",
        size_bytes=1,
        modified_at=NOW,
        observed_at=NOW,
    )

    analyzer = CalibreMetadataAnalyzer(engine, fake_runtime)  # type: ignore[arg-type]
    with pytest.raises(CalibreMetadataError, match="changed"):
        analyzer.analyze(source_root, observation)
    assert fake_runtime.command is None
