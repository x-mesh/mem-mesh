# Requirements Document

## Introduction

mem-mesh는 파편화된 AI 개발 도구들(Cursor, Kiro, Claude CLI 등) 간에 작업 맥락과 대화 내역을 중앙화하여 공유하는 메모리 시스템입니다. 개발자가 도구 간 전환 시 맥락 손실 없이 연속적인 개발 경험을 제공하며, 로컬 SQLite + sqlite-vec 기반으로 비용 없이 운영됩니다.

## Glossary

- **Memory_Server**: FastAPI 기반 중앙 메모리 서버로, MCP 프로토콜을 통해 클라이언트와 통신
- **Memory**: 저장되는 개별 맥락 단위 (대화, 작업 로그, 결정, 코드 스니펫 등)
- **Embedding_Service**: 텍스트를 벡터로 변환하는 서비스 (sentence-transformers MiniLM-L6-v2 사용)
- **Search_Service**: 하이브리드 검색을 수행하는 서비스 (SQL 필터링 + 벡터 유사도)
- **Context_Service**: 특정 메모리와 관련된 맥락을 조회하는 서비스
- **MCP_Handler**: Model Context Protocol 요청을 처리하는 핸들러
- **Vector_Index**: sqlite-vec 기반 벡터 인덱스
- **Project_ID**: 메모리를 프로젝트별로 분류하는 식별자
- **Category**: 메모리 유형 (task, bug, idea, decision, incident, code_snippet)
- **Similarity_Score**: 코사인 유사도 기반 검색 점수 (0.0 ~ 1.0)
- **Recency_Weight**: 최신성 가중치 (0.0 ~ 1.0)

## Requirements

### Requirement 1: 메모리 저장 (mem-mesh.add)

**User Story:** As a developer, I want to save important context, code changes, and decisions to long-term memory, so that I can recall them later from any AI tool.

#### Acceptance Criteria

1. WHEN a user provides content to save, THE Memory_Server SHALL generate an embedding vector using the Embedding_Service
2. WHEN content is provided without a project_id, THE Memory_Server SHALL store the memory as a global memory accessible across all projects
3. WHEN content is provided with a project_id, THE Memory_Server SHALL associate the memory with that specific project
4. WHEN content length is less than 10 characters, THE Memory_Server SHALL reject the request with a 400 error
5. WHEN content length exceeds 10,000 characters, THE Memory_Server SHALL reject the request with a 400 error
6. WHEN a memory is successfully saved, THE Memory_Server SHALL return the memory ID, status, and created_at timestamp
7. WHEN the same content with the same project_id is submitted twice, THE Memory_Server SHALL detect the duplicate via content_hash and return the existing memory ID
8. IF embedding generation fails, THEN THE Memory_Server SHALL retry up to 3 times before returning a 500 error
9. IF database write fails, THEN THE Memory_Server SHALL rollback the transaction and return a 500 error
10. WHEN a memory is saved, THE Memory_Server SHALL persist it to SQLite immediately with ACID guarantees

### Requirement 2: 메모리 검색 (mem-mesh.search)

**User Story:** As a developer, I want to search for related memories based on a query, so that I can quickly find past work logs, solutions, and decisions relevant to my current task.

#### Acceptance Criteria

1. WHEN a user provides a search query, THE Search_Service SHALL generate an embedding vector for the query
2. WHEN a query is provided without project_id, THE Search_Service SHALL search across all projects
3. WHEN a query is provided with project_id, THE Search_Service SHALL filter results to that specific project
4. WHEN a category filter is provided, THE Search_Service SHALL only return memories matching that category
5. WHEN searching, THE Search_Service SHALL return memories with similarity_score above 0.5
6. WHEN recency_weight is provided (0.0-1.0), THE Search_Service SHALL apply the formula: score_final = (1 - α) * similarity + α * recency_score
7. WHEN limit is not specified, THE Search_Service SHALL return a maximum of 5 results
8. WHEN limit is specified, THE Search_Service SHALL return up to that number of results (max 20)
9. WHEN no matching memories are found, THE Search_Service SHALL return an empty array (not an error)
10. WHEN results are returned, THE Search_Service SHALL include id, content, similarity_score, created_at, project_id, category, and source for each memory
11. THE Search_Service SHALL complete searches within 200ms for up to 10,000 memories

