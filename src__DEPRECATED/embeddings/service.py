"""
Embedding Service for mem-mesh
텍스트를 벡터로 변환하는 서비스
"""

import struct
import logging
from typing import Optional
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingService:
    """임베딩 생성 서비스"""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model: Optional[SentenceTransformer] = None
        self.model_name = model_name
        self.dimension = 384
        logger.info(f"EmbeddingService initialized with model: {model_name}")
    
    def load_model(self) -> None:
        """모델 로드 (lazy loading)"""
        if self.model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            try:
                self.model = SentenceTransformer(self.model_name)
                logger.info(f"Model {self.model_name} loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load model {self.model_name}: {e}")
                raise
    
    def embed(self, text: str) -> list[float]:
        """단일 텍스트 임베딩"""
        if self.model is None:
            self.load_model()
        
        try:
            # sentence-transformers는 numpy array를 반환하므로 list로 변환
            embedding = self.model.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to generate embedding for text: {e}")
            raise
    
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """배치 임베딩"""
        if self.model is None:
            self.load_model()
        
        try:
            embeddings = self.model.encode(texts, convert_to_tensor=False)
            return [embedding.tolist() for embedding in embeddings]
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            raise
    
    def to_bytes(self, embedding: list[float]) -> bytes:
        """임베딩을 bytes로 변환 (SQLite 저장용)"""
        if len(embedding) != self.dimension:
            raise ValueError(f"Expected embedding dimension {self.dimension}, got {len(embedding)}")
        
        # float32로 패킹하여 bytes로 변환
        return struct.pack(f'{len(embedding)}f', *embedding)
    
    def from_bytes(self, data: bytes) -> list[float]:
        """bytes를 임베딩으로 변환"""
        expected_size = self.dimension * 4  # float32 = 4 bytes
        if len(data) != expected_size:
            raise ValueError(f"Expected {expected_size} bytes, got {len(data)}")
        
        # bytes를 float32 리스트로 언패킹
        return list(struct.unpack(f'{self.dimension}f', data))