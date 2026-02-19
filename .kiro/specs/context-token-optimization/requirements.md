# 요구사항 문서 (Requirements Document)

## 소개 (Introduction)

mem-mesh 시스템의 맥락 관리 및 토큰 최적화 기능은 AI 도구 사용 시 세션 단위로 작업 맥락을 효율적으로 관리하고, 중요도 기반의 메모리 승격 시스템을 통해 토큰 사용량을 최대 95%까지 절감하면서도 검색 품질을 향상시키는 것을 목표로 합니다.

현재 시스템의 주요 문제점:
- 세션이 길어질수록 모든 대화 내역이 AI의 맥락에 포함되어 토큰 비용이 급증하고 응답 속도가 저하됨
- 사소한 질답과 중요한 기술적 결정사항이 구분 없이 저장되어 검색 결과의 순도가 낮아짐

이 기능은 세션 계층화, 지능적 핀(Pin) 시스템, 중요도 기반 메모리 승격을 통해 이러한 문제를 해결합니다.

## 용어 정의 (Glossary)

- **Session**: 사용자의 연속된 작업 단위로, 시작과 종료가 명확한 작업 맥락
- **Pin**: 세션 내에서 진행 중인 작업을 추적하는 임시 저장소 항목
- **Memory**: 영구적으로 저장되는 벡터 DB의 메모리 항목
- **Importance**: 1(사소함)부터 5(핵심 아키텍처)까지의 중요도 등급
- **Promotion**: 중요한 핀을 영구 메모리로 전환하는 프로세스
- **Context_Token**: AI 모델의 입력으로 사용되는 토큰
- **Summary**: 세션 또는 핀의 요약 정보
- **Lazy_Loading**: 필요한 시점에만 상세 데이터를 로드하는 기법
- **SearchIntentAnalyzer**: 사용자 검색 의도를 분석하는 서비스
- **UnifiedSearchService**: 통합 검색 서비스
- **PinService**: 핀 관리 서비스
- **SessionService**: 세션 관리 서비스

## 요구사항 (Requirements)

### Requirement 1: 세션 계층화 및 지연 로딩

**User Story:** AI 도구 사용자로서, 세션 시작 시 전체 대화 내역이 아닌 요약 정보만 로드되기를 원합니다. 그래야 토큰 사용량을 줄이고 응답 속도를 높일 수 있습니다.

#### Acceptance Criteria

1. WHEN session_resume 도구가 expand=false로 호출되면, THE SessionService SHALL 세션 통계와 마지막 요약만 반환하고 100 토큰 이하로 제한해야 함
2. WHEN session_resume 도구가 expand=true로 호출되면, THE SessionService SHALL 활성 핀들의 상세 내용을 포함하여 반환해야 함
3. WHEN session_resume 도구가 limit 파라미터와 함께 호출되면, THE SessionService SHALL 지정된 개수만큼의 최근 핀만 반환해야 함
4. WHEN 세션이 존재하지 않을 때 session_resume이 호출되면, THE SessionService SHALL 적절한 메시지와 함께 no_session 상태를 반환해야 함
5. WHEN session_resume이 성공적으로 실행되면, THE SessionService SHALL pins_count, open_pins, completed_pins를 포함한 세션 요약을 반환해야 함

### Requirement 2: 지능적 핀(Pin) 시스템

**User Story:** 개발자로서, 현재 진행 중인 작업을 중요도와 함께 추적하고 싶습니다. 그래야 나중에 중요한 작업만 영구 저장할 수 있습니다.

#### Acceptance Criteria

1. WHEN pin_add 도구가 호출되면, THE PinService SHALL content, project_id, importance(1-5), tags를 포함한 새 핀을 생성해야 함
2. WHEN pin_add에서 importance가 명시되지 않으면, THE PinService SHALL SearchIntentAnalyzer를 사용하여 자동으로 중요도를 추정해야 함
3. WHEN pin_add에서 importance가 1-5 범위를 벗어나면, THE PinService SHALL 에러를 반환하고 핀 생성을 거부해야 함
4. WHEN 핀이 생성되면, THE PinService SHALL 고유한 pin_id와 session_id를 반환해야 함
5. WHEN 핀이 생성되면, THE PinService SHALL 생성 시각(created_at)과 상태(status=open)를 자동으로 설정해야 함

