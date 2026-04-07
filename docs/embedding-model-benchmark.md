# Embedding Model Benchmark for mem-mesh

> Date: 2026-04-07  
> Test environment: macOS Darwin 25.4.0, Python 3.13, sentence-transformers  
> Method: Clean 7-memory corpus, 15 Korean/English hybrid queries, cosine similarity

## Results Summary

| Rank | Model | Accuracy | Avg Score | Avg Gap | Load Time | Dim | Disk |
|:---:|-------|:---:|:---:|:---:|:---:|:---:|:---:|
| **1** | **nlpai-lab/KURE-v1** | **93%** | 0.612 | 0.166 | **5.0s** | 1024 | ~2.2GB |
| 2 | intfloat/multilingual-e5-large | 93% | 0.854 | 0.053 | 42.6s | 1024 | ~2.2GB |
| 3 | BAAI/bge-m3 | 93% | 0.603 | 0.169 | 46.1s | 1024 | ~4.4GB |
| 4 | nlpai-lab/KoE5 | 93% | 0.456 | 0.231 | 55.8s | 1024 | ~2.2GB |
| 5 | dragonkue/BGE-m3-ko | 93% | 0.559 | 0.207 | 61.0s | 1024 | ~2.2GB |
| 6 | jhgan/ko-sroberta-sts | 87% | 0.492 | 0.123 | 20.3s | 768 | ~845MB |
| 7 | paraphrase-multilingual-MiniLM-L12-v2 | 67% | 0.405 | 0.113 | 4.0s | 384 | ~458MB |
| 8 | snunlp/KR-SBERT-V40K-klueNLI-augSTS | 67% | 0.492 | 0.103 | 32.5s | 768 | ~892MB |

### Metrics Explained

- **Accuracy**: Top-1 hit rate (query → expected memory)
- **Avg Score**: Mean cosine similarity of top-1 results (higher = better absolute matching)
- **Avg Gap**: Mean score difference between 1st and 2nd result (higher = better discrimination)
- **Load Time**: Time to load model into memory (cached on disk)

## Analysis

### 93% Accuracy Group (5 models)

All five 93%-accuracy models failed only on one query: "디비 동시 접근" → expected `sqlite_wal`, got `schema_migration`. This query uses Korean slang ("디비" = DB) with an abstract concept ("동시 접근" = concurrent access), which is challenging for all models.

| Model | Strengths | Weaknesses |
|-------|-----------|------------|
| **KURE-v1** | Fastest load (5s), good discrimination (0.166 gap), Korean-optimized | Moderate absolute scores |
| E5-large | Highest absolute scores (0.854) | Low discrimination (0.053 gap), slow load (43s), needs query/passage prefix |
| BGE-M3 | Balanced scores + discrimination | Slow load (46s), largest disk (4.4GB) |
| KoE5 | Best discrimination (0.231 gap) | Slowest load (56s), lowest absolute scores, needs prefix |
| BGE-m3-ko | Good balance | Slowest load (61s) |

### Why KURE-v1 is recommended for mem-mesh

1. **Load time**: 5s vs 43-61s — critical for cold start and server restart
2. **Discrimination**: Gap 0.166 means clear separation between relevant and irrelevant results
3. **Korean optimization**: Fine-tuned BGE-M3 with Korean retrieval data (Korea University)
4. **Practical accuracy**: Same 93% as models 8-12x slower to load

### E5-large caveat

E5-large shows the highest absolute scores (0.854) but the **lowest discrimination** (0.053 gap). This means all memories score similarly high, making it harder to distinguish the best match. In production with thousands of memories, this could lead to noisy results.

## Memory & Storage

### Model Weights (RAM & Params)

Measured as full process RSS after model load + one inference (`psutil.Process.memory_info().rss`).

