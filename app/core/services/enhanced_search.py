"""
Enhanced Search Service with Quality Optimization
품질 최적화가 적용된 향상된 검색 서비스
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from .search import SearchService
from .search_quality import (
    SearchIntentAnalyzer,
    SearchQualityScorer,
    RelevanceFeedback,
    DynamicEmbeddingSelector
)
from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResponse, SearchResult
from .cache_manager import get_cache_manager

logger = logging.getLogger(__name__)


class EnhancedSearchService(SearchService):
    """Enhanced search with quality optimization"""

    def __init__(
        self,
        db: Database,
        embedding_service: EmbeddingService,
        enable_quality_scoring: bool = True,
        enable_feedback: bool = True,
        enable_dynamic_embedding: bool = False
    ):
        """
        Initialize enhanced search service

        Args:
            db: Database instance
            embedding_service: Embedding service
            enable_quality_scoring: Enable quality-based reranking
            enable_feedback: Enable relevance feedback learning
            enable_dynamic_embedding: Enable dynamic model selection
        """
        super().__init__(db, embedding_service)

        self.enable_quality_scoring = enable_quality_scoring
        self.enable_feedback = enable_feedback
        self.enable_dynamic_embedding = enable_dynamic_embedding

        # Initialize quality components
        self.intent_analyzer = SearchIntentAnalyzer()
        self.quality_scorer = SearchQualityScorer()
        self.feedback_tracker = RelevanceFeedback() if enable_feedback else None
        self.embedding_selector = DynamicEmbeddingSelector() if enable_dynamic_embedding else None

        logger.info(f"Enhanced search initialized - Quality: {enable_quality_scoring}, "
                   f"Feedback: {enable_feedback}, Dynamic: {enable_dynamic_embedding}")

    async def search(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
        sort_by: str = "relevance",  # Changed default to relevance
        sort_direction: str = "desc",
        recency_weight: float = 0.0,
        search_mode: str = "smart",  # New: smart mode
        performance_mode: str = "balanced",  # fast/balanced/quality
        min_quality_score: float = 0.3  # Minimum quality threshold
    ) -> SearchResponse:
        """
        Enhanced search with quality optimization

        Args:
            query: Search query
            project_id: Project filter
            category: Category filter
            source: Source filter
            tag: Tag filter
            limit: Result limit
            offset: Pagination offset
            sort_by: Sort field (relevance/created_at/quality)
            sort_direction: Sort direction
            recency_weight: Recency importance (0.0-1.0)
            search_mode: Search mode (smart/hybrid/exact/semantic/fuzzy)
            performance_mode: Performance vs quality trade-off
            min_quality_score: Minimum quality score threshold

        Returns:
            Enhanced SearchResponse with quality scores
        """
        start_time = datetime.now()

        # Analyze query intent
        intent = self.intent_analyzer.analyze(query)
        logger.info(f"Query intent: {intent.intent_type}, "
                   f"urgency: {intent.urgency:.2f}, "
                   f"specificity: {intent.specificity:.2f}")

        # Auto-adjust parameters based on intent
        if search_mode == "smart":
            search_mode, limit, category = self._auto_adjust_params(
                intent, search_mode, limit, category
            )

        # Select optimal embedding model if enabled
        if self.enable_dynamic_embedding and self.embedding_selector:
            model_name = self.embedding_selector.select_model(
                query, intent, performance_mode
            )
            if model_name != self.embedding_service.model_name:
                logger.info(f"Switching to model: {model_name}")
                # Note: Actual model switching would require reinitialization
                # This is a placeholder for the concept

        # Get base results from parent class
        base_response = await super().search(
            query=query,
            project_id=project_id,
            category=category or intent.expected_category,
            source=source,
            tag=tag,
            limit=limit * 2 if self.enable_quality_scoring else limit,  # Get extra for filtering
            offset=offset,
            sort_by="created_at" if sort_by == "relevance" else sort_by,
            sort_direction=sort_direction,
            recency_weight=recency_weight,
            search_mode=search_mode if search_mode != "smart" else "hybrid"
        )

        # Apply quality scoring if enabled
        if self.enable_quality_scoring and base_response.results:
            # Prepare user context
            user_context = {
                'project_id': project_id,
                'current_time': datetime.now().isoformat(),
                'performance_mode': performance_mode
            }

            # Convert results to dicts for scoring
            results_dict = [
                {
                    'id': r.id,
                    'content': r.content,
                    'category': r.category,
                    'project_id': r.project_id,
                    'tags': r.tags,
                    'created_at': r.created_at,
                    'similarity_score': r.similarity_score,
                    'source': r.source
                }
                for r in base_response.results
            ]

            # Score and rerank
            scored_results = self.quality_scorer.score_results(
                query, results_dict, user_context
            )

            # Apply feedback boost if enabled
            if self.enable_feedback and self.feedback_tracker:
                for result in scored_results:
                    feedback_boost = self.feedback_tracker.get_result_boost(
                        query, result['id']
                    )
                    result['quality_score'] += feedback_boost * 0.2
                    result['feedback_boost'] = feedback_boost

            # Filter by minimum quality score
            filtered_results = [
                r for r in scored_results
                if r.get('quality_score', 0) >= min_quality_score
            ]

            # Sort by chosen criteria
            if sort_by == "relevance" or sort_by == "quality":
                filtered_results.sort(
                    key=lambda x: x.get('quality_score', 0),
                    reverse=True
                )
            elif sort_by == "created_at":
                filtered_results.sort(
                    key=lambda x: x.get('created_at', ''),
                    reverse=(sort_direction == "desc")
                )

            # Limit results
            filtered_results = filtered_results[:limit]

            # Convert back to SearchResult objects
            enhanced_results = []
            for r in filtered_results:
                result = SearchResult(
                    id=r['id'],
                    content=r['content'],
                    category=r['category'],
                    project_id=r['project_id'],
                    tags=r['tags'],
                    created_at=r['created_at'],
                    updated_at=r.get('updated_at', r['created_at']),
                    similarity_score=r.get('quality_score', r.get('similarity_score', 0)),
                    source=r.get('source', 'unknown')
                )
                # Add quality metadata
                result.quality_score = r.get('quality_score', 0)
                result.scoring_details = r.get('scoring_details', {})
                enhanced_results.append(result)

            # Update response
            base_response.results = enhanced_results

        # Add search metadata
        search_time = (datetime.now() - start_time).total_seconds()
        base_response.metadata = {
            'search_time': search_time,
            'intent': {
                'type': intent.intent_type,
                'urgency': intent.urgency,
                'specificity': intent.specificity,
                'temporal_focus': intent.temporal_focus
            },
            'quality_scoring_enabled': self.enable_quality_scoring,
            'feedback_enabled': self.enable_feedback,
            'performance_mode': performance_mode,
            'auto_adjusted': search_mode == "smart"
        }

        # Log search analytics
        self._log_search_analytics(query, intent, base_response, search_time)

        return base_response

    def _auto_adjust_params(
        self,
        intent: Any,
        search_mode: str,
        limit: int,
        category: Optional[str]
    ) -> tuple:
        """Auto-adjust search parameters based on intent"""

        # Adjust search mode
        if intent.intent_type == 'debug':
            search_mode = 'exact'  # Prefer exact matches for debugging
        elif intent.intent_type == 'explore':
            search_mode = 'semantic'  # Prefer semantic for exploration
        elif intent.specificity > 0.7:
            search_mode = 'exact'  # High specificity → exact match
        else:
            search_mode = 'hybrid'  # Default to hybrid

        # Adjust limit based on urgency and specificity
        if intent.urgency > 0.8:
            limit = min(limit, 5)  # Urgent → fewer but better results
        elif intent.specificity > 0.8:
            limit = min(limit, 3)  # Very specific → few results expected
        elif intent.intent_type == 'explore':
            limit = max(limit, 10)  # Exploration → more results

        # Use predicted category if not specified
        if not category and intent.expected_category:
            category = intent.expected_category

        return search_mode, limit, category

    def _log_search_analytics(
        self,
        query: str,
        intent: Any,
        response: SearchResponse,
        search_time: float
    ):
        """Log search analytics for monitoring"""
        logger.info(f"Search Analytics - "
                   f"Query: '{query[:50]}...', "
                   f"Intent: {intent.intent_type}, "
                   f"Results: {len(response.results)}, "
                   f"Time: {search_time:.3f}s, "
                   f"Avg Quality: {self._avg_quality_score(response.results):.2f}")

    def _avg_quality_score(self, results: List[SearchResult]) -> float:
        """Calculate average quality score"""
        if not results:
            return 0.0

        scores = [
            getattr(r, 'quality_score', r.similarity_score)
            for r in results
        ]
        return sum(scores) / len(scores) if scores else 0.0

    async def record_feedback(
        self,
        query: str,
        result_id: str,
        feedback_type: str,
        value: Any
    ):
        """Record user feedback for result improvement"""
        if not self.enable_feedback or not self.feedback_tracker:
            return

        if feedback_type == 'click':
            self.feedback_tracker.record_click(
                query, result_id,
                position=value.get('position', 0),
                dwell_time=value.get('dwell_time')
            )
        elif feedback_type == 'rating':
            self.feedback_tracker.record_rating(
                query, result_id,
                rating=value
            )

        logger.info(f"Feedback recorded - Query: '{query[:30]}...', "
                   f"Result: {result_id[:8]}, Type: {feedback_type}")

    async def get_search_suggestions(
        self,
        partial_query: str,
        limit: int = 5
    ) -> List[str]:
        """Get search suggestions based on query history"""
        suggestions = []

        # Get recent successful queries
        # This would typically query a search history table
        # For now, return common patterns

        common_patterns = [
            f"{partial_query} bug",
            f"{partial_query} error",
            f"{partial_query} implementation",
            f"{partial_query} fix",
            f"{partial_query} optimization"
        ]

        return [p for p in common_patterns if len(p) < 50][:limit]

    async def explain_results(
        self,
        query: str,
        results: List[SearchResult]
    ) -> Dict[str, Any]:
        """Explain why certain results were returned"""
        intent = self.intent_analyzer.analyze(query)

        explanations = []
        for i, result in enumerate(results[:3]):  # Explain top 3
            explanation = {
                'position': i + 1,
                'id': result.id,
                'reasons': []
            }

            # Quality score explanation
            if hasattr(result, 'quality_score'):
                if result.quality_score > 0.8:
                    explanation['reasons'].append("High quality match")
                elif result.quality_score > 0.6:
                    explanation['reasons'].append("Good quality match")

            # Category match
            if hasattr(result, 'category'):
                if result.category == intent.expected_category:
                    explanation['reasons'].append(f"Matches expected category: {result.category}")

            # Recency
            if hasattr(result, 'created_at'):
                try:
                    created = datetime.fromisoformat(result.created_at.replace('Z', '+00:00'))
                    age = (datetime.now() - created.replace(tzinfo=None)).days
                    if age <= 7:
                        explanation['reasons'].append("Recently created")
                except:
                    pass

            explanations.append(explanation)

        return {
            'query_intent': {
                'type': intent.intent_type,
                'focus': intent.temporal_focus,
                'expected_category': intent.expected_category
            },
            'result_explanations': explanations
        }


# Example usage patterns
"""
# Initialize enhanced search
enhanced_search = EnhancedSearchService(
    db=db,
    embedding_service=embedding_service,
    enable_quality_scoring=True,
    enable_feedback=True,
    enable_dynamic_embedding=True
)

# Smart search (auto-adjusts parameters)
results = await enhanced_search.search(
    query="urgent login bug fix",
    search_mode="smart",
    performance_mode="balanced",
    min_quality_score=0.5
)

# Record user feedback
await enhanced_search.record_feedback(
    query="urgent login bug fix",
    result_id=results.results[0].id,
    feedback_type="click",
    value={"position": 1, "dwell_time": 45.2}
)

# Get search suggestions
suggestions = await enhanced_search.get_search_suggestions("auth")

# Explain why results were returned
explanation = await enhanced_search.explain_results(
    query="urgent login bug fix",
    results=results.results
)
"""