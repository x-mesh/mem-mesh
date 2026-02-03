"""
TokenEstimator: 텍스트 토큰 수 추정 서비스

tiktoken 라이브러리를 사용하여 다양한 OpenAI 모델의 토큰 수를 추정합니다.
"""

import logging
from typing import Optional, Dict
import tiktoken

logger = logging.getLogger(__name__)


class TokenEstimator:
    """
    텍스트의 토큰 수를 추정하는 서비스
    
    tiktoken 라이브러리를 사용하여 OpenAI 모델별 토큰 수를 정확하게 계산합니다.
    """
    
    # 지원하는 모델과 해당 인코딩
    MODEL_ENCODINGS: Dict[str, str] = {
        # GPT-4 모델들
        "gpt-4": "cl100k_base",
        "gpt-4-turbo": "cl100k_base",
        "gpt-4-turbo-preview": "cl100k_base",
        "gpt-4-0125-preview": "cl100k_base",
        "gpt-4-1106-preview": "cl100k_base",
        "gpt-4-vision-preview": "cl100k_base",
        "gpt-4-32k": "cl100k_base",
        "gpt-4-0613": "cl100k_base",
        "gpt-4-32k-0613": "cl100k_base",
        
        # GPT-3.5 모델들
        "gpt-3.5-turbo": "cl100k_base",
        "gpt-3.5-turbo-16k": "cl100k_base",
        "gpt-3.5-turbo-0125": "cl100k_base",
        "gpt-3.5-turbo-1106": "cl100k_base",
        "gpt-3.5-turbo-0613": "cl100k_base",
        "gpt-3.5-turbo-16k-0613": "cl100k_base",
        
        # 레거시 모델들
        "text-davinci-003": "p50k_base",
        "text-davinci-002": "p50k_base",
        "text-curie-001": "r50k_base",
        "text-babbage-001": "r50k_base",
        "text-ada-001": "r50k_base",
    }
    
    DEFAULT_ENCODING = "cl100k_base"  # GPT-4/GPT-3.5-turbo 기본 인코딩
    
    def __init__(self, default_model: str = "gpt-4"):
        """
        TokenEstimator 초기화
        
        Args:
            default_model: 기본 모델 이름 (기본값: "gpt-4")
        """
        self.default_model = default_model
        self._encoders: Dict[str, tiktoken.Encoding] = {}
        
        # 기본 인코더 미리 로드
        try:
            self._get_encoder(self.default_model)
            logger.info(f"TokenEstimator initialized with default model: {default_model}")
        except Exception as e:
            logger.warning(f"Failed to load default encoder for {default_model}: {e}")
    
    def _get_encoder(self, model: str) -> tiktoken.Encoding:
        """
        모델에 해당하는 tiktoken 인코더를 가져옵니다.
        
        Args:
            model: 모델 이름
            
        Returns:
            tiktoken.Encoding 객체
        """
        # 캐시된 인코더가 있으면 반환
        if model in self._encoders:
            return self._encoders[model]
        
        # 모델에 해당하는 인코딩 이름 찾기
        encoding_name = self.MODEL_ENCODINGS.get(model, self.DEFAULT_ENCODING)
        
        try:
            # 인코더 로드 및 캐싱
            encoder = tiktoken.get_encoding(encoding_name)
            self._encoders[model] = encoder
            logger.debug(f"Loaded encoder '{encoding_name}' for model '{model}'")
            return encoder
        except Exception as e:
            logger.error(f"Failed to load encoder '{encoding_name}' for model '{model}': {e}")
            # 폴백: 기본 인코딩 사용
            if encoding_name != self.DEFAULT_ENCODING:
                logger.info(f"Falling back to default encoding: {self.DEFAULT_ENCODING}")
                encoder = tiktoken.get_encoding(self.DEFAULT_ENCODING)
                self._encoders[model] = encoder
                return encoder
            raise
    
    def estimate_tokens(
        self,
        content: str,
        model: Optional[str] = None
    ) -> int:
        """
        텍스트의 예상 토큰 수를 계산합니다.
        
        Args:
            content: 분석할 텍스트
            model: 모델 이름 (None이면 기본 모델 사용)
            
        Returns:
            예상 토큰 수
            
        Examples:
            >>> estimator = TokenEstimator()
            >>> estimator.estimate_tokens("Hello, world!")
            4
            >>> estimator.estimate_tokens("안녕하세요", model="gpt-3.5-turbo")
            3
        """
        if not content:
            return 0
        
        model = model or self.default_model
        
        try:
            encoder = self._get_encoder(model)
            tokens = encoder.encode(content)
            token_count = len(tokens)
            
            logger.debug(f"Estimated {token_count} tokens for {len(content)} characters (model: {model})")
            return token_count
            
        except Exception as e:
            logger.error(f"Token estimation failed for model '{model}': {e}")
            # 폴백: 간단한 휴리스틱 (평균 4자당 1토큰)
            fallback_count = max(1, len(content) // 4)
            logger.warning(f"Using fallback estimation: {fallback_count} tokens")
            return fallback_count
    
    def estimate_tokens_batch(
        self,
        contents: list[str],
        model: Optional[str] = None
    ) -> list[int]:
        """
        여러 텍스트의 토큰 수를 일괄 계산합니다.
        
        Args:
            contents: 분석할 텍스트 리스트
            model: 모델 이름 (None이면 기본 모델 사용)
            
        Returns:
            각 텍스트의 예상 토큰 수 리스트
        """
        return [self.estimate_tokens(content, model) for content in contents]
    
    def estimate_tokens_dict(
        self,
        data: dict,
        model: Optional[str] = None
    ) -> int:
        """
        딕셔너리 데이터의 토큰 수를 추정합니다.
        
        JSON 형식으로 변환 후 토큰 수를 계산합니다.
        
        Args:
            data: 분석할 딕셔너리
            model: 모델 이름
            
        Returns:
            예상 토큰 수
        """
        import json
        try:
            content = json.dumps(data, ensure_ascii=False)
            return self.estimate_tokens(content, model)
        except Exception as e:
            logger.error(f"Failed to estimate tokens for dict: {e}")
            return 0
    
    def get_supported_models(self) -> list[str]:
        """
        지원하는 모델 목록을 반환합니다.
        
        Returns:
            지원하는 모델 이름 리스트
        """
        return list(self.MODEL_ENCODINGS.keys())
    
    def get_encoding_for_model(self, model: str) -> str:
        """
        모델에 사용되는 인코딩 이름을 반환합니다.
        
        Args:
            model: 모델 이름
            
        Returns:
            인코딩 이름
        """
        return self.MODEL_ENCODINGS.get(model, self.DEFAULT_ENCODING)
