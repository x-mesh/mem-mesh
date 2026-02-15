# mem-mesh MCP Integration Guide

> 전체 규칙: `docs/rules/all-tools-full.md`  
> IDE 프롬프트: `docs/rules/mem-mesh-ide-prompt.md`  
> 5분 시작: `docs/rules/modules/quick-start.md`

---

## Quick Reference

### Project Detection
- 디렉토리명 → project_id: `/path/to/my-app` → `project_id="my-app"`

### Core Tools
| Tool | Purpose |
|------|---------|
| `search` | Find memories |
| `add` | Save memory |
| `session_resume` | Load session (expand=false) |
| `pin_add` / `pin_complete` | Track task |
| `batch_operations` | Batch add/search (30-50% token save) |
| `link` / `get_links` | Memory relations |

### Categories
`task` | `bug` | `idea` | `decision` | `incident` | `code_snippet` | `git-history`

### Search
- 구문 사용: ✅ "token optimization" ❌ "token"
- project_id 항상 지정

### Web UI
- Rules Manager: `/dashboard/rules`
- Memory Dashboard: `/dashboard`
