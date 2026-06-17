# Jasper Telegram Bot

Jasper（狗蛋）的 Telegram bot，和小克/Lucien 共用同一套代码架构，部署在 Render 免费层。

## 特性

- **微信式短消息**：自动拆句逐条发送，像真人聊天
- **API 随时换**：中转站/模型/密钥全走环境变量，改完重启即生效
- **群聊支持**：@唤醒、回复唤醒、随机插嘴、点表情
- **多模态**：图片识别 + 语音转写
- **Gist 持久化**：聊天历史备份到 GitHub Gist
- **Memory Hub 集成**：长期记忆由 Memory Hub 统一管理（自动注入 + 自动提取）
- **跨聊天感知**：私聊/小群/大群之间的记忆互通，带隐私分层保护
- **思维链清理**：自动过滤模型输出的 `<think>` 标签，防止泄露思维过程
- **表情动作系统**：bot 可以在回复中通过括号标签触发真实动作
  - 踢人：`（踢用户ID）` — bot 自主决定是否踢人，需要群管理员权限
  - 改签名：`（签名:内容）` — bot 随时可以根据心情更新自己的 Telegram 签名
  - 标签会被自动隐藏，用户只看到正常回复
  - bot 不会对主人使用踢人功能（CECI_ID 保护）
- **自动摘要**：对话历史过长时自动生成摘要压缩
- **诊断命令**：`/testadmin` 检查 bot 管理员权限，`/checkuser ID` 查看用户身份

## 部署（Render）

1. 推送代码到 GitHub 仓库 `Jasper-telegrambot`
2. Render → New → Web Service → 连接仓库 → Docker → 免费套餐
3. 设置环境变量（见下方）
4. 设置 Webhook：`https://api.telegram.org/bot{TOKEN}/setWebhook?url=https://{RENDER_URL}/webhook`
5. （可选）UptimeRobot 每 5 分钟 ping `/health` 防休眠

## 环境变量

### 必填
| 变量 | 说明 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `BOT_NAME` | Jasper |
| `BOT_USERNAME` | Bot 的 @username |
| `CLAUDE_BASE_URL` | AI API 地址（中转站） |
| `CLAUDE_API_KEY` | AI API 密钥 |
| `CLAUDE_MODEL` | 模型名称 |
| `PROMPT_RULES` | Jasper 的人设 prompt |

### Memory Hub
| 变量 | 说明 |
|------|------|
| `MEMORY_HUB_URL` | `http://172.245.180.158:8888` |
| `MEMORY_HUB_SECRET` | Hub 密码 |
| `AI_ID` | `jasper` |
| `MEMORY_NOTIFY` | `true`（私聊显示记忆注入通知，8秒后自动删除） |

### 可选
| 变量 | 说明 |
|------|------|
| `API_FORMAT` | `openai` 或 `anthropic`，默认 openai |
| `GIST_ID` | GitHub Gist ID（聊天历史持久化） |
| `GIST_TOKEN` | GitHub Token |
| `VISION_MODEL` | 图片识别模型 |

## 架构

```
用户消息 → bot.py webhook
  ├─ load_history()：从 Gist 恢复聊天历史
  ├─ hub_get_context()：从 Memory Hub 获取走廊 + 相关记忆
  ├─ build_cross_chat_context()：跨聊天上下文（隐私分层）
  ├─ call_claude()：组装 prompt → 调用 AI API
  ├─ 清理思维链（<think> 标签）
  ├─ parse_and_execute_actions()：解析动作标签（踢人/改签名）并执行
  ├─ hub_post_process()：自动提取新记忆存入 Memory Hub
  └─ save_history()：保存聊天历史到 Gist（超长时硬截断）
```

## 和其他 bot 的关系

三个 bot（小克/Lucien/Jasper）代码架构相同，各自独立部署在 Render，通过环境变量区分角色和人设。共享同一个 Memory Hub 实例，记忆互通。
