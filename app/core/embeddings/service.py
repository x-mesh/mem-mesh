"""
Embedding Service for mem-mesh
텍스트를 벡터로 변환하는 서비스
"""

import asyncio
import logging
import os
import ssl
import struct
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

import urllib3

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
    # English lightweight
    "all-MiniLM-L6-v2": 384,
    "all-MiniLM-L12-v2": 384,
    "all-mpnet-base-v2": 768,
    "paraphrase-MiniLM-L6-v2": 384,
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
    "distiluse-base-multilingual-cased-v2": 512,
    "multi-qa-MiniLM-L6-cos-v1": 384,
    "multi-qa-mpnet-base-cos-v1": 768,
    # BGE English
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
    # Multilingual E5
    "intfloat/multilingual-e5-small": 384,
    "intfloat/multilingual-e5-base": 768,
    "intfloat/multilingual-e5-large": 1024,
    # BGE-M3 multilingual
    "BAAI/bge-m3": 1024,
    # Korean specialized
    "nlpai-lab/KURE-v1": 1024,
    "nlpai-lab/KoE5": 1024,
    "dragonkue/BGE-m3-ko": 1024,
    "snunlp/KR-SBERT-V40K-klueNLI-augSTS": 768,
    "jhgan/ko-sroberta-sts": 768,
}

# 모델 이름 별칭 (짧은 이름 -> 전체 이름)
MODEL_ALIASES = {
    "multilingual-e5-small": "intfloat/multilingual-e5-small",
    "multilingual-e5-base": "intfloat/multilingual-e5-base",
    "multilingual-e5-large": "intfloat/multilingual-e5-large",
    "e5-small": "intfloat/multilingual-e5-small",
    "e5-base": "intfloat/multilingual-e5-base",
    "e5-large": "intfloat/multilingual-e5-large",
    "bge-m3": "BAAI/bge-m3",
    "kure": "nlpai-lab/KURE-v1",
    "koe5": "nlpai-lab/KoE5",
    "bge-m3-ko": "dragonkue/BGE-m3-ko",
    "kr-sbert": "snunlp/KR-SBERT-V40K-klueNLI-augSTS",
    "ko-sroberta": "jhgan/ko-sroberta-sts",
    "bge-small-en": "BAAI/bge-small-en-v1.5",
    "bge-base-en": "BAAI/bge-base-en-v1.5",
    "bge-large-en": "BAAI/bge-large-en-v1.5",
}


# E5 계열 모델은 query/passage prefix가 필요
_E5_MODEL_PATTERNS = ("e5-", "/e5-", "multilingual-e5-")


def _is_e5_model(model_name: str) -> bool:
    """E5 계열 모델 여부 판단"""
    name_lower = model_name.lower()
    return any(pat in name_lower for pat in _E5_MODEL_PATTERNS)


def is_model_cached(model_name: str) -> bool:
    """HuggingFace 캐시에 모델이 존재하는지 확인"""
    resolved = MODEL_ALIASES.get(model_name, model_name)
    try:
        from huggingface_hub import scan_cache_dir

        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == resolved:
                # 최소한 하나의 revision이 있으면 캐시됨
                if repo.revisions:
                    return True
        return False
    except Exception:
        # huggingface_hub 미설치 또는 캐시 스캔 실패
        return False


