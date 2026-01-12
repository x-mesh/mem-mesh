#!/usr/bin/env python3
"""
Kiro Chat 파일을 읽어서 Qdrant에 저장하는 스크립트 (Async 버전)
"""
import os
import sys
import json
import glob
import uuid
import asyncio
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from qdrant_client import QdrantClient
from qdrant_client.async_qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer
from logging_config import setup_logging

logger = setup_logging("import_kiro_chat")


class AsyncKiroChatImporter:
    """Kiro Chat 파일 임포터 (비동기 버전)"""
    
    def __init__(self, chat_dir=None, max_workers=7):
        self.async_client = AsyncQdrantClient(host='localhost', port=6333)
        self.sync_client = QdrantClient(host='localhost', port=6333)  # 컬렉션 생성용
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.chat_dir = chat_dir
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        logger.info(f"Async Kiro Chat 임포터 초기화 완료 (워커: {max_workers}개)")
    
    def find_chat_files(self):
        """Kiro Chat 파일 찾기"""
        if self.chat_dir is None:
            chat_dir = Path.home() / "Library/Application Support/Kiro/User/globalStorage"
        else:
            chat_dir = Path(self.chat_dir)
        
        if not chat_dir.exists():
            logger.warning(f"Chat 디렉토리가 없습니다: {chat_dir}")
            return []
        
        chat_files = list(chat_dir.glob("**/*.chat"))
        logger.info(f"찾은 Chat 파일: {len(chat_files)}개 (경로: {chat_dir})")
        
        return chat_files
    
    async def read_chat_file_async(self, file_path):
        """Chat 파일 비동기 읽기"""
        try:
            loop = asyncio.get_event_loop()
            
            def read_file():
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    return json.loads(content)
            
            data = await loop.run_in_executor(self.executor, read_file)
            logger.debug(f"Chat 파일 읽음: {file_path.name}")
            return data
            
        except Exception as e:
            logger.error(f"Chat 파일 읽기 실패 ({file_path}): {e}")
            return None
    
    def extract_messages(self, chat_data):
        """Chat 데이터에서 메시지 추출"""
        messages = []
        
        if isinstance(chat_data, dict):
            if 'chat' in chat_data:
                messages = chat_data['chat']
            elif 'messages' in chat_data:
                messages = chat_data['messages']
            else:
                messages = [chat_data]
        elif isinstance(chat_data, list):
            messages = chat_data
        
        return messages
    
    async def create_embeddings_batch(self, contents):
        """배치로 임베딩 생성"""
        loop = asyncio.get_event_loop()
        
        def encode_batch():
            return self.embedding_model.encode(contents)
        
        embeddings = await loop.run_in_executor(self.executor, encode_batch)
        return embeddings
    
    async def save_messages_to_qdrant_async(self, messages, file_name, collection="kiro_chat", batch_size=50):
        """메시지를 Qdrant에 비동기 저장"""
        try:
            # 컬렉션 확인/생성 (동기)
            await self._ensure_collection_async(collection)
            
            saved_count = 0
            batch = []
            contents_batch = []
            
            for idx, message in enumerate(messages):
                if not isinstance(message, dict):
                    continue
                
                role = message.get('role', 'unknown')
                content = message.get('content', '')
                
                if not content or not content.strip():
                    continue
                
                # 배치에 추가
                batch.append({
                    'message': message,
                    'role': role,
                    'content': content,
                    'file_name': file_name,
                    'message_index': idx
                })
                contents_batch.append(content)
                
                # 배치 크기에 도달하면 처리
                if len(batch) >= batch_size:
                    saved = await self._process_batch(batch, contents_batch, collection)
                    saved_count += saved
                    batch = []
                    contents_batch = []
            
            # 남은 배치 처리
            if batch:
                saved = await self._process_batch(batch, contents_batch, collection)
                saved_count += saved
            
            logger.info(f"✓ {file_name}: {saved_count}개 메시지 저장 완료")
            return saved_count
            
        except Exception as e:
            logger.error(f"Qdrant 저장 실패: {e}")
            return 0
    
    async def _process_batch(self, batch, contents_batch, collection):
        """배치 처리"""
        try:
            # 배치로 임베딩 생성
            embeddings = await self.create_embeddings_batch(contents_batch)
            
            # Point 객체 생성
            points = []
            for i, item in enumerate(batch):
                vector = embeddings[i].tolist() if hasattr(embeddings[i], 'tolist') else list(embeddings[i])
                
                payload = {
                    "role": item['role'],
                    "content": item['content'],
                    "file_name": item['file_name'],
                    "message_index": item['message_index'],
                    "timestamp": datetime.now().isoformat(),
                    "source": "kiro_chat_import"
                }
                
                point = models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload=payload
                )
                points.append(point)
            
            # 비동기로 Qdrant에 저장
            await self.async_client.upsert(collection_name=collection, points=points)
            return len(points)
            
        except Exception as e:
            logger.error(f"배치 처리 실패: {e}")
            return 0
    
    async def _ensure_collection_async(self, collection_name):
        """컬렉션 확인/생성 (비동기)"""
        try:
            await self.async_client.get_collection(collection_name)
        except Exception:
            logger.info(f"컬렉션 생성 중: {collection_name}")
            
            # 동기 클라이언트로 컬렉션 생성 (비동기 클라이언트에서 지원하지 않는 경우)
            loop = asyncio.get_event_loop()
            
            def create_collection():
                sample_embedding = self.embedding_model.encode(["test"])
                embedding_size = len(sample_embedding[0]) if isinstance(sample_embedding, list) else sample_embedding.shape[-1]
                
                self.sync_client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(size=int(embedding_size), distance=models.Distance.COSINE),
                )
            
            await loop.run_in_executor(self.executor, create_collection)
            logger.info(f"컬렉션 생성 완료: {collection_name}")
    
    async def process_chat_file(self, chat_file):
        """단일 Chat 파일 처리"""
        try:
            # Chat 파일 읽기
            chat_data = await self.read_chat_file_async(chat_file)
            if not chat_data:
                return 0
            
            # 메시지 추출
            messages = self.extract_messages(chat_data)
            if not messages:
                return 0
            
            # Qdrant에 저장
            saved = await self.save_messages_to_qdrant_async(messages, chat_file.name)
            return saved
            
        except Exception as e:
            logger.error(f"파일 처리 실패 ({chat_file}): {e}")
            return 0
    
    async def import_all_chats_async(self, concurrent_files=10):
        """모든 Chat 파일 비동기 임포트"""
        chat_files = self.find_chat_files()
        
        if not chat_files:
            logger.warning("임포트할 Chat 파일이 없습니다")
            return 0
        
        print(f"\n✓ Async Kiro Chat 파일 임포트 시작")
        print(f"{'='*70}")
        print(f"파일 수: {len(chat_files)}개, 동시 처리: {concurrent_files}개")
        
        # 파일을 청크로 나누어 처리
        total_saved = 0
        
        for i in range(0, len(chat_files), concurrent_files):
            chunk = chat_files[i:i + concurrent_files]
            
            # 청크 내 파일들을 동시에 처리
            tasks = [self.process_chat_file(chat_file) for chat_file in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 결과 집계
            chunk_saved = 0
            for j, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"파일 처리 중 예외 발생: {result}")
                else:
                    chunk_saved += result
            
            total_saved += chunk_saved
            logger.info(f"청크 {i//concurrent_files + 1} 완료: {chunk_saved}개 메시지 저장")
        
        print(f"\n{'='*70}")
        print(f"✓ 비동기 임포트 완료: 총 {total_saved}개 메시지 저장됨")
        
        return total_saved
    
    async def close(self):
        """리소스 정리"""
        await self.async_client.close()
        self.executor.shutdown(wait=True)


async def main():
    """메인 함수"""
    # CLI 인자 처리
    chat_dir = None
    if len(sys.argv) > 1:
        chat_dir = sys.argv[1]
        logger.info(f"CLI 인자로 받은 chat_dir: {chat_dir}")
    
    importer = AsyncKiroChatImporter(chat_dir=chat_dir)
    
    try:
        await importer.import_all_chats_async()
    finally:
        await importer.close()


if __name__ == "__main__":
    asyncio.run(main())

