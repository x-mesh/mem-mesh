# MCP mem-mesh 자동 프로젝트 감지 프롬프트

> **Note**: 이 문서는 레거시입니다. 통합 가이드는 `docs/rules/mem-mesh-mcp-guide.md`를 참조하세요.

## 🎯 IDE 시스템 프롬프트 (자동 프로젝트 감지)

```markdown
You have access to mem-mesh MCP for context retrieval.

## AUTOMATIC PROJECT DETECTION
The system automatically detects your project from:
1. Current directory name (e.g., "mem-mesh" → "mem-mesh-optimization")
2. Git repository name
3. Environment variable MEM_MESH_PROJECT

## SEARCH RULES
1. **Project is auto-detected** - No need to specify unless switching projects
2. Use descriptive phrases, not single words
3. Results limited to 5 most relevant items
4. Noise automatically filtered (kiro-*, test-*, tmp-* excluded)

## SEARCH PATTERN
```python
# Current directory: /Users/username/work/mem-mesh
# Auto-detected project: mem-mesh-optimization

# ✅ GOOD - Project automatically applied
search("token optimization strategy")
# Internally becomes: search("token optimization strategy", project="mem-mesh-optimization")

# ✅ GOOD - Override project when needed
search("search quality", project="mem-mesh-search-quality")

# ❌ BAD - Single word (too broad)
search("token")
```

## CONTEXT VARIABLES
- $PROJECT = auto-detected from current directory
- $DIR = current directory name
- $USER = current user

## NOISE PREVENTION
Automatically excluded:
- kiro-* projects (45+ noise projects)
- test-* projects
- tmp-* projects
- Content < 50 characters
- Duplicate content
```

## 🔧 IDE 설정 파일 (.vscode/settings.json)

```json
{
  "mem-mesh": {
    "autoDetectProject": true,
    "projectDetection": {
      "useCurrentDir": true,
      "useGitRepo": true,
      "fallbackProject": null
    },
    "searchDefaults": {
      "limit": 5,
      "minScore": 0.3,
      "aggressiveFilter": true
    },
    "noiseFilters": {
      "excludePatterns": [
        "kiro-*",
        "test-*",
        "tmp-*",
        "demo-*"
      ],
      "minContentLength": 50,
      "removeDuplicates": true
    },
    "projectMappings": {
      "mem-mesh": "mem-mesh-optimization",
      "my-app": "my-app-production",
      "api-server": "api-server-main"
    }
  }
}
```

## 📝 실제 사용 예시

### 1. 기본 사용 (프로젝트 자동 감지)

```python
# 현재 디렉토리: /Users/jinwoo/work/mem-mesh
# 자동 감지: mem-mesh-optimization

# 검색 시 자동으로 프로젝트 필터 적용
results = mcp.search("토큰 최적화")
# → 실제: search("토큰 최적화", project="mem-mesh-optimization")
```

### 2. 다른 프로젝트 검색

```python
# 다른 프로젝트 명시적 지정
results = mcp.search("검색 품질", project="mem-mesh-search-quality")
```

### 3. 환경변수로 고정

```bash
# 특정 프로젝트로 고정하고 싶을 때
export MEM_MESH_PROJECT="my-special-project"
```

## 🚀 통합 스크립트

```python
#!/usr/bin/env python3
"""MCP 검색 with 자동 프로젝트 감지"""

import os
from pathlib import Path

def get_current_project():
    """현재 프로젝트 자동 감지"""

    # 1. 환경변수 우선
    if 'MEM_MESH_PROJECT' in os.environ:
        return os.environ['MEM_MESH_PROJECT']

    # 2. 현재 디렉토리명
    current_dir = Path.cwd().name

    # 매핑 테이블
    mappings = {
        'mem-mesh': 'mem-mesh-optimization',
        'mem_mesh': 'mem-mesh-optimization',
        # 추가 매핑...
    }

    # 3. 매핑 확인
    if current_dir in mappings:
        return mappings[current_dir]

    # 4. 노이즈 디렉토리 제외
    if current_dir.startswith(('kiro', 'test', 'tmp')):
        return None

    # 5. 디렉토리명 그대로 사용
    return current_dir

def smart_search(query, **kwargs):
    """스마트 검색 (프로젝트 자동 적용)"""

    # 프로젝트 자동 감지
    if 'project' not in kwargs:
        project = get_current_project()
        if project:
            kwargs['project'] = project

    # 노이즈 필터 기본값
    kwargs.setdefault('limit', 5)
    kwargs.setdefault('min_score', 0.3)

    # MCP 검색 실행
    return mcp.search(query, **kwargs)

# 사용 예
results = smart_search("토큰 최적화")  # 프로젝트 자동 적용!
```

## 📊 효과

### Before (프로젝트 미지정)
- 검색 결과: 대부분 kiro-* 프로젝트 (노이즈)
- 정확도: 0-10%
- 토큰 낭비: 많은 무관한 결과

### After (자동 프로젝트 감지)
- 검색 결과: 현재 프로젝트 중심
- 정확도: 70-100%
- 토큰 절약: 5개로 제한 + 관련성 높음

## 💡 추가 팁

1. **디렉토리 명명 규칙**
   - 프로젝트와 동일한 이름 사용
   - 예: `mem-mesh`, `my-app`, `api-server`

2. **Git 리포지토리 활용**
   - Git repo 이름이 자동으로 프로젝트로 인식됨

3. **다중 프로젝트 작업**
   ```bash
   # 프로젝트별 터미널/탭 분리
   cd ~/work/project-a && export MEM_MESH_PROJECT=project-a
   cd ~/work/project-b && export MEM_MESH_PROJECT=project-b
   ```

4. **VS Code 워크스페이스별 설정**
   ```json
   // .vscode/settings.json
   {
     "terminal.integrated.env.osx": {
       "MEM_MESH_PROJECT": "${workspaceFolderBasename}"
     }
   }
   ```

## 🔍 디버깅

현재 감지된 프로젝트 확인:
```bash
python -c "from app.mcp_integration.auto_context import get_current_project_id; print(get_current_project_id())"
```

수동 테스트:
```bash
cd /path/to/your/project
python app/mcp_integration/auto_context.py
```