### Requirement 3: 맥락 조회 (mem-mesh.context)

**User Story:** As a developer, I want to get context around a specific memory including related work and timeline, so that I can understand the full picture of past decisions and actions.

#### Acceptance Criteria

1. WHEN a user provides a memory_id, THE Context_Service SHALL load the primary memory
2. WHEN the primary memory is loaded, THE Context_Service SHALL search for similar memories using vector similarity
3. WHEN similar memories are found, THE Context_Service SHALL classify relationships as "before", "after", or "similar" based on created_at timestamps
4. WHEN depth is specified (1-5), THE Context_Service SHALL expand the search to include memories related to the related memories
5. WHEN depth is not specified, THE Context_Service SHALL use a default depth of 2
6. WHEN project_id is provided, THE Context_Service SHALL limit context search to that project
7. WHEN context is retrieved, THE Context_Service SHALL return primary_memory, related_memories array, and timeline array
8. IF the memory_id does not exist, THEN THE Context_Service SHALL return a 404 error
9. THE Context_Service SHALL complete context retrieval within 300ms

### Requirement 4: 메모리 삭제 (mem-mesh.delete)

**User Story:** As a developer, I want to delete outdated or incorrect memories, so that my memory store remains accurate and relevant.

#### Acceptance Criteria

1. WHEN a user provides a memory_id to delete, THE Memory_Server SHALL verify the memory exists
2. WHEN the memory exists, THE Memory_Server SHALL remove it from both SQLite and the vector index
3. WHEN deletion is successful, THE Memory_Server SHALL return the deleted memory ID and status "deleted"
4. IF the memory_id does not exist, THEN THE Memory_Server SHALL return a 404 error
5. WHEN a memory is deleted, THE Memory_Server SHALL clean up any related_memory_ids references in other memories

### Requirement 5: 메모리 업데이트 (mem-mesh.update)

**User Story:** As a developer, I want to update existing memories with new information, so that I can keep my memory store current without creating duplicates.

#### Acceptance Criteria

1. WHEN a user provides a memory_id and new content, THE Memory_Server SHALL regenerate the embedding vector
2. WHEN only category or tags are updated, THE Memory_Server SHALL NOT regenerate the embedding
3. WHEN an update is successful, THE Memory_Server SHALL update the updated_at timestamp
4. WHEN an update is successful, THE Memory_Server SHALL return the memory ID and status "updated"
5. IF the memory_id does not exist, THEN THE Memory_Server SHALL return a 404 error

### Requirement 6: 서버 설정 및 초기화

**User Story:** As a developer, I want to configure the memory server via environment variables, so that I can customize behavior without code changes.

#### Acceptance Criteria

1. WHEN the server starts, THE Memory_Server SHALL load configuration from .env file
2. WHEN DATABASE_PATH is specified, THE Memory_Server SHALL use that path for the SQLite database
3. WHEN DATABASE_PATH is not specified, THE Memory_Server SHALL use "./mem_mesh.db" as default
4. WHEN EMBEDDING_MODEL is specified, THE Memory_Server SHALL load that sentence-transformers model
5. WHEN EMBEDDING_MODEL is not specified, THE Memory_Server SHALL use "all-MiniLM-L6-v2" as default
6. WHEN SEARCH_THRESHOLD is specified (0.0-1.0), THE Memory_Server SHALL use that as the minimum similarity score
7. WHEN SEARCH_THRESHOLD is not specified, THE Memory_Server SHALL use 0.5 as default
8. WHEN LOG_LEVEL is specified, THE Memory_Server SHALL configure logging accordingly
9. WHEN the server starts, THE Memory_Server SHALL create the database and tables if they don't exist
10. WHEN the server starts, THE Memory_Server SHALL initialize the sqlite-vec vector index
11. WHEN the embedding model is loaded, THE Memory_Server SHALL complete loading within 5 seconds

### Requirement 7: MCP 프로토콜 지원

**User Story:** As a developer, I want to use mem-mesh through the MCP protocol, so that I can integrate it with Cursor, Kiro, Claude Desktop, and other MCP-compatible tools.

#### Acceptance Criteria

