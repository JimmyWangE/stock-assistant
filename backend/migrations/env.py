"""Alembic 的运行入口：连接数据库并执行 versions/ 下尚未执行的迁移。"""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import Base


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


asyncio.run(_main())
