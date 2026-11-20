"""新增自选股、站内提醒、每日 AI 报告三张表"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.create_table(
        "watch_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("alert_pct", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "code"),
    )
    op.create_index("ix_watch_items_user_id", "watch_items", ["user_id"])
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("url", sa.String(300), nullable=True),
        sa.Column("dedupe", sa.String(80), nullable=False),
        sa.Column("read", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "dedupe"),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])
    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("facts", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("date", "kind"),
    )
    op.create_index("ix_daily_reports_date", "daily_reports", ["date"])


def downgrade() -> None:
    op.drop_table("daily_reports")
    op.drop_table("alerts")
    op.drop_table("watch_items")
