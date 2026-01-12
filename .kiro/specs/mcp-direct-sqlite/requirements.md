# Requirements Document

## Introduction

이 문서는 mem-mesh 시스템의 아키텍처 개선을 위한 요구사항을 정의합니다. 현재 MCP 서버와 FastAPI 대시보드가 별도로 운영되고 있으나, MCP가 직접 SQLite에 쓰는 기능을 추가하여 대시보드 없이도 독립적으로 동작할 수 있도록 합니다. 또한 SQLite WAL 모드를 활용하여 동시 접근 시 안정성을 높이고, Docker 및 Makefile을 통한 배포 편의성을 제공합니다.

기존 `src` 디렉토리 구조를 `app` 디렉토리로 재구성하여 더 명확한 모듈 분리를 제공합니다.

## Glossary

- **MCP_Server**: Model Context Protocol을 구현한 stdio 기반 서버로, AI 에이전트와 통신하여 메모리 저장/검색 기능을 제공 (기존 구현)
- **FastMCP_Server**: FastMCP 라이브러리를 사용하여 구현한 MCP 서버로, 데코레이터 기반의 간결한 도구 정의 방식을 사용
- **FastAPI_Dashboard**: 웹 UI와 REST API를 제공하는 FastAPI 기반 서버
- **Storage_Mode**: MCP 서버의 데이터 저장 방식을 결정하는 설정 (direct: SQLite 직접 접근, api: FastAPI 서버 경유)
- **WAL_Mode**: SQLite의 Write-Ahead Logging 모드로, 동시 읽기/쓰기 성능을 향상시키는 저널링 방식
- **Docker_Container**: 애플리케이션을 격리된 환경에서 실행하기 위한 컨테이너 이미지
- **App_Directory**: 새로운 애플리케이션 디렉토리 구조 (`app/`)로, MCP와 Dashboard를 명확히 분리

## Requirements

### Requirement 1: MCP 스토리지 모드 설정

**User Story:** As a 시스템 관리자, I want MCP 서버의 스토리지 모드를 설정할 수 있게, so that 환경에 따라 직접 SQLite 접근 또는 API 경유 방식을 선택할 수 있다.

#### Acceptance Criteria

1. WHEN MCP_Server가 시작될 때, THE MCP_Server SHALL 환경변수 또는 커맨드라인 인자로 storage_mode를 설정받을 수 있어야 한다
2. WHEN storage_mode가 "direct"로 설정되면, THE MCP_Server SHALL SQLite 데이터베이스에 직접 연결하여 데이터를 읽고 쓴다
3. WHEN storage_mode가 "api"로 설정되면, THE MCP_Server SHALL FastAPI_Dashboard의 REST API를 통해 데이터를 읽고 쓴다
4. WHEN storage_mode가 지정되지 않으면, THE MCP_Server SHALL 기본값으로 "direct" 모드를 사용한다
5. WHEN 잘못된 storage_mode 값이 제공되면, THE MCP_Server SHALL 명확한 에러 메시지와 함께 시작을 거부한다

### Requirement 2: Direct 모드 SQLite 접근

**User Story:** As a 개발자, I want MCP 서버가 FastAPI 없이 직접 SQLite에 접근할 수 있게, so that 대시보드 없이도 메모리 기능을 사용할 수 있다.

#### Acceptance Criteria

1. WHEN storage_mode가 "direct"이고 mem-mesh.add가 호출되면, THE MCP_Server SHALL SQLite 데이터베이스에 직접 메모리를 저장한다
2. WHEN storage_mode가 "direct"이고 mem-mesh.search가 호출되면, THE MCP_Server SHALL SQLite 데이터베이스에서 직접 벡터 검색을 수행한다
3. WHEN storage_mode가 "direct"이고 mem-mesh.update가 호출되면, THE MCP_Server SHALL SQLite 데이터베이스에서 직접 메모리를 업데이트한다
4. WHEN storage_mode가 "direct"이고 mem-mesh.delete가 호출되면, THE MCP_Server SHALL SQLite 데이터베이스에서 직접 메모리를 삭제한다
5. WHEN storage_mode가 "direct"이고 mem-mesh.context가 호출되면, THE MCP_Server SHALL SQLite 데이터베이스에서 직접 컨텍스트를 조회한다
6. WHEN storage_mode가 "direct"이고 mem-mesh.stats가 호출되면, THE MCP_Server SHALL SQLite 데이터베이스에서 직접 통계를 조회한다

### Requirement 3: API 모드 HTTP 클라이언트

**User Story:** As a 개발자, I want MCP 서버가 FastAPI 서버를 통해 데이터에 접근할 수 있게, so that 기존 대시보드와 함께 사용할 수 있다.

#### Acceptance Criteria

1. WHEN storage_mode가 "api"이면, THE MCP_Server SHALL FastAPI_Dashboard의 REST API 엔드포인트를 호출하여 데이터를 처리한다
2. WHEN API 호출이 실패하면, THE MCP_Server SHALL 적절한 에러 메시지를 반환하고 재시도 로직을 수행한다
3. WHEN API 서버 URL이 설정되지 않으면, THE MCP_Server SHALL 기본값으로 "http://localhost:8000"을 사용한다

### Requirement 4: SQLite WAL 모드 동시성 지원

**User Story:** As a 시스템 관리자, I want MCP와 대시보드가 동시에 SQLite에 접근해도 안정적으로 동작하게, so that 데이터 손실이나 충돌 없이 사용할 수 있다.

#### Acceptance Criteria