| Model | Dim | Params | Process RSS | Disk Size |
|-------|:---:|:------:|:-----------:|:---------:|
| MiniLM-multi | 384 | 118M | **795MB** | ~458MB |
| KR-SBERT | 768 | 117M | **561MB** | ~892MB |
| ko-sroberta | 768 | 111M | **534MB** | ~845MB |
| **KURE-v1** | 1024 | 568M | **802MB** | ~2.2GB |
| KoE5 | 1024 | 560M | **801MB** | ~2.2GB |
| BGE-m3-ko | 1024 | 568M | **801MB** | ~2.2GB |
| BGE-M3 | 1024 | 568M | **809MB** | ~4.4GB |
| E5-large | 1024 | 560M | **811MB** | ~2.2GB |

**Key finding**: All 1024d models use ~800MB RSS, not 2.2GB. PyTorch uses memory-mapped files, so actual RAM consumption is much lower than model file size on disk. The 768d Korean models are lighter at ~530-560MB.

### Vector Storage (sqlite-vec)

Each memory stores a single embedding vector: `dimension × 4 bytes (float32)`.

| Dimension | Per Memory | 1K memories | 10K memories | 100K memories |
|:---------:|:----------:|:-----------:|:------------:|:-------------:|
| 384 | 1.5KB | 1.5MB | 14.6MB | 146.5MB |
| 768 | 3.0KB | 2.9MB | 29.3MB | 293.0MB |
| 1024 | 4.0KB | 3.9MB | 39.1MB | 390.6MB |

**Key takeaway**: The dominant cost is **model loading (~2.2GB RAM)**, not vector storage. Even at 100K memories with 1024d, vectors use only ~391MB.

### Total RAM estimate (1024d model + vectors)

| Memories | Model RSS | Vectors | FTS5 index | Total (approx) |
|:--------:|:---------:|:-------:|:----------:|:--------------:|
| 1K | ~800MB | 4MB | ~2MB | **~810MB** |
| 10K | ~800MB | 39MB | ~20MB | **~860MB** |
| 100K | ~800MB | 391MB | ~200MB | **~1.4GB** |

Note: Model RSS ~800MB is the measured process memory (PyTorch uses mmap, so actual RAM is far less than 2.2GB disk size).

## Test Corpus

7 Korean technical memories covering: FastAPI bugs, SQLite WAL, embedding comparison, MCP protocol, FTS5 tokenizer, memory leak incident, schema migration.

### Queries (15)

| # | Query | Expected | Type |
|---|-------|----------|------|
| 0 | 비동기 미들웨어 버그 | fastapi_bug | Korean abstract |
| 1 | request body 두 번 읽기 | fastapi_bug | Korean + English |
| 2 | ASGI 스트림 | fastapi_bug | English keyword |
| 3 | WAL 모드 성능 | sqlite_wal | English keyword |
| 4 | 디비 동시 접근 | sqlite_wal | Korean slang |
| 5 | 임베딩 모델 비교 | embedding_compare | Korean |
| 6 | multilingual 한국어 recall | embedding_compare | Mixed |
| 7 | 한국어 형태소 분석 | fts5_tokenizer | Korean abstract |
| 8 | 토크나이저 kiwi mecab | fts5_tokenizer | English keyword |
| 9 | 메모리 누수 싱글턴 | memory_leak | Korean |
| 10 | RSS 메모리 사용량 감소 | memory_leak | Korean + English |
| 11 | 스키마 버전 마이그레이션 롤백 | schema_migration | Korean |
| 12 | Streamable HTTP transport | mcp_transport | English |
| 13 | MCP 세션 관리 | mcp_transport | Mixed |
| 14 | 벡터 검색 하이브리드 | embedding_compare | Korean |

### Per-Model Detailed Results

