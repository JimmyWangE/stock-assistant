from fastapi import FastAPI
from sqlalchemy import text

from app import llm
from app.config import settings
from app.db import engine, redis

app = FastAPI(title="A股对话式投研", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.get("/api/health/live")
async def live() -> dict[str, str]:
    """进程存活检查，供容器健康检查使用，不访问任何依赖。"""
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
