#!/usr/bin/env python3
"""
요약 기능만 테스트하는 스크립트
"""
import logging
import re
from typing import Optional

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleSummarizer:
    """간단한 요약 테스터"""
    
    def __init__(self, model_name: str = "sshleifer/distilbart-cnn-12-6"):
        self.model_name = model_name
        self.summary_model = None
        self.verbose_level = 3
    
    def initialize(self):
        """요약 모델 초기화"""
        try:
            from transformers import pipeline
            logger.info(f"요약 모델 로드 중: {self.model_name}")
            
            # 가벼운 모델들 우선 시도
            lightweight_models = [
                "sshleifer/distilbart-cnn-12-6",  # 가벼운 BART (우선)
                "t5-small",                       # T5 small (빠름)
                "facebook/bart-large-cnn",        # 고품질 BART
            ]
            
            model_to_use = self.model_name
            model_loaded = False
            
            # 사용자 지정 모델 먼저 시도
            if self.model_name not in lightweight_models:
                try:
                    logger.info(f"사용자 지정 모델 시도: {self.model_name}")
                    self.summary_model = pipeline(
                        "summarization",
                        model=self.model_name,
                        device=-1,  # CPU 사용
                        framework="pt",
                        return_tensors=False,
                        clean_up_tokenization_spaces=True,
                        trust_remote_code=False  # 보안상 원격 코드 실행 방지
                    )
                    model_to_use = self.model_name
                    model_loaded = True
                    logger.info(f"사용자 지정 모델 로드 성공: {model_to_use}")
                except Exception as e:
                    logger.warning(f"사용자 지정 모델 로드 실패 {self.model_name}: {e}")
            
            # 폴백 모델들 시도
            if not model_loaded:
                models_to_try = [self.model_name] if self.model_name in lightweight_models else lightweight_models
                
                for model in models_to_try:
                    try:
                        logger.info(f"모델 시도: {model}")
                        self.summary_model = pipeline(
                            "summarization",
                            model=model,
                            device=-1,  # CPU 사용
                            framework="pt",
                            return_tensors=False,
                            clean_up_tokenization_spaces=True,
                            trust_remote_code=False
                        )
                        model_to_use = model
                        model_loaded = True
                        logger.info(f"모델 로드 성공: {model_to_use}")
                        break
                    except Exception as e:
                        logger.warning(f"모델 로드 실패 {model}: {e}")
                        continue
            
            if model_loaded:
                # 모델 테스트
                try:
                    test_text = "This is a test sentence for model validation. The model should be able to process this text without errors."
                    test_result = self.summary_model(test_text, max_length=50, min_length=10, do_sample=False)
                    logger.info(f"모델 테스트 성공: {model_to_use}")
                    logger.debug(f"테스트 결과: {test_result}")
                except Exception as e:
                    logger.error(f"모델 테스트 실패: {e}")
                    self.summary_model = None
                    model_loaded = False
            
            if not model_loaded:
                logger.warning("모든 요약 모델 로드 실패, 간단한 텍스트 요약만 사용")
                self.summary_model = None
                
        except ImportError:
            logger.error("transformers 라이브러리가 필요합니다: pip install transformers torch")
            raise
        except Exception as e:
            logger.warning(f"요약 모델 초기화 실패, 간단한 텍스트 요약 사용: {e}")
            self.summary_model = None
    
    def simple_summarize(self, text: str, max_sentences: int = 3) -> str:
        """간단한 텍스트 요약 (모델 없이)"""
        # 텍스트 정리
        text = text.strip()
        if len(text) < 100:
            return text
        
        # 문장 분리 (더 정교하게)
        sentences = re.split(r'[.!?]+\s+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        
        if len(sentences) <= max_sentences:
            return '. '.join(sentences) + ('.' if not text.endswith('.') else '')
        
        # 길이와 중요도 기반으로 문장 점수 계산
        sentence_scores = []
        for sentence in sentences:
            score = len(sentence)  # 기본 점수는 길이
            
            # 중요한 키워드가 있으면 가중치 추가
            important_keywords = ['결정', 'decision', '구현', 'implement', '문제', 'problem', 
                                '해결', 'solve', '변경', 'change', '추가', 'add', '수정', 'fix']
            for keyword in important_keywords:
                if keyword.lower() in sentence.lower():
                    score *= 1.5
                    break
            
            # 코드 블록이 있으면 가중치 추가
            if '```' in sentence or 'def ' in sentence or 'class ' in sentence:
                score *= 2
            
            # 너무 짧거나 긴 문장은 점수 조정
            if len(sentence) < 50:
                score *= 0.5
            elif len(sentence) > 500:
                score *= 0.8
                
            sentence_scores.append((sentence, score))
        
        # 상위 문장들 선택
        sentence_scores.sort(key=lambda x: x[1], reverse=True)
        top_sentences = [s[0] for s in sentence_scores[:max_sentences]]
        
        # 원래 순서대로 재정렬 (가능한 경우)
        result_sentences = []
        for sentence in sentences:
            if sentence in top_sentences:
                result_sentences.append(sentence)
                if len(result_sentences) >= max_sentences:
                    break
        
        summary = '. '.join(result_sentences)
        if not summary.endswith('.'):
            summary += '.'
        
        return summary
    
    def _get_model_specific_params(self, model_name: str, base_max_length: int, 
                                 base_min_length: int, max_length: int, input_length: int) -> dict:
        """모델별 최적화된 파라미터 반환"""
        # 기본 파라미터
        params = {
            "max_length": base_max_length,
            "min_length": base_min_length,
            "do_sample": False,
            "truncation": True
        }
        
        # 모델별 특화 파라미터
        if "t5" in model_name:
            # T5는 max_new_tokens 사용
            params = {
                "max_new_tokens": base_max_length,
                "min_new_tokens": base_min_length,
                "do_sample": False,
                "truncation": True
            }
        elif "pegasus" in model_name:
            # Pegasus는 더 긴 요약 허용
            params.update({
                "max_length": min(max_length, max(100, input_length // 2)),
                "min_length": min(50, max(20, input_length // 8)),
                "length_penalty": 2.0,
                "num_beams": 4,
                "early_stopping": True
            })
        elif "bart" in model_name:
            # BART 최적화
            params.update({
                "length_penalty": 2.0,
                "num_beams": 4,
                "early_stopping": True,
                "no_repeat_ngram_size": 3
            })
        elif "kobart" in model_name:
            # 한국어 BART
            params.update({
                "length_penalty": 1.5,
                "num_beams": 3,
                "early_stopping": True
            })
        
        return params
    
    def _extract_summary_safely(self, result) -> Optional[str]:
        """요약 결과에서 안전하게 텍스트 추출"""
        try:
            # 리스트 형태의 결과 처리
            if isinstance(result, list):
                if len(result) == 0:
                    logger.debug("결과 리스트가 비어있음")
                    return None
                
                first_item = result[0]
                logger.debug(f"첫 번째 결과 항목 타입: {type(first_item)}")
                
                if isinstance(first_item, dict):
                    # 딕셔너리에서 summary_text 추출
                    if 'summary_text' in first_item:
                        summary = first_item['summary_text']
                        if isinstance(summary, str) and summary.strip():
                            return summary.strip()
                        else:
                            logger.debug(f"summary_text가 비어있거나 문자열이 아님: {type(summary)}")
                    else:
                        logger.debug(f"summary_text 키가 없음. 사용 가능한 키: {list(first_item.keys())}")
                elif isinstance(first_item, str):
                    # 문자열 결과 직접 반환
                    if first_item.strip():
                        return first_item.strip()
                    else:
                        logger.debug("첫 번째 결과가 빈 문자열")
                else:
                    logger.debug(f"예상하지 못한 첫 번째 결과 타입: {type(first_item)}")
            
            # 딕셔너리 형태의 결과 처리
            elif isinstance(result, dict):
                if 'summary_text' in result:
                    summary = result['summary_text']
                    if isinstance(summary, str) and summary.strip():
                        return summary.strip()
                else:
                    logger.debug(f"딕셔너리에 summary_text 키가 없음. 사용 가능한 키: {list(result.keys())}")
            
            # 문자열 결과 직접 처리
            elif isinstance(result, str):
                if result.strip():
                    return result.strip()
                else:
                    logger.debug("결과가 빈 문자열")
            
            else:
                logger.debug(f"예상하지 못한 결과 타입: {type(result)}")
            
            return None
            
        except Exception as e:
            logger.error(f"요약 추출 중 오류: {type(e).__name__}: {str(e)}")
            return None
    
    def ai_summarize(self, text: str, max_length: int = 500) -> str:
        """AI 모델을 사용한 요약 (상세한 디버깅 포함)"""
        if self.summary_model is None:
            logger.debug("요약 모델이 로드되지 않음, 간단한 요약 사용")
            return self.simple_summarize(text)
        
        try:
            # 입력 텍스트 전처리 및 검증
            input_text = text.strip()
            logger.debug(f"입력 텍스트 길이: {len(input_text)} 문자")
            
            if len(input_text) < 100:
                logger.debug("입력 텍스트가 너무 짧음 (< 100자), 원본 반환")
                return input_text
            
            # 토크나이저 제한을 고려하여 입력 길이 조정
            max_input_length = 2500  # 안전한 문자 수 제한
            if len(input_text) > max_input_length:
                input_text = input_text[:max_input_length] + "..."
                logger.debug(f"입력 텍스트를 {max_input_length}자로 잘라냄")
            
            # 모델 정보 확인
            model_name = getattr(self.summary_model.model.config, 'name_or_path', 'unknown').lower()
            logger.debug(f"사용 중인 요약 모델: {model_name}")
            
            # 기본 파라미터 계산
            base_max_length = min(max_length, max(50, len(input_text) // 3))
            base_min_length = min(30, max(10, len(input_text) // 10))
            
            # 모델별 최적화된 파라미터 설정
            summarization_kwargs = self._get_model_specific_params(
                model_name, base_max_length, base_min_length, max_length, len(input_text)
            )
            
            logger.debug(f"요약 파라미터: {summarization_kwargs}")
            
            # 요약 생성 시도
            logger.debug("AI 요약 모델 호출 시작...")
            result = self.summary_model(input_text, **summarization_kwargs)
            logger.debug(f"AI 모델 반환 결과 타입: {type(result)}")
            logger.debug(f"AI 모델 반환 결과 길이: {len(result) if hasattr(result, '__len__') else 'N/A'}")
            
            # 결과 상세 분석
            if result:
                logger.debug(f"결과 내용 미리보기: {str(result)[:200]}...")
                
                # 안전한 결과 추출
                summary = self._extract_summary_safely(result)
                if summary:
                    logger.debug(f"요약 성공: {len(summary)} 문자")
                    return summary
                else:
                    logger.warning("AI 모델이 유효한 요약을 생성하지 못함")
            else:
                logger.warning("AI 모델이 빈 결과 반환")
            
            # 폴백: 간단한 요약 사용
            logger.debug("AI 요약 실패, 간단한 요약으로 폴백")
            return self.simple_summarize(text)
                
        except IndexError as e:
            logger.error(f"AI 요약 중 IndexError 발생: {str(e)}")
            logger.error(f"모델: {getattr(self.summary_model.model.config, 'name_or_path', 'unknown')}")
            logger.error(f"입력 길이: {len(input_text) if 'input_text' in locals() else 'unknown'}")
            return self.simple_summarize(text)
        except Exception as e:
            logger.error(f"AI 요약 중 예외 발생: {type(e).__name__}: {str(e)}")
            logger.error(f"모델: {getattr(self.summary_model.model.config, 'name_or_path', 'unknown') if self.summary_model else 'None'}")
            return self.simple_summarize(text)

def test_various_texts():
    """다양한 텍스트로 요약 테스트"""
    summarizer = SimpleSummarizer()
    summarizer.initialize()
    
    test_cases = [
        # 정상적인 긴 텍스트
        """
        Kiro Chat 파일을 mem-mesh에 import하는 과정에서 AI 요약 기능을 사용할 때 IndexError가 발생하고 있습니다. 
        이 오류는 요약 모델이 예상과 다른 형태의 결과를 반환할 때 발생하는 것으로 보입니다. 
        
        구체적으로는 result[0]에 접근할 때 리스트가 비어있거나, 딕셔너리 구조가 예상과 다를 때 발생합니다.
        이를 해결하기 위해 더 안전한 결과 추출 로직과 상세한 디버깅 로그를 추가했습니다.
        
        요약 모델은 transformers 라이브러리의 pipeline을 사용하며, BART, T5, Pegasus 등 다양한 모델을 지원합니다.
        각 모델별로 최적화된 파라미터를 사용하여 더 나은 요약 품질을 제공하려고 합니다.
        """,
        
        # 짧은 텍스트
        "이것은 매우 짧은 텍스트입니다.",
        
        # 빈 텍스트
        "",
        
        # 특수 문자가 많은 텍스트
        "```python\ndef test():\n    return 'hello'\n```\n이 코드는 테스트 함수입니다.",
        
        # 매우 긴 텍스트
        "이것은 매우 긴 텍스트입니다. " * 200
    ]
    
    for i, text in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"테스트 케이스 {i}")
        print(f"{'='*60}")
        print(f"입력 길이: {len(text)} 문자")
        print(f"입력 미리보기: {text[:100]}...")
        
        try:
            summary = summarizer.ai_summarize(text, max_length=200)
            print(f"\n✅ 요약 성공!")
            print(f"요약 길이: {len(summary)} 문자")
            print(f"요약 내용: {summary}")
        except Exception as e:
            print(f"❌ 요약 실패: {type(e).__name__}: {str(e)}")

if __name__ == "__main__":
    test_various_texts()