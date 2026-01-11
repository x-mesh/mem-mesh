#!/usr/bin/env python3
"""
sqlite-vec 테스트 스크립트 (pysqlite3 사용)
"""

try:
    import pysqlite3.dbapi2 as sqlite3
    print("✅ pysqlite3 사용")
except ImportError:
    import sqlite3
    print("⚠️ 기본 sqlite3 사용")

import sqlite_vec

def test_sqlite_vec():
    print("=== sqlite-vec 테스트 ===")
    
    try:
        # 메모리 데이터베이스 생성
        conn = sqlite3.connect(':memory:')
        print("✅ SQLite 연결 성공")
        print(f"SQLite 버전: {conn.execute('SELECT sqlite_version()').fetchone()[0]}")
        print(f"load_extension 지원: {hasattr(conn, 'load_extension')}")
        
        # sqlite-vec 로드 시도
        try:
            sqlite_vec.load(conn)
            print("✅ sqlite-vec 로드 성공")
        except Exception as e:
            print(f"❌ sqlite-vec 로드 실패: {e}")
            return False
        
        # 벡터 테이블 생성 테스트
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE vec_items USING vec0(
                    embedding float[3]
                )
            """)
            print("✅ 벡터 테이블 생성 성공")
        except Exception as e:
            print(f"❌ 벡터 테이블 생성 실패: {e}")
            return False
        
        # 벡터 데이터 삽입 테스트
        try:
            conn.execute("""
                INSERT INTO vec_items(rowid, embedding) 
                VALUES (1, '[1.0, 2.0, 3.0]')
            """)
            conn.execute("""
                INSERT INTO vec_items(rowid, embedding) 
                VALUES (2, '[4.0, 5.0, 6.0]')
            """)
            print("✅ 벡터 데이터 삽입 성공")
        except Exception as e:
            print(f"❌ 벡터 데이터 삽입 실패: {e}")
            return False
        
        # 벡터 검색 테스트
        try:
            cursor = conn.execute("""
                SELECT rowid, distance 
                FROM vec_items 
                WHERE embedding MATCH '[1.1, 2.1, 3.1]' 
                ORDER BY distance 
                LIMIT 5
            """)
            results = cursor.fetchall()
            print(f"✅ 벡터 검색 성공: {results}")
        except Exception as e:
            print(f"❌ 벡터 검색 실패: {e}")
            return False
        
        # vec_version() 함수 테스트
        try:
            cursor = conn.execute("SELECT vec_version()")
            version = cursor.fetchone()[0]
            print(f"✅ sqlite-vec 버전: {version}")
        except Exception as e:
            print(f"❌ vec_version() 실패: {e}")
            return False
        
        conn.close()
        print("🎉 모든 테스트 통과!")
        return True
        
    except Exception as e:
        print(f"❌ 전체 테스트 실패: {e}")
        return False

if __name__ == "__main__":
    success = test_sqlite_vec()
    exit(0 if success else 1)