from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import User
from app.security import (
    clear_login_cookie,
    current_user,
    hash_password,
    set_login_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["账号"])


class Credentials(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str


@router.post("/register", response_model=UserOut)
async def register(body: Credentials, response: Response) -> User:
    """自行注册，不限制邮箱域名、邀请码或审核（验收 A2）。注册成功即视为已登录。"""
    username = body.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="用户名至少 2 个字符")
    user = User(username=username, password_hash=await hash_password(body.password))
    async with SessionLocal() as db:
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="用户名已被使用") from None
    set_login_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
async def login(body: Credentials, response: Response) -> User:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == body.username.strip()))
    # 用户不存在和密码错误给同一个提示，不泄露哪些用户名已注册
    if user is None or not await verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    set_login_cookie(response, user.id)
    return user


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_login_cookie(response)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user
