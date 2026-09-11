# Telegram IFTTT

Self-hosted Telegram workflow automation for ordinary user accounts and Bot API integrations.

把 Telegram 动作连成一条可靠的线：发送消息、等待回复、点击按钮、条件分支——全部通过可视化画布编排，运行时自动等待 bot 响应并写入 SQLite 检查点，服务重启后从断点继续。

---

## 快速开始

### 1. 准备配置文件

```bash
cp .env.example .env
```

编辑 `.env`，**必须填写以下四项**：

```bash
# ┌─────────────────────────────────────────────────────┐
# │                    必填项                             │
# └─────────────────────────────────────────────────────┘

# 适配器类型：普通用户账号用 mtproto，Bot 用 bot_api
TG_IFTTT_ADAPTER=mtproto

# Telegram API ID，从 https://my.telegram.org 获取
TG_IFTTT_API_ID=

# Telegram API Hash，从 https://my.telegram.org 获取
TG_IFTTT_API_HASH=

# 管理令牌，用于访问 Web 控制台和 API
# 生成方式：python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# 如果值包含 $，在 .env 中用单引号包裹整个值
TG_IFTTT_ADMIN_TOKEN=
```

> **如何获取 API ID / API Hash？**
> 1. 访问 https://my.telegram.org 并登录你的 Telegram 账号
> 2. 点击「API development tools」
> 3. 填写应用名称（随意），提交后即可看到 `App api_id` 和 `App api_hash`

### 2. 启动服务

```bash
docker compose up -d
```

首次启动会自动拉取镜像。启动后：

| 服务 | 地址 | 说明 |
|------|------|------|
| Web 控制台 | `http://localhost:8080` | 可视化流程编辑器 |
| REST API | `http://localhost:8000` | 管理接口 |
| 健康检查 | `http://localhost:8000/api/health` | 无需认证 |

### 3. 登录 Telegram 账号

1. 打开 `http://localhost:8080`
2. 输入 `.env` 中的 `TG_IFTTT_ADMIN_TOKEN` 进入控制台
3. 在左侧导航点击「Telegram 账号」
4. 点击「添加账号」，选择登录方式：
   - **QR 扫码**：用 Telegram 手机端扫描二维码
   - **手机号验证码**：输入手机号 → 收到验证码 → 填入（如开启了两步验证，还需输入密码）

登录成功后，账号状态显示为 `ready`，即可在流程中选用。

---

## Web 控制台操作指南

### 流程编辑器

左侧导航「流程编辑器」是核心操作界面，交互方式类似 n8n / Node-RED：

- **添加节点**：从左侧节点库拖拽到画布，或点击节点库项在画布中心添加
- **连接节点**：拖拽节点右侧的手柄到下一个节点
- **编辑节点**：点击节点，在右侧检查器中配置参数
- **编辑连线**：点击连线，可设置分支条件
- **删除**：选中节点或连线后按 `Delete` / `Backspace`
- **缩放**：鼠标滚轮或 `-` / `+` 按钮；拖拽空白处平移画布
- **撤销/重做**：`⌘Z` / `⌘⇧Z`
- **保存**：`⌘S` 或点击右上角「保存版本」
- **运行**：`⌘↵` 或点击「手动运行」

### 可用节点类型

| 节点 | 说明 |
|------|------|
| 发送消息 | 向目标会话发送文本（如 `/start`） |
| 等待消息 | 按发送者和文本内容筛选等待新消息 |
| 点击按钮 | 自动匹配 Inline Keyboard 按钮并点击 |
| 回答回调 | Bot API callback query 应答 |
| 读取消息 | 获取目标会话最近消息快照 |
| 设置变量 | 写入安全表达式变量 |
| 条件分支 | 安全表达式判断，控制流程走向 |
| 延迟 | 等待指定秒数 |
| 结束 | 结束当前流程 |

### 流程配置

在画布顶部的元信息栏可以设置：

- **流程名称** / **流程 ID**：用于标识和管理
- **默认目标会话**：如 `@bot` 或数字 peer ID，节点可单独覆盖
- **执行账号**：从已登录的 Telegram 账号中选择
- **触发器**：手动触发、定时调度（每 N 天的固定时刻）、事件触发

### 运行记录

左侧导航「运行记录」显示每次流程执行的状态、检查点位置和错误信息。每个节点完成后写入 SQLite 检查点，服务重启后可从当前位置继续。

