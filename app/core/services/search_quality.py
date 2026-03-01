"""
Advanced Search Quality System for mem-mesh
검색 품질 향상을 위한 고급 시스템
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SearchIntent:
    """Search intent analysis result"""

    intent_type: str  # 'lookup', 'explore', 'debug', 'learn', 'review'
    urgency: float  # 0.0 - 1.0
    specificity: float  # 0.0 - 1.0
    temporal_focus: str  # 'recent', 'historical', 'any'
    expected_category: Optional[str] = None
    key_entities: List[str] = None


class SearchIntentAnalyzer:
    """Analyze search query intent for better results"""

    def __init__(self):
        # Intent patterns
        self.debug_patterns = [
            r"\berror\b",
            r"\bbug\b",
            r"\bfix\b",
            r"\bissue\b",
            r"\bcrash\b",
            r"\bfail\b",
            r"\bexception\b",
            r"\bproblem\b",
        ]
        self.lookup_patterns = [
            r"\bwhat\s+is\b",
            r"\bhow\s+to\b",
            r"\bwhere\s+is\b",
            r"\bshow\s+me\b",
            r"\bfind\b",
            r"\bget\b",
        ]
        self.explore_patterns = [
            r"\brelated\b",
            r"\bsimilar\b",
            r"\blike\b",
            r"\balternative\b",
            r"\bother\b",
            r"\bmore\b",
        ]
        self.review_patterns = [
            r"\brecent\b",
            r"\blast\b",
            r"\bprevious\b",
            r"\bhistory\b",
            r"\bchanges\b",
            r"\bupdates\b",
        ]
        self.learn_patterns = [
            r"\bunderstand\b",
            r"\bexplain\b",
            r"\bwhy\b",
            r"\bconcept\b",
            r"\bidea\b",
            r"\btheory\b",
        ]

        # Urgency indicators
        self.urgency_keywords = {
            "urgent": 1.0,
            "asap": 1.0,
            "critical": 0.9,
            "important": 0.8,
            "now": 0.8,
            "immediately": 0.9,
            "quick": 0.7,
            "fast": 0.7,
        }

        # Temporal indicators
        self.temporal_keywords = {
            "recent": "recent",
            "latest": "recent",
            "new": "recent",
            "today": "recent",
            "yesterday": "recent",
            "last week": "recent",
            "old": "historical",
            "past": "historical",
            "previous": "historical",
            "history": "historical",
            "archive": "historical",
        }

    def analyze(self, query: str) -> SearchIntent:
        """Analyze search query intent"""
        query_lower = query.lower()

        # Determine intent type
        intent_type = self._determine_intent_type(query_lower)

        # Calculate urgency
        urgency = self._calculate_urgency(query_lower)

        # Calculate specificity
        specificity = self._calculate_specificity(query)

        # Determine temporal focus
        temporal_focus = self._determine_temporal_focus(query_lower)

        # Predict expected category
        expected_category = self._predict_category(query_lower, intent_type)

        # Extract key entities
        key_entities = self._extract_entities(query)

        return SearchIntent(
            intent_type=intent_type,
            urgency=urgency,
            specificity=specificity,
            temporal_focus=temporal_focus,
            expected_category=expected_category,
            key_entities=key_entities,
        )

    def _determine_intent_type(self, query_lower: str) -> str:
        """Determine the primary intent type"""
        if any(re.search(p, query_lower) for p in self.debug_patterns):
            return "debug"
        elif any(re.search(p, query_lower) for p in self.lookup_patterns):
            return "lookup"
        elif any(re.search(p, query_lower) for p in self.explore_patterns):
            return "explore"
        elif any(re.search(p, query_lower) for p in self.review_patterns):
            return "review"
        elif any(re.search(p, query_lower) for p in self.learn_patterns):
            return "learn"
        else:
            return "lookup"  # Default

    def _calculate_urgency(self, query_lower: str) -> float:
        """Calculate query urgency score"""
        urgency = 0.3  # Base urgency

        for keyword, score in self.urgency_keywords.items():
            if keyword in query_lower:
                urgency = max(urgency, score)

        # Exclamation marks indicate urgency
        urgency += min(query_lower.count("!") * 0.2, 0.4)

        return min(urgency, 1.0)

    def _calculate_specificity(self, query: str) -> float:
        """Calculate how specific the query is"""
        words = query.split()

        # Factors that increase specificity
        specificity = 0.0

        # Word count (more words = more specific, up to a point)
        specificity += min(len(words) / 10, 0.3)

        # Presence of quotes (exact match)
        if '"' in query:
            specificity += 0.3

        # Camel case or snake_case (likely code/technical)
        if any("_" in word or self._is_camelcase(word) for word in words):
            specificity += 0.2

        # Numbers or IDs
        if any(char.isdigit() for char in query):
            specificity += 0.1

        # Technical terms (basic detection)
        tech_terms = [
            "api",
            "function",
            "method",
            "class",
            "variable",
            "endpoint",
            "database",
            "query",
            "index",
        ]
        if any(term in query.lower() for term in tech_terms):
            specificity += 0.1

        return min(specificity, 1.0)

    def _is_camelcase(self, word: str) -> bool:
        """Check if word is camelCase"""
        return (
            len(word) > 1 and word[0].islower() and any(c.isupper() for c in word[1:])
        )

    def _determine_temporal_focus(self, query_lower: str) -> str:
        """Determine temporal focus of the query"""
        for keyword, focus in self.temporal_keywords.items():
            if keyword in query_lower:
                return focus
        return "any"  # Default to no temporal preference

    def _predict_category(self, query_lower: str, intent_type: str) -> Optional[str]:
        """Predict the most likely category"""
        # Category prediction based on keywords and intent
        if intent_type == "debug":
            return "bug"
        elif "decision" in query_lower or "decide" in query_lower:
            return "decision"
        elif "task" in query_lower or "todo" in query_lower:
            return "task"
        elif "idea" in query_lower or "proposal" in query_lower:
            return "idea"
        elif any(
            word in query_lower for word in ["code", "function", "class", "method"]
        ):
            return "code_snippet"
        elif "incident" in query_lower or "outage" in query_lower:
            return "incident"

        return None

    def _extract_entities(self, query: str) -> List[str]:
        """Extract key entities from the query"""
        entities = []

        # Extract quoted strings
        quoted = re.findall(r'"([^"]+)"', query)
        entities.extend(quoted)

        # Extract CamelCase words (likely class/function names)
        words = query.split()
        camelcase = [w for w in words if self._is_camelcase(w)]
        entities.extend(camelcase)

        # Extract snake_case words
        snake_case = re.findall(r"\b\w+_\w+\b", query)
        entities.extend(snake_case)

        # Extract potential file paths
        paths = re.findall(r"[\w/]+\.\w+", query)
        entities.extend(paths)

        return list(set(entities))  # Remove duplicates


class SearchQualityScorer:
    """Advanced scoring system for search results"""

    def __init__(self):
        self.intent_analyzer = SearchIntentAnalyzer()

        # Scoring weights (tunable)
        self.weights = {
            "vector_similarity": 0.3,
            "keyword_match": 0.2,
            "metadata_relevance": 0.15,
            "recency": 0.1,
            "category_match": 0.1,
            "entity_overlap": 0.1,
            "importance": 0.05,
        }

    def score_results(
        self,
        query: str,
        results: List[Dict[str, Any]],
        user_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Score and rerank search results based on quality"""

        # Analyze query intent
        intent = self.intent_analyzer.analyze(query)

        # Score each result
        scored_results = []
        for result in results:
            score = self._calculate_score(query, result, intent, user_context)
            result["quality_score"] = score
            result["scoring_details"] = self._get_scoring_breakdown(
                query, result, intent, user_context
            )
            scored_results.append(result)

        # Sort by quality score
        scored_results.sort(key=lambda x: x["quality_score"], reverse=True)

        return scored_results

    def _calculate_score(
        self,
        query: str,
        result: Dict[str, Any],
        intent: SearchIntent,
        user_context: Optional[Dict[str, Any]],
    ) -> float:
        """Calculate comprehensive quality score"""

        scores = {}

        # 1. Vector similarity (if available)
        scores["vector_similarity"] = result.get("similarity_score", 0.5)

        # 2. Keyword match score
        scores["keyword_match"] = self._keyword_match_score(
            query, result.get("content", "")
        )

        # 3. Metadata relevance
        scores["metadata_relevance"] = self._metadata_relevance_score(
            result, intent, user_context
        )

        # 4. Recency score
        scores["recency"] = self._recency_score(
            result.get("created_at", ""), intent.temporal_focus
        )

        # 5. Category match
        scores["category_match"] = self._category_match_score(
            result.get("category", ""), intent.expected_category
        )

        # 6. Entity overlap
        scores["entity_overlap"] = self._entity_overlap_score(
            result.get("content", ""), intent.key_entities
        )

        # 7. Importance score (based on pins, references, etc.)
        scores["importance"] = self._importance_score(result)

        # Apply intent-based weight adjustments
        adjusted_weights = self._adjust_weights_for_intent(self.weights.copy(), intent)

        # Calculate weighted sum
        total_score = sum(scores[key] * adjusted_weights[key] for key in scores)

        return total_score

    def _keyword_match_score(self, query: str, content: str) -> float:
        """Calculate keyword overlap score"""
        if not content:
            return 0.0

        query_words = set(query.lower().split())
        content_words = set(content.lower().split())

        if not query_words:
            return 0.0

        # Exact phrase match
        if query.lower() in content.lower():
            return 1.0

        # Word overlap
        overlap = len(query_words & content_words)
        score = overlap / len(query_words)

        # Boost for order preservation
        if all(word in content.lower() for word in query.lower().split()):
            score += 0.2

        return min(score, 1.0)

    def _metadata_relevance_score(
        self,
        result: Dict[str, Any],
        intent: SearchIntent,
        user_context: Optional[Dict[str, Any]],
    ) -> float:
        """Score based on metadata relevance"""
        score = 0.5  # Base score

        # Project match
        if user_context and user_context.get("project_id"):
            if result.get("project_id") == user_context["project_id"]:
                score += 0.3

        # Tags relevance
        if result.get("tags") and intent.key_entities:
            tags = result["tags"] if isinstance(result["tags"], list) else []
            tag_overlap = len(set(tags) & set(intent.key_entities))
            score += min(tag_overlap * 0.1, 0.2)

        return min(score, 1.0)

    def _recency_score(self, created_at: str, temporal_focus: str) -> float:
        """Calculate recency score based on temporal focus"""
        if not created_at:
            return 0.5

        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age = (datetime.now() - created.replace(tzinfo=None)).days

            if temporal_focus == "recent":
                # Prefer recent items
                if age <= 1:
                    return 1.0
                elif age <= 7:
                    return 0.8
                elif age <= 30:
                    return 0.6
                else:
                    return 0.3

            elif temporal_focus == "historical":
                # Prefer older items
                if age > 90:
                    return 0.9
                elif age > 30:
                    return 0.7
                elif age > 7:
                    return 0.5
                else:
                    return 0.3

            else:  # 'any'
                # Slight preference for recent
                return max(0.3, 1.0 - (age / 365))

        except Exception as e:
            logger.warning(f"Scoring calculation error: {e}")
            return 0.5

    def _category_match_score(
        self, result_category: str, expected_category: Optional[str]
    ) -> float:
        """Score category match"""
        if not expected_category:
            return 0.5  # Neutral if no expectation

        if result_category == expected_category:
            return 1.0

        # Partial credit for related categories
        related = {
            "bug": ["incident", "task"],
            "task": ["bug", "idea"],
            "decision": ["idea", "task"],
            "code_snippet": ["bug", "task"],
        }

        if result_category in related.get(expected_category, []):
            return 0.7

        return 0.3

    def _entity_overlap_score(
        self, content: str, entities: Optional[List[str]]
    ) -> float:
        """Score based on entity overlap"""
        if not entities or not content:
            return 0.5

        found = sum(1 for entity in entities if entity in content)
        return min(found / len(entities), 1.0)

    def _importance_score(self, result: Dict[str, Any]) -> float:
        """Calculate importance based on various signals"""
        score = 0.5  # Base

        # Category importance
        category_importance = {
            "bug": 0.9,
            "incident": 0.85,
            "decision": 0.8,
            "task": 0.6,
            "code_snippet": 0.5,
            "idea": 0.4,
        }
        score = category_importance.get(result.get("category", ""), score)

        # Boost for specific tags
        important_tags = ["critical", "important", "urgent", "breaking"]
        if result.get("tags"):
            tags = result["tags"] if isinstance(result["tags"], list) else []
            if any(tag in important_tags for tag in tags):
                score += 0.2

        return min(score, 1.0)

    def _adjust_weights_for_intent(
        self, weights: Dict[str, float], intent: SearchIntent
    ) -> Dict[str, float]:
        """Adjust scoring weights based on intent"""

        if intent.intent_type == "debug":
            # For debugging, prioritize recent bugs and exact matches
            weights["recency"] *= 2.0
            weights["category_match"] *= 1.5
            weights["keyword_match"] *= 1.5

        elif intent.intent_type == "explore":
            # For exploration, prioritize similarity and variety
            weights["vector_similarity"] *= 1.5
            weights["metadata_relevance"] *= 0.5

        elif intent.intent_type == "review":
            # For review, prioritize recency and importance
            weights["recency"] *= 2.0
            weights["importance"] *= 1.5

        elif intent.intent_type == "lookup":
            # For lookup, prioritize exact matches
            weights["keyword_match"] *= 2.0
            weights["entity_overlap"] *= 1.5

        # Normalize weights to sum to 1
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}

    def _get_scoring_breakdown(
        self,
        query: str,
        result: Dict[str, Any],
        intent: SearchIntent,
        user_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Get detailed scoring breakdown for transparency"""
        return {
            "intent_type": intent.intent_type,
            "urgency": intent.urgency,
            "specificity": intent.specificity,
            "component_scores": {
                "vector_similarity": result.get("similarity_score", 0.5),
                "keyword_match": self._keyword_match_score(
                    query, result.get("content", "")
                ),
                "recency": self._recency_score(
                    result.get("created_at", ""), intent.temporal_focus
                ),
                "category_match": self._category_match_score(
                    result.get("category", ""), intent.expected_category
                ),
            },
        }


class RelevanceFeedback:
    """Track and learn from user feedback on search results"""

    def __init__(self, storage_path: str = "search_feedback.json"):
        self.storage_path = storage_path
        self.feedback_data = self._load_feedback()

    def _load_feedback(self) -> Dict[str, Any]:
        """Load feedback history"""
        try:
            with open(self.storage_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to record feedback: {e}")
            return {"queries": {}, "click_through": {}, "result_ratings": {}}

    def record_click(
        self,
        query: str,
        result_id: str,
        position: int,
        dwell_time: Optional[float] = None,
    ) -> None:
        """Record user click on a result"""
        if query not in self.feedback_data["click_through"]:
            self.feedback_data["click_through"][query] = []

        self.feedback_data["click_through"][query].append(
            {
                "result_id": result_id,
                "position": position,
                "dwell_time": dwell_time,
                "timestamp": datetime.now().isoformat(),
            }
        )

        self._save_feedback()

    def record_rating(
        self,
        query: str,
        result_id: str,
        rating: float,  # 0.0 - 1.0
    ) -> None:
        """Record explicit user rating"""
        if query not in self.feedback_data["result_ratings"]:
            self.feedback_data["result_ratings"][query] = {}

        self.feedback_data["result_ratings"][query][result_id] = {
            "rating": rating,
            "timestamp": datetime.now().isoformat(),
        }

        self._save_feedback()

    def get_result_boost(self, query: str, result_id: str) -> float:
        """Get relevance boost based on feedback history"""
        boost = 0.0

        # Check click-through rate
        if query in self.feedback_data["click_through"]:
            clicks = self.feedback_data["click_through"][query]
            result_clicks = [c for c in clicks if c["result_id"] == result_id]

            if result_clicks:
                # More clicks = higher boost
                boost += min(len(result_clicks) * 0.1, 0.3)

                # Consider dwell time
                avg_dwell = np.mean(
                    [
                        c["dwell_time"]
                        for c in result_clicks
                        if c["dwell_time"] is not None
                    ]
                )
                if avg_dwell > 30:  # 30 seconds
                    boost += 0.2

        # Check explicit ratings
        if query in self.feedback_data["result_ratings"]:
            if result_id in self.feedback_data["result_ratings"][query]:
                rating = self.feedback_data["result_ratings"][query][result_id][
                    "rating"
                ]
                boost += rating * 0.5

        return min(boost, 1.0)

    def _save_feedback(self):
        """Save feedback to disk"""
        try:
            with open(self.storage_path, "w") as f:
                json.dump(self.feedback_data, f, indent=2)
        except Exception as e:
            print(f"Failed to save feedback: {e}")


class DynamicEmbeddingSelector:
    """Select optimal embedding model based on query characteristics"""

    def __init__(self):
        self.model_profiles = {
            "all-MiniLM-L6-v2": {
                "dimensions": 384,
                "speed": "fast",
                "quality": "good",
                "best_for": ["general", "english", "short"],
            },
            "all-mpnet-base-v2": {
                "dimensions": 768,
                "speed": "medium",
                "quality": "excellent",
                "best_for": ["technical", "detailed", "english"],
            },
            "multilingual-e5-small": {
                "dimensions": 384,
                "speed": "fast",
                "quality": "good",
                "best_for": ["multilingual", "mixed", "short"],
            },
            "multilingual-e5-large": {
                "dimensions": 1024,
                "speed": "slow",
                "quality": "excellent",
                "best_for": ["multilingual", "complex", "detailed"],
            },
        }

    def select_model(
        self, query: str, intent: SearchIntent, performance_mode: str = "balanced"
    ) -> str:
        """Select optimal embedding model for the query"""

        # Detect language characteristics
        has_non_ascii = any(ord(char) > 127 for char in query)
        is_technical = any(
            term in query.lower()
            for term in ["api", "function", "class", "error", "bug"]
        )
        is_long = len(query.split()) > 10

        # Performance mode preferences
        if performance_mode == "fast":
            # Prefer fast models
            if has_non_ascii:
                return "multilingual-e5-small"
            return "all-MiniLM-L6-v2"

        elif performance_mode == "quality":
            # Prefer quality models
            if has_non_ascii:
                return "multilingual-e5-large"
            elif is_technical:
                return "all-mpnet-base-v2"
            return "all-MiniLM-L6-v2"

        else:  # balanced
            # Balance speed and quality
            if has_non_ascii and is_long:
                return "multilingual-e5-large"
            elif has_non_ascii:
                return "multilingual-e5-small"
            elif is_technical and intent.specificity > 0.7:
                return "all-mpnet-base-v2"
            else:
                return "all-MiniLM-L6-v2"
