# KouriChat 改造为 OpenClaw 通道

> 任务时间: 2026-06-02
> 操作者: ClaudeCode (花水终的 AI 助手)

## 目标

将 KouriChat-OpenClaw 改造为通过 OpenClaw 运行的 QQ 聊天机器人：
1. **删除微信渠道** (wxauto)：KouriChat 之前用 `wxauto` 监听微信消息，改造后**完全删除**
2. **目标说话平台遵循 OpenClaw 配置**：QQ 通道走 OpenClaw 自带的 `@openclaw/qqbot` 插件（appId/secret 已在 `~/.openclaw/openclaw.json` 配好）
3. **模型请求从 OpenClaw 拿**：KouriChat 的 LLM 调用改为通过 `openclaw-sdk` (PyPI, 2.1.0) 走 OpenClaw gateway (`ws://127.0.0.1:18789`)

## 架构

**改造前 (微信模式)**
```
[微信]  <-->  wxauto  <-->  KouriChat.main  <-->  OpenAI API
              (本地)        (Python 主进程)       (DeepSeek/GPT/...)
```

**改造后 (OpenClaw QQ 模式，路 B)**
```
[QQ]  <-->  OpenClaw qqbot  <-->  OpenClaw gateway  <-->  KouriChat.bridge
                              (18789 WS)              (asyncio Python)
                                                          |
                                                          v
                                                       openclaw_sdk.Agent
                                                          |
                                                          v
                                                       MiniMax / 其它模型
```

KouriChat 不再是独立聊天前端，而是：
- 接收：通过 SDK 订阅 OpenClaw gateway 转发的 QQ 消息
- 处理：拼人设 prompt + 调 SDK Agent
- 发送：通过 SDK 调 OpenClaw 转发回 QQ
- 记忆/情绪/人设：保留 KouriChat 原有逻辑（base.md / worldview.md / memory_service.py）

## 改动文件清单

### 删除
- `src/Wechat_Login_Clicker/` — 整个目录（微信登录点击器，无用）
- `src/utils/cleanup.py` 中 `cleanup_wxauto_files` 方法（约 60 行）

### 大改
- `src/main.py` (815 行) — 删 `from wxauto import WeChat`、删 `WeChat()` 实例化、删主消息循环（基于 `listen_list` + `AddListenChat`）、删 `AutoSendHandler`，改为**调用 bridge 启动** OpenClaw SDK 事件循环
- `src/handlers/message.py` — 删 `self.wx = WeChat()`、删 `self.wx.SendMsg/SendFiles`、删微信专属字段；保留消息处理逻辑（拼 prompt、调 LLM、emoji/图片），**发送改为调 bridge.send_qq_message()**
- `src/services/ai/llm_service.py` — 把 `from openai import OpenAI` + `self.client = OpenAI(...)` 改为 `from openclaw_sdk import OpenClawClient` + `await OpenClawClient.connect()` + `client.get_agent("main")` + `agent.execute(message, context=...)`；`get_response` / `chat` 方法签名保留（main.py 那些调用方不动）
- `data/config/__init__.py` — `user.listen_list` 字段保留（兼容），但加 `user.openclaw` 配置段（gateway URL/token/agent_id）
- `requirements.txt` — 删 `wxautold`、删 `PyAutoGUI`、删 `uiautomation`，加 `openclaw-sdk>=2.1.0`

### 新建
- `src/openclaw_bridge.py` — 封装 OpenClaw SDK 调用：
  - `class OpenClawBridge`: 异步连接 gateway，启动 QQ 消息订阅
  - `on_qq_message(callback)`: 注册消息回调
  - `send_text(target_id, text)` / `send_image(target_id, path)`: 发送
  - `llm_chat(messages)`: 调 Agent 拿模型回复
- `PLAN.md` — 本文件

### 不动
- `data/avatars/*/avatar.md` — 人设文本（"微信"作为人设描述保留，**不改**）
- `src/base/base.md` `worldview.md` `group.md` `memory.md` — 基础 prompt
- `modules/memory/` — 记忆服务（核心逻辑，与渠道无关）
- `modules/reminder/` — 提醒服务（看下 wxauto 引用，可能要清）
- `src/services/ai/image_recognition_service.py` — 改基地址走 OpenClaw
- `src/services/ai/network_search_service.py` — 改基地址走 OpenClaw

## Git 规则

按 `AGENTS.md`：
- commit 格式: `feat: ClaudeCode: 中文描述`
- 每次改动后 push；push 失败先 commit 本地

## 启动 / 验证

KouriChat 改造后**不再独立启动 `python run.py` 接收 QQ 消息**——QQ 消息由 OpenClaw qqbot 插件收。KouriChat 是 OpenClaw 的"下游 processor"。

**验证步骤**：
1. OpenClaw gateway 已在跑（18789）— 确认
2. 启动 KouriChat bridge（`python run.py` → `main()` → `bridge.start()`）— 验证 bridge 成功连接到 gateway
3. 通过 OpenClaw 模拟 QQ 消息：本地用 `openclaw agent` 或直接 `openclaw cron` 跑一条测试消息，看 KouriChat bridge 是否收到 + 调通 LLM
4. 看 KouriChat `logs/bot.log` 和 `logs/users/*.log` 有没有**首条日志**出现（按 AGENTS.md "必须等待日志出现才能确认启动成功"）

## 风险

1. **大文件改动**：`main.py` 815 行 + `message.py` 600+ 行，删/改 ≈ 200 行
2. **OpenClaw SDK 是 2.1.0**（2026-02-28），新；API 可能与我读到的有出入
3. **KouriChat prompt 体系（base.md/worldview/memory）和 OpenClaw Agent 的 system prompt 怎么融合**——这是个我没完全想清楚的设计点。我**默认**做法：把人设 prompt 整体作为 `Agent.execute()` 的 `context.system_prompt` 传，**绕开** OpenClaw 自己的 system prompt
4. **Wxauto 引用漏删**：modules/reminder/、image_recognition 等地方可能也有引用，commit 前 grep 一遍

## 不在本次范围

- 改人设 prompt（base.md 等）
- 改记忆系统
- 改 WebUI（`run_config_web.py`）
- 改 autoupdate
