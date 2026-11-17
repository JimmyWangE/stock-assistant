import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, User, now
from app.security import current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["历史会话"])


class ConversationOut(BaseModel):
    id: str
    title: str
    updated_at: datetime


class MessageOut(BaseModel):
    role: str
    content: str
    blocks: list[dict] | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)


def expiry_cutoff() -> datetime:
    """最后一次对话早于这个时刻的会话视为已过期（验收 C6）。"""
    return now() - timedelta(days=settings.conversation_keep_days)


def _as_utc(value: datetime) -> datetime:
    # SQLite 读出来的时间不带时区，统一按 UTC 处理后才能比较
    return value if value.tzinfo else value.replace(tzinfo=now().tzinfo)


async def get_owned_conversation(db: AsyncSession, conversation_id: str, user: User) -> Conversation:
    """按 id 取会话并校验归属。所有按 id 访问会话的地方都必须走这里（验收 A3）。"""
    conversation = await db.get(Conversation, conversation_id)
    # 过期会话由后台定时清理，清理前也当作不存在，这样"过期即消失"不依赖清理何时运行
    if conversation is None or _as_utc(conversation.updated_at) < expiry_cutoff():
        raise HTTPException(status_code=404, detail="会话不存在")
    if conversation.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(q: str = "", user: User = Depends(current_user)) -> list[Conversation]:
    """列出当前用户的会话。带 q 时只返回标题或任一条消息正文含该词的会话（验收 C2）。"""
    query = select(Conversation).where(
        Conversation.user_id == user.id, Conversation.updated_at >= expiry_cutoff()
    )
    keyword = q.strip()[:100]
    if keyword:
        # % 和 _ 在 LIKE 里是通配符，用户输入的要按字面匹配
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        in_messages = select(Message.conversation_id).where(
            Message.content.ilike(pattern, escape="\\")
        )
        query = query.where(
            or_(Conversation.title.ilike(pattern, escape="\\"), Conversation.id.in_(in_messages))
        )
    async with SessionLocal() as db:
        rows = await db.scalars(query.order_by(Conversation.updated_at.desc()))
        return list(rows)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, user: User = Depends(current_user)) -> dict:
    async with SessionLocal() as db:
        conversation = await get_owned_conversation(db, conversation_id, user)
        messages = await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id)
        )
        return {
            "id": conversation.id,
            "title": conversation.title,
            "updated_at": conversation.updated_at,
            "messages": list(messages),
        }


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: str, body: RenameIn, user: User = Depends(current_user)
) -> Conversation:
    """重命名会话（验收 C3）。不改最后对话时间，重命名不应推迟过期。"""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="名称不能为空")
    async with SessionLocal() as db:
        conversation = await get_owned_conversation(db, conversation_id, user)
        conversation.title = title
        await db.commit()
        await db.refresh(conversation)
        return conversation


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, user: User = Depends(current_user)) -> Response:
    """删除会话及其全部消息（验收 C4）。"""
    async with SessionLocal() as db:
        conversation = await get_owned_conversation(db, conversation_id, user)
        await _delete_conversations(db, [conversation.id])
        await db.commit()
    return Response(status_code=204)


async def _delete_conversations(db: AsyncSession, ids: list[str]) -> None:
    # 显式先删消息：不依赖数据库的级联设置（本地 SQLite 默认不启用外键级联）
    await db.execute(delete(Message).where(Message.conversation_id.in_(ids)))
    await db.execute(delete(Conversation).where(Conversation.id.in_(ids)))


async def purge_expired() -> int:
    """删除所有过期会话，返回删除的个数。"""
    async with SessionLocal() as db:
        ids = list(
            await db.scalars(select(Conversation.id).where(Conversation.updated_at < expiry_cutoff()))
        )
        # 分批删，避免一条语句带上万个 id
        for start in range(0, len(ids), 500):
            await _delete_conversations(db, ids[start : start + 500])
        await db.commit()
        return len(ids)


async def keep_purging_expired() -> None:
    """后台任务：启动时清理一次，之后每小时一次。"""
    while True:
        try:
            removed = await purge_expired()
            if removed:
                logger.info("已清理 %d 个过期会话", removed)
        except Exception:  # noqa: BLE001 清理失败不能影响服务，下一轮再试
            logger.exception("清理过期会话失败")
        await asyncio.sleep(3600)
