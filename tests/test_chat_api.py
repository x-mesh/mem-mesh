"""Chat HTTP API tests (settings round-trip) with overridden temporary DB."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database.base import Database
from app.web.common.dependencies import get_database
from app.web.dashboard.route_modules.chat import router as chat_router


@asynccontextmanager
async def _temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


def _app(db: Database) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: db
    return app


@pytest.mark.asyncio
async def test_chat_settings_round_trip_masks_key_and_records_source():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            # initial: nothing in DB
            r = await client.get("/api/chat/v1/settings")
            assert r.status_code == 200
            body = r.json()
            assert body["llm_api_key"]["secret"] is True
            assert body["llm_api_key"]["value"] is None

            # persist
            r = await client.put(
                "/api/chat/v1/settings",
                json={
                    "llm_provider": "OpenAI",
                    "llm_api_key": "sk-secret",
                    "llm_model": "gpt-4o",
                    "llm_base_url": "https://api.groq.com/openai/v1",
                },
            )
            assert r.status_code == 200
            body = r.json()
            # provider normalized + sourced from DB
            assert body["llm_provider"]["value"] == "openai"
            assert body["llm_provider"]["source"] == "db"
            assert body["llm_model"]["value"] == "gpt-4o"
            # key configured but never echoed back
            assert body["llm_api_key"]["configured"] is True
            assert body["llm_api_key"]["value"] is None

            # persisted to app_config under chat.llm_*
            assert await db.get_app_config("chat.llm_provider") == "openai"
            assert await db.get_app_config("chat.llm_api_key") == "sk-secret"


@pytest.mark.asyncio
async def test_chat_settings_rejects_bad_provider():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.put(
                "/api/chat/v1/settings", json={"llm_provider": "gemini"}
            )
            assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_test_rejects_bad_provider_override():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/chat/v1/test", json={"provider": "gemini"})
            assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_settings_clear_key_deletes_db_row():
    async with _temp_db() as db:
        await db.set_app_config("chat.llm_api_key", "sk-old")
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.put("/api/chat/v1/settings", json={"llm_api_key": "   "})
            assert r.status_code == 200
            assert await db.get_app_config("chat.llm_api_key") is None
