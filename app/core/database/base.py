"""Database connection and initialization for mem-mesh.

This module provides SQLite database connection with WAL mode support
and sqlite-vec extension for vector search capabilities.

Requirements: 4.1, 4.4 - SQLite WAL mode and busy_timeout configuration
"""

# pysqlite3를 우선적으로 사용 (extension loading 지원)
try:
    import pysqlite3.dbapi2 as sqlite3
    SQLITE3_MODULE = "pysqlite3"
except ImportError:
    import sqlite3
    SQLITE3_MODULE = "sqlite3"

import asyncio
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple
from contextlib import asynccontextmanager
import logging

try:
    import sqlite_vec
    # SQLite extension loading 지원 여부 확인
    test_conn = sqlite3.connect(':memory:')
    if hasattr(test_conn, 'load_extension'):
        SQLITE_VEC_AVAILABLE = True
        logger = logging.getLogger(__name__)
        logger.info(f"sqlite-vec available with {SQLITE3_MODULE} (extension loading supported)")
    else:
        SQLITE_VEC_AVAILABLE = False
        logger = logging.getLogger(__name__)
        logger.warning(f"sqlite-vec available with {SQLITE3_MODULE} but extension loading not supported")
    test_conn.close()
except ImportError:
    SQLITE_VEC_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("sqlite-vec Python package not available")

logger = logging.getLogger(__name__)


