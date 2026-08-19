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
from foliotone.enrichment.provider_cache_contracts import (
    ProviderCacheContentSlot,
    ProviderCacheFailureSlot,
    ProviderCacheFreshness,
    ProviderCacheLimits,
    ProviderCachePayloadKind,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
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
    "ProviderCacheContentSlot",
    "ProviderCacheFailureSlot",
    "ProviderCacheFreshness",
    "ProviderCacheLimits",
    "ProviderCachePayloadKind",
    "ProviderCacheResultStatus",
    "ProviderCacheSlots",
    "StructuredKnowledgeBookResult",
    "SyntheticBookKnowledgeProvider",
    "provider_policy_from_legacy",
]
