import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings

_model_name = settings.llm_model


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


THINK_END = "</think>"


async def stream_chat(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """调用对话接口，逐段产出正文文本；思考内容不会产出。"""
    async for text in _strip_thinking(_raw_stream(messages), settings.llm_enable_thinking):
        yield text


async def _strip_thinking(chunks: AsyncIterator[str], thinking: bool) -> AsyncIterator[str]:
    """去掉思考内容。

    这个模型开启思考时，输出是"思考内容 + </think> + 正文"，开头没有起始标记，
    所以 </think> 之前的一切都是思考。标记可能被切在两段之间，要攒起来再找。
    """
    if not thinking:
        async for text in chunks:
            yield text
        return

    buffer = ""
    answering = False  # 已经越过结束标记
    started = False  # 正文已经出了第一个非空白字符
    async for text in chunks:
        if not answering:
            buffer += text
            if THINK_END not in buffer:
                continue
            answering = True
            text = buffer.split(THINK_END, 1)[1]
        if not started:
            # 结束标记后面跟着几个换行，去掉，免得正文开头空一截
            text = text.lstrip()
            if not text:
                continue
            started = True
        yield text
    # 整段输出都没出现结束标记：说明模型这次没按思考格式输出，把内容当正文交出去，避免回答丢失
    if not answering and buffer:
        yield buffer


async def _raw_stream(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """调用 OpenAI 兼容的对话接口，逐段产出模型原始输出。"""
    payload = {
        "model": await resolve_model(),
        "messages": messages,
        "stream": True,
        # 模型服务（vLLM）的扩展参数：控制是否先思考
        "chat_template_kwargs": {"enable_thinking": settings.llm_enable_thinking},
    }
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
                text = (choices[0].get("delta") or {}).get("content")
                if text:
                    yield text
