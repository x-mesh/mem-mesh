#!/usr/bin/env python3
"""
Kiro Chat 파일을 mem-mesh에 bulk import하는 스크립트 (요약: Qwen2.5-7B-Instruct 지원)

사용법:
    python scripts/import_kiro_chat_memmesh.py [chat_dir] [options]

옵션:
    --mode: raw | hybrid | clean | semantic | summary (기본: hybrid)
        - raw: 원본 데이터 그대로 저장
        - hybrid: 시스템 프롬프트 제거, 의미있는 대화만 추출 (기본값)
        - clean: 코드/결정사항만 추출
        - semantic: 임베딩 기반 의미적 중복 제거 + hybrid 필터링
        - summary: 긴 메시지/세션을 요약해서 저장 (LLM/seq2seq 지원)
    --similarity-threshold: semantic 모드에서 중복 판정 임계값 (기본: 0.9)
    --db-path: 데이터베이스 경로 (기본: data/memories.db)
    --project-id: 프로젝트 ID (기본: 파일 경로에서 추출)
    --dry-run: 실제 저장 없이 미리보기
    --limit: 처리할 최대 파일 수

요약 모델 관련:
    --summary-model: 요약 모델명 (기본: facebook/bart-large-cnn)
    --summary-backend: auto | hf_seq2seq | qwen_chat (기본: auto)
        - auto: 모델명에 qwen이 포함되면 qwen_chat, 아니면 hf_seq2seq
        - hf_seq2seq: pipeline("summarization") 사용 (BART/T5/Pegasus 등)
        - qwen_chat: Qwen Instruct 계열 Chat template + generate 사용
    --summary-language: ko | en (기본: ko)
    --summary-style: bullets | paragraph (기본: bullets)
    --qwen-device: auto | cpu | cuda (기본: auto)
    --qwen-max-new-tokens: Qwen 요약 생성 토큰 수 (기본: 384)
    --qwen-temperature: (기본: 0.2)
    --qwen-top-p: (기본: 0.9)
"""

import sys
import os
import json
import re
import asyncio
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

import numpy as np

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import AddParams

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ImportMode(Enum):
    RAW = "raw"
    HYBRID = "hybrid"
    CLEAN = "clean"
    SEMANTIC = "semantic"
    SUMMARY = "summary"


class SummaryBackend(Enum):
    AUTO = "auto"
    HF_SEQ2SEQ = "hf_seq2seq"
    QWEN_CHAT = "qwen_chat"


