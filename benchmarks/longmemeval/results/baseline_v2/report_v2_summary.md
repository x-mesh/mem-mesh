# LongMemEval Benchmark v2 Results

**Date**: 2026-02-26
**Config**: variant=s, topk=10, hybrid search, sonnet, direct (no CoT)

## v1 → v2 Comparison (500 questions)

| Category | v1 | v2 | Delta |
|---------|-----|-----|------|
| knowledge-update | 9.0% | **89.7%** | **+80.7%p** |
| single-session-assistant | 87.5% | **98.2%** | **+10.7%p** |
| single-session-preference | 46.7% | **66.7%** | **+20.0%p** |
| multi-session | 68.4% | **72.2%** | **+3.8%p** |
| single-session-user | 85.7% | 87.1% | +1.4%p |
| temporal-reasoning | 76.7% | 75.9% | -0.8%p |
| **Overall** | **64.6%** | **80.6%** | **+16.0%p** |
| **Task-Averaged** | **62.3%** | **81.7%** | **+19.4%p** |
| Abstention | 70.0% | **90.0%** | **+20.0%p** |
| Generation Failed | 72 | **0** | **-100%** |

## Retrieval Metrics (unchanged — same DB/index)

| Metric | Value |
|--------|-------|
| Recall@10 (any) | 97.0% |
| Recall@10 (all) | 90.6% |
| Avg search time | 37 ms |
| Avg generation time | 10.9 s |

## v2 Changes Applied

### 1. Retry with backoff + stdin pipe
- Prompt delivery via stdin (`-p -` + `input=prompt`) instead of CLI arg
- Exponential backoff (2s, 4s, 8s) between retries
- Default retries: 1 → 3
- **Result**: Generation failures 72 → 0

### 2. Chronological sorting of retrieved excerpts
- `RetrievalResult.sorted_contents_with_dates` property sorts by date (oldest → newest)
- Date headers added to excerpts: `--- Excerpt 1 (2023/04/15) ---`
- **Result**: knowledge-update 9% → 89.7%

### 3. Enhanced generation prompts
- Added temporal priority instructions to both DIRECT and COT prompts
- "Excerpts are ordered chronologically. Prefer MOST RECENT information."
- COT prompt includes 3-step reasoning structure
- **Result**: Improved preference (+20%p), assistant (+10.7%p), abstention (+20%p)

### 4. --retry-failed CLI option
- Filters `(generation failed)` results from checkpoint
- Uses `update_result()` to replace in-place
- Enables selective re-run without full benchmark restart

## Remaining Weak Points

| Category | Accuracy | Issue |
|---------|----------|-------|
| single-session-preference | 66.7% | Needs better personalization context utilization |
| multi-session | 72.2% | recall_all=89%, some sessions missed |
| temporal-reasoning | 75.9% | Complex date arithmetic errors |
