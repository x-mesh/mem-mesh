"""
TokenEstimator 단위 테스트

Requirements: 7.1, 7.2
"""

import pytest
from app.core.services.token_estimator import TokenEstimator


class TestTokenEstimator:
    """TokenEstimator 클래스 테스트"""
    
    def test_initialization(self):
        """TokenEstimator 초기화 테스트"""
        estimator = TokenEstimator()
        assert estimator.default_model == "gpt-4"
        
        estimator_custom = TokenEstimator(default_model="gpt-3.5-turbo")
        assert estimator_custom.default_model == "gpt-3.5-turbo"
    
    def test_estimate_tokens_empty_string(self):
        """빈 문자열의 토큰 수는 0이어야 함"""
        estimator = TokenEstimator()
        assert estimator.estimate_tokens("") == 0
        assert estimator.estimate_tokens(None) == 0
    
    def test_estimate_tokens_simple_text(self):
        """간단한 영어 텍스트 토큰 추정"""
        estimator = TokenEstimator()
        
        # "Hello, world!"는 대략 4 토큰
        token_count = estimator.estimate_tokens("Hello, world!")
        assert token_count > 0
        assert token_count < 10  # 합리적인 범위
    
    def test_estimate_tokens_korean_text(self):
        """한국어 텍스트 토큰 추정"""
        estimator = TokenEstimator()
        
        # 한국어는 영어보다 토큰 수가 많을 수 있음
        token_count = estimator.estimate_tokens("안녕하세요, 세계!")
        assert token_count > 0
    
    def test_estimate_tokens_long_text(self):
        """긴 텍스트 토큰 추정"""
        estimator = TokenEstimator()
        
        long_text = "This is a longer text. " * 100
        token_count = estimator.estimate_tokens(long_text)
        
        # 긴 텍스트는 더 많은 토큰을 가져야 함
        assert token_count > 100
    
    def test_estimate_tokens_different_models(self):
        """다양한 모델에 대한 토큰 추정"""
        estimator = TokenEstimator()
        
        text = "Hello, world!"
        
        # GPT-4
        tokens_gpt4 = estimator.estimate_tokens(text, model="gpt-4")
        assert tokens_gpt4 > 0
        
        # GPT-3.5-turbo
        tokens_gpt35 = estimator.estimate_tokens(text, model="gpt-3.5-turbo")
        assert tokens_gpt35 > 0
        
        # 같은 인코딩을 사용하므로 토큰 수가 같아야 함
        assert tokens_gpt4 == tokens_gpt35
    
    def test_estimate_tokens_batch(self):
        """여러 텍스트 일괄 토큰 추정"""
        estimator = TokenEstimator()
        
        texts = [
            "Hello",
            "World",
            "This is a test"
        ]
        
        token_counts = estimator.estimate_tokens_batch(texts)
        
        assert len(token_counts) == len(texts)
        assert all(count > 0 for count in token_counts)
        # 긴 텍스트가 더 많은 토큰을 가져야 함
        assert token_counts[2] > token_counts[0]
    
    def test_estimate_tokens_dict(self):
        """딕셔너리 데이터 토큰 추정"""
        estimator = TokenEstimator()
        
        data = {
            "name": "test",
            "value": 123,
            "description": "This is a test"
        }
        
        token_count = estimator.estimate_tokens_dict(data)
        assert token_count > 0
    
    def test_get_supported_models(self):
        """지원하는 모델 목록 조회"""
        estimator = TokenEstimator()
        
        models = estimator.get_supported_models()
        
        assert isinstance(models, list)
        assert len(models) > 0
        assert "gpt-4" in models
        assert "gpt-3.5-turbo" in models
    
    def test_get_encoding_for_model(self):
        """모델별 인코딩 이름 조회"""
        estimator = TokenEstimator()
        
        # GPT-4는 cl100k_base 사용
        assert estimator.get_encoding_for_model("gpt-4") == "cl100k_base"
        
        # GPT-3.5-turbo도 cl100k_base 사용
        assert estimator.get_encoding_for_model("gpt-3.5-turbo") == "cl100k_base"
        
        # 알 수 없는 모델은 기본 인코딩 반환
        assert estimator.get_encoding_for_model("unknown-model") == "cl100k_base"
    
    def test_encoder_caching(self):
        """인코더 캐싱 동작 확인"""
        estimator = TokenEstimator()
        
        # 같은 모델로 여러 번 호출
        text = "Test text"
        estimator.estimate_tokens(text, model="gpt-4")
        estimator.estimate_tokens(text, model="gpt-4")
        
        # 캐시에 인코더가 저장되어 있어야 함
        assert "gpt-4" in estimator._encoders
    
    def test_fallback_on_error(self):
        """에러 발생 시 폴백 동작 확인"""
        estimator = TokenEstimator()
        
        # 매우 긴 텍스트로 테스트 (에러가 발생하지 않아야 함)
        long_text = "a" * 100000
        token_count = estimator.estimate_tokens(long_text)
        
        # 폴백이든 정상 계산이든 결과가 반환되어야 함
        assert token_count > 0
    
    def test_special_characters(self):
        """특수 문자 포함 텍스트 토큰 추정"""
        estimator = TokenEstimator()
        
        text_with_special = "Hello! @#$%^&*() 123 안녕하세요 🎉"
        token_count = estimator.estimate_tokens(text_with_special)
        
        assert token_count > 0
    
    def test_multiline_text(self):
        """여러 줄 텍스트 토큰 추정"""
        estimator = TokenEstimator()
        
        multiline_text = """
        This is line 1
        This is line 2
        This is line 3
        """
        
        token_count = estimator.estimate_tokens(multiline_text)
        assert token_count > 0


class TestTokenEstimatorEdgeCases:
    """TokenEstimator 엣지 케이스 테스트"""
    
    def test_whitespace_only(self):
        """공백만 있는 텍스트"""
        estimator = TokenEstimator()
        
        token_count = estimator.estimate_tokens("   ")
        assert token_count >= 0
    
    def test_single_character(self):
        """단일 문자"""
        estimator = TokenEstimator()
        
        token_count = estimator.estimate_tokens("a")
        assert token_count > 0
    
    def test_numbers_only(self):
        """숫자만 있는 텍스트"""
        estimator = TokenEstimator()
        
        token_count = estimator.estimate_tokens("1234567890")
        assert token_count > 0
    
    def test_unicode_characters(self):
        """유니코드 문자"""
        estimator = TokenEstimator()
        
        # 이모지, 특수 유니코드 문자
        text = "Hello 👋 世界 🌍"
        token_count = estimator.estimate_tokens(text)
        assert token_count > 0
    
    def test_code_snippet(self):
        """코드 스니펫 토큰 추정"""
        estimator = TokenEstimator()
        
        code = """
        def hello_world():
            print("Hello, world!")
            return True
        """
        
        token_count = estimator.estimate_tokens(code)
        assert token_count > 0
    
    def test_json_string(self):
        """JSON 문자열 토큰 추정"""
        estimator = TokenEstimator()
        
        json_str = '{"name": "test", "value": 123, "nested": {"key": "value"}}'
        token_count = estimator.estimate_tokens(json_str)
        assert token_count > 0
