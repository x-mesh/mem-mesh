"""Ad-hoc read-path benchmark against a production DB snapshot.

Measures the SQL the dashboard /api/memories/search path actually runs
(see app/core/database/base.py + app/core/services/unified_search.py).
Read-only; does not mutate the DB. Throwaway diagnostic tool.
"""
import sqlite3
import statistics
import sys
import time

import sqlite_vec

DB = sys.argv[1] if len(sys.argv) > 1 else "data/prod_memories.db"


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    c.execute("PRAGMA busy_timeout=5000")
    return c


def bench(label, fn, n=25, warmup=3):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        rows = fn()
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    p95 = ts[min(len(ts) - 1, int(n * 0.95))]
    nrows = len(rows) if hasattr(rows, "__len__") else rows
    print(
        f"  {label:48s} median={statistics.median(ts):8.2f}ms  "
        f"p95={p95:8.2f}ms  min={ts[0]:7.2f}ms  rows={nrows}"
    )


def plan(c, label, sql, params=()):
    rows = c.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    print(f"  [{label}]")
    for r in rows:
        print(f"      {r['detail']}")


c = conn()
emb = c.execute("SELECT embedding FROM memories LIMIT 1").fetchone()[0]
# a project_id that actually has rows (mimics dashboard default filter)
pid = c.execute(
    "SELECT project_id FROM memories WHERE project_id IS NOT NULL "
    "GROUP BY project_id ORDER BY COUNT(*) DESC LIMIT 1"
).fetchone()[0]
pid_n = c.execute("SELECT COUNT(*) FROM memories WHERE project_id=?", (pid,)).fetchone()[0]
print(f"DB={DB}  top project_id={pid!r} ({pid_n} rows)\n")

NONEMB = ("id,content,content_hash,project_id,category,source,tags,"
          "created_at,updated_at,client")

print("=== TIMINGS ===")
# 1. recent list, current code path: SELECT *  (drags embedding BLOB)
bench("recent SELECT *  LIMIT 25",
      lambda: c.execute(
          "SELECT * FROM memories WHERE 1=1 ORDER BY created_at DESC LIMIT 25 OFFSET 0"
      ).fetchall())
# 2. same but without embedding column
bench("recent SELECT (no embedding) LIMIT 25",
      lambda: c.execute(
          f"SELECT {NONEMB} FROM memories ORDER BY created_at DESC LIMIT 25"
      ).fetchall())
# 3. separate COUNT(*) (unified_search runs this every list call)
bench("COUNT(*) memories",
      lambda: c.execute("SELECT COUNT(*) AS c FROM memories").fetchall())
# 4. recent list filtered by project (typical dashboard)
bench("recent SELECT * WHERE project_id LIMIT 25",
      lambda: c.execute(
          "SELECT * FROM memories WHERE 1=1 AND project_id=? "
          "ORDER BY created_at DESC LIMIT 25 OFFSET 0", (pid,)
      ).fetchall())
# 5. deep OFFSET pagination
bench("recent SELECT * LIMIT 25 OFFSET 16000",
      lambda: c.execute(
          "SELECT * FROM memories ORDER BY created_at DESC LIMIT 25 OFFSET 16000"
      ).fetchall())
# 6. tag filter via JSON_EXTRACT LIKE (full scan)
bench("tag filter JSON_EXTRACT LIKE",
      lambda: c.execute(
          "SELECT * FROM memories WHERE 1=1 AND JSON_EXTRACT(tags,'$') LIKE ? "
          "ORDER BY created_at DESC LIMIT 25", ('%"decision"%',)
      ).fetchall())
# 7. FTS exact
bench("FTS5 exact MATCH LIMIT 25",
      lambda: c.execute(
          "SELECT m.* FROM memories_fts fts JOIN memories m ON fts.id=m.id "
          "WHERE fts.memories_fts MATCH ? ORDER BY fts.rank LIMIT 25", ("버그",)
      ).fetchall())
# 8. vec semantic (the real base.py query)
bench("vec semantic MATCH k=25",
      lambda: c.execute(
          "SELECT m.*, ve.distance FROM memories m JOIN ("
          "SELECT memory_id, distance FROM memory_embeddings "
          "WHERE embedding MATCH ? ORDER BY distance LIMIT ?) ve "
          "ON m.id = ve.memory_id ORDER BY ve.distance LIMIT 25", (emb, 25)
      ).fetchall())
# 9. vec semantic with project pre-filter widened (limit*5)
bench("vec semantic MATCH k=125 (filtered path)",
      lambda: c.execute(
          "SELECT m.*, ve.distance FROM memories m JOIN ("
          "SELECT memory_id, distance FROM memory_embeddings "
          "WHERE embedding MATCH ? ORDER BY distance LIMIT ?) ve "
          "ON m.id = ve.memory_id WHERE m.project_id=? "
          "ORDER BY ve.distance LIMIT 25", (emb, 125, pid)
      ).fetchall())

print("\n=== QUERY PLANS ===")
plan(c, "recent SELECT *",
     "SELECT * FROM memories ORDER BY created_at DESC LIMIT 25")
plan(c, "recent WHERE project_id",
     "SELECT * FROM memories WHERE project_id=? ORDER BY created_at DESC LIMIT 25", (pid,))
plan(c, "tag JSON_EXTRACT LIKE",
     "SELECT * FROM memories WHERE JSON_EXTRACT(tags,'$') LIKE ? "
     "ORDER BY created_at DESC LIMIT 25", ('%"x"%',))
plan(c, "FTS exact",
     "SELECT m.* FROM memories_fts fts JOIN memories m ON fts.id=m.id "
     "WHERE fts.memories_fts MATCH ? ORDER BY fts.rank LIMIT 25", ("버그",))
c.close()
