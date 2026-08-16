"""External knowledge enrichment and provider boundaries."""

from foliotone.enrichment.contracts import (
    BookKnowledgeDTO,
    BookKnowledgeQuery,
    BookKnowledgeResponse,
    KnowledgeProviderDescriptor,
    KnowledgeProviderMode,
    StructuredKnowledgeBookResult,
)
from foliotone.enrichment.providers import SyntheticBookKnowledgeProvider

__all__ = [
    "BookKnowledgeDTO",
    "BookKnowledgeQuery",
    "BookKnowledgeResponse",
    "KnowledgeProviderDescriptor",
    "KnowledgeProviderMode",
    "StructuredKnowledgeBookResult",
    "SyntheticBookKnowledgeProvider",
]