class KiroChatImporter:
    """Kiro Chat 파일을 mem-mesh에 import하는 클래스"""

    SYSTEM_PROMPT_PATTERNS = [
        r'^# System Prompt',
        r'^<identity>',
        r'^You are Kiro',
    ]

    CODE_BLOCK_PATTERN = re.compile(r'```[\w]*\n[\s\S]*?```')

    # 요약에서 불필요한 메타/로그를 덜어내기 위한 패턴(세션 요약용)
    NOISE_LINE_PATTERNS = [
        r'^\[BOT\]\s*I will follow these instructions\.\s*$',
        r'^\[TOOL\]\s*You are operating in a workspace.*$',
        r'^<fileTree>\s*$',
        r'^</fileTree>\s*$',
        r'^\s*<fileTree>[\s\S]*?</fileTree>\s*$',
    ]

    def __init__(
        self,
        db_path: str = "data/memories.db",
        mode: ImportMode = ImportMode.HYBRID,
        dry_run: bool = False,
        similarity_threshold: float = 0.9,
        embedding_model: str = "all-MiniLM-L6-v2",
        summary_model: str = "facebook/bart-large-cnn",
        summary_backend: SummaryBackend = SummaryBackend.AUTO,
        summary_language: str = "ko",
        summary_style: str = "bullets",
        qwen_device: str = "auto",
        qwen_max_new_tokens: int = 384,
        qwen_temperature: float = 0.2,
        qwen_top_p: float = 0.9,
        verbose_level: int = 0
    ):
        self.db_path = db_path
        self.mode = mode
        self.dry_run = dry_run
        self.similarity_threshold = similarity_threshold

        self.storage: Optional[DirectStorageBackend] = None

        # Embedding
        self.embedding_model_name = embedding_model
        self.embedding_model = None  # SentenceTransformer (lazy import)

        # Summary
        self.summary_model_name = summary_model
        self.summary_backend = summary_backend
        self.summary_language = summary_language
        self.summary_style = summary_style

        self.summary_model = None  # hf pipeline summarizer
        self.qwen_tokenizer = None
        self.qwen_model = None
        self.qwen_device = qwen_device
        self.qwen_max_new_tokens = qwen_max_new_tokens
        self.qwen_temperature = qwen_temperature
        self.qwen_top_p = qwen_top_p

        self.verbose_level = verbose_level

        # semantic 모드용 글로벌 임베딩 캐시
        self.global_embeddings: List[np.ndarray] = []
        self.global_contents: List[str] = []

        self.stats = {
            "files_processed": 0,
            "messages_imported": 0,
            "messages_skipped": 0,
            "semantic_duplicates": 0,
            "summaries_created": 0,
            "errors": 0
        }

    # -------------------------
    # Lifecycle
    # -------------------------
    async def initialize(self) -> None:
        """스토리지 백엔드 초기화 + 모드별 모델 로드"""
        if not self.dry_run:
            self.storage = DirectStorageBackend(self.db_path)
            await self.storage.initialize()
            logger.info(f"Storage initialized: {self.db_path}")

        if self.mode == ImportMode.SEMANTIC:
            self._load_embedding_model()

        if self.mode == ImportMode.SUMMARY:
            self._load_summary_model()

    async def shutdown(self) -> None:
        if self.storage:
            await self.storage.shutdown()

    # -------------------------
    # Model loading
    # -------------------------
    def _load_embedding_model(self) -> None:
        logger.info(f"Loading embedding model: {self.embedding_model_name}")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "semantic 모드를 사용하려면 sentence-transformers가 필요합니다.\n"
                "pip install sentence-transformers"
            ) from e

        # local_files_only=False: 캐시 없으면 다운로드 시도
        self.embedding_model = SentenceTransformer(
            self.embedding_model_name,
            local_files_only=False
        )
        logger.info("Embedding model loaded")

    def _resolve_summary_backend(self) -> SummaryBackend:
        if self.summary_backend != SummaryBackend.AUTO:
            return self.summary_backend

        name = (self.summary_model_name or "").lower()
        if "qwen" in name:
            return SummaryBackend.QWEN_CHAT
        return SummaryBackend.HF_SEQ2SEQ

    def _load_summary_model(self) -> None:
        backend = self._resolve_summary_backend()
        logger.info(f"Summary backend: {backend.value}")
        logger.info(f"Summary model: {self.summary_model_name}")

        if backend == SummaryBackend.QWEN_CHAT:
            self._load_qwen_chat_model()
        else:
            self._load_hf_seq2seq_summarizer()

    def _load_qwen_chat_model(self) -> None:
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
        except ImportError as e:
            raise RuntimeError(
                "Qwen 요약을 사용하려면 transformers + torch가 필요합니다.\n"
                "pip install transformers torch"
            ) from e

        model_id = self.summary_model_name
        logger.info(f"Loading Qwen chat model: {model_id}")

        # device 결정
        device_pref = (self.qwen_device or "auto").lower()
        has_cuda = torch.cuda.is_available()

        if device_pref == "cuda" and not has_cuda:
            logger.warning("qwen-device=cuda 이지만 CUDA를 사용할 수 없습니다. cpu로 전환합니다.")
            device_pref = "cpu"

        if device_pref == "cpu":
            device_map = {"": "cpu"}
            dtype = torch.float32  # CPU는 fp32가 안전
        else:
            # auto / cuda
            device_map = "auto"
            # GPU면 bf16 권장 (가능한 경우)
            dtype = torch.bfloat16 if has_cuda else torch.float32

        self.qwen_tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        self.qwen_model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=dtype,
            device_map=device_map,
            trust_remote_code=True,
        )

        self.summary_model = None
        logger.info("Qwen chat summarizer loaded")

        # 간단 테스트
        try:
            _ = self.qwen_summarize("테스트 문장입니다. 모델이 정상 동작하는지 확인합니다.", max_new_tokens=64)
            logger.info("Qwen summarizer test OK")
        except Exception as e:
            logger.error(f"Qwen summarizer test FAILED: {e}")
            self.qwen_model = None
            self.qwen_tokenizer = None

    def _load_hf_seq2seq_summarizer(self) -> None:
        try:
            from transformers import pipeline
        except ImportError as e:
            raise RuntimeError(
                "요약을 사용하려면 transformers + torch가 필요합니다.\n"
                "pip install transformers torch"
            ) from e

        logger.info("Loading HF seq2seq summarization pipeline...")

        lightweight_models = [
            "sshleifer/distilbart-cnn-12-6",
            "facebook/bart-large-cnn",
            "t5-small",
            "google/pegasus-xsum",
            "t5-base",
        ]

        model_to_use = self.summary_model_name
        model_loaded = False

        # 사용자 지정 모델 먼저 시도
        if self.summary_model_name not in lightweight_models:
            try:
                logger.info(f"사용자 지정 모델 시도: {self.summary_model_name}")
                self.summary_model = pipeline(
                    "summarization",
                    model=self.summary_model_name,
                    device=-1,  # CPU
                    framework="pt",
                    return_tensors=False,
                    clean_up_tokenization_spaces=True,
                    trust_remote_code=False
                )
                model_loaded = True
                model_to_use = self.summary_model_name
                logger.info(f"사용자 지정 모델 로드 성공: {model_to_use}")
            except Exception as e:
                logger.warning(f"사용자 지정 모델 로드 실패 {self.summary_model_name}: {e}")

        # 폴백 모델들 시도
        if not model_loaded:
            models_to_try = [self.summary_model_name] if self.summary_model_name in lightweight_models else lightweight_models
            for m in models_to_try:
                try:
                    logger.info(f"모델 시도: {m}")
                    self.summary_model = pipeline(
                        "summarization",
                        model=m,
                        device=-1,
                        framework="pt",
                        return_tensors=False,
                        clean_up_tokenization_spaces=True,
                        trust_remote_code=False
                    )
                    model_loaded = True
                    model_to_use = m
                    logger.info(f"모델 로드 성공: {model_to_use}")
                    break
                except Exception as e:
                    logger.warning(f"모델 로드 실패 {m}: {e}")

        if not model_loaded:
            logger.warning("모든 요약 모델 로드 실패, 간단한 텍스트 요약만 사용")
            self.summary_model = None
            return

        # 모델 테스트
        try:
            test_text = "This is a test sentence for model validation. The model should process without errors."
            _ = self.summary_model(test_text, max_length=50, min_length=10, do_sample=False)
            logger.info(f"HF summarizer test OK: {model_to_use}")
        except Exception as e:
            logger.error(f"HF summarizer test FAILED: {e}")
            self.summary_model = None

    # -------------------------
    # File handling
    # -------------------------
    def find_chat_files(self, chat_dir: str) -> List[Path]:
        chat_path = Path(chat_dir)
        if not chat_path.exists():
            logger.warning(f"Chat 디렉토리가 없습니다: {chat_dir}")
            return []
        chat_files = list(chat_path.glob("**/*.chat"))
        logger.info(f"찾은 Chat 파일: {len(chat_files)}개")
        return chat_files

    def read_chat_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"파일 읽기 실패 ({file_path}): {e}")
            return None

    # -------------------------
    # Filters / helpers
    # -------------------------
    def is_system_prompt(self, content: str) -> bool:
        for pattern in self.SYSTEM_PROMPT_PATTERNS:
            if re.search(pattern, content, re.MULTILINE):
                return True
        return False

    def extract_project_id(self, file_path: Path) -> str:
        parts = file_path.parts
        for i, part in enumerate(parts):
            if part == "kiro.kiroagent" and i + 1 < len(parts):
                return f"kiro-{parts[i + 1][:8]}"
        return "kiro-unknown"

    def determine_category(self, role: str, content: str) -> str:
        content_lower = content.lower()

        if self.CODE_BLOCK_PATTERN.search(content):
            return "code_snippet"

        decision_keywords = ['결정', 'decided', 'decision', '설계', 'design', 'architecture']
        if any(kw in content_lower for kw in decision_keywords):
            return "decision"

        bug_keywords = ['bug', 'error', '버그', '에러', 'fix', '수정']
        if any(kw in content_lower for kw in bug_keywords):
            return "bug"

        idea_keywords = ['idea', '아이디어', 'suggest', '제안', 'could', 'maybe']
        if any(kw in content_lower for kw in idea_keywords):
            return "idea"

        return "task"

    def _is_noise_line_for_summary(self, line: str) -> bool:
        s = line.strip()
        if not s:
            return True
        for pat in self.NOISE_LINE_PATTERNS:
            if re.match(pat, s):
                return True
        # tool/filetree 같은 메타 라인 약하게 제거
        if s.startswith("[TOOL]") or s.startswith("<fileTree") or s.startswith("</fileTree"):
            return True
        return False

    # -------------------------
    # Message processors
    # -------------------------
    def process_message_raw(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        content = message.get('content', '')
        if not content or len(content.strip()) < 10:
            return None
        return {
            "content": content,
            "category": self.determine_category(message.get('role', ''), content),
            "source": "kiro_chat_import",
            "tags": ["kiro", "raw", message.get('role', 'unknown')]
        }

    def process_message_hybrid(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        content = message.get('content', '')
        role = message.get('role', '')

        if not content or len(content.strip()) < 10:
            return None

        if role == 'human' and self.is_system_prompt(content):
            return None

        if role == 'bot' and len(content.strip()) < 50:
            return None

        if len(content) > 10000:
            content = content[:9900] + "\n\n[... truncated ...]"

        return {
            "content": content,
            "category": self.determine_category(role, content),
            "source": "kiro_chat_import",
            "tags": ["kiro", "hybrid", role]
        }

    def process_message_clean(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        content = message.get('content', '')
        role = message.get('role', '')

        if role != 'bot':
            return None

        has_code = bool(self.CODE_BLOCK_PATTERN.search(content))
        if not has_code and len(content) < 200:
            return None

        if self.is_system_prompt(content):
            return None

        if len(content) > 10000:
            content = content[:9900] + "\n\n[... truncated ...]"

        return {
            "content": content,
            "category": "code_snippet" if has_code else "decision",
            "source": "kiro_chat_import",
            "tags": ["kiro", "clean", "bot"]
        }

    # -------------------------
    # Semantic duplicate detection
    # -------------------------
    def compute_embedding(self, text: str) -> np.ndarray:
        if self.embedding_model is None:
            raise RuntimeError("Embedding model not initialized")
        return self.embedding_model.encode(text, convert_to_numpy=True)

    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))

    def is_semantic_duplicate(self, content: str, embedding: np.ndarray) -> Tuple[bool, Optional[str], float]:
        max_similarity = 0.0
        most_similar_content = None

        for i, cached_emb in enumerate(self.global_embeddings):
            similarity = self.cosine_similarity(embedding, cached_emb)
            if similarity > max_similarity:
                max_similarity = similarity
                most_similar_content = self.global_contents[i]

        if max_similarity >= self.similarity_threshold:
            return True, most_similar_content, max_similarity
        return False, None, max_similarity

    def process_message_semantic(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        content = message.get('content', '')
        role = message.get('role', '')

        if not content or len(content.strip()) < 10:
            return None

        if role == 'human' and self.is_system_prompt(content):
            return None

        if role == 'bot' and len(content.strip()) < 50:
            return None

        if len(content) > 10000:
            content = content[:9900] + "\n\n[... truncated ...]"

        embedding = self.compute_embedding(content[:2000])
        is_dup, similar_preview, similarity = self.is_semantic_duplicate(content, embedding)
        if is_dup:
            self.stats["semantic_duplicates"] += 1
            logger.debug(f"\n{'='*50}")
            logger.debug(f"[DUPLICATE] 유사도: {similarity:.3f}")
            logger.debug(f"[NEW] {content[:150]}...")
            logger.debug(f"[EXISTING] {similar_preview}...")
            logger.debug(f"{'='*50}")
            return None

        self.global_embeddings.append(embedding)
        self.global_contents.append(content[:200])

        return {
            "content": content,
            "category": self.determine_category(role, content),
            "source": "kiro_chat_import",
            "tags": ["kiro", "semantic", role]
        }

    # -------------------------
    # Summarization
    # -------------------------
    def simple_summarize(self, text: str, max_sentences: int = 3) -> str:
        text = text.strip()
        if len(text) < 100:
            return text

        sentences = re.split(r'[.!?]+\s+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if len(sentences) <= max_sentences:
            return '. '.join(sentences) + ('.' if not text.endswith('.') else '')

        sentence_scores = []
        for sentence in sentences:
            score = len(sentence)

            important_keywords = [
                '결정', 'decision', '구현', 'implement', '문제', 'problem',
                '해결', 'solve', '변경', 'change', '추가', 'add', '수정', 'fix'
            ]
            for keyword in important_keywords:
                if keyword.lower() in sentence.lower():
                    score *= 1.5
                    break

            if '```' in sentence or 'def ' in sentence or 'class ' in sentence:
                score *= 2

            if len(sentence) < 50:
                score *= 0.5
            elif len(sentence) > 500:
                score *= 0.8

            sentence_scores.append((sentence, score))

        sentence_scores.sort(key=lambda x: x[1], reverse=True)
        top_sentences = [s[0] for s in sentence_scores[:max_sentences]]

        result_sentences = []
        for sentence in sentences:
            if sentence in top_sentences:
                result_sentences.append(sentence)
                if len(result_sentences) >= max_sentences:
                    break

        summary = '. '.join(result_sentences)
        if not summary.endswith('.'):
            summary += '.'

        if self.verbose_level >= 3:
            self._print_summary_comparison(text, summary, "간단한 요약")

        return summary

    def _print_summary_comparison(self, original: str, summary: str, method: str) -> None:
        print(f"\n{'='*80}")
        print(f"📝 {method} 비교")
        print(f"{'='*80}")
        print(f"📊 압축률: {len(original)} → {len(summary)} 문자 ({len(summary)/len(original)*100:.1f}%)")
        print(f"\n🔤 원문 ({len(original)}자):")
        print("-" * 40)
        print(original[:500] + ("..." if len(original) > 500 else ""))
        print(f"\n✨ 요약본 ({len(summary)}자):")
        print("-" * 40)
        print(summary)
        print(f"{'='*80}\n")

    def _make_qwen_prompt(self, text: str) -> List[Dict[str, str]]:
        # 스타일/언어 옵션 반영
        lang = self.summary_language.lower()
        style = self.summary_style.lower()

        if lang == "en":
            lang_inst = "Write the summary in English."
        else:
            lang_inst = "한국어로 요약해줘."

        if style == "paragraph":
            fmt_inst = "One short paragraph. No bullet points."
        else:
            fmt_inst = "5~8개 불릿으로. 각 불릿은 짧게."

        system = (
            "You are a helpful assistant that writes concise, faithful summaries. "
            "Never add facts that are not in the source."
        )

        user = (
            f"{lang_inst}\n"
            f"{fmt_inst}\n"
            "- 원문에 없는 내용은 추가하지 말 것\n"
            "- 결정사항/규칙/제약/액션아이템/오류-해결 중심\n"
            "- 불필요한 시스템 로그/메타 문구는 제외\n\n"
            "TEXT:\n"
            f"{text}"
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def qwen_summarize(self, text: str, max_new_tokens: Optional[int] = None) -> str:
        if self.qwen_model is None or self.qwen_tokenizer is None:
            return self.simple_summarize(text)

        try:
            import torch
        except ImportError:
            return self.simple_summarize(text)

        txt = text.strip()
        if len(txt) < 120:
            return txt

        messages = self._make_qwen_prompt(txt)
        prompt = self.qwen_tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.qwen_tokenizer(prompt, return_tensors="pt")
        inputs = {k: v.to(self.qwen_model.device) for k, v in inputs.items()}

        gen_max = max_new_tokens if max_new_tokens is not None else self.qwen_max_new_tokens

        with torch.no_grad():
            out = self.qwen_model.generate(
                **inputs,
                max_new_tokens=gen_max,
                temperature=float(self.qwen_temperature),
                top_p=float(self.qwen_top_p),
                do_sample=True,
                repetition_penalty=1.05,
            )

        gen = out[0][inputs["input_ids"].shape[-1]:]
        summary = self.qwen_tokenizer.decode(gen, skip_special_tokens=True).strip()
        if not summary:
            return self.simple_summarize(text)

        if self.verbose_level >= 3:
            self._print_summary_comparison(txt, summary, f"Qwen 요약 ({self.summary_model_name})")

        return summary

    def ai_summarize(self, text: str, max_length: int = 500) -> str:
        """
        요약 엔진 통합:
        - Qwen backend: generate 기반
        - HF seq2seq backend: pipeline("summarization")
        - 실패 시: simple_summarize
        """
        # Qwen 경로
        if self.qwen_model is not None:
            input_text = text.strip()
            if len(input_text) > 12000:
                input_text = input_text[:12000] + "..."
            # max_length는 '문자' 의미로 들어오기도 해서, 여기서는 new_tokens 상한으로 매핑
            return self.qwen_summarize(input_text, max_new_tokens=min(768, max(96, max_length)))

        # HF seq2seq 경로
        if self.summary_model is None:
            return self.simple_summarize(text)

        try:
            input_text = text.strip()
            if len(input_text) < 100:
                return input_text

            max_input_length = 2500
            if len(input_text) > max_input_length:
                input_text = input_text[:max_input_length] + "..."

            model_name = getattr(self.summary_model.model.config, 'name_or_path', 'unknown').lower()

            base_max_length = min(max_length, max(50, len(input_text) // 3))
            base_min_length = min(30, max(10, len(input_text) // 10))

            summarization_kwargs = self._get_model_specific_params(
                model_name, base_max_length, base_min_length, max_length, len(input_text)
            )

            result = self.summary_model(input_text, **summarization_kwargs)
            summary = self._extract_summary_safely(result)
            if summary:
                if self.verbose_level >= 3:
                    self._print_summary_comparison(input_text, summary, f"AI 요약 ({model_name})")
                return summary

            return self.simple_summarize(text)

        except Exception as e:
            logger.error(f"AI 요약 중 예외 발생: {type(e).__name__}: {str(e)}")
            return self.simple_summarize(text)

    def _get_model_specific_params(self, model_name: str, base_max_length: int,
                                  base_min_length: int, max_length: int, input_length: int) -> dict:
        params = {
            "max_length": base_max_length,
            "min_length": base_min_length,
            "do_sample": False,
            "truncation": True
        }

        if "t5" in model_name:
            params = {
                "max_new_tokens": base_max_length,
                "min_new_tokens": base_min_length,
                "do_sample": False,
                "truncation": True
            }
        elif "pegasus" in model_name:
            params.update({
                "max_length": min(max_length, max(100, input_length // 2)),
                "min_length": min(50, max(20, input_length // 8)),
                "length_penalty": 2.0,
                "num_beams": 4,
                "early_stopping": True
            })
        elif "bart" in model_name:
            params.update({
                "length_penalty": 2.0,
                "num_beams": 4,
                "early_stopping": True,
                "no_repeat_ngram_size": 3
            })
        elif "kobart" in model_name:
            params.update({
                "length_penalty": 1.5,
                "num_beams": 3,
                "early_stopping": True
            })

        return params

    def _extract_summary_safely(self, result) -> Optional[str]:
        try:
            if isinstance(result, list):
                if len(result) == 0:
                    return None
                first_item = result[0]
                if isinstance(first_item, dict):
                    if 'summary_text' in first_item:
                        summary = first_item['summary_text']
                        return summary.strip() if isinstance(summary, str) and summary.strip() else None
                elif isinstance(first_item, str):
                    return first_item.strip() if first_item.strip() else None
            elif isinstance(result, dict):
                if 'summary_text' in result and isinstance(result['summary_text'], str):
                    return result['summary_text'].strip() or None
            elif isinstance(result, str):
                return result.strip() or None
            return None
        except Exception as e:
            logger.error(f"요약 추출 중 오류: {type(e).__name__}: {str(e)}")
            return None

    # -------------------------
    # Summary mode processors
    # -------------------------
    def create_session_summary(self, messages: List[Dict], file_path: Path) -> Optional[Dict]:
        meaningful_messages = []
        for msg in messages:
            content = (msg.get('content', '') or '').strip()
            role = (msg.get('role', '') or '').strip()

            # 시스템 프롬프트/너무 짧은 메시지 스킵
            if (role == 'human' and self.is_system_prompt(content)) or len(content) < 30:
                continue

            # 세션 요약용 노이즈 라인 제거(간단)
            lines = content.splitlines()
            filtered_lines = [ln for ln in lines if not self._is_noise_line_for_summary(ln)]
            filtered = "\n".join(filtered_lines).strip()
            if len(filtered) < 30:
                continue

            meaningful_messages.append(f"[{role.upper()}] {filtered}")

        if len(meaningful_messages) < 2:
            return None

        full_conversation = '\n\n'.join(meaningful_messages)

        # 너무 길면 요약
        if len(full_conversation) > 1200:
            summary = self.ai_summarize(full_conversation, max_length=800)
        else:
            summary = full_conversation

        if self.verbose_level >= 3 and len(full_conversation) > 1200:
            self._print_summary_comparison(full_conversation, summary, "세션 요약")

        keywords = self.extract_keywords(full_conversation)

        return {
            "content": f"[세션 요약]\n\n{summary}\n\n[원본 메시지 수: {len(meaningful_messages)}개]",
            "category": "decision",
            "source": "kiro_chat_session_summary",
            "tags": ["kiro", "summary", "session"] + keywords[:5]
        }

    def extract_keywords(self, text: str) -> List[str]:
        words = re.findall(r'\b[a-zA-Z가-힣]{3,}\b', text.lower())
        stopwords = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
            '그리고', '하지만', '그런데', '그래서', '따라서', '또한', '그러나', '이것', '저것',
            'you', 'are', 'will', 'can', 'use'
        }
        words = [w for w in words if w not in stopwords and len(w) > 2]
        from collections import Counter
        word_counts = Counter(words)
        return [word for word, _count in word_counts.most_common(10)]

    def process_message_summary(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        content = message.get('content', '')
        role = message.get('role', '')

        if not content or len(content.strip()) < 10:
            return None

        if role == 'human' and self.is_system_prompt(content):
            return None

        if len(content.strip()) < 200:
            return None

        if len(content) > 2000:
            summarized_content = self.ai_summarize(content, max_length=600)
            content = f"[요약]\n{summarized_content}\n\n[원본 길이: {len(content)}자]"
            self.stats["summaries_created"] += 1

        return {
            "content": content,
            "category": self.determine_category(role, content),
            "source": "kiro_chat_summary",
            "tags": ["kiro", "summary", role]
        }

    # -------------------------
    # Router
    # -------------------------
    def process_message(self, message: Dict, file_path: Path) -> Optional[Dict]:
        if self.mode == ImportMode.RAW:
            return self.process_message_raw(message, file_path)
        elif self.mode == ImportMode.HYBRID:
            return self.process_message_hybrid(message, file_path)
        elif self.mode == ImportMode.SEMANTIC:
            return self.process_message_semantic(message, file_path)
        elif self.mode == ImportMode.SUMMARY:
            return self.process_message_summary(message, file_path)
        else:
            return self.process_message_clean(message, file_path)

    # -------------------------
    # Import
    # -------------------------
    async def import_chat_file(self, file_path: Path, project_id: Optional[str] = None) -> int:
        chat_data = self.read_chat_file(file_path)
        if not chat_data:
            self.stats["errors"] += 1
            return 0

        messages = chat_data.get('chat', [])
        if not messages:
            return 0

        pid = project_id or self.extract_project_id(file_path)

        imported = 0

        if self.mode == ImportMode.SUMMARY:
            session_summary = self.create_session_summary(messages, file_path)
            if session_summary:
                if self.dry_run:
                    logger.debug(f"[DRY-RUN] Would import session summary: {session_summary['content'][:120]}...")
                    imported += 1
                else:
                    try:
                        params = AddParams(
                            content=session_summary["content"],
                            project_id=pid,
                            category=session_summary["category"],
                            source=session_summary["source"],
                            tags=session_summary["tags"]
                        )
                        await self.storage.add_memory(params)
                        imported += 1
                        self.stats["summaries_created"] += 1
                    except Exception as e:
                        logger.error(f"세션 요약 저장 실패: {e}")
                        self.stats["errors"] += 1

        for msg in messages:
            processed = self.process_message(msg, file_path)
            if not processed:
                self.stats["messages_skipped"] += 1
                continue

            if self.dry_run:
                logger.debug(f"[DRY-RUN] Would import: {processed['content'][:120]}...")
                imported += 1
                continue

            try:
                params = AddParams(
                    content=processed["content"],
                    project_id=pid,
                    category=processed["category"],
                    source=processed["source"],
                    tags=processed["tags"]
                )
                await self.storage.add_memory(params)
                imported += 1
            except Exception as e:
                logger.error(f"메모리 저장 실패: {e}")
                self.stats["errors"] += 1

        return imported

    async def import_all(self, chat_dir: str, project_id: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, int]:
        chat_files = self.find_chat_files(chat_dir)

        if limit:
            chat_files = chat_files[:limit]

        if not chat_files:
            logger.warning("Import할 Chat 파일이 없습니다")
            return self.stats

        print(f"\n{'='*60}")
        print(f"Kiro Chat Import to mem-mesh")
        print(f"{'='*60}")
        print(f"Mode: {self.mode.value}")
        if self.mode == ImportMode.SEMANTIC:
            print(f"Similarity Threshold: {self.similarity_threshold}")
            print(f"Embedding Model: {self.embedding_model_name}")
        if self.mode == ImportMode.SUMMARY:
            print(f"Summary Model: {self.summary_model_name}")
            print(f"Summary Backend: {self._resolve_summary_backend().value}")
        print(f"Files: {len(chat_files)}")
        print(f"DB: {self.db_path}")
        print(f"Dry-run: {self.dry_run}")
        print(f"{'='*60}\n")

        for i, file_path in enumerate(chat_files, 1):
            try:
                imported = await self.import_chat_file(file_path, project_id)
                self.stats["files_processed"] += 1
                self.stats["messages_imported"] += imported

                if i % 100 == 0:
                    logger.info(f"진행: {i}/{len(chat_files)} 파일 처리됨")

            except Exception as e:
                logger.error(f"파일 처리 실패 ({file_path}): {e}")
                self.stats["errors"] += 1

        print(f"\n{'='*60}")
        print(f"Import 완료")
        print(f"{'='*60}")
        print(f"처리된 파일: {self.stats['files_processed']}")
        print(f"Import된 메시지: {self.stats['messages_imported']}")
        print(f"스킵된 메시지: {self.stats['messages_skipped']}")
        if self.mode == ImportMode.SEMANTIC:
            print(f"의미적 중복 제거: {self.stats['semantic_duplicates']}")
        if self.mode == ImportMode.SUMMARY:
            print(f"생성된 요약: {self.stats['summaries_created']}")
        print(f"에러: {self.stats['errors']}")
        print(f"{'='*60}\n")

        return self.stats


async def main():
    parser = argparse.ArgumentParser(
        description="Kiro Chat 파일을 mem-mesh에 bulk import"
    )
    parser.add_argument(
        "chat_dir",
        nargs="?",
        default="imports",
        help="Chat 파일이 있는 디렉토리 (기본: imports)"
    )
    parser.add_argument(
        "--mode",
        choices=["raw", "hybrid", "clean", "semantic", "summary"],
        default="hybrid",
        help="Import 모드 (기본: hybrid)"
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=float(os.environ.get("KIRO_SIMILARITY_THRESHOLD", "0.9")),
        help="semantic 모드에서 중복 판정 임계값 (기본: 0.9, 환경변수: KIRO_SIMILARITY_THRESHOLD)"
    )
    parser.add_argument(
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="임베딩 모델 (기본: all-MiniLM-L6-v2)"
    )

    # Summary options
    parser.add_argument(
        "--summary-model",
        default="facebook/bart-large-cnn",
        help="요약 모델 (기본: facebook/bart-large-cnn). Qwen 사용 시 예: Qwen/Qwen2.5-7B-Instruct"
    )
    parser.add_argument(
        "--summary-backend",
        choices=["auto", "hf_seq2seq", "qwen_chat"],
        default="auto",
        help="요약 백엔드 (기본: auto)"
    )
    parser.add_argument(
        "--summary-language",
        choices=["ko", "en"],
        default="ko",
        help="요약 언어 (기본: ko)"
    )
    parser.add_argument(
        "--summary-style",
        choices=["bullets", "paragraph"],
        default="bullets",
        help="요약 형식 (기본: bullets)"
    )
    parser.add_argument(
        "--qwen-device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="Qwen 실행 디바이스 (기본: auto)"
    )
    parser.add_argument(
        "--qwen-max-new-tokens",
        type=int,
        default=384,
        help="Qwen 요약 생성 max_new_tokens (기본: 384)"
    )
    parser.add_argument(
        "--qwen-temperature",
        type=float,
        default=0.2,
        help="Qwen temperature (기본: 0.2)"
    )
    parser.add_argument(
        "--qwen-top-p",
        type=float,
        default=0.9,
        help="Qwen top_p (기본: 0.9)"
    )

    parser.add_argument(
        "--db-path",
        default="data/memories.db",
        help="데이터베이스 경로 (기본: data/memories.db)"
    )
    parser.add_argument(
        "--project-id",
        help="프로젝트 ID (기본: 파일 경로에서 자동 추출)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 저장 없이 미리보기"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="처리할 최대 파일 수"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="상세 로그 출력 (-v: INFO, -vv: DEBUG, -vvv: 원문/요약 비교)"
    )

    args = parser.parse_args()

    # verbose 레벨에 따른 로깅 설정
    if args.verbose >= 2:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.verbose >= 1:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    importer = KiroChatImporter(
        db_path=args.db_path,
        mode=ImportMode(args.mode),
        dry_run=args.dry_run,
        similarity_threshold=args.similarity_threshold,
        embedding_model=args.embedding_model,
        summary_model=args.summary_model,
        summary_backend=SummaryBackend(args.summary_backend),
        summary_language=args.summary_language,
        summary_style=args.summary_style,
        qwen_device=args.qwen_device,
        qwen_max_new_tokens=args.qwen_max_new_tokens,
        qwen_temperature=args.qwen_temperature,
        qwen_top_p=args.qwen_top_p,
        verbose_level=args.verbose
    )

    try:
        await importer.initialize()
        await importer.import_all(
            chat_dir=args.chat_dir,
            project_id=args.project_id,
            limit=args.limit
        )
    finally:
        await importer.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
