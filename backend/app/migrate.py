from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def upgrade_database() -> None:
    """把数据库表结构升级到最新版本。已是最新时什么都不做。"""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, "head")
