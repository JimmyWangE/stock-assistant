from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Conversation, Message, User
from app.security import current_user

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


async def get_owned_conversation(db: AsyncSession, conversation_id: str, user: User) -> Conversation:
    """按 id 取会话并校验归属。所有按 id 访问会话的地方都必须走这里（验收 A3）。"""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conversation.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: User = Depends(current_user)) -> list[Conversation]:
    async with SessionLocal() as db:
        rows = await db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        )
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
