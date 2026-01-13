#!/usr/bin/env python3
"""
대화형 검색 도구

다양한 임베딩 모델을 선택하여 실시간으로 검색 결과를 확인할 수 있는 도구입니다.
"""

import asyncio
import argparse
import logging
import time
from pathlib import Path
from typing import Optional

# 프로젝트 루트를 path에 추가
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.embeddings.service import EmbeddingService, MODEL_DIMENSIONS
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import SearchParams

# 로깅 설정
logger = logging.getLogger(__name__)


class InteractiveSearchTool:
    """대화형 검색 도구 클래스"""
    
    # 지원되는 모델 목록
    SUPPORTED_MODELS = [
        # 소형 모델 (빠른 속도)
        "all-MiniLM-L6-v2",
        "paraphrase-MiniLM-L6-v2", 
        "multi-qa-MiniLM-L6-cos-v1",
        "intfloat/multilingual-e5-small",
        
        # 중형 모델 (균형)
        "all-MiniLM-L12-v2",
        "distiluse-base-multilingual-cased-v2",
        "intfloat/multilingual-e5-base",
        
        # 대형 모델 (높은 정확도)
        "all-mpnet-base-v2",
        "multi-qa-mpnet-base-cos-v1",
        "intfloat/multilingual-e5-large",
    ]
    
    def __init__(self, db_path: str = "data/memories.db", verbose: int = 0):
        self.db_path = db_path
        self.verbose = verbose
        self.storage = None
        self.current_model = None
        
        # 로깅 레벨 설정
        if verbose >= 2:
            logging.basicConfig(level=logging.DEBUG)
        elif verbose >= 1:
            logging.basicConfig(level=logging.INFO)
        else:
            logging.basicConfig(level=logging.WARNING)
    
    async def initialize(self):
        """검색 도구 초기화"""
        print("🔍 대화형 검색 도구 초기화 중...")
        
        self.storage = DirectStorageBackend(self.db_path)
        await self.storage.initialize()
        
        # 현재 데이터베이스 모델 정보 확인
        current_db_model = await self.storage.db.get_embedding_metadata("embedding_model")
        current_db_dim_str = await self.storage.db.get_embedding_metadata("embedding_dimension")
        current_db_dim = int(current_db_dim_str) if current_db_dim_str else None
        
        current_service_model = self.storage.embedding_service.model_name
        current_service_dim = self.storage.embedding_service.dimension
        
        print("✅ 초기화 완료!")
        if self.verbose >= 1:
            print(f"   데이터베이스: {self.db_path}")
            print(f"   서비스 모델: {current_service_model} ({current_service_dim}차원)")
            if current_db_model:
                print(f"   DB 저장 모델: {current_db_model} ({current_db_dim}차원)")
                
                if current_db_model != current_service_model:
                    print(f"   ⚠️  모델 불일치 감지!")
                    if current_db_dim != current_service_dim:
                        print(f"   ❌ 차원도 다름 - 벡터 검색 부정확할 수 있음")
                    else:
                        print(f"   ⚠️  같은 차원이지만 다른 모델 - 검색 부정확할 수 있음")
                else:
                    print(f"   ✅ 모델 일치")
            else:
                print(f"   ℹ️  DB 모델 정보 없음 (새 데이터베이스?)")
    
    def display_available_models(self):
        """사용 가능한 모델 목록 표시"""
        print("\n📋 사용 가능한 임베딩 모델:")
        print("-" * 60)
        
        for i, model in enumerate(self.SUPPORTED_MODELS, 1):
            dimension = MODEL_DIMENSIONS.get(model, "unknown")
            model_type = self._get_model_type(model)
            print(f"{i:2d}. {model:<35} ({dimension}차원, {model_type})")
        
        print("-" * 60)
    
    def _get_model_type(self, model: str) -> str:
        """모델 타입 분류"""
        if any(x in model.lower() for x in ["minilm-l6", "e5-small"]):
            return "소형"
        elif any(x in model.lower() for x in ["minilm-l12", "e5-base", "distiluse"]):
            return "중형"
        elif any(x in model.lower() for x in ["mpnet", "e5-large"]):
            return "대형"
        else:
            return "기타"
    
    async def switch_model(self, model_name: str) -> bool:
        """모델 전환"""
        if model_name not in self.SUPPORTED_MODELS:
            print(f"❌ 지원되지 않는 모델: {model_name}")
            return False
        
        try:
            print(f"🔄 모델 전환 중: {model_name}")
            start_time = time.time()
            
            # 현재 데이터베이스 모델 정보 확인
            current_db_model = await self.storage.db.get_embedding_metadata("embedding_model")
            current_db_dim_str = await self.storage.db.get_embedding_metadata("embedding_dimension")
            current_db_dim = int(current_db_dim_str) if current_db_dim_str else None
            
            # 새 임베딩 서비스 생성
            new_service = EmbeddingService(model_name, preload=True)
            
            # 모델 호환성 검사
            if current_db_model and current_db_model != model_name:
                print(f"⚠️  모델 불일치 경고!")
                print(f"   데이터베이스 모델: {current_db_model} ({current_db_dim}차원)")
                print(f"   새로운 모델: {model_name} ({new_service.dimension}차원)")
                
                if current_db_dim != new_service.dimension:
                    print(f"❌ 차원 불일치: {current_db_dim} != {new_service.dimension}")
                    print(f"   벡터 검색 결과가 부정확할 수 있습니다.")
                    print(f"   텍스트 검색으로 fallback됩니다.")
                else:
                    print(f"⚠️  같은 차원이지만 다른 모델입니다.")
                    print(f"   벡터 공간이 달라 검색 결과가 부정확할 수 있습니다.")
                
                print(f"💡 정확한 검색을 위해서는 다음 중 하나를 실행하세요:")
                print(f"   1. 모델 마이그레이션: python scripts/switch_embedding_model.py {model_name}")
                print(f"   2. 원래 모델 사용: {current_db_model}")
                
                # 사용자 확인
                if self.verbose == 0:  # 비대화형 모드가 아닌 경우만
                    confirm = input(f"\n계속 진행하시겠습니까? (y/N): ")
                    if confirm.lower() != 'y':
                        print("모델 전환이 취소되었습니다.")
                        return False
            
            # 스토리지의 임베딩 서비스 교체
            self.storage.embedding_service = new_service
            self.current_model = model_name
            
            load_time = time.time() - start_time
            
            print(f"✅ 모델 전환 완료: {model_name}")
            if self.verbose >= 1:
                print(f"   로딩 시간: {load_time:.3f}초")
                print(f"   차원: {new_service.dimension}")
            
            return True
            
        except Exception as e:
            print(f"❌ 모델 전환 실패: {e}")
            if self.verbose >= 2:
                import traceback
                traceback.print_exc()
            return False
    
    async def search(self, query: str, limit: int = 5, 
                    project_id: Optional[str] = None,
                    category: Optional[str] = None) -> None:
        """검색 실행"""
        if not query.strip():
            print("❌ 검색어를 입력해주세요.")
            return
        
        print(f"\n🔍 검색 실행: '{query}'")
        if self.verbose >= 1:
            print(f"   모델: {self.current_model or self.storage.embedding_service.model_name}")
            print(f"   제한: {limit}개")
            if project_id:
                print(f"   프로젝트: {project_id}")
            if category:
                print(f"   카테고리: {category}")
        
        try:
            start_time = time.time()
            
            # 검색 실행
            search_params = SearchParams(
                query=query,
                limit=limit,
                project_id=project_id,
                category=category
            )
            
            search_result = await self.storage.search_memories(search_params)
            results = search_result.results
            
            search_time = time.time() - start_time
            
            # 결과 표시
            print(f"\n📊 검색 결과 ({len(results)}개, {search_time:.3f}초)")
            print("=" * 80)
            
            if not results:
                print("검색 결과가 없습니다.")
                return
            
            for i, result in enumerate(results, 1):
                print(f"\n{i}. [{result.category}] {result.id[:8]}...")
                
                # 내용 표시 (길면 자르기)
                content = result.content
                if len(content) > 200:
                    content = content[:200] + "..."
                
                print(f"   내용: {content}")
                
                if hasattr(result, 'score') and result.score is not None:
                    print(f"   점수: {result.score:.4f}")
                
                if result.project_id:
                    print(f"   프로젝트: {result.project_id}")
                
                if hasattr(result, 'tags') and result.tags:
                    print(f"   태그: {', '.join(result.tags)}")
                
                print(f"   생성일: {result.created_at}")
                
                if self.verbose >= 2:
                    print(f"   전체 내용: {result.content}")
            
            print("=" * 80)
            
        except Exception as e:
            print(f"❌ 검색 실패: {e}")
            if self.verbose >= 2:
                import traceback
                traceback.print_exc()
    
    def display_help(self):
        """도움말 표시"""
        print("\n📖 사용 가능한 명령어:")
        print("-" * 50)
        print("  models          - 사용 가능한 모델 목록 표시")
        print("  model <name>    - 모델 전환")
        print("  search <query>  - 검색 실행")
        print("  limit <number>  - 검색 결과 개수 설정 (기본: 5)")
        print("  project <id>    - 프로젝트 필터 설정/해제")
        print("  category <cat>  - 카테고리 필터 설정/해제")
        print("  clear           - 필터 초기화")
        print("  help            - 이 도움말 표시")
        print("  quit, exit      - 종료")
        print("-" * 50)
        print("\n💡 팁:")
        print("  - 모델 번호로도 선택 가능 (예: model 1)")
        print("  - 검색어에 공백이 있으면 따옴표로 감싸세요")
        print("  - -v, -vv 옵션으로 상세 로그 확인 가능")
        print("\n⚠️  중요한 주의사항:")
        print("  - 모델 전환 시 기존 임베딩과 호환성 문제가 있을 수 있습니다")
        print("  - 차원이 다른 모델로 전환하면 벡터 검색이 부정확해집니다")
        print("  - 정확한 검색을 위해서는 모델 마이그레이션이 필요합니다")
        print("  - 마이그레이션: python scripts/switch_embedding_model.py <모델명>")
    
    async def run_interactive(self, initial_project=None, initial_category=None, initial_limit=5):
        """대화형 모드 실행"""
        print("\n🎯 대화형 검색 모드 시작")
        print("도움말을 보려면 'help'를 입력하세요.")
        
        # 기본 설정 (초기값 반영)
        current_limit = initial_limit
        current_project = initial_project
        current_category = initial_category
        
        while True:
            try:
                # 프롬프트 표시
                model_name = self.current_model or self.storage.embedding_service.model_name
                model_short = model_name.split('/')[-1] if '/' in model_name else model_name
                
                filters = []
                if current_project:
                    filters.append(f"project:{current_project}")
                if current_category:
                    filters.append(f"category:{current_category}")
                
                filter_str = f" [{', '.join(filters)}]" if filters else ""
                
                prompt = f"search({model_short}, limit={current_limit}{filter_str})> "
                user_input = input(prompt).strip()
                
                if not user_input:
                    continue
                
                # 명령어 파싱
                parts = user_input.split(None, 1)
                command = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                
                # 명령어 처리
                if command in ['quit', 'exit', 'q']:
                    print("👋 검색 도구를 종료합니다.")
                    break
                
                elif command == 'help':
                    self.display_help()
                
                elif command == 'models':
                    self.display_available_models()
                
                elif command == 'model':
                    if not args:
                        print("❌ 모델명을 입력해주세요. (예: model all-MiniLM-L6-v2)")
                        continue
                    
                    # 숫자로 입력된 경우 모델명으로 변환
                    if args.isdigit():
                        model_idx = int(args) - 1
                        if 0 <= model_idx < len(self.SUPPORTED_MODELS):
                            args = self.SUPPORTED_MODELS[model_idx]
                        else:
                            print(f"❌ 잘못된 모델 번호: {args}")
                            continue
                    
                    await self.switch_model(args)
                
                elif command == 'search':
                    if not args:
                        print("❌ 검색어를 입력해주세요. (예: search 버그 수정)")
                        continue
                    
                    await self.search(
                        query=args,
                        limit=current_limit,
                        project_id=current_project,
                        category=current_category
                    )
                
                elif command == 'limit':
                    if not args or not args.isdigit():
                        print("❌ 숫자를 입력해주세요. (예: limit 10)")
                        continue
                    
                    current_limit = int(args)
                    print(f"✅ 검색 결과 개수를 {current_limit}개로 설정했습니다.")
                
                elif command == 'project':
                    if not args:
                        current_project = None
                        print("✅ 프로젝트 필터를 해제했습니다.")
                    else:
                        current_project = args
                        print(f"✅ 프로젝트 필터를 '{args}'로 설정했습니다.")
                
                elif command == 'category':
                    if not args:
                        current_category = None
                        print("✅ 카테고리 필터를 해제했습니다.")
                    else:
                        current_category = args
                        print(f"✅ 카테고리 필터를 '{args}'로 설정했습니다.")
                
                elif command == 'clear':
                    current_project = None
                    current_category = None
                    print("✅ 모든 필터를 초기화했습니다.")
                
                else:
                    # 명령어가 없으면 검색으로 간주
                    await self.search(
                        query=user_input,
                        limit=current_limit,
                        project_id=current_project,
                        category=current_category
                    )
            
            except KeyboardInterrupt:
                print("\n👋 검색 도구를 종료합니다.")
                break
            except EOFError:
                print("\n👋 검색 도구를 종료합니다.")
                break
            except Exception as e:
                print(f"❌ 오류 발생: {e}")
                if self.verbose >= 2:
                    import traceback
                    traceback.print_exc()
    
    async def shutdown(self):
        """리소스 정리"""
        if self.storage:
            await self.storage.shutdown()


