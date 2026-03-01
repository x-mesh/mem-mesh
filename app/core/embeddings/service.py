"""
Embedding Service for mem-mesh
텍스트를 벡터로 변환하는 서비스
"""

import os
import ssl
import struct
import logging
import time
import urllib3
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..services.metrics_collector import MetricsCollector

# MEM_MESH_IGNORE_SSL 환경변수가 설정되어 있으면 SSL 검증 비활성화
_ignore_ssl = os.getenv("MEM_MESH_IGNORE_SSL", "").lower() in ("1", "true", "yes")
if _ignore_ssl:
    # SSL 검증 비활성화
    ssl._create_default_https_context = ssl._create_unverified_context
    # urllib3 경고 비활성화
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # 환경변수 설정
    os.environ["CURL_CA_BUNDLE"] = ""
    os.environ["REQUESTS_CA_BUNDLE"] = ""
    os.environ["SSL_CERT_FILE"] = ""
    os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "0"

    # requests 라이브러리 SSL 검증 비활성화
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context

    class SSLAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = create_urllib3_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)

    # 기본 세션에 SSL 어댑터 적용
    session = requests.Session()
    session.mount("https://", SSLAdapter())
    session.verify = False

    # huggingface_hub의 기본 세션 패치
    try:
        import huggingface_hub

        huggingface_hub.configure_http_backend(backend_factory=lambda: session)
    except Exception:
        # Silently ignore if huggingface_hub is not available or configuration fails
        pass

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None  # type: ignore

logger = logging.getLogger(__name__)


# 모델별 임베딩 차원 매핑
MODEL_DIMENSIONS = {
    "all-MiniLM-L6-v2": 384,
    "all-MiniLM-L12-v2": 384,
    "all-mpnet-base-v2": 768,
    "paraphrase-MiniLM-L6-v2": 384,
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
    "distiluse-base-multilingual-cased-v2": 512,
    "multi-qa-MiniLM-L6-cos-v1": 384,
    "multi-qa-mpnet-base-cos-v1": 768,
    "intfloat/multilingual-e5-small": 384,
    "intfloat/multilingual-e5-base": 768,
    "intfloat/multilingual-e5-large": 1024,
}

# 모델 이름 별칭 (짧은 이름 -> 전체 이름)
MODEL_ALIASES = {
    "multilingual-e5-small": "intfloat/multilingual-e5-small",
    "multilingual-e5-base": "intfloat/multilingual-e5-base",
    "multilingual-e5-large": "intfloat/multilingual-e5-large",
    "e5-small": "intfloat/multilingual-e5-small",
    "e5-base": "intfloat/multilingual-e5-base",
    "e5-large": "intfloat/multilingual-e5-large",
}


# E5 계열 모델은 query/passage prefix가 필요
_E5_MODEL_PATTERNS = ("e5-", "/e5-", "multilingual-e5-")


def _is_e5_model(model_name: str) -> bool:
    """E5 계열 모델 여부 판단"""
    name_lower = model_name.lower()
    return any(pat in name_lower for pat in _E5_MODEL_PATTERNS)


