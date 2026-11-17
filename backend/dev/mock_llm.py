"""本地开发用的假模型服务：模拟 OpenAI 兼容接口的流式输出。只在本地开发时使用。

行为尽量贴近真实模型：默认先输出思考内容和 </think>；带 tools 时会按问题里的关键词发起工具调用，
拿到工具结果后再作答。

启动：uvicorn mock_llm:app --app-dir backend/dev --port 8001
然后让后端的 LLM_BASE_URL 指向 http://127.0.0.1:8001/v1
"""

import asyncio
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

REPLY = """这是**本地假模型**的回复，用来验证流式输出和页面排版。

你刚才的问题是：「{question}」

| 指标 | 数值 | 说明 |
|---|---|---|
| 示例一 | 12.3 | 仅为排版演示 |
| 示例二 | 45.6 | 不是真实数据 |

要点：

1. 文字应当逐步出现，而不是整段一次显示。
2. 表格、列表、`行内代码` 都应正常渲染。
"""

PERIODS = {"月": "monthly", "周": "weekly", "60分": "60min", "30分": "30min", "15分": "15min", "5分": "5min", "1分": "1min"}


def _pick_tool(question: str) -> dict | None:
    """按关键词决定调用哪个工具；股票取问题里的 6 位代码，没有就用茅台。"""
    code = re.search(r"\d{6}", question)
    symbol = code.group() if code else "贵州茅台"
    if "K线" in question.upper() or "走势" in question:
        period = next((v for k, v in PERIODS.items() if k in question), "daily")
        return {"name": "get_kline", "arguments": json.dumps({"symbol": symbol, "period": period})}
    if "财报" in question or "财务" in question:
        return {"name": "get_financials", "arguments": json.dumps({"symbol": symbol})}
    if "新闻" in question or "政策" in question:
        if code or "茅台" in question:
            return {"name": "get_stock_news", "arguments": json.dumps({"symbol": symbol})}
        return {"name": "get_market_news", "arguments": json.dumps({})}
    if "股价" in question or "行情" in question:
        return {"name": "get_stock_quote", "arguments": json.dumps({"symbol": symbol})}
    return None


def _chunk(delta: dict, finish: str | None = None) -> str:
    return f"data: {json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}, ensure_ascii=False)}\n\n"


@app.get("/v1/models")
async def models() -> dict:
    return {"data": [{"id": "mock-model"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> StreamingResponse:
    body = await request.json()
    last = body["messages"][-1]
    thinking = (body.get("chat_template_kwargs") or {}).get("enable_thinking", True)
    tool = _pick_tool(last["content"]) if body.get("tools") and last["role"] == "user" else None

    if last["role"] == "tool":
        tool_text = "\n\n".join(m["content"] for m in body["messages"] if m["role"] == "tool")
        text = f"以下是工具返回的数据（假模型原样转述）：\n\n{tool_text}"
    else:
        text = REPLY.format(question=last["content"])
    if tool:
        text = ""
    # 模仿真实模型：除非明确关闭思考，否则先输出思考内容和结束标记（没有起始标记）
    if thinking:
        text = "用户在提问。我需要用中文回答。\n</think>\n\n" + text

    async def gen():
        await asyncio.sleep(0.4)
        for i in range(0, len(text), 4):
            yield _chunk({"content": text[i : i + 4]})
            await asyncio.sleep(0.02)
        if tool:
            # 真实模型也是这样：名称只在第一段，参数分几段到达
            args = tool["arguments"]
            yield _chunk({"tool_calls": [{"id": "call-mock-1", "type": "function", "index": 0, "function": {"name": tool["name"], "arguments": ""}}]})
            for i in range(0, len(args), 7):
                yield _chunk({"tool_calls": [{"id": "call-mock-1", "type": "function", "index": 0, "function": {"name": None, "arguments": args[i : i + 7]}}]})
            yield _chunk({"content": ""}, "tool_calls")
        else:
            yield _chunk({"content": ""}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
