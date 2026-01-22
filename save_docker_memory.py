#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/app')

from app.core.database.base import Database
from app.core.services.memory import MemoryService
from app.core.embeddings.service import EmbeddingService
from app.core.config import get_settings

async def save_memory():
    settings = get_settings()
    db = Database(settings.database_path)
    
    embedding_service = EmbeddingService(settings.embedding_model)
    memory_service = MemoryService(db, embedding_service)
    
    content = """Q: mem-mesh Docker containerization with Makefile

A: Docker setup completed successfully

Files created:
- Dockerfile (production): multi-stage build, Python 3.11, non-root user
- Dockerfile.dev (development): hot-reload, debugging tools
- docker-compose.yml: production/dev services
- Makefile: convenient command wrappers
- .dockerignore: build optimization

Key commands:
make build-dev, make up-dev, make bash-dev, make logs-dev, make test, make down

Issues resolved:
- pysqlite3 build failure: added libsqlite3-dev package
- docker-compose version warning: removed version field

Results:
- Dev container running at http://localhost:8000
- API health check working (/api/health)
- Bash debugging access available
- Data persistence via volumes (./data, ./logs)
- README.md updated with Docker section"""
    
    memory = await memory_service.add_memory(
        content=content,
        category="task",
        project_id="mem-mesh",
        tags=["docker", "dockerfile", "makefile", "containerization", "devops"],
        source="manual"
    )
    
    print(f"Saved to mem-mesh | Project: mem-mesh | ID: {memory.id}")

if __name__ == "__main__":
    asyncio.run(save_memory())
