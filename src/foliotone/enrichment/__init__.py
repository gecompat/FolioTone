"""External knowledge enrichment and provider boundaries."""

from foliotone.enrichment.contracts import (
    BookKnowledgeDTO,
    BookKnowledgeQuery,
    BookKnowledgeResponse,
    KnowledgeProviderDescriptor,
    KnowledgeProviderMode,
    ProviderAccessMode,
    ProviderCachePolicy,
    StructuredKnowledgeBookResult,
    provider_policy_from_legacy,
)
from foliotone.enrichment.providers import SyntheticBookKnowledgeProvider

__all__ = [
    "BookKnowledgeDTO",
    "BookKnowledgeQuery",
    "BookKnowledgeResponse",
    "KnowledgeProviderDescriptor",
    "KnowledgeProviderMode",
    "ProviderAccessMode",
    "ProviderCachePolicy",
    "StructuredKnowledgeBookResult",
    "SyntheticBookKnowledgeProvider",
    "provider_policy_from_legacy",
]
