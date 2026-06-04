#!/usr/bin/env python3
"""Normalize project ids across all tables to de-fragment the project list.

Collapses worktree suffixes / casing / separator variants of the same repo into
one canonical id (mirrors
``app.web.dashboard.route_modules.hooks._normalize_project_id``), then merges
the now-duplicate ``projects`` rows while preserving session/pin foreign keys.

    term-mesh-wt-170638b5  → term-mesh
    oci_tools / OCI-Tools  → oci-tools
    VLM                    → vlm

Affected tables: memories, projects (PK), sessions, pins, token_usage,
hook_events, search_metrics. The FTS index syncs via the memories triggers; the
sqlite-vec tables key on memory_id only, so they need no changes.

Usage:
    python scripts/migrate_project_id_normalization.py             # dry-run
    python scripts/migrate_project_id_normalization.py --apply
    python scripts/migrate_project_id_normalization.py --db /path/to.db --apply

⚠️  Run against a backup first. This rewrites primary keys in ``projects``.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Settings  # noqa: E402
from app.core.database.base import Database  # noqa: E402

# Keep in sync with hooks._normalize_project_id / hooks._WT_SUFFIX_RE.
_WT_SUFFIX_RE = re.compile(r"[-_]wt[-_][0-9a-f]{6,}$", re.IGNORECASE)

# Tables carrying a project_id column (``projects.id`` is handled separately
# because it is a primary key that sessions/pins reference).
_CHILD_TABLES = (
    "memories",
    "sessions",
    "pins",
    "token_usage",
    "hook_events",
    "search_metrics",
)


def normalize_project_id(name: str) -> str:
    name = (name or "").strip()
    if "/" in name:  # an absolute/relative path leaked in as the id
        name = name.rstrip("/").split("/")[-1]
    name = name.lower()
    name = _WT_SUFFIX_RE.sub("", name)
    name = re.sub(r"[_.]", "-", name)  # unify separators
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "unknown"


def _collect_ids(conn) -> set[str]:
    ids: set[str] = set()
    for table in _CHILD_TABLES:
        try:
            rows = conn.execute(
                f"SELECT DISTINCT project_id FROM {table} WHERE project_id IS NOT NULL"
            ).fetchall()
        except Exception as e:  # table may not exist in older DBs
            print(f"  (skip {table}: {e})")
            continue
        ids.update(r[0] for r in rows if r[0])
    try:
        ids.update(r[0] for r in conn.execute("SELECT id FROM projects").fetchall())
    except Exception as e:
        print(f"  (skip projects: {e})")
    return ids


def _count_rows(conn, table: str, project_id: str) -> int:
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


async def migrate(db_path: str, dry_run: bool = True) -> None:
    db = Database(db_path)
    await db.connect()
    conn = db.connection
    try:
        ids = _collect_ids(conn)
        mapping = {pid: normalize_project_id(pid) for pid in ids}
        mapping = {old: new for old, new in mapping.items() if old != new}

        if not mapping:
            print("✅ 정규화할 project_id 없음 — 이미 정규 형태입니다.")
            return

        print(f"정규화 대상 {len(mapping)}개 (현재 전체 {len(ids)}개):\n")
        for old, new in sorted(mapping.items()):
            affected = sum(_count_rows(conn, t, old) for t in _CHILD_TABLES)
            print(f"  {old:40s} → {new:25s} ({affected} rows)")

        targets = {new for new in mapping.values()}
        print(f"\n예상 결과: {len(ids)} → {len(ids) - len(mapping) + len(targets - ids)} 프로젝트")

        if dry_run:
            print("\n[dry-run] 변경 사항 없음. 적용하려면 --apply 를 붙이세요.")
            return

        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN")
            # 1) Child tables: straight rename.
            for table in _CHILD_TABLES:
                for old, new in mapping.items():
                    conn.execute(
                        f"UPDATE {table} SET project_id = ? WHERE project_id = ?",
                        (new, old),
                    )
            # 2) projects PK: rename when the target is free, otherwise merge
            #    (the duplicate row is dropped; children already point to `new`).
            for old, new in mapping.items():
                exists = conn.execute(
                    "SELECT 1 FROM projects WHERE id = ?", (new,)
                ).fetchone()
                if exists:
                    conn.execute("DELETE FROM projects WHERE id = ?", (old,))
                else:
                    conn.execute(
                        "UPDATE projects SET id = ? WHERE id = ?", (new, old)
                    )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

        remaining = {p for p in _collect_ids(conn) if normalize_project_id(p) != p}
        print("\n✅ 적용 완료.")
        if remaining:
            print(f"⚠️  남은 비정규 id {len(remaining)}개: {sorted(remaining)}")
        else:
            print("   모든 project_id 정규화 확인됨.")
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite DB 경로 (기본: Settings)")
    parser.add_argument(
        "--apply", action="store_true", help="실제 적용 (미지정 시 dry-run)"
    )
    args = parser.parse_args()

    db_path = args.db or Settings().database_path
    print(f"DB: {db_path}")
    asyncio.run(migrate(db_path, dry_run=not args.apply))


if __name__ == "__main__":
    main()
