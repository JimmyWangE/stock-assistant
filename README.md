# A股对话式投研

内部团队使用的 A 股对话式投研网页应用。需求、架构和进度见 [docs](docs/)。

当前阶段：已有注册登录、对话页（流式回答）、历史会话列表，以及行情查询和 K 线图（模型通过工具调用取数）。财报、新闻政策、条件选股的数据尚未接入。

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
  app/tools/        模型可调用的数据工具：行情、K 线（经 AkShare 取自新浪财经）
  app/export/       待实现：PDF 导出
  migrations/       数据库表结构的迁移文件，后端启动时自动执行
  dev/mock_llm.py   本地开发用的假模型服务
frontend/           Vue 3 + TypeScript 前端
deploy/             部署参考配置
.env.example        配置模板
docs/               项目总览、架构方案、进度记录
```

## 部署（服务器）

不使用 Docker。服务器上由 systemd 管理四个服务，均为本项目专用实例：

| 服务 | 作用 |
|---|---|
| `stock-assistant-backend` | 后端（uvicorn，仅监听本机） |
| `stock-assistant-nginx` | 对外提供网页，并把 `/api/` 转给后端 |
| `stock-assistant-postgres` | 数据库（仅监听本机） |
| `stock-assistant-redis` | 缓存（仅监听本机） |

具体目录、端口、模型服务地址、密钥路径都不写在仓库里，以服务器上的 `.env` 和服务单元文件为准。`.env` 各项含义见 [.env.example](.env.example)；服务单元和 nginx 配置的脱敏副本见 [deploy/](deploy/)。

### 更新代码

在项目目录下执行：

1. `git pull`
2. 后端依赖：`backend/.venv/bin/pip install -r backend/requirements.txt`
3. 前端构建：`cd frontend && npm ci && npm run build`
4. 重启后端：`systemctl restart stock-assistant-backend`（数据库表结构会在启动时自动升级到最新）
5. 验证：`curl -s http://localhost:<对外端口>/api/health`

只改了前端时可跳过第 2、4 步；只改了后端时可跳过第 3 步。

**成功的判定**：返回的 JSON 中 `status` 为 `ok`，且 `database`、`redis`、`llm` 三项的 `status` 都是 `ok`，`llm.api_key_loaded` 为 `true`，`llm.models` 列出了模型名。

**常见失败**

| 现象 | 原因与处理 |
|---|---|
| `llm.api_key_loaded` 为 `false` | `.env` 的 `LLM_API_KEY_FILE` 路径不对、文件为空，或后端进程的账户没有读权限 |
| `llm.status` 为 `error` 且提示 401 | 密钥不正确 |
| `llm.status` 为 `error` 且提示连接失败或超时 | 访问不到模型服务，用 `curl <LLM_BASE_URL>/models` 确认 |
| 回答不是逐字出现，而是等很久后整段显示 | nginx 没有关闭缓冲，对照 `deploy/nginx.conf.example` 检查 `proxy_buffering off` |
| 行情或 K 线问题回答"数据未获取" | 后端访问不到外网的行情数据源（新浪财经），检查服务器出网 |
| 网页打开是旧版本 | 前端没有重新构建，或 nginx 指向的不是 `frontend/dist` |

注意：不要把密钥内容写进 `.env`、日志或任何回复里，只通过文件路径引用。模型服务地址、密钥路径、`.env` 都不要提交。

## 本地开发

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
