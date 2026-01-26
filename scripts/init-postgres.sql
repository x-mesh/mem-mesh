-- PostgreSQL 초기화 스크립트
-- pgvector 확장 및 테이블 생성

-- pgvector 확장 활성화
CREATE EXTENSION IF NOT EXISTS vector;

-- 확장 버전 확인
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

-- memories 테이블 생성
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    project_id TEXT,
    category TEXT NOT NULL DEFAULT 'task',
    source TEXT NOT NULL,
    embedding vector(384),  -- 384차원 벡터 (paraphrase-multilingual-MiniLM-L12-v2)
    tags TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_memories_project_id ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash);

-- 벡터 검색을 위한 IVFFlat 인덱스
-- 주의: 데이터가 충분히 쌓인 후에 생성하는 것이 좋음 (최소 1000개 이상)
-- CREATE INDEX IF NOT EXISTS idx_memories_embedding 
-- ON memories USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);

-- HNSW 인덱스 (더 빠른 검색, 더 많은 메모리 사용)
-- CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
-- ON memories USING hnsw (embedding vector_cosine_ops)
-- WITH (m = 16, ef_construction = 64);

-- Work Tracking System 테이블 (선택사항)
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    tech_stack TEXT,
    global_rules TEXT,
    global_context TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL DEFAULT 'default',
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'active',
    summary TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS pins (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL DEFAULT 'default',
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'open',
    tags TEXT,
    embedding vector(384),
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Work Tracking 인덱스
CREATE INDEX IF NOT EXISTS idx_sessions_project_status ON sessions(project_id, status);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_pins_session ON pins(session_id);
CREATE INDEX IF NOT EXISTS idx_pins_project_status ON pins(project_id, status);
CREATE INDEX IF NOT EXISTS idx_pins_importance ON pins(importance DESC);
CREATE INDEX IF NOT EXISTS idx_pins_user ON pins(user_id);

-- 통계 정보
SELECT 
    'PostgreSQL + pgvector 초기화 완료' as status,
    version() as pg_version,
    (SELECT extversion FROM pg_extension WHERE extname = 'vector') as pgvector_version;