1. THE Database SHALL SQLite WAL 모드를 활성화하여 동시 읽기/쓰기를 지원한다
2. WHEN 여러 프로세스가 동시에 데이터베이스에 접근하면, THE Database SHALL WAL 모드를 통해 읽기 작업이 쓰기 작업을 차단하지 않도록 한다
3. WHEN 쓰기 충돌이 발생하면, THE Database SHALL SQLITE_BUSY 에러를 적절히 처리하고 재시도한다
4. THE Database SHALL busy_timeout을 설정하여 잠금 대기 시간을 관리한다

### Requirement 5: Docker 컨테이너화

**User Story:** As a DevOps 엔지니어, I want FastAPI와 MCP 서버를 Docker로 실행할 수 있게, so that 일관된 환경에서 배포할 수 있다.

#### Acceptance Criteria

1. THE Docker_Container SHALL FastAPI_Dashboard를 실행하는 Dockerfile을 제공한다
2. THE Docker_Container SHALL MCP_Server를 실행하는 Dockerfile을 제공한다
3. WHEN docker-compose를 사용하면, THE Docker_Container SHALL FastAPI와 MCP 서버를 함께 실행할 수 있다
4. THE Docker_Container SHALL 데이터베이스 파일을 볼륨으로 마운트하여 데이터 영속성을 보장한다
5. THE Docker_Container SHALL 환경변수를 통해 설정을 주입받을 수 있다

### Requirement 6: Makefile 빌드 자동화

**User Story:** As a 개발자, I want Makefile을 통해 빌드/실행/테스트를 간편하게 수행할 수 있게, so that 개발 워크플로우가 단순해진다.

#### Acceptance Criteria

1. THE Makefile SHALL `make install` 명령으로 의존성을 설치할 수 있다
2. THE Makefile SHALL `make run-api` 명령으로 FastAPI 서버를 실행할 수 있다
3. THE Makefile SHALL `make run-mcp` 명령으로 MCP 서버를 실행할 수 있다
4. THE Makefile SHALL `make test` 명령으로 테스트를 실행할 수 있다
5. THE Makefile SHALL `make docker-build` 명령으로 Docker 이미지를 빌드할 수 있다
6. THE Makefile SHALL `make docker-up` 명령으로 Docker Compose를 실행할 수 있다
7. THE Makefile SHALL `make clean` 명령으로 빌드 아티팩트를 정리할 수 있다

### Requirement 7: 설정 통합 관리

**User Story:** As a 시스템 관리자, I want 모든 설정을 환경변수와 설정 파일로 관리할 수 있게, so that 환경별 설정을 쉽게 변경할 수 있다.

#### Acceptance Criteria

1. THE Settings SHALL storage_mode 설정을 환경변수 MEM_MESH_STORAGE_MODE로 받을 수 있다
2. THE Settings SHALL api_base_url 설정을 환경변수 MEM_MESH_API_BASE_URL로 받을 수 있다
3. THE Settings SHALL busy_timeout 설정을 환경변수 MEM_MESH_BUSY_TIMEOUT으로 받을 수 있다
4. WHEN .env 파일이 존재하면, THE Settings SHALL 해당 파일에서 설정을 로드한다
5. THE Settings SHALL 커맨드라인 인자가 환경변수보다 우선순위를 갖도록 한다

### Requirement 8: FastMCP 기반 MCP 서버

**User Story:** As a 개발자, I want FastMCP 라이브러리를 사용한 MCP 서버 구현을 사용할 수 있게, so that 더 간결하고 유지보수하기 쉬운 코드로 MCP 기능을 제공받을 수 있다.

#### Acceptance Criteria

1. THE FastMCP_Server SHALL FastMCP 라이브러리를 사용하여 MCP 프로토콜을 구현한다
2. THE FastMCP_Server SHALL 기존 MCP_Server와 동일한 6개 도구(add, search, context, update, delete, stats)를 제공한다
3. THE FastMCP_Server SHALL 기존 MCP_Server의 코드를 수정하지 않고 별도 모듈로 구현한다
4. WHEN FastMCP_Server가 시작되면, THE FastMCP_Server SHALL storage_mode 설정에 따라 direct 또는 api 모드로 동작한다
5. THE FastMCP_Server SHALL `python -m app.mcp` 명령으로 실행할 수 있다
6. THE FastMCP_Server SHALL FastMCP의 데코레이터 기반 도구 정의 방식을 사용한다
7. THE FastMCP_Server SHALL 기존 서비스 레이어(MemoryService, SearchService 등)를 재사용한다

### Requirement 9: 디렉토리 구조 재구성

**User Story:** As a 개발자, I want 애플리케이션 디렉토리 구조가 명확하게 분리되어 있게, so that MCP와 Dashboard를 독립적으로 실행하고 관리할 수 있다.

#### Acceptance Criteria

1. THE App_Directory SHALL 기존 `src/` 디렉토리의 코드를 `app/` 디렉토리로 재구성한다
2. THE App_Directory SHALL `app/mcp/` 하위에 FastMCP 기반 MCP 서버를 구현한다
3. THE App_Directory SHALL `app/dashboard/` 하위에 FastAPI 대시보드를 구현한다
4. THE App_Directory SHALL `app/core/` 하위에 공통 모듈(database, embeddings, services, schemas)을 배치한다
5. THE MCP_Server SHALL `python -m app.mcp` 명령으로 실행할 수 있다
6. THE FastAPI_Dashboard SHALL `python -m app.dashboard` 명령으로 실행할 수 있다
7. THE App_Directory SHALL 기존 `src/` 디렉토리는 유지하여 하위 호환성을 보장한다
