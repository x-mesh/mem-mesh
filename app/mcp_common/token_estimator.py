"""Token estimation utilities for MCP responses.

Uses tiktoken to estimate token counts for GPT models.
Other models may have different tokenization, so these are estimates.
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Lazy-loaded encoder
_encoder = None


def _get_encoder():
    """Lazy-load tiktoken encoder to avoid startup overhead."""
    global _encoder
    if _encoder is None:
        try:
            import tiktoken
            # cl100k_base is used by GPT-4, GPT-3.5-turbo
            _encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning("tiktoken not installed, token estimation disabled")
            return None
        except Exception as e:
            logger.warning(f"Failed to load tiktoken encoder: {e}")
            return None
    return _encoder


def estimate_tokens(text: str) -> Optional[int]:
    """Estimate token count for given text.
    
    Args:
        text: Text to estimate tokens for
        
    Returns:
        Estimated token count, or None if estimation failed
    """
    encoder = _get_encoder()
    if encoder is None:
        return None
    
    try:
        return len(encoder.encode(text))
    except Exception as e:
        logger.warning(f"Token estimation failed: {e}")
        return None


def add_token_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
    """Add token estimation metadata to a result dict.
    
    Adds _meta field with:
    - char_count: Character count of JSON representation
    - estimated_tokens: Estimated GPT token count
    
    Args:
        result: Original result dictionary
        
    Returns:
        Result with _meta field added
    """
    # Serialize to get accurate character count
    json_text = json.dumps(result)
    char_count = len(json_text)
    
    # Estimate tokens
    estimated_tokens = estimate_tokens(json_text)
    
    # Add metadata
    result["_meta"] = {
        "char_count": char_count,
        "estimated_tokens": estimated_tokens,
    }
    
    return result


def get_response_stats(responses: list) -> Dict[str, Any]:
    """Calculate aggregate stats for multiple responses.
    
    Args:
        responses: List of response dictionaries with _meta
        
    Returns:
        Aggregate statistics
    """
    total_chars = 0
    total_tokens = 0
    count = 0
    
    for resp in responses:
        if "_meta" in resp:
            meta = resp["_meta"]
            total_chars += meta.get("char_count", 0)
            if meta.get("estimated_tokens"):
                total_tokens += meta["estimated_tokens"]
            count += 1
    
    return {
        "response_count": count,
        "total_char_count": total_chars,
        "total_estimated_tokens": total_tokens,
        "avg_tokens_per_response": total_tokens // count if count > 0 else 0,
    }
