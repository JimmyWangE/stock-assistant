import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import llm
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, User, now
from app.security import current_user
from app.sessions.router import get_owned_conversation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["对话"])

SYSTEM_PROMPT = (
    "你是面向内部投研团队的 A 股投研助手，用简体中文回答，表达专业、简洁，适合时用 Markdown 表格和列表。"
    "当前系统尚未接入行情、财报和新闻数据源：涉及具体的最新股价、财务数字或当日新闻时，"
    "必须明确说明暂时无法获取实时数据，不得编造数字。"
)

# 模型并发闸门（验收 B10）。目前后端是单进程，用进程内信号量即可；
# 将来若启动多个后端进程，需要换成 Redis 计数。
_gate = asyncio.Semaphore(settings.llm_max_concurrency)
# 持有后台保存任务的引用，防止任务没跑完就被回收
_background: set[asyncio.Task] = set()


class ChatIn(BaseModel):
    conversation_id: str | None = None
    content: str = Field(min_length=1, max_length=8000)


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _save_reply(conversation_id: str, content: str) -> None:
    async with SessionLocal() as db:
        db.add(Message(conversation_id=conversation_id, role="assistant", content=content))
        conversation = await db.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = now()
        await db.commit()


async def _stream(
    conversation_id: str, title: str, messages: list[dict[str, str]]
) -> AsyncIterator[str]:
    # 先把会话信息和状态发出去，用户 1 秒内就能看到反馈（验收 B1），不必等模型
    yield _event("meta", {"conversation_id": conversation_id, "title": title})
    queued = _gate.locked()
    yield _event("status", {"text": "当前提问人数较多，正在排队…" if queued else "正在思考…"})

    parts: list[str] = []
    try:
        async with _gate:
            if queued:
                yield _event("status", {"text": "正在思考…"})
            async for text in llm.stream_chat(messages):
                parts.append(text)
                yield _event("delta", {"text": text})
        yield _event("done", {})
    except Exception:  # noqa: BLE001 任何失败都要以事件形式告诉前端，而不是断流
        logger.exception("模型调用失败")
        yield _event("error", {"message": "模型服务暂时不可用，请稍后重试"})
    finally:
        # 用户中途停止或断开时也保留已生成的部分；放进独立任务，不受本次请求取消的影响
        if parts:
            task = asyncio.create_task(_save_reply(conversation_id, "".join(parts)))
            _background.add(task)
            task.add_done_callback(_background.discard)


@router.post("")
async def chat(body: ChatIn, user: User = Depends(current_user)) -> StreamingResponse:
    """提问并以事件流返回回答。事件：meta、status、delta、done、error。"""
    content = body.content.strip()
    async with SessionLocal() as db:
        if body.conversation_id:
            conversation = await get_owned_conversation(db, body.conversation_id, user)
            conversation.updated_at = now()
        else:
            conversation = Conversation(user_id=user.id, title=content[:30])
            db.add(conversation)
            await db.flush()
        db.add(Message(conversation_id=conversation.id, role="user", content=content))
        await db.commit()

        recent = await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.desc())
            .limit(settings.llm_history_messages)
        )
        history = [{"role": m.role, "content": m.content} for m in reversed(list(recent))]
        conversation_id, title = conversation.id, conversation.title

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    return StreamingResponse(
        _stream(conversation_id, title, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
