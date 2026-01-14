# Requirements Document

## Introduction

Work Tracking System은 mem-mesh에 세션 기반 작업 추적 기능을 추가합니다. Steve Yegge의 "Beads(구슬)" 컨셉과 work-memory-mcp의 세션 추적을 차용하여, 단기 작업(Pins)과 장기 지식(Memories)을 분리 관리합니다.

**핵심 목표:**
- 프로젝트 > 세션 > Pin의 계층 구조
- "어제 하던 거 이어서" 컨텍스트 로드
- 토큰 효율적인 세션 관리
- AI 자동 중요도 판단

## Glossary

- **Project**: 장기 프로젝트 단위. 기술 스택, 전역 컨텍스트 저장
- **Session**: 작업 세션. 프로젝트 이름 기반으로 자동 생성/관리
- **Pin**: 단기 작업 항목 (Beads 컨셉). 완료 후 삭제 또는 Memory로 승격
- **Memory**: 장기 지식 저장소 (기존 memories 테이블)
- **Importance**: 중요도 점수 (1-5). AI가 자동 판단
- **Lead_Time**: Pin 생성부터 완료까지 소요 시간
- **User**: 사용자 식별자. 시스템 사용자명 또는 "default"

## Requirements

### Requirement 1: 프로젝트 관리

**User Story:** As a developer, I want to manage project metadata, so that I can store global context and tech stack information per project.

#### Acceptance Criteria

1. WHEN a new project_id is encountered, THE System SHALL auto-create a project record with default values
2. THE Project SHALL store name, description, tech_stack (JSON array), and global_context fields
3. WHEN updating project metadata, THE System SHALL validate and persist changes immediately
4. THE System SHALL provide API to list all projects with memory counts

### Requirement 2: 세션 관리

**User Story:** As a developer, I want session-based tracking, so that I can resume work with full context from previous sessions.

#### Acceptance Criteria

1. WHEN a pin is created for a project, THE System SHALL auto-create or reuse an active session for that project
2. THE Session SHALL track started_at, ended_at, status (active/paused/completed), and summary
3. WHEN no activity for 4 hours, THE System SHALL auto-pause the session
4. WHEN user requests "resume last session", THE System SHALL load all pins and context from the most recent session
5. THE System SHALL generate a summary when session ends (AI-generated)
6. WHEN loading session context, THE System SHALL minimize token usage by returning compressed summaries

### Requirement 3: Pin 생성 및 관리

**User Story:** As a developer, I want to create and manage pins (short-term tasks), so that I can track work items within a session.

#### Acceptance Criteria

1. WHEN creating a pin, THE System SHALL assign it to the current active session
2. THE Pin SHALL contain content, importance (1-5), status (open/in_progress/completed), and tags
3. WHEN creating a pin, THE AI SHALL auto-determine importance score (1-5) based on content
4. THE System SHALL support pin status transitions: open → in_progress → completed
5. WHEN a pin is marked completed, THE System SHALL record completed_at timestamp
6. THE System SHALL calculate lead_time as (completed_at - created_at) for completed pins

### Requirement 4: Pin 생명주기 및 승격

**User Story:** As a developer, I want completed pins to be cleaned up or promoted to memories, so that I maintain a clean workspace while preserving important knowledge.

#### Acceptance Criteria

1. WHEN a pin is completed with importance >= 4, THE System SHALL prompt for promotion to Memory
2. WHEN promoting a pin to Memory, THE System SHALL copy content, tags, and create embedding
3. WHEN a pin is completed with importance < 4, THE System SHALL delete it after 7 days
4. THE System SHALL provide manual promotion option regardless of importance score
5. WHEN deleting a pin, THE System SHALL update session statistics

### Requirement 5: 컨텍스트 로드 (토큰 효율)

**User Story:** As a developer, I want to load session context efficiently, so that I can resume work without wasting tokens.

#### Acceptance Criteria

1. WHEN loading context, THE System SHALL return session summary (compressed) instead of full pin contents
2. THE System SHALL provide "expand" option to load full pin details on demand
3. WHEN loading context, THE System SHALL prioritize pins by importance score (high first)
4. THE System SHALL limit initial context load to top 10 pins by importance
5. WHEN session has > 20 pins, THE System SHALL auto-generate a condensed summary

### Requirement 6: 통계 및 Lead Time

**User Story:** As a developer, I want to see work statistics including lead time, so that I can track productivity.

#### Acceptance Criteria

1. THE System SHALL calculate average_lead_time for completed pins per project
2. THE System SHALL provide daily/weekly pin completion counts
3. THE Dashboard SHALL display Avg Lead Time metric from actual pin data
4. THE System SHALL track pins by status (open, in_progress, completed) per project

### Requirement 7: MCP API 확장

**User Story:** As an AI agent, I want MCP tools for pin and session management, so that I can automate work tracking.

#### Acceptance Criteria

1. THE System SHALL provide `pin_add` tool to create new pins
2. THE System SHALL provide `pin_complete` tool to mark pins as completed
3. THE System SHALL provide `pin_promote` tool to promote pins to memories
4. THE System SHALL provide `session_resume` tool to load last session context
5. THE System SHALL provide `session_end` tool to close current session with summary
6. WHEN using pin tools, THE System SHALL auto-manage session lifecycle

### Requirement 8: 사용자 식별

**User Story:** As a developer, I want user identification on pins and sessions, so that I can track work by user in multi-user environments.

#### Acceptance Criteria

1. THE System SHALL store user_id field on sessions and pins tables
2. WHEN user_id is not provided, THE System SHALL default to "default"
3. THE System SHALL attempt to auto-detect system username (via `whoami` or environment variable)
4. WHEN filtering by user, THE System SHALL return only that user's sessions and pins
5. THE System SHALL support USER environment variable override for user identification
