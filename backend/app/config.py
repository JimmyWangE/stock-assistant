from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有配置都来自环境变量或工作目录下的 .env，各项含义见仓库根目录的 .env.example。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://finance:finance@127.0.0.1:5432/finance"
    redis_url: str = "redis://127.0.0.1:6379/0"

    # 登录凭证的签名密钥。留空时每次启动随机生成，重启后所有人需重新登录。
    secret_key: str = ""
    login_days: int = 7
    # 会话距最后一次对话超过这么多天就自动删除（验收 C6）
    conversation_keep_days: int = 30

    # 自研模型：OpenAI 兼容接口
    llm_base_url: str = ""  # 必须通过环境变量 LLM_BASE_URL 提供
    llm_api_key_file: str = ""
    llm_model: str = ""  # 留空则启动后从 /v1/models 取第一个
    llm_max_concurrency: int = 200
    # 采样温度。调低让模型更稳定：更少漏调工具、更少随意改写数据
    llm_temperature: float = 0.3
    # 是否让模型先思考再作答。开启时思考内容不展示给用户，但会占用上下文并推迟出字。
    llm_enable_thinking: bool = False
    # 模型服务的最大上下文长度（提问 + 回答的总 token 数），与模型服务的 max_model_len 一致
    llm_context_tokens: int = 8192
    # 为回答预留的 token 数；历史消息只能使用剩余部分
    llm_reserved_output_tokens: int = 2000
    # 为工具定义和工具返回的数据预留的 token 数
    llm_reserved_tool_tokens: int = 2500

    def read_llm_api_key(self) -> str:
        """每次调用时读文件，密钥轮换后无需重启。读不到返回空串。"""
        if not self.llm_api_key_file:
            return ""
        path = Path(self.llm_api_key_file)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()


settings = Settings()
