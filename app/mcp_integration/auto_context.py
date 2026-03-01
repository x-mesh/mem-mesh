"""
MCP 자동 컨텍스트 통합
Automatic context detection for MCP
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# 상위 디렉토리를 path에 추가
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.core.services.project_detector import ProjectDetector


class MCPAutoContext:
    """MCP용 자동 컨텍스트"""

    def __init__(self):
        self.detector = ProjectDetector()
        self.current_project = None
        self.context_cache = {}

    def get_current_project(self) -> str:
        """
        현재 프로젝트 가져오기

        우선순위:
        1. 환경변수 MEM_MESH_PROJECT
        2. 현재 디렉토리명
        3. Git 리포지토리명
        4. 상위 디렉토리명
        """
        # 1. 환경변수 확인
        if "MEM_MESH_PROJECT" in os.environ:
            return os.environ["MEM_MESH_PROJECT"]

        # 2. 현재 디렉토리 기반 감지
        project = self.detector.detect_from_path()
        if project:
            return project

        # 3. 기본값: 현재 디렉토리명
        current_dir = os.path.basename(os.getcwd())

        # kiro로 시작하면 None 반환 (노이즈 방지)
        if current_dir.startswith("kiro"):
            return None

        return current_dir

    def build_search_query(self, query: str, **kwargs) -> Dict[str, Any]:
        """
        검색 쿼리 자동 구성

        Args:
            query: 검색어
            **kwargs: 추가 옵션

        Returns:
            최적화된 검색 파라미터
        """
        # 현재 프로젝트
        project = self.get_current_project()

        # 기본 파라미터
        params = {
            "query": query,
            "limit": kwargs.get("limit", 5),
            "min_score": kwargs.get("min_score", 0.3),
        }

        # 프로젝트 필터 추가
        if project:
            params["project_filter"] = project

        # 카테고리 힌트
        if "category" in kwargs:
            params["category"] = kwargs["category"]

        # 태그
        if "tags" in kwargs:
            params["tags"] = kwargs["tags"]

        # 노이즈 필터 설정
        params["noise_filter"] = {
            "aggressive": True,
            "exclude_projects": ["kiro-*", "test-*", "tmp-*"],
            "min_content_length": 50,
        }

        return params

    def get_prompt_context(self) -> str:
        """
        MCP 프롬프트용 컨텍스트 문자열 생성
        """
        project = self.get_current_project()
        current_dir = os.path.basename(os.getcwd())

        prompt = f"""
Current Context:
- Working Directory: {current_dir}
- Project: {project or 'auto-detect'}
- Path: {os.getcwd()}

Search Configuration:
- Auto project filter: {project or 'none'}
- Max results: 5
- Noise filter: enabled (excluding kiro-*, test-*, tmp-*)
- Min relevance score: 0.3

When searching mem-mesh:
1. Project '{project}' will be automatically applied as filter
2. Single word queries will be expanded automatically
3. Results are limited to 5 most relevant items
4. Noise from test/temporary projects is filtered out
""".strip()

        return prompt


def get_mcp_search_params(query: str, **kwargs) -> Dict[str, Any]:
    """
    MCP 검색 파라미터 자동 생성 (간편 함수)

    사용 예:
    params = get_mcp_search_params("토큰 최적화")
    """
    auto_context = MCPAutoContext()
    return auto_context.build_search_query(query, **kwargs)


def get_current_project_id() -> Optional[str]:
    """현재 프로젝트 ID 가져오기 (간편 함수)"""
    auto_context = MCPAutoContext()
    return auto_context.get_current_project()


# CLI 테스트용
if __name__ == "__main__":
    import json

    auto_context = MCPAutoContext()

    print("=" * 60)
    print("🔍 MCP 자동 컨텍스트 테스트")
    print("=" * 60)

    # 현재 프로젝트
    project = auto_context.get_current_project()
    print(f"\n현재 프로젝트: {project}")
    print(f"현재 디렉토리: {os.getcwd()}")

    # 검색 파라미터 생성
    test_queries = ["토큰", "검색 최적화", "캐시 관리"]

    for query in test_queries:
        params = auto_context.build_search_query(query)
        print(f"\n검색어: '{query}'")
        print(f"파라미터: {json.dumps(params, indent=2, ensure_ascii=False)}")

    # 프롬프트 컨텍스트
    print("\n" + "=" * 60)
    print("MCP 프롬프트 컨텍스트:")
    print("=" * 60)
    print(auto_context.get_prompt_context())
