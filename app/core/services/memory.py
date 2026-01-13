"""
Memory Service for mem-mesh
메모리 CRUD 작업을 담당하는 서비스
"""

import json
import logging
from typing import Optional, List
from datetime import datetime

from ..database.base import Database
from ..database.models import Memory
from ..embeddings.service import EmbeddingService
from ..schemas.requests import AddParams, UpdateParams
from ..schemas.responses import AddResponse, UpdateResponse, DeleteResponse

logger = logging.getLogger(__name__)


class MemoryNotFoundError(Exception):
    """메모리를 찾을 수 없을 때 발생하는 예외"""
    pass


class DatabaseError(Exception):
    """데이터베이스 작업 실패 시 발생하는 예외"""
    pass


class EmbeddingError(Exception):
    """임베딩 생성 실패 시 발생하는 예외"""
    pass


class MemoryService:
    """메모리 저장/조회/삭제/업데이트 서비스"""
    
    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service
        self.max_retries = 3
        logger.info("MemoryService initialized")
    
    async def create(
        self, 
        content: str, 
        project_id: Optional[str] = None,
        category: str = "task", 
        source: str = "unknown", 
        tags: Optional[List[str]] = None
    ) -> AddResponse:
        """
        새 메모리 생성 (중복 감지 포함)
        
        Args:
            content: 메모리 내용
            project_id: 프로젝트 식별자
            category: 메모리 카테고리
            source: 메모리 생성 소스
            tags: 태그 목록
            
        Returns:
            AddResponse: 생성 결과
            
        Raises:
            ValueError: 입력 검증 실패
            EmbeddingError: 임베딩 생성 실패
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info(f"Creating memory with content length: {len(content)}")
        
        # 1. content_hash 계산
        content_hash = Memory.compute_hash(content)
        
        # 2. 중복 체크
        existing_memory = await self._find_duplicate(content_hash, project_id)
        if existing_memory:
            logger.info(f"Duplicate memory found: {existing_memory['id']}")
            return AddResponse(
                id=existing_memory['id'],
                status="duplicate",
                created_at=existing_memory['created_at']
            )
        
        # 3. 임베딩 생성 (재시도 로직 포함)
        embedding_vector = await self._generate_embedding_with_retry(content)
        embedding_bytes = self.embedding_service.to_bytes(embedding_vector)
        
        # 4. Memory 객체 생성
        memory = Memory(
            content=content,
            content_hash=content_hash,
            project_id=project_id,
            category=category,
            source=source,
            embedding=embedding_bytes,
            tags=json.dumps(tags) if tags else None
        )
        
        # 5. DB 저장 (트랜잭션)
        try:
            async with self.db.transaction():
                # memories 테이블에 저장
                await self.db.execute(
                    """
                    INSERT INTO memories 
                    (id, content, content_hash, project_id, category, source, embedding, tags, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory.id,
                        memory.content,
                        memory.content_hash,
                        memory.project_id,
                        memory.category,
                        memory.source,
                        memory.embedding,
                        memory.tags,
                        memory.created_at,
                        memory.updated_at
                    )
                )
                
                # 벡터 인덱스에 저장
                await self._save_to_vector_index(memory.id, embedding_bytes)
                
            logger.info(f"Memory created successfully: {memory.id}")
            return AddResponse(
                id=memory.id,
                status="saved",
                created_at=memory.created_at
            )
            
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            raise DatabaseError(f"Failed to save memory: {e}")
    
    async def get(self, memory_id: str) -> Optional[Memory]:
        """
        ID로 메모리 조회
        
        Args:
            memory_id: 메모리 ID
            
        Returns:
            Memory 객체 또는 None
        """
        logger.debug(f"Getting memory: {memory_id}")
        
        try:
            row = await self.db.fetchone(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,)
            )
            
            if row is None:
                return None
            
            # SQLite Row를 Memory 객체로 변환
            memory_dict = dict(row)
            return Memory(**memory_dict)
            
        except Exception as e:
            logger.error(f"Failed to get memory {memory_id}: {e}")
            raise DatabaseError(f"Failed to get memory: {e}")
    
    async def update(
        self, 
        memory_id: str, 
        content: Optional[str] = None,
        category: Optional[str] = None, 
        tags: Optional[List[str]] = None
    ) -> UpdateResponse:
        """
        메모리 업데이트 (content 변경 시 재임베딩)
        
        Args:
            memory_id: 업데이트할 메모리 ID
            content: 새로운 내용 (선택적)
            category: 새로운 카테고리 (선택적)
            tags: 새로운 태그 목록 (선택적)
            
        Returns:
            UpdateResponse: 업데이트 결과
            
        Raises:
            MemoryNotFoundError: 메모리를 찾을 수 없음
            EmbeddingError: 임베딩 생성 실패
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info(f"Updating memory: {memory_id}")
        
        # 1. 기존 메모리 조회
        existing_memory = await self.get(memory_id)
        if existing_memory is None:
            raise MemoryNotFoundError(f"Memory not found: {memory_id}")
        
        # 2. 업데이트할 필드 결정
        content_changed = content is not None and content != existing_memory.content
        
        try:
            async with self.db.transaction():
                if content_changed:
                    # content가 변경된 경우: 재임베딩 필요
                    logger.info("Content changed, regenerating embedding")
                    
                    # 새로운 임베딩 생성
                    embedding_vector = await self._generate_embedding_with_retry(content)
                    embedding_bytes = self.embedding_service.to_bytes(embedding_vector)
                    
                    # content_hash 재계산
                    content_hash = Memory.compute_hash(content)
                    
                    # 업데이트 쿼리
                    await self.db.execute(
                        """
                        UPDATE memories 
                        SET content = ?, content_hash = ?, category = ?, tags = ?, 
                            embedding = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            content,
                            content_hash,
                            category or existing_memory.category,
                            json.dumps(tags) if tags is not None else existing_memory.tags,
                            embedding_bytes,
                            datetime.utcnow().isoformat() + 'Z',
                            memory_id
                        )
                    )
                    
                    # 벡터 인덱스 업데이트
                    await self._update_vector_index(memory_id, embedding_bytes)
                    
                else:
                    # metadata만 변경된 경우: 임베딩 유지
                    logger.info("Only metadata changed, keeping existing embedding")
                    
                    await self.db.execute(
                        """
                        UPDATE memories 
                        SET category = ?, tags = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            category or existing_memory.category,
                            json.dumps(tags) if tags is not None else existing_memory.tags,
                            datetime.utcnow().isoformat() + 'Z',
                            memory_id
                        )
                    )
                
            logger.info(f"Memory updated successfully: {memory_id}")
            return UpdateResponse(
                id=memory_id,
                status="updated"
            )
            
        except Exception as e:
            logger.error(f"Failed to update memory {memory_id}: {e}")
            raise DatabaseError(f"Failed to update memory: {e}")
    
    async def delete(self, memory_id: str) -> DeleteResponse:
        """
        메모리 삭제 (SQLite + 벡터 인덱스)
        
        Args:
            memory_id: 삭제할 메모리 ID
            
        Returns:
            DeleteResponse: 삭제 결과
            
        Raises:
            MemoryNotFoundError: 메모리를 찾을 수 없음
            DatabaseError: 데이터베이스 작업 실패
        """
        logger.info(f"Deleting memory: {memory_id}")
        
        # 1. 메모리 존재 확인
        existing_memory = await self.get(memory_id)
        if existing_memory is None:
            raise MemoryNotFoundError(f"Memory not found: {memory_id}")
        
        try:
            async with self.db.transaction():
                # 2. SQLite에서 삭제
                await self.db.execute(
                    "DELETE FROM memories WHERE id = ?",
                    (memory_id,)
                )
                
                # 3. 벡터 인덱스에서 삭제
                await self._delete_from_vector_index(memory_id)
                
                # 4. related_memory_ids 참조 정리
                # 현재 스키마에는 related_memory_ids 필드가 없으므로 
                # Context 서비스에서 동적으로 관계를 계산함
                logger.debug(f"Memory {memory_id} deleted, no related_memory_ids cleanup needed")
                
            logger.info(f"Memory deleted successfully: {memory_id}")
            return DeleteResponse(
                id=memory_id,
                status="deleted"
            )
            
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            raise DatabaseError(f"Failed to delete memory: {e}")
    
    # Private helper methods
    
    async def _find_duplicate(self, content_hash: str, project_id: Optional[str]) -> Optional[dict]:
        """중복 메모리 검색"""
        try:
            row = await self.db.fetchone(
                "SELECT id, created_at FROM memories WHERE content_hash = ? AND project_id = ?",
                (content_hash, project_id)
            )
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to check for duplicates: {e}")
            raise DatabaseError(f"Failed to check for duplicates: {e}")
    
    async def _generate_embedding_with_retry(self, content: str) -> List[float]:
        """재시도 로직을 포함한 임베딩 생성"""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Generating embedding (attempt {attempt + 1}/{self.max_retries})")
                return self.embedding_service.embed(content)
                
            except Exception as e:
                last_error = e
                logger.warning(f"Embedding generation failed (attempt {attempt + 1}): {e}")
                
                if attempt < self.max_retries - 1:
                    # 지수 백오프
                    import asyncio
                    delay = 0.1 * (2 ** attempt)
                    await asyncio.sleep(min(delay, 1.0))
        
        logger.error(f"Embedding generation failed after {self.max_retries} attempts")
        raise EmbeddingError(f"Failed to generate embedding after {self.max_retries} attempts: {last_error}")
    
    async def _save_to_vector_index(self, memory_id: str, embedding_bytes: bytes) -> None:
        """벡터 인덱스에 저장"""
        try:
            # sqlite-vec 테이블이 존재하는지 확인 (올바른 테이블 이름 사용)
            cursor = await self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='memory_embeddings'
            """)
            
            if cursor.fetchone():
                # sqlite-vec 사용 - embedding을 JSON 형식으로 변환
                import json
                import numpy as np
                
                # bytes를 numpy array로 변환
                embedding_array = np.frombuffer(embedding_bytes, dtype=np.float32)
                # JSON 문자열로 변환
                embedding_json = json.dumps(embedding_array.tolist())
                
                # vector 테이블에 저장 (DELETE + INSERT 패턴 사용)
                await self.db.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?",
                    (memory_id,)
                )
                await self.db.execute(
                    "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, embedding_json)
                )
                logger.debug(f"Saved to vector table: {memory_id}")
            else:
                # fallback 테이블 사용
                await self.db.execute(
                    "INSERT INTO memories_vec_fallback (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, embedding_bytes)
                )
                logger.debug(f"Saved to fallback table: {memory_id}")
                
        except Exception as e:
            logger.error(f"Failed to save to vector index: {e}")
            raise
    
    async def _update_vector_index(self, memory_id: str, embedding_bytes: bytes) -> None:
        """벡터 인덱스 업데이트"""
        try:
            # sqlite-vec 테이블이 존재하는지 확인 (올바른 테이블 이름 사용)
            cursor = await self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='memory_embeddings'
            """)
            
            if cursor.fetchone():
                # sqlite-vec 사용 - embedding을 JSON 형식으로 변환
                import json
                import numpy as np
                
                # bytes를 numpy array로 변환
                embedding_array = np.frombuffer(embedding_bytes, dtype=np.float32)
                # JSON 문자열로 변환
                embedding_json = json.dumps(embedding_array.tolist())
                
                # vector 테이블 업데이트 (DELETE + INSERT 패턴 사용)
                await self.db.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?",
                    (memory_id,)
                )
                await self.db.execute(
                    "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, embedding_json)
                )
                logger.debug(f"Updated vector table: {memory_id}")
            else:
                # fallback 테이블 사용
                await self.db.execute(
                    "UPDATE memories_vec_fallback SET embedding = ? WHERE memory_id = ?",
                    (embedding_bytes, memory_id)
                )
                logger.debug(f"Updated fallback table: {memory_id}")
                
        except Exception as e:
            logger.error(f"Failed to update vector index: {e}")
            raise
    
    async def _delete_from_vector_index(self, memory_id: str) -> None:
        """벡터 인덱스에서 삭제"""
        try:
            # sqlite-vec 테이블이 존재하는지 확인 (올바른 테이블 이름 사용)
            cursor = await self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='memory_embeddings'
            """)
            
            if cursor.fetchone():
                # sqlite-vec 사용
                await self.db.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?",
                    (memory_id,)
                )
                logger.debug(f"Deleted from vector table: {memory_id}")
            else:
                # fallback 테이블 사용
                await self.db.execute(
                    "DELETE FROM memories_vec_fallback WHERE memory_id = ?",
                    (memory_id,)
                )
                logger.debug(f"Deleted from fallback table: {memory_id}")
                
        except Exception as e:
            logger.error(f"Failed to delete from vector index: {e}")
            raise
