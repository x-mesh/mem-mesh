"""Project 서비스 - 프로젝트 관리 비즈니스 로직"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from app.core.database.base import Database
from app.core.schemas.projects import (
    ProjectRenameResult,
    ProjectRenameTableResult,
    ProjectResponse,
    ProjectUpdate,
    ProjectWithStats,
)

logger = logging.getLogger(__name__)


class ProjectService:
    """프로젝트 관리 서비스"""

    def __init__(self, db: Database):
        self.db = db

    async def get_or_create_project(self, project_id: str) -> ProjectResponse:
        """
        프로젝트 조회 또는 자동 생성.

        Args:
            project_id: 프로젝트 ID

        Returns:
            ProjectResponse
        """
        # Query existing project
        row = await self.db.fetchone(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        )

        if row:
            return self._row_to_response(row)

        # Auto-create new project
        now = datetime.now(timezone.utc).isoformat()

        await self.db.execute(
            """
            INSERT INTO projects (id, name, description, tech_stack, global_rules, global_context, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, project_id, None, None, None, None, now, now),
        )
        self.db.connection.commit()

        logger.info(f"Auto-created project: {project_id}")

        return ProjectResponse(
            id=project_id,
            name=project_id,
            description=None,
            tech_stack=None,
            global_rules=None,
            global_context=None,
            created_at=now,
            updated_at=now,
        )

    async def get_project(self, project_id: str) -> Optional[ProjectResponse]:
        """프로젝트 조회"""
        row = await self.db.fetchone(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        )

        if not row:
            return None

        return self._row_to_response(row)

    async def update_project(
        self, project_id: str, update: ProjectUpdate
    ) -> Optional[ProjectResponse]:
        """프로젝트 업데이트"""
        # Check existing project
        existing = await self.get_project(project_id)
        if not existing:
            return None

        # Collect fields to update
        updates = []
        params = []

        update_data = update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if not updates:
            return existing

        # Add updated_at
        now = datetime.now(timezone.utc).isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(project_id)

        await self.db.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", tuple(params)
        )
        self.db.connection.commit()

        logger.info(f"Updated project: {project_id}")

        return await self.get_project(project_id)

    async def list_projects(self) -> List[ProjectResponse]:
        """모든 프로젝트 목록 조회"""
        rows = await self.db.fetchall("SELECT * FROM projects ORDER BY updated_at DESC")

        return [self._row_to_response(row) for row in rows]

    async def list_projects_with_stats(self) -> List[ProjectWithStats]:
        """프로젝트 목록 조회 (통계 포함)"""
        rows = await self.db.fetchall("""
            SELECT 
                p.*,
                COALESCE(m.memory_count, 0) as memory_count,
                COALESCE(pin.pin_count, 0) as pin_count,
                s.id as active_session,
                COALESCE(lt.avg_lead_time, 0) as avg_lead_time_hours
            FROM projects p
            LEFT JOIN (
                SELECT project_id, COUNT(*) as memory_count
                FROM memories
                GROUP BY project_id
            ) m ON p.id = m.project_id
            LEFT JOIN (
                SELECT project_id, COUNT(*) as pin_count
                FROM pins
                GROUP BY project_id
            ) pin ON p.id = pin.project_id
            LEFT JOIN (
                SELECT project_id, id
                FROM sessions
                WHERE status = 'active'
            ) s ON p.id = s.project_id
            LEFT JOIN (
                SELECT 
                    project_id,
                    AVG(
                        (julianday(completed_at) - julianday(created_at)) * 24
                    ) as avg_lead_time
                FROM pins
                WHERE status = 'completed' AND completed_at IS NOT NULL
                GROUP BY project_id
            ) lt ON p.id = lt.project_id
            ORDER BY p.updated_at DESC
            """)

        return [self._row_to_stats_response(row) for row in rows]

    async def _tables_with_project_id(self) -> List[str]:
        """project_id 컬럼을 가진 실제 테이블 목록 (동적 탐색).

        하드코딩하지 않는 이유: project_id를 쓰는 테이블이 18개 넘고 계속 늘어난다.
        목록을 고정하면 새 테이블이 조용히 누락돼 반쪽 병합이 된다.
        FTS/vec 가상 테이블은 제외한다 — memories의 트리거가 알아서 동기화하며,
        직접 UPDATE하면 인덱스가 어긋난다.
        """

        rows = await self.db.fetchall("""
            SELECT name, sql FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """)
        tables: List[str] = []
        for row in rows:
            sql = row["sql"] or ""
            if " USING " in sql.upper():  # virtual table (fts5, vec0)
                continue
            columns = await self.db.fetchall(f"PRAGMA table_info({row['name']})")
            if any(col["name"] == "project_id" for col in columns):
                tables.append(row["name"])
        return tables

    async def _project_unique_tables(self, tables: List[str]) -> set:
        """Tables where project_id alone is UNIQUE (or the PK).

        These are the settings-shaped rows — a relay auto-share subscription, an
        overview schedule, an auto-enrich subscription. On a merge the target's
        row wins and the source row is dropped; nothing else in the schema can
        collide on project_id (memories/pins/token_usage key on id).
        """

        unique: set = set()
        for table in tables:
            for index in await self.db.fetchall(f"PRAGMA index_list({table})"):
                if not index["unique"]:
                    continue
                cols = [
                    c["name"]
                    for c in await self.db.fetchall(
                        f"PRAGMA index_info({index['name']})"
                    )
                ]
                if cols == ["project_id"] and not index["partial"]:
                    unique.add(table)
                    break
            else:
                info = await self.db.fetchall(f"PRAGMA table_info({table})")
                pk = [c["name"] for c in info if c["pk"]]
                if pk == ["project_id"]:
                    unique.add(table)
        return unique

    async def _conflicting_active_sessions(self, source_id: str, target_id: str) -> int:
        """Active source sessions whose (project, user) slot is already taken.

        Only one active session per (project_id, user_id) is allowed, so these
        get closed (status='ended') on the way over rather than dropped.
        """

        row = await self.db.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM sessions s
            WHERE s.project_id = ?
              AND s.status = 'active'
              AND EXISTS (
                    SELECT 1 FROM sessions t
                    WHERE t.project_id = ?
                      AND t.status = 'active'
                      AND t.user_id = s.user_id
              )
            """,
            (source_id, target_id),
        )
        return int(row["count"]) if row else 0

    async def rename_project(
        self, source_id: str, target_id: str, *, dry_run: bool = False
    ) -> ProjectRenameResult:
        """프로젝트 이름 변경. target이 이미 있으면 그쪽으로 흡수(병합)한다.

        project_id를 가진 모든 테이블을 한 트랜잭션에서 옮긴다. project_id가
        UNIQUE인 설정성 테이블(구독/스케줄 등)에서 target 행이 이미 있으면 옮길
        수 없으므로 source 행을 버린다(target 설정이 이긴다). 활성 세션은 프로젝트
        당 하나만 허용되므로, 충돌하는 source 세션은 ended로 닫고 옮긴다.
        """

        source_id = source_id.strip()
        target_id = target_id.strip()
        if not source_id or not target_id:
            raise ValueError("source_id와 target_id는 비어 있을 수 없습니다")
        if source_id == target_id:
            raise ValueError("source_id와 target_id가 같습니다")

        tables = await self._tables_with_project_id()
        merged = (
            await self.db.fetchone("SELECT 1 FROM projects WHERE id = ?", (target_id,))
            is not None
        )

        if dry_run:
            # The preview has to predict what apply() will DROP, not just what it
            # moves: on a table keyed by project_id (a subscription, a schedule)
            # the target's row wins and the source row is deleted. A preview that
            # reports those as "moved" asks the user to approve a silent delete.
            unique_tables = await self._project_unique_tables(tables)
            results: List[ProjectRenameTableResult] = []
            sessions_ended = 0
            for table in tables:
                if table == "projects":
                    continue
                row = await self.db.fetchone(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = ?",
                    (source_id,),
                )
                total = int(row["count"])
                if not total:
                    continue
                dropped = 0
                if table == "sessions":
                    sessions_ended = await self._conflicting_active_sessions(
                        source_id, target_id
                    )
                elif table in unique_tables:
                    conflict = await self.db.fetchone(
                        f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = ?",
                        (target_id,),
                    )
                    # project_id is UNIQUE here, so an existing target row means
                    # every source row for this table loses.
                    dropped = total if int(conflict["count"]) else 0
                results.append(
                    ProjectRenameTableResult(
                        table=table, moved=total - dropped, dropped=dropped
                    )
                )
            return ProjectRenameResult(
                source_id=source_id,
                target_id=target_id,
                merged=merged,
                dry_run=True,
                total_moved=sum(r.moved for r in results),
                total_dropped=sum(r.dropped for r in results),
                sessions_ended=sessions_ended,
                tables=results,
            )

        now = datetime.now(timezone.utc).isoformat()
        results = []
        sessions_ended = 0
        unique_tables = await self._project_unique_tables(tables)

        async with self.db.transaction():
            # sessions/pins have FK REFERENCES projects(id) and foreign_keys is
            # ON, so the target project row must exist before anything moves.
            if not merged:
                await self.db.execute(
                    """
                    INSERT INTO projects (
                        id, name, description, tech_stack, global_rules,
                        global_context, created_at, updated_at
                    )
                    SELECT ?, ?, description, tech_stack, global_rules,
                           global_context, created_at, ?
                    FROM projects WHERE id = ?
                    """,
                    (target_id, target_id, now, source_id),
                )
                if (
                    await self.db.fetchone(
                        "SELECT 1 FROM projects WHERE id = ?", (target_id,)
                    )
                    is None
                ):
                    # source had no projects row either (memories-only project)
                    await self.db.execute(
                        """
                        INSERT INTO projects (
                            id, name, description, tech_stack, global_rules,
                            global_context, created_at, updated_at
                        )
                        VALUES (?, ?, NULL, NULL, NULL, NULL, ?, ?)
                        """,
                        (target_id, target_id, now, now),
                    )

            for table in tables:
                if table == "projects":
                    continue

                before = await self.db.fetchone(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = ?",
                    (source_id,),
                )
                if not before["count"]:
                    continue

                # OR IGNORE: a UNIQUE(project_id) row already on the target is
                # kept; the source row stays behind and is handled below.
                await self.db.execute(
                    f"UPDATE OR IGNORE {table} SET project_id = ? WHERE project_id = ?",
                    (target_id, source_id),
                )
                left = await self.db.fetchone(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = ?",
                    (source_id,),
                )
                dropped = int(left["count"])

                if dropped and table == "sessions":
                    # Only one active session per (project, user) is allowed.
                    # Close the loser instead of deleting session history.
                    await self.db.execute(
                        """
                        UPDATE sessions
                        SET status = 'ended',
                            ended_at = COALESCE(ended_at, ?),
                            project_id = ?,
                            updated_at = ?
                        WHERE project_id = ?
                        """,
                        (now, target_id, now, source_id),
                    )
                    sessions_ended = dropped
                    dropped = 0
                elif dropped:
                    if table not in unique_tables:
                        # A row that would not move, on a table where project_id
                        # is NOT the unique key: this is not the settings-row case
                        # the drop was written for — it is a schema the merge does
                        # not understand. Abort the whole transaction instead of
                        # deleting rows nobody predicted (the dry-run preview did
                        # not warn about them either).
                        raise RuntimeError(
                            f"rename aborted: {dropped} row(s) in '{table}' could "
                            f"not move from '{source_id}' to '{target_id}' and "
                            "project_id is not that table's unique key — refusing "
                            "to delete unpredicted rows"
                        )
                    await self.db.execute(
                        f"DELETE FROM {table} WHERE project_id = ?", (source_id,)
                    )

                results.append(
                    ProjectRenameTableResult(
                        table=table,
                        moved=int(before["count"]) - dropped,
                        dropped=dropped,
                    )
                )

            await self.db.execute("DELETE FROM projects WHERE id = ?", (source_id,))
            await self.db.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?", (now, target_id)
            )

        logger.info(
            "Renamed project %s -> %s (merged=%s, moved=%s)",
            source_id,
            target_id,
            merged,
            sum(r.moved for r in results),
        )

        return ProjectRenameResult(
            source_id=source_id,
            target_id=target_id,
            merged=merged,
            dry_run=False,
            total_moved=sum(r.moved for r in results),
            total_dropped=sum(r.dropped for r in results),
            sessions_ended=sessions_ended,
            tables=results,
        )

    async def delete_project(self, project_id: str) -> bool:
        """프로젝트 삭제 (관련 세션, 핀도 삭제)"""
        existing = await self.get_project(project_id)
        if not existing:
            return False

        # Delete related pins
        await self.db.execute("DELETE FROM pins WHERE project_id = ?", (project_id,))

        # Delete related sessions
        await self.db.execute(
            "DELETE FROM sessions WHERE project_id = ?", (project_id,)
        )

        # Delete project
        await self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.db.connection.commit()

        logger.info(f"Deleted project: {project_id}")
        return True

    def _row_to_response(self, row) -> ProjectResponse:
        """DB row를 ProjectResponse로 변환"""
        return ProjectResponse(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            tech_stack=row["tech_stack"],
            global_rules=row["global_rules"],
            global_context=row["global_context"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_stats_response(self, row) -> ProjectWithStats:
        """DB row를 ProjectWithStats로 변환"""
        return ProjectWithStats(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            tech_stack=row["tech_stack"],
            global_rules=row["global_rules"],
            memory_count=row["memory_count"] or 0,
            pin_count=row["pin_count"] or 0,
            active_session=row["active_session"],
            avg_lead_time_hours=row["avg_lead_time_hours"],
        )
