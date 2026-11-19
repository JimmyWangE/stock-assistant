"""新增 screen_data 表：保存条件选股用的财务数据和技术指标快照，重启后不必重新抓取"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "screen_data",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("screen_data")
