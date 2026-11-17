"""本地开发用的假模型服务：模拟 OpenAI 兼容接口的流式输出。只在本地开发时使用。

启动：uvicorn mock_llm:app --app-dir backend/dev --port 8001
然后让后端的 LLM_BASE_URL 指向 http://127.0.0.1:8001/v1
"""

import asyncio
import json

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


@app.get("/v1/models")
async def models() -> dict:
    return {"data": [{"id": "mock-model"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> StreamingResponse:
    body = await request.json()
    question = body["messages"][-1]["content"]
    text = REPLY.format(question=question)
    # 模仿真实模型：除非明确关闭思考，否则先输出思考内容和结束标记（没有起始标记）
    if (body.get("chat_template_kwargs") or {}).get("enable_thinking", True):
        text = "用户在提问。我需要用中文回答，并给出一个表格。\n</think>\n\n" + text

    async def gen():
        await asyncio.sleep(0.6)
        for i in range(0, len(text), 4):
            chunk = {"choices": [{"delta": {"content": text[i : i + 4]}}]}
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.03)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
