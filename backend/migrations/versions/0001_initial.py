"""用户、会话、消息三张表"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    # 引入迁移工具之前，这三张表是由程序启动时直接创建的。已有的库里表已存在，跳过即可。
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("username", sa.String(32), nullable=False),
            sa.Column("password_hash", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    if "conversations" not in existing:
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
        op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])

    if "messages" not in existing:
        op.create_table(
            "messages",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "conversation_id",
                sa.String(32),
                sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("users")