class EmbeddingService:
    """임베딩 생성 서비스"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        preload: bool = True,
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """
        임베딩 서비스 초기화

        Args:
            model_name: 사용할 sentence-transformers 모델 이름 (None이면 설정에서 읽음)
            preload: True면 초기화 시 모델을 미리 로드 (기본값: True)
            metrics_collector: 메트릭 수집기 (선택적)
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install it with: pip install sentence-transformers"
            )
        
        self.model: Optional[SentenceTransformer] = None
        self.metrics_collector = metrics_collector

        # 설정에서 모델 이름 가져오기
        if model_name is None:
            from ..config import Settings

            settings = Settings()
            model_name = settings.embedding_model
            logger.info(f"Loading model from settings: {model_name}")

        # 모델 별칭 처리 (짧은 이름 -> 전체 이름)
        self.model_name = MODEL_ALIASES.get(model_name, model_name)
        if self.model_name != model_name:
            logger.info(f"Model alias resolved: {model_name} -> {self.model_name}")

        # E5 모델 여부 (query/passage prefix 자동 적용)
        self._is_e5 = _is_e5_model(self.model_name)
        if self._is_e5:
            logger.info("E5 model detected: query/passage prefix will be applied automatically")

        # 기본 차원 설정 (실제 모델 로드 후 업데이트됨)
        self.dimension: int = MODEL_DIMENSIONS.get(self.model_name, 384)
        logger.info(
            f"EmbeddingService initializing with model: {self.model_name} (dimension: {self.dimension})"
        )

        if preload:
            self._preload_model()

    def _preload_model(self) -> None:
        """시작 시 모델 미리 로드 및 검증"""
        logger.info(f"Preloading embedding model: {self.model_name}")
        # MCP 서버에서는 stdout을 JSON-RPC 전용으로 사용해야 하므로 print 대신 logger 사용
        logger.info(f"Loading embedding model: {self.model_name}...")

        try:
            self.model = SentenceTransformer(self.model_name)

            # 모델 차원 자동 감지
            actual_dim = self.model.get_sentence_embedding_dimension()
            if actual_dim != self.dimension:
                logger.info(f"Updating dimension from {self.dimension} to {actual_dim}")
                self.dimension = actual_dim

            # 테스트 임베딩으로 모델 검증
            test_embedding = self.model.encode("test", convert_to_tensor=False)
            if len(test_embedding) != self.dimension:
                raise ValueError(
                    f"Model dimension mismatch: expected {self.dimension}, got {len(test_embedding)}"
                )

            logger.info(f"Model loaded successfully (dimension: {self.dimension})")
            logger.info(
                f"Model {self.model_name} preloaded successfully (dimension: {self.dimension})"
            )

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            logger.error(f"Failed to preload model {self.model_name}: {e}")
            raise

    def load_model(self) -> None:
        """모델 로드 (lazy loading - preload=False인 경우 사용)"""
        if self.model is None:
            self._preload_model()

    def _prepare_text(self, text: str, is_query: bool) -> str:
        """E5 모델일 경우 query/passage prefix를 자동 적용"""
        if not self._is_e5:
            return text
        prefix = "query: " if is_query else "passage: "
        return prefix + text

    def embed(self, text: str, is_query: bool = False) -> list[float]:
        """
        단일 텍스트 임베딩

        Args:
            text: 임베딩할 텍스트
            is_query: True면 검색 쿼리용 임베딩 (E5 모델에서 "query:" prefix 적용)
        """
        if self.model is None:
            self.load_model()

        assert self.model is not None, "Model should be loaded"

        start_time = time.perf_counter()
        cache_hit = False

        try:
            prepared = self._prepare_text(text, is_query)
            embedding = self.model.encode(prepared, convert_to_tensor=False, normalize_embeddings=True)
            result = embedding.tolist()

            self._collect_embedding_metric(
                operation="generate",
                count=1,
                start_time=start_time,
                cache_hit=cache_hit,
            )

            return result
        except Exception as e:
            logger.error(f"Failed to generate embedding for text: {e}")
            raise

    def embed_batch(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        """
        배치 임베딩

        Args:
            texts: 임베딩할 텍스트 리스트
            is_query: True면 검색 쿼리용 임베딩 (E5 모델에서 "query:" prefix 적용)
        """
        if self.model is None:
            self.load_model()

        assert self.model is not None, "Model should be loaded"

        start_time = time.perf_counter()
        cache_hit = False

        try:
            prepared = [self._prepare_text(t, is_query) for t in texts]
            embeddings = self.model.encode(prepared, convert_to_tensor=False, normalize_embeddings=True)
            result = [embedding.tolist() for embedding in embeddings]

            self._collect_embedding_metric(
                operation="batch_generate",
                count=len(texts),
                start_time=start_time,
                cache_hit=cache_hit,
            )

            return result
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            raise

    def to_bytes(self, embedding: list[float]) -> bytes:
        """임베딩을 bytes로 변환 (SQLite 저장용)"""
        # 동적 차원 지원
        return struct.pack(f"{len(embedding)}f", *embedding)

    def from_bytes(self, data: bytes) -> list[float]:
        """bytes를 임베딩으로 변환"""
        # 동적 차원 지원: 데이터 크기에서 차원 계산
        num_floats = len(data) // 4  # float32 = 4 bytes
        if len(data) % 4 != 0:
            raise ValueError(
                f"Invalid data size: {len(data)} bytes (not divisible by 4)"
            )

        return list(struct.unpack(f"{num_floats}f", data))

    def get_model_info(self) -> dict:
        """모델 정보 반환"""
        return {
            "model_name": self.model_name,
            "dimension": self.dimension,
            "loaded": self.model is not None,
        }

    def _collect_embedding_metric(
        self, operation: str, count: int, start_time: float, cache_hit: bool
    ) -> None:
        """
        임베딩 메트릭 수집 헬퍼 메서드

        Args:
            operation: 작업 유형 ('generate', 'batch_generate')
            count: 생성된 임베딩 수
            start_time: 시작 시간 (time.perf_counter())
            cache_hit: 캐시 히트 여부
        """
        if self.metrics_collector is None:
            return

        try:
            import asyncio

            total_time_ms = int((time.perf_counter() - start_time) * 1000)

            # 비동기 메서드를 동기 컨텍스트에서 호출
            try:
                asyncio.get_running_loop()
                # 이미 이벤트 루프가 실행 중이면 태스크로 스케줄링
                asyncio.create_task(
                    self.metrics_collector.collect_embedding_metric(
                        operation=operation,
                        count=count,
                        total_time_ms=total_time_ms,
                        cache_hit=cache_hit,
                        model_name=self.model_name,
                    )
                )
            except RuntimeError:
                # 이벤트 루프가 없으면 새로 생성하여 실행
                asyncio.run(
                    self.metrics_collector.collect_embedding_metric(
                        operation=operation,
                        count=count,
                        total_time_ms=total_time_ms,
                        cache_hit=cache_hit,
                        model_name=self.model_name,
                    )
                )
        except Exception as e:
            # 메트릭 수집 실패는 임베딩 생성에 영향을 주지 않음
            logger.warning(f"Failed to collect embedding metric: {e}")
