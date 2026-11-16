# A股对话式投研

内部团队使用的 A 股对话式投研网页应用。需求、架构和进度见 [docs](docs/)。

当前阶段：已有注册登录、对话页（流式回答）和历史会话列表。尚未接入行情、财报、新闻数据，模型暂时只凭自身知识回答。

## 目录

```
backend/            FastAPI 后端
  app/main.py       入口与健康检查
  app/models.py     数据表：用户、会话、消息
  app/security.py   密码哈希与登录凭证
  app/config.py     配置（全部来自环境变量）
  app/llm.py        模型服务客户端
  app/auth/         注册、登录
  app/chat/         流式对话、并发排队
  app/sessions/     历史会话
  app/{tools,export}/   待实现：数据工具、PDF 导出
  dev/mock_llm.py   本地开发用的假模型服务，不随镜像部署
frontend/           Vue 3 + TypeScript 前端，nginx 提供静态文件并转发 /api
docker-compose.yml  四个服务：db、redis、backend、web
.env.example        配置模板
docs/               项目总览、架构方案、进度记录
```

## 部署（服务器）

前提：Linux，已安装 Docker 和 Docker Compose 插件，能访问内网的模型服务，并知道模型服务地址和模型密钥文件在服务器上的路径（这两项不写在仓库里，由部署任务的下达方另行告知）。

1. 获取代码：首次 `git clone https://github.com/JimmyWangE/stock-assistant.git && cd stock-assistant`；之后更新用 `git pull`。
2. 生成配置（仅首次）：`cp .env.example .env`，在 `.env` 里填写四项必填值：`POSTGRES_PASSWORD`（随机串即可）、`SECRET_KEY`（用 `openssl rand -hex 32` 生成）、`LLM_BASE_URL`（模型服务地址，以 `/v1` 结尾）、`LLM_API_KEY_FILE`（密钥文件的绝对路径）。缺任何一项 `docker compose` 会直接报错并指出缺的是哪项。拉取依赖慢时，取消 `PIP_INDEX_URL`、`NPM_REGISTRY` 两行示例的注释。`.env` 不进仓库，`git pull` 不会覆盖它。
3. 构建并启动：`docker compose up -d --build`（更新代码后同样执行这一条）
4. 验证依赖：`curl -s http://localhost:8080/api/health`
5. 验证功能：浏览器打开 `http://<服务器地址>:8080`，注册一个账号，提一个问题，回答应逐字出现。

**启动成功的判定**：返回的 JSON 中 `status` 为 `ok`，且 `database`、`redis`、`llm` 三项的 `status` 都是 `ok`，`llm.api_key_loaded` 为 `true`，`llm.models` 列出了模型名。

**常见失败**

| 现象 | 原因与处理 |
|---|---|
| `docker compose up` 报 secret 文件不存在 | 密钥文件路径不对，在 `.env` 里改 `LLM_API_KEY_FILE` |
| `llm.api_key_loaded` 为 `false` | 密钥文件为空或容器内无法读取，检查文件内容和权限 |
| `llm.status` 为 `error` 且提示 401 | 密钥不正确 |
| `llm.status` 为 `error` 且提示连接失败或超时 | 容器内访问不到模型服务，在宿主机上用 `curl <LLM_BASE_URL>/models` 确认 |
| 8080 端口被占用 | 在 `.env` 里改 `WEB_PORT` |

注意：不要把密钥内容写进 `.env`、日志或任何回复里，只通过文件路径引用。本仓库是公开的，模型服务地址、密钥路径、`.env` 都不要提交。

## 本地开发（不用 Docker）

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd frontend && npm install && npm run dev
```

本机没有 PostgreSQL 和模型服务时，用 SQLite 和假模型代替，分别在两个终端启动：

```bash
cd backend && .venv/bin/uvicorn mock_llm:app --app-dir dev --port 8001
```

```bash
cd backend && DATABASE_URL=sqlite+aiosqlite:///./dev.db LLM_BASE_URL=http://127.0.0.1:8001/v1 .venv/bin/uvicorn app.main:app --reload
```

然后打开 `http://localhost:5173`。
