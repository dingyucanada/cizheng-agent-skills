"""Optional local NeMo embedding ranker; not enabled by the main application."""
from .client import RetrieverClient, RetrieverError, SnapshotIndex

__all__ = ["RetrieverClient", "RetrieverError", "SnapshotIndex"]
