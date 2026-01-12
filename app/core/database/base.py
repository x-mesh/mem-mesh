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
                self.connection.close()
                self.connection = None
                logger.info("Database connection closed")
    
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
                            base_query = base_query.replace(
                                "ORDER BY distance", 
                                f"WHERE {' AND '.join(filter_conditions)} ORDER BY distance"
                            )
                    
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
        filters: Optional[Dict[str, Any]] = None
    ) -> List[sqlite3.Row]:
        """최근 메모리 조회 (생성일 기준 내림차순)"""
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
            
            base_query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = await self.execute(base_query, tuple(params))
            return cursor.fetchall()
            
        except Exception as e:
            logger.error(f"Get recent memories failed: {e}")
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
