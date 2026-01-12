#!/usr/bin/env python3
"""
요약 모델 디버깅 스크립트

사용법:
    python scripts/debug_summarization.py [--model MODEL_NAME] [--text "텍스트"]
"""
import sys
import argparse
import logging
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.import_kiro_chat_memmesh import KiroChatImporter, ImportMode

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_summarization_model(model_name: str, test_text: str):
    """요약 모델 테스트"""
    print(f"\n{'='*60}")
    print(f"요약 모델 디버깅 테스트")
    print(f"{'='*60}")
    print(f"모델: {model_name}")
    print(f"입력 텍스트 길이: {len(test_text)} 문자")
    print(f"{'='*60}\n")
    
    # KiroChatImporter 인스턴스 생성
    importer = KiroChatImporter(
        mode=ImportMode.SUMMARY,
        summary_model=model_name,
        verbose_level=3,  # 최대 상세 로그
        dry_run=True
    )
    
    try:
        # 비동기 초기화를 동기적으로 실행
        import asyncio
        asyncio.run(importer.initialize())
        
        print("🔍 모델 초기화 완료\n")
        
        # 요약 테스트
        print("📝 요약 테스트 시작...")
        summary = importer.ai_summarize(test_text, max_length=200)
        
        print(f"\n✅ 요약 완료!")
        print(f"원본 길이: {len(test_text)} 문자")
        print(f"요약 길이: {len(summary)} 문자")
        print(f"압축률: {len(summary)/len(test_text)*100:.1f}%")
        
        print(f"\n📄 원본 텍스트:")
        print("-" * 40)
        print(test_text[:500] + ("..." if len(test_text) > 500 else ""))
        
        print(f"\n✨ 요약 결과:")
        print("-" * 40)
        print(summary)
        
    except Exception as e:
        print(f"❌ 오류 발생: {type(e).__name__}: {str(e)}")
        logger.exception("상세 오류 정보:")
    
    finally:
        # 정리
        try:
            asyncio.run(importer.shutdown())
        except:
            pass

def main():
    parser = argparse.ArgumentParser(description="요약 모델 디버깅")
    parser.add_argument(
        "--model",
        default="sshleifer/distilbart-cnn-12-6",
        help="테스트할 요약 모델 (기본: sshleifer/distilbart-cnn-12-6)"
    )
    parser.add_argument(
        "--text",
        help="요약할 텍스트 (기본: 샘플 텍스트 사용)"
    )
    
    args = parser.parse_args()
    
    # 기본 테스트 텍스트
    default_text = """
    Kiro Chat 파일을 mem-mesh에 import하는 과정에서 AI 요약 기능을 사용할 때 IndexError가 발생하고 있습니다. 
    이 오류는 요약 모델이 예상과 다른 형태의 결과를 반환할 때 발생하는 것으로 보입니다. 
    
    구체적으로는 result[0]에 접근할 때 리스트가 비어있거나, 딕셔너리 구조가 예상과 다를 때 발생합니다.
    이를 해결하기 위해 더 안전한 결과 추출 로직과 상세한 디버깅 로그를 추가했습니다.
    
    요약 모델은 transformers 라이브러리의 pipeline을 사용하며, BART, T5, Pegasus 등 다양한 모델을 지원합니다.
    각 모델별로 최적화된 파라미터를 사용하여 더 나은 요약 품질을 제공하려고 합니다.
    
    또한 모델 로드 실패 시 간단한 텍스트 요약으로 폴백하는 메커니즘도 구현되어 있습니다.
    이를 통해 요약 기능이 완전히 실패하지 않고 최소한의 기능은 제공할 수 있도록 했습니다.
    """
    
    test_text = args.text or default_text.strip()
    test_summarization_model(args.model, test_text)

if __name__ == "__main__":
    main()