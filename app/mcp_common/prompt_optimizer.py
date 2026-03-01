"""
MCP Prompt Optimizer
Reduces token usage in IDE <-> mem-mesh communication
"""

import json
from typing import Any, Dict, List, Optional


class PromptOptimizer:
    """
    Optimizes prompts and responses for minimal token usage
    while maintaining context quality
    """

    # 시스템 프롬프트 템플릿 (IDE에서 사용)
    SYSTEM_PROMPTS = {
        "minimal": """mem-mesh MCP tools:
- search(q, limit=3): Find memories
- context(id, depth=1): Get related
- add(content): Save memory
- batch_operations(ops): Batch exec
Use minimal queries, cache results.""",
        "standard": """You have access to mem-mesh memory system via MCP:

SEARCH STRATEGY:
1. Start with broad search (limit=3)
2. Use context() for deep dive
3. Cache and reuse results
4. Batch operations when possible

TOOLS:
- search: Query memories (cache for 5min)
- context: Get related memories (use sparingly)
- add: Save important info
- batch_*: Use for multiple ops

EFFICIENCY:
- Prefer exact matches over semantic
- Use project_id filter when known
- Limit results to essentials only""",
        "advanced": """# mem-mesh Memory System (MCP)

## Efficient Usage Pattern
```
1. Initial: search(query, limit=3)
2. If needed: context(memory_id, depth=1)
3. Save: add(content, category)
4. Batch: batch_operations([...])
```

## Token Optimization Rules
1. SEARCH ONCE: Cache results during conversation
2. NARROW SCOPE: Use filters (project_id, category)
3. SHALLOW FIRST: Start with depth=1, increase if needed
4. BATCH ALWAYS: Group operations
5. SUMMARIZE: Request compressed format

## Response Formats
- "compact": IDs + titles only
- "standard": Include content snippets
- "full": Complete memory (avoid unless necessary)

## Categories Priority
High value: bug > decision > code_snippet > task > idea
Use category filter for focused searches.""",
    }

    @staticmethod
    def generate_search_prompt(
        task: str, context: Dict[str, Any], mode: str = "efficient"
    ) -> str:
        """
        Generate optimized search prompt for minimal tokens
        """
        if mode == "minimal":
            # 극도로 압축된 프롬프트
            return f"Q:{task[:50]}"

        elif mode == "efficient":
            # 효율적인 프롬프트 (권장)
            project = context.get("project_id", "")
            category_hint = PromptOptimizer._infer_category(task)

            return f"""TASK: {task[:100]}
{f"PROJECT: {project}" if project else ""}
{f"CATEGORY: {category_hint}" if category_hint else ""}
LIMIT: 3"""

        else:  # detailed
            return f"""SEARCH REQUEST
Task: {task}
Project: {context.get("project_id", "any")}
Category: {PromptOptimizer._infer_category(task) or "auto"}
Depth: {context.get("depth", 1)}
Format: compact

Return only essential memories for this task."""

    @staticmethod
    def _infer_category(task: str) -> Optional[str]:
        """Infer category from task description"""
        task_lower = task.lower()

        if any(word in task_lower for word in ["bug", "error", "fix", "issue"]):
            return "bug"
        elif any(word in task_lower for word in ["decide", "decision", "choice"]):
            return "decision"
        elif any(word in task_lower for word in ["code", "function", "implement"]):
            return "code_snippet"
        elif any(word in task_lower for word in ["task", "todo", "need"]):
            return "task"
        elif any(word in task_lower for word in ["idea", "consider", "maybe"]):
            return "idea"

        return None

    @staticmethod
    def compress_search_results(
        results: List[Dict[str, Any]], max_tokens: int = 500, format: str = "compact"
    ) -> str:
        """
        Compress search results for minimal token usage
        """
        if not results:
            return "No results"

        if format == "minimal":
            # 극도로 압축: ID와 점수만
            lines = []
            for r in results[:5]:
                lines.append(f"{r['id'][:8]}:{r.get('score', 0):.2f}")
            return " ".join(lines)

        elif format == "compact":
            # 압축: ID, 카테고리, 첫 50자
            output = []
            for i, r in enumerate(results[:5], 1):
                content = r.get("content", "")[:50]
                output.append(f"{i}. [{r.get('category', 'unknown')}] {content}...")
            return "\n".join(output)

        elif format == "standard":
            # 표준: 구조화된 요약
            output = []
            for i, r in enumerate(results[:3], 1):
                output.append(f"""
{i}. Memory {r["id"][:8]}
   Category: {r.get("category", "unknown")}
   Content: {r.get("content", "")[:100]}...
   Score: {r.get("score", 0):.2f}""")
            return "\n".join(output)

        else:  # full
            # 전체 (피하는 것이 좋음)
            return json.dumps(results[:2], indent=2)

    @staticmethod
    def compress_context_response(
        context_data: Dict[str, Any], max_tokens: int = 800
    ) -> Dict[str, Any]:
        """
        Compress context response for minimal tokens
        """
        if not context_data:
            return {"summary": "No context"}

        primary = context_data.get("primary_memory", {})
        related = context_data.get("related_memories", [])

        compressed = {
            "primary": {
                "id": primary.get("id", "")[:8],
                "category": primary.get("category"),
                "summary": primary.get("content", "")[:100],
            },
            "related_count": len(related),
            "related_summary": [],
        }

        # 관련 메모리 요약 (최대 3개)
        for mem in related[:3]:
            compressed["related_summary"].append(
                {
                    "cat": mem.get("category", "unk")[:4],  # 카테고리 축약
                    "sim": round(mem.get("similarity_score", 0), 2),
                    "hint": mem.get("content", "")[:30],
                }
            )

        return compressed

    @staticmethod
    def generate_batch_prompt(operations: List[str]) -> str:
        """
        Generate efficient batch operation prompt
        """
        return f"""BATCH[{len(operations)}]:
{chr(10).join(f"{i + 1}.{op[:50]}" for i, op in enumerate(operations[:10]))}
{"..." if len(operations) > 10 else ""}"""

    @staticmethod
    def format_for_llm_context(
        memories: List[Dict[str, Any]],
        max_tokens: int = 2000,
        priority: str = "relevance",
    ) -> str:
        """
        Format memories for inclusion in LLM context window
        """
        if not memories:
            return "[No relevant memories]"

        # 우선순위별 정렬
        if priority == "relevance":
            sorted_memories = sorted(
                memories, key=lambda x: x.get("similarity_score", 0), reverse=True
            )
        elif priority == "recency":
            sorted_memories = sorted(
                memories, key=lambda x: x.get("created_at", ""), reverse=True
            )
        else:  # category
            category_priority = {
                "bug": 5,
                "decision": 4,
                "code_snippet": 3,
                "task": 2,
                "idea": 1,
            }
            sorted_memories = sorted(
                memories,
                key=lambda x: category_priority.get(x.get("category", ""), 0),
                reverse=True,
            )

        # 토큰 예산에 맞춰 압축
        output = ["[MEMORY CONTEXT]"]
        token_count = 50  # 헤더 예상 토큰

        for i, mem in enumerate(sorted_memories, 1):
            # 각 메모리를 압축 형식으로
            if token_count > max_tokens * 0.8:  # 80% 도달 시 중단
                output.append(f"... +{len(sorted_memories) - i + 1} more")
                break

            # 카테고리별 다른 압축 수준
            category = mem.get("category", "unknown")
            if category in ["bug", "decision"]:
                # 중요: 더 많은 내용 포함
                snippet = mem.get("content", "")[:150]
                memory_text = f"\n{i}. [{category}] {snippet}"
            else:
                # 덜 중요: 매우 압축
                snippet = mem.get("content", "")[:50]
                memory_text = f"\n{i}. {snippet[:30]}..."

            # 예상 토큰 수 계산 (대략 4자 = 1토큰)
            estimated_tokens = len(memory_text) / 4
            if token_count + estimated_tokens > max_tokens:
                break

            output.append(memory_text)
            token_count += estimated_tokens

        return "\n".join(output)