async def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(
        description="대화형 검색 도구 - 다양한 임베딩 모델로 실시간 검색 테스트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python scripts/interactive_search.py                    # 기본 실행
  python scripts/interactive_search.py "버그 수정"         # 검색어와 함께 실행
  python scripts/interactive_search.py -v                 # 상세 로그
  python scripts/interactive_search.py -vv                # 디버그 로그
  python scripts/interactive_search.py --model all-mpnet-base-v2  # 특정 모델로 시작
  python scripts/interactive_search.py --limit 10         # 기본 검색 결과 개수 설정
  python scripts/interactive_search.py "API 구현" --model all-mpnet-base-v2 --limit 10  # 모든 옵션 조합
        """
    )
    
    parser.add_argument("query", nargs="?", 
                       help="검색어 (선택사항, 제공되면 바로 검색 실행)")
    parser.add_argument("--db-path", default="data/memories.db", 
                       help="데이터베이스 경로 (기본: data/memories.db)")
    parser.add_argument("--model", 
                       help="시작할 임베딩 모델 (기본: 현재 설정된 모델)")
    parser.add_argument("--limit", type=int, default=5,
                       help="기본 검색 결과 개수 (기본: 5)")
    parser.add_argument("--project", 
                       help="프로젝트 ID 필터")
    parser.add_argument("--category", 
                       help="카테고리 필터")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                       help="상세 출력 (-v: INFO, -vv: DEBUG)")
    
    args = parser.parse_args()
    
    # 검색 도구 초기화
    search_tool = InteractiveSearchTool(args.db_path, args.verbose)
    
    try:
        await search_tool.initialize()
        
        # 시작 모델 설정
        if args.model:
            await search_tool.switch_model(args.model)
        
        # 초기 검색 실행 (검색어가 제공된 경우)
        if args.query:
            print(f"\n🔍 초기 검색 실행: '{args.query}'")
            await search_tool.search(
                query=args.query,
                limit=args.limit,
                project_id=args.project,
                category=args.category
            )
            print("\n" + "="*60)
            print("💡 대화형 모드로 계속 진행합니다. 'help'를 입력하면 도움말을 볼 수 있습니다.")
        
        # 대화형 모드 실행
        await search_tool.run_interactive(
            initial_project=args.project,
            initial_category=args.category,
            initial_limit=args.limit
        )
        
    except Exception as e:
        print(f"❌ 실행 실패: {e}")
        if args.verbose >= 2:
            import traceback
            traceback.print_exc()
    finally:
        await search_tool.shutdown()


if __name__ == "__main__":
    asyncio.run(main())