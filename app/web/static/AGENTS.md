# Frontend Static Assets

> Golden Rules, 세션 관리, 보안 정책, Anti-Patterns 등 프로젝트 공통 표준은 root [AGENTS.md](../AGENTS.md) 참조.

## Module Context
`static/` holds the standalone single-page application that the FastAPI dashboard serves. `static/js/main.js` wires the SPA, components, pages, API client, router, and WebSocket/SSE services as ES modules. `static/css/main.css` defines shared styling, while subfolders (`components`, `pages`, `services`, `utils`) encapsulate UI widgets, content layouts, API helpers, and cross-cutting utilities. `static/test-api.js` plus files in `static/tests/` provide lightweight smoke checks against backend endpoints and SSE streams.

## Tech Stack & Constraints
- Pure JavaScript with native ES module imports; no bundler, transpiler, or npm pipeline runs for these files.
- `fetch`/`EventSource` wrappers in `services/api-client.js`/`services/websocket-client.js` abstract MCP/REST calls; SSE/WebSocket clients expect the MCP SSE (`/mcp/sse`) and WebSocket (`/ws`) transports to be live.
- CSS is scoped conservatively in `css/main.css`; avoid introducing preprocessors.
- Images and fonts must stay in `static/` so FastAPI can serve them via the mounted static directory.

## Implementation Patterns
- `App` class (in `main.js`) instantiates `APIClient`, `Router`, `AppState`, `ThemeManager`, `ErrorHandler`, and `ToastNotifications`, registers pages, and starts client-side routing with `pushState`.
- `services/router.js` centralizes route → page mapping and keeps navigation callbacks consistent; `services/app-state.js` tracks active project/filters.
- Components follow the `MemoryCard`, `ContextTimeline`, `NetworkGraph`, and other modules for reusable DOM rendering; each component exports a class or factory so pages can render them declaratively.
- SSE and WebSocket updates share `services/websocket-client.js` and `components/connection-status.js` to reflect live data; pages subscribe via the global `window.app`.

## Testing Strategy
- Run `node static/test-api.js` (or open it in the browser) against a live backend to verify MCP/SSE responses and API shapes.
- Open `static/test-search.html` and `tests/test_web_ui.html` in a browser to validate UI routing, search flows, and LiveUpdate indicators.
- Smoke test `static/main.js` by serving the SPA with `python -m app.web --reload` and watching devtools for module import or fetch errors.

## Local Golden Rules
**Do's:**
- Keep the SPA modular: pages assemble components/services instead of imperatively manipulating DOM.
- Use `APIClient` for all HTTP/SSE calls so headers, base URLs, and response parsing stay centralized.
- Expose status updates (toast, connection indicator) via shared utilities such as `ToastNotifications` and `ConnectionStatus`.

**Don'ts:**
- Do not introduce bundler configs or build steps—this folder is served as-is.
- Do not duplicate DOM queries across components; factor them into utility modules or shared service.
- Avoid inline styles or themes that bypass `ThemeManager` toggles; keep styling centralized in `css/main.css`.
