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


async def stream_chat(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """调用 OpenAI 兼容的对话接口，逐段产出正文文本。"""
    payload = {"model": await resolve_model(), "messages": messages, "stream": True}
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
