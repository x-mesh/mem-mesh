"""project_id 정규화가 쓰기 경로 전체에서 일관되게 적용되는지 검증.

배경 (issue #6): 대시보드 프로젝트 상세에서 통계는 메모리 8개를 세는데 목록은
0건이었다. ProjectService가 정규화 없이 받은 값 그대로 projects 행을 만들어
projects.id="CSAP"가 되는 사이, 메모리는 AddParams 정규화를 거쳐
project_id="csap"로 저장됐다. 통계는 projects.id = memories.project_id 정확
매칭이라 갈라진 채로 숫자가 맞아 보였고, 목록은 정규화된 id로 찾으니 비었다.
"""

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from app.core.schemas.projects import ProjectUpdate
from app.core.schemas.requests import normalize_project_id
from app.core.services.project import ProjectService


async def _insert_memory(db, project_id: str, content: str) -> None:
    """AddParams를 거친 저장을 흉내낸다 (project_id는 정규화된 값)."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO memories "
        "(id, content, content_hash, embedding, project_id, category, source, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            content,
            hashlib.sha256(content.encode()).hexdigest(),
            b"",
            normalize_project_id(project_id),
            "task",
            "mcp",
            now,
            now,
        ),
    )


@pytest.mark.asyncio
async def test_create_normalizes_uppercase_project_id(temp_db):
    """대문자로 만들어도 저장되는 id는 정규화된 형태다."""
    service = ProjectService(temp_db)

    project = await service.get_or_create_project("CSAP")

    assert project.id == "csap"
    rows = await temp_db.fetchall("SELECT id FROM projects")
    assert [row["id"] for row in rows] == ["csap"]


@pytest.mark.asyncio
async def test_create_is_idempotent_across_spellings(temp_db):
    """같은 저장소의 다른 표기가 하나의 프로젝트로 모인다.

    정규화는 단순 소문자화가 아니라 구분자까지 통일하므로 "oci_tools"와
    "OCI-Tools"도 같은 id가 된다.
    """
    service = ProjectService(temp_db)

    first = await service.get_or_create_project("CSAP")
    second = await service.get_or_create_project("csap")

    assert first.id == second.id == "csap"

    third = await service.get_or_create_project("oci_tools")
    fourth = await service.get_or_create_project("OCI-Tools")

    assert third.id == fourth.id == "oci-tools"

    rows = await temp_db.fetchall("SELECT id FROM projects ORDER BY id")
    assert [row["id"] for row in rows] == ["csap", "oci-tools"]


@pytest.mark.asyncio
async def test_stats_and_filtered_list_agree(temp_db):
    """issue #6 회귀: 통계 건수와 project_id 필터 조회 건수가 일치한다.

    정규화가 생성 경로에서 빠지면 projects.id가 "CSAP"로 남아 통계는 0건이
    되고(조인 실패), 아래 두 건수가 어긋난다.
    """
    service = ProjectService(temp_db)
    await service.get_or_create_project("CSAP")
    for i in range(8):
        await _insert_memory(temp_db, "CSAP", f"CSAP memory {i}")

    stats = {s.id: s.memory_count for s in await service.list_projects_with_stats()}
    listed = await temp_db.fetchall(
        "SELECT id FROM memories WHERE project_id = ?",
        (normalize_project_id("CSAP"),),
    )

    assert stats == {"csap": 8}
    assert len(listed) == 8


@pytest.mark.asyncio
async def test_lookup_and_update_follow_the_same_id_rule(temp_db):
    """생성한 프로젝트를 원본 표기로도 조회·수정할 수 있다."""
    service = ProjectService(temp_db)
    await service.get_or_create_project("CSAP")

    assert (await service.get_project("CSAP")) is not None
    updated = await service.update_project("CSAP", ProjectUpdate(name="CSAP 프로젝트"))

    assert updated is not None
    assert updated.id == "csap"
    assert updated.name == "CSAP 프로젝트"


@pytest.mark.asyncio
async def test_delete_accepts_original_spelling(temp_db):
    """삭제도 같은 규칙을 따른다 — 만든 표기로 지울 수 있어야 한다."""
    service = ProjectService(temp_db)
    await service.get_or_create_project("CSAP")

    assert await service.delete_project("CSAP") is True
    assert await service.get_project("csap") is None