class SmartMCPClient:
    """
    Smart MCP client that optimizes token usage
    """

    def __init__(self, optimizer: PromptOptimizer):
        self.optimizer = optimizer
        self.cache = {}  # 로컬 캐시
        self.last_search = None
        self.token_budget = 4000  # 기본 토큰 예산

    async def smart_search(
        self, query: str, use_cache: bool = True, compress: bool = True
    ) -> str:
        """
        Smart search with caching and compression
        """
        # 캐시 확인
        cache_key = f"search:{query[:50]}"
        if use_cache and cache_key in self.cache:
            return f"[CACHED] {self.cache[cache_key]}"

        # 검색 수행 (MCP 도구 호출)
        results = await self._mcp_search(query, limit=3)

        # 압축
        if compress:
            compressed = self.optimizer.compress_search_results(
                results, max_tokens=500, format="compact"
            )
        else:
            compressed = json.dumps(results)

        # 캐시 저장
        self.cache[cache_key] = compressed
        self.last_search = results

        return compressed

    async def smart_context(self, memory_id: str, max_depth: int = 1) -> str:
        """
        Smart context retrieval with progressive depth
        """
        # 얕은 깊이부터 시작
        context = await self._mcp_context(memory_id, depth=1)

        # 압축
        compressed = self.optimizer.compress_context_response(context, max_tokens=800)

        # 필요시에만 깊이 증가
        if len(compressed.get("related_summary", [])) < 2 and max_depth > 1:
            context = await self._mcp_context(memory_id, depth=2)
            compressed = self.optimizer.compress_context_response(
                context, max_tokens=800
            )

        return json.dumps(compressed)

    async def _mcp_search(self, query: str, limit: int) -> List[Dict]:
        """Placeholder for actual MCP search call"""
        raise NotImplementedError(
            "MCP search integration not yet implemented - requires MCP client context"
        )

    async def _mcp_context(self, memory_id: str, depth: int) -> Dict:
        """Placeholder for actual MCP context call"""
        raise NotImplementedError(
            "MCP context integration not yet implemented - requires MCP client context"
        )


# 사용 예시 프롬프트 템플릿
EXAMPLE_PROMPTS = {
    "efficient_task": """
I need to {task_description}.

Search for relevant memories:
1. Use search("{keywords}", limit=3)
2. If found, check context(memory_id, depth=1) for the most relevant one
3. Only retrieve more if essential

Focus on {category} category if applicable.
""",
    "batch_learning": """
I learned several things. Save them efficiently:

Use batch_operations([
  {"type": "add", "content": "{lesson1}", "category": "decision"},
  {"type": "add", "content": "{lesson2}", "category": "idea"},
  {"type": "add", "content": "{lesson3}", "category": "task"}
])

This saves tokens vs individual adds.
""",
    "context_aware_search": """
Working on: {current_project}

Search with project filter:
search("{query}", project_id="{current_project}", limit=3)

This returns only relevant results, reducing tokens.
""",
    "progressive_exploration": """
Exploring: {topic}

Step 1: search("{topic}", limit=3, format="compact")
Step 2: If promising, context(best_id, depth=1)
Step 3: Only if needed, increase depth or search related

This progressive approach minimizes token usage.
""",
}
