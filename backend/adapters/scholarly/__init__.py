"""Collection-source adapters beyond OpenAlex."""

from backend.adapters.scholarly.client import (
    COREClient,
    COREClientError,
    ScopusClient,
    ScopusClientError,
    ScholarlySearchRequest,
    SemanticScholarClient,
    SemanticScholarClientError,
)
from backend.adapters.scholarly.mapper import (
    ScholarlySourceMappingError,
    map_core_work,
    map_scopus_entry,
    map_semantic_scholar_paper,
)

__all__ = [
    "COREClient",
    "COREClientError",
    "ScopusClient",
    "ScopusClientError",
    "ScholarlySearchRequest",
    "ScholarlySourceMappingError",
    "SemanticScholarClient",
    "SemanticScholarClientError",
    "map_core_work",
    "map_scopus_entry",
    "map_semantic_scholar_paper",
]
