from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """改动任何表结构后，都要在 migrations/versions/ 里加一个迁移文件。"""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Conversation(Base):
    __tablename__ = "conversations"

    # 会话 id 会出现在网址里，用随机串而不是自增数字，避免被逐个猜测
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # 最后一次对话时间：列表排序用，也是"满一个月自动删除"的起算点
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    # 随回答展示的图表、表格的原始数据。存数据而不是图片：重开会话时按原样重画，即生成时的快照
    blocks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ScreenData(Base):
    """条件选股的数据快照。每类数据一行（financials、technicals），payload 为整份数据。"""

    __tablename__ = "screen_data"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WatchItem(Base):
    """自选股。alert_pct 为涨跌幅提醒阈值（%），涨或跌超过它时提醒一次。"""

    __tablename__ = "watch_items"
    __table_args__ = (UniqueConstraint("user_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(6))
    name: Mapped[str] = mapped_column(String(32))
    alert_pct: Mapped[float] = mapped_column(Float, default=5.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Alert(Base):
    """站内提醒。dedupe 是去重键（如 600519:up:2026-11-20），同一用户同一事件只提醒一次。"""

    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("user_id", "dedupe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(6))
    name: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dedupe: Mapped[str] = mapped_column(String(80))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class DailyReport(Base):
    """每日 AI 报告：kind 为 morning（早报）或 close（收盘复盘）。全站共用，每天每类一份。"""

    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("date", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    content: Mapped[str] = mapped_column(Text)
    # 生成报告时交给模型的数据原文，便于核对报告里的数字
    facts: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