<details>
<summary>MiniLM-multi (67%)</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fts5_tokenizer      0.274  0.052 X
 1 request body 두번읽기    fastapi_bug        fastapi_bug         0.391  0.085 O
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.638  0.334 O
 3 WAL 모드 성능             sqlite_wal         fts5_tokenizer      0.291  0.014 X
 4 디비 동시 접근              sqlite_wal         embedding_compare   0.339  0.025 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.476  0.010 O
 6 multilingual 한국어      embedding_compare  embedding_compare   0.416  0.079 O
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.419  0.120 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.475  0.285 O
 9 메모리 누수 싱글턴            memory_leak        embedding_compare   0.283  0.046 X
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.721  0.351 O
11 스키마 마이그레이션 롤백         schema_migration   embedding_compare   0.223  0.001 X
12 Streamable HTTP        mcp_transport      mcp_transport       0.396  0.145 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.392  0.085 O
14 벡터 검색 하이브리드           embedding_compare  embedding_compare   0.349  0.068 O
```
</details>

<details>
<summary>KURE-v1 (93%) ★ Recommended</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fastapi_bug         0.656  0.172 O
 1 request body 두번읽기    fastapi_bug        fastapi_bug         0.686  0.193 O
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.607  0.193 O
 3 WAL 모드 성능             sqlite_wal         sqlite_wal          0.674  0.243 O
 4 디비 동시 접근              sqlite_wal         schema_migration    0.471  0.026 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.634  0.155 O
 6 multilingual 한국어      embedding_compare  embedding_compare   0.638  0.170 O
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.546  0.086 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.603  0.250 O
 9 메모리 누수 싱글턴            memory_leak        memory_leak         0.582  0.130 O
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.652  0.184 O
11 스키마 마이그레이션 롤백         schema_migration   schema_migration    0.694  0.232 O
12 Streamable HTTP        mcp_transport      mcp_transport       0.669  0.248 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.565  0.122 O
14 벡터 검색 하이브리드           embedding_compare  embedding_compare   0.499  0.081 O
```
</details>

<details>
<summary>E5-large (93%)</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fastapi_bug         0.867  0.065 O
 1 request body 두번읽기    fastapi_bug        fastapi_bug         0.866  0.052 O
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.831  0.059 O
 3 WAL 모드 성능             sqlite_wal         sqlite_wal          0.892  0.081 O
 4 디비 동시 접근              sqlite_wal         schema_migration    0.809  0.023 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.879  0.058 O
 6 multilingual 한국어      embedding_compare  embedding_compare   0.874  0.052 O
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.832  0.022 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.860  0.073 O
 9 메모리 누수 싱글턴            memory_leak        memory_leak         0.850  0.055 O
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.877  0.073 O
11 스키마 마이그레이션 롤백         schema_migration   schema_migration    0.884  0.072 O
12 Streamable HTTP        mcp_transport      mcp_transport       0.829  0.051 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.835  0.042 O
14 벡터 검색 하이브리드           embedding_compare  embedding_compare   0.820  0.016 O
```
</details>

<details>
<summary>KoE5 (93%)</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fastapi_bug         0.499  0.246 O
 1 request body 두번읽기    fastapi_bug        fastapi_bug         0.566  0.335 O
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.367  0.229 O
 3 WAL 모드 성능             sqlite_wal         sqlite_wal          0.605  0.341 O
 4 디비 동시 접근              sqlite_wal         schema_migration    0.246  0.041 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.550  0.262 O
 6 multilingual 한국어      embedding_compare  embedding_compare   0.471  0.194 O
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.344  0.105 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.385  0.280 O
 9 메모리 누수 싱글턴            memory_leak        memory_leak         0.500  0.259 O
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.533  0.311 O
11 스키마 마이그레이션 롤백         schema_migration   schema_migration    0.671  0.398 O
12 Streamable HTTP        mcp_transport      mcp_transport       0.480  0.272 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.392  0.181 O
14 벡터 검색 하이브리드           embedding_compare  embedding_compare   0.229  0.014 O
```
</details>

