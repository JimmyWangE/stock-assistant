"""消息表增加 blocks 列：保存随回答展示的图表数据"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.add_column("messages", sa.Column("blocks", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "blocks")
