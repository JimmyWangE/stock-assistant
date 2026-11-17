import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import llm
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.config import settings
from app.db import engine, redis
from app.migrate import upgrade_database
from app.overview import keep_board_fresh, router as overview_router
from app.sessions.router import keep_purging_expired, router as sessions_router
from app.tools import market


# uvicorn 只配置了它自己的日志；不设这一行，本项目 INFO 级别的日志（如过期会话清理数量）不会输出
logging.getLogger("app").setLevel(logging.INFO)
if not logging.getLogger("app").handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    logging.getLogger("app").addHandler(_handler)
    logging.getLogger("app").propagate = False


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 启动时把数据库表结构升级到最新。迁移工具是同步的，放到线程里跑
    await asyncio.to_thread(upgrade_database)
    # 后台定期刷新行情工具要用的股票名称表，不阻塞启动
    refresher = asyncio.create_task(market.keep_stock_table_fresh())
    # 后台定期删除超过保留期的会话（验收 C6）
    purger = asyncio.create_task(keep_purging_expired())
    # 后台刷新页面上的市场看板
    board = asyncio.create_task(keep_board_fresh())
    logging.getLogger("app").info("后台任务已启动：股票名称表刷新、过期会话清理、市场看板")
    yield
    refresher.cancel()
    purger.cancel()
    board.cancel()


app = FastAPI(
    title="A股对话式投研",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(overview_router)


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