### Requirement 3: 핀 완료 및 중요도 기반 승격 제안

**User Story:** 개발자로서, 작업을 완료할 때 중요한 작업은 영구 메모리로 승격할지 제안받고 싶습니다. 그래야 중요한 정보만 장기 저장할 수 있습니다.

#### Acceptance Criteria

1. WHEN pin_complete 도구가 호출되면, THE PinService SHALL 해당 핀의 상태를 completed로 변경하고 completed_at 시각을 기록해야 함
2. WHEN 완료된 핀의 importance가 4 이상이면, THE PinService SHALL 승격 제안(promotion_suggested=true)을 응답에 포함해야 함
3. WHEN 완료된 핀의 importance가 3 이하이면, THE PinService SHALL 승격 제안 없이 완료 확인만 반환해야 함
4. WHEN pin_complete에 존재하지 않는 pin_id가 전달되면, THE PinService SHALL 에러를 반환해야 함
5. WHEN 핀이 완료되면, THE PinService SHALL lead_time_hours를 자동으로 계산하여 저장해야 함

### Requirement 4: 메모리 승격 프로세스

**User Story:** 개발자로서, 중요한 핀을 영구 메모리로 승격하고 싶습니다. 그래야 나중에 벡터 검색으로 찾을 수 있습니다.

#### Acceptance Criteria

1. WHEN pin_promote 도구가 호출되면, THE PinService SHALL 해당 핀의 내용을 영구 메모리로 복사하고 memory_id를 반환해야 함
2. WHEN 핀이 승격되면, THE PinService SHALL 핀의 importance를 메모리의 메타데이터에 포함해야 함
3. WHEN 핀이 승격되면, THE PinService SHALL 핀의 tags를 메모리에 그대로 전달해야 함
4. WHEN 핀이 승격되면, THE PinService SHALL 핀의 project_id를 메모리에 포함해야 함
5. WHEN 이미 승격된 핀에 대해 pin_promote가 다시 호출되면, THE PinService SHALL 중복 승격을 방지하고 기존 memory_id를 반환해야 함

### Requirement 5: 세션 종료 및 요약 생성

**User Story:** AI 도구 사용자로서, 세션을 종료할 때 자동으로 요약이 생성되고 중요한 핀만 영구 저장되기를 원합니다. 그래야 다음 세션에서 효율적으로 맥락을 복원할 수 있습니다.

#### Acceptance Criteria

1. WHEN session_end 도구가 호출되면, THE SessionService SHALL 현재 세션의 모든 핀을 기반으로 요약을 생성해야 함
2. WHEN session_end에 summary 파라미터가 제공되면, THE SessionService SHALL 제공된 요약을 사용해야 함
3. WHEN session_end에 summary가 제공되지 않으면, THE SessionService SHALL 핀들의 내용을 기반으로 자동 요약을 생성해야 함
4. WHEN 세션이 종료되면, THE SessionService SHALL importance 4 이상의 완료된 핀들에 대해 자동 승격을 제안해야 함
5. WHEN 세션이 종료되면, THE SessionService SHALL 세션 통계(총 핀 수, 완료된 핀 수, 평균 lead_time)를 반환해야 함

### Requirement 6: 의도 기반 맥락 조정

**User Story:** AI 도구 사용자로서, 검색 의도에 따라 자동으로 적절한 깊이의 맥락이 로드되기를 원합니다. 그래야 디버깅 시에는 상세 정보를, 탐색 시에는 요약 정보를 얻을 수 있습니다.

#### Acceptance Criteria

1. WHEN UnifiedSearchService가 'Debug' 의도로 검색을 수행하면, THE SessionService SHALL 관련 핀과 메모리를 상세 모드(expand=true)로 로드해야 함
2. WHEN UnifiedSearchService가 'Explore' 의도로 검색을 수행하면, THE SessionService SHALL 요약 모드(expand=false)로 넓은 범위의 정보를 로드해야 함
3. WHEN UnifiedSearchService가 'Implement' 의도로 검색을 수행하면, THE SessionService SHALL 관련 핀의 중요도가 3 이상인 항목만 우선 로드해야 함
4. WHEN 검색 의도가 명확하지 않으면, THE SessionService SHALL 기본값으로 요약 모드를 사용해야 함
5. WHEN 의도 기반 맥락 조정이 실행되면, THE SessionService SHALL 로드된 맥락의 예상 토큰 수를 반환해야 함

