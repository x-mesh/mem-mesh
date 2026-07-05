# Product

## Register
product

## Users
Developers and operators who run mem-mesh as a local or team memory server for AI coding tools and MCP clients.

## Product Purpose
mem-mesh is a persistent memory layer for AI coding tools, reached over MCP with hooks and an operational dashboard. Its value does not rest on the claim that searching past sessions makes a model write better code — mem-mesh treats that as a measurable hypothesis, not a premise (see *Empirical Stance*). It rests on three capabilities that source control and code review do not provide.

## Defensible Core
Three things git, pull requests, and well-kept docs do not capture. These are the reasons to run mem-mesh, and each stands without reference to any unproven coding-speed benefit.

### 1. Session-to-session work state
`pin_add` / `pin_complete` track the unit of work inside a session; `session_resume` restores the open and in-progress pins from where the previous session stopped. This answers "where was I" directly — the one use case that drew consistent support even from skeptics of AI memory. Stale pins auto-close (in_progress after 7 days, open after 30), so restored state reflects live work instead of accumulating dead entries.

### 2. Knowledge that never reaches git
The *why* behind a decision, the approach that was tried and failed (a negative result worth not repeating), an operational constraint learned during an incident — these rarely survive in commits, PR descriptions, or design docs, even in a well-documented repository. mem-mesh keeps them as first-class categories (`decision`, `bug`, `incident`, `idea`, `code_snippet`) with typed relations (`supersedes`, `depends_on`, and others), so a superseded decision links to the one that replaced it rather than silently contradicting it.

### 3. Observability and retrospective
`weekly_review` reports what was captured, how memory is being used, and where it is going stale; the dashboard exposes the same operationally; team relay shares curated memory across machines. Critiques that dispute a coding-speed benefit still grant the observability use — knowing what your agents recorded and retrieved has value on its own.

## Empirical Stance
mem-mesh does not assert that retrieving past sessions improves coding performance. It instruments the question and lets the data decide.

- **Injection is tracked, not assumed.** Every memory auto-surfaced into a session is written to `injected_memories`, one row per injected memory with its turn and position. A deterministic Stop-time heuristic (no LLM) later judges whether an injected memory was actually referenced.
- **Utility is reported.** `weekly_review` includes an `injection_stats` block: how much was injected and how much of it was used.
- **Claims are testable offline.** A replay harness (`scripts/replay_injection_eval.py`) re-runs real captured prompts through the legacy blunt-truncation format and the current one, scoring both with deterministic metrics and an optional blind LLM judge.
- **Null is an acceptable answer.** The harness states its own premise: if the current format shows no advantage, shrinking injection is a valid outcome. Positioning follows the measurement, not the other way around.

## Capabilities in This Release
Only what is implemented and verifiable in the code.

### Injection quality
Surfaced memories render as `- [category] (age · source) title` lines through a three-tier extraction fallback: (1) an enrichment title and abstract when present (`source=enriched`), (2) a markdown heading plus its first sentence (`source=extracted`), (3) free text clipped at a sentence boundary within ~200 characters — never mid-sentence, skipping code blocks. Age is relative and human-readable ("오늘", "5일 전", "2개월 전"). Superseded and client-verified-stale memories are excluded from injection. Tiers 2 and 3 need no LLM, so injection stays legible in environments with no enrichment model configured.

### Lifespan and staleness
Code and commit memories carry `anchors` — the client collects `git rev-parse HEAD` and file paths at write time. Because the server has no git access, verification is delegated: the client checks anchor freshness locally and reports it through `report_anchor_status`. A two-stage stale gate follows. A client-reported `stale` verdict excludes the memory from injection (strong signal); an unverified commit anchor older than the configured age (default 90 days) only appends a "미검증 anchor" warning token without excluding it (weak signal).

### Promotion to durable docs
`doc_proposal` promotes high-value memory toward version-controlled documentation through a human gate: an LLM drafts the proposal when configured, a person approves or rejects it, and the client — not the server — applies the change to a file. The server never writes to the working tree; it only records the `applied` report and advances the state machine (`pending → approved → applied`, or `pending → rejected`). The model is explicit: **memory is the staging area, git is the durable layer.** Candidate ranking uses category weights and works without an LLM, so the free tier still surfaces what is worth promoting.

### Hygiene
Auto-captured content passes deterministic secret/PII redaction before it reaches long-term memory — private-key blocks, JWTs, and provider token shapes (`sk-…`, `gh…_…`, `xox…`, `AKIA…`, `AIza…`) are masked to `<REDACTED>`, idempotently. Content-rewriting maintenance (`improve`) and contradiction handling (`reconcile`) run as queues that are never auto-applied; a person approves each change, mirroring the doc-proposal gate. Session surfacing deliberately skips conversation-dump (`Q:`/`A:`) noise and favors high-value categories.

## Honest Limits
For pure code work in a repository whose commits, PRs, and docs are already well kept, the marginal value of retrieving past *sessions* is unproven — this is the critique mem-mesh takes seriously. Rather than assert a benefit, mem-mesh ships the tools to measure it (`injection_stats`, the Stop-time heuristic, the replay harness) and treats "reduce injection" as a legitimate result. The three defensible-core capabilities above stand independently of how that measurement resolves.

## Brand Personality
Pragmatic, calm, precise, and local-first. The interface should feel like an operator console for repeated work, not a marketing surface.

## Anti-References
- Navigation that promotes setup pages above daily memory and work views.
- Decorative dashboards that hide status, config paths, or auth state.
- Setup flows that require users to hand-edit tokens or infer the right client format.
- Positioning copy that claims a coding-speed benefit the instrumentation has not shown.

## Design Principles
1. Keep repeated memory work one click away.
2. Put setup, connection, and security controls under Settings.
3. Make copy-paste configuration explicit about target file, format, and required environment variables.
4. Surface auth risk and token state near the client configuration that depends on it.
5. Prefer dense, familiar controls over promotional layout.
6. Show a memory's age, source, and staleness wherever it is surfaced — never present a memory as if it were timeless.

## Accessibility and Inclusion
Meet WCAG AA contrast, preserve keyboard access, avoid motion-dependent feedback, and keep setup copy concise enough for non-native English readers.
