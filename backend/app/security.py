import base64
import hashlib
import secrets
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Cookie, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.models import User, now

COOKIE_NAME = "session"
_SECRET = settings.secret_key or secrets.token_hex(32)
_ALGORITHM = "HS256"


def _prepare(password: str) -> bytes:
    # bcrypt 只取前 72 字节，先做一次摘要，任意长度的密码都完整参与校验
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


async def hash_password(password: str) -> str:
    # bcrypt 故意算得慢，放到线程池里，避免卡住其他人的请求
    hashed = await run_in_threadpool(bcrypt.hashpw, _prepare(password), bcrypt.gensalt())
    return hashed.decode("ascii")


async def verify_password(password: str, password_hash: str) -> bool:
    return await run_in_threadpool(
        bcrypt.checkpw, _prepare(password), password_hash.encode("ascii")
    )


def set_login_cookie(response: Response, user_id: int) -> None:
    lifetime = timedelta(days=settings.login_days)
    token = jwt.encode({"sub": str(user_id), "exp": now() + lifetime}, _SECRET, _ALGORITHM)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,  # 页面脚本读不到，降低凭证被盗风险
        samesite="lax",
    )


def clear_login_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


async def current_user(token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> User:
    """所有需要登录的接口都依赖它；未登录或凭证失效一律 401。"""
    unauthorized = HTTPException(status_code=401, detail="请先登录")
    if not token:
        raise unauthorized
    try:
        user_id = int(jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user
