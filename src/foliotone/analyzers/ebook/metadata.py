"""Provider-neutral, provenance-linked e-book metadata candidates."""

from __future__ import annotations

from dataclasses import dataclass

from foliotone.core import EntityId, EntityKind
from foliotone.core._validation import require_confidence, require_non_empty
from foliotone.tooling import ToolResult

EBOOK_METADATA_CANDIDATE_RESULT = "ebook_metadata_candidate"
EBOOK_METADATA_CANDIDATE_PROFILE = "ebook-metadata-candidate/v1"


@dataclass(frozen=True, slots=True)
class EbookMetadataCandidate:
    """One non-canonical field candidate projected from bounded tool evidence."""

    field_path: str
    value: str
    source_location: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        for field_name in ("field_path", "value", "source_location"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        require_confidence(self.confidence)

    def to_tool_result(
        self,
        *,
        execution_id: EntityId,
        observation_id: EntityId,
    ) -> ToolResult:
        """Bind the candidate to the exact tool execution and file observation."""
        return ToolResult(
            id=EntityId.new(),
            execution_id=execution_id,
            result_type=EBOOK_METADATA_CANDIDATE_RESULT,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation_id,
            key=self.field_path,
            value=self.value,
            confidence=self.confidence,
            explanation=(
                f"{EBOOK_METADATA_CANDIDATE_PROFILE}; source={self.source_location}; "
                "direct metadata projection, not canonical metadata"
            ),
        )