1. THE MCP_Handler SHALL expose mem-mesh.add tool with the specified input schema
2. THE MCP_Handler SHALL expose mem-mesh.search tool with the specified input schema
3. THE MCP_Handler SHALL expose mem-mesh.context tool with the specified input schema
4. THE MCP_Handler SHALL expose mem-mesh.delete tool with the specified input schema
5. THE MCP_Handler SHALL expose mem-mesh.update tool with the specified input schema
6. WHEN an MCP request is received, THE MCP_Handler SHALL validate the input against the tool's schema
7. IF input validation fails, THEN THE MCP_Handler SHALL return a descriptive error message
8. THE MCP_Handler SHALL support stdio transport for local tool integration
9. WHEN the server runs, THE Memory_Server SHALL be compatible with Cursor IDE
10. WHEN the server runs, THE Memory_Server SHALL be compatible with Claude Desktop
11. WHEN the server runs, THE Memory_Server SHALL be compatible with CLI/uv tools

### Requirement 8: 데이터 모델 및 저장소

**User Story:** As a developer, I want memories stored with comprehensive metadata, so that I can filter, sort, and organize them effectively.

#### Acceptance Criteria

1. THE Memory model SHALL include id (UUID), content (TEXT), content_hash (TEXT), project_id (TEXT), category (TEXT), source (TEXT), embedding (BLOB), tags (JSON), created_at (DATETIME), updated_at (DATETIME)
2. WHEN a memory is created, THE Memory_Server SHALL generate a UUID for the id field
3. WHEN a memory is created, THE Memory_Server SHALL compute SHA256 hash for content_hash
4. THE Vector_Index SHALL store embeddings with 384 dimensions (MiniLM-L6-v2 output)
5. THE Memory_Server SHALL create indexes on project_id, created_at, and category columns
6. THE Memory_Server SHALL use sqlite-vec for vector similarity search operations
7. FOR ALL valid Memory objects, serializing then deserializing SHALL produce an equivalent object

### Requirement 9: 에러 처리 및 로깅

**User Story:** As a developer, I want clear error messages and comprehensive logging, so that I can troubleshoot issues quickly.

#### Acceptance Criteria

1. WHEN an error occurs, THE Memory_Server SHALL return a structured error response with error code and message
2. WHEN a request is processed, THE Memory_Server SHALL log the request method, path, and duration
3. WHEN an error occurs, THE Memory_Server SHALL log the error with stack trace at ERROR level
4. WHEN embedding generation takes longer than 100ms, THE Memory_Server SHALL log a warning
5. WHEN search takes longer than 200ms, THE Memory_Server SHALL log a warning
6. THE Memory_Server SHALL use structured JSON logging format

### Requirement 10: 메모리 통계 조회 (mem-mesh.stats)

**User Story:** As a developer, I want to view statistics about my stored memories, so that I can understand my memory usage patterns and manage storage effectively.

#### Acceptance Criteria

1. WHEN a user requests overall statistics, THE Memory_Server SHALL return total memory count across all projects
2. WHEN a user requests statistics by project, THE Memory_Server SHALL return memory counts grouped by project_id
3. WHEN a user requests statistics by category, THE Memory_Server SHALL return memory counts grouped by category
4. WHEN a user requests statistics by source, THE Memory_Server SHALL return memory counts grouped by source
5. WHEN a user requests statistics with project_id filter, THE Memory_Server SHALL return counts only for that project
6. WHEN a user requests statistics with date range, THE Memory_Server SHALL return counts for memories created within that range
7. THE Memory_Server SHALL return statistics including total_memories, unique_projects, categories_breakdown, sources_breakdown, and date_range_info
8. THE Memory_Server SHALL complete statistics queries within 100ms for up to 100K memories
9. WHEN no memories exist for the requested filters, THE Memory_Server SHALL return zero counts (not an error)
10. THE Memory_Server SHALL support statistics via both REST API (/memories/stats) and MCP protocol (mem-mesh.stats)

### Requirement 11: 성능 요구사항

**User Story:** As a developer, I want fast response times, so that mem-mesh doesn't slow down my workflow.

#### Acceptance Criteria

1. THE Memory_Server SHALL complete memory saves within 100ms (local embedding)
2. THE Memory_Server SHALL complete memory searches within 200ms (up to 10K memories)
3. THE Memory_Server SHALL complete context retrieval within 300ms
4. THE Embedding_Service SHALL generate embeddings within 50ms per text
5. THE Memory_Server SHALL handle 10+ concurrent client connections
6. THE Memory_Server SHALL support up to 1M+ memories with acceptable performance degradation
