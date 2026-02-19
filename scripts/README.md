# scripts/ — 마이그레이션 및 유틸리티 스크립트

모든 스크립트는 `app.core.config.Settings`를 사용하므로 `MEM_MESH_*` 환경변수를 따릅니다.

## 마이그레이션 (Migration)

| 스크립트 | 설명 | 사용법 |
|----------|------|--------|
| `migrate_embeddings.py` | 임베딩 모델 변경 마이그레이션 | `--check-only` → `--dry-run` → 실행 |
| `migrate_context_token_optimization.py` | 컨텍스트/토큰 최적화 스키마 마이그레이션 | `python scripts/migrate_context_token_optimization.py` |
| `migrate_memory_relations.py` | 메모리 관계 테이블 마이그레이션 | `python scripts/migrate_memory_relations.py` |
| `migrate_monitoring_tables.py` | 모니터링 테이블 마이그레이션 | `python scripts/migrate_monitoring_tables.py` |
| `migrate_to_postgres.py` | PostgreSQL 마이그레이션 (실험적) | 사전 백업 필수 |
| `migrate_to_qdrant.py` | Qdrant 마이그레이션 (실험적) | 사전 백업 필수 |
| `upgrade_to_multilingual.py` | 다국어 임베딩 모델 업그레이드 | `--check-only` 지원 |
| `switch_embedding_model.py` | 임베딩 모델 전환 | `--check-only` 지원 |
| `setup_fts.py` | FTS5 전문 검색 인덱스 설정 | `python scripts/setup_fts.py` |
| `regenerate_embeddings.py` | 임베딩 전체 재생성 | 주의: 시간 소요 큼 |

## 검증 (Verification)

| 스크립트 | 설명 |
|----------|------|
| `verify_db_consistency.py` | DB 무결성 검사 |
| `verify_embeddings.py` | 임베딩 메타데이터 정합성 검증 |
| `verify_search_features.py` | 검색 기능 검증 |

## 벤치마크 및 분석 (Benchmark / Analysis)

| 스크립트 | 설명 |
|----------|------|
| `benchmark_vector_dbs.py` | 벡터 DB 성능 벤치마크 |
| `benchmark_embedding_models.py` | 임베딩 모델 비교 벤치마크 |
| `evaluate_search_quality.py` | 검색 품질 평가 |
| `ab_test_embeddings.py` | 임베딩 A/B 테스트 |
| `analyze_embedding_differences.py` | 임베딩 차이 분석 |
| `analyze_conversations.py` | 대화 데이터 분석 |
| `compare_before_after.py` | 변경 전후 비교 |
| `compare_after.py` | 변경 후 비교 |
| `final_comparison.py` | 최종 비교 |
| `final_comparison_fixed.py` | 최종 비교 (수정) |

## 데이터 가져오기 (Import / Sync)

| 스크립트 | 설명 |
|----------|------|
| `import_kiro_chat.py` | Kiro 대화 데이터 가져오기 |
| `import_kiro_chat-v2.py` | Kiro 대화 가져오기 v2 |
| `import_kiro_chat_memmesh.py` | Kiro → mem-mesh 전용 가져오기 |
| `sync_memories.py` | 메모리 동기화 |
| `sync_memories_from_macmini.py` | Mac mini에서 메모리 동기화 |
| `sync_to_remote_mcp.py` | 원격 MCP 서버 동기화 |
| `consolidate_projects.py` | 프로젝트 통합 |

## 데이터 저장 (Save to Memory)

| 스크립트 | 설명 |
|----------|------|
| `save_qa_pair.py` | Q&A 쌍 저장 |
| `save_docker_memory.py` | Docker 관련 메모리 저장 |
| `save_optimization_to_memory.py` | 최적화 내용 메모리 저장 |
| `save_search_issue_to_memory.py` | 검색 이슈 메모리 저장 |
| `save_search_quality_to_memory.py` | 검색 품질 메모리 저장 |
| `save_session_to_memesh.py` | 세션 메모리 저장 |
| `save_thread_summary_korean.py` | 스레드 요약 저장 (한국어) |
| `save_work_tracking_test_to_memory.py` | Work tracking 테스트 저장 |
| `save_work_tracking_via_mcp.py` | MCP 통한 work tracking 저장 |

## 디버그 및 테스트 (Debug / Test)

| 스크립트 | 설명 |
|----------|------|
| `debug_mcp_sse_search.py` | MCP SSE 검색 디버깅 |
| `debug_summarization.py` | 요약 기능 디버깅 |
| `interactive_search.py` | 대화형 검색 테스트 |
| `search_qa_pairs.py` | Q&A 쌍 검색 |
| `mcp_client_script.py` | MCP 클라이언트 테스트 |
| `test_duplicate_logging.py` | 중복 로깅 테스트 |
| `test_qwen_cli.py` | Qwen CLI 테스트 |
| `test_summary_only.py` | 요약 전용 테스트 |
| `simple_summarization_test.py` | 간단 요약 테스트 |
| `cleanup_noise_data.py` | 노이즈 데이터 정리 |

## 기타 (Utility)

| 스크립트 | 설명 |
|----------|------|
| `generate_rules_bundle.py` | 규칙 번들 생성 |
| `run_mcp_server.py` | MCP 서버 실행 |
| `init-postgres.sql` | PostgreSQL 초기화 SQL |
