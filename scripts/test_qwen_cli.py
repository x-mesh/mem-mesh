#!/usr/bin/env python3
"""
qwen-cli 요약 기능 테스트 스크립트
"""
import subprocess
import sys

def test_qwen_cli():
    """qwen-cli 사용 가능 여부 및 요약 기능 테스트"""
    print("🔍 qwen-cli 테스트 시작...")
    
    # 1. qwen 명령어 존재 여부 확인
    try:
        result = subprocess.run(["qwen", "--help"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ qwen 명령어 사용 가능")
        else:
            print("❌ qwen 명령어를 찾을 수 없습니다")
            print("qwen-cli를 설치하고 PATH에 추가하세요")
            return False
    except FileNotFoundError:
        print("❌ qwen 명령어를 찾을 수 없습니다")
        print("qwen-cli를 설치하고 PATH에 추가하세요")
        return False
    except Exception as e:
        print(f"❌ qwen 명령어 확인 중 오류: {e}")
        return False
    
    # 2. 간단한 요약 테스트
    test_text = """
    Kiro Chat 파일을 mem-mesh에 import하는 과정에서 AI 요약 기능을 사용할 때 IndexError가 발생하고 있습니다. 
    이 오류는 요약 모델이 예상과 다른 형태의 결과를 반환할 때 발생하는 것으로 보입니다. 
    
    구체적으로는 result[0]에 접근할 때 리스트가 비어있거나, 딕셔너리 구조가 예상과 다를 때 발생합니다.
    이를 해결하기 위해 더 안전한 결과 추출 로직과 상세한 디버깅 로그를 추가했습니다.
    """
    
    summary_prompt = f"""다음 텍스트를 한국어로 간결하게 요약해주세요. 주요 내용과 핵심 포인트를 포함하여 100자 이내로 요약하세요:

{test_text.strip()}

요약:"""
    
    print(f"\n📝 요약 테스트 실행...")
    print(f"입력 텍스트 길이: {len(test_text)} 문자")
    
    try:
        result = subprocess.run(
            ["qwen", "--prompt", summary_prompt],
            capture_output=True,
            text=True,
            timeout=60,
            encoding='utf-8'
        )
        
        print(f"qwen 실행 완료. 반환 코드: {result.returncode}")
        
        if result.returncode == 0:
            summary = result.stdout.strip()
            print(f"\n✅ 요약 성공!")
            print(f"요약 길이: {len(summary)} 문자")
            print(f"\n📄 원본 텍스트:")
            print("-" * 40)
            print(test_text.strip())
            print(f"\n✨ qwen-cli 요약 결과:")
            print("-" * 40)
            print(summary)
            return True
        else:
            print(f"❌ qwen 실행 실패. 반환 코드: {result.returncode}")
            if result.stderr:
                print(f"오류 메시지: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ qwen 실행 시간 초과 (60초)")
        return False
    except Exception as e:
        print(f"❌ qwen 실행 중 오류: {e}")
        return False

if __name__ == "__main__":
    success = test_qwen_cli()
    if success:
        print(f"\n🎉 qwen-cli 테스트 성공!")
        print("이제 다음 명령어로 qwen-cli를 사용할 수 있습니다:")
        print("python3 scripts/import_kiro_chat_memmesh.py --mode summary --summary-model qwen-cli")
    else:
        print(f"\n💡 qwen-cli 설치 방법:")
        print("1. qwen-cli를 설치하세요")
        print("2. qwen 명령어가 PATH에 있는지 확인하세요")
        print("3. 'qwen --help' 명령어가 작동하는지 확인하세요")
    
    sys.exit(0 if success else 1)