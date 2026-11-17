import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings

_model_name = settings.llm_model

THINK_END = "</think>"


def _headers() -> dict[str, str]:
    key = settings.read_llm_api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


async def list_models() -> list[str]:
    """返回模型服务上可用的模型名，用于健康检查和自动发现模型名。"""
    async with httpx.AsyncClient(base_url=settings.llm_base_url, timeout=5) as client:
        resp = await client.get("/models", headers=_headers())
        resp.raise_for_status()
        return [m["id"] for m in resp.json().get("data", [])]


async def resolve_model() -> str:
    """配置里没写模型名时，取模型服务返回的第一个，并记住。"""
    global _model_name
    if not _model_name:
        models = await list_models()
        if not models:
            raise RuntimeError("模型服务没有返回任何可用模型")
        _model_name = models[0]
    return _model_name


class ThinkingFilter:
    """去掉思考内容。

    这个模型开启思考时，输出是"思考内容 + </think> + 正文"，开头没有起始标记，
    所以 </think> 之前的一切都是思考。标记可能被切在两段之间，要攒起来再找。
    """

    def __init__(self, thinking: bool) -> None:
        self._answering = not thinking  # 已经越过结束标记（没开思考则一开始就是正文）
        self._started = not thinking  # 正文已经出了第一个非空白字符
        self._buffer = ""

    def feed(self, text: str) -> str:
        if not self._answering:
            self._buffer += text
            if THINK_END not in self._buffer:
                return ""
            self._answering = True
            text = self._buffer.split(THINK_END, 1)[1]
            self._buffer = ""
        if not self._started:
            # 结束标记后面跟着几个换行，去掉，免得正文开头空一截
            text = text.lstrip()
            self._started = bool(text)
        return text

    def flush(self) -> str:
        """输出结束时调用。整段都没出现结束标记，说明模型这次没按思考格式输出，把内容当正文交出去。"""
        text, self._buffer = self._buffer, ""
        return "" if self._answering else text


async def stream_chat(
    messages: list[dict[str, Any]], tools: list[dict] | None = None
) -> AsyncIterator[tuple[str, Any]]:
    """调用 OpenAI 兼容的对话接口。

    逐个产出 ("text", 一段正文)；如果模型决定调用工具，最后再产出一次
    ("tool_calls", [{"id", "name", "arguments"}, ...])，arguments 是 JSON 字符串。
    """
    payload: dict[str, Any] = {
        "model": await resolve_model(),
        "messages": messages,
        "stream": True,
        "temperature": settings.llm_temperature,
        # 模型服务（vLLM）的扩展参数：控制是否先思考
        "chat_template_kwargs": {"enable_thinking": settings.llm_enable_thinking},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    thinking = ThinkingFilter(settings.llm_enable_thinking)
    calls: dict[int, dict[str, str]] = {}
    # 首字可能要等一会儿，读超时放宽；连接超时保持短，服务不可达时尽快报错
    timeout = httpx.Timeout(connect=5, read=120, write=10, pool=5)
    async with httpx.AsyncClient(base_url=settings.llm_base_url, timeout=timeout) as client:
        async with client.stream(
            "POST", "/chat/completions", json=payload, headers=_headers()
        ) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                choices = json.loads(data).get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    text = thinking.feed(delta["content"])
                    if text:
                        yield "text", text
                # 工具调用的名称只在第一段出现，参数分多段到达，按序号拼起来
                for part in delta.get("tool_calls") or []:
                    call = calls.setdefault(part.get("index", 0), {"id": "", "name": "", "arguments": ""})
                    fn = part.get("function") or {}
                    call["id"] = part.get("id") or call["id"]
                    call["name"] = fn.get("name") or call["name"]
                    call["arguments"] += fn.get("arguments") or ""

    rest = thinking.flush()
    if rest:
        yield "text", rest
    if calls:
        yield "tool_calls", [calls[i] for i in sorted(calls) if calls[i]["name"]]
