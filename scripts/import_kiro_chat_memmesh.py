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
        embedding_model: str = "all-MiniLM-L6-v2",
        summary_model: str = "facebook/bart-large-cnn",
        verbose_level: int = 0
    ):
        self.db_path = db_path
        self.mode = mode
        self.dry_run = dry_run
        self.similarity_threshold = similarity_threshold
        self.storage: Optional[DirectStorageBackend] = None
        self.embedding_model: Optional[SentenceTransformer] = None
        self.embedding_model_name = embedding_model
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
            try:
                from transformers import pipeline
                logger.info(f"Loading summarization model: {self.summary_model_name}")
                
                # 더 나은 요약 모델들 우선 시도 (성능 순)
                lightweight_models = [
                    "facebook/bart-large-cnn",        # 고품질 BART (큰 모델)
                    "sshleifer/distilbart-cnn-12-6",  # 가벼운 BART
                    "google/pegasus-xsum",            # Pegasus (뉴스 요약 특화)
                    "ainize/kobart-news",             # 한국어 BART
                    "microsoft/DialoGPT-medium",      # 대화 특화
                    "t5-base",                        # T5 base
                    "t5-small"                        # T5 small (폴백)
                ]
                
                model_to_use = self.summary_model_name
                if self.summary_model_name in ["facebook/bart-large-cnn", "sshleifer/distilbart-cnn-12-6"]:
                    # 기본 모델인 경우 고품질 모델부터 시도
                    for model in lightweight_models:
                        try:
                            logger.info(f"Trying model: {model}")
                            self.summary_model = pipeline(
                                "summarization",
                                model=model,
                                device=-1,  # CPU 사용
                                framework="pt",
                                return_tensors=False,  # 텐서 반환 방지
                                clean_up_tokenization_spaces=True  # 토큰화 공백 정리
                            )
                            model_to_use = model
                            break
                        except Exception as e:
                            logger.warning(f"Failed to load {model}: {e}")
                            continue
                else:
                    # 사용자 지정 모델 사용
                    try:
                        self.summary_model = pipeline(
                            "summarization",
                            model=self.summary_model_name,
                            device=-1,
                            framework="pt",
                            return_tensors=False,
                            clean_up_tokenization_spaces=True
                        )
                        model_to_use = self.summary_model_name
                    except Exception as e:
                        logger.warning(f"Failed to load custom model {self.summary_model_name}: {e}")
                        # 폴백으로 고품질 모델부터 시도
                        for model in lightweight_models:
                            try:
                                logger.info(f"Fallback to model: {model}")
                                self.summary_model = pipeline(
                                    "summarization",
                                    model=model,
                                    device=-1,
                                    framework="pt",
                                    return_tensors=False,
                                    clean_up_tokenization_spaces=True
                                )
                                model_to_use = model
                                break
                            except Exception as e2:
                                logger.warning(f"Failed to load fallback {model}: {e2}")
                                continue
                
                if self.summary_model:
                    logger.info(f"Summarization model loaded: {model_to_use}")
                else:
                    logger.warning("모든 요약 모델 로드 실패, 간단한 텍스트 요약 사용")
                    
            except ImportError:
                logger.error("transformers 라이브러리가 필요합니다: pip install transformers torch")
                raise
            except Exception as e:
                logger.warning(f"요약 모델 로드 실패, 간단한 텍스트 요약 사용: {e}")
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
        
        # 내용이 10000자 초과시 잘라내기
        if len(content) > 10000:
            content = content[:9900] + "\n\n[... truncated ...]"
        
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
        
        # 내용이 10000자 초과시 잘라내기
        if len(content) > 10000:
            content = content[:9900] + "\n\n[... truncated ...]"
        
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
        
        # 내용이 10000자 초과시 잘라내기
        if len(content) > 10000:
            content = content[:9900] + "\n\n[... truncated ...]"
        
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
    
    def ai_summarize(self, text: str, max_length: int = 500) -> str:
        """AI 모델을 사용한 요약"""
        if self.summary_model is None:
            return self.simple_summarize(text)
        
        try:
            # 입력 텍스트 전처리
            input_text = text.strip()
            if len(input_text) < 100:
                return input_text
            
            # 토크나이저 제한을 고려하여 입력 길이 조정
            # BART는 보통 1024 토큰 제한이 있음
            max_input_length = 2500  # 안전한 문자 수 제한 (약 500-600 토큰)
            if len(input_text) > max_input_length:
                input_text = input_text[:max_input_length] + "..."
                logger.debug(f"Input truncated to {max_input_length} characters")
            
            # 요약 생성 - 모델별로 다른 파라미터 사용
            model_name = getattr(self.summary_model.model.config, 'name_or_path', '').lower()
            
            # 기본 파라미터
            base_max_length = min(max_length, max(50, len(input_text) // 3))
            base_min_length = min(30, max(10, len(input_text) // 10))
            
            summarization_kwargs = {
                "max_length": base_max_length,
                "min_length": base_min_length,
                "do_sample": False,
                "truncation": True,
                "padding": False  # padding 비활성화
            }
            
            # 모델별 특화 파라미터
            if "t5" in model_name:
                # T5 모델의 경우
                summarization_kwargs.update({
                    "max_new_tokens": base_max_length,
                    "min_new_tokens": base_min_length
                })
                summarization_kwargs.pop("max_length", None)
                summarization_kwargs.pop("min_length", None)
            elif "pegasus" in model_name:
                # Pegasus 모델의 경우 더 긴 요약 허용
                summarization_kwargs.update({
                    "max_length": min(max_length, max(100, len(input_text) // 2)),
                    "min_length": min(50, max(20, len(input_text) // 8)),
                    "length_penalty": 2.0,  # 길이 페널티
                    "num_beams": 4,  # 빔 서치
                    "early_stopping": True
                })
            elif "bart" in model_name:
                # BART 모델의 경우 최적화된 파라미터
                summarization_kwargs.update({
                    "length_penalty": 2.0,
                    "num_beams": 4,
                    "early_stopping": True,
                    "no_repeat_ngram_size": 3  # 반복 방지
                })
            elif "kobart" in model_name:
                # 한국어 BART의 경우
                summarization_kwargs.update({
                    "length_penalty": 1.5,
                    "num_beams": 3,
                    "early_stopping": True
                })
            
            # padding 파라미터 제거 (일부 모델에서 지원하지 않음)
            summarization_kwargs.pop("padding", None)
            
            result = self.summary_model(input_text, **summarization_kwargs)
            
            if result and len(result) > 0 and 'summary_text' in result[0]:
                summary = result[0]['summary_text'].strip()
                
                # -vvv 옵션일 때 원문과 요약본 비교 출력
                if self.verbose_level >= 3:
                    self._print_summary_comparison(input_text, summary, "AI 요약")
                
                return summary if summary else self.simple_summarize(text)
            else:
                return self.simple_summarize(text)
                
        except Exception as e:
            logger.warning(f"AI 요약 실패 ({type(e).__name__}: {str(e)[:100]}), 간단한 요약 사용")
            return self.simple_summarize(text)
    
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
                        await self.storage.add_memory(params)
                        imported += 1
                        self.stats["summaries_created"] += 1
                    except Exception as e:
                        logger.error(f"세션 요약 저장 실패: {e}")
                        self.stats["errors"] += 1
        
        # 개별 메시지 처리
        for msg in messages:
            processed = self.process_message(msg, file_path)
            if not processed:
                self.stats["messages_skipped"] += 1
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
                await self.storage.add_memory(params)
                imported += 1
            except Exception as e:
                logger.error(f"메모리 저장 실패: {e}")
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
        default=float(os.environ.get("KIRO_SIMILARITY_THRESHOLD", "0.85")),
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
        help="요약 모델 (기본: facebook/bart-large-cnn, 고품질 모델)"
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
