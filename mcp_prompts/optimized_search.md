# MCP mem-mesh 검색 최적화 가이드

## 🎯 노이즈 감소를 위한 검색 전략

### 1. 프로젝트 컨텍스트 자동 설정

MCP를 사용할 때 현재 작업 중인 프로젝트를 자동으로 인식하여 검색 노이즈를 줄입니다.

```python
# 프로젝트 자동 감지 예시
current_project = detect_project_from_context()  # git repo, 폴더명 등
results = mcp.search(query="토큰 최적화", project_filter=current_project)
```

### 2. 스마트 쿼리 구성

#### ❌ 피해야 할 검색 (노이즈 많음)
```python
# 단일 단어 검색
mcp.search("토큰")
mcp.search("cache")
```

#### ✅ 권장 검색 패턴 (정확도 높음)
```python
# 구체적인 구문 사용
mcp.search("토큰 최적화 전략")
mcp.search("캐시 관리 시스템")

# 프로젝트 필터와 함께
mcp.search("검색 품질", project_filter="mem-mesh-search-quality")

# 카테고리 지정
mcp.search("임베딩", category="code_snippet")
```

### 3. IDE 프롬프트 템플릿

IDE에서 mem-mesh를 사용할 때 다음 프롬프트를 추가하세요:

```markdown
## mem-mesh 검색 가이드

검색 시 다음 규칙을 따르세요:

1. **프로젝트 지정**: 현재 작업 중인 프로젝트 ID를 항상 포함
   - 예: `project:mem-mesh-optimization`

2. **구체적인 쿼리**: 단일 단어보다 구문 사용
   - ❌ "토큰"
   - ✅ "토큰 최적화 방법"

3. **카테고리 활용**:
   - `category:decision` - 의사결정 사항
   - `category:code_snippet` - 코드 예제
   - `category:task` - 작업 기록

4. **시간 범위 지정** (최근 정보 우선):
   - `recent:7d` - 최근 7일
   - `recent:today` - 오늘

5. **태그 활용**:
   - `tags:optimization` - 최적화 관련
   - `tags:korean` - 한국어 관련
```

### 4. 자동 컨텍스트 추출 스크립트

```python
def get_smart_context():
    """현재 작업 컨텍스트 자동 추출"""

    context = {
        # Git 리포지토리에서 프로젝트 추출
        'project': get_git_repo_name() or 'default',

        # 현재 파일에서 카테고리 추측
        'category': guess_category_from_file(),

        # 최근 작업 기준 시간 범위
        'recency': 'recent:7d',

        # 언어 감지
        'language': detect_language_preference()
    }

    return context

# 사용 예시
context = get_smart_context()
results = mcp.search(
    query="검색 최적화",
    project_filter=context['project'],
    category=context['category']
)
```

### 5. 노이즈 필터링 규칙

```python
# 자동 노이즈 필터링
NOISE_FILTERS = {
    # 중복 제거
    'remove_duplicates': True,

    # 최소 관련성 점수
    'min_score': 0.3,

    # 제외 프로젝트 패턴
    'exclude_projects': ['test-*', 'tmp-*', 'kiro-*'],

    # 제외 카테고리
    'exclude_categories': ['debug', 'temp'],

    # 최소 콘텐츠 길이
    'min_content_length': 50,

    # 최대 결과 수
    'max_results': 10
}
```

### 6. 프롬프트 최적화 예시

#### IDE 시스템 프롬프트 (200 tokens)
```
You have access to mem-mesh for retrieving context.

SEARCH RULES:
1. Always specify project_id when available
2. Use phrase queries, not single words
3. Prefer recent results (last 7 days)
4. Limit to 5 results per search
5. Cache search results for 5 minutes

SEARCH PATTERN:
- First search: broad query with project filter
- If insufficient: refine with category/tags
- Maximum 2 searches per topic

Example:
✅ search("token optimization strategy", project="mem-mesh-opt", limit=5)
❌ search("token")
```

### 7. 검색 품질 모니터링

```python
# 검색 품질 메트릭
def evaluate_search_quality(results):
    metrics = {
        'precision': calculate_precision(results),
        'noise_ratio': count_irrelevant(results) / len(results),
        'diversity': calculate_diversity(results),
        'recency': average_age(results)
    }

    if metrics['noise_ratio'] > 0.5:
        logger.warning("High noise ratio detected, refine query")

    return metrics
```

## 🚀 적용 방법

1. **IDE 설정 업데이트**
```bash
# .vscode/settings.json 또는 IDE 설정에 추가
{
  "mem-mesh.searchStrategy": "smart",
  "mem-mesh.defaultProject": "${workspaceFolderBasename}",
  "mem-mesh.noiseFilter": true,
  "mem-mesh.maxResults": 5
}
```

2. **MCP 클라이언트 설정**
```python
# mcp_client_config.py
MCP_CONFIG = {
    'search': {
        'auto_project': True,
        'min_query_length': 2,
        'default_limit': 5,
        'cache_ttl': 300,  # 5 minutes
        'noise_filters': NOISE_FILTERS
    }
}
```

3. **검색 래퍼 함수**
```python
def smart_search(query, **kwargs):
    """노이즈가 적은 스마트 검색"""

    # 자동 컨텍스트 추가
    if 'project_filter' not in kwargs:
        kwargs['project_filter'] = get_current_project()

    # 쿼리 확장
    if len(query.split()) == 1:
        query = expand_query(query)

    # 노이즈 필터 적용
    kwargs['min_score'] = kwargs.get('min_score', 0.3)
    kwargs['limit'] = min(kwargs.get('limit', 5), 10)

    return mcp.search(query, **kwargs)
```

## 📊 예상 개선 효과

- **노이즈 감소**: 80% 감소 (프로젝트 필터 사용 시)
- **검색 정확도**: 11.7% → 70%+ (일반 검색)
- **토큰 사용량**: 추가 30% 감소 (캐싱 + 제한)
- **응답 속도**: 2배 향상 (결과 수 제한)