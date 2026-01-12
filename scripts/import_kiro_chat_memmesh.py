#!/usr/bin/env python3
"""
Kiro Chat 파일을 mem-mesh에 bulk import하는 스크립트

사용법:
    python scripts/import_kiro_chat_memmesh.py [chat_dir] [options]

옵션:
    --mode: raw | hybrid | clean | semantic (기본: hybrid)
        - raw: 원본 데이터 그대로 저장
        - hybrid: 시스템 프롬프트 제거, 의미있는 대화만 추출 (기본값)
        - clean: 코드/결정사항만 추출
        - semantic: 임베딩 기반 의미적 중복 제거 + hybrid 필터링
    --similarity-threshold: semantic 모드에서 중복 판정 임계값 (기본: 0.85)
    --db-path: 데이터베이스 경로 (기본: data/memories.db)
    --project-id: 프로젝트 ID (기본: 파일 경로에서 추출)
    --dry-run: 실제 저장 없이 미리보기
    --limit: 처리할 최대 파일 수
"""
import sys
import os
import json
import re
import asyncio
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum

import numpy as np
from sentence_transformers import SentenceTransformer

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv()

from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import AddParams

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# .env에서 기본 임베딩 모델 가져오기
DEFAULT_EMBEDDING_MODEL = os.getenv("MEM_MESH_EMBEDDING_MODEL", "all-MiniLM-L6-v2")


class ImportMode(Enum):
    RAW = "raw"
    HYBRID = "hybrid"
    CLEAN = "clean"
    SEMANTIC = "semantic"
    SUMMARY = "summary"


