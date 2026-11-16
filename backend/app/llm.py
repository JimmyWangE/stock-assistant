import httpx

from app.config import settings


def _headers() -> dict[str, str]:
    key = settings.read_llm_api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


async def list_models() -> list[str]:
    """返回模型服务上可用的模型名，用于健康检查和自动发现模型名。"""
    async with httpx.AsyncClient(base_url=settings.llm_base_url, timeout=5) as client:
        resp = await client.get("/models", headers=_headers())
        resp.raise_for_status()
        return [m["id"] for m in resp.json().get("data", [])]
