#!/usr/bin/env python3
"""
간단한 요약 모델 테스트 스크립트
"""
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_summarization():
    """요약 모델 직접 테스트"""
    try:
        from transformers import pipeline
        
        print("🔍 요약 모델 로드 중...")
        
        # 가벼운 모델부터 시도
        models_to_try = [
            "sshleifer/distilbart-cnn-12-6",  # 가벼운 BART
            "t5-small",                       # T5 small
            "facebook/bart-large-cnn",        # 큰 BART
        ]
        
        summarizer = None
        model_used = None
        
        for model in models_to_try:
            try:
                print(f"모델 시도: {model}")
                summarizer = pipeline(
                    "summarization",
                    model=model,
                    device=-1,  # CPU 사용
                    framework="pt",
                    return_tensors=False,
                    clean_up_tokenization_spaces=True,
                    trust_remote_code=False
                )
                model_used = model
                print(f"✅ 모델 로드 성공: {model}")
                break
            except Exception as e:
                print(f"❌ 모델 로드 실패 {model}: {e}")
                continue
        
        if not summarizer:
            print("❌ 모든 모델 로드 실패")
            return
        
        # 테스트 텍스트
        test_text = """
        Kiro Chat 파일을 mem-mesh에 import하는 과정에서 AI 요약 기능을 사용할 때 IndexError가 발생하고 있습니다. 
        이 오류는 요약 모델이 예상과 다른 형태의 결과를 반환할 때 발생하는 것으로 보입니다. 
        
        구체적으로는 result[0]에 접근할 때 리스트가 비어있거나, 딕셔너리 구조가 예상과 다를 때 발생합니다.
        이를 해결하기 위해 더 안전한 결과 추출 로직과 상세한 디버깅 로그를 추가했습니다.
        
        요약 모델은 transformers 라이브러리의 pipeline을 사용하며, BART, T5, Pegasus 등 다양한 모델을 지원합니다.
        각 모델별로 최적화된 파라미터를 사용하여 더 나은 요약 품질을 제공하려고 합니다.
        """
        
        print(f"\n📝 요약 테스트 시작...")
        print(f"사용 모델: {model_used}")
        print(f"입력 길이: {len(test_text)} 문자")
        
        # 요약 파라미터
        kwargs = {
            "max_length": 150,
            "min_length": 30,
            "do_sample": False,
            "truncation": True
        }
        
        print(f"요약 파라미터: {kwargs}")
        
        # 요약 실행
        result = summarizer(test_text, **kwargs)
        
        print(f"\n🔍 결과 분석:")
        print(f"결과 타입: {type(result)}")
        print(f"결과 길이: {len(result) if hasattr(result, '__len__') else 'N/A'}")
        print(f"결과 내용: {result}")
        
        # 안전한 요약 추출
        if result and isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            print(f"\n첫 번째 항목 타입: {type(first_item)}")
            
            if isinstance(first_item, dict):
                print(f"사용 가능한 키: {list(first_item.keys())}")
                if 'summary_text' in first_item:
                    summary = first_item['summary_text']
                    print(f"\n✅ 요약 성공!")
                    print(f"요약 길이: {len(summary)} 문자")
                    print(f"요약 내용: {summary}")
                else:
                    print("❌ summary_text 키가 없음")
            else:
                print(f"❌ 첫 번째 항목이 딕셔너리가 아님: {first_item}")
        else:
            print("❌ 결과가 비어있거나 예상 형태가 아님")
            
    except ImportError as e:
        print(f"❌ Import 오류: {e}")
        print("필요한 패키지를 설치하세요: pip install transformers torch")
    except Exception as e:
        print(f"❌ 예외 발생: {type(e).__name__}: {e}")
        logger.exception("상세 오류:")

if __name__ == "__main__":
    test_summarization()