# 선택 가능한 모델 목록 (온보딩 UI용)
AVAILABLE_MODELS = [
    # ── Korean Specialized ──
    {
        "name": "nlpai-lab/KURE-v1",
        "dimension": 1024,
        "size": "~2.2GB",
        "description": "Korean retrieval SOTA. Fine-tuned BGE-M3 with Korean data. Best for Korean-heavy workflows.",
        "recommended": True,
        "category": "korean",
        "lang": "ko/en",
        "max_tokens": 8192,
    },
    {
        "name": "nlpai-lab/KoE5",
        "dimension": 1024,
        "size": "~1.1GB",
        "description": "Korean-tuned E5-large. Excellent Korean retrieval with smaller footprint than KURE.",
        "recommended": False,
        "category": "korean",
        "lang": "ko/en",
        "max_tokens": 512,
    },
    {
        "name": "dragonkue/BGE-m3-ko",
        "dimension": 1024,
        "size": "~2.2GB",
        "description": "BGE-M3 fine-tuned for Korean. Strong Korean + multilingual performance.",
        "recommended": False,
        "category": "korean",
        "lang": "ko/en",
        "max_tokens": 8192,
    },
    {
        "name": "snunlp/KR-SBERT-V40K-klueNLI-augSTS",
        "dimension": 768,
        "size": "~440MB",
        "description": "Korean SBERT by SNU NLP. Lightweight Korean semantic similarity model.",
        "recommended": False,
        "category": "korean",
        "lang": "ko",
        "max_tokens": 512,
    },
    {
        "name": "jhgan/ko-sroberta-sts",
        "dimension": 768,
        "size": "~440MB",
        "description": "Korean SRoBERTa for semantic similarity. Good for short Korean texts.",
        "recommended": False,
        "category": "korean",
        "lang": "ko",
        "max_tokens": 512,
    },
    # ── Multilingual ──
    {
        "name": "BAAI/bge-m3",
        "dimension": 1024,
        "size": "~2.2GB",
        "description": "Top multilingual model. 100+ languages, 8K tokens. Dense + sparse retrieval.",
        "recommended": False,
        "category": "multilingual",
        "lang": "100+ langs",
        "max_tokens": 8192,
    },
    {
        "name": "intfloat/multilingual-e5-large",
        "dimension": 1024,
        "size": "~1.1GB",
        "description": "Strong multilingual embeddings. Good balance for mixed-language content.",
        "recommended": False,
        "category": "multilingual",
        "lang": "100+ langs",
        "max_tokens": 512,
    },
    {
        "name": "intfloat/multilingual-e5-base",
        "dimension": 768,
        "size": "~470MB",
        "description": "Mid-size multilingual E5. Good quality with moderate resource usage.",
        "recommended": False,
        "category": "multilingual",
        "lang": "100+ langs",
        "max_tokens": 512,
    },
    {
        "name": "intfloat/multilingual-e5-small",
        "dimension": 384,
        "size": "~118MB",
        "description": "Smallest multilingual E5. Fast inference, low memory footprint.",
        "recommended": False,
        "category": "multilingual",
        "lang": "100+ langs",
        "max_tokens": 512,
    },
    # ── English Optimized ──
    {
        "name": "BAAI/bge-large-en-v1.5",
        "dimension": 1024,
        "size": "~1.3GB",
        "description": "Top English retrieval model. Excellent for English-only environments.",
        "recommended": False,
        "category": "english",
        "lang": "en",
        "max_tokens": 512,
    },
    {
        "name": "all-mpnet-base-v2",
        "dimension": 768,
        "size": "~420MB",
        "description": "Best all-round English model. High quality sentence embeddings.",
        "recommended": False,
        "category": "english",
        "lang": "en",
        "max_tokens": 384,
    },
    {
        "name": "BAAI/bge-small-en-v1.5",
        "dimension": 384,
        "size": "~130MB",
        "description": "Compact English model with strong performance. Great for low-resource setups.",
        "recommended": False,
        "category": "english",
        "lang": "en",
        "max_tokens": 512,
    },
    {
        "name": "all-MiniLM-L6-v2",
        "dimension": 384,
        "size": "~80MB",
        "description": "Most popular English model. Ultra-fast, minimal resource usage.",
        "recommended": False,
        "category": "english",
        "lang": "en",
        "max_tokens": 256,
    },
]