### Requirement 7: 토큰 사용량 추적 및 최적화

**User Story:** 시스템 관리자로서, 세션별 토큰 사용량을 추적하고 최적화 효과를 측정하고 싶습니다. 그래야 시스템의 효율성을 모니터링할 수 있습니다.

#### Acceptance Criteria

1. WHEN 세션이 시작되면, THE SessionService SHALL 초기 맥락 토큰 수를 기록해야 함
2. WHEN 세션 중 맥락이 로드될 때마다, THE SessionService SHALL 누적 토큰 수를 업데이트해야 함
3. WHEN 세션이 종료되면, THE SessionService SHALL 총 토큰 사용량과 절감률을 계산하여 반환해야 함
4. WHEN 지연 로딩이 사용되면, THE SessionService SHALL 로드되지 않은 핀의 예상 토큰 수를 별도로 추적해야 함
5. WHEN 토큰 사용량이 임계값(예: 10,000 토큰)을 초과하면, THE SessionService SHALL 경고 메시지를 반환해야 함

### Requirement 8: 핀 검색 및 필터링

**User Story:** 개발자로서, 현재 세션의 핀들을 중요도, 상태, 태그로 필터링하여 검색하고 싶습니다. 그래야 특정 작업을 빠르게 찾을 수 있습니다.

#### Acceptance Criteria

1. WHEN 핀 검색이 importance 필터와 함께 요청되면, THE PinService SHALL 지정된 중요도 이상의 핀만 반환해야 함
2. WHEN 핀 검색이 status 필터와 함께 요청되면, THE PinService SHALL 지정된 상태(open/completed)의 핀만 반환해야 함
3. WHEN 핀 검색이 tags 필터와 함께 요청되면, THE PinService SHALL 지정된 태그를 포함한 핀만 반환해야 함
4. WHEN 핀 검색이 여러 필터와 함께 요청되면, THE PinService SHALL AND 조건으로 필터를 적용해야 함
5. WHEN 핀 검색 결과가 반환되면, THE PinService SHALL 결과를 created_at 기준 내림차순으로 정렬해야 함

### Requirement 9: 세션 통계 및 분석

**User Story:** 시스템 관리자로서, 프로젝트별 세션 통계를 확인하고 싶습니다. 그래야 팀의 작업 패턴과 효율성을 분석할 수 있습니다.

#### Acceptance Criteria

1. WHEN 세션 통계가 요청되면, THE SessionService SHALL 프로젝트별 총 세션 수를 반환해야 함
2. WHEN 세션 통계가 요청되면, THE SessionService SHALL 평균 세션 지속 시간을 계산하여 반환해야 함
3. WHEN 세션 통계가 요청되면, THE SessionService SHALL 세션당 평균 핀 수를 반환해야 함
4. WHEN 세션 통계가 요청되면, THE SessionService SHALL 중요도별 핀 분포를 반환해야 함
5. WHEN 세션 통계가 요청되면, THE SessionService SHALL 평균 토큰 절감률을 계산하여 반환해야 함

### Requirement 10: 데이터베이스 성능 최적화

**User Story:** 시스템 관리자로서, 세션과 핀 데이터가 효율적으로 저장되고 조회되기를 원합니다. 그래야 대규모 사용 환경에서도 빠른 응답 속도를 유지할 수 있습니다.

#### Acceptance Criteria

1. WHEN 핀 테이블이 생성되면, THE Database SHALL pin_id, session_id, project_id에 인덱스를 생성해야 함
2. WHEN 세션 테이블이 생성되면, THE Database SHALL session_id, project_id, created_at에 인덱스를 생성해야 함
3. WHEN 핀 또는 세션 조회가 실행되면, THE Database SHALL SQLite WAL 모드를 사용하여 동시성을 지원해야 함
4. WHEN 완료된 핀이 30일 이상 경과하고 승격되지 않았으면, THE Database SHALL 자동 정리 대상으로 표시해야 함
5. WHEN 데이터베이스 정리가 실행되면, THE Database SHALL 승격되지 않은 오래된 핀을 삭제하고 통계를 반환해야 함