class Database:
    """SQLite + sqlite-vec 데이터베이스 연결 및 쿼리 관리
    
    Requirements:
    - 4.1: WAL 모드 활성화
    - 4.4: busy_timeout 설정
    """
    
    def __init__(self, db_path: str, busy_timeout: int = 5000):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
            busy_timeout: SQLite busy timeout in milliseconds (default: 5000)
        """
        self.db_path = db_path
        self.busy_timeout = busy_timeout
        self.connection: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()
    
    async def connect(self) -> None:
        """DB 연결 및 sqlite-vec 확장 로드"""
        async with self._lock:
            if self.connection is not None:
                return
            
            # 데이터베이스 디렉토리 생성
            db_path = Path(self.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                # SQLite 연결 생성
                self.connection = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    isolation_level=None  # autocommit mode
                )
                
                # Row factory 설정 (dict 형태로 결과 반환)
                self.connection.row_factory = sqlite3.Row
                
                # busy_timeout 설정 (Requirement 4.4)
                self.connection.execute(f"PRAGMA busy_timeout={self.busy_timeout}")
                logger.info(f"SQLite busy_timeout set to {self.busy_timeout}ms")
                
                # WAL 모드 활성화 (Requirement 4.1)
                self.connection.execute("PRAGMA journal_mode=WAL")
                logger.info("SQLite WAL mode enabled")
                
                # Foreign key 제약 조건 활성화
                self.connection.execute("PRAGMA foreign_keys=ON")
                
                # sqlite-vec 로드 시도 (여러 방법)
                vec_loaded = False
                
                if SQLITE_VEC_AVAILABLE:
                    try:
                        # 방법 1: sqlite-vec Python 패키지로 로드
                        sqlite_vec.load(self.connection)
                        logger.info("sqlite-vec loaded via Python package")
                        vec_loaded = True
                    except Exception as e:
                        logger.warning(f"Failed to load sqlite-vec via Python package: {e}")
                
                # 방법 2: 직접 extension 로드 시도
                if not vec_loaded and hasattr(self.connection, 'load_extension'):
                    try:
                        # macOS에서 sqlite-vec extension 직접 로드 시도
                        self.connection.enable_load_extension(True)
                        self.connection.load_extension("vec0")
                        logger.info("sqlite-vec loaded via direct extension loading")
                        vec_loaded = True
                    except Exception as e:
                        logger.warning(f"Failed to load sqlite-vec via extension: {e}")
                    finally:
                        try:
                            self.connection.enable_load_extension(False)
                        except:
                            pass
                
                # 방법 3: 벡터 테이블 생성 테스트
                if vec_loaded:
                    try:
                        # 벡터 기능 테스트
                        self.connection.execute("SELECT vec_version()")
                        logger.info("sqlite-vec vector functions are available")
                    except Exception as e:
                        logger.warning(f"sqlite-vec loaded but vector functions not available: {e}")
                        vec_loaded = False
                
                if not vec_loaded:
                    logger.warning("sqlite-vec not available, using fallback text search only")
                
                # 테이블 및 인덱스 초기화
                await self.init_tables()
                
                logger.info(f"Database connected: {self.db_path}")
                
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                if self.connection:
                    self.connection.close()
                    self.connection = None
                raise
    
    async def init_tables(self) -> None:
        """테이블 및 인덱스 생성"""
        if not self.connection:
            raise RuntimeError("Database not connected")
        
        try:
            # memories 테이블 생성
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    project_id TEXT,
                    category TEXT NOT NULL DEFAULT 'task',
                    source TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    tags TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # embedding_metadata 테이블 생성 (모델 정보 저장용)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS embedding_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # 인덱스 생성
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_memories_project_id ON memories(project_id)",
                "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)",
                "CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash)"
            ]
            
            for index_sql in indexes:
                self.connection.execute(index_sql)
            
            # sqlite-vec 가상 테이블 생성 (Python 패키지가 로드된 경우에만)
            if SQLITE_VEC_AVAILABLE:
                try:
                    # vec0 함수가 사용 가능한지 테스트
                    test_result = self.connection.execute("SELECT vec_version()").fetchone()
                    if test_result:
                        # 실제 vector 검색용 테이블 생성
                        self.connection.execute("""
                            CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
                                memory_id TEXT PRIMARY KEY,
                                embedding FLOAT[384]
                            )
                        """)
                        logger.info("Vector table 'memory_embeddings' created successfully with sqlite-vec")
                        
                        # 기존 메모리들의 embedding을 vector 테이블로 마이그레이션
                        await self._migrate_embeddings_to_vector_table()
                        
                    else:
                        raise Exception("vec_version() not available")
                except Exception as e:
                    logger.warning(f"Failed to create vector table: {e}")
            
            # Fallback 테이블은 항상 생성 (MemoryService에서 사용)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS memories_vec_fallback (
                    memory_id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL
                )
            """)
            logger.info("Created fallback vector table")
            
            self.connection.commit()
            logger.info("Database tables and indexes initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize tables: {e}")
            raise
    
    # ===== Embedding Metadata Methods =====
    
    async def get_embedding_metadata(self, key: str) -> Optional[str]:
        """임베딩 메타데이터 조회"""
        try:
            row = await self.fetchone(
                "SELECT value FROM embedding_metadata WHERE key = ?",
                (key,)
            )
            return row['value'] if row else None
        except Exception as e:
            logger.error(f"Failed to get embedding metadata: {e}")
            return None
    
    async def set_embedding_metadata(self, key: str, value: str) -> None:
        """임베딩 메타데이터 저장"""
        from datetime import datetime
        try:
            await self.execute(
                """
                INSERT OR REPLACE INTO embedding_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, datetime.utcnow().isoformat() + 'Z')
            )
            self.connection.commit()
            logger.info(f"Embedding metadata set: {key}={value}")
        except Exception as e:
            logger.error(f"Failed to set embedding metadata: {e}")
            raise
    
    async def check_embedding_model_consistency(self, current_model: str, current_dim: int) -> dict:
        """
        현재 설정된 임베딩 모델과 DB에 저장된 모델 정보 비교
        
        Returns:
            {
                "consistent": bool,
                "stored_model": str or None,
                "stored_dim": int or None,
                "current_model": str,
                "current_dim": int,
                "needs_migration": bool,
                "message": str
            }
        """
        stored_model = await self.get_embedding_metadata("embedding_model")
        stored_dim_str = await self.get_embedding_metadata("embedding_dimension")
        stored_dim = int(stored_dim_str) if stored_dim_str else None
        
        result = {
            "consistent": True,
            "stored_model": stored_model,
            "stored_dim": stored_dim,
            "current_model": current_model,
            "current_dim": current_dim,
            "needs_migration": False,
            "message": ""
        }
        
        # 첫 실행인 경우 (메타데이터 없음)
        if stored_model is None:
            # 기존 데이터가 있는지 확인
            cursor = await self.execute("SELECT COUNT(*) as count FROM memories")
            count = cursor.fetchone()['count']
            
            if count > 0:
                # 기존 데이터가 있지만 메타데이터가 없음 - 마이그레이션 필요할 수 있음
                result["message"] = f"⚠️ 기존 메모리 {count}개가 있지만 임베딩 모델 정보가 없습니다. 현재 모델({current_model})로 메타데이터를 설정합니다."
                logger.warning(result["message"])
                # 현재 모델로 메타데이터 설정
                await self.set_embedding_metadata("embedding_model", current_model)
                await self.set_embedding_metadata("embedding_dimension", str(current_dim))
            else:
                # 새 DB - 현재 모델로 메타데이터 설정
                result["message"] = f"✅ 새 데이터베이스입니다. 임베딩 모델: {current_model} (dim: {current_dim})"
                await self.set_embedding_metadata("embedding_model", current_model)
                await self.set_embedding_metadata("embedding_dimension", str(current_dim))
            
            return result
        
        # 모델 불일치 확인
        if stored_model != current_model:
            result["consistent"] = False
            result["needs_migration"] = True
            result["message"] = f"⚠️ 임베딩 모델 불일치!\n  - DB 저장 모델: {stored_model}\n  - 현재 설정 모델: {current_model}\n  마이그레이션이 필요합니다: python scripts/migrate_embeddings.py"
            logger.warning(result["message"])
        elif stored_dim and stored_dim != current_dim:
            result["consistent"] = False
            result["needs_migration"] = True
            result["message"] = f"⚠️ 임베딩 차원 불일치!\n  - DB 저장 차원: {stored_dim}\n  - 현재 설정 차원: {current_dim}\n  마이그레이션이 필요합니다."
            logger.warning(result["message"])
        else:
            result["message"] = f"✅ 임베딩 모델 일치: {current_model} (dim: {current_dim})"
            logger.info(result["message"])
        
        return result
    
    async def _migrate_embeddings_to_vector_table(self) -> None:
        """기존 메모리들의 embedding을 vector 테이블로 마이그레이션"""
        try:
            # 기존 메모리들 조회
            cursor = await self.execute("SELECT id, embedding FROM memories WHERE embedding IS NOT NULL")
            memories = cursor.fetchall()
            
            if not memories:
                logger.info("No memories with embeddings found for migration")
                return
            
            # vector 테이블에 이미 데이터가 있는지 확인
            cursor = await self.execute("SELECT COUNT(*) as count FROM memory_embeddings")
            existing_count = cursor.fetchone()['count']
            
            if existing_count > 0:
                logger.info(f"Vector table already has {existing_count} embeddings, skipping migration")
                return
            
            # embedding들을 vector 테이블로 마이그레이션
            migrated_count = 0
            for memory in memories:
                try:
                    # embedding을 JSON 문자열로 변환 (sqlite-vec 형식)
                    import json
                    import numpy as np
                    
                    # BLOB에서 numpy array로 변환
                    embedding_array = np.frombuffer(memory['embedding'], dtype=np.float32)
                    # JSON 문자열로 변환
                    embedding_json = json.dumps(embedding_array.tolist())
                    
                    # vector 테이블에 삽입
                    await self.execute(
                        "INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                        (memory['id'], embedding_json)
                    )
                    migrated_count += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to migrate embedding for memory {memory['id']}: {e}")
                    continue
            
            self.connection.commit()
            logger.info(f"Successfully migrated {migrated_count} embeddings to vector table")
            
        except Exception as e:
            logger.error(f"Embedding migration failed: {e}")
            # 마이그레이션 실패해도 계속 진행
    
    async def close(self) -> None:
        """데이터베이스 연결 종료"""
        async with self._lock:
            if self.connection:
                try:
                    # 진행 중인 트랜잭션 커밋
                    self.connection.commit()
                except Exception as e:
                    logger.warning(f"Error committing final transaction: {e}")
                
                try:
                    # WAL 체크포인트 실행 (변경사항을 메인 DB 파일에 반영)
                    self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception as e:
                    logger.warning(f"Error during WAL checkpoint: {e}")
                
                try:
                    # 연결 종료
                    self.connection.close()
                    logger.info("Database connection closed")
                except Exception as e:
                    logger.warning(f"Error closing database connection: {e}")
                finally:
                    self.connection = None
    
    async def execute(self, query: str, params: Tuple = ()) -> sqlite3.Cursor:
        """쿼리 실행"""
        if not self.connection:
            raise RuntimeError("Database not connected")
        
        try:
            cursor = self.connection.execute(query, params)
            return cursor
        except Exception as e:
            logger.error(f"Query execution failed: {query}, params: {params}, error: {e}")
            raise
    
    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        """단일 행 조회"""
        cursor = await self.execute(query, params)
        return cursor.fetchone()
    
    async def fetchall(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """모든 행 조회"""
        cursor = await self.execute(query, params)
        return cursor.fetchall()
    
    async def vector_search(
        self, 
        embedding: bytes, 
        limit: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple]:
        """벡터 유사도 검색"""
        if not self.connection:
            raise RuntimeError("Database not connected")
        
        # sqlite-vec가 사용 가능한 경우 벡터 검색 수행
        if SQLITE_VEC_AVAILABLE:
            try:
                # 벡터 테이블이 존재하는지 확인
                cursor = await self.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='memory_embeddings'
                """)
                
                if cursor.fetchone():
                    # embedding을 JSON 문자열로 변환
                    import json
                    import numpy as np
                    
                    # BLOB에서 numpy array로 변환
                    embedding_array = np.frombuffer(embedding, dtype=np.float32)
                    # JSON 문자열로 변환
                    embedding_json = json.dumps(embedding_array.tolist())
                    
                    # 벡터 검색 수행
                    base_query = """
                        SELECT m.*, ve.distance 
                        FROM memories m
                        JOIN (
                            SELECT memory_id, distance 
                            FROM memory_embeddings 
                            WHERE embedding MATCH ? 
                            ORDER BY distance 
                            LIMIT ?
                        ) ve ON m.id = ve.memory_id
                    """
                    params = [embedding_json, limit]
                    
                    # 필터 조건 추가
                    if filters:
                        filter_conditions = []
                        if filters.get('project_id'):
                            filter_conditions.append("m.project_id = ?")
                            params.append(filters['project_id'])
                        if filters.get('category'):
                            filter_conditions.append("m.category = ?")
                            params.append(filters['category'])
                        
                        if filter_conditions:
                            base_query += f" WHERE {' AND '.join(filter_conditions)}"
                    
                    base_query += " ORDER BY ve.distance"
                    
                    cursor = await self.execute(base_query, tuple(params))
                    results = cursor.fetchall()
                    
                    if results:
                        logger.info(f"Vector search found {len(results)} results")
                        return results
                    else:
                        logger.info("Vector search returned no results, falling back to text search")
                else:
                    logger.info("Vector table not found, falling back to text search")
            except Exception as e:
                logger.warning(f"Vector search failed: {e}, falling back to text search")
        
        # Fallback to text-based search
        logger.info("Using fallback text search (vector search not available)")
        return await self._fallback_search(limit, filters)
    
    async def _fallback_search(
        self,
        limit: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple]:
        """벡터 검색이 불가능할 때 사용하는 fallback 검색"""
        base_query = "SELECT * FROM memories WHERE 1=1"
        params = []
        
        if filters:
            if filters.get('project_id'):
                base_query += " AND project_id = ?"
                params.append(filters['project_id'])
            if filters.get('category'):
                base_query += " AND category = ?"
                params.append(filters['category'])
        
        base_query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor = await self.execute(base_query, tuple(params))
        return cursor.fetchall()
    
    async def get_recent_memories(
        self,
        limit: int,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_direction: str = "desc",
        filters: Optional[Dict[str, Any]] = None
    ) -> List[sqlite3.Row]:
        """최근 메모리 조회 (페이지네이션 및 정렬 지원)"""
        if not self.connection:
            raise RuntimeError("Database not connected")
        
        try:
            base_query = "SELECT * FROM memories WHERE 1=1"
            params = []
            
            # 필터 조건 추가
            if filters:
                if filters.get('project_id'):
                    base_query += " AND project_id = ?"
                    params.append(filters['project_id'])
                if filters.get('category'):
                    base_query += " AND category = ?"
                    params.append(filters['category'])
                if filters.get('source'):
                    base_query += " AND source = ?"
                    params.append(filters['source'])
                if filters.get('tag'):
                    # 태그는 JSON 배열에서 검색
                    base_query += " AND JSON_EXTRACT(tags, '$') LIKE ?"
                    params.append(f'%"{filters["tag"]}"%')
            
            # 정렬 추가
            valid_sort_columns = ['created_at', 'updated_at', 'category', 'project_id', 'source']
            if sort_by not in valid_sort_columns:
                sort_by = 'created_at'
            
            sort_direction = sort_direction.upper()
            if sort_direction not in ['ASC', 'DESC']:
                sort_direction = 'DESC'
            
            # size로 정렬하는 경우 content 길이 사용
            if sort_by == 'size':
                base_query += f" ORDER BY LENGTH(content) {sort_direction}"
            elif sort_by == 'project':
                base_query += f" ORDER BY project_id {sort_direction}"
            else:
                base_query += f" ORDER BY {sort_by} {sort_direction}"
            
            # 페이지네이션 추가
            base_query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = await self.execute(base_query, tuple(params))
            return cursor.fetchall()
            
        except Exception as e:
            logger.error(f"Get recent memories failed: {e}")
            raise
    
    async def count_memories(
        self,
        filters: Optional[Dict[str, Any]] = None
    ) -> int:
        """메모리 총 개수 조회"""
        if not self.connection:
            raise RuntimeError("Database not connected")
        
        try:
            base_query = "SELECT COUNT(*) as count FROM memories WHERE 1=1"
            params = []
            
            # 필터 조건 추가
            if filters:
                if filters.get('project_id'):
                    base_query += " AND project_id = ?"
                    params.append(filters['project_id'])
                if filters.get('category'):
                    base_query += " AND category = ?"
                    params.append(filters['category'])
                if filters.get('source'):
                    base_query += " AND source = ?"
                    params.append(filters['source'])
                if filters.get('tag'):
                    # 태그는 JSON 배열에서 검색
                    base_query += " AND JSON_EXTRACT(tags, '$') LIKE ?"
                    params.append(f'%"{filters["tag"]}"%')
            
            cursor = await self.execute(base_query, tuple(params))
            result = cursor.fetchone()
            return result['count'] if result else 0
            
        except Exception as e:
            logger.error(f"Count memories failed: {e}")
            raise
    
    @asynccontextmanager
    async def transaction(self):
        """트랜잭션 컨텍스트 매니저"""
        if not self.connection:
            raise RuntimeError("Database not connected")
        
        async with self._lock:
            try:
                self.connection.execute("BEGIN")
                yield
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise
    
    def __del__(self):
        """소멸자에서 연결 정리"""
        if self.connection:
            self.connection.close()
