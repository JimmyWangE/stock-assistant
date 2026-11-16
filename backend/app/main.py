from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import llm
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.config import settings
from app.db import engine, redis
from app.models import Base
from app.sessions.router import router as sessions_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 启动时建表（已存在则跳过）。上线后第一次改表结构前，需要换成迁移工具。
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="A股对话式投研",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(chat_router)


@app.get("/api/health/live")
async def live() -> dict[str, str]:
    """进程存活检查，不访问任何依赖。"""
    return {"status": "ok"}


@app.get("/api/health")
async def health() -> dict:
    """逐项检查依赖。部署后访问这个接口，三项都是 ok 才算启动成功。"""
    result: dict[str, dict] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        result["database"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 健康检查要报告任何失败原因
        result["database"] = {"status": "error", "detail": str(exc)[:200]}

    try:
        await redis.ping()
        result["redis"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        result["redis"] = {"status": "error", "detail": str(exc)[:200]}

    try:
        models = await llm.list_models()
        result["llm"] = {
            "status": "ok",
            "models": models,
            "api_key_loaded": bool(settings.read_llm_api_key()),
        }
    except Exception as exc:  # noqa: BLE001
        result["llm"] = {
            "status": "error",
            "detail": str(exc)[:200] or type(exc).__name__,
            "api_key_loaded": bool(settings.read_llm_api_key()),
        }

    overall = "ok" if all(v["status"] == "ok" for v in result.values()) else "degraded"
    return {"status": overall, **result}