class EmbeddingService:
    """임베딩 생성 서비스"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        preload: bool = True,
        defer_loading: bool = False,
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """
        임베딩 서비스 초기화

        Args:
            model_name: 사용할 sentence-transformers 모델 이름 (None이면 설정에서 읽음)
            preload: True면 초기화 시 모델을 미리 로드 (기본값: True)
            defer_loading: True면 embed() 호출 시 자동 로딩 차단 (Web 서버용)
            metrics_collector: 메트릭 수집기 (선택적)
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install it with: pip install sentence-transformers"
            )

        self.model: Optional[SentenceTransformer] = None
        self.metrics_collector = metrics_collector

        # 다운로드/로딩 상태 추적
        self._status: str = "not_loaded"  # not_loaded | downloading | loading | ready | error
        self._download_progress: float = 0.0
        self._error_message: Optional[str] = None
        self._load_lock = threading.Lock()
        self._defer_loading = defer_loading

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
            logger.info(
                "E5 model detected: query/passage prefix will be applied automatically"
            )

        # 기본 차원 설정 (실제 모델 로드 후 업데이트됨)
        self.dimension: int = MODEL_DIMENSIONS.get(self.model_name, 384)
        logger.info(
            f"EmbeddingService initializing with model: {self.model_name} (dimension: {self.dimension})"
        )

        if preload:
            self._preload_model()

    @property
    def is_ready(self) -> bool:
        """모델이 로드되어 사용 가능한지 여부"""
        return self._status == "ready" and self.model is not None

    @property
    def status(self) -> str:
        """현재 상태: not_loaded | downloading | loading | ready | error"""
        return self._status

    @property
    def download_progress(self) -> float:
        """다운로드 진행률 (0.0 ~ 1.0)"""
        return self._download_progress

    @property
    def error_message(self) -> Optional[str]:
        """에러 메시지 (에러 상태일 때)"""
        return self._error_message

    def get_status_info(self) -> dict:
        """현재 상태 정보를 딕셔너리로 반환"""
        return {
            "status": self._status,
            "progress": self._download_progress,
            "model": self.model_name,
            "dimension": self.dimension,
            "error": self._error_message,
        }

    def _preload_model(self) -> None:
        """시작 시 모델 미리 로드 및 검증"""
        logger.info(f"Preloading embedding model: {self.model_name}")
        self._status = "loading"
        self._download_progress = 0.0

        try:
            self.model = SentenceTransformer(self.model_name)
            self._download_progress = 0.9

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

            self._status = "ready"
            self._download_progress = 1.0
            logger.info(
                f"Model {self.model_name} preloaded successfully (dimension: {self.dimension})"
            )

        except Exception as e:
            self._status = "error"
            self._error_message = str(e)
            logger.error(f"Failed to preload model {self.model_name}: {e}")
            raise

    def load_model(self) -> None:
        """모델 로드 (lazy loading - preload=False인 경우 사용)"""
        if self.model is None:
            self._preload_model()

    def load_model_background(
        self,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> threading.Thread:
        """백그라운드 스레드에서 모델 로드. 완료/에러 시 status가 업데이트됨.

        Args:
            on_progress: 진행률 콜백 (progress: float, status: str)

        Returns:
            시작된 Thread 객체
        """
        svc = self  # closure reference

        def _notify(progress: float, status: str) -> None:
            """상태 업데이트 + 콜백 호출 헬퍼"""
            svc._download_progress = progress
            svc._status = status
            if on_progress:
                on_progress(progress, status)

        def _worker() -> None:
            with self._load_lock:
                if self._status == "ready":
                    return

                self._error_message = None

                try:
                    logger.info(f"Background loading model: {self.model_name}")
                    cached = is_model_cached(self.model_name)

                    if cached:
                        # 캐시됨 — 바로 loading 단계
                        _notify(0.5, "loading")
                    else:
                        # 미캐시 — snapshot_download로 실제 진행률 추적
                        _notify(0.0, "downloading")
                        self._download_with_progress(_notify)

                    # 모델 로드 (캐시에서 로드하므로 빠름)
                    _notify(0.85, "loading")
                    self.model = SentenceTransformer(self.model_name)
                    _notify(0.92, "loading")

                    # 차원 자동 감지
                    actual_dim = self.model.get_sentence_embedding_dimension()
                    if actual_dim != self.dimension:
                        logger.info(
                            f"Updating dimension from {self.dimension} to {actual_dim}"
                        )
                        self.dimension = actual_dim

                    # 검증
                    test_embedding = self.model.encode(
                        "test", convert_to_tensor=False
                    )
                    if len(test_embedding) != self.dimension:
                        raise ValueError(
                            f"Model dimension mismatch: expected {self.dimension}, "
                            f"got {len(test_embedding)}"
                        )

                    _notify(1.0, "ready")
                    logger.info(
                        f"Model {self.model_name} loaded in background "
                        f"(dimension: {self.dimension})"
                    )

                except Exception as e:
                    self._status = "error"
                    self._error_message = str(e)
                    self._download_progress = 0.0
                    if on_progress:
                        on_progress(0.0, "error")
                    logger.error(f"Background model load failed: {e}")

        thread = threading.Thread(target=_worker, daemon=True, name="model-loader")
        thread.start()
        return thread

    def _download_with_progress(
        self,
        notify: Callable[[float, str], None],
    ) -> None:
        """huggingface_hub snapshot_download로 실제 다운로드 진행률 추적.

        다운로드 완료 후 SentenceTransformer()는 캐시에서 즉시 로드됨.
        진행률은 0.0~0.80 범위로 매핑 (0.80 이후는 모델 로딩 단계).
        """
        try:
            from huggingface_hub import snapshot_download
            import tqdm as tqdm_mod

            # 파일별 다운로드 바이트 추적
            _file_totals: dict = {}  # id -> total
            _file_downloaded: dict = {}  # id -> downloaded
            _last_reported: list = [0.0]  # 마지막 보고 진행률 (debounce)

            svc = self

            class _ProgressTqdm(tqdm_mod.tqdm):
                """snapshot_download의 tqdm을 오버라이드하여 진행률 캡처"""

                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    tid = id(self)
                    _file_totals[tid] = self.total or 0
                    _file_downloaded[tid] = 0

                def update(self, n=1):
                    super().update(n)
                    tid = id(self)
                    _file_downloaded[tid] = _file_downloaded.get(tid, 0) + n

                    total = sum(_file_totals.values())
                    downloaded = sum(_file_downloaded.values())
                    if total > 0:
                        # 0.0 ~ 0.80 범위로 매핑
                        pct = min(downloaded / total, 1.0) * 0.80
                        # 5% 이상 변동 시에만 보고 (WebSocket 스팸 방지)
                        if pct - _last_reported[0] >= 0.05 or pct >= 0.79:
                            _last_reported[0] = pct
                            notify(round(pct, 2), "downloading")

                def close(self):
                    super().close()

            snapshot_download(
                self.model_name,
                tqdm_class=_ProgressTqdm,
            )
            logger.info(f"Model files downloaded: {self.model_name}")

        except ImportError:
            # huggingface_hub 없으면 SentenceTransformer가 직접 다운로드
            logger.warning(
                "huggingface_hub not available, falling back to basic download"
            )
            notify(0.1, "downloading")
        except Exception as e:
            # 다운로드 실패 시 SentenceTransformer에 위임 (재시도 기회)
            logger.warning(f"snapshot_download failed, falling back: {e}")
            notify(0.1, "downloading")

    def switch_model(self, new_model_name: str) -> None:
        """모델 변경 (온보딩에서 사용자가 모델을 선택한 경우)"""
        resolved = MODEL_ALIASES.get(new_model_name, new_model_name)
        if resolved == self.model_name and self._status == "ready":
            return

        self.model = None
        self.model_name = resolved
        self._is_e5 = _is_e5_model(self.model_name)
        self.dimension = MODEL_DIMENSIONS.get(self.model_name, 384)
        self._status = "not_loaded"
        self._download_progress = 0.0
        self._error_message = None
        logger.info(f"Model switched to: {self.model_name}")

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
            if self._defer_loading and self._status in ("not_loaded", "downloading", "loading"):
                raise RuntimeError(
                    f"Embedding model not ready (status: {self._status}). "
                    "Please select a model via onboarding first."
                )
            self.load_model()

        assert self.model is not None, "Model should be loaded"

        start_time = time.perf_counter()
        cache_hit = False

        try:
            prepared = self._prepare_text(text, is_query)
            embedding = self.model.encode(
                prepared, convert_to_tensor=False, normalize_embeddings=True
            )
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

    def embed_batch(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        """
        배치 임베딩

        Args:
            texts: 임베딩할 텍스트 리스트
            is_query: True면 검색 쿼리용 임베딩 (E5 모델에서 "query:" prefix 적용)
        """
        if self.model is None:
            if self._defer_loading and self._status in ("not_loaded", "downloading", "loading"):
                raise RuntimeError(
                    f"Embedding model not ready (status: {self._status}). "
                    "Please select a model via onboarding first."
                )
            self.load_model()

        assert self.model is not None, "Model should be loaded"

        start_time = time.perf_counter()
        cache_hit = False

        try:
            prepared = [self._prepare_text(t, is_query) for t in texts]
            embeddings = self.model.encode(
                prepared, convert_to_tensor=False, normalize_embeddings=True
            )
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
