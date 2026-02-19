"""
ImportanceAnalyzer 단위 테스트

ImportanceAnalyzer 클래스의 키워드 기반 중요도 분석 기능을 테스트합니다.
"""

import pytest
from app.core.services.importance_analyzer import ImportanceAnalyzer


class TestImportanceAnalyzer:
    """ImportanceAnalyzer 클래스 테스트"""
    
    @pytest.fixture
    def analyzer(self):
        """테스트용 ImportanceAnalyzer 인스턴스"""
        return ImportanceAnalyzer()
    
    # 기본 기능 테스트
    
    def test_initialization(self, analyzer):
        """초기화 시 키워드 사전이 로드되는지 확인"""
        assert analyzer.keywords is not None
        assert len(analyzer.keywords) == 5
        assert all(importance in analyzer.keywords for importance in range(1, 6))
    
    def test_default_importance_for_empty_content(self, analyzer):
        """빈 컨텐츠에 대해 기본 중요도(3)를 반환하는지 확인"""
        result = analyzer.analyze("")
        assert result == 3
    
    def test_default_importance_for_no_keyword_match(self, analyzer):
        """키워드가 매칭되지 않으면 기본 중요도(3)를 반환하는지 확인"""
        result = analyzer.analyze("Some random text without keywords")
        assert result == 3
    
    # 중요도 5 (아키텍처, 설계, 중대) 테스트
    
    def test_importance_5_architecture_english(self, analyzer):
        """영어 'architecture' 키워드로 중요도 5 반환"""
        result = analyzer.analyze("Design new system architecture")
        assert result == 5
    
    def test_importance_5_critical_english(self, analyzer):
        """영어 'critical' 키워드로 중요도 5 반환"""
        result = analyzer.analyze("Critical security vulnerability found")
        assert result == 5
    
    def test_importance_5_korean(self, analyzer):
        """한국어 '아키텍처' 키워드로 중요도 5 반환"""
        result = analyzer.analyze("시스템 아키텍처 설계")
        assert result == 5
    
    def test_importance_5_with_tags(self, analyzer):
        """태그에 'security' 포함 시 중요도 5 반환"""
        result = analyzer.analyze("Fix issue", tags=["security", "critical"])
        assert result == 5
    
    # 중요도 4 (기능, 구현, 최적화) 테스트
    
    def test_importance_4_feature_english(self, analyzer):
        """영어 'feature' 키워드로 중요도 4 반환"""
        result = analyzer.analyze("Implement new authentication feature")
        assert result == 4
    
    def test_importance_4_optimize_english(self, analyzer):
        """영어 'optimize' 키워드로 중요도 4 반환"""
        result = analyzer.analyze("Optimize database query performance")
        assert result == 4
    
    def test_importance_4_korean(self, analyzer):
        """한국어 '기능' 키워드로 중요도 4 반환"""
        result = analyzer.analyze("새로운 기능 구현")
        assert result == 4
    
    # 중요도 3 (수정, 업데이트, 개선) 테스트
    
    def test_importance_3_bug_english(self, analyzer):
        """영어 'bug' 키워드로 중요도 3 반환"""
        result = analyzer.analyze("Found bug in login flow")
        assert result == 3
    
    def test_importance_3_update_english(self, analyzer):
        """영어 'update' 키워드로 중요도 3 반환"""
        result = analyzer.analyze("Update dependencies")
        assert result == 3
    
    def test_importance_3_korean(self, analyzer):
        """한국어 '버그' 키워드로 중요도 3 반환"""
        result = analyzer.analyze("버그 발견")
        assert result == 3
    
    # 중요도 2 (테스트, 문서, 주석) 테스트
    
    def test_importance_2_test_english(self, analyzer):
        """영어 'test' 키워드로 중요도 2 반환"""
        result = analyzer.analyze("Add unit tests")
        assert result == 2
    
    def test_importance_2_doc_english(self, analyzer):
        """영어 'doc' 키워드로 중요도 2 반환"""
        result = analyzer.analyze("Update documentation")
        assert result == 2
    
    def test_importance_2_korean(self, analyzer):
        """한국어 '테스트' 키워드로 중요도 2 반환"""
        result = analyzer.analyze("테스트 코드 작성")
        assert result == 2
    
    # 중요도 1 (오타, 포맷, 스타일) 테스트
    
    def test_importance_1_typo_english(self, analyzer):
        """영어 'typo' 키워드로 중요도 1 반환"""
        result = analyzer.analyze("Typo in variable name")
        assert result == 1
    
    def test_importance_1_format_english(self, analyzer):
        """영어 'format' 키워드로 중요도 1 반환"""
        result = analyzer.analyze("Format code with black")
        assert result == 1
    
    def test_importance_1_korean(self, analyzer):
        """한국어 '오타' 키워드로 중요도 1 반환"""
        result = analyzer.analyze("오타 수정")
        assert result == 1
    
    # 엣지 케이스 테스트
    
    def test_case_insensitive_matching(self, analyzer):
        """대소문자 구분 없이 매칭되는지 확인"""
        result1 = analyzer.analyze("ARCHITECTURE design")
        result2 = analyzer.analyze("architecture DESIGN")
        assert result1 == 5
        assert result2 == 5
    
    def test_word_boundary_matching(self, analyzer):
        """단어 경계를 고려한 매칭 확인"""
        # "test"는 "testing"과 매칭되어야 함
        result = analyzer.analyze("Add testing framework")
        assert result == 2
    
    def test_multiple_keywords_highest_importance(self, analyzer):
        """여러 키워드가 있을 때 가장 높은 중요도 반환"""
        # "architecture" (5)와 "test" (2)가 모두 있지만 5를 반환해야 함
        result = analyzer.analyze("Architecture test for new system")
        assert result == 5
    
    def test_multiple_matches_same_importance(self, analyzer):
        """같은 중요도의 키워드가 여러 번 매칭되어도 해당 중요도 반환"""
        result = analyzer.analyze("Bug found and update error handling")
        assert result == 3
    
    def test_tags_only_analysis(self, analyzer):
        """컨텐츠 없이 태그만으로도 분석 가능"""
        result = analyzer.analyze("Do something", tags=["architecture", "design"])
        assert result == 5
    
    def test_none_tags(self, analyzer):
        """tags가 None이어도 정상 동작"""
        result = analyzer.analyze("Implement feature", tags=None)
        assert result == 4
    
    def test_empty_tags_list(self, analyzer):
        """빈 태그 리스트도 정상 동작"""
        result = analyzer.analyze("Implement feature", tags=[])
        assert result == 4
    
    # 유틸리티 메서드 테스트
    
    def test_get_keywords_for_importance(self, analyzer):
        """특정 중요도의 키워드 목록 조회"""
        keywords = analyzer.get_keywords_for_importance(5)
        assert isinstance(keywords, list)
        assert "architecture" in keywords
        assert "아키텍처" in keywords
    
    def test_get_keywords_for_invalid_importance(self, analyzer):
        """존재하지 않는 중요도에 대해 빈 리스트 반환"""
        keywords = analyzer.get_keywords_for_importance(10)
        assert keywords == []
    
    def test_get_all_keywords(self, analyzer):
        """모든 키워드 사전 조회"""
        all_keywords = analyzer.get_all_keywords()
        assert isinstance(all_keywords, dict)
        assert len(all_keywords) == 5
        # 원본이 변경되지 않도록 복사본 반환 확인
        all_keywords[5].append("test_keyword")
        assert "test_keyword" not in analyzer.keywords[5]
    
    def test_add_custom_keyword(self, analyzer):
        """커스텀 키워드 추가"""
        analyzer.add_custom_keyword(5, "mission-critical")
        keywords = analyzer.get_keywords_for_importance(5)
        assert "mission-critical" in keywords
        
        # 추가한 키워드로 분석 가능한지 확인
        result = analyzer.analyze("This is mission-critical")
        assert result == 5
    
    def test_add_custom_keyword_invalid_importance(self, analyzer):
        """잘못된 중요도로 키워드 추가 시 에러 발생"""
        with pytest.raises(ValueError, match="Importance must be between 1 and 5"):
            analyzer.add_custom_keyword(10, "invalid")
    
    def test_add_duplicate_custom_keyword(self, analyzer):
        """중복 키워드 추가 시 중복 방지"""
        initial_count = len(analyzer.get_keywords_for_importance(5))
        analyzer.add_custom_keyword(5, "architecture")  # 이미 존재하는 키워드
        final_count = len(analyzer.get_keywords_for_importance(5))
        assert initial_count == final_count
    
    # 실제 사용 시나리오 테스트
    
    def test_real_scenario_critical_bug(self, analyzer):
        """실제 시나리오: 중대한 버그 수정"""
        result = analyzer.analyze(
            "Critical bug in authentication system causing security breach",
            tags=["security", "urgent"]
        )
        assert result == 5
    
    def test_real_scenario_new_feature(self, analyzer):
        """실제 시나리오: 새 기능 구현"""
        result = analyzer.analyze(
            "Implement user profile feature with avatar upload",
            tags=["feature", "enhancement"]
        )
        assert result == 4
    
    def test_real_scenario_minor_fix(self, analyzer):
        """실제 시나리오: 사소한 수정"""
        result = analyzer.analyze(
            "Typo in error message",
            tags=["cleanup"]
        )
        assert result == 1
    
    def test_real_scenario_documentation(self, analyzer):
        """실제 시나리오: 문서 작업"""
        result = analyzer.analyze(
            "Add API documentation and usage examples",
            tags=["docs"]
        )
        assert result == 2
    
    def test_real_scenario_korean_mixed(self, analyzer):
        """실제 시나리오: 한국어 혼합 - 아키텍처가 우선"""
        result = analyzer.analyze(
            "시스템 아키텍처 설계 및 구조 변경",
            tags=["architecture", "design"]
        )
        assert result == 5
