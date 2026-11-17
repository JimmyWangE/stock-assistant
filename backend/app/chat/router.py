import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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
from app.tools.registry import STATUS, TOOLS, run_tool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["对话"])

SYSTEM_PROMPT = """你是面向内部投研团队的 A 股投研助手，用简体中文回答，表达专业、简洁，适合时用 Markdown 表格和列表。

数据规则：
- 涉及股价、涨跌幅、成交、K 线、走势、财务数据、新闻、政策时，必须先调用工具取数，不得凭记忆给出数字或新闻。
- 引用工具数据时，写明数据时间，照工具给出的原样写（有秒就保留到秒）。
- 工具结果末尾给出的来源链接，原样写在回答末尾，不要改写来源名称，也不要自己拼链接。
- 只要问题里出现了具体股票并且问的是价格或走势，哪怕问题很短（如"比亚迪的股价"），也要调用工具。
- K 线图和财务指标表由系统自动展示在回答上方，不要用文字画图，也不要完整复述图表里的数据，重点做解读。
- 引用新闻、政策时逐条附上工具给出的原文链接和发布时间；工具没有返回的不得提及。
- 问到政策时用 get_policy 取官方原文；同时问政策和新闻时，两个工具都调用，回答里把官方发布和媒体报道分开写。官方发布只有标题，不得臆测条款内容。
- 分析个股时可以组合多个工具（行情、财务、新闻），但只取回答问题真正需要的数据。
- 工具返回"数据未获取"时，如实告诉用户哪些数据没有取到，再基于已有信息作答，不得编造。
- 条件选股（按指标筛选股票）的工具尚未接入：遇到这类问题，说明暂时无法筛选，不得编造股票名单。"""

# 一次回答里最多让模型调用几轮工具，防止模型反复调用停不下来
MAX_TOOL_ROUNDS = 4
SHANGHAI = ZoneInfo("Asia/Shanghai")

# 模型并发闸门（验收 B10）。目前后端是单进程，用进程内信号量即可；
# 将来若启动多个后端进程，需要换成 Redis 计数。
_gate = asyncio.Semaphore(settings.llm_max_concurrency)
# 持有后台保存任务的引用，防止任务没跑完就被回收
_background: set[asyncio.Task] = set()


class ChatIn(BaseModel):
    conversation_id: str | None = None
    content: str = Field(min_length=1, max_length=4000)


def _fit_history(newest_first: list[Message]) -> list[dict[str, str]]:
    """从最新的消息往前取，直到用完上下文预算；返回按时间正序排列的消息。

    模型上下文有限，超出会被模型服务直接拒绝。这里把 1 个字符按 1 个 token 估算：
    中文实际约 0.6–1 个 token，英文更少，所以这个估算只会偏保守，不会超限。
    """
    budget = (
        settings.llm_context_tokens
        - settings.llm_reserved_output_tokens
        - settings.llm_reserved_tool_tokens
        - len(SYSTEM_PROMPT)
    )
    kept: list[dict[str, str]] = []
    for message in newest_first:
        budget -= len(message.content)
        # 最新一条（用户刚提的问题）无论多长都要带上
        if budget < 0 and kept:
            break
        kept.append({"role": message.role, "content": message.content})
    return kept[::-1]


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _save_reply(conversation_id: str, content: str, blocks: list[dict]) -> None:
    async with SessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            # 回答还没生成完，用户就把会话删了：不再保存
            return
        db.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                blocks=blocks or None,
            )
        )
        conversation.updated_at = now()
        await db.commit()


async def _stream(
    conversation_id: str, title: str, messages: list[dict[str, Any]]
) -> AsyncIterator[str]:
    # 先把会话信息和状态发出去，用户 1 秒内就能看到反馈（验收 B1），不必等模型
    yield _event("meta", {"conversation_id": conversation_id, "title": title})
    queued = _gate.locked()
    yield _event("status", {"text": "当前提问人数较多，正在排队…" if queued else "正在思考…"})

    parts: list[str] = []
    blocks: list[dict] = []
    try:
        async with _gate:
            if queued:
                yield _event("status", {"text": "正在思考…"})

            for round_no in range(MAX_TOOL_ROUNDS + 1):
                # 最后一轮不再提供工具，逼模型用已有数据给出回答
                tools = TOOLS if round_no < MAX_TOOL_ROUNDS else None
                round_text: list[str] = []
                calls: list[dict[str, str]] = []
                async for kind, value in llm.stream_chat(messages, tools):
                    if kind == "text":
                        round_text.append(value)
                        parts.append(value)
                        yield _event("delta", {"text": value})
                    else:
                        calls = value
                if not calls:
                    break

                # 把模型的调用请求和每个工具的结果依次接到对话后面，再让模型继续
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(round_text),
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {"name": call["name"], "arguments": call["arguments"]},
                            }
                            for call in calls
                        ],
                    }
                )
                for call in calls:
                    yield _event("status", {"text": STATUS.get(call["name"], "正在查询数据…")})
                    result = await run_tool(call["name"], call["arguments"])
                    for block in result.blocks:
                        blocks.append(block)
                        yield _event("block", block)
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": result.text}
                    )
                yield _event("status", {"text": "正在整理回答…"})
        yield _event("done", {})
    except Exception:  # noqa: BLE001 任何失败都要以事件形式告诉前端，而不是断流
        logger.exception("模型调用失败")
        yield _event("error", {"message": "模型服务暂时不可用，请稍后重试"})
    finally:
        # 用户中途停止或断开时也保留已生成的部分；放进独立任务，不受本次请求取消的影响
        if parts or blocks:
            task = asyncio.create_task(_save_reply(conversation_id, "".join(parts), blocks))
            _background.add(task)
            task.add_done_callback(_background.discard)


@router.post("")
async def chat(body: ChatIn, user: User = Depends(current_user)) -> StreamingResponse:
    """提问并以事件流返回回答。事件：meta、status、delta、block、done、error。"""
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
            .limit(40)
        )
        history = _fit_history(list(recent))
        conversation_id, title = conversation.id, conversation.title

    # 模型不知道今天是哪天，而"最近""今天"这类问题需要它知道
    clock = f"当前时间：{datetime.now(SHANGHAI):%Y-%m-%d %H:%M}（北京时间）。"
    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{clock}"}, *history]
    return StreamingResponse(
        _stream(conversation_id, title, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
