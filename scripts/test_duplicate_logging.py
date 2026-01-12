#!/usr/bin/env python3
"""
중복 메시지 로깅 테스트 스크립트
"""
import subprocess
import sys

def test_duplicate_logging():
    """중복 메시지 로깅 기능 테스트"""
    print("🔍 중복 메시지 로깅 테스트 시작...")
    
    # 1. 첫 번째 import (새로운 메시지들)
    print("\n📥 첫 번째 import 실행...")
    try:
        result1 = subprocess.run([
            "python3", "scripts/import_kiro_chat_memmesh.py",
            "--mode", "raw",
            "--limit", "10",
            "-vvv"
        ], capture_output=True, text=True, timeout=120)
        
        print("첫 번째 import 완료")
        if result1.returncode != 0:
            print(f"오류 발생: {result1.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("첫 번째 import 시간 초과")
        return False
    except Exception as e:
        print(f"첫 번째 import 실행 중 오류: {e}")
        return False
    
    # 2. 두 번째 import (중복 메시지들)
    print("\n🔄 두 번째 import 실행 (중복 검출 테스트)...")
    try:
        result2 = subprocess.run([
            "python3", "scripts/import_kiro_chat_memmesh.py",
            "--mode", "raw",
            "--limit", "10",
            "-vvv"
        ], capture_output=True, text=True, timeout=120)
        
        print("두 번째 import 완료")
        if result2.returncode != 0:
            print(f"오류 발생: {result2.stderr}")
            return False
        
        # 중복 메시지 로그 확인
        output = result2.stdout
        if "[중복 메시지]" in output:
            print("✅ 중복 메시지 로깅 확인됨")
            
            # 중복 메시지 수 카운트
            duplicate_count = output.count("[중복 메시지]")
            print(f"검출된 중복 메시지: {duplicate_count}개")
            
            # 상세 로그 샘플 출력
            lines = output.split('\n')
            duplicate_lines = [line for line in lines if "[중복 메시지]" in line]
            
            print("\n📋 중복 메시지 로그 샘플:")
            for i, line in enumerate(duplicate_lines[:3]):  # 처음 3개만
                print(f"  {i+1}. {line.strip()}")
            
            return True
        else:
            print("❌ 중복 메시지 로깅이 확인되지 않음")
            print("출력 샘플:")
            print(output[:500])
            return False
            
    except subprocess.TimeoutExpired:
        print("두 번째 import 시간 초과")
        return False
    except Exception as e:
        print(f"두 번째 import 실행 중 오류: {e}")
        return False

if __name__ == "__main__":
    success = test_duplicate_logging()
    if success:
        print(f"\n🎉 중복 메시지 로깅 테스트 성공!")
        print("이제 -vvv 옵션으로 중복 메시지에 대한 상세한 정보를 확인할 수 있습니다.")
    else:
        print(f"\n💡 테스트 실패. 다음을 확인해보세요:")
        print("1. mem-mesh 서버가 실행 중인지 확인")
        print("2. 데이터베이스 연결이 정상인지 확인")
        print("3. import할 chat 파일이 존재하는지 확인")
    
    sys.exit(0 if success else 1)