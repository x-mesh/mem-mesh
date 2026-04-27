"""
Memory Relations 서비스.

메모리 간 관계를 관리하는 비즈니스 로직.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.core.database.base import Database
from app.core.errors import MemoryNotFoundError, RelationNotFoundError
from app.core.schemas.relations import (
    Relation,
    RelationCreate,
    RelationGraph,
    RelationType,
    RelationUpdate,
    RelationWithMemory,
)


class RelationService:
    """메모리 관계 서비스"""

    def __init__(self, db: Database):
        self.db = db

    async def _memory_exists(self, memory_id: str) -> bool:
        """메모리 존재 여부 확인"""
        result = await self.db.fetchone(
            "SELECT id FROM memories WHERE id = ?", (memory_id,)
        )
        return result is not None

    async def create_relation(self, data: RelationCreate) -> Relation:
        """관계 생성"""
        # 메모리 존재 확인
        if not await self._memory_exists(data.source_id):
            raise MemoryNotFoundError(data.source_id, role="Source memory")
        if not await self._memory_exists(data.target_id):
            raise MemoryNotFoundError(data.target_id, role="Target memory")

        # 자기 참조 방지
        if data.source_id == data.target_id:
            raise ValueError("Cannot create relation to self")

        now = datetime.now(timezone.utc).isoformat()
        relation_id = str(uuid.uuid4())

        await self.db.execute(
            """
            INSERT INTO memory_relations 
            (id, source_id, target_id, relation_type, strength, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relation_id,
                data.source_id,
                data.target_id,
                data.relation_type.value,
                data.strength,
                json.dumps(data.metadata) if data.metadata else None,
                now,
                now,
            ),
        )

        return await self.get_relation(relation_id)

    async def get_relation(self, relation_id: str) -> Optional[Relation]:
        """관계 조회"""
        row = await self.db.fetchone(
            "SELECT * FROM memory_relations WHERE id = ?", (relation_id,)
        )
        if not row:
            return None

        return self._row_to_relation(row)

    async def update_relation(self, relation_id: str, data: RelationUpdate) -> Relation:
        """관계 수정"""
        existing = await self.get_relation(relation_id)
        if not existing:
            raise RelationNotFoundError(f"Relation not found: {relation_id}")

        updates = []
        params = []

        if data.relation_type is not None:
            updates.append("relation_type = ?")
            params.append(data.relation_type.value)

        if data.strength is not None:
            updates.append("strength = ?")
            params.append(data.strength)

        if data.metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(data.metadata))

        if updates:
            updates.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            params.append(relation_id)

            await self.db.execute(
                f"UPDATE memory_relations SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )

        return await self.get_relation(relation_id)

    async def delete_relation(self, relation_id: str) -> bool:
        """관계 삭제"""
        cursor = await self.db.execute(
            "DELETE FROM memory_relations WHERE id = ?", (relation_id,)
        )
        return cursor.rowcount > 0

    async def get_relations_for_memory(
        self,
        memory_id: str,
        relation_type: Optional[RelationType] = None,
        direction: str = "both",  # 'outgoing', 'incoming', 'both'
        min_strength: float = 0.0,
        limit: int = 50,
    ) -> List[RelationWithMemory]:
        """특정 메모리의 관계 조회"""
        conditions = []
        params = []

        if direction == "outgoing":
            conditions.append("r.source_id = ?")
            params.append(memory_id)
        elif direction == "incoming":
            conditions.append("r.target_id = ?")
            params.append(memory_id)
        else:  # both
            conditions.append("(r.source_id = ? OR r.target_id = ?)")
            params.extend([memory_id, memory_id])

        if relation_type:
            conditions.append("r.relation_type = ?")
            params.append(relation_type.value)

        conditions.append("r.strength >= ?")
        params.append(min_strength)

        params.append(limit)

        query = f"""
            SELECT 
                r.*,
                s.content as source_content,
                s.project_id as source_project_id,
                t.content as target_content,
                t.project_id as target_project_id
            FROM memory_relations r
            LEFT JOIN memories s ON r.source_id = s.id
            LEFT JOIN memories t ON r.target_id = t.id
            WHERE {' AND '.join(conditions)}
            ORDER BY r.strength DESC, r.created_at DESC
            LIMIT ?
        """

        rows = await self.db.fetchall(query, tuple(params))
        return [self._row_to_relation_with_memory(row) for row in rows]

    async def get_relation_graph(
        self,
        memory_id: str,
        depth: int = 2,
        relation_types: Optional[List[RelationType]] = None,
        min_strength: float = 0.0,
    ) -> RelationGraph:
        """관계 그래프 조회 (BFS)"""
        visited = set()
        relations = []
        queue = [(memory_id, 0)]

        while queue:
            current_id, current_depth = queue.pop(0)

            if current_id in visited or current_depth >= depth:
                continue

            visited.add(current_id)

            # 현재 노드의 관계 조회
            node_relations = await self.get_relations_for_memory(
                current_id,
                direction="both",
                min_strength=min_strength,
            )

            for rel in node_relations:
                # 관계 유형 필터
                if relation_types and rel.relation_type not in relation_types:
                    continue

                relations.append(rel)

                # 다음 탐색 대상 추가
                next_id = (
                    rel.target_id if rel.source_id == current_id else rel.source_id
                )
                if next_id not in visited:
                    queue.append((next_id, current_depth + 1))

        # 중복 제거
        seen_ids = set()
        unique_relations = []
        for rel in relations:
            if rel.id not in seen_ids:
                seen_ids.add(rel.id)
                unique_relations.append(rel)

        return RelationGraph(
            center_id=memory_id,
            relations=unique_relations,
            depth=depth,
            total_nodes=len(visited),
        )

    async def find_or_create_relation(
        self, data: RelationCreate
    ) -> tuple[Relation, bool]:
        """관계 조회 또는 생성 (created 여부 반환)"""
        existing = await self.db.fetchone(
            """
            SELECT * FROM memory_relations 
            WHERE source_id = ? AND target_id = ? AND relation_type = ?
            """,
            (data.source_id, data.target_id, data.relation_type.value),
        )

        if existing:
            return self._row_to_relation(existing), False

        relation = await self.create_relation(data)
        return relation, True

    async def auto_link_similar(
        self,
        memory_id: str,
        threshold: float = 0.7,
        limit: int = 5,
    ) -> List[Relation]:
        """벡터 유사도 기반 자동 연결.

        주어진 메모리와 유사한 메모리를 벡터 검색으로 찾아
        ``RelationType.SIMILAR`` 관계를 생성한다. 이미 존재하는 관계는
        ``get_or_create_relation`` 을 통해 중복 생성하지 않는다.

        Args:
            memory_id: 기준 메모리 ID
            threshold: 최소 유사도 (0.0-1.0). 거리→유사도 변환 후 필터
            limit: 생성할 최대 관계 수
        """
        if not await self._memory_exists(memory_id):
            raise MemoryNotFoundError(memory_id)

        row = await self.db.fetchone(
            "SELECT embedding FROM memories WHERE id = ?", (memory_id,)
        )
        if not row or row["embedding"] is None:
            return []

        # 자기 자신이 결과에 포함되므로 limit+1 로 조회
        raw_results = await self.db.vector_search(
            embedding=row["embedding"], limit=limit + 1, filters=None
        )
        if not raw_results:
            return []

        created_relations: List[Relation] = []
        for result_row in raw_results:
            if len(created_relations) >= limit:
                break

            try:
                target_id = result_row["id"]
                distance = float(result_row["distance"])
            except (IndexError, KeyError, TypeError, ValueError):
                continue

            if target_id == memory_id:
                continue

            similarity = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
            if similarity < threshold:
                continue

            relation, created = await self.get_or_create_relation(
                RelationCreate(
                    source_id=memory_id,
                    target_id=target_id,
                    relation_type=RelationType.SIMILAR,
                    strength=similarity,
                )
            )
            if created:
                created_relations.append(relation)

        return created_relations

    def _row_to_relation(self, row: dict) -> Relation:
        """DB row를 Relation으로 변환"""
        return Relation(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation_type=RelationType(row["relation_type"]),
            strength=row["strength"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_relation_with_memory(self, row: dict) -> RelationWithMemory:
        """DB row를 RelationWithMemory로 변환"""
        return RelationWithMemory(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation_type=RelationType(row["relation_type"]),
            strength=row["strength"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_content=(
                row["source_content"] if "source_content" in row.keys() else None
            ),
            source_project_id=(
                row["source_project_id"] if "source_project_id" in row.keys() else None
            ),
            target_content=(
                row["target_content"] if "target_content" in row.keys() else None
            ),
            target_project_id=(
                row["target_project_id"] if "target_project_id" in row.keys() else None
            ),
        )
