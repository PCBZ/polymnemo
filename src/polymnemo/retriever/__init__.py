from .base import Retriever
from .hybrid import HybridRetriever, rrf_fuse
from .keyword import KeywordRetriever
from .vector import VectorRetriever

# What `recall` accepts. `similarity` is the default and the only one that
# existed before #17.
RECALL_MODES = ("similarity", "keyword", "rrf")

__all__ = [
    "RECALL_MODES",
    "HybridRetriever",
    "KeywordRetriever",
    "Retriever",
    "VectorRetriever",
    "rrf_fuse",
]
