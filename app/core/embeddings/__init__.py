"""Embeddings module for mem-mesh application.

This module provides embedding generation services.
"""

# Lazy import to avoid sentence_transformers dependency at module load time
__all__ = ["EmbeddingService"]


def __getattr__(name):
    if name == "EmbeddingService":
        from .service import EmbeddingService

        return EmbeddingService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
