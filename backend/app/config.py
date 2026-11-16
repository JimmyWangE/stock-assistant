from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有配置都来自环境变量，默认值对应 docker-compose.yml 里的服务名。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://finance:finance@db:5432/finance"
    redis_url: str = "redis://redis:6379/0"

    # 登录凭证的签名密钥。留空时每次启动随机生成，重启后所有人需重新登录。
    secret_key: str = ""
    login_days: int = 7

    # 自研模型：OpenAI 兼容接口
    llm_base_url: str = ""  # 必须通过环境变量 LLM_BASE_URL 提供
    llm_api_key_file: str = "/run/secrets/llm_api_key"
    llm_model: str = ""  # 留空则启动后从 /v1/models 取第一个
    llm_max_concurrency: int = 200
    # 每次提问带给模型的最近消息条数（模型上下文长度未知，先保守截断）
    llm_history_messages: int = 20

    def read_llm_api_key(self) -> str:
        """每次调用时读文件，密钥轮换后无需重启。读不到返回空串。"""
        path = Path(self.llm_api_key_file)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()


settings = Settings()