class KiroChatImporter:
    """Kiro Chat 파일을 mem-mesh에 import하는 클래스"""
    
    # 시스템 프롬프트 시작 패턴
    SYSTEM_PROMPT_PATTERNS = [
        r'^# System Prompt',
        r'^<identity>',
        r'^You are Kiro',
    ]
    
    # 코드 블록 패턴
    CODE_BLOCK_PATTERN = re.compile(r'```[\w]*\n[\s\S]*?```')
    
    def __init__(
        self,
        db_path: str = "data/memories.db",
        mode: ImportMode = ImportMode.HYBRID,
        dry_run: bool = False,
        similarity_threshold: float = 0.85,
        embedding_model: Optional[str] = None,  # None이면 .env에서 읽음
        summary_model: str = "facebook/bart-large-cnn",
        verbose_level: int = 0
    ):
        self.db_path = db_path
        self.mode = mode
        self.dry_run = dry_run
        self.similarity_threshold = similarity_threshold
        self.storage: Optional[DirectStorageBackend] = None
        self.embedding_model: Optional[SentenceTransformer] = None
        # .env에서 기본값 사용
        self.embedding_model_name = embedding_model or DEFAULT_EMBEDDING_MODEL
        self.summary_model_name = summary_model
        self.summary_model = None
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
            "duplicate_messages": 0,  # 중복으로 스킵된 메시지 수
            "filtered_messages": 0,   # 필터링으로 스킵된 메시지 수 (시스템 프롬프트 등)
            "errors": 0
        }
    
    async def initialize(self) -> None:
        """스토리지 백엔드 초기화"""
        if not self.dry_run:
            self.storage = DirectStorageBackend(self.db_path)
            await self.storage.initialize()
            logger.info(f"Storage initialized: {self.db_path}")
        
        # semantic 모드일 때 임베딩 모델 로드
        if self.mode == ImportMode.SEMANTIC:
            logger.info(f"Loading embedding model: {self.embedding_model_name}")
            # 로컬 캐시 우선 사용 (오프라인 모드)
            self.embedding_model = SentenceTransformer(
                self.embedding_model_name,
                local_files_only=False  # 캐시 없으면 다운로드 시도
            )
            logger.info("Embedding model loaded")
        
        # summary 모드일 때 요약 모델 로드
        if self.mode == ImportMode.SUMMARY:
            # qwen-cli 사용 여부 확인
            if self.summary_model_name == "qwen-cli":
                logger.info("qwen-cli 요약 모드로 설정됨")
                # qwen 명령어 사용 가능 여부 확인
                try:
                    import subprocess
                    result = subprocess.run(["qwen", "--help"], capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        logger.info("qwen-cli 사용 가능 확인됨")
                        self.summary_model = "qwen-cli"  # 특별한 마커로 설정
                    else:
                        logger.error("qwen 명령어를 찾을 수 없습니다. qwen-cli가 설치되어 있는지 확인하세요.")
                        self.summary_model = None
                except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                    logger.error(f"qwen 명령어 확인 실패: {e}")
                    logger.error("qwen-cli가 설치되어 있고 PATH에 있는지 확인하세요.")
                    self.summary_model = None
                except Exception as e:
                    logger.error(f"qwen-cli 확인 중 예외 발생: {e}")
                    self.summary_model = None
            else:
                # 기존 transformers 모델 로드 로직
                try:
                    from transformers import pipeline
                    logger.info(f"Loading summarization model: {self.summary_model_name}")
                    
                    # 더 나은 요약 모델들 우선 시도 (성능 순)
                    lightweight_models = [
                        "sshleifer/distilbart-cnn-12-6",  # 가벼운 BART (우선)
                        "facebook/bart-large-cnn",        # 고품질 BART
                        "t5-small",                       # T5 small (빠름)
                        "google/pegasus-xsum",            # Pegasus (뉴스 요약 특화)
                        "t5-base",                        # T5 base
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
                                device=-1,  # CPU 사용
                                framework="pt",
                                return_tensors=False,
                                clean_up_tokenization_spaces=True,
                                trust_remote_code=False  # 보안상 원격 코드 실행 방지
                            )
                            model_to_use = self.summary_model_name
                            model_loaded = True
                            logger.info(f"사용자 지정 모델 로드 성공: {model_to_use}")
                        except Exception as e:
                            logger.warning(f"사용자 지정 모델 로드 실패 {self.summary_model_name}: {e}")
                    
                    # 폴백 모델들 시도
                    if not model_loaded:
                        models_to_try = [self.summary_model_name] if self.summary_model_name in lightweight_models else lightweight_models
                        
                        for model in models_to_try:
                            try:
                                logger.info(f"모델 시도: {model}")
                                self.summary_model = pipeline(
                                    "summarization",
                                    model=model,
                                    device=-1,  # CPU 사용
                                    framework="pt",
                                    return_tensors=False,
                                    clean_up_tokenization_spaces=True,
                                    trust_remote_code=False
                                )
                                model_to_use = model
                                model_loaded = True
                                logger.info(f"모델 로드 성공: {model_to_use}")
                                break
                            except Exception as e:
                                logger.warning(f"모델 로드 실패 {model}: {e}")
                                continue
                    
                    if model_loaded:
                        # 모델 테스트
                        try:
                            test_text = "This is a test sentence for model validation. The model should be able to process this text without errors."
                            test_result = self.summary_model(test_text, max_length=50, min_length=10, do_sample=False)
                            logger.info(f"모델 테스트 성공: {model_to_use}")
                            logger.debug(f"테스트 결과: {test_result}")
                        except Exception as e:
                            logger.error(f"모델 테스트 실패: {e}")
                            self.summary_model = None
                            model_loaded = False
                    
                    if not model_loaded:
                        logger.warning("모든 요약 모델 로드 실패, 간단한 텍스트 요약만 사용")
                        self.summary_model = None
                        
                except ImportError:
                    logger.error("transformers 라이브러리가 필요합니다: pip install transformers torch")
                    raise
                except Exception as e:
                    logger.warning(f"요약 모델 초기화 실패, 간단한 텍스트 요약 사용: {e}")
                    self.summary_model = None
    
    async def shutdown(self) -> None:
        """스토리지 백엔드 종료"""
        if self.storage:
            await self.storage.shutdown()
    
    def find_chat_files(self, chat_dir: str) -> List[Path]:
        """Chat 파일 찾기"""
        chat_path = Path(chat_dir)
        if not chat_path.exists():
            logger.warning(f"Chat 디렉토리가 없습니다: {chat_dir}")
            return []
        
        chat_files = list(chat_path.glob("**/*.chat"))
        logger.info(f"찾은 Chat 파일: {len(chat_files)}개")
        return chat_files
    
    def read_chat_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Chat 파일 읽기"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"파일 읽기 실패 ({file_path}): {e}")
            return None
    
    def is_system_prompt(self, content: str) -> bool:
        """시스템 프롬프트인지 확인"""
        for pattern in self.SYSTEM_PROMPT_PATTERNS:
            if re.search(pattern, content, re.MULTILINE):
                return True
        return False
    
    def extract_project_id(self, file_path: Path) -> str:
        """파일 경로에서 프로젝트 ID 추출
        
        경로 예: .../kiro.kiroagent/{workspace_hash}/{session_hash}.chat
        """
        parts = file_path.parts
        # kiro.kiroagent 다음의 해시를 workspace ID로 사용
        for i, part in enumerate(parts):
            if part == "kiro.kiroagent" and i + 1 < len(parts):
                return f"kiro-{parts[i + 1][:8]}"
        return "kiro-unknown"
    
    def determine_category(self, role: str, content: str) -> str:
        """메시지 내용에 따라 카테고리 결정"""
        content_lower = content.lower()
        
        # 코드 블록이 있으면 code_snippet
        if self.CODE_BLOCK_PATTERN.search(content):
            return "code_snippet"
        
        # 결정/설계 관련 키워드
        decision_keywords = ['결정', 'decided', 'decision', '설계', 'design', 'architecture']
        if any(kw in content_lower for kw in decision_keywords):
            return "decision"
        
        # 버그/에러 관련
        bug_keywords = ['bug', 'error', '버그', '에러', 'fix', '수정']
        if any(kw in content_lower for kw in bug_keywords):
            return "bug"
        
        # 아이디어 관련
        idea_keywords = ['idea', '아이디어', 'suggest', '제안', 'could', 'maybe']
        if any(kw in content_lower for kw in idea_keywords):
            return "idea"
        
        return "task"
    
    def process_message_raw(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        """RAW 모드: 원본 그대로 저장"""
        content = message.get('content', '')
        if not content or len(content.strip()) < 10:
            return None
        
        # 내용이 10000자 초과시 잘라내기 (pydantic 제한)
        max_content_length = 9900  # 약간의 여유를 둠
        if len(content) > max_content_length:
            content = content[:max_content_length] + "\n\n[... truncated due to length limit ...]"
            logger.debug(f"Content truncated from {len(message.get('content', ''))} to {len(content)} characters")
        
        return {
            "content": content,
            "category": self.determine_category(message.get('role', ''), content),
            "source": "kiro_chat_import",
            "tags": ["kiro", "raw", message.get('role', 'unknown')]
        }
    
    def process_message_hybrid(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        """HYBRID 모드: 시스템 프롬프트 제거, 의미있는 대화만"""
        content = message.get('content', '')
        role = message.get('role', '')
        
        # 빈 내용 스킵
        if not content or len(content.strip()) < 10:
            return None
        
        # 시스템 프롬프트 스킵
        if role == 'human' and self.is_system_prompt(content):
            return None
        
        # 너무 짧은 응답 스킵 (예: "understood", "I will follow...")
        if role == 'bot' and len(content.strip()) < 50:
            return None
        
        # 내용이 10000자 초과시 잘라내기 (pydantic 제한)
        max_content_length = 9900  # 약간의 여유를 둠
        if len(content) > max_content_length:
            content = content[:max_content_length] + "\n\n[... truncated due to length limit ...]"
            logger.debug(f"Content truncated from {len(message.get('content', ''))} to {len(content)} characters")
        
        return {
            "content": content,
            "category": self.determine_category(role, content),
            "source": "kiro_chat_import",
            "tags": ["kiro", "hybrid", role]
        }
    
    def process_message_clean(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        """CLEAN 모드: 코드/결정사항만 추출"""
        content = message.get('content', '')
        role = message.get('role', '')
        
        # bot 응답만 처리
        if role != 'bot':
            return None
        
        # 코드 블록이 있거나 충분히 긴 응답만
        has_code = bool(self.CODE_BLOCK_PATTERN.search(content))
        if not has_code and len(content) < 200:
            return None
        
        # 시스템 프롬프트 스킵
        if self.is_system_prompt(content):
            return None
        
        # 내용이 10000자 초과시 잘라내기 (pydantic 제한)
        max_content_length = 9900  # 약간의 여유를 둠
        if len(content) > max_content_length:
            content = content[:max_content_length] + "\n\n[... truncated due to length limit ...]"
            logger.debug(f"Content truncated from {len(message.get('content', ''))} to {len(content)} characters")
        
        return {
            "content": content,
            "category": "code_snippet" if has_code else "decision",
            "source": "kiro_chat_import",
            "tags": ["kiro", "clean", "bot"]
        }
    
    def compute_embedding(self, text: str) -> np.ndarray:
        """텍스트의 임베딩 벡터 계산"""
        if self.embedding_model is None:
            raise RuntimeError("Embedding model not initialized")
        return self.embedding_model.encode(text, convert_to_numpy=True)
    
    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """두 벡터 간 코사인 유사도 계산"""
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))
    
    def is_semantic_duplicate(self, content: str, embedding: np.ndarray) -> tuple[bool, Optional[str], float]:
        """글로벌 캐시에서 의미적 중복 여부 확인
        
        Returns:
            (is_duplicate, similar_content_preview, similarity_score)
        """
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
        """SEMANTIC 모드: hybrid 필터링 + 임베딩 기반 중복 제거"""
        content = message.get('content', '')
        role = message.get('role', '')
        
        # 빈 내용 스킵
        if not content or len(content.strip()) < 10:
            return None
        
        # 시스템 프롬프트 스킵
        if role == 'human' and self.is_system_prompt(content):
            return None
        
        # 너무 짧은 응답 스킵
        if role == 'bot' and len(content.strip()) < 50:
            return None
        
        # 내용이 10000자 초과시 잘라내기 (pydantic 제한)
        max_content_length = 9900  # 약간의 여유를 둠
        if len(content) > max_content_length:
            content = content[:max_content_length] + "\n\n[... truncated due to length limit ...]"
            logger.debug(f"Content truncated from {len(message.get('content', ''))} to {len(content)} characters")
        
        # 임베딩 계산 및 중복 체크
        embedding = self.compute_embedding(content[:2000])  # 임베딩은 앞부분만
        
        is_dup, similar_preview, similarity = self.is_semantic_duplicate(content, embedding)
        if is_dup:
            self.stats["semantic_duplicates"] += 1
            # verbose 모드에서 중복 정보 출력
            logger.debug(f"\n{'='*50}")
            logger.debug(f"[DUPLICATE] 유사도: {similarity:.3f}")
            logger.debug(f"[NEW] {content[:150]}...")
            logger.debug(f"[EXISTING] {similar_preview}...")
            logger.debug(f"{'='*50}")
            return None
        
        # 글로벌 캐시에 추가
        self.global_embeddings.append(embedding)
        self.global_contents.append(content[:200])  # 디버깅용 미리보기
        
        return {
            "content": content,
            "category": self.determine_category(role, content),
            "source": "kiro_chat_import",
            "tags": ["kiro", "semantic", role]
        }
    
    def simple_summarize(self, text: str, max_sentences: int = 3) -> str:
        """간단한 텍스트 요약 (모델 없이)"""
        # 텍스트 정리
        text = text.strip()
        if len(text) < 100:
            return text
        
        # 문장 분리 (더 정교하게)
        sentences = re.split(r'[.!?]+\s+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        
        if len(sentences) <= max_sentences:
            return '. '.join(sentences) + ('.' if not text.endswith('.') else '')
        
        # 길이와 중요도 기반으로 문장 점수 계산
        sentence_scores = []
        for sentence in sentences:
            score = len(sentence)  # 기본 점수는 길이
            
            # 중요한 키워드가 있으면 가중치 추가
            important_keywords = ['결정', 'decision', '구현', 'implement', '문제', 'problem', 
                                '해결', 'solve', '변경', 'change', '추가', 'add', '수정', 'fix']
            for keyword in important_keywords:
                if keyword.lower() in sentence.lower():
                    score *= 1.5
                    break
            
            # 코드 블록이 있으면 가중치 추가
            if '```' in sentence or 'def ' in sentence or 'class ' in sentence:
                score *= 2
            
            # 너무 짧거나 긴 문장은 점수 조정
            if len(sentence) < 50:
                score *= 0.5
            elif len(sentence) > 500:
                score *= 0.8
                
            sentence_scores.append((sentence, score))
        
        # 상위 문장들 선택
        sentence_scores.sort(key=lambda x: x[1], reverse=True)
        top_sentences = [s[0] for s in sentence_scores[:max_sentences]]
        
        # 원래 순서대로 재정렬 (가능한 경우)
        result_sentences = []
        for sentence in sentences:
            if sentence in top_sentences:
                result_sentences.append(sentence)
                if len(result_sentences) >= max_sentences:
                    break
        
        summary = '. '.join(result_sentences)
        if not summary.endswith('.'):
            summary += '.'
        
        # -vvv 옵션일 때 원문과 요약본 비교 출력
        if self.verbose_level >= 3:
            self._print_summary_comparison(text, summary, "간단한 요약")
            
        return summary
    
    def _print_summary_comparison(self, original: str, summary: str, method: str) -> None:
        """원문과 요약본 비교 출력 (vvv 모드용)"""
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
    
    def qwen_cli_summarize(self, text: str, max_length: int = 500) -> str:
        """qwen-cli를 사용한 요약"""
        try:
            import subprocess
            import json
            
            # 입력 텍스트 전처리
            input_text = text.strip()
            logger.debug(f"qwen-cli 입력 텍스트 길이: {len(input_text)} 문자")
            
            if len(input_text) < 100:
                logger.debug("입력 텍스트가 너무 짧음 (< 100자), 원본 반환")
                return input_text
            
            # 입력 길이 제한 (qwen-cli의 토큰 제한 고려)
            max_input_length = 4000  # qwen-cli에 적합한 길이
            if len(input_text) > max_input_length:
                input_text = input_text[:max_input_length] + "..."
                logger.debug(f"입력 텍스트를 {max_input_length}자로 잘라냄")
            
            # 요약 프롬프트 구성
            summary_prompt = f"""다음 텍스트를 한국어로 간결하게 요약해주세요. 주요 내용과 핵심 포인트를 포함하여 {max_length//4}자 이내로 요약하세요:

{input_text}

요약:"""
            
            logger.debug("qwen-cli 명령어 실행 시작...")
            logger.debug(f"프롬프트 길이: {len(summary_prompt)} 문자")
            
            # qwen 명령어 실행
            result = subprocess.run(
                ["qwen", "--prompt", summary_prompt],
                capture_output=True,
                text=True,
                timeout=60,  # 60초 타임아웃
                encoding='utf-8'
            )
            
            logger.debug(f"qwen-cli 실행 완료. 반환 코드: {result.returncode}")
            
            if result.returncode == 0:
                summary = result.stdout.strip()
                logger.debug(f"qwen-cli 원본 출력 길이: {len(summary)} 문자")
                
                if summary:
                    # 출력에서 불필요한 부분 제거 (프롬프트 반복 등)
                    summary = self._clean_qwen_output(summary, input_text)
                    
                    logger.debug(f"qwen-cli 요약 성공: {len(summary)} 문자")
                    
                    # -vvv 옵션일 때 원문과 요약본 비교 출력
                    if self.verbose_level >= 3:
                        self._print_summary_comparison(input_text, summary, "qwen-cli 요약")
                    
                    return summary
                else:
                    logger.warning("qwen-cli가 빈 결과 반환")
            else:
                logger.error(f"qwen-cli 실행 실패. 반환 코드: {result.returncode}")
                logger.error(f"stderr: {result.stderr}")
            
            # 폴백: 간단한 요약 사용
            logger.debug("qwen-cli 요약 실패, 간단한 요약으로 폴백")
            return self.simple_summarize(text)
            
        except subprocess.TimeoutExpired:
            logger.error("qwen-cli 실행 시간 초과 (60초)")
            return self.simple_summarize(text)
        except FileNotFoundError:
            logger.error("qwen 명령어를 찾을 수 없습니다. qwen-cli가 설치되어 있는지 확인하세요.")
            return self.simple_summarize(text)
        except Exception as e:
            logger.error(f"qwen-cli 요약 중 예외 발생: {type(e).__name__}: {str(e)}")
            return self.simple_summarize(text)
    
    def _clean_qwen_output(self, output: str, original_text: str) -> str:
        """qwen-cli 출력에서 불필요한 부분 제거"""
        try:
            # 출력에서 원본 텍스트나 프롬프트 부분 제거
            lines = output.split('\n')
            cleaned_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 프롬프트 반복이나 원본 텍스트 반복 스킵
                if "다음 텍스트를" in line or "요약해주세요" in line or "요약:" in line:
                    continue
                
                # 원본 텍스트의 일부가 그대로 반복되는 경우 스킵
                if len(line) > 50 and line in original_text:
                    continue
                
                cleaned_lines.append(line)
            
            # 정리된 결과 조합
            result = ' '.join(cleaned_lines)
            
            # 너무 길면 잘라내기
            if len(result) > 1000:
                result = result[:950] + "..."
            
            return result if result else output  # 정리 후 빈 결과면 원본 반환
            
        except Exception as e:
            logger.debug(f"qwen 출력 정리 중 오류: {e}")
            return output  # 오류 시 원본 반환
    def ai_summarize(self, text: str, max_length: int = 500) -> str:
        """AI 모델을 사용한 요약 (상세한 디버깅 포함)"""
        # qwen-cli 사용 여부 확인
        if self.summary_model == "qwen-cli":
            return self.qwen_cli_summarize(text, max_length)
        
        if self.summary_model is None:
            logger.debug("요약 모델이 로드되지 않음, 간단한 요약 사용")
            return self.simple_summarize(text)
        
        try:
            # 입력 텍스트 전처리 및 검증
            input_text = text.strip()
            logger.debug(f"입력 텍스트 길이: {len(input_text)} 문자")
            
            if len(input_text) < 100:
                logger.debug("입력 텍스트가 너무 짧음 (< 100자), 원본 반환")
                return input_text
            
            # 토크나이저 제한을 고려하여 입력 길이 조정
            max_input_length = 2500  # 안전한 문자 수 제한
            if len(input_text) > max_input_length:
                input_text = input_text[:max_input_length] + "..."
                logger.debug(f"입력 텍스트를 {max_input_length}자로 잘라냄")
            
            # 모델 정보 확인
            model_name = getattr(self.summary_model.model.config, 'name_or_path', 'unknown').lower()
            logger.debug(f"사용 중인 요약 모델: {model_name}")
            
            # 기본 파라미터 계산
            base_max_length = min(max_length, max(50, len(input_text) // 3))
            base_min_length = min(30, max(10, len(input_text) // 10))
            
            # 모델별 최적화된 파라미터 설정
            summarization_kwargs = self._get_model_specific_params(
                model_name, base_max_length, base_min_length, max_length, len(input_text)
            )
            
            logger.debug(f"요약 파라미터: {summarization_kwargs}")
            
            # 요약 생성 시도
            logger.debug("AI 요약 모델 호출 시작...")
            result = self.summary_model(input_text, **summarization_kwargs)
            logger.debug(f"AI 모델 반환 결과 타입: {type(result)}")
            logger.debug(f"AI 모델 반환 결과 길이: {len(result) if hasattr(result, '__len__') else 'N/A'}")
            
            # 결과 상세 분석
            if result:
                logger.debug(f"결과 내용 미리보기: {str(result)[:200]}...")
                
                # 안전한 결과 추출
                summary = self._extract_summary_safely(result)
                if summary:
                    logger.debug(f"요약 성공: {len(summary)} 문자")
                    
                    # -vvv 옵션일 때 원문과 요약본 비교 출력
                    if self.verbose_level >= 3:
                        self._print_summary_comparison(input_text, summary, f"AI 요약 ({model_name})")
                    
                    return summary
                else:
                    logger.warning("AI 모델이 유효한 요약을 생성하지 못함")
            else:
                logger.warning("AI 모델이 빈 결과 반환")
            
            # 폴백: 간단한 요약 사용
            logger.debug("AI 요약 실패, 간단한 요약으로 폴백")
            return self.simple_summarize(text)
                
        except IndexError as e:
            logger.error(f"AI 요약 중 IndexError 발생: {str(e)}")
            logger.error(f"모델: {getattr(self.summary_model.model.config, 'name_or_path', 'unknown')}")
            logger.error(f"입력 길이: {len(input_text) if 'input_text' in locals() else 'unknown'}")
            return self.simple_summarize(text)
        except Exception as e:
            logger.error(f"AI 요약 중 예외 발생: {type(e).__name__}: {str(e)}")
            logger.error(f"모델: {getattr(self.summary_model.model.config, 'name_or_path', 'unknown') if self.summary_model else 'None'}")
            return self.simple_summarize(text)
    
    def _get_model_specific_params(self, model_name: str, base_max_length: int, 
                                 base_min_length: int, max_length: int, input_length: int) -> dict:
        """모델별 최적화된 파라미터 반환"""
        # 기본 파라미터
        params = {
            "max_length": base_max_length,
            "min_length": base_min_length,
            "do_sample": False,
            "truncation": True
        }
        
        # 모델별 특화 파라미터
        if "t5" in model_name:
            # T5는 max_new_tokens 사용
            params = {
                "max_new_tokens": base_max_length,
                "min_new_tokens": base_min_length,
                "do_sample": False,
                "truncation": True
            }
        elif "pegasus" in model_name:
            # Pegasus는 더 긴 요약 허용
            params.update({
                "max_length": min(max_length, max(100, input_length // 2)),
                "min_length": min(50, max(20, input_length // 8)),
                "length_penalty": 2.0,
                "num_beams": 4,
                "early_stopping": True
            })
        elif "bart" in model_name:
            # BART 최적화
            params.update({
                "length_penalty": 2.0,
                "num_beams": 4,
                "early_stopping": True,
                "no_repeat_ngram_size": 3
            })
        elif "kobart" in model_name:
            # 한국어 BART
            params.update({
                "length_penalty": 1.5,
                "num_beams": 3,
                "early_stopping": True
            })
        
        return params
    
    def _extract_summary_safely(self, result) -> Optional[str]:
        """요약 결과에서 안전하게 텍스트 추출"""
        try:
            # 리스트 형태의 결과 처리
            if isinstance(result, list):
                if len(result) == 0:
                    logger.debug("결과 리스트가 비어있음")
                    return None
                
                first_item = result[0]
                logger.debug(f"첫 번째 결과 항목 타입: {type(first_item)}")
                
                if isinstance(first_item, dict):
                    # 딕셔너리에서 summary_text 추출
                    if 'summary_text' in first_item:
                        summary = first_item['summary_text']
                        if isinstance(summary, str) and summary.strip():
                            return summary.strip()
                        else:
                            logger.debug(f"summary_text가 비어있거나 문자열이 아님: {type(summary)}")
                    else:
                        logger.debug(f"summary_text 키가 없음. 사용 가능한 키: {list(first_item.keys())}")
                elif isinstance(first_item, str):
                    # 문자열 결과 직접 반환
                    if first_item.strip():
                        return first_item.strip()
                    else:
                        logger.debug("첫 번째 결과가 빈 문자열")
                else:
                    logger.debug(f"예상하지 못한 첫 번째 결과 타입: {type(first_item)}")
            
            # 딕셔너리 형태의 결과 처리
            elif isinstance(result, dict):
                if 'summary_text' in result:
                    summary = result['summary_text']
                    if isinstance(summary, str) and summary.strip():
                        return summary.strip()
                else:
                    logger.debug(f"딕셔너리에 summary_text 키가 없음. 사용 가능한 키: {list(result.keys())}")
            
            # 문자열 결과 직접 처리
            elif isinstance(result, str):
                if result.strip():
                    return result.strip()
                else:
                    logger.debug("결과가 빈 문자열")
            
            else:
                logger.debug(f"예상하지 못한 결과 타입: {type(result)}")
            
            return None
            
        except Exception as e:
            logger.error(f"요약 추출 중 오류: {type(e).__name__}: {str(e)}")
            return None
    
    def create_session_summary(self, messages: List[Dict], file_path: Path) -> Optional[Dict]:
        """Chat 세션 전체를 분석하여 요약 생성"""
        # 의미있는 메시지만 추출
        meaningful_messages = []
        for msg in messages:
            content = msg.get('content', '')
            role = msg.get('role', '')
            
            # 시스템 프롬프트나 너무 짧은 메시지 스킵
            if (role == 'human' and self.is_system_prompt(content)) or len(content.strip()) < 30:
                continue
            
            meaningful_messages.append(f"[{role.upper()}] {content}")
        
        if len(meaningful_messages) < 2:
            return None
        
        # 전체 대화 내용 결합
        full_conversation = '\n\n'.join(meaningful_messages)
        
        # 요약 생성
        if len(full_conversation) > 1000:
            summary = self.ai_summarize(full_conversation, max_length=800)
        else:
            summary = full_conversation
        
        # -vvv 옵션일 때 세션 요약 비교 출력
        if self.verbose_level >= 3 and len(full_conversation) > 1000:
            self._print_summary_comparison(full_conversation, summary, "세션 요약")
        
        # 주요 키워드 추출
        keywords = self.extract_keywords(full_conversation)
        
        return {
            "content": f"[세션 요약]\n\n{summary}\n\n[원본 메시지 수: {len(meaningful_messages)}개]",
            "category": "decision",  # 세션 요약은 주로 결정사항
            "source": "kiro_chat_session_summary",
            "tags": ["kiro", "summary", "session"] + keywords[:5]  # 상위 5개 키워드만
        }
    
    def extract_keywords(self, text: str) -> List[str]:
        """텍스트에서 키워드 추출"""
        # 간단한 키워드 추출 (빈도 기반)
        words = re.findall(r'\b[a-zA-Z가-힣]{3,}\b', text.lower())
        
        # 불용어 제거
        stopwords = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
                    '그리고', '하지만', '그런데', '그래서', '따라서', '또한', '그러나', '이것', '저것'}
        
        words = [w for w in words if w not in stopwords and len(w) > 2]
        
        # 빈도 계산
        from collections import Counter
        word_counts = Counter(words)
        
        return [word for word, count in word_counts.most_common(10)]
    
    def process_message_summary(self, message: Dict, _file_path: Path) -> Optional[Dict]:
        """SUMMARY 모드: 긴 응답 요약"""
        content = message.get('content', '')
        role = message.get('role', '')
        
        # 빈 내용 스킵
        if not content or len(content.strip()) < 10:
            return None
        
        # 시스템 프롬프트 스킵
        if role == 'human' and self.is_system_prompt(content):
            return None
        
        # 너무 짧은 응답 스킵
        if len(content.strip()) < 200:
            return None
        
        # 긴 응답만 요약 처리
        if len(content) > 2000:
            summarized_content = self.ai_summarize(content, max_length=600)
            content = f"[요약]\n{summarized_content}\n\n[원본 길이: {len(content)}자]"
            self.stats["summaries_created"] += 1
        
        # 내용이 10000자 초과시 잘라내기 (pydantic 제한) - 요약 후에도 길 수 있음
        max_content_length = 9900  # 약간의 여유를 둠
        if len(content) > max_content_length:
            content = content[:max_content_length] + "\n\n[... truncated due to length limit ...]"
            logger.debug(f"Summarized content still too long, truncated to {len(content)} characters")
        
        return {
            "content": content,
            "category": self.determine_category(role, content),
            "source": "kiro_chat_summary",
            "tags": ["kiro", "summary", role]
        }
    
    def process_message(self, message: Dict, file_path: Path) -> Optional[Dict]:
        """모드에 따라 메시지 처리"""
        if self.mode == ImportMode.RAW:
            return self.process_message_raw(message, file_path)
        elif self.mode == ImportMode.HYBRID:
            return self.process_message_hybrid(message, file_path)
        elif self.mode == ImportMode.SEMANTIC:
            return self.process_message_semantic(message, file_path)
        elif self.mode == ImportMode.SUMMARY:
            return self.process_message_summary(message, file_path)
        else:  # CLEAN
            return self.process_message_clean(message, file_path)
    
    async def import_chat_file(
        self, 
        file_path: Path, 
        project_id: Optional[str] = None
    ) -> int:
        """단일 Chat 파일 import"""
        chat_data = self.read_chat_file(file_path)
        if not chat_data:
            self.stats["errors"] += 1
            return 0
        
        messages = chat_data.get('chat', [])
        if not messages:
            return 0
        
        # 프로젝트 ID 결정
        pid = project_id or self.extract_project_id(file_path)
        
        imported = 0
        
        # SUMMARY 모드에서는 세션 요약도 생성
        if self.mode == ImportMode.SUMMARY:
            session_summary = self.create_session_summary(messages, file_path)
            if session_summary:
                if self.dry_run:
                    logger.debug(f"[DRY-RUN] Would import session summary: {session_summary['content'][:100]}...")
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
                        
                        # -vvv 모드에서 저장 전 상세 정보 출력
                        if self.verbose_level >= 3:
                            logger.info(f"[세션 요약 저장] 프로젝트: {pid}, 카테고리: {session_summary['category']}")
                            logger.info(f"[세션 요약 저장] 내용 길이: {len(session_summary['content'])} 문자")
                            logger.info(f"[세션 요약 저장] 내용 미리보기: {session_summary['content'][:200]}...")
                        
                        result = await self.storage.add_memory(params)
                        
                        # 중복 검출 시 상세 로깅
                        if hasattr(result, 'status') and result.status == "duplicate":
                            self.stats["duplicate_messages"] += 1  # 중복 세션 요약 카운트
                            if self.verbose_level >= 3:
                                logger.warning(f"[중복 세션 요약] 기존 메모리 ID: {result.id}")
                                logger.warning(f"[중복 세션 요약] 생성 시간: {result.created_at}")
                                logger.warning(f"[중복 세션 요약] 내용: {session_summary['content'][:100]}...")
                        else:
                            imported += 1
                            self.stats["summaries_created"] += 1
                            if self.verbose_level >= 3:
                                logger.info(f"[세션 요약 저장 성공] 새 메모리 ID: {result.id}")
                                
                    except Exception as e:
                        logger.error(f"세션 요약 저장 실패: {e}")
                        self.stats["errors"] += 1
        
        # 개별 메시지 처리
        for msg in messages:
            processed = self.process_message(msg, file_path)
            if not processed:
                self.stats["filtered_messages"] += 1  # 필터링으로 스킵
                continue
            
            if self.dry_run:
                logger.debug(f"[DRY-RUN] Would import: {processed['content'][:100]}...")
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
                
                # -vvv 모드에서 저장 전 상세 정보 출력
                if self.verbose_level >= 3:
                    logger.info(f"[메시지 저장] 프로젝트: {pid}, 카테고리: {processed['category']}")
                    logger.info(f"[메시지 저장] 소스: {processed['source']}, 태그: {processed['tags']}")
                    logger.info(f"[메시지 저장] 내용 길이: {len(processed['content'])} 문자")
                    logger.info(f"[메시지 저장] 내용 미리보기: {processed['content'][:200]}...")
                
                result = await self.storage.add_memory(params)
                
                # 중복 검출 시 상세 로깅
                if hasattr(result, 'status') and result.status == "duplicate":
                    self.stats["duplicate_messages"] += 1  # 중복 메시지 카운트
                    if self.verbose_level >= 3:
                        logger.warning(f"[중복 메시지] 기존 메모리 ID: {result.id}")
                        logger.warning(f"[중복 메시지] 생성 시간: {result.created_at}")
                        logger.warning(f"[중복 메시지] 카테고리: {processed['category']}, 태그: {processed['tags']}")
                        logger.warning(f"[중복 메시지] 내용: {processed['content'][:150]}...")
                        logger.warning(f"[중복 메시지] 파일: {file_path}")
                else:
                    imported += 1
                    if self.verbose_level >= 3:
                        logger.info(f"[메시지 저장 성공] 새 메모리 ID: {result.id}")
                        
            except Exception as e:
                logger.error(f"메모리 저장 실패: {e}")
                if self.verbose_level >= 3:
                    logger.error(f"[저장 실패 상세] 파일: {file_path}")
                    logger.error(f"[저장 실패 상세] 내용: {processed['content'][:100]}...")
                self.stats["errors"] += 1
        
        return imported
    
    async def import_all(
        self, 
        chat_dir: str, 
        project_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, int]:
        """모든 Chat 파일 import"""
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
        
        # 스킵된 메시지 상세 분석
        total_skipped = self.stats['filtered_messages'] + self.stats['duplicate_messages']
        print(f"스킵된 메시지: {total_skipped}")
        
        if self.verbose_level >= 1:
            print(f"  - 필터링으로 스킵: {self.stats['filtered_messages']} (시스템 프롬프트, 짧은 메시지 등)")
            print(f"  - 중복으로 스킵: {self.stats['duplicate_messages']} (이미 존재하는 내용)")
        
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
        help="semantic 모드에서 중복 판정 임계값 (기본: 0.85, 환경변수: KIRO_SIMILARITY_THRESHOLD)"
    )
    parser.add_argument(
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="임베딩 모델 (기본: all-MiniLM-L6-v2)"
    )
    parser.add_argument(
        "--summary-model",
        default="facebook/bart-large-cnn",
        help="요약 모델 (기본: facebook/bart-large-cnn, 고품질 모델) 또는 'qwen-cli'로 qwen CLI 사용"
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
