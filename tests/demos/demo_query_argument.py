#!/usr/bin/env python3
"""
검색어 인수 기능 데모 - 실제 명령행 실행 시뮬레이션
"""

import time


def run_command_demo(cmd, description):
    """명령어 실행 데모"""
    print(f"\n🔍 {description}")
    print(f"명령어: {cmd}")
    print("-" * 60)

    # 실제로는 실행하지 않고 설명만 출력
    print("(실제 실행 시 다음과 같은 결과가 나타납니다)")

    if "버그 수정" in cmd:
        print("🔍 초기 검색 실행: '버그 수정'")
        print("📊 검색 결과 (3개, 0.5초)")
        print("1. [bug] 캐시 정보 함수에 버그가 있네요. 수정하겠습니다.")
        print("2. [bug] 이제 수정하겠습니다.")
        print("3. [bug] 주요 파일들을 수정합니다:")
        print("💡 대화형 모드로 계속 진행합니다.")

    elif "API 구현" in cmd:
        print("🔍 초기 검색 실행: 'API 구현'")
        print("📊 검색 결과 (10개, 0.8초)")
        print("1. [task] FastAPI 서버 구현 완료")
        print("2. [decision] REST API 설계 결정사항")
        print("3. [code_snippet] API 엔드포인트 예제")
        print("💡 대화형 모드로 계속 진행합니다.")

    elif "데이터베이스" in cmd:
        print("🔍 초기 검색 실행: '데이터베이스'")
        print(
            "📊 검색 결과 (5개, 0.3초) [category:decision, project:kiro-conversations]"
        )
        print("1. [decision] SQLite + sqlite-vec 아키텍처 선택")
        print("2. [decision] 임베딩 모델 마이그레이션 완료")
        print("💡 대화형 모드로 계속 진행합니다.")


def main():
    """데모 실행"""
    print("🎯 검색어 인수 기능 데모")
    print("=" * 60)

    demos = [
        ('python scripts/interactive_search.py "버그 수정"', "기본 검색어 실행"),
        (
            'python scripts/interactive_search.py "API 구현" --model all-mpnet-base-v2 --limit 10',
            "모델과 제한 개수 지정",
        ),
        (
            'python scripts/interactive_search.py "데이터베이스" --category decision --project kiro-conversations',
            "카테고리와 프로젝트 필터링",
        ),
        (
            'python scripts/interactive_search.py "성능 최적화" -v',
            "상세 로그와 함께 실행",
        ),
    ]

    for cmd, desc in demos:
        run_command_demo(cmd, desc)
        time.sleep(1)

    print("\n" + "=" * 60)
    print("🎉 검색어 인수 기능 데모 완료!")
    print("\n💡 주요 개선사항:")
    print("✅ 명령행에서 바로 검색어 입력 가능")
    print("✅ 초기 필터 설정 (프로젝트, 카테고리) 지원")
    print("✅ 검색 후 대화형 모드로 자동 전환")
    print("✅ 모든 기존 옵션과 호환")

    print("\n🚀 실제 사용해보기:")
    print('python scripts/interactive_search.py "원하는 검색어"')


if __name__ == "__main__":
    main()