### 配置文件导入/导出

点击「配置文件」按钮可以 YAML / JSON 格式查看、编辑和导入导出流程。凭据、session 和 Bot Token 永远不会进入流程配置文件。

---

## .env 配置项说明

### 必填项

| 变量 | 说明 |
|------|------|
| `TG_IFTTT_ADAPTER` | 适配器类型：`mtproto`（普通用户账号）或 `bot_api`（Bot） |
| `TG_IFTTT_API_ID` | Telegram API ID，从 https://my.telegram.org 获取 |
| `TG_IFTTT_API_HASH` | Telegram API Hash，从 https://my.telegram.org 获取 |
| `TG_IFTTT_ADMIN_TOKEN` | 管理令牌，Web 控制台和 API 的访问密钥 |

### Bot API 模式

如果使用 Bot Token 而非普通用户账号：

```bash
TG_IFTTT_ADAPTER=bot_api
TG_IFTTT_BOT_TOKEN=123456:your-bot-token
```

> Bot Token 无法模拟用户点击键盘按钮。需要 `/start` 后点击按钮的流程必须使用 `mtproto` 适配器和已登录的普通用户账号。

### 可选项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TG_IFTTT_MASTER_KEY` | 无 | 32 字节密钥（64 位十六进制），设置后 session 加密存储 |
| `TG_IFTTT_API_BIND_PORT` | `8000` | API 服务端口 |
| `TG_IFTTT_UI_BIND_PORT` | `8080` | Web 控制台端口 |
| `TG_IFTTT_TIMEZONE` | `Asia/Shanghai` | 定时调度的时区 |
| `TG_IFTTT_RECOVERY_INTERVAL` | `15` | 恢复轮询间隔（秒） |
| `TG_IFTTT_SCHEDULER_INTERVAL` | `20` | 调度器轮询间隔（秒） |
| `TG_IFTTT_EVENT_POLL_INTERVAL` | `5` | 事件轮询间隔（秒） |
| `TG_IFTTT_WEBHOOK_SECRET` | 无 | 外部 Webhook 调用的独立密钥 |

### Node-RED（仅开发模式）

使用 `docker-compose-dev.yaml` 时可启用 Node-RED 兼容编辑器：

```bash
TG_IFTTT_NODERED_USER=admin
TG_IFTTT_NODERED_PASSWORD=your-password
TG_IFTTT_NODERED_BIND_PORT=1880
```

---

## 部署方式

### 生产部署（预构建镜像）

```bash
cp .env.example .env
# 编辑 .env 填写必填项
docker compose up -d
```

使用 Docker Hub 上的多架构镜像（amd64 / arm64），无需本地构建。

### 开发部署（本地构建 + Node-RED）

```bash
cp .env.example .env
# 编辑 .env 填写必填项
docker compose -f docker-compose-dev.yaml up -d --build
```

包含 Node-RED 兼容编辑器，访问 `http://localhost:8080/nodered/`。

### 单独运行 API

```bash
docker build -t tg-ifttt-api .
docker run --rm -p 8000:8000 --env-file .env -v tg_ifttt_data:/data tg-ifttt-api
```

### 更新服务

修改 `.env` 后需要重建容器使新配置生效：

```bash
docker compose up -d --force-recreate
```

---

## 开发

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
```

离线示例（不连接 Telegram）：

```bash
python3 -m tg_ifttt.cli.qinglong --config examples/config.yaml
```

构建并推送多架构 Docker 镜像：

```bash
./scripts/docker-publish.sh                          # amd64 + arm64，推送全部服务
./scripts/docker-publish.sh --platforms linux/amd64   # 单架构
./scripts/docker-publish.sh --tag v0.2.0             # 指定版本标签
./scripts/docker-publish.sh --dry-run                # 只构建不推送
```

---

## 安全须知

- **永远不要**将 `.env` 文件、Telegram session、Bot Token 或 API 密钥提交到仓库
- 将公网端口置于 HTTPS 反向代理之后
- `TG_IFTTT_MASTER_KEY` 设置后，已加密的 session 需要原始密钥才能解密；移除该变量只影响新 session
- 普通 session 是敏感凭据，请保护 SQLite 数据卷，不要暴露给其他用户
- 流程配置文件中只选择账号 ID，不包含任何凭据