<details>
<summary>BGE-M3 (93%)</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fastapi_bug         0.626  0.138 O
 1 request body 두번읽기    fastapi_bug        fastapi_bug         0.677  0.188 O
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.581  0.202 O
 3 WAL 모드 성능             sqlite_wal         sqlite_wal          0.703  0.270 O
 4 디비 동시 접근              sqlite_wal         schema_migration    0.457  0.019 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.633  0.158 O
 6 multilingual 한국어      embedding_compare  embedding_compare   0.614  0.175 O
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.530  0.079 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.588  0.252 O
 9 메모리 누수 싱글턴            memory_leak        memory_leak         0.593  0.155 O
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.664  0.223 O
11 스키마 마이그레이션 롤백         schema_migration   schema_migration    0.651  0.207 O
12 Streamable HTTP        mcp_transport      mcp_transport       0.704  0.282 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.544  0.111 O
14 벡터 검색 하이브리드           embedding_compare  embedding_compare   0.487  0.084 O
```
</details>

<details>
<summary>BGE-m3-ko (93%)</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fastapi_bug         0.586  0.199 O
 1 request body 두번읽기    fastapi_bug        fastapi_bug         0.640  0.233 O
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.565  0.257 O
 3 WAL 모드 성능             sqlite_wal         sqlite_wal          0.648  0.287 O
 4 디비 동시 접근              sqlite_wal         schema_migration    0.377  0.040 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.584  0.178 O
 6 multilingual 한국어      embedding_compare  embedding_compare   0.595  0.231 O
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.465  0.092 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.544  0.286 O
 9 메모리 누수 싱글턴            memory_leak        memory_leak         0.527  0.163 O
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.630  0.256 O
11 스키마 마이그레이션 롤백         schema_migration   schema_migration    0.657  0.281 O
12 Streamable HTTP        mcp_transport      mcp_transport       0.628  0.312 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.516  0.175 O
14 벡터 검색 하이브리드           embedding_compare  embedding_compare   0.422  0.112 O
```
</details>

<details>
<summary>ko-sroberta (87%)</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fastapi_bug         0.636  0.169 O
 1 request body 두번읽기    fastapi_bug        fastapi_bug         0.458  0.155 O
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.368  0.007 O
 3 WAL 모드 성능             sqlite_wal         sqlite_wal          0.507  0.112 O
 4 디비 동시 접근              sqlite_wal         schema_migration    0.420  0.106 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.509  0.140 O
 6 multilingual 한국어      embedding_compare  embedding_compare   0.347  0.038 O
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.379  0.089 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.523  0.166 O
 9 메모리 누수 싱글턴            memory_leak        memory_leak         0.618  0.144 O
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.561  0.181 O
11 스키마 마이그레이션 롤백         schema_migration   schema_migration    0.587  0.202 O
12 Streamable HTTP        mcp_transport      mcp_transport       0.657  0.240 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.376  0.076 O
14 벡터 검색 하이브리드           embedding_compare  fts5_tokenizer      0.432  0.025 X
```
</details>

<details>
<summary>KR-SBERT (67%)</summary>

```
 0 비동기 미들웨어 버그        fastapi_bug        fastapi_bug         0.468  0.065 O
 1 request body 두번읽기    fastapi_bug        sqlite_wal          0.519  0.101 X
 2 ASGI 스트림              fastapi_bug        fastapi_bug         0.475  0.162 O
 3 WAL 모드 성능             sqlite_wal         mcp_transport       0.462  0.044 X
 4 디비 동시 접근              sqlite_wal         mcp_transport       0.436  0.008 X
 5 임베딩 모델 비교             embedding_compare  embedding_compare   0.369  0.025 O
 6 multilingual 한국어      embedding_compare  fts5_tokenizer      0.533  0.033 X
 7 한국어 형태소 분석            fts5_tokenizer     fts5_tokenizer      0.411  0.121 O
 8 토크나이저 kiwi mecab      fts5_tokenizer     fts5_tokenizer      0.537  0.090 O
 9 메모리 누수 싱글턴            memory_leak        memory_leak         0.607  0.234 O
10 RSS 메모리 사용량 감소        memory_leak        memory_leak         0.610  0.250 O
11 스키마 마이그레이션 롤백         schema_migration   schema_migration    0.573  0.212 O
12 Streamable HTTP        mcp_transport      mcp_transport       0.479  0.038 O
13 MCP 세션 관리              mcp_transport      mcp_transport       0.472  0.091 O
14 벡터 검색 하이브리드           embedding_compare  fastapi_bug         0.430  0.075 X
```
</details>

## Recommendation

**Default model: `nlpai-lab/KURE-v1`**

- Best balance of accuracy (93%), load time (5s), and discrimination (0.166 gap)
- Korean-optimized with strong English/multilingual fallback (BGE-M3 base)
- Same 1024 dimensions as other top models — no migration needed when switching between